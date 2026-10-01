from __future__ import annotations

import dataclasses
from datetime import datetime
from zoneinfo import ZoneInfo

from calls import amo_actions
from config import settings as base_settings

MSK = ZoneInfo("Europe/Moscow")

TEST_SETTINGS = dataclasses.replace(
    base_settings,
    amocrm_calls_pipeline_id=10805174,
    amocrm_calls_stage_primary_contact_id=85063946,
    amocrm_calls_stage_written_in_tg_id=85063950,
    amocrm_calls_stage_meeting_id=85064214,
    amocrm_varvara_user_id=999,
)


def test_get_leads_in_stage_uses_configured_pipeline_and_stage(monkeypatch):
    monkeypatch.setattr(amo_actions, "settings", TEST_SETTINGS)
    calls = []
    monkeypatch.setattr(
        amo_actions.amo_client,
        "get_leads_in_stage",
        lambda pipeline_id, status_id: calls.append((pipeline_id, status_id)) or ["lead"],
    )

    result = amo_actions.get_leads_in_stage()

    assert calls == [(10805174, 85063946)]
    assert result == ["lead"]


def test_move_to_written_in_tg_updates_status(monkeypatch):
    monkeypatch.setattr(amo_actions, "settings", TEST_SETTINGS)
    calls = []
    monkeypatch.setattr(amo_actions.amo_client, "update_lead_status", lambda lead_id, status_id: calls.append((lead_id, status_id)))

    amo_actions.move_to_written_in_tg(42)

    assert calls == [(42, 85063950)]


def test_move_to_meeting_updates_status(monkeypatch):
    monkeypatch.setattr(amo_actions, "settings", TEST_SETTINGS)
    calls = []
    monkeypatch.setattr(amo_actions.amo_client, "update_lead_status", lambda lead_id, status_id: calls.append((lead_id, status_id)))

    amo_actions.move_to_meeting(42)

    assert calls == [(42, 85064214)]


def test_create_fallback_task_uses_fixed_text_and_varvara(monkeypatch):
    monkeypatch.setattr(amo_actions, "settings", TEST_SETTINGS)
    calls = []
    monkeypatch.setattr(
        amo_actions.amo_client,
        "create_task",
        lambda lead_id, responsible_user_id, text, complete_till_ts: calls.append(
            (lead_id, responsible_user_id, text)
        ),
    )

    amo_actions.create_fallback_task(42)

    assert calls == [(42, 999, "тг недоступен, связаться вручную")]


def test_create_meeting_task_formats_time_and_deadline(monkeypatch):
    monkeypatch.setattr(amo_actions, "settings", TEST_SETTINGS)
    calls = []
    monkeypatch.setattr(
        amo_actions.amo_client,
        "create_task",
        lambda lead_id, responsible_user_id, text, complete_till_ts: calls.append(
            (lead_id, responsible_user_id, text, complete_till_ts)
        ),
    )
    meeting_at = datetime(2026, 8, 24, 13, 0, tzinfo=MSK)

    amo_actions.create_meeting_task(42, meeting_at)

    assert calls == [(42, 999, "Встреча с партнером в 13:00", int(meeting_at.timestamp()))]
