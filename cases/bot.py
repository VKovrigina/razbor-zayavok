from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatMemberStatus
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from amo.client import amo_client
from cases import contact_delivery
from cases import repository as repo
from cases import templates
from cases.amo_retry import amo_with_retries
from cases.models import CaseStatus
from config import settings
from reporting import webhook as report_webhook

logger = logging.getLogger(__name__)

bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()

CALLBACK_PREFIX = "case:"

_NOT_A_MEMBER_STATUSES = {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}


def case_claim_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Беру", callback_data=f"{CALLBACK_PREFIX}{task_id}")]
        ]
    )


@dp.callback_query(F.data.startswith(CALLBACK_PREFIX))
async def handle_case_claim(callback: CallbackQuery) -> None:
    """Раздел 3 Логика ИИ агента.md. Роль бота строго ограничена этим и публикацией кейса
    (разд. 2) — вся доставка контакта (разд. 4) идёт через вторую telethon-сессию, не отсюда
    (решено 2026-07-31, см. cases/contact_delivery.py)."""
    try:
        task_id = int(callback.data[len(CALLBACK_PREFIX):])
    except ValueError:
        await callback.answer()
        return

    user = callback.from_user

    # Проверка членства в группе ДО CAS-лока (решено 2026-07-31) — форварднутая кнопка вне
    # группы не должна позволять забрать кейс тому, кто в группе партнёров не состоит.
    member = await bot.get_chat_member(settings.telegram_group_id, user.id)
    if member.status in _NOT_A_MEMBER_STATUSES:
        await callback.answer(templates.not_a_member_alert(), show_alert=True)
        return

    nick = templates.partner_display_nick(user.username, user.first_name, user.last_name)

    locked = await asyncio.to_thread(repo.claim_case, task_id, user.id, nick)
    if not locked:
        case = await asyncio.to_thread(repo.get_case, task_id)
        if case is None:
            await callback.answer("Кейс не найден.", show_alert=True)
        else:
            await callback.answer(
                templates.already_claimed_alert(case.claimed_by_tg_username or nick), show_alert=True
            )
        return

    case = await asyncio.to_thread(repo.get_case, task_id)
    deal_id = case.deal_id

    # «✅ Взял» в сообщении и ответ на нажатие — необязательные шаги (пункт 4 аудита 2026-10-28):
    # раньше их сбой обрывал всё дальше — кейс закреплён, а CRM и доставки нет, алерта нет. Ответ
    # падает, например, на нажатиях, накопившихся за время простоя: "query is too old" (24.08).
    try:
        await callback.message.edit_text(templates.claimed_text(callback.message.text or "", nick))
    except Exception:
        logger.exception("Не удалось отметить взятие в сообщении кейса (task_id=%s)", task_id)
    try:
        await callback.answer()
    except Exception:
        logger.warning("Не удалось ответить на нажатие «Беру» (task_id=%s)", task_id, exc_info=True)

    try:
        await amo_with_retries(
            amo_client.update_lead_status_and_field,
            deal_id,
            settings.amocrm_stage_taken_by_partner_id,
            settings.amocrm_field_id_partner_nick,
            nick,
        )
    except Exception:
        logger.exception("Не удалось обновить сделку после взятия кейса (task_id=%s)", task_id)
        try:
            await asyncio.to_thread(
                report_webhook.send_error_notification,
                marker=str(deal_id),
                message=f"Не удалось обновить сделку после взятия кейса (task_id={task_id}, взял {nick})",
            )
        except Exception:
            logger.exception("Не удалось отправить алерт о сбое обновления CRM (task_id=%s)", task_id)
        await asyncio.to_thread(repo.set_status, task_id, CaseStatus.FAILED_CRM_UPDATE)

    # Раздел 4 запускается безусловно — независимо от того, успел ли шаг обновления CRM выше
    # (решено 2026-07-31).
    await contact_delivery.deliver_contact(task_id, deal_id, user.id)
