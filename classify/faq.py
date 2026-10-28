from __future__ import annotations

import logging

import anthropic

from config import settings

logger = logging.getLogger(__name__)

# По умолчанию SDK ждёт ответа до 10 минут на попытку (с 2 повторами — до 30 минут), всё это
# время сделка заблокирована. Классификация отвечает за секунды.
_CLAUDE_TIMEOUT_SECONDS = 60.0
_client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=_CLAUDE_TIMEOUT_SECONDS)

# Все пункты FAQ_ENTRIES сейчас заполнены реальными фактами. _PLACEHOLDER_MARKER/_USABLE_ENTRIES
# остаются как защита на будущее: если сюда добавят черновик "[ЗАПОЛНИТЬ: ...]", он физически не
# попадёт в enum ниже и бот не сможет отправить заглушку живому клиенту.
FAQ_ENABLED = True

_NO_MATCH = "none"
_PLACEHOLDER_MARKER = "[ЗАПОЛНИТЬ"

# Закрывающий вопрос про передачу кейса на оценку добавляется одинаково ко ВСЕМ FAQ-ответам
# враппером `core/templates.py: faq_answer_with_followup` — поэтому answer здесь не должен сам
# повторять этот вопрос (faq_price — исключение: там свой уточняющий вопрос про частоту
# использования интеграции, он не дублирует закрывающий). Обработка ответа — см.
# core/state_machine.py: handle_incoming_reply.
FAQ_ENTRIES = [
    {
        "id": "faq_price",
        "examples": "сколько это стоит, какая цена, сколько будет стоить интеграция",
        "answer": (
            "Точная цена станет понятна после того, как партнёр-интегратор оценит вашу задачу — "
            "он же сориентирует вас и по нужному тарифу Альбато.\n\n"
            "Подскажите, пожалуйста: как часто вы планируете пользоваться этой интеграцией? "
            "Это поможет точнее посчитать, какой тариф вам подойдёт."
        ),
    },
    {
        "id": "faq_timeline",
        "examples": "сколько по срокам, как быстро сделаете, когда будет готово",
        "answer": (
            "Вашу заявку мы выложим на партнёрскую биржу сразу, как только вы дадите согласие. "
            "Обычно партнёры оценивают задачу в течение дня, в редких случаях — до 2 дней."
        ),
    },
    {
        "id": "faq_albato_tariff",
        "examples": (
            "что за тариф Альбато, обязательно ли покупать тариф, зачем платить ещё и Альбато"
        ),
        "answer": (
            "Без тарифа Альбато интеграция работать не будет. Оплата складывается из двух "
            "частей: оплата настройки интегратору и оплата тарифа Альбато."
        ),
    },
    {
        "id": "faq_who_is_integrator",
        "examples": "кто такой интегратор, почему я плачу не только Альбато, это ваш сотрудник",
        "answer": (
            "Наши партнёры — не сотрудники Альбато. Это интеграторы с опытом в настройке, "
            "которые в том числе прошли наше обучение."
        ),
    },
    {
        "id": "faq_free_estimate",
        "examples": "оценка бесплатная, за оценку ТЗ нужно платить",
        "answer": (
            "Оценка ТЗ бесплатная. После неё мы создадим чат с партнёром-интегратором, где вы "
            "сможете обсудить с ним все детали настройки."
        ),
    },
    {
        "id": "faq_can_decline_after_estimate",
        "examples": "а если цена или сроки не подойдут можно отказаться, ни к чему не обязывает",
        "answer": "Да, отказаться от настройки после оценки можно.",
    },
    {
        "id": "faq_payment_timing",
        "examples": "когда платить сейчас или после, оплата до начала работ или по результату",
        "answer": (
            "Оплату интегратору вы обсуждаете и согласовываете напрямую с ним. А тариф Альбато "
            "нужно будет оплатить, когда закончится бесплатный период в вашем личном кабинете."
        ),
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
        "answer": "Да, несколько разных задач можно оформить в рамках одной заявки.",
    },
]

_FAQ_BY_ID = {entry["id"]: entry for entry in FAQ_ENTRIES}

# Плейсхолдеры-черновики исключены — Claude физически не может их выбрать (нет в enum ниже).
_USABLE_ENTRIES = [e for e in FAQ_ENTRIES if not e["answer"].startswith(_PLACEHOLDER_MARKER)]

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
                "enum": [entry["id"] for entry in _USABLE_ENTRIES] + [_NO_MATCH],
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
    return "\n".join(f"- {e['id']}: {e['examples']}" for e in _USABLE_ENTRIES)


def _system_prompt_with_catalog() -> str:
    # Каталог — в system, не в user-сообщении: он статичен между вызовами (в отличие от
    # case_context/message_text), поэтому кэшируется вместе с промптом (cache_control ниже).
    return f"{_SYSTEM_PROMPT}\n\nБаза знаний:\n{_faq_catalog_text()}"


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
        system=[
            {
                "type": "text",
                "text": _system_prompt_with_catalog(),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "match_faq"},
        messages=[
            {
                "role": "user",
                "content": (
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
