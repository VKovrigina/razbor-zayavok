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
    monkeypatch.setattr(state_machine.checklist, "mentions_messaging_work", lambda text: False)
    monkeypatch.setattr(state_machine.amo_actions, "get_lead_status_id", lambda deal_id: None)

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


def test_faq_answer_delivered_but_log_event_fails_still_counts_as_answered(repo, monkeypatch):
    """P-040: если сообщение реально доставлено, а repo.log_event упал — это НЕ должно
    считаться "ответа не было" (неверный текст задачи Варваре, инкремент не произошедший,
    хотя ответ реально ушёл клиенту)."""
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    faq_answer = "Точная цена после оценки."
    _patch_faq_match(monkeypatch, "faq_price", faq_answer)
    _make_deal_awaiting_reply(repo, 19)

    real_log_event = state_machine.repo.log_event

    def flaky_log_event(deal_id, direction, channel, text):
        if direction == "out":
            raise RuntimeError("log_event boom")
        return real_log_event(deal_id, direction, channel, text)

    monkeypatch.setattr(state_machine.repo, "log_event", flaky_log_event)

    question = "сколько это стоит?"
    _handle(19, question)

    deal = repo.get_deal(19)
    assert deal.status == Status.AWAITING_REPLY_1  # НЕ эскалировано — ответ реально доставлен
    assert deal.faq_cycle_count == 1  # инкремент произошёл, как при обычном успешном ответе
    assert len(sent_messages) == 1  # клиенту ушёл именно FAQ-ответ, ничего повторно/взамен
    task_texts = [t for _, t in manager_tasks]
    assert state_machine.templates.task_text_faq_answered(question, faq_answer) in task_texts
    assert state_machine.templates.TASK_TEXT_CLARIFICATION not in task_texts


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


def test_faq_cap_reached_does_not_unlock_before_escalation(repo, monkeypatch):
    """P-039: на cap-й итерации лок не должен сниматься через resume_awaiting_reply ДО того, как
    эскалация подтверждена — иначе конкурентный handle_incoming_reply мог бы стартовать
    дублирующий цикл в этом окне."""
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, "faq_price", "Точная цена после оценки.")
    _make_deal_awaiting_reply(repo, 20)

    resume_calls = []
    original_resume = state_machine.repo.resume_awaiting_reply

    def spy_resume(deal_id, next_action_at):
        resume_calls.append(deal_id)
        return original_resume(deal_id, next_action_at)

    monkeypatch.setattr(state_machine.repo, "resume_awaiting_reply", spy_resume)

    for _ in range(state_machine._FAQ_CYCLE_CAP - 1):
        _handle(20, "сколько это стоит?")
    assert len(resume_calls) == state_machine._FAQ_CYCLE_CAP - 1  # цикл продолжался — лок снят

    # Cap-я итерация — цикл НЕ продолжается, resume_awaiting_reply не должен вызываться.
    _handle(20, "сколько это стоит?")

    assert len(resume_calls) == state_machine._FAQ_CYCLE_CAP - 1  # без изменений
    deal = repo.get_deal(20)
    assert deal.status == Status.ESCALATED_AMBIGUOUS
    assert deal.in_progress is False  # снято через repo.escalate, не resume_awaiting_reply


def test_faq_cap_reached_stays_locked_if_escalation_fails(repo, monkeypatch):
    """P-039: если эскалация на cap-й итерации не проходит (после всех ретраев), сделка должна
    явно разблокироваться через unlock, а не оставаться неопределённо разлоченной с середины
    cap-проверки."""
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, "faq_price", "Точная цена после оценки.")
    _make_deal_awaiting_reply(repo, 21)

    for _ in range(state_machine._FAQ_CYCLE_CAP - 1):
        _handle(21, "сколько это стоит?")

    def failing_escalate(deal_id, status):
        raise RuntimeError("db down")

    monkeypatch.setattr(state_machine.repo, "escalate", failing_escalate)
    monkeypatch.setattr(state_machine, "_DB_WRITE_RETRY_DELAY_SECONDS", 0)

    _handle(21, "сколько это стоит?")

    deal = repo.get_deal(21)
    assert deal.status == Status.AWAITING_REPLY_1  # эскалация не прошла — статус не менялся
    assert deal.in_progress is False  # но явно разблокирована для повторной попытки
    assert deal.faq_cycle_count == state_machine._FAQ_CYCLE_CAP  # инкремент уже случился


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


def test_faq_no_match_escalates_silently_without_replying_to_client(repo, monkeypatch):
    """P-055: неопределённый вопрос без совпадения в базе знаний — бот клиенту не отвечает
    вовсе (реагирует только на вопросы, которые реально знает), но эскалация и задача Варваре
    происходят как обычно."""
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, None)
    _make_deal_awaiting_reply(repo, 4)

    _handle(4, "какой-то неизвестный вопрос")

    deal = repo.get_deal(4)
    assert deal.status == Status.ESCALATED_AMBIGUOUS
    assert deal.faq_cycle_count == 0
    assert sent_messages == []
    assert manager_tasks[-1][1] == state_machine.templates.TASK_TEXT_CLARIFICATION


def test_positive_reply_with_addition_includes_it_in_note_and_field(repo, monkeypatch):
    """Полное ТЗ пишется дважды (примечание для Варвары + custom-поле для "Выдача кейсов
    партнёрам") одним и тем же содержанием — но поле без эмодзи (партнёры видят его дословно),
    примечание с эмодзи (только Варвара внутри CRM). Содержательный ответ клиента добавляется
    строкой "Дополнение: ..." в обоих местах."""
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        state_machine.classify_client, "classify_sync", lambda text, case: ReplyCategory.POSITIVE
    )
    monkeypatch.setattr(state_machine.checklist, "describes_addition_to_case", lambda text: True)

    note_calls = []
    monkeypatch.setattr(
        state_machine.amo_actions, "add_note", lambda deal_id, text: note_calls.append((deal_id, text))
    )
    field_calls = []
    monkeypatch.setattr(
        state_machine.amo_actions,
        "set_full_spec_field",
        lambda deal_id, text: field_calls.append((deal_id, text)),
    )

    _make_deal_awaiting_reply(repo, 40)

    _handle(40, "Да, ещё нужно передавать статусы заказов")

    deal = repo.get_deal(40)
    assert deal.status == Status.ESCALATED_POSITIVE
    assert len(note_calls) == 1
    assert "Дополнение: Да, ещё нужно передавать статусы заказов" in note_calls[0][1]
    assert field_calls[0][1] == note_calls[0][1].replace("🔸", "")  # то же содержание, без эмодзи


def test_positive_reply_bare_agreement_excludes_addition_line(repo, monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        state_machine.classify_client, "classify_sync", lambda text, case: ReplyCategory.POSITIVE
    )
    monkeypatch.setattr(state_machine.checklist, "describes_addition_to_case", lambda text: False)

    note_calls = []
    monkeypatch.setattr(
        state_machine.amo_actions, "add_note", lambda deal_id, text: note_calls.append((deal_id, text))
    )
    field_calls = []
    monkeypatch.setattr(
        state_machine.amo_actions,
        "set_full_spec_field",
        lambda deal_id, text: field_calls.append((deal_id, text)),
    )

    _make_deal_awaiting_reply(repo, 41)

    _handle(41, "да, жду")

    assert "Дополнение" not in note_calls[0][1]
    assert field_calls[0][1] == note_calls[0][1].replace("🔸", "")  # то же содержание, без эмодзи


def test_positive_reply_full_spec_field_failure_does_not_block_escalation(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    monkeypatch.setattr(
        state_machine.classify_client, "classify_sync", lambda text, case: ReplyCategory.POSITIVE
    )
    monkeypatch.setattr(state_machine.checklist, "describes_addition_to_case", lambda text: False)

    def failing_set_full_spec_field(deal_id, text):
        raise RuntimeError("boom")

    monkeypatch.setattr(state_machine.amo_actions, "set_full_spec_field", failing_set_full_spec_field)

    _make_deal_awaiting_reply(repo, 42)

    _handle(42, "да")

    deal = repo.get_deal(42)
    assert deal.status == Status.ESCALATED_POSITIVE
    assert sent_messages == [state_machine.templates.REPLY_POSITIVE]


def _make_new_deal(repo, deal_id: int):
    repo.create_deal_new(deal_id, 900 + deal_id, "Клиент", "client_test", None, "amoCRM", "Кейс")


def _process_new_deal(deal_id: int):
    asyncio.run(state_machine.process_new_deal(deal_id))


def _patch_first_contact_success(monkeypatch):
    """Полностью детерминированная подготовка + отправка — без единого реального сетевого вызова
    (ни Anthropic, ни amoCRM, ни Telegram), чтобы тест не зависел от сети/квоты и не полз в
    реальный `mark_failed`+`create_manager_task` при случайной заминке внешнего API. Возвращает
    список вызовов `set_channel_tag` для проверки."""
    monkeypatch.setattr(state_machine.checklist, "assess", lambda stack_text, case_text: [])
    monkeypatch.setattr(state_machine.checklist, "assess_topic", lambda stack_text, case_text: [])
    monkeypatch.setattr(state_machine.checklist, "mentions_messaging_work", lambda case_text: False)
    monkeypatch.setattr(state_machine.amo_actions, "move_to_negotiations", lambda deal_id: None)

    channel_tag_calls = []
    monkeypatch.setattr(
        state_machine.amo_actions,
        "set_channel_tag",
        lambda deal_id, channel_value: channel_tag_calls.append((deal_id, channel_value)),
    )

    async def fake_send_first_contact(username, text):
        return 12345

    monkeypatch.setattr(state_machine.telegram_sender, "send_first_contact", fake_send_first_contact)

    return channel_tag_calls


def test_process_new_deal_happy_path_sends_and_advances(repo, monkeypatch):
    channel_tag_calls = _patch_first_contact_success(monkeypatch)
    _make_new_deal(repo, 10)

    _process_new_deal(10)

    deal = repo.get_deal(10)
    assert deal.status == Status.AWAITING_REPLY_1
    assert deal.channel == Channel.TELEGRAM
    assert channel_tag_calls == [(10, "telegram")]


def test_process_new_deal_channel_tag_failure_does_not_block_deal(repo, monkeypatch):
    """Тег канала — best-effort для соседнего проекта "Выдача кейсов к группу", не должен
    мешать основному сценарию, если amoCRM недоступен именно на этом шаге."""
    _patch_first_contact_success(monkeypatch)
    _make_new_deal(repo, 12)

    def failing_set_channel_tag(deal_id, channel_value):
        raise RuntimeError("boom")

    monkeypatch.setattr(state_machine.amo_actions, "set_channel_tag", failing_set_channel_tag)

    _process_new_deal(12)

    deal = repo.get_deal(12)
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


def test_incoming_log_event_failure_unlocks_and_aborts(repo, monkeypatch):
    """P-038: если зафиксировать входящее сообщение не удалось после нескольких попыток — сделка
    разблокируется, а не остаётся занятой навсегда; дальше обработка не идёт (классификация не
    вызывается)."""
    monkeypatch.setattr(state_machine, "_DB_WRITE_RETRY_DELAY_SECONDS", 0)
    _make_deal_awaiting_reply(repo, 20)

    classify_called = False

    def should_not_be_called(text, case):
        nonlocal classify_called
        classify_called = True
        return ReplyCategory.AMBIGUOUS

    monkeypatch.setattr(state_machine.classify_client, "classify_sync", should_not_be_called)

    real_log_event = state_machine.repo.log_event

    def failing_log_event(deal_id, direction, channel, text):
        if direction == "in":
            raise RuntimeError("database is locked")
        return real_log_event(deal_id, direction, channel, text)

    monkeypatch.setattr(state_machine.repo, "log_event", failing_log_event)

    _handle(20, "какой-то ответ")

    deal = repo.get_deal(20)
    assert deal.in_progress is False
    assert deal.status == Status.AWAITING_REPLY_1  # обработка не продолжилась
    assert classify_called is False


def test_restart_reminder_cycle_failure_unlocks_and_aborts(repo, monkeypatch):
    """P-038: тот же принцип для restart_reminder_cycle в FAQ-ветке — сбой не должен оставлять
    сделку заблокированной навсегда."""
    monkeypatch.setattr(state_machine, "_DB_WRITE_RETRY_DELAY_SECONDS", 0)
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, "faq_price", "Точная цена после оценки.")
    _make_deal_awaiting_reply(repo, 21)

    def failing_restart(deal_id, next_action_at):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(state_machine.repo, "restart_reminder_cycle", failing_restart)

    _handle(21, "сколько это стоит?")

    deal = repo.get_deal(21)
    assert deal.in_progress is False
    assert deal.status == Status.AWAITING_REPLY_1  # restart_reminder_cycle так и не зафиксировался
    assert len(sent_messages) == 1  # ответ клиенту всё же ушёл до сбоя
    assert len(manager_tasks) == 1  # задача на авто-ответ тоже успела создаться до сбоя


def _make_deal_escalated(repo, deal_id: int, status: Status):
    from core import timeutils

    repo.create_deal_new(deal_id, 900 + deal_id, "Клиент", "client_test", None, "amoCRM", "Кейс")
    repo.set_awaiting_first_sent(
        deal_id, Channel.TELEGRAM.value, 12345, timeutils.to_iso(timeutils.utcnow())
    )
    repo.escalate(deal_id, status)


def test_post_positive_escalation_faq_match_answers_without_followup_or_task(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, "faq_price", "Точная цена после оценки.")
    _make_deal_escalated(repo, 30, Status.ESCALATED_POSITIVE)

    _handle(30, "а сколько всё-таки стоит?")

    deal = repo.get_deal(30)
    assert deal.status == Status.ESCALATED_POSITIVE  # статус не меняется
    assert deal.in_progress is False
    assert sent_messages == ["Точная цена после оценки."]  # БЕЗ закрывающего вопроса
    assert manager_tasks == []  # БЕЗ новой задачи


def test_post_positive_escalation_no_match_sends_fixed_reply_without_task(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, None)
    _make_deal_escalated(repo, 31, Status.ESCALATED_POSITIVE)

    _handle(31, "вопрос, которого нет в базе")

    deal = repo.get_deal(31)
    assert deal.status == Status.ESCALATED_POSITIVE
    assert sent_messages == [state_machine.templates.REPLY_NO_FAQ_MATCH_AFTER_POSITIVE]
    assert manager_tasks == []


def test_deal_taken_by_partner_stays_fully_silent(repo, monkeypatch):
    """P-056: как только партнёр забрал сделку (реальный этап amoCRM 'взят партнёром'), бот
    больше не отвечает даже на вопросы, которые знает через FAQ — партнёр ведёт клиента сам."""
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    partner_stage_id = state_machine.settings.amocrm_stage_taken_by_partner_id
    monkeypatch.setattr(
        state_machine.amo_actions, "get_lead_status_id", lambda deal_id: partner_stage_id
    )
    faq_called = False

    def should_not_be_called(text, case):
        nonlocal faq_called
        faq_called = True
        return "faq_price"

    monkeypatch.setattr(state_machine.faq_client, "match_faq_sync", should_not_be_called)
    _make_deal_escalated(repo, 33, Status.ESCALATED_POSITIVE)

    _handle(33, "а сколько всё-таки стоит?")

    deal = repo.get_deal(33)
    assert deal.status == Status.ESCALATED_POSITIVE
    assert sent_messages == []
    assert manager_tasks == []
    assert faq_called is False


def test_other_escalated_statuses_remain_fully_silent(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    _patch_faq_match(monkeypatch, "faq_price", "Точная цена после оценки.")
    _make_deal_escalated(repo, 32, Status.ESCALATED_NEGATIVE)

    _handle(32, "у вас есть ответ на мой вопрос?")

    assert repo.get_deal(32).status == Status.ESCALATED_NEGATIVE
    assert sent_messages == []
    assert manager_tasks == []


# --- Предупреждение о тарифе на "операции" (работа с сообщениями), P-052 ---

def test_process_new_deal_messaging_work_detected_sends_second_message_and_flags(repo, monkeypatch):
    _patch_first_contact_success(monkeypatch)
    monkeypatch.setattr(state_machine.checklist, "mentions_messaging_work", lambda case_text: True)

    first_contact_texts = []

    async def fake_send_first_contact(username, text):
        first_contact_texts.append(text)
        return 12345

    monkeypatch.setattr(state_machine.telegram_sender, "send_first_contact", fake_send_first_contact)

    sent_replies = []

    async def fake_send_reply(peer_id, text):
        sent_replies.append(text)

    monkeypatch.setattr(state_machine.telegram_sender, "send_reply", fake_send_reply)

    tag_calls = []
    monkeypatch.setattr(
        state_machine.amo_actions,
        "set_messaging_tariff_tag",
        lambda deal_id: tag_calls.append(deal_id),
    )

    _make_new_deal(repo, 13)

    _process_new_deal(13)

    deal = repo.get_deal(13)
    assert deal.status == Status.AWAITING_REPLY_1
    assert deal.messaging_tariff_flagged is True
    assert tag_calls == [13]
    assert sent_replies == [state_machine.templates.MESSAGING_TARIFF_WARNING]
    assert len(first_contact_texts) == 1
    assert state_machine.templates.MESSAGING_TARIFF_CLOSING_NOTE in first_contact_texts[0]


def test_process_new_deal_no_messaging_work_sends_only_first_message(repo, monkeypatch):
    _patch_first_contact_success(monkeypatch)  # mentions_messaging_work по умолчанию False
    tag_calls = []
    monkeypatch.setattr(
        state_machine.amo_actions,
        "set_messaging_tariff_tag",
        lambda deal_id: tag_calls.append(deal_id),
    )
    send_reply_called = False

    async def should_not_be_called(peer_id, text):
        nonlocal send_reply_called
        send_reply_called = True

    monkeypatch.setattr(state_machine.telegram_sender, "send_reply", should_not_be_called)

    _make_new_deal(repo, 14)

    _process_new_deal(14)

    deal = repo.get_deal(14)
    assert deal.messaging_tariff_flagged is False
    assert tag_calls == []
    assert send_reply_called is False


def test_process_new_deal_messaging_warning_send_failure_does_not_block_first_message(repo, monkeypatch):
    _patch_first_contact_success(monkeypatch)
    monkeypatch.setattr(state_machine.checklist, "mentions_messaging_work", lambda case_text: True)

    first_contact_texts = []

    async def fake_send_first_contact(username, text):
        first_contact_texts.append(text)
        return 12345

    monkeypatch.setattr(state_machine.telegram_sender, "send_first_contact", fake_send_first_contact)

    async def failing_send_reply(peer_id, text):
        raise RuntimeError("boom")

    monkeypatch.setattr(state_machine.telegram_sender, "send_reply", failing_send_reply)

    _make_new_deal(repo, 15)

    _process_new_deal(15)

    deal = repo.get_deal(15)
    assert deal.status == Status.AWAITING_REPLY_1  # первое сообщение всё равно ушло
    assert len(first_contact_texts) == 1
    assert deal.messaging_tariff_flagged is True  # флаг — независимый best-effort шаг


def test_late_messaging_mention_sends_warning_and_waits_without_classifying(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    monkeypatch.setattr(state_machine.checklist, "mentions_messaging_work", lambda text: True)

    classify_called = False

    def should_not_be_called(text, case):
        nonlocal classify_called
        classify_called = True
        return ReplyCategory.AMBIGUOUS

    monkeypatch.setattr(state_machine.classify_client, "classify_sync", should_not_be_called)

    tag_calls = []
    monkeypatch.setattr(
        state_machine.amo_actions,
        "set_messaging_tariff_tag",
        lambda deal_id: tag_calls.append(deal_id),
    )

    _make_deal_awaiting_reply(repo, 22)

    _handle(22, "а можно ещё, чтобы ИИ агент отвечал клиентам?")

    deal = repo.get_deal(22)
    assert deal.messaging_tariff_flagged is True
    assert tag_calls == [22]
    assert sent_messages == [state_machine.templates.MESSAGING_TARIFF_WARNING]
    assert classify_called is False
    assert deal.status == Status.AWAITING_REPLY_1  # не эскалировано, ждём отдельный ответ
    assert deal.in_progress is False
    assert manager_tasks == []


def _make_deal_awaiting_reply_flagged(repo, deal_id: int):
    _make_deal_awaiting_reply(repo, deal_id)
    repo.set_messaging_tariff_flagged(deal_id, True)


def test_messaging_flagged_positive_reply_creates_extra_manager_task(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    monkeypatch.setattr(
        state_machine.classify_client, "classify_sync", lambda text, case: ReplyCategory.POSITIVE
    )
    monkeypatch.setattr(state_machine.checklist, "describes_addition_to_case", lambda text: False)
    _make_deal_awaiting_reply_flagged(repo, 23)

    _handle(23, "да, готовы")

    deal = repo.get_deal(23)
    assert deal.status == Status.ESCALATED_POSITIVE
    task_texts = [t for _, t in manager_tasks]
    assert state_machine.templates.TASK_TEXT_FINALIZE_SPEC in task_texts
    assert state_machine.templates.TASK_TEXT_MESSAGING_POSITIVE in task_texts
    assert state_machine.templates.MESSAGING_TARIFF_WARNING not in sent_messages  # не дублируем


def test_messaging_flagged_negative_reply_creates_extra_manager_task(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    monkeypatch.setattr(
        state_machine.classify_client, "classify_sync", lambda text, case: ReplyCategory.NEGATIVE
    )
    _make_deal_awaiting_reply_flagged(repo, 24)

    _handle(24, "нет, не готовы по такой цене")

    deal = repo.get_deal(24)
    assert deal.status == Status.ESCALATED_NEGATIVE
    task_texts = [t for _, t in manager_tasks]
    assert state_machine.templates.TASK_TEXT_NEGATIVE_CLIENT in task_texts
    assert state_machine.templates.TASK_TEXT_MESSAGING_NEGATIVE in task_texts
    # Отказ именно от тарифа на сообщения — мягкий ответ, а не обычный REPLY_NEGATIVE.
    assert sent_messages == [state_machine.templates.REPLY_MESSAGING_NEGATIVE]


def test_negative_reply_without_messaging_flag_uses_standard_reply(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    monkeypatch.setattr(
        state_machine.classify_client, "classify_sync", lambda text, case: ReplyCategory.NEGATIVE
    )
    _make_deal_awaiting_reply(repo, 26)  # не помечена флагом

    _handle(26, "неактуально, отбой")

    assert sent_messages == [state_machine.templates.REPLY_NEGATIVE]


def test_messaging_not_flagged_no_extra_manager_task(repo, monkeypatch):
    manager_tasks, sent_messages = _patch_common(monkeypatch)
    monkeypatch.setattr(
        state_machine.classify_client, "classify_sync", lambda text, case: ReplyCategory.POSITIVE
    )
    monkeypatch.setattr(state_machine.checklist, "describes_addition_to_case", lambda text: False)
    _make_deal_awaiting_reply(repo, 25)  # не помечена флагом

    _handle(25, "да, готовы")

    task_texts = [t for _, t in manager_tasks]
    assert state_machine.templates.TASK_TEXT_MESSAGING_POSITIVE not in task_texts
    assert state_machine.templates.TASK_TEXT_MESSAGING_NEGATIVE not in task_texts
