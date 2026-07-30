from __future__ import annotations

import imaplib
import logging
import smtplib
import time
from email.mime.text import MIMEText
from email.utils import formatdate

from config import settings

logger = logging.getLogger(__name__)

# IMAP-имя папки "Отправленные" в этом почтовом ящике (Яндекс Почта).
_SENT_FOLDER = "Sent"

# Без явного timeout imaplib/smtplib используют socket.getdefaulttimeout() (по умолчанию None —
# блокировка навсегда). Зависший TCP-коннект к почтовому серверу мог бы повесить поток в общем
# ThreadPoolExecutor (используется ВСЕМИ asyncio.to_thread-вызовами приложения) бесконечно,
# останавливая не только email (P-043 в BACKLOG.md). Значение — как в amo/client.py/amo/auth.py.
_MAIL_TIMEOUT_SECONDS = 30


def send_email_sync(to_address: str, subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.email_from_address
    msg["To"] = to_address
    msg["Date"] = formatdate(localtime=True)

    with smtplib.SMTP_SSL(
        settings.email_smtp_host, settings.email_smtp_port, timeout=_MAIL_TIMEOUT_SECONDS
    ) as smtp:
        smtp.login(settings.email_smtp_user, settings.email_smtp_password)
        smtp.send_message(msg)

    _save_to_sent(msg)


def _save_to_sent(msg: MIMEText) -> None:
    """Прямая отправка через SMTP не появляется в 'Отправленные' сама по себе — в отличие от
    веб-интерфейса Яндекса, который сам сохраняет туда копию, smtplib этого не делает. Дублируем
    письмо через IMAP APPEND, чтобы переписка бота была видна в обычном почтовом клиенте. Сбой
    здесь не должен считаться неудачей отправки — письмо уже реально доставлено через SMTP выше,
    поэтому только логируем и не бросаем исключение."""
    try:
        with imaplib.IMAP4_SSL(
            settings.email_imap_host, settings.email_imap_port, timeout=_MAIL_TIMEOUT_SECONDS
        ) as imap:
            imap.login(settings.email_imap_user, settings.email_imap_password)
            imap.append(
                _SENT_FOLDER,
                "\\Seen",
                imaplib.Time2Internaldate(time.time()),
                msg.as_bytes(),
            )
    except Exception:
        logger.exception("Не удалось сохранить копию письма в '%s'", _SENT_FOLDER)
