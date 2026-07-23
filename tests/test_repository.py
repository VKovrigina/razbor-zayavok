from db.models import Status


def test_create_and_get_deal(repo):
    repo.create_deal_new(1, 100, "Иван", "ivan_test", None, "Bitrix24", "Кейс")
    deal = repo.get_deal(1)
    assert deal is not None
    assert deal.status == Status.NEW
    assert deal.telegram_username == "ivan_test"


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
