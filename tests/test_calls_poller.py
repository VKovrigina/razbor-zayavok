from __future__ import annotations

import asyncio

from calls import poller


def test_poll_once_processes_every_lead(monkeypatch):
    monkeypatch.setattr(poller.amo_actions, "get_leads_in_stage", lambda: [{"id": 1}, {"id": 2}])
    processed = []

    async def fake_offer(lead, now):
        processed.append(lead["id"])
        return "offered"

    monkeypatch.setattr(poller.booking, "offer_slots_for_lead", fake_offer)

    asyncio.run(poller.poll_once())

    assert processed == [1, 2]


def test_poll_once_continues_after_one_lead_fails(monkeypatch):
    monkeypatch.setattr(poller.amo_actions, "get_leads_in_stage", lambda: [{"id": 1}, {"id": 2}])
    processed = []

    async def fake_offer(lead, now):
        if lead["id"] == 1:
            raise RuntimeError("boom")
        processed.append(lead["id"])
        return "offered"

    monkeypatch.setattr(poller.booking, "offer_slots_for_lead", fake_offer)

    asyncio.run(poller.poll_once())

    assert processed == [2]


def test_poll_once_with_no_leads_does_nothing(monkeypatch):
    monkeypatch.setattr(poller.amo_actions, "get_leads_in_stage", lambda: [])
    calls = []
    monkeypatch.setattr(poller.booking, "offer_slots_for_lead", lambda lead, now: calls.append(lead))

    asyncio.run(poller.poll_once())

    assert calls == []
