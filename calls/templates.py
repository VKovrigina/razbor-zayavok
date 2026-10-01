from __future__ import annotations

TEMPLATE_1 = (
    "{name}, здравствуйте!\n"
    "Меня зовут Варвара, я из партнерского отдела Альбато. Мы получили ваш отклик на нашу "
    "партнерскую программу. Очень рады, что вы заинтересовались предложением!\n"
    "Что думаете о созвоне {weekday}? Вы расскажете больше о своем опыте, а мы — о нашей "
    "программе. В {slot_1} или в {slot_2} по МСК будет удобно?"
)

TEMPLATE_2 = (
    "{name}, здравствуйте!\n"
    "Меня зовут Варвара, я из партнерского отдела Альбато. Мы получили ваш отклик на "
    "партнерскую программу — очень рады вашему интересу!\n"
    "Предлагаю созвониться {weekday}, чтобы познакомиться поближе: вы расскажете о своем "
    "опыте, а мы подробнее презентуем программу и варианты сотрудничества.\n"
    "Подскажите, будет ли у вас время в {slot_1} или в {slot_2} по МСК?"
)

TEMPLATES = [TEMPLATE_1, TEMPLATE_2]

_WEEKDAY_NAMES_RU = {
    0: "понедельник",
    1: "вторник",
    2: "среду",
    3: "четверг",
    4: "пятницу",
    5: "субботу",
    6: "воскресенье",
}

# "в"/"во" перед днём недели — фонетическое правило, "во" только перед "вторник"
_WEEKDAY_PREPOSITION_PHRASES_RU = {
    0: "в понедельник",
    1: "во вторник",
    2: "в среду",
    3: "в четверг",
    4: "в пятницу",
    5: "в субботу",
    6: "в воскресенье",
}

_MONTHS_GENITIVE_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def weekday_name(day) -> str:
    return _WEEKDAY_NAMES_RU[day.weekday()]


def format_day_month(day) -> str:
    return f"{day.day} {_MONTHS_GENITIVE_RU[day.month]}"


def weekday_with_date(day) -> str:
    """"во вторник 25 августа" — с предлогом (в/во) и датой, для исходящего предложения слота."""
    return f"{_WEEKDAY_PREPOSITION_PHRASES_RU[day.weekday()]} {format_day_month(day)}"


def next_template_index(repo) -> int:
    """Round-robin 0,1,0,1,... — персистентно в kv_store (repo.get_kv/set_kv), переживает
    перезапуск процесса. Чередование нужно, чтобы разные клиенты не получали одинаковый текст
    подряд (антибан Telegram, см. Decisions Log)."""
    raw = repo.get_kv("last_template_index")
    last = int(raw) if raw is not None else -1
    current = (last + 1) % len(TEMPLATES)
    repo.set_kv("last_template_index", str(current))
    return current


def render(index: int, *, name: str, weekday: str, slot_1: str, slot_2: str) -> str:
    return TEMPLATES[index].format(name=name, weekday=weekday, slot_1=slot_1, slot_2=slot_2)
