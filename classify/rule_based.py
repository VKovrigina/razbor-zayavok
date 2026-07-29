from __future__ import annotations

from db.models import ReplyCategory

NEGATIVE_MARKERS = (
    "неактуальн",
    "позовите оператор",
    "позови оператор",
    "дайте оператор",
    "нужен оператор",
    "нужен человек",
    "позовите человек",
    "не хочу общаться с бот",
    "не хочу с ботом",
    "не согласен",
    "не согласна",
    "отказ",
    # Мягкие отказы/отсрочки без явного "неактуально" — клиент даёт понять, что продолжать
    # сейчас не хочет, даже без грубых слов.
    "пока нет",
    "не сейчас",
    "пока не готов",
    "пока рано",
)

QUESTION_MARKERS = (
    "?",
    "сколько",
    "стоимост",
    "цена",
    "когда",
    "почему",
    "уточн",
    "как именно",
)

POSITIVE_MARKERS = (
    "да,",
    "да.",
    "да!",
    "хорошо",
    "ок",
    "окей",
    "согласен",
    "согласна",
    "верно",
    "подходит",
    "устраивает",
    "давайте",
    "продолжайте",
    "норм",
    "всё верно",
    "все верно",
)


def classify_rule_based(message_text: str) -> ReplyCategory:
    """Временный запасной вариант без LLM: негатив — по ключевым маркерам отказа/просьбы
    оператора, вопрос без готового ответа у бота — неоднозначно, явное согласие без вопроса —
    позитив. Во всех прочих случаях — неоднозначно (безопасный дефолт: эскалация к человеку,
    а не ложный позитив)."""
    lowered = message_text.lower()

    if any(marker in lowered for marker in NEGATIVE_MARKERS):
        return ReplyCategory.NEGATIVE

    if any(marker in lowered for marker in QUESTION_MARKERS):
        return ReplyCategory.AMBIGUOUS

    if any(marker in lowered for marker in POSITIVE_MARKERS):
        return ReplyCategory.POSITIVE

    return ReplyCategory.AMBIGUOUS
