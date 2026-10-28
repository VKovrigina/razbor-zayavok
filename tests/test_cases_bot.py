import asyncio
from types import SimpleNamespace

from aiogram.enums import ChatMemberStatus

from cases import bot as bot_module
from cases.models import CaseStatus


def _user(user_id=555, username="ivan_partner", first_name="Иван", last_name="Петров"):
    return SimpleNamespace(id=user_id, username=username, first_name=first_name, last_name=last_name)


class FakeMessage:
    def __init__(self, text="Текст кейса"):
        self.text = text
        self.edited_text = None

    async def edit_text(self, text):
        self.edited_text = text


class FakeCallback:
    def __init__(self, data, user=None, message=None):
        self.data = data
        self.from_user = user or _user()
        self.message = message or FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append((text, show_alert))


def _member(status):
    return SimpleNamespace(status=status)


def _fake_get_chat_member(status):
    async def _get(group_id, user_id):
        return _member(status)

    return _get


async def _async_noop(*args, **kwargs):
    return None


def test_handle_case_claim_rejects_non_member_before_cas_lock(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(bot_module, "repo", cases_repo)
    monkeypatch.setattr(
        bot_module.bot, "get_chat_member", _fake_get_chat_member(ChatMemberStatus.LEFT)
    )
    callback = FakeCallback("case:1")

    asyncio.run(bot_module.handle_case_claim(callback))

    assert cases_repo.get_case(1).status == CaseStatus.POSTED  # лок не выполнялся
    assert callback.answers[0][1] is True  # show_alert


def test_handle_case_claim_success_locks_edits_message_and_updates_crm(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(bot_module, "repo", cases_repo)
    monkeypatch.setattr(
        bot_module.bot, "get_chat_member", _fake_get_chat_member(ChatMemberStatus.MEMBER)
    )
    crm_calls = []
    monkeypatch.setattr(
        bot_module.amo_client,
        "update_lead_status_and_field",
        lambda lead_id, status_id, field_id, value: crm_calls.append((lead_id, status_id, field_id, value)),
    )
    monkeypatch.setattr(bot_module.contact_delivery, "deliver_contact", _async_noop)

    callback = FakeCallback("case:1")
    asyncio.run(bot_module.handle_case_claim(callback))

    case = cases_repo.get_case(1)
    assert case.status == CaseStatus.CLAIMED
    assert case.claimed_by_tg_username == "@ivan_partner"
    assert "✅ Взял: @ivan_partner" in callback.message.edited_text
    assert len(crm_calls) == 1
    assert crm_calls[0][0] == 100


def test_handle_case_claim_second_click_shows_already_claimed_message_unchanged(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    cases_repo.claim_case(1, 999, "@first_partner")
    monkeypatch.setattr(bot_module, "repo", cases_repo)
    monkeypatch.setattr(
        bot_module.bot, "get_chat_member", _fake_get_chat_member(ChatMemberStatus.MEMBER)
    )

    callback = FakeCallback("case:1", user=_user(user_id=555, username="second_partner"))
    asyncio.run(bot_module.handle_case_claim(callback))

    assert callback.message.edited_text is None  # сообщение не менялось
    assert "@first_partner" in callback.answers[0][0]


def test_handle_case_claim_uses_username_when_present(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(bot_module, "repo", cases_repo)
    monkeypatch.setattr(
        bot_module.bot, "get_chat_member", _fake_get_chat_member(ChatMemberStatus.MEMBER)
    )
    monkeypatch.setattr(bot_module.amo_client, "update_lead_status_and_field", lambda *a: None)
    monkeypatch.setattr(bot_module.contact_delivery, "deliver_contact", _async_noop)

    callback = FakeCallback("case:1", user=_user(username="ivan_partner"))
    asyncio.run(bot_module.handle_case_claim(callback))

    assert cases_repo.get_case(1).claimed_by_tg_username == "@ivan_partner"


def test_handle_case_claim_uses_display_name_fallback_when_no_username(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(bot_module, "repo", cases_repo)
    monkeypatch.setattr(
        bot_module.bot, "get_chat_member", _fake_get_chat_member(ChatMemberStatus.MEMBER)
    )
    monkeypatch.setattr(bot_module.amo_client, "update_lead_status_and_field", lambda *a: None)
    monkeypatch.setattr(bot_module.contact_delivery, "deliver_contact", _async_noop)

    callback = FakeCallback("case:1", user=_user(username=None, first_name="Иван", last_name="Петров"))
    asyncio.run(bot_module.handle_case_claim(callback))

    assert cases_repo.get_case(1).claimed_by_tg_username == "Иван Петров"


def test_handle_case_claim_crm_update_failure_alerts_sets_failed_crm_update_but_does_not_rollback_claim(
    cases_repo, monkeypatch
):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(bot_module, "repo", cases_repo)
    monkeypatch.setattr(
        bot_module.bot, "get_chat_member", _fake_get_chat_member(ChatMemberStatus.MEMBER)
    )

    def failing_update(*args):
        raise RuntimeError("amoCRM недоступен")

    monkeypatch.setattr(bot_module.amo_client, "update_lead_status_and_field", failing_update)
    sent = []
    monkeypatch.setattr(
        bot_module.report_webhook,
        "send_error_notification",
        lambda marker, message: sent.append((marker, message)),
    )
    monkeypatch.setattr(bot_module.contact_delivery, "deliver_contact", _async_noop)

    callback = FakeCallback("case:1")
    asyncio.run(bot_module.handle_case_claim(callback))

    case = cases_repo.get_case(1)
    assert case.status == CaseStatus.FAILED_CRM_UPDATE
    assert case.claimed_by_tg_user_id == 555  # взятие НЕ откатилось
    assert len(sent) == 1


def test_handle_case_claim_triggers_contact_delivery_even_when_crm_update_failed(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(bot_module, "repo", cases_repo)
    monkeypatch.setattr(
        bot_module.bot, "get_chat_member", _fake_get_chat_member(ChatMemberStatus.MEMBER)
    )

    def failing_update(*args):
        raise RuntimeError("amoCRM недоступен")

    monkeypatch.setattr(bot_module.amo_client, "update_lead_status_and_field", failing_update)
    monkeypatch.setattr(bot_module.report_webhook, "send_error_notification", lambda marker, message: None)

    delivered = []

    async def fake_deliver(task_id, deal_id, partner_id):
        delivered.append((task_id, deal_id, partner_id))

    monkeypatch.setattr(bot_module.contact_delivery, "deliver_contact", fake_deliver)

    callback = FakeCallback("case:1")
    asyncio.run(bot_module.handle_case_claim(callback))

    assert delivered == [(1, 100, 555)]


def test_handle_case_claim_unknown_task_id_in_callback_data_handled_gracefully(cases_repo, monkeypatch):
    monkeypatch.setattr(bot_module, "repo", cases_repo)
    monkeypatch.setattr(
        bot_module.bot, "get_chat_member", _fake_get_chat_member(ChatMemberStatus.MEMBER)
    )

    callback = FakeCallback("case:9999")
    asyncio.run(bot_module.handle_case_claim(callback))  # не должно бросить исключение

    assert callback.answers[0][1] is True


def test_handle_case_claim_non_numeric_callback_data_handled_gracefully(cases_repo, monkeypatch):
    monkeypatch.setattr(bot_module, "repo", cases_repo)
    callback = FakeCallback("case:not-a-number")

    asyncio.run(bot_module.handle_case_claim(callback))  # не должно бросить исключение

    assert callback.answers == [(None, None)]


# --- Пункт 4 аудита 2026-10-28: сбой «необязательных» шагов не обрывает доставку ---

import pytest


@pytest.fixture()
def claim_env(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(bot_module, "repo", cases_repo)
    monkeypatch.setattr(bot_module.bot, "get_chat_member", _fake_get_chat_member(ChatMemberStatus.MEMBER))

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(bot_module.asyncio, "sleep", no_sleep)
    env = {"crm": [], "delivered": [], "alerts": []}
    monkeypatch.setattr(
        bot_module.amo_client, "update_lead_status_and_field", lambda *a: env["crm"].append(a)
    )

    async def deliver(task_id, deal_id, partner_id):
        env["delivered"].append(task_id)

    monkeypatch.setattr(bot_module.contact_delivery, "deliver_contact", deliver)
    monkeypatch.setattr(
        bot_module.report_webhook, "send_error_notification", lambda marker, message: env["alerts"].append(message)
    )
    return env


def test_edit_text_failure_does_not_stop_crm_and_delivery(claim_env):
    class BrokenMessage(FakeMessage):
        async def edit_text(self, text):
            raise RuntimeError("Bad Request: MESSAGE_TOO_LONG")

    asyncio.run(bot_module.handle_case_claim(FakeCallback("case:1", message=BrokenMessage())))
    assert len(claim_env["crm"]) == 1 and claim_env["delivered"] == [1]


def test_old_callback_answer_failure_does_not_stop_crm_and_delivery(claim_env):
    class OldCallback(FakeCallback):
        async def answer(self, text=None, show_alert=None):
            raise RuntimeError("Bad Request: query is too old and response timeout expired")

    asyncio.run(bot_module.handle_case_claim(OldCallback("case:1")))
    assert len(claim_env["crm"]) == 1 and claim_env["delivered"] == [1]


def test_long_case_text_shortened_with_claimed_suffix(claim_env):
    message = FakeMessage(text="а" * 5000)
    asyncio.run(bot_module.handle_case_claim(FakeCallback("case:1", message=message)))
    assert len(message.edited_text) <= 4096 and "✅ Взял:" in message.edited_text


def test_crm_retried_then_succeeds_without_alert(claim_env, monkeypatch, cases_repo):
    attempts = []

    def flaky(*args):
        attempts.append(args)
        if len(attempts) < 3:
            raise ConnectionError("Remote end closed connection without response")

    monkeypatch.setattr(bot_module.amo_client, "update_lead_status_and_field", flaky)
    asyncio.run(bot_module.handle_case_claim(FakeCallback("case:1")))
    assert len(attempts) == 3 and claim_env["alerts"] == []
    assert cases_repo.get_case(1).status == CaseStatus.CLAIMED


def test_crm_fails_three_times_alerts_and_still_delivers(claim_env, monkeypatch, cases_repo):
    attempts = []

    def broken(*args):
        attempts.append(args)
        raise ConnectionError("amo down")

    monkeypatch.setattr(bot_module.amo_client, "update_lead_status_and_field", broken)
    asyncio.run(bot_module.handle_case_claim(FakeCallback("case:1")))
    assert len(attempts) == 3 and len(claim_env["alerts"]) == 1
    assert claim_env["delivered"] == [1]
