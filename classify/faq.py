from __future__ import annotations

import logging

import anthropic

from config import settings

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# Временно выключено (2026-07-23): ответы в FAQ_ENTRIES ниже местами placeholder
# ("[ЗАПОЛНИТЬ: ...]") — пока docs/faq-knowledge-base.md не заполнен реальными фактами (цены,
# сроки, условия тарифа), включать нельзя — иначе бот отправит заглушку живому клиенту.
# Включить обратно: FAQ_ENABLED = True, после переноса финальных ответов в FAQ_ENTRIES.
FAQ_ENABLED = False

_NO_MATCH = "none"

# Черновик — тексты ответов взяты из docs/faq-knowledge-base.md как заглушки.
# TODO: перенести сюда финальные ответы после того, как в docs/faq-knowledge-base.md будут
# заполнены реальные факты (цены, сроки, условия тарифа) — сейчас answer местами placeholder.
FAQ_ENTRIES = [
    {
        "id": "faq_price",
        "examples": "сколько это стоит, какая цена, сколько будет стоить интеграция",
        "answer": "[ЗАПОЛНИТЬ: faq_price — см. docs/faq-knowledge-base.md]",
    },
    {
        "id": "faq_timeline",
        "examples": "сколько по срокам, как быстро сделаете, когда будет готово",
        "answer": "[ЗАПОЛНИТЬ: faq_timeline — см. docs/faq-knowledge-base.md]",
    },
    {
        "id": "faq_albato_tariff",
        "examples": (
            "что за тариф Альбато, обязательно ли покупать тариф, зачем платить ещё и Альбато"
        ),
        "answer": "[ЗАПОЛНИТЬ: faq_albato_tariff — см. docs/faq-knowledge-base.md]",
    },
    {
        "id": "faq_who_is_integrator",
        "examples": "кто такой интегратор, почему я плачу не только Альбато, это ваш сотрудник",
        "answer": "[ЗАПОЛНИТЬ: faq_who_is_integrator — см. docs/faq-knowledge-base.md]",
    },
    {
        "id": "faq_free_estimate",
        "examples": "оценка бесплатная, за оценку ТЗ нужно платить",
        "answer": "[ЗАПОЛНИТЬ: faq_free_estimate — см. docs/faq-knowledge-base.md]",
    },
    {
        "id": "faq_can_decline_after_estimate",
        "examples": "а если цена или сроки не подойдут можно отказаться, ни к чему не обязывает",
        "answer": "[ЗАПОЛНИТЬ: faq_can_decline_after_estimate — см. docs/faq-knowledge-base.md]",
    },
    {
        "id": "faq_payment_timing",
        "examples": "когда платить сейчас или после, оплата до начала работ или по результату",
        "answer": "[ЗАПОЛНИТЬ: faq_payment_timing — см. docs/faq-knowledge-base.md]",
    },
    {
        "id": "faq_tz_clarification",
        "examples": "не понимаю что писать в ТЗ, какие данные вам нужны, что значит подробное описание",
        "answer": (
            "Опишите, пожалуйста: 1) какие именно сервисы должны быть связаны между собой, "
            "2) какие данные нужно передавать (например: заявки, контакты, статусы заказов), "
            "3) в какую сторону — откуда куда, 4) есть ли условия/фильтры. Чем подробнее — тем "
            "точнее и быстрее партнёр сможет оценить работу."
        ),
    },
    {
        "id": "faq_multiple_services",
        "examples": "у меня несколько разных интеграций это одна заявка или разные",
        "answer": "[ЗАПОЛНИТЬ: faq_multiple_services — см. docs/faq-knowledge-base.md]",
    },
]

_FAQ_BY_ID = {entry["id"]: entry for entry in FAQ_ENTRIES}

_TOOL = {
    "name": "match_faq",
    "description": (
        "Найти пункт базы знаний, который отвечает на вопрос клиента. Если ни один пункт не "
        "подходит — вернуть 'none'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "faq_id": {
                "type": "string",
                "enum": [entry["id"] for entry in FAQ_ENTRIES] + [_NO_MATCH],
            }
        },
        "required": ["faq_id"],
    },
}

_SYSTEM_PROMPT = """Ты помогаешь подобрать готовый ответ из базы знаний партнёрского отдела
Альбато на встречный вопрос клиента. Тебе даны пункты базы знаний (id + типичные формулировки
вопроса). Сопоставь вопрос клиента с ОДНИМ наиболее подходящим пунктом по смыслу (не только по
дословному совпадению слов). Если ни один пункт по смыслу не подходит — верни 'none'. Не
пытайся ответить сам, только выбери id или 'none'."""


def _faq_catalog_text() -> str:
    return "\n".join(f"- {e['id']}: {e['examples']}" for e in FAQ_ENTRIES)


def match_faq_sync(message_text: str, case_context: str | None) -> str | None:
    """Возвращает id подходящего пункта базы знаний, либо None (FAQ выключен, нет совпадения,
    либо нет API-ключа)."""
    if not FAQ_ENABLED:
        return None
    if not settings.anthropic_api_key:
        return None

    response = _client.messages.create(
        model=settings.anthropic_model,
        max_tokens=200,
        system=_SYSTEM_PROMPT,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "match_faq"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"База знаний:\n{_faq_catalog_text()}\n\n"
                    f"Контекст задачи клиента: {case_context or '—'}\n\n"
                    f"Вопрос клиента:\n{message_text}"
                ),
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "match_faq":
            faq_id = block.input["faq_id"]
            return None if faq_id == _NO_MATCH else faq_id
    logger.warning("match_faq: Claude не вернул tool_use, считаем что совпадений нет")
    return None


def get_answer(faq_id: str) -> str:
    return _FAQ_BY_ID[faq_id]["answer"]
