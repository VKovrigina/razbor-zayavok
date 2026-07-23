from datetime import datetime, timezone

from core import timeutils


def test_weekday_no_rollover():
    wednesday = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    result = timeutils.next_business_day_at_local_hour(wednesday, 14)
    local = result.astimezone(timeutils.tz())
    assert local.strftime("%A") == "Thursday"
    assert local.hour == 14


def test_friday_rolls_to_monday():
    friday = datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)
    result = timeutils.next_business_day_at_local_hour(friday, 14)
    local = result.astimezone(timeutils.tz())
    assert local.strftime("%A") == "Monday"
    assert local.hour == 14


def test_saturday_rolls_to_monday():
    saturday = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
    result = timeutils.next_business_day_at_local_hour(saturday, 14)
    local = result.astimezone(timeutils.tz())
    assert local.strftime("%A") == "Monday"
