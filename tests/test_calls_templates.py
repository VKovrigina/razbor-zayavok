from __future__ import annotations

from datetime import date

from calls import templates


class FakeRepo:
    def __init__(self):
        self._kv = {}

    def get_kv(self, key):
        return self._kv.get(key)

    def set_kv(self, key, value):
        self._kv[key] = value


def test_first_call_returns_index_0():
    assert templates.next_template_index(FakeRepo()) == 0


def test_second_call_returns_index_1():
    repo = FakeRepo()
    templates.next_template_index(repo)
    assert templates.next_template_index(repo) == 1


def test_third_call_wraps_back_to_0():
    repo = FakeRepo()
    templates.next_template_index(repo)
    templates.next_template_index(repo)
    assert templates.next_template_index(repo) == 0


def test_render_template_1_substitutes_placeholders():
    text = templates.render(0, name="Иван", weekday="во вторник 25 августа", slot_1="12:00", slot_2="12:30")
    assert "Иван" in text
    assert "во вторник 25 августа" in text
    assert "в во вторник" not in text  # не должно остаться дублирующегося предлога из текста шаблона
    assert "12:00" in text
    assert "12:30" in text
    assert "Варвара" in text


def test_render_template_2_substitutes_placeholders():
    text = templates.render(1, name="Иван", weekday="в пятницу 28 августа", slot_1="14:00", slot_2="14:30")
    assert "Иван" in text
    assert "в пятницу 28 августа" in text
    assert "в в пятницу" not in text
    assert "14:00" in text
    assert "14:30" in text
    assert "Варвара" in text


def test_weekday_name_monday_wednesday_friday():
    assert templates.weekday_name(date(2026, 8, 24)) == "понедельник"
    assert templates.weekday_name(date(2026, 8, 26)) == "среду"
    assert templates.weekday_name(date(2026, 8, 28)) == "пятницу"


def test_format_day_month_regular_date():
    assert templates.format_day_month(date(2026, 8, 25)) == "25 августа"


def test_format_day_month_january_no_leading_zero():
    assert templates.format_day_month(date(2026, 1, 1)) == "1 января"


def test_weekday_with_date_tuesday_uses_vo_preposition():
    # "во вторник" — не "в вторник" (фонетическое правило, только вторник среди дней недели)
    assert templates.weekday_with_date(date(2026, 8, 25)) == "во вторник 25 августа"


def test_weekday_with_date_monday_uses_v_preposition():
    assert templates.weekday_with_date(date(2026, 8, 24)) == "в понедельник 24 августа"


def test_weekday_with_date_friday_uses_v_preposition():
    assert templates.weekday_with_date(date(2026, 8, 28)) == "в пятницу 28 августа"
