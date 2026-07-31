import requests

from amo.client import amo_client


def test_list_open_tasks_returns_single_page(monkeypatch):
    monkeypatch.setattr(
        amo_client,
        "get",
        lambda path, params=None: {"_embedded": {"tasks": [{"id": 1}, {"id": 2}]}},
    )
    assert amo_client.list_open_tasks(12195858) == [{"id": 1}, {"id": 2}]


def test_list_open_tasks_paginates_until_short_page(monkeypatch):
    pages = [
        {"_embedded": {"tasks": [{"id": i} for i in range(250)]}},
        {"_embedded": {"tasks": [{"id": 999}]}},
    ]
    calls = []

    def fake_get(path, params=None):
        calls.append(params["page"])
        return pages[params["page"] - 1]

    monkeypatch.setattr(amo_client, "get", fake_get)
    tasks = amo_client.list_open_tasks(12195858)
    assert len(tasks) == 251
    assert calls == [1, 2]


def test_list_open_tasks_returns_empty_list_when_no_tasks(monkeypatch):
    monkeypatch.setattr(amo_client, "get", lambda path, params=None: {"_embedded": {"tasks": []}})
    assert amo_client.list_open_tasks(12195858) == []


def test_list_open_tasks_stops_at_max_pages_safety_limit(monkeypatch):
    full_page = {"_embedded": {"tasks": [{"id": i} for i in range(250)]}}
    calls = []

    def fake_get(path, params=None):
        calls.append(params["page"])
        return full_page

    monkeypatch.setattr(amo_client, "get", fake_get)
    tasks = amo_client.list_open_tasks(12195858)
    assert len(calls) == 40
    assert len(tasks) == 40 * 250


def test_get_lead_without_contacts_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(amo_client, "get", lambda path, params=None: calls.append((path, params)) or {})

    amo_client.get_lead(42)

    assert calls == [("/api/v4/leads/42", None)]


def test_get_lead_with_contacts_when_requested(monkeypatch):
    calls = []
    monkeypatch.setattr(amo_client, "get", lambda path, params=None: calls.append((path, params)) or {})

    amo_client.get_lead(42, with_contacts=True)

    assert calls == [("/api/v4/leads/42", {"with": "contacts"})]


def test_complete_task_sends_patch_with_is_completed_true(monkeypatch):
    patch_calls = []
    monkeypatch.setattr(amo_client, "patch", lambda path, json: patch_calls.append((path, json)))

    amo_client.complete_task(555)

    assert patch_calls == [("/api/v4/tasks/555", {"is_completed": True})]


def test_update_lead_status_and_field_sends_single_patch_with_both_keys(monkeypatch):
    patch_calls = []
    monkeypatch.setattr(amo_client, "patch", lambda path, json: patch_calls.append((path, json)))

    amo_client.update_lead_status_and_field(42, 82404578, 968087, "@partner_nick")

    assert patch_calls == [
        (
            "/api/v4/leads/42",
            {
                "status_id": 82404578,
                "custom_fields_values": [{"field_id": 968087, "values": [{"value": "@partner_nick"}]}],
            },
        )
    ]


def test_update_lead_status_and_field_raises_on_http_error(monkeypatch):
    class FakeResponse:
        content = b""

        def raise_for_status(self):
            raise requests.HTTPError("500 Server Error")

    monkeypatch.setattr(requests, "request", lambda method, url, headers, timeout, **kw: FakeResponse())
    monkeypatch.setattr("amo.client.get_access_token", lambda: "fake-token")

    try:
        amo_client.update_lead_status_and_field(42, 1, 2, "x")
        assert False, "expected HTTPError to propagate"
    except requests.HTTPError:
        pass
