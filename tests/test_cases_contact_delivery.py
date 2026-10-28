import asyncio

from cases import contact_delivery
from cases.models import CaseStatus


def _lead_with_tag(tag_name, full_spec="Текст ТЗ"):
    return {
        "_embedded": {"tags": [{"name": tag_name}], "contacts": [{"id": 900}]},
        "custom_fields_values": [
            {"field_id": contact_delivery.settings.amocrm_field_id_full_spec, "values": [{"value": full_spec}]}
        ],
    }


async def _async_noop(*args, **kwargs):
    return None


def _patch_extract_lead_data(monkeypatch, telegram_username="client_username", name="Иван Клиент", email="ivan@example.com"):
    monkeypatch.setattr(
        contact_delivery,
        "extract_lead_data",
        lambda lead: {
            "telegram_username": telegram_username,
            "contact_name": name,
            "email_address": email,
        },
    )


def _fake_create_group(link="https://t.me/+link", warnings=None):
    async def _create(partner_id, title, intro_text):
        return link, list(warnings or [])

    return _create


def test_deliver_contact_tg_branch_creates_group_and_sets_group_created(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(contact_delivery.amo_client, "get_lead", lambda deal_id, with_contacts=False: _lead_with_tag("ТГ"))
    _patch_extract_lead_data(monkeypatch)
    monkeypatch.setattr(contact_delivery.group_creator, "create_group_with_invite", _fake_create_group())

    sent = []

    async def fake_send_dm(target, text):
        sent.append((target, text))

    monkeypatch.setattr(contact_delivery.group_creator, "send_dm", fake_send_dm)

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert cases_repo.get_case(1).status == CaseStatus.GROUP_CREATED


def test_deliver_contact_tg_branch_passes_client_nick_as_group_title(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(contact_delivery.amo_client, "get_lead", lambda deal_id, with_contacts=False: _lead_with_tag("ТГ"))
    _patch_extract_lead_data(monkeypatch, telegram_username="vr_kvr")

    titles = []

    async def fake_create_group(partner_id, title, intro_text):
        titles.append(title)
        return "https://t.me/+link", []

    monkeypatch.setattr(contact_delivery.group_creator, "create_group_with_invite", fake_create_group)
    monkeypatch.setattr(contact_delivery.group_creator, "send_dm", _async_noop)

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert titles == ["@vr_kvr & Альбато"]


def test_deliver_contact_tg_branch_sends_distinct_messages_to_client_and_partner(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(
        contact_delivery.amo_client,
        "get_lead",
        lambda deal_id, with_contacts=False: _lead_with_tag("ТГ", full_spec="🔸Сервисы: amoCRM"),
    )
    _patch_extract_lead_data(monkeypatch, telegram_username="client_username")
    monkeypatch.setattr(contact_delivery.group_creator, "create_group_with_invite", _fake_create_group("https://t.me/+link"))

    sent = []

    async def fake_send_dm(target, text):
        sent.append((target, text))

    monkeypatch.setattr(contact_delivery.group_creator, "send_dm", fake_send_dm)

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    by_target = dict(sent)
    assert "client_username" in by_target
    assert 555 in by_target
    assert by_target["client_username"] == (
        "На вашу заявку отреагировал наш партнер. Вот чат с ним для обсуждения интеграции. "
        "Присоединяйтесь! https://t.me/+link"
    )
    assert by_target[555] == "Чат для обсуждения интеграции:\n🔸Сервисы: amoCRM\nhttps://t.me/+link"


def test_deliver_contact_tg_branch_posts_case_intro_into_chat(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(
        contact_delivery.amo_client, "get_lead",
        lambda deal_id, with_contacts=False: _lead_with_tag("ТГ", full_spec="🔸Сервисы: amoCRM"),
    )
    _patch_extract_lead_data(monkeypatch)
    intros = []

    async def fake_create_group(partner_id, title, intro_text):
        intros.append(intro_text)
        return "https://t.me/+link", []

    monkeypatch.setattr(contact_delivery.group_creator, "create_group_with_invite", fake_create_group)
    monkeypatch.setattr(contact_delivery.group_creator, "send_dm", _async_noop)

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert intros == ["Чат для обсуждения\n\n🔸Сервисы: amoCRM"]


def test_deliver_contact_tg_branch_optional_step_warning_alerts_but_succeeds(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(contact_delivery.amo_client, "get_lead", lambda deal_id, with_contacts=False: _lead_with_tag("ТГ"))
    _patch_extract_lead_data(monkeypatch)
    monkeypatch.setattr(
        contact_delivery.group_creator, "create_group_with_invite",
        _fake_create_group(warnings=["не удалось добавить чат в папку «Настройки»"]),
    )
    monkeypatch.setattr(contact_delivery.group_creator, "send_dm", _async_noop)
    alerts = []
    monkeypatch.setattr(
        contact_delivery.report_webhook, "send_error_notification",
        lambda marker, message: alerts.append((marker, message)),
    )

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert cases_repo.get_case(1).status == CaseStatus.GROUP_CREATED
    assert len(alerts) == 1 and alerts[0][0] == "100" and "Настройки" in alerts[0][1]


def test_deliver_contact_tg_branch_failure_alerts_and_sets_failed_group_creation(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(contact_delivery.amo_client, "get_lead", lambda deal_id, with_contacts=False: _lead_with_tag("ТГ"))
    _patch_extract_lead_data(monkeypatch)

    async def failing_create_group(partner_id, title, intro_text):
        raise RuntimeError("telethon недоступен")

    monkeypatch.setattr(contact_delivery.group_creator, "create_group_with_invite", failing_create_group)

    sent = []
    monkeypatch.setattr(
        contact_delivery.report_webhook,
        "send_error_notification",
        lambda marker, message: sent.append((marker, message)),
    )

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert cases_repo.get_case(1).status == CaseStatus.FAILED_GROUP_CREATION
    assert len(sent) == 1
    assert sent[0][0] == "100"


def test_deliver_contact_tg_branch_does_not_notify_partner_on_failure(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(contact_delivery.amo_client, "get_lead", lambda deal_id, with_contacts=False: _lead_with_tag("ТГ"))
    _patch_extract_lead_data(monkeypatch)

    async def failing_create_group(partner_id, title, intro_text):
        raise RuntimeError("telethon недоступен")

    monkeypatch.setattr(contact_delivery.group_creator, "create_group_with_invite", failing_create_group)
    monkeypatch.setattr(contact_delivery.report_webhook, "send_error_notification", lambda marker, message: None)

    sent = []

    async def fake_send_dm(target, text):
        sent.append(target)

    monkeypatch.setattr(contact_delivery.group_creator, "send_dm", fake_send_dm)

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert sent == []  # партнёр не уведомляется об ошибке напрямую


def test_deliver_contact_email_branch_sends_name_and_email_sets_contact_sent(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(contact_delivery.amo_client, "get_lead", lambda deal_id, with_contacts=False: _lead_with_tag("Почта"))
    _patch_extract_lead_data(monkeypatch, name="Иван Клиент", email="ivan@example.com")

    sent = []

    async def fake_send_dm(target, text):
        sent.append((target, text))

    monkeypatch.setattr(contact_delivery.group_creator, "send_dm", fake_send_dm)

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert cases_repo.get_case(1).status == CaseStatus.CONTACT_SENT
    assert len(sent) == 1
    assert sent[0][0] == 555
    assert "Иван Клиент" in sent[0][1]
    assert "ivan@example.com" in sent[0][1]
    assert "Текст ТЗ" in sent[0][1]  # сам кейс, а не только контакт


def test_deliver_contact_email_branch_failure_alerts_and_sets_failed_contact_send(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(contact_delivery.amo_client, "get_lead", lambda deal_id, with_contacts=False: _lead_with_tag("Почта"))
    _patch_extract_lead_data(monkeypatch)

    async def failing_send_dm(target, text):
        raise RuntimeError("telethon недоступен")

    monkeypatch.setattr(contact_delivery.group_creator, "send_dm", failing_send_dm)
    sent = []
    monkeypatch.setattr(
        contact_delivery.report_webhook,
        "send_error_notification",
        lambda marker, message: sent.append((marker, message)),
    )

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert cases_repo.get_case(1).status == CaseStatus.FAILED_CONTACT_SEND
    assert len(sent) == 1


def test_deliver_contact_unknown_tag_alerts_and_sets_failed_channel_unknown(cases_repo, monkeypatch):
    # Найдено на реальных сделках 2026-07-31: сделки, заведённые вручную (не через main.py),
    # могут не иметь тега «ТГ»/«Почта» — раньше это тихо игнорировалось (взятие оставалось
    # CLAIMED навсегда без единого сигнала). Теперь — алерт + FAILED_CHANNEL_UNKNOWN.
    cases_repo.insert_posted(1, 100)
    monkeypatch.setattr(contact_delivery.amo_client, "get_lead", lambda deal_id, with_contacts=False: _lead_with_tag("СовсемДругойТег"))

    calls = []
    monkeypatch.setattr(contact_delivery.group_creator, "create_group_with_invite", lambda partner_id, title: calls.append(1))
    monkeypatch.setattr(contact_delivery.group_creator, "send_dm", _async_noop)

    sent = []
    monkeypatch.setattr(
        contact_delivery.report_webhook,
        "send_error_notification",
        lambda marker, message: sent.append((marker, message)),
    )

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert calls == []
    assert cases_repo.get_case(1).status == CaseStatus.FAILED_CHANNEL_UNKNOWN
    assert len(sent) == 1
    assert sent[0][0] == "100"


def test_deliver_contact_no_tags_at_all_alerts_and_sets_failed_channel_unknown(cases_repo, monkeypatch):
    # Вариант без тегов вообще (реальный случай — сделка 39665733, tags=[]), не только "другой тег".
    cases_repo.insert_posted(1, 100)
    lead = _lead_with_tag("ТГ")
    lead["_embedded"]["tags"] = []
    monkeypatch.setattr(contact_delivery.amo_client, "get_lead", lambda deal_id, with_contacts=False: lead)

    monkeypatch.setattr(
        contact_delivery.report_webhook, "send_error_notification", lambda marker, message: None
    )

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert cases_repo.get_case(1).status == CaseStatus.FAILED_CHANNEL_UNKNOWN


def test_deliver_contact_get_lead_failure_alerts_with_partner_nick(cases_repo, monkeypatch):
    cases_repo.insert_posted(1, 100)
    cases_repo.claim_case(1, 555, "@ivan_partner")
    attempts = []

    def broken_get_lead(deal_id, with_contacts=False):
        attempts.append(deal_id)
        raise ConnectionError("amo down")

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(contact_delivery.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(contact_delivery.amo_client, "get_lead", broken_get_lead)
    alerts = []
    monkeypatch.setattr(
        contact_delivery.report_webhook, "send_error_notification", lambda marker, message: alerts.append(message)
    )

    asyncio.run(contact_delivery.deliver_contact(1, 100, 555))

    assert len(attempts) == 3
    assert cases_repo.get_case(1).status == CaseStatus.FAILED_CONTACT_SEND
    assert len(alerts) == 1 and "@ivan_partner" in alerts[0]
