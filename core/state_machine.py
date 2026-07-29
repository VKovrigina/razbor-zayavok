from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from amo import actions as amo_actions
from classify import client as classify_client
from classify import faq as faq_client
from config import settings
from core import checklist, templates, timeutils
from db import repository as repo
from db.models import Channel, Deal, INACTIVE_STATUSES, ReplyCategory, Status
from email_channel import sender as email_sender
from telegram_channel import sender as telegram_sender

logger = logging.getLogger(__name__)

# Этапы CRM, на которых бот вправе слать напоминания об отсутствии ответа (см.
# process_scheduler_tick). Если сделку вручную перевели на любой другой этап — напоминания
# останавливаются (см. `_deal_in_reminder_eligible_stage`).
_REMINDER_ELIGIBLE_STAGE_IDS = {
    settings.amocrm_stage_negotiations_id,
    settings.amocrm_stage_silence_id,
    settings.amocrm_stage_clarification_id,
}

# Если сделка занята (напр. шедулер шлёт напоминание, ~15-90с) — не бросаем входящее сообщение
# сразу, а пробуем ещё несколько раз (см. handle_incoming_reply): P-009 в BACKLOG.md.
_LOCK_RETRY_INTERVAL_SECONDS = 15
_LOCK_RETRY_ATTEMPTS = 4  # ~60 секунд суммарного ожидания

# Шаги в handle_incoming_reply, которые обязаны либо зафиксироваться, либо явно разблокировать
# сделку (иначе она виснет заблокированной навсегда, см. P-008/P-038 в BACKLOG.md) — несколько
# попыток на случай мимолётной ошибки SQLite ("database is locked"): repo.escalate,
# log_event входящего, restart_reminder_cycle.
_DB_WRITE_RETRY_ATTEMPTS = 3
_DB_WRITE_RETRY_DELAY_SECONDS = 1

# Сколько раз подряд бот может сам ответить на встречный вопрос клиента (FAQ-ветка), прежде чем
# принудительно эскалировать на Варвару вместо очередного автоответа — защита от бесконечного
# цикла, если клиент постоянно задаёт вопросы из базы знаний (P-020 в BACKLOG.md).
_FAQ_CYCLE_CAP = 5


async def _send_via_channel(deal: Deal, text: str) -> None:
    if deal.channel == Channel.TELEGRAM:
        await telegram_sender.send_reply(deal.telegram_peer_id, text)
    elif deal.channel == Channel.EMAIL:
        subject = f"Re: {settings.email_subject}"
        await asyncio.to_thread(email_sender.send_email_sync, deal.email_address, subject, text)
    else:
        raise RuntimeError(f"Сделка {deal.deal_id}: не задан канал отправки")


async def _send_first_contact(deal_id: int, deal: Deal, text: str) -> tuple[Channel, int | None] | None:
    """Отправляет `text` первым сообщением (Telegram, с fallback на email), логирует и
    возвращает (канал, telegram_peer_id), либо None (и заводит FAILED-задачу на Варвару), если
    ни один канал не сработал. Любая ошибка Telegram (не только известные FloodWait/приватность/
    неверный username) даёт шанс на email-резерв — сделка не должна теряться из-за незнакомого
    типа ошибки Telethon (P-011 в BACKLOG.md)."""
    channel: Channel | None = None
    peer_id: int | None = None

    if deal.telegram_username:
        try:
            peer_id = await telegram_sender.send_first_contact(deal.telegram_username, text)
            channel = Channel.TELEGRAM
        except Exception:
            # Не только TelegramSendError (FloodWait/PeerFlood/приватность/неверный username) —
            # любая другая ошибка Telethon (забаненный/деактивированный аккаунт, сетевой сбой и
            # т.п.) тоже должна давать шанс на email-резерв, а не терять сделку молча (P-011).
            logger.exception("Сделка %s: Telegram недоступен, пробуем email", deal_id)

    if channel is None and deal.email_address:
        try:
            await asyncio.to_thread(
                email_sender.send_email_sync, deal.email_address, settings.email_subject, text
            )
            channel = Channel.EMAIL
        except Exception:
            logger.exception("Сделка %s: отправка email тоже не удалась", deal_id)

    if channel is None:
        repo.mark_failed(deal_id, templates.TASK_TEXT_NO_CHANNEL)
        await asyncio.to_thread(
            amo_actions.create_manager_task, deal_id, templates.TASK_TEXT_NO_CHANNEL
        )
        return None

    repo.log_event(deal_id, "out", channel.value, text)
    return channel, peer_id


async def process_new_deal(deal_id: int) -> None:
    """Первый контакт по сделке, только что попавшей в 'Новый контакт'. Ни один из чеклистов не
    блокирует отправку — оба влияют только на текст того же основного сообщения
    (`core/templates.py: first_message`):
    - `checklist.assess` — если сервисов названо меньше двух или задача не описана (ни проблема,
      ни данные для обработки), перед абзацем согласия на оплату добавляется предупреждение;
    - `checklist.assess_topic` — если по тексту задачи распознана известная тема (ИИ-агент/бот,
      Tilda+iiko, Яндекс Метрика, бот в Максе) с недостающими деталями, эти вопросы заменяют
      закрывающий вопрос "Хотите что-то добавить?".

    Сразу после отправки сделка переводится на этап 'Первичные переговоры' — независимо от того,
    ответит клиент или нет (не дожидаемся ответа, в отличие от предыдущей версии сценария).

    Подготовка сообщения (чек-листы + шаблон, до попытки отправки) обёрнута в try/except: сбой
    здесь означает, что клиенту ТОЧНО ничего не ушло (в отличие от сбоя после отправки), поэтому
    безопасно сразу пометить сделку FAILED и завести задачу Варваре — иначе сделка осталась бы в
    `NEW` навсегда, никем не подхватываемая повторно (P-016 в BACKLOG.md, реализовался как P-036).

    Сразу после `set_awaiting_first_sent` на сделку ставится тег канала связи ('ТГ'/'Почта',
    `amo_actions.set_channel_tag`) — сам этот проект его не читает, это подготовка для соседнего
    проекта "Выдача кейсов к группу", которому нужен фактический канал при передаче контакта
    клиента партнёру. Канал дальше не меняется до конца жизни сделки, так что момент верный.

    Если `checklist.mentions_messaging_work(case_text)` находит в задаче работу с сообщениями
    (ИИ-агент, автообработка отзывов, пересылка между системами) — обычный закрывающий вопрос в
    первом сообщении заменяется на нейтральную фразу (`templates.MESSAGING_TARIFF_CLOSING_NOTE`),
    а сразу вторым ОТДЕЛЬНЫМ сообщением уходит предупреждение о тарифе на 'операции'
    (`templates.MESSAGING_TARIFF_WARNING`, со своим закрывающим вопросом). Сделка помечается
    флагом `messaging_tariff_flagged` и тегом 'Месседжинг' (`amo_actions.set_messaging_tariff_tag`)
    — флаг читает `handle_incoming_reply`, чтобы завести доп. задачу Варваре по ответу клиента
    (P-052 в BACKLOG.md). То же самое (без второго сообщения этой функции) может произойти позже,
    если клиент упомянет это только в переписке — см. `handle_incoming_reply`."""
    deal = repo.get_deal(deal_id)
    if deal is None:
        return

    try:
        missing = checklist.assess(deal.stack_text, deal.case_text)
        topic_questions = checklist.assess_topic(deal.stack_text, deal.case_text)
        messaging_flagged = await asyncio.to_thread(
            checklist.mentions_messaging_work, deal.case_text
        )
        text = templates.first_message(
            deal.contact_name,
            deal.stack_text,
            deal.case_text,
            missing,
            topic_questions,
            closing_question_override=(
                templates.MESSAGING_TARIFF_CLOSING_NOTE if messaging_flagged else None
            ),
        )
    except Exception:
        logger.exception("Сделка %s: не удалось подготовить первое сообщение", deal_id)
        repo.mark_failed(deal_id, templates.TASK_TEXT_PREP_FAILED)
        try:
            await asyncio.to_thread(
                amo_actions.create_manager_task, deal_id, templates.TASK_TEXT_PREP_FAILED
            )
        except Exception:
            logger.exception("Сделка %s: не удалось создать задачу на Варвару", deal_id)
        return

    sent = await _send_first_contact(deal_id, deal, text)
    if sent is None:
        return

    try:
        await asyncio.to_thread(amo_actions.move_to_negotiations, deal_id)
    except Exception:
        logger.exception("Сделка %s: не удалось перевести на этап 'Первичные переговоры'", deal_id)

    channel, peer_id = sent
    next_action_at = timeutils.next_reminder_at_iso()
    repo.set_awaiting_first_sent(deal_id, channel.value, peer_id, next_action_at)

    try:
        await asyncio.to_thread(amo_actions.set_channel_tag, deal_id, channel.value)
    except Exception:
        logger.exception("Сделка %s: не удалось поставить тег канала (%s)", deal_id, channel.value)

    if messaging_flagged:
        try:
            repo.set_messaging_tariff_flagged(deal_id, True)
        except Exception:
            logger.exception("Сделка %s: не удалось сохранить флаг тарифа на сообщения", deal_id)
        try:
            await asyncio.to_thread(amo_actions.set_messaging_tariff_tag, deal_id)
        except Exception:
            logger.exception("Сделка %s: не удалось поставить тег 'Месседжинг'", deal_id)
        try:
            fresh_deal = repo.get_deal(deal_id)  # канал/peer_id теперь сохранены
            await _send_via_channel(fresh_deal, templates.MESSAGING_TARIFF_WARNING)
            repo.log_event(
                deal_id, "out", fresh_deal.channel.value, templates.MESSAGING_TARIFF_WARNING
            )
        except Exception:
            logger.exception(
                "Сделка %s: не удалось отправить предупреждение о тарифе на сообщения", deal_id
            )


def _deal_in_reminder_eligible_stage(deal_id: int) -> bool:
    status_id = amo_actions.get_lead_status_id(deal_id)
    return status_id in _REMINDER_ELIGIBLE_STAGE_IDS


async def _escalate_with_retries(deal_id: int, new_status: Status) -> bool:
    """`repo.escalate` — единственный шаг классификации ответа, который обязан зафиксироваться
    (см. P-008 в BACKLOG.md): вызывается ДО побочных эффектов (примечание/ответ клиенту/смена
    этапа/задача Варваре), поэтому если он так и не пройдёт после нескольких попыток — ничего
    из побочных эффектов ещё не произошло и можно безопасно отменить обработку без риска дублей."""
    for attempt in range(1, _DB_WRITE_RETRY_ATTEMPTS + 1):
        try:
            repo.escalate(deal_id, new_status)
            return True
        except Exception:
            logger.exception(
                "Сделка %s: попытка %s/%s зафиксировать эскалацию (%s) не удалась",
                deal_id,
                attempt,
                _DB_WRITE_RETRY_ATTEMPTS,
                new_status,
            )
            if attempt < _DB_WRITE_RETRY_ATTEMPTS:
                await asyncio.sleep(_DB_WRITE_RETRY_DELAY_SECONDS)
    return False


async def _log_event_with_retries(deal_id: int, direction: str, channel: str | None, text: str) -> bool:
    """Как и `repo.escalate` — обязан либо зафиксироваться, либо дать вызывающей стороне явно
    разблокировать сделку, а не оставить её занятой навсегда (P-038 в BACKLOG.md)."""
    for attempt in range(1, _DB_WRITE_RETRY_ATTEMPTS + 1):
        try:
            repo.log_event(deal_id, direction, channel, text)
            return True
        except Exception:
            logger.exception(
                "Сделка %s: попытка %s/%s записать событие (%s) не удалась",
                deal_id,
                attempt,
                _DB_WRITE_RETRY_ATTEMPTS,
                direction,
            )
            if attempt < _DB_WRITE_RETRY_ATTEMPTS:
                await asyncio.sleep(_DB_WRITE_RETRY_DELAY_SECONDS)
    return False


async def _restart_reminder_cycle_with_retries(deal_id: int, next_action_at: str) -> int | None:
    """Как и `repo.escalate` — обязан либо зафиксироваться, либо дать вызывающей стороне явно
    разблокировать сделку (P-038 в BACKLOG.md). Возвращает `faq_cycle_count` либо `None` при
    исчерпании попыток."""
    for attempt in range(1, _DB_WRITE_RETRY_ATTEMPTS + 1):
        try:
            return repo.restart_reminder_cycle(deal_id, next_action_at)
        except Exception:
            logger.exception(
                "Сделка %s: попытка %s/%s зафиксировать restart_reminder_cycle не удалась",
                deal_id,
                attempt,
                _DB_WRITE_RETRY_ATTEMPTS,
            )
            if attempt < _DB_WRITE_RETRY_ATTEMPTS:
                await asyncio.sleep(_DB_WRITE_RETRY_DELAY_SECONDS)
    return None


async def process_scheduler_tick() -> None:
    """Вызывается периодически: рассылает напоминание №1 / закрывающее сообщение тем, у кого
    подошло время, согласно `next_action_at`. Та же цепочка обслуживает и ожидание ответа на
    первое сообщение (этап 'Первичные переговоры'), и ожидание ответа на уточняющий вопрос бота
    на этапе 'Уточнение ТЗ' (см. handle_incoming_reply: restart_reminder_cycle) — оба случая
    неотличимы для шедулера, статус в локальной БД один и тот же."""
    now = timeutils.to_iso(timeutils.utcnow())
    for stale in repo.list_due_rows(now):
        deal_id = stale.deal_id
        if not repo.try_lock(deal_id):
            continue
        try:
            # Перечитываем сделку заново после лока: за время между выборкой due-строк и локом
            # мог прийти ответ клиента (handle_incoming_reply уже мог изменить статус и снять
            # next_action_at) — не шлём напоминание, если это произошло.
            deal = repo.get_deal(deal_id)
            if deal is None:
                repo.unlock(deal_id)
                continue
            if deal.status not in (Status.AWAITING_REPLY_1, Status.AWAITING_REPLY_2):
                repo.unlock(deal_id)
                continue
            if deal.next_action_at is None or deal.next_action_at > now:
                repo.unlock(deal_id)
                continue

            if not await asyncio.to_thread(_deal_in_reminder_eligible_stage, deal_id):
                repo.stop_reminders(deal_id)
                continue

            if deal.status == Status.AWAITING_REPLY_1:
                await _send_via_channel(deal, templates.REMINDER_1)
                repo.log_event(deal_id, "out", deal.channel.value, templates.REMINDER_1)
                try:
                    await asyncio.to_thread(amo_actions.move_to_silence, deal_id)
                except Exception:
                    logger.exception("Сделка %s: не удалось перевести на этап 'Молчание'", deal_id)
                repo.advance_to_reminder2(deal_id, timeutils.next_reminder_at_iso())
            else:  # AWAITING_REPLY_2
                await _send_via_channel(deal, templates.CLOSING_NO_REPLY)
                repo.log_event(deal_id, "out", deal.channel.value, templates.CLOSING_NO_REPLY)
                await asyncio.to_thread(amo_actions.move_to_blocked, deal_id)
                repo.close_no_reply(deal_id)
        except Exception:
            logger.exception("Сделка %s: ошибка при обработке due-строки шедулера", deal_id)
            retry_at = timeutils.to_iso(timeutils.utcnow() + timedelta(hours=1))
            repo.reschedule(deal_id, retry_at)


async def _answer_faq_after_positive(deal_id: int, deal: Deal, text: str) -> None:
    """Клиент уже согласился (сделка в `ESCALATED_POSITIVE`, ТЗ собрано и передано), но продолжает
    писать вопросы. Бот по-прежнему может ответить по базе знаний — но БЕЗ закрывающего вопроса
    про передачу кейса на оценку (кейс уже передан) и БЕЗ новой задачи Варваре (человек уже в
    курсе, задача `TASK_TEXT_FINALIZE_SPEC` уже стоит). Если вопрос не нашёлся в базе — фиксированный
    ответ, что тема будет закрыта вместе с результатом оценки (тоже без задачи). Продуктовое
    решение, см. Логика ИИ агента.md.

    Лок берётся однократно, без ретраев (в отличие от основного пути) — это необязательная
    любезность поверх уже завершённого сценария, не стоит того, чтобы держать клиента в очереди
    на повторные попытки; если сделка занята — просто пропускаем этот вопрос."""
    if not repo.try_lock(deal_id):
        return

    try:
        repo.log_event(deal_id, "in", deal.channel.value if deal.channel else None, text)

        faq_id = None
        try:
            faq_id = await asyncio.to_thread(faq_client.match_faq_sync, text, deal.case_text)
        except Exception:
            logger.exception(
                "Сделка %s: подбор ответа из базы знаний (после согласия клиента) не удался",
                deal_id,
            )

        reply_text = (
            faq_client.get_answer(faq_id) if faq_id else templates.REPLY_NO_FAQ_MATCH_AFTER_POSITIVE
        )
        try:
            await _send_via_channel(deal, reply_text)
            repo.log_event(deal_id, "out", deal.channel.value, reply_text)
        except Exception:
            logger.exception(
                "Сделка %s: не удалось отправить ответ клиенту после согласия", deal_id
            )
    finally:
        repo.unlock(deal_id)


async def handle_incoming_reply(deal_id: int, text: str, channel: Channel) -> None:
    """Входящее сообщение от клиента (Telegram или email). Любой ответ переводит сделку на этап
    'Уточнение ТЗ' и классифицируется на positive/negative/ambiguous.

    Positive/negative, а также ambiguous без совпадения в базе знаний — сразу переводятся на этап
    'Ручная проверка' и на Варвару ставится задача (после этого бот больше не реагирует на
    сообщения по этой сделке, см. INACTIVE_STATUSES). Если ответ positive — перед переводом в
    сделку добавляется примечание с собранным ТЗ И записывается то же самое в custom-поле
    «Полное ТЗ» (см. `core/templates.py: spec_note`, `amo_actions.set_full_spec_field`) — поле
    читает соседний проект "Выдача кейсов к группу" при публикации кейса партнёрам. Ответ клиента
    добавляется строкой "Дополнение: ..." только если `checklist.describes_addition_to_case`
    решит, что это содержательное уточнение, а не голое согласие ("да"/"жду"/"хорошо").

    `repo.escalate` (см. `_escalate_with_retries`) вызывается ДО этих побочных эффектов, не после
    — если зафиксировать эскалацию так и не удастся, ничего из побочных эффектов ещё не произошло,
    и сделку можно безопасно разблокировать без риска дублей при следующей попытке (P-008 в
    BACKLOG.md).

    Ambiguous С совпадением в базе знаний — бот отвечает сам (ответ + закрывающий вопрос про
    передачу кейса на оценку, `templates.faq_answer_with_followup`) и остаётся ждать реакции
    клиента (`repo.restart_reminder_cycle`, та же цепочка напоминаний, что после первого
    сообщения). На КАЖДЫЙ такой автоответ ставится задача Варваре (человек в курсе, что бот
    ответил сам) — но полной эскалации (перевод на 'Ручная проверка') пока нет: следующий ответ
    клиента снова проходит через эту функцию (содержательный ответ → positive/negative → обычная
    эскалация ниже; ещё один вопрос из базы знаний → снова эта ветка). После `_FAQ_CYCLE_CAP`
    подряд отвеченных вопросов по одной сделке — принудительная полная эскалация вместо
    очередного автоответа (P-020 в BACKLOG.md). Если отправить автоответ не удалось — это
    равносильно "ответа в базе нет": обычная эскалация с `REPLY_AMBIGUOUS`, `restart_reminder_cycle`
    не вызывается (P-019 в BACKLOG.md).

    Если сделка занята (напр. шедулер шлёт напоминание) — не бросаем сообщение сразу, а пробуем
    получить блокировку ещё `_LOCK_RETRY_ATTEMPTS` раз с паузой `_LOCK_RETRY_INTERVAL_SECONDS`
    (~60 секунд суммарно); если так и не удалось — логируем предупреждение с текстом сообщения
    и выходим (P-009 в BACKLOG.md).

    `ESCALATED_POSITIVE` — исключение среди `INACTIVE_STATUSES`: клиент уже согласился, ТЗ собрано
    и передано, но он может продолжать задавать вопросы. Такие сообщения не доходят до классификации
    и полного цикла выше — см. `_answer_faq_after_positive` (без закрывающего вопроса про оценку
    кейса — он уже передан, и без новой задачи Варваре — человек уже в курсе).

    Если сделка ещё НЕ помечена флагом `messaging_tariff_flagged` (см. `process_new_deal`), а
    текущее входящее сообщение упоминает работу с сообщениями (`checklist.mentions_messaging_work`)
    — это "позднее упоминание" (P-052 в BACKLOG.md): бот шлёт то же предупреждение о тарифе
    (`templates.MESSAGING_TARIFF_WARNING`) отдельным сообщением, ставит флаг+тег 'Месседжинг' и
    перезапускает цикл ожидания (`restart_reminder_cycle`, как в FAQ-ветке) — ТЕКУЩЕЕ сообщение НЕ
    классифицируется как positive/negative/ambiguous, бот ждёт отдельный ответ именно на вопрос про
    тариф. Флаг гарантирует, что это срабатывает не более одного раза за сделку.

    Если сделка ПОМЕЧЕНА флагом (при создании или после позднего упоминания) — при классификации
    ответа как positive/negative заводится ДОПОЛНИТЕЛЬНАЯ задача Варваре (`templates.
    TASK_TEXT_MESSAGING_POSITIVE`/`TASK_TEXT_MESSAGING_NEGATIVE`) в дополнение к обычной задаче.
    При negative-ответе клиенту при этом уходит не обычный `REPLY_NEGATIVE`, а более мягкий
    `templates.REPLY_MESSAGING_NEGATIVE` ("Поняла вас, спасибо за ответ...") — это отказ конкретно
    от условий тарифа на сообщения, а не общий негатив по заявке. Остальная эскалация (примечание/
    этап/обычная задача) не меняется."""
    deal = repo.get_deal(deal_id)
    if deal is None:
        return
    if deal.status in INACTIVE_STATUSES:
        if deal.status == Status.ESCALATED_POSITIVE:
            await _answer_faq_after_positive(deal_id, deal, text)
        return  # уже эскалировано/заблокировано/провалено — полный цикл бота дальше не идёт

    if not repo.try_lock(deal_id):
        for _ in range(_LOCK_RETRY_ATTEMPTS):
            await asyncio.sleep(_LOCK_RETRY_INTERVAL_SECONDS)
            if repo.try_lock(deal_id):
                break
        else:
            logger.warning(
                "Сделка %s: не удалось получить блокировку за ~%s сек — входящее сообщение "
                "потеряно: %r",
                deal_id,
                _LOCK_RETRY_ATTEMPTS * _LOCK_RETRY_INTERVAL_SECONDS,
                text[:200],
            )
            return

    if not await _log_event_with_retries(deal_id, "in", channel.value, text):
        logger.warning(
            "Сделка %s: не удалось зафиксировать входящее сообщение — сделка разблокирована для "
            "повторной попытки: %r",
            deal_id,
            text[:200],
        )
        repo.unlock(deal_id)
        return

    try:
        await asyncio.to_thread(amo_actions.move_to_clarification, deal_id)
    except Exception:
        logger.exception("Сделка %s: не удалось перевести на этап 'Уточнение ТЗ'", deal_id)

    if not deal.messaging_tariff_flagged:
        try:
            messaging_flagged_now = await asyncio.to_thread(
                checklist.mentions_messaging_work, text
            )
        except Exception:
            logger.exception(
                "Сделка %s: не удалось проверить упоминание работы с сообщениями", deal_id
            )
            messaging_flagged_now = False

        if messaging_flagged_now:
            try:
                repo.set_messaging_tariff_flagged(deal_id, True)
            except Exception:
                logger.exception(
                    "Сделка %s: не удалось сохранить флаг тарифа на сообщения", deal_id
                )
            try:
                await asyncio.to_thread(amo_actions.set_messaging_tariff_tag, deal_id)
            except Exception:
                logger.exception("Сделка %s: не удалось поставить тег 'Месседжинг'", deal_id)
            try:
                await _send_via_channel(deal, templates.MESSAGING_TARIFF_WARNING)
                repo.log_event(
                    deal_id, "out", deal.channel.value, templates.MESSAGING_TARIFF_WARNING
                )
            except Exception:
                logger.exception(
                    "Сделка %s: не удалось отправить предупреждение о тарифе на сообщения",
                    deal_id,
                )

            cycle_count = await _restart_reminder_cycle_with_retries(
                deal_id, timeutils.next_reminder_at_iso()
            )
            if cycle_count is None:
                logger.warning(
                    "Сделка %s: не удалось зафиксировать restart_reminder_cycle после позднего "
                    "предупреждения о тарифе — сделка разблокирована для повторной попытки",
                    deal_id,
                )
            repo.unlock(deal_id)
            return

    try:
        category = await asyncio.to_thread(classify_client.classify_sync, text, deal.case_text)
    except Exception:
        logger.exception("Сделка %s: классификация ответа не удалась, считаем ambiguous", deal_id)
        category = ReplyCategory.AMBIGUOUS

    if category == ReplyCategory.POSITIVE:
        reply_text = templates.REPLY_POSITIVE
        task_text = templates.TASK_TEXT_FINALIZE_SPEC
        new_status = Status.ESCALATED_POSITIVE
    elif category == ReplyCategory.NEGATIVE:
        reply_text = (
            templates.REPLY_MESSAGING_NEGATIVE
            if deal.messaging_tariff_flagged
            else templates.REPLY_NEGATIVE
        )
        task_text = templates.TASK_TEXT_NEGATIVE_CLIENT
        new_status = Status.ESCALATED_NEGATIVE
    else:
        faq_id = None
        try:
            faq_id = await asyncio.to_thread(faq_client.match_faq_sync, text, deal.case_text)
        except Exception:
            logger.exception("Сделка %s: подбор ответа из базы знаний не удался", deal_id)

        faq_answer_sent = False
        faq_answer = None
        if faq_id:
            faq_answer = faq_client.get_answer(faq_id)
            combined_text = templates.faq_answer_with_followup(faq_answer)
            try:
                await _send_via_channel(deal, combined_text)
                repo.log_event(deal_id, "out", deal.channel.value, combined_text)
                faq_answer_sent = True
            except Exception:
                logger.exception("Сделка %s: не удалось отправить ответ из базы знаний", deal_id)

        if faq_answer_sent:
            # Задача Варваре на КАЖДЫЙ автоответ — человек в курсе, что бот ответил сам (продуктовое
            # решение, см. Логика ИИ агента.md).
            try:
                await asyncio.to_thread(
                    amo_actions.create_manager_task, deal_id,
                    templates.task_text_faq_answered(text, faq_answer),
                )
            except Exception:
                logger.exception(
                    "Сделка %s: не удалось создать задачу Варваре по авто-ответу FAQ", deal_id
                )

            cycle_count = await _restart_reminder_cycle_with_retries(
                deal_id, timeutils.next_reminder_at_iso()
            )
            if cycle_count is None:
                logger.warning(
                    "Сделка %s: не удалось зафиксировать restart_reminder_cycle — сделка "
                    "разблокирована для повторной попытки",
                    deal_id,
                )
                repo.unlock(deal_id)
                return
            if cycle_count < _FAQ_CYCLE_CAP:
                return
            # Предел повторов исчерпан (P-020) — принудительно эскалируем. Клиенту уже отправлен
            # ответ+закрывающий вопрос выше, повторно REPLY_AMBIGUOUS не шлём (reply_text=None).
            reply_text = None
            task_text = templates.TASK_TEXT_FAQ_LIMIT_REACHED
            new_status = Status.ESCALATED_AMBIGUOUS
        else:
            # Ответа в базе знаний нет, либо отправка не удалась (P-019: в обоих случаях клиент
            # ничего содержательного не получил — restart_reminder_cycle не вызываем).
            reply_text = templates.REPLY_AMBIGUOUS
            task_text = templates.TASK_TEXT_CLARIFICATION
            new_status = Status.ESCALATED_AMBIGUOUS

    if not await _escalate_with_retries(deal_id, new_status):
        logger.warning(
            "Сделка %s: эскалация (%s) не зафиксирована после %s попыток — сообщение клиента "
            "не обработано, сделка разблокирована для повторной попытки",
            deal_id,
            new_status,
            _DB_WRITE_RETRY_ATTEMPTS,
        )
        repo.unlock(deal_id)
        return

    if category == ReplyCategory.POSITIVE:
        if checklist.describes_addition_to_case(text):
            case_with_addition = f"{deal.case_text or ''}\n\nДополнение: {text}".strip()
        else:
            case_with_addition = deal.case_text or ""
        note_text = templates.spec_note(deal.stack_text, case_with_addition)
        try:
            await asyncio.to_thread(amo_actions.add_note, deal_id, note_text)
        except Exception:
            logger.exception("Сделка %s: не удалось добавить примечание с ТЗ", deal_id)
        try:
            await asyncio.to_thread(amo_actions.set_full_spec_field, deal_id, note_text)
        except Exception:
            logger.exception("Сделка %s: не удалось записать текст ТЗ в поле 'Полное ТЗ'", deal_id)

    if reply_text is not None:
        # None — только когда предел повторов FAQ-цикла исчерпан: клиенту уже отправлен ответ+
        # закрывающий вопрос выше, повторно слать нечего.
        try:
            await _send_via_channel(deal, reply_text)
            repo.log_event(deal_id, "out", deal.channel.value, reply_text)
        except Exception:
            logger.exception("Сделка %s: не удалось отправить ответ клиенту (%s)", deal_id, category)

    try:
        await asyncio.to_thread(amo_actions.move_to_manual_review, deal_id)
    except Exception:
        logger.exception("Сделка %s: не удалось перевести на этап 'Ручная проверка'", deal_id)

    try:
        await asyncio.to_thread(amo_actions.create_manager_task, deal_id, task_text)
    except Exception:
        logger.exception("Сделка %s: не удалось создать задачу на Варвару", deal_id)

    if deal.messaging_tariff_flagged and category in (
        ReplyCategory.POSITIVE,
        ReplyCategory.NEGATIVE,
    ):
        extra_task_text = (
            templates.TASK_TEXT_MESSAGING_POSITIVE
            if category == ReplyCategory.POSITIVE
            else templates.TASK_TEXT_MESSAGING_NEGATIVE
        )
        try:
            await asyncio.to_thread(amo_actions.create_manager_task, deal_id, extra_task_text)
        except Exception:
            logger.exception(
                "Сделка %s: не удалось создать доп. задачу по тарифу на сообщения", deal_id
            )
