from __future__ import annotations

import logging
import re

import anthropic

from config import settings

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

MIN_SERVICES = 2

# Разделители между сервисами в свободном тексте поля "Стек сервисов": запятая, плюс, слэш,
# амперсанд, точка с запятой, перевод строки, союз "и" отдельным словом.
_SERVICE_SPLIT_RE = re.compile(r"[,+/&;\n]|\bи\b", re.IGNORECASE)


def _count_services(stack_text: str | None) -> int:
    if not stack_text:
        return 0
    parts = [p.strip() for p in _SERVICE_SPLIT_RE.split(stack_text) if p.strip()]
    return len(parts)


_TOOL = {
    "name": "assess_case",
    "description": (
        "Оценить, достаточно ли текста поля 'Задача', чтобы партнёр-интегратор мог понять, "
        "что нужно сделать."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "describes_problem_or_data": {
                "type": "boolean",
                "description": (
                    "true, если описана проблема клиента, которую нужно решить, ИЛИ описано, "
                    "какие данные нужно обрабатывать"
                ),
            }
        },
        "required": ["describes_problem_or_data"],
    },
}

_SYSTEM_PROMPT = """Ты помогаешь оценить полноту заявки клиента в партнёрском отделе Альбато.
Тебе дан текст поля "Задача" из сделки. Верни true, если в тексте есть хотя бы одно из:
- описана проблема/цель клиента, которую нужно решить с помощью интеграции;
- описано, какие данные нужно обрабатывать (что откуда куда передавать, какие поля/события).
Верни false, если текст пустой или слишком общий/бессмысленный («надо интеграцию», «нужна
автоматизация», «настройте пожалуйста») и не даёт понять ни проблему, ни данные."""


def _case_describes_problem_or_data(case_text: str | None) -> bool:
    if not case_text or not case_text.strip():
        return False

    if not settings.anthropic_api_key:
        # Без API-ключа — грубая эвристика (см. classify/rule_based.py: тот же принцип фолбэка).
        return len(case_text.strip()) >= 15

    response = _client.messages.create(
        model=settings.anthropic_model,
        max_tokens=100,
        system=_SYSTEM_PROMPT,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "assess_case"},
        messages=[{"role": "user", "content": f"Текст поля 'Задача':\n{case_text}"}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "assess_case":
            value = block.input.get("describes_problem_or_data")
            if value is None:
                logger.warning("assess_case: ответ модели без обязательного поля, считаем недостаточно")
                return False
            return bool(value)
    logger.warning("assess_case: Claude не вернул tool_use, считаем что описания недостаточно")
    return False


def assess(stack_text: str | None, case_text: str | None) -> list[str]:
    """Возвращает список проблемных полей сделки:
    - "stack" — названо меньше `MIN_SERVICES` сервисов;
    - "case" — не описана ни проблема клиента, ни данные для обработки.
    Не блокирует отправку сообщения — используется, чтобы вставить предупреждение о нехватке
    данных в основное сообщение (см. core/templates.py: first_message)."""
    issues: list[str] = []
    if _count_services(stack_text) < MIN_SERVICES:
        issues.append("stack")
    if not _case_describes_problem_or_data(case_text):
        issues.append("case")
    return issues


# ---------------------------------------------------------------------------
# Тематические чек-листы — для распознанных типов задач проверяем специфичные для темы
# детали. Если чего-то не хватает, эти вопросы ЗАМЕНЯЮТ закрывающий вопрос "Хотите что-то
# добавить?" в первом сообщении (см. core/templates.py: first_message/_closing_question).
# ---------------------------------------------------------------------------

_TOPIC_DEFINITIONS = {
    "ai_agent": {
        "trigger_hint": "клиенту нужно настроить ИИ-агента или чат-бота",
        "criteria": [
            ("for_whom", "для кого предназначен ИИ-агент/чат-бот"),
            ("questions_to_cover", "какие вопросы/задачи он должен закрывать"),
            ("knowledge_base_location", "где сейчас лежит информация/база знаний, на основе которой он должен отвечать"),
            ("desired_result", "какой результат нужен от ИИ-агента/чат-бота"),
        ],
    },
    "tilda_iiko": {
        "trigger_hint": "клиенту нужно настроить связку Тильда (Tilda) и Айко (iiko)",
        "criteria": [
            ("iiko_modifiers", "есть ли у товаров в iiko модификаторы (например опции острое/не острое)"),
            ("delivery_map", "есть ли на сайте карта с зонами/областями доставки"),
            ("delivery_territory", "по какой территории осуществляется доставка"),
            ("delivery_options", "какие варианты доставки — самовывоз или курьером"),
            ("payment_options", "какие варианты оплаты — наличными или картой"),
        ],
    },
    "yandex_metrika": {
        "trigger_hint": "клиенту нужно настроить Яндекс Метрику",
        "criteria": [
            ("counters_configured", "настроены ли у клиента счётчики Яндекс Метрики"),
        ],
    },
    "max_bot": {
        "trigger_hint": "клиенту нужно настроить бота в мессенджере Макс",
        "criteria": [
            ("existing_bot", "есть ли у клиента уже бот в мессенджере Макс"),
        ],
    },
}


def _topic_catalog_text() -> str:
    lines = []
    for topic, definition in _TOPIC_DEFINITIONS.items():
        lines.append(f"### {topic} — {definition['trigger_hint']}")
        for cid, text in definition["criteria"]:
            lines.append(f"- {cid}: {text}")
    return "\n".join(lines)


_TOPIC_SYSTEM_PROMPT = f"""Ты помогаешь оценить полноту заявки клиента в партнёрском отделе Альбато.
Тебе даны типы задач с их специфичными критериями (что должно быть описано в задаче для каждого типа):

{_topic_catalog_text()}

Определи, относится ли задача клиента к ОДНОМУ из этих типов (по смыслу, не только по точному
совпадению слов). Если да — верни topic = соответствующий id, и в missing_criteria_ids перечисли
id критериев ИЗ ЭТОГО ТИПА, которые НЕ упомянуты в описании задачи. Если задача не относится ни к
одному типу — верни topic = "none" и missing_criteria_ids = []."""

_TOPIC_TOOL = {
    "name": "assess_topic",
    "description": (
        "Определить тему задачи клиента среди известных типов и оценить, какие специфичные для "
        "темы детали уже указаны, а какие нет."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "per_criterion_analysis": {
                "type": "string",
                "description": (
                    "ПЕРЕД тем как заполнить остальные поля: если тема определена, пройдись по "
                    "КАЖДОМУ критерию этой темы по отдельности и коротко напиши — упомянут он в "
                    "тексте задачи или нет, и почему (цитата или пересказ, если да)."
                ),
            },
            "topic": {
                "type": "string",
                "enum": [*_TOPIC_DEFINITIONS.keys(), "none"],
            },
            "missing_criteria_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "id критериев из темы `topic`, которые НЕ упомянуты — заполнять строго по "
                    "выводам из per_criterion_analysis, не пропускать освещённые критерии"
                ),
            },
        },
        "required": ["per_criterion_analysis", "topic", "missing_criteria_ids"],
    },
}


def _detect_topic_by_keywords(combined_lower: str) -> str | None:
    if any(k in combined_lower for k in ("ии-агент", "ии агент", "чат-бот", "чатбот", "чат бот")):
        return "ai_agent"
    has_tilda = "тильда" in combined_lower or "tilda" in combined_lower
    has_iiko = "айко" in combined_lower or "айка" in combined_lower or "iiko" in combined_lower
    if has_tilda and has_iiko:
        return "tilda_iiko"
    if "метрик" in combined_lower and ("яндекс" in combined_lower or "yandex" in combined_lower):
        return "yandex_metrika"
    if "макс" in combined_lower and "бот" in combined_lower:
        return "max_bot"
    return None


def _assess_topic_fallback(stack_text: str | None, case_text: str | None) -> list[str]:
    combined_lower = f"{stack_text or ''} {case_text or ''}".lower()
    topic = _detect_topic_by_keywords(combined_lower)
    if topic is None:
        return []
    # Без LLM не можем судить, что именно уже упомянуто — безопасный дефолт: спросить всё.
    return [text for _, text in _TOPIC_DEFINITIONS[topic]["criteria"]]


def assess_topic(stack_text: str | None, case_text: str | None) -> list[str]:
    """Возвращает тексты вопросов для темы, распознанной в задаче (см. `_TOPIC_DEFINITIONS`),
    которые не освещены в описании. Пустой список — тема не распознана или все пункты на месте.
    Эти вопросы ЗАМЕНЯЮТ закрывающий вопрос "Хотите что-то добавить?" в первом сообщении."""
    combined = f"{stack_text or ''}\n{case_text or ''}".strip()
    if not combined:
        return []

    if not settings.anthropic_api_key:
        return _assess_topic_fallback(stack_text, case_text)

    response = _client.messages.create(
        model=settings.anthropic_model,
        # 1024, не 300 — per_criterion_analysis для тем с 5 критериями (tilda_iiko) может быть
        # длинным; при более низком лимите ответ обрезался ДО поля "topic" (оно идёт в схеме
        # после per_criterion_analysis) — KeyError на проде, сделка навсегда застревала в NEW
        # (см. BACKLOG.md, найдено 2026-07-27).
        max_tokens=1024,
        system=_TOPIC_SYSTEM_PROMPT,
        tools=[_TOPIC_TOOL],
        tool_choice={"type": "tool", "name": "assess_topic"},
        messages=[
            {
                "role": "user",
                "content": f"Стек сервисов: {stack_text or '—'}\nЗадача: {case_text or '—'}",
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "assess_topic":
            topic = block.input.get("topic")
            # Ответ модели мог быть обрезан по max_tokens ДО заполнения обязательных полей —
            # это не то же самое, что "тема не найдена", но безопасный дефолт тот же: не задавать
            # тематических вопросов, а не падать (см. комментарий про max_tokens выше).
            if not topic or topic == "none" or topic not in _TOPIC_DEFINITIONS:
                return []
            missing_ids = set(block.input.get("missing_criteria_ids") or [])
            criteria = _TOPIC_DEFINITIONS[topic]["criteria"]
            return [text for cid, text in criteria if cid in missing_ids]
    logger.warning("assess_topic: Claude не вернул tool_use, тема не определена")
    return []
