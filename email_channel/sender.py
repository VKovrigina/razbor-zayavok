from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from config import settings


def send_email_sync(to_address: str, subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.email_from_address
    msg["To"] = to_address

    with smtplib.SMTP_SSL(settings.email_smtp_host, settings.email_smtp_port) as smtp:
        smtp.login(settings.email_smtp_user, settings.email_smtp_password)
        smtp.send_message(msg)
