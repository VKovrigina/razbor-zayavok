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
            return bool(block.input["describes_problem_or_data"])
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
