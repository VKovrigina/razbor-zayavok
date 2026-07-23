from __future__ import annotations

import asyncio
import email as email_lib
import email.utils
import imaplib
import logging
from email.header import decode_header

from config import settings
from db import repository as repo
from db.models import Channel

logger = logging.getLogger(__name__)

_AUTO_REPLY_SUBJECT_MARKERS = (
    "auto-reply",
    "out of office",
    "undelivered",
    "delivery status notification",
    "автоответ",
    "автоматический ответ",
)


def _decode(value: str) -> str:
    parts = decode_header(value)
    return "".join(
        (p.decode(enc or "utf-8", errors="ignore") if isinstance(p, bytes) else p) for p, enc in parts
    )


def _is_auto_reply(msg: email_lib.message.Message) -> bool:
    auto_submitted = (msg.get("Auto-Submitted") or "").lower()
    if auto_submitted and auto_submitted != "no":
        return True
    subject = _decode(msg.get("Subject") or "").lower()
    return any(marker in subject for marker in _AUTO_REPLY_SUBJECT_MARKERS)


def _extract_body(msg: email_lib.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                return payload.decode(charset, errors="ignore") if payload else ""
        return ""
    charset = msg.get_content_charset() or "utf-8"
    payload = msg.get_payload(decode=True)
    return payload.decode(charset, errors="ignore") if payload else ""


def _fetch_unseen_sync() -> list[tuple[str, str]]:
    """Возвращает (from_address, body) для новых непрочитанных писем, помечает их прочитанными.
    Пропускает авто-ответы/bounce-письма."""
    results: list[tuple[str, str]] = []
    with imaplib.IMAP4_SSL(settings.email_imap_host, settings.email_imap_port) as imap:
        imap.login(settings.email_imap_user, settings.email_imap_password)
        imap.select("INBOX")
        status, data = imap.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return results
        for num in data[0].split():
            status, msg_data = imap.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email_lib.message_from_bytes(msg_data[0][1])
            imap.store(num, "+FLAGS", "\\Seen")
            if _is_auto_reply(msg):
                continue
            from_address = email.utils.parseaddr(msg.get("From") or "")[1].lower()
            if not from_address:
                continue
            results.append((from_address, _extract_body(msg)))
    return results


async def poll_once() -> None:
    from core import state_machine  # локальный импорт — избегаем цикла на уровне модулей

    if not settings.email_imap_host:
        return
    pairs = await asyncio.to_thread(_fetch_unseen_sync)
    for from_address, body in pairs:
        deal = repo.get_deal_by_email(from_address)
        if deal is None:
            continue
        try:
            await state_machine.handle_incoming_reply(deal.deal_id, body, Channel.EMAIL)
        except Exception:
            logger.exception("Ошибка обработки входящего письма по сделке %s", deal.deal_id)


async def poll_loop(interval_seconds: int = 60) -> None:
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("Ошибка в цикле поллинга почты")
        await asyncio.sleep(interval_seconds)
