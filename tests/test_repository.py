from db.models import Channel, Status


def test_create_and_get_deal(repo):
    repo.create_deal_new(1, 100, "Иван", "ivan_test", None, "Bitrix24", "Кейс")
    deal = repo.get_deal(1)
    assert deal is not None
    assert deal.status == Status.NEW
    assert deal.telegram_username == "ivan_test"


def test_create_deal_new_flags_telegram_channel_when_username_present(repo):
    repo.create_deal_new(101, 100, "Иван", "ivan_test", "ivan@example.com", "Bitrix24", "Кейс")
    deal = repo.get_deal(101)
    assert deal.channel == Channel.TELEGRAM


def test_create_deal_new_flags_email_channel_when_no_telegram_username(repo):
    repo.create_deal_new(102, 100, "Иван", None, "ivan@example.com", "Bitrix24", "Кейс")
    deal = repo.get_deal(102)
    assert deal.channel == Channel.EMAIL


def test_conflict_detected_then_cleared_after_escalation(repo):
    repo.create_deal_new(1, 100, "Иван", "ivan_test", None, "Bitrix24", "Кейс")

    conflict = repo.find_conflicting_active_deal("ivan_test", None, exclude_deal_id=2)
    assert conflict is not None
    assert conflict.deal_id == 1

    repo.escalate(1, Status.ESCALATED_POSITIVE)

    conflict_after = repo.find_conflicting_active_deal("ivan_test", None, exclude_deal_id=2)
    assert conflict_after is None


def test_try_lock_prevents_double_processing(repo):
    repo.create_deal_new(2, 200, "Петр", "petr_test", None, "amoCRM", "Кейс 2")

    assert repo.try_lock(2) is True
    assert repo.try_lock(2) is False  # уже занято

    repo.unlock(2)
    assert repo.try_lock(2) is True


def test_list_due_rows_returns_awaiting_deals(repo):
    from core import timeutils

    repo.create_deal_new(3, 300, "Ольга", "olga_test", None, "amoCRM", "Кейс 3")
    repo.set_awaiting_first_sent(3, "telegram", 999, timeutils.to_iso(timeutils.utcnow()))

    due = repo.list_due_rows(timeutils.to_iso(timeutils.utcnow()))
    assert any(d.deal_id == 3 for d in due)


def test_daily_send_cap_enforced(repo):
    results = [repo.increment_and_check_daily_cap(3) for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_restart_reminder_cycle_resets_to_awaiting_reply_1(repo):
    from core import timeutils

    repo.create_deal_new(4, 400, "Анна", "anna_test", None, "amoCRM", "Кейс 4")
    repo.set_awaiting_first_sent(4, "telegram", 111, timeutils.to_iso(timeutils.utcnow()))
    repo.advance_to_reminder2(4, timeutils.to_iso(timeutils.utcnow()))

    next_action_at = timeutils.to_iso(timeutils.utcnow())
    repo.restart_reminder_cycle(4, next_action_at)

    deal = repo.get_deal(4)
    assert deal.status == Status.AWAITING_REPLY_1
    assert deal.reminder_count == 0
    assert deal.in_progress is False
    assert deal.next_action_at == next_action_at


def test_create_deal_new_initializes_faq_cycle_count_to_zero(repo):
    repo.create_deal_new(41, 400, "Анна", "anna_test", None, "amoCRM", "Кейс 4")
    assert repo.get_deal(41).faq_cycle_count == 0


def test_restart_reminder_cycle_increments_faq_cycle_count_and_returns_it(repo):
    """P-020: вызывающая сторона (core/state_machine.py) решает по возвращённому значению, не
    пора ли принудительно эскалировать вместо очередного автоответа на встречный вопрос."""
    from core import timeutils

    repo.create_deal_new(42, 400, "Анна", "anna_test", None, "amoCRM", "Кейс 4")
    repo.set_awaiting_first_sent(42, "telegram", 111, timeutils.to_iso(timeutils.utcnow()))

    next_action_at = timeutils.to_iso(timeutils.utcnow())
    assert repo.restart_reminder_cycle(42, next_action_at) == 1
    assert repo.restart_reminder_cycle(42, next_action_at) == 2
    assert repo.restart_reminder_cycle(42, next_action_at) == 3
    assert repo.get_deal(42).faq_cycle_count == 3


def test_stop_reminders_clears_next_action_at_without_changing_status(repo):
    from core import timeutils

    repo.create_deal_new(5, 500, "Борис", "boris_test", None, "amoCRM", "Кейс 5")
    repo.set_awaiting_first_sent(5, "telegram", 222, timeutils.to_iso(timeutils.utcnow()))

    repo.stop_reminders(5)

    deal = repo.get_deal(5)
    assert deal.status == Status.AWAITING_REPLY_1  # статус не меняем — только останавливаем шедулер
    assert deal.next_action_at is None
    assert deal.in_progress is False

    due = repo.list_due_rows(timeutils.to_iso(timeutils.utcnow()))
    assert not any(d.deal_id == 5 for d in due)


def test_block_superseded_sets_blocked_status_and_stops_reminders(repo):
    from core import timeutils

    repo.create_deal_new(6, 600, "Виктор", "viktor_test", None, "amoCRM", "Кейс 6")
    repo.set_awaiting_first_sent(6, "telegram", 333, timeutils.to_iso(timeutils.utcnow()))

    repo.block_superseded(6, new_deal_id=7)

    deal = repo.get_deal(6)
    assert deal.status == Status.BLOCKED
    assert deal.next_action_at is None
    assert deal.in_progress is False


def test_blocked_deal_not_reopenable_via_conflict_check(repo):
    repo.create_deal_new(8, 800, "Галина", "galina_test", None, "amoCRM", "Кейс 8")
    repo.block_superseded(8, new_deal_id=9)

    conflict = repo.find_conflicting_active_deal("galina_test", None, exclude_deal_id=10)
    assert conflict is None  # BLOCKED — не активная, не считается конфликтом для будущих сделок


def test_create_deal_new_initializes_messaging_tariff_flagged_to_false(repo):
    repo.create_deal_new(43, 400, "Анна", "anna_test", None, "amoCRM", "Кейс 4")
    assert repo.get_deal(43).messaging_tariff_flagged is False


def test_set_messaging_tariff_flagged_updates_value(repo):
    repo.create_deal_new(44, 400, "Анна", "anna_test", None, "amoCRM", "Кейс 4")

    repo.set_messaging_tariff_flagged(44, True)

    assert repo.get_deal(44).messaging_tariff_flagged is True


def test_list_recent_activity_returns_latest_event_per_deal(repo):
    from core import timeutils

    repo.create_deal_new(45, 400, "Анна", "anna_test", None, "amoCRM", "Кейс 4")
    since = timeutils.to_iso(timeutils.utcnow())
    repo.log_event(45, "out", "telegram", "Первое сообщение")
    repo.log_event(45, "in", "telegram", "Ответ клиента")

    rows = repo.list_recent_activity(since)

    assert len(rows) == 1
    assert rows[0]["deal_id"] == 45
    assert rows[0]["direction"] == "in"
    assert rows[0]["text"] == "Ответ клиента"
    assert rows[0]["channel"] == "telegram"


def test_list_recent_activity_ignores_events_before_window(repo):
    from core import timeutils

    repo.create_deal_new(46, 400, "Анна", "anna_test", None, "amoCRM", "Кейс 4")
    repo.log_event(46, "out", "telegram", "Старое сообщение")
    since = timeutils.to_iso(timeutils.utcnow())

    assert repo.list_recent_activity(since) == []


def test_get_daily_send_count_does_not_increment(repo):
    assert repo.get_daily_send_count() == 0
    repo.increment_and_check_daily_cap(10)
    assert repo.get_daily_send_count() == 1
    assert repo.get_daily_send_count() == 1  # повторный вызов peek — не меняет счётчик


def test_list_recent_activity_covers_multiple_deals(repo):
    from core import timeutils

    repo.create_deal_new(47, 400, "Анна", "anna_test", None, "amoCRM", "Кейс 4")
    repo.create_deal_new(48, 400, "Борис", "boris_test", None, "amoCRM", "Кейс 5")
    since = timeutils.to_iso(timeutils.utcnow())
    repo.log_event(47, "out", "telegram", "Сообщение 1")
    repo.log_event(48, "out", "email", "Сообщение 2")

    rows = repo.list_recent_activity(since)

    assert {r["deal_id"] for r in rows} == {47, 48}
