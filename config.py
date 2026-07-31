from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    # amoCRM
    amocrm_base_url: str = os.environ.get("AMOCRM_BASE_URL", "")
    amocrm_client_id: str = os.environ.get("AMOCRM_CLIENT_ID", "")
    amocrm_client_secret: str = os.environ.get("AMOCRM_CLIENT_SECRET", "")
    amocrm_redirect_uri: str = os.environ.get("AMOCRM_REDIRECT_URI", "")
    amocrm_access_token: str = os.environ.get("AMOCRM_ACCESS_TOKEN", "")
    amocrm_refresh_token: str = os.environ.get("AMOCRM_REFRESH_TOKEN", "")

    amocrm_pipeline_id: int | None = _int("AMOCRM_PIPELINE_ID")
    amocrm_stage_new_contact_id: int | None = _int("AMOCRM_STAGE_NEW_CONTACT_ID")
    amocrm_stage_negotiations_id: int | None = _int("AMOCRM_STAGE_NEGOTIATIONS_ID")
    amocrm_stage_clarification_id: int | None = _int("AMOCRM_STAGE_CLARIFICATION_ID")
    amocrm_stage_silence_id: int | None = _int("AMOCRM_STAGE_SILENCE_ID")
    amocrm_stage_manual_review_id: int | None = _int("AMOCRM_STAGE_MANUAL_REVIEW_ID")
    amocrm_stage_blocked_id: int | None = _int("AMOCRM_STAGE_BLOCKED_ID")
    # "взят партнёром" — сценарий "Выдача кейсов партнёрам" (main_cases.py, Логика ИИ агента.md,
    # раздел про выдачу кейсов). Main.py не переводит сюда сам — только читает, чтобы понять,
    # что партнёр уже забрал сделку в работу (см. core/state_machine.py: handle_incoming_reply).
    amocrm_stage_taken_by_partner_id: int | None = _int("AMOCRM_STAGE_TAKEN_BY_PARTNER_ID")
    # "отправлено в группу" — используется только main_cases.py (не main.py)
    amocrm_stage_sent_to_group_id: int | None = _int("AMOCRM_STAGE_SENT_TO_GROUP_ID")

    amocrm_field_id_telegram: int | None = _int("AMOCRM_FIELD_ID_TELEGRAM")
    amocrm_field_id_stack: int | None = _int("AMOCRM_FIELD_ID_STACK")
    amocrm_field_id_case: int | None = _int("AMOCRM_FIELD_ID_CASE")
    # "Полное ТЗ" — сценарий "Выдача кейсов партнёрам": заполняется здесь при позитивном ответе
    # клиента, читается в main_cases.py при публикации кейса партнёрам.
    amocrm_field_id_full_spec: int | None = _int("AMOCRM_FIELD_ID_FULL_SPEC")
    # "Партнер ник" — используется только main_cases.py (не main.py)
    amocrm_field_id_partner_nick: int | None = _int("AMOCRM_FIELD_ID_PARTNER_NICK")

    amocrm_varvara_user_id: int | None = _int("AMOCRM_VARVARA_USER_ID")

    # Telegram (Telethon / MTProto) — используется main.py
    telegram_api_id: int | None = _int("TELEGRAM_API_ID")
    telegram_api_hash: str = os.environ.get("TELEGRAM_API_HASH", "")
    telegram_phone: str = os.environ.get("TELEGRAM_PHONE", "")
    telegram_session_path: str = os.environ.get("TELEGRAM_SESSION_PATH", "data/telegram.session")

    # Telegram Bot API + вторая telethon-сессия (то же TELEGRAM_API_ID/API_HASH выше, свой
    # session-файл) — используется только main_cases.py, сценарий "Выдача кейсов партнёрам"
    telegram_bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_group_id: int | None = _int("TELEGRAM_GROUP_ID")
    telegram_cases_session_path: str = os.environ.get(
        "TELEGRAM_CASES_SESSION_PATH", "data/telegram_cases.session"
    )
    # Тема (forum topic) "кейсы" в группе партнёров — найдена через GetForumTopicsRequest
    # (2026-08-01), thread_id=3 в тестовой группе. Публикация кейса идёт именно в эту тему,
    # не в General.
    telegram_cases_topic_id: int | None = _int("TELEGRAM_CASES_TOPIC_ID")

    # Anthropic
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    # Email fallback
    email_from_address: str = os.environ.get("EMAIL_FROM_ADDRESS", "")
    email_subject: str = os.environ.get("EMAIL_SUBJECT", "Ваша заявка на интеграцию — Альбато")
    email_smtp_host: str = os.environ.get("EMAIL_SMTP_HOST", "")
    email_smtp_port: int = _int("EMAIL_SMTP_PORT", 465)
    email_smtp_user: str = os.environ.get("EMAIL_SMTP_USER", "")
    email_smtp_password: str = os.environ.get("EMAIL_SMTP_PASSWORD", "")
    email_imap_host: str = os.environ.get("EMAIL_IMAP_HOST", "")
    email_imap_port: int = _int("EMAIL_IMAP_PORT", 993)
    email_imap_user: str = os.environ.get("EMAIL_IMAP_USER", "")
    email_imap_password: str = os.environ.get("EMAIL_IMAP_PASSWORD", "")

    # Отчётность в вебхук (Albato) — P-014 в BACKLOG.md: видимость работы бота и уведомление о
    # краше, сам механизм реконнекта Telethon (main.py:44) не чинит.
    report_webhook_url: str = os.environ.get("REPORT_WEBHOOK_URL", "")
    report_interval_seconds: int = _int("REPORT_INTERVAL_SECONDS", 7200)

    # Общие
    timezone: str = os.environ.get("TIMEZONE", "Europe/Moscow")
    db_path: str = os.environ.get("DB_PATH", "data/app.db")
    # Отдельный файл БД для main_cases.py (сценарий "Выдача кейсов партнёрам") — намеренно НЕ
    # тот же файл, что db_path: два независимых процесса не пишут в один SQLite (см. P-021 —
    # риск database is locked даже для одного писателя, со вторым стало бы хуже)
    db_cases_path: str = os.environ.get("DB_CASES_PATH", "data/app_cases.db")
    amocrm_poll_interval_seconds: int = _int("AMOCRM_POLL_INTERVAL_SECONDS", 90)
    scheduler_tick_seconds: int = _int("SCHEDULER_TICK_SECONDS", 60)
    daily_telegram_send_cap: int = _int("DAILY_TELEGRAM_SEND_CAP", 500)
    reminder_hour_local: int = _int("REMINDER_HOUR_LOCAL", 14)

    # Обязательные для старта поля (без них сервис не может выполнять свою основную функцию)
    _required: tuple = field(
        default=(
            "amocrm_base_url",
            "amocrm_pipeline_id",
            "amocrm_stage_new_contact_id",
            "amocrm_stage_negotiations_id",
            "amocrm_stage_clarification_id",
            "amocrm_stage_silence_id",
            "amocrm_stage_manual_review_id",
            "amocrm_stage_blocked_id",
            "amocrm_field_id_telegram",
            "amocrm_field_id_stack",
            "amocrm_field_id_case",
            "amocrm_field_id_full_spec",
            "amocrm_varvara_user_id",
            "telegram_api_id",
            "telegram_api_hash",
            "telegram_phone",
        ),
        repr=False,
        compare=False,
    )

    # Обязательные для старта main_cases.py (сценарий "Выдача кейсов партнёрам") — отдельный
    # набор, НЕ добавляется в _required выше, чтобы не сломать validate() у main.py
    _required_cases: tuple = field(
        default=(
            "amocrm_base_url",
            "amocrm_varvara_user_id",
            "amocrm_field_id_full_spec",
            "amocrm_field_id_partner_nick",
            "amocrm_stage_sent_to_group_id",
            "amocrm_stage_taken_by_partner_id",
            "telegram_bot_token",
            "telegram_group_id",
            "telegram_api_id",
            "telegram_api_hash",
            "telegram_phone",
            "telegram_cases_session_path",
        ),
        repr=False,
        compare=False,
    )

    def validate(self) -> None:
        # ANTHROPIC_API_KEY намеренно не в _required: без него classify.client переключается
        # на классификацию по правилам (classify/rule_based.py) — грубее, но работоспособно.
        missing = [name for name in self._required if not getattr(self, name)]
        if missing:
            raise RuntimeError(
                "Не заполнены обязательные переменные окружения: "
                + ", ".join(m.upper() for m in missing)
                + ". Смотрите .env.example."
            )

    def validate_cases(self) -> None:
        """Отдельная валидация для main_cases.py — не влияет и не вызывается из validate()."""
        missing = [name for name in self._required_cases if not getattr(self, name)]
        if missing:
            raise RuntimeError(
                "Не заполнены обязательные переменные окружения для main_cases.py: "
                + ", ".join(m.upper() for m in missing)
                + ". Смотрите .env.example."
            )


settings = Settings()
