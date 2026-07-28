import asyncio

from core import state_machine
from db.models import Channel, ReplyCategory, Status


def _make_deal_awaiting_reply(repo, deal_id: int):
    from core import timeutils

    repo.create_deal_new(deal_id, 900 + deal_id, "Клиент", "client_test", None, "amoCRM", "Кейс")
    repo.set_awaiting_first_sent(
        deal_id, Channel.TELEGRAM.value, 12345, timeutils.to_iso(timeutils.utcnow())
    )


def _handle(deal_id: int, text: str):
    asyncio.run(state_machine.handle_incoming_reply(deal_id, text, Channel.TELEGRAM))


def _patch_common(monkeypatch):
    """Заглушки внешних эффектов (amoCRM/классификация/Telegram) — FAQ-ветку handle_incoming_reply
    можно проверять изолированно от реальных API. Возвращает списки для проверки побочных
    эффектов."""
    monkeypatch.setattr(state_machine.amo_actions, "move_to_clarification", lambda deal_id: None)
    monkeypatch.setattr(state_machine.amo_actions, "move_to_manual_review", lambda deal_id: None)
    monkeypatch.setattr(state_machine.amo_actions, "add_note", lambda deal_id, text: None)

    manager_tasks = []
    monkeypatch.setattr(
        state_machine.amo_actions,
        "create_manager_task",
        lambda deal_id, text: manager_tasks.append((deal_id, text)),
    )

    monkeypatch.setattr(
        state_machine.classify_client, "classify_sync", lambda text, case: ReplyCategory.AMBIGUOUS
    )

    sent_messages = []

    async def fake_send_reply(peer_id, text):
        sent_messages.append(text)

    monkeypatch.setattr(state_machine.telegram_sender, "send_reply", fake_send_reply)

    return manager_tasks, sent_messages


def _patch_faq_match(monkeypatch, faq_id, answer=None):
    monkeypatch.setattr(state_machine.faq_client, "match_faq_sync", lambda text, case: faq_id)
    if faq_id is not None:
        monkeypatch.setattr(state_machine.faq_client, "get_answer", lambda fid: answer)


def test_faq_match_answers_and_waits_without_escalating(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, "faq_price", "Точная цена после оценки.")
    _make_deal_awaiting_reply(repo, 1)

    _handle(1, "сколько это стоит?")

    deal = repo.get_deal(1)
    assert deal.status == Status.AWAITING_REPLY_1  # НЕ эскалировано
    assert deal.in_progress is False
    assert deal.faq_cycle_count == 1
    assert len(sent_messages) == 1
    assert sent_messages[0].startswith("Точная цена после оценки.")
    assert len(manager_tasks) == 1  # задача Варваре на каждый автоответ


def test_faq_cap_reached_forces_escalation(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, "faq_price", "Точная цена после оценки.")
    _make_deal_awaiting_reply(repo, 2)

    for _ in range(state_machine._FAQ_CYCLE_CAP - 1):
        _handle(2, "сколько это стоит?")
        assert repo.get_deal(2).status == Status.AWAITING_REPLY_1

    # Последний, cap-й подряд отвеченный вопрос — предел исчерпан, принудительная эскалация.
    _handle(2, "сколько это стоит?")

    deal = repo.get_deal(2)
    assert deal.status == Status.ESCALATED_AMBIGUOUS
    assert deal.faq_cycle_count == state_machine._FAQ_CYCLE_CAP
    # Ответ+вопрос отправлялся на каждой итерации, включая последнюю — но не дважды на последней.
    assert len(sent_messages) == state_machine._FAQ_CYCLE_CAP
    task_texts = [t for _, t in manager_tasks]
    assert state_machine.templates.TASK_TEXT_FAQ_LIMIT_REACHED in task_texts


def test_faq_match_but_send_fails_falls_back_to_normal_escalation(repo, monkeypatch):
    """P-019: если отправить автоответ не удалось, restart_reminder_cycle не вызывается — сделка
    уходит в обычную эскалацию, а не остаётся молча ждать несуществующего ответа."""
    manager_tasks, _sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, "faq_price", "Точная цена после оценки.")
    _make_deal_awaiting_reply(repo, 3)

    async def failing_send_reply(peer_id, text):
        raise RuntimeError("boom")

    monkeypatch.setattr(state_machine.telegram_sender, "send_reply", failing_send_reply)

    _handle(3, "сколько это стоит?")

    deal = repo.get_deal(3)
    assert deal.status == Status.ESCALATED_AMBIGUOUS
    assert deal.faq_cycle_count == 0  # restart_reminder_cycle не вызывался
    # Обычная эскалация (не FAQ-специфичная задача) — ответа клиенту так и не было отправлено.
    assert manager_tasks == [(3, state_machine.templates.TASK_TEXT_CLARIFICATION)]


def test_faq_no_match_behaves_as_before(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, None)
    _make_deal_awaiting_reply(repo, 4)

    _handle(4, "какой-то неизвестный вопрос")

    deal = repo.get_deal(4)
    assert deal.status == Status.ESCALATED_AMBIGUOUS
    assert deal.faq_cycle_count == 0
    assert sent_messages == [state_machine.templates.REPLY_AMBIGUOUS]
    assert manager_tasks[-1][1] == state_machine.templates.TASK_TEXT_CLARIFICATION


def _make_new_deal(repo, deal_id: int):
    repo.create_deal_new(deal_id, 900 + deal_id, "Клиент", "client_test", None, "amoCRM", "Кейс")


def _process_new_deal(deal_id: int):
    asyncio.run(state_machine.process_new_deal(deal_id))


def _patch_first_contact_success(monkeypatch):
    monkeypatch.setattr(state_machine.amo_actions, "move_to_negotiations", lambda deal_id: None)

    async def fake_send_first_contact(username, text):
        return 12345

    monkeypatch.setattr(state_machine.telegram_sender, "send_first_contact", fake_send_first_contact)


def test_process_new_deal_happy_path_sends_and_advances(repo, monkeypatch):
    _patch_first_contact_success(monkeypatch)
    _make_new_deal(repo, 10)

    _process_new_deal(10)

    deal = repo.get_deal(10)
    assert deal.status == Status.AWAITING_REPLY_1
    assert deal.channel == Channel.TELEGRAM


def test_process_new_deal_prep_failure_marks_failed_without_sending(repo, monkeypatch):
    """P-016: сбой ДО отправки (чек-лист/шаблон) не должен оставлять сделку навсегда в NEW —
    сразу FAILED + задача Варваре, сообщение клиенту не отправляется вовсе."""
    _patch_first_contact_success(monkeypatch)
    _make_new_deal(repo, 11)

    def failing_assess(stack_text, case_text):
        raise RuntimeError("boom")

    monkeypatch.setattr(state_machine.checklist, "assess", failing_assess)

    send_first_contact_called = False

    async def should_not_be_called(username, text):
        nonlocal send_first_contact_called
        send_first_contact_called = True
        return 12345

    monkeypatch.setattr(state_machine.telegram_sender, "send_first_contact", should_not_be_called)

    manager_tasks = []
    monkeypatch.setattr(
        state_machine.amo_actions,
        "create_manager_task",
        lambda deal_id, text: manager_tasks.append((deal_id, text)),
    )

    _process_new_deal(11)

    deal = repo.get_deal(11)
    assert deal.status == Status.FAILED
    assert send_first_contact_called is False
    assert manager_tasks == [(11, state_machine.templates.TASK_TEXT_PREP_FAILED)]
