from __future__ import annotations

import asyncio
import email as email_lib
import email.utils
import html
import imaplib
import logging
import re
from email.header import decode_header

from amo import actions as amo_actions
from config import settings
from db import repository as repo
from db.models import Channel
from email_channel import sender as email_sender
from reporting import watchdog
from reporting import webhook as report_webhook

logger = logging.getLogger(__name__)

_AUTO_REPLY_SUBJECT_MARKERS = (
    "auto-reply",
    "out of office",
    "undelivered",
    "delivery status notification",
    "автоответ",
    "автоматический ответ",
)


def _decode_bytes(data: bytes, charset: str | None) -> str:
    try:
        return data.decode(charset or "utf-8", errors="ignore")
    except LookupError:  # неизвестная кодировка ("unknown-8bit" у некодированной кириллицы и т.п.)
        return data.decode("utf-8", errors="ignore")


def _decode(value: str) -> str:
    parts = decode_header(value)
    return "".join((_decode_bytes(p, enc) if isinstance(p, bytes) else p) for p, enc in parts)


def _is_auto_reply(msg: email_lib.message.Message) -> bool:
    auto_submitted = (msg.get("Auto-Submitted") or "").lower()
    if auto_submitted and auto_submitted != "no":
        return True
    subject = _decode(msg.get("Subject") or "").lower()
    return any(marker in subject for marker in _AUTO_REPLY_SUBJECT_MARKERS)


# Начало цитаты/подписи в ответе: "--" подпись и "----------------" Яндекса, "Отправлено из
# мобильной ...", заголовок цитаты "Кому: адрес" / "From: адрес", строка-атрибуция
# "Ср, 29 июля 2026 г. в 14:28, Имя <адрес>:" / "On Mon, 07 Sep 2026 ..., адрес wrote:".
_QUOTE_START = re.compile(
    r"^(?:-{2,}$"
    r"|-+\s*(?:original message|исходное сообщение|пересылаемое сообщение)"
    r"|отправлено из мобильной"
    r"|кому:?\s.*@|(?:от|from):\s.*@"
    r"|.*\d{4}.*\S@\S+.*:$)",
    re.IGNORECASE,
)
# Gmail переносит длинную атрибуцию: 'On Tue, 15 Sep 2026 ..., "Имя"' + '<адрес> wrote:'
_WRAPPED_ATTRIBUTION_TAIL = re.compile(r"^<[^<>\s]+@[^<>\s]+>.*:$")


def _decode_part(part: email_lib.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    return _decode_bytes(payload, part.get_content_charset()).replace("\r\n", "\n")


def _html_to_text(body: str) -> str:
    body = re.split(r"<blockquote", body, maxsplit=1, flags=re.IGNORECASE)[0]
    body = re.sub(r"<br\s*/?>|</(?:div|p|li|tr|h\d)>", "\n", body, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", "", body))
    return "\n".join(line.strip() for line in text.split("\n"))


def _strip_quote(text: str) -> str:
    """Оставляет только новый текст ответа — без цитаты нашего письма и подписи (иначе они уходят
    в "Дополнение" Полного ТЗ и в группу партнёров, сделка 40324483). Если над цитатой пусто
    (ответ снизу, под цитатой) — убирает только строки "> ...", чтобы не потерять ответ."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if i > 0 and _WRAPPED_ATTRIBUTION_TAIL.match(line.strip()) and re.search(r"\d{4}", lines[i - 1]):
            cut = i - 1
        elif line.startswith(">") or _QUOTE_START.match(line.strip()):
            cut = i
        else:
            continue
        head = "\n".join(lines[:cut]).strip()
        if head:
            return re.sub(r"\n{3,}", "\n\n", head)
        break
    rest = "\n".join(line for line in lines if not line.startswith(">")).strip()
    return re.sub(r"\n{3,}", "\n\n", rest)


def _extract_body(msg: email_lib.message.Message) -> str:
    """text/plain, а если его нет — text/html, переведённый в текст (веб- и мобильная Яндекс
    Почта присылают письмо только в HTML)."""
    parts = [p for p in msg.walk() if not p.is_multipart() and not p.get_filename()]
    for part in parts:
        if part.get_content_type() == "text/plain":
            return _strip_quote(_decode_part(part))
    for part in parts:
        if part.get_content_type() == "text/html":
            return _strip_quote(_html_to_text(_decode_part(part)))
    return ""


def _imap():
    # Без timeout imaplib ждёт ответа сервера вечно — опрос почты тихо вставал бы навсегда
    # (тот же таймаут, что в email_channel/sender.py).
    imap = imaplib.IMAP4_SSL(
        settings.email_imap_host, settings.email_imap_port, timeout=email_sender._MAIL_TIMEOUT_SECONDS
    )
    imap.login(settings.email_imap_user, settings.email_imap_password)
    imap.select("INBOX")
    return imap


def _fetch_unseen_sync() -> list[tuple[bytes, bytes]]:
    """(uid, сырое письмо) непрочитанных писем — БЕЗ пометки прочитанными (BODY.PEEK[]): помечаем
    только после обработки (_mark_seen_sync), иначе сбой посреди пачки или перезапуск терял письма
    (пункт 7 аудита 2026-10-28)."""
    results: list[tuple[bytes, bytes]] = []
    with _imap() as imap:
        status, data = imap.uid("SEARCH", None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return results
        for uid in data[0].split():
            status, msg_data = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            results.append((uid, msg_data[0][1]))
    return results


def _mark_seen_sync(uid: bytes) -> None:
    with _imap() as imap:
        imap.uid("STORE", uid, "+FLAGS", "(\\Seen)")


def _parse_message(raw: bytes) -> tuple[str, str] | None:
    """(адрес отправителя, текст ответа); None — автоответ/bounce или нет отправителя."""
    msg = email_lib.message_from_bytes(raw)
    if _is_auto_reply(msg):
        return None
    from_address = email.utils.parseaddr(msg.get("From") or "")[1].lower()
    if not from_address:
        return None
    return from_address, _extract_body(msg)


# uid писем, уже обработанных в этом запуске: если пометить письмо прочитанным не удалось, оно
# придёт в следующей пачке снова — не обрабатываем его повторно (иначе двойной ответ клиенту).
_processed_uids: set[bytes] = set()


async def _mark_seen(uid: bytes) -> None:
    _processed_uids.add(uid)
    try:
        await asyncio.to_thread(_mark_seen_sync, uid)
    except Exception:
        logger.exception("Не удалось пометить письмо %s прочитанным", uid)


async def poll_once() -> None:
    from core import state_machine  # локальный импорт — избегаем цикла на уровне модулей

    if not settings.email_imap_host:
        return
    items = await asyncio.to_thread(_fetch_unseen_sync)
    for uid, raw in items:
        watchdog.beat("email_poll")
        if uid in _processed_uids:
            continue
        try:
            parsed = _parse_message(raw)
        except Exception:
            # Одно "кривое" письмо не должно блокировать остальные; помечаем прочитанным, чтобы
            # не спотыкаться о него каждую минуту.
            logger.exception("Не удалось прочитать письмо %s", uid)
            try:
                await asyncio.to_thread(
                    report_webhook.send_error_notification,
                    marker="email",
                    message=f"Не удалось прочитать входящее письмо (UID {uid.decode()}) — посмотрите в ящике вручную",
                )
            except Exception:
                logger.exception("Не удалось отправить алерт о нечитаемом письме")
            await _mark_seen(uid)
            continue

        deal = repo.get_deal_by_email(parsed[0]) if parsed else None
        if deal is not None:
            from_address, body = parsed
            try:
                if deal.channel == Channel.TELEGRAM:
                    # Переписка по этой сделке ведётся в Telegram — письмо не запускает сценарий
                    # параллельно, просто фиксируется в сделке для видимости (см. P-007 в BACKLOG.md).
                    repo.log_event(deal.deal_id, "in", Channel.EMAIL.value, body)
                    await asyncio.to_thread(amo_actions.add_note, deal.deal_id, f"Почта: {body}")
                else:
                    await state_machine.handle_incoming_reply(deal.deal_id, body, Channel.EMAIL)
            except Exception:
                logger.exception("Ошибка обработки входящего письма по сделке %s", deal.deal_id)
        await _mark_seen(uid)


async def poll_loop(interval_seconds: int = 60) -> None:
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("Ошибка в цикле поллинга почты")
        watchdog.beat("email_poll")
        await asyncio.sleep(interval_seconds)
