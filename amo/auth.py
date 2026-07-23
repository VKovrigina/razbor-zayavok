from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from config import settings
from db.repository import get_kv, set_kv

_TOKEN_URL_PATH = "/oauth2/access_token"
_REFRESH_MARGIN = timedelta(minutes=10)
_LONG_LIVED_FALLBACK_TTL = timedelta(days=300)


def _load_state() -> dict:
    return {
        "access_token": get_kv("amocrm_access_token") or settings.amocrm_access_token,
        "refresh_token": get_kv("amocrm_refresh_token") or settings.amocrm_refresh_token,
        "expires_at": get_kv("amocrm_expires_at"),
    }


def _save_state(access_token: str, refresh_token: str, expires_at: datetime) -> None:
    set_kv("amocrm_access_token", access_token)
    set_kv("amocrm_refresh_token", refresh_token)
    set_kv("amocrm_expires_at", expires_at.isoformat())


def _refresh(refresh_token: str) -> dict:
    url = settings.amocrm_base_url.rstrip("/") + _TOKEN_URL_PATH
    payload = {
        "client_id": settings.amocrm_client_id,
        "client_secret": settings.amocrm_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "redirect_uri": settings.amocrm_redirect_uri,
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_access_token() -> str:
    """Возвращает валидный access_token. Если настроен полноценный OAuth-обмен
    (client_id/secret + refresh_token) — обновляет токен по истечении срока.
    Если задан только долгосрочный токен (AMOCRM_ACCESS_TOKEN, без refresh-схемы) —
    использует его напрямую (долгосрочные токены amoCRM живут ~год)."""
    state = _load_state()

    can_refresh = bool(
        settings.amocrm_client_id and settings.amocrm_client_secret and state["refresh_token"]
    )

    if not can_refresh:
        if not state["access_token"]:
            raise RuntimeError(
                "Не задан AMOCRM_ACCESS_TOKEN и нет данных для OAuth refresh — "
                "заполните .env (см. README)."
            )
        if not state["expires_at"]:
            _save_state(
                state["access_token"],
                state["refresh_token"] or "",
                datetime.now(timezone.utc) + _LONG_LIVED_FALLBACK_TTL,
            )
        return state["access_token"]

    expires_at = (
        datetime.fromisoformat(state["expires_at"]) if state["expires_at"] else None
    )
    if state["access_token"] and expires_at and datetime.now(timezone.utc) < expires_at - _REFRESH_MARGIN:
        return state["access_token"]

    data = _refresh(state["refresh_token"])
    new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])
    _save_state(data["access_token"], data["refresh_token"], new_expires_at)
    return data["access_token"]
