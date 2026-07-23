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
from db.models import Channel, Deal, ReplyCategory, Status, TERMINAL_ESCALATED_STATUSES
from email_channel import sender as email_sender
from telegram_channel import sender as telegram_sender
from telegram_channel.sender import TelegramSendError

logger = logging.getLogger(__name__)


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
    ни один канал не сработал."""
    channel: Channel | None = None
    peer_id: int | None = None

    if deal.telegram_username:
        try:
            peer_id = await telegram_sender.send_first_contact(deal.telegram_username, text)
            channel = Channel.TELEGRAM
        except TelegramSendError as e:
            logger.info("Сделка %s: Telegram недоступен (%s), пробуем email", deal_id, e)

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
    """Первый контакт по сделке, только что попавшей в 'Новый контакт'. Чеклист целостности
    задачи (`core/checklist.py`) не блокирует отправку — если сервисов названо меньше двух или
    задача не описана (ни проблема, ни данные для обработки), в то же самое сообщение перед
    абзацем согласия на оплату добавляется предупреждение о нехватке данных (см.
    `core/templates.py: first_message`)."""
    deal = repo.get_deal(deal_id)
    if deal is None:
        return

    missing = checklist.assess(deal.stack_text, deal.case_text)
    text = templates.first_message(deal.contact_name, deal.stack_text, deal.case_text, missing)
    sent = await _send_first_contact(deal_id, deal, text)
    if sent is None:
        return

    channel, peer_id = sent
    next_action_at = timeutils.next_reminder_at_iso()
    repo.set_awaiting_first_sent(deal_id, channel.value, peer_id, next_action_at)


async def process_scheduler_tick() -> None:
    """Вызывается периодически: рассылает напоминание №1 / закрывающее сообщение тем, у кого
    подошло время, согласно `next_action_at`."""
    now = timeutils.to_iso(timeutils.utcnow())
    for deal in repo.list_due_rows(now):
        if not repo.try_lock(deal.deal_id):
            continue
        try:
            if deal.status == Status.AWAITING_REPLY_1:
                await _send_via_channel(deal, templates.REMINDER_1)
                repo.log_event(deal.deal_id, "out", deal.channel.value, templates.REMINDER_1)
                repo.advance_to_reminder2(deal.deal_id, timeutils.next_reminder_at_iso())
            elif deal.status == Status.AWAITING_REPLY_2:
                await _send_via_channel(deal, templates.CLOSING_NO_REPLY)
                repo.log_event(deal.deal_id, "out", deal.channel.value, templates.CLOSING_NO_REPLY)
                await asyncio.to_thread(amo_actions.move_to_blocked, deal.deal_id)
                repo.close_no_reply(deal.deal_id)
            else:
                repo.unlock(deal.deal_id)
        except Exception:
            logger.exception("Сделка %s: ошибка при обработке due-строки шедулера", deal.deal_id)
            retry_at = timeutils.to_iso(timeutils.utcnow() + timedelta(hours=1))
            repo.reschedule(deal.deal_id, retry_at)


async def handle_incoming_reply(deal_id: int, text: str, channel: Channel) -> None:
    """Входящее сообщение от клиента (Telegram или email). Любой ответ переводит сделку на этап
    'Первичные переговоры' и классифицируется на positive/negative/ambiguous; после этого бот
    больше не реагирует на сообщения по этой сделке (см. TERMINAL_ESCALATED_STATUSES)."""
    deal = repo.get_deal(deal_id)
    if deal is None:
        return
    if deal.status in TERMINAL_ESCALATED_STATUSES or deal.status == Status.FAILED:
        return  # уже эскалировано человеку — бот не вмешивается

    if not repo.try_lock(deal_id):
        return  # сделка сейчас обрабатывается (напр. шедулер шлёт напоминание)

    repo.log_event(deal_id, "in", channel.value, text)

    try:
        await asyncio.to_thread(amo_actions.move_to_negotiations, deal_id)
    except Exception:
        logger.exception("Сделка %s: не удалось перевести на этап 'Первичные переговоры'", deal_id)

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
        reply_text = templates.REPLY_NEGATIVE
        task_text = templates.TASK_TEXT_NEGATIVE_CLIENT
        new_status = Status.ESCALATED_NEGATIVE
    else:
        faq_id = None
        try:
            faq_id = await asyncio.to_thread(faq_client.match_faq_sync, text, deal.case_text)
        except Exception:
            logger.exception("Сделка %s: подбор ответа из базы знаний не удался", deal_id)

        if faq_id:
            reply_text = faq_client.get_answer(faq_id)
            task_text = templates.task_text_faq_answered(faq_id)
        else:
            reply_text = templates.REPLY_AMBIGUOUS
            task_text = templates.TASK_TEXT_CLARIFICATION
        new_status = Status.ESCALATED_AMBIGUOUS

    try:
        await _send_via_channel(deal, reply_text)
        repo.log_event(deal_id, "out", deal.channel.value, reply_text)
    except Exception:
        logger.exception("Сделка %s: не удалось отправить ответ клиенту (%s)", deal_id, category)

    try:
        await asyncio.to_thread(amo_actions.create_manager_task, deal_id, task_text)
    except Exception:
        logger.exception("Сделка %s: не удалось создать задачу на Варвару", deal_id)

    repo.escalate(deal_id, new_status)
