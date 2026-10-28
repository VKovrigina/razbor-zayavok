from __future__ import annotations

import logging

import anthropic

from classify.prompt import SYSTEM_PROMPT
from classify.rule_based import classify_rule_based
from config import settings
from db.models import ReplyCategory

logger = logging.getLogger(__name__)

# По умолчанию SDK ждёт ответа до 10 минут на попытку (с 2 повторами — до 30 минут), всё это
# время сделка заблокирована. Классификация отвечает за секунды.
_CLAUDE_TIMEOUT_SECONDS = 60.0
_client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=_CLAUDE_TIMEOUT_SECONDS)

_TOOL = {
    "name": "classify_reply",
    "description": "Классифицировать ответ клиента по четырём категориям.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["positive", "negative", "ambiguous", "not_relevant"],
            }
        },
        "required": ["category"],
    },
}


def classify_sync(
    message_text: str, case_context: str | None, last_bot_message: str | None = None
) -> ReplyCategory:
    if not settings.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY не задан — используется временная классификация по правилам "
            "(classify.rule_based), она грубее, чем классификация через Claude"
        )
        return classify_rule_based(message_text)

    response = _client.messages.create(
        model=settings.anthropic_model,
        max_tokens=200,
        # cache_control: SYSTEM_PROMPT одинаков на каждый вызов — Anthropic кэширует этот
        # префикс, повторные вызовы в течение TTL кэша платят ~10% цены за эти input-токены.
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "classify_reply"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Контекст задачи клиента: {case_context or '—'}\n\n"
                    f"Последнее сообщение бота клиенту:\n{last_bot_message or '—'}\n\n"
                    f"Ответ клиента:\n{message_text}"
                ),
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "classify_reply":
            return ReplyCategory(block.input["category"])
    raise RuntimeError("Claude не вернул классификацию (нет tool_use в ответе)")
