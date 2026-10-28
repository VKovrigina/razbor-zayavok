from __future__ import annotations

import logging
import re

import anthropic

from config import settings

logger = logging.getLogger(__name__)

# По умолчанию SDK ждёт ответа до 10 минут на попытку (с 2 повторами — до 30 минут), всё это
# время сделка заблокирована. Классификация отвечает за секунды.
_CLAUDE_TIMEOUT_SECONDS = 60.0
_client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=_CLAUDE_TIMEOUT_SECONDS)

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
        "Оценить, достаточно ли полей 'Стек сервисов' и 'Задача', чтобы партнёр-интегратор мог "
        "понять, что нужно сделать."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            # Список ПЕРЕД has_two_services: модель сначала выписывает сервисы, потом решает —
            # без этого на пустой задаче она стабильно отвечала false на «Яндекс почта МАХ».
            "services_found": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Все сервисы/системы из стека и задачи, по одному на элемент, без Альбато "
                    "(«Яндекс почта МАХ» → [\"Яндекс почта\", \"МАХ\"])"
                ),
            },
            "has_two_services": {
                "type": "boolean",
                "description": (
                    "true, если по стеку и задаче вместе видно минимум два сервиса/системы, "
                    "которые нужно связать (правила — в system prompt)"
                ),
            },
            "describes_problem_or_data": {
                "type": "boolean",
                "description": (
                    "true, если описана проблема клиента, которую нужно решить, ИЛИ описано, "
                    "какие данные нужно обрабатывать"
                ),
            }
        },
        "required": ["services_found", "has_two_services", "describes_problem_or_data"],
    },
}

_SYSTEM_PROMPT = """Ты помогаешь оценить полноту заявки клиента в партнёрском отделе Альбато.
Тебе даны поля сделки "Стек сервисов" и "Задача". Оцени два пункта.

1) has_two_services — true, если по стеку и задаче ВМЕСТЕ видно минимум два сервиса/системы,
которые нужно связать между собой. Сервисы могут быть записаны через пробел, тире, стрелку,
предлог («сеилбот битрикс», «Озон - Яндекс Доставка», «Мой склад с Adesk») — это два сервиса.
Считай достаточным (true) также, если:
- второй сервис назван только в тексте задачи (стек «Posiflora», задача «из Tilda в Posiflora»);
- это один и тот же сервис на двух аккаунтах («связать товары на двух аккаунтах МойСклад»);
- вторая система упомянута без названия («заявки из формы ВК в нашу CRM», «с самописной CRM»).
Сам Альбато (Albato) вторым сервисом НЕ считается — это платформа-связка.
Верни false, если виден только один сервис и непонятно, с чем его связывать, или сервисов нет.
Пункт 1 оценивай НЕЗАВИСИМО от пункта 2: если в стеке названы два сервиса, это true, даже когда
задача пустая или непонятная («Авито в макс», «Яндекс почта МАХ», «сеилбот битрикс» без задачи —
true). Пустота задачи учитывается только в пункте 2.

2) describes_problem_or_data — true, если в задаче есть хотя бы одно из:
- описана проблема/цель клиента, которую нужно решить с помощью интеграции;
- описано, какие данные нужно обрабатывать (что откуда куда передавать, какие поля/события).
Верни false, если текст задачи пустой или слишком общий/бессмысленный («надо интеграцию», «нужна
автоматизация», «настройте пожалуйста») и не даёт понять ни проблему, ни данные."""


def _assess_with_llm(stack_text: str | None, case_text: str | None) -> tuple[bool, bool]:
    """Один вызов Claude на оба пункта: (has_two_services, describes_problem_or_data).
    Безопасный дефолт при пропущенном поле или отсутствии tool_use — False (пункт помечается)."""
    response = _client.messages.create(
        model=settings.anthropic_model,
        # С запасом: services_found идёт ПЕРВЫМ и на длинном стеке (сделка 40328525, 12 сервисов)
        # съедал 150 токенов — describes_problem_or_data обрезался и подробное ТЗ помечалось как
        # неполное. Оплачиваются только реально сгенерированные токены, не лимит.
        max_tokens=1024,
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "assess_case"},
        messages=[
            {
                "role": "user",
                "content": f"Стек сервисов:\n{stack_text or '—'}\n\nЗадача:\n{case_text or '—'}",
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "assess_case":
            values = []
            for field_name in ("has_two_services", "describes_problem_or_data"):
                value = block.input.get(field_name)
                if value is None:
                    logger.warning(
                        "assess_case: ответ модели без поля %s, считаем недостаточно", field_name
                    )
                values.append(bool(value))
            return values[0], values[1]
    logger.warning("assess_case: Claude не вернул tool_use, считаем что данных недостаточно")
    return False, False


def assess(stack_text: str | None, case_text: str | None) -> list[str]:
    """Возвращает список проблемных полей сделки:
    - "stack" — не видно минимум `MIN_SERVICES` сервисов (Claude смотрит стек И задачу: второй
      сервис может быть назван только в задаче, сервисы могут быть записаны через пробел);
    - "case" — не описана ни проблема клиента, ни данные для обработки.
    Без API-ключа — грубый фолбэк: регулярка по разделителям стека и длина текста задачи.
    Не блокирует отправку сообщения — используется, чтобы вставить предупреждение о нехватке
    данных в основное сообщение (см. core/templates.py: first_message)."""
    has_stack = bool(stack_text and stack_text.strip())
    has_case = bool(case_text and case_text.strip())

    if not has_stack and not has_case:
        return ["stack", "case"]

    if settings.anthropic_api_key:
        services_ok, case_ok = _assess_with_llm(stack_text, case_text)
    else:
        # Без API-ключа — грубая эвристика (см. classify/rule_based.py: тот же принцип фолбэка).
        services_ok = _count_services(stack_text) >= MIN_SERVICES
        case_ok = len((case_text or "").strip()) >= 15

    issues: list[str] = []
    if not services_ok:
        issues.append("stack")
    if not has_case or not case_ok:
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
        system=[
            {"type": "text", "text": _TOPIC_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
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


# ---------------------------------------------------------------------------
# Дополнение к задаче при позитивном ответе — отличаем содержательное уточнение от голого
# согласия ("да"/"жду"/"хорошо"), см. core/state_machine.py: handle_incoming_reply.
# ---------------------------------------------------------------------------

_ADDITION_TOOL = {
    "name": "assess_addition",
    "description": (
        "Оценить, добавляет ли ответ клиента что-то по существу к описанию задачи, или это "
        "просто согласие продолжить без новой информации."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "adds_information": {
                "type": "boolean",
                "description": (
                    "true, если в ответе клиента есть новые детали/уточнения по задаче; false, "
                    "если это просто согласие/подтверждение без новой информации (например "
                    "«да», «хорошо», «жду», «согласен», «спасибо»)"
                ),
            }
        },
        "required": ["adds_information"],
    },
}

_ADDITION_SYSTEM_PROMPT = """Ты помогаешь понять, добавляет ли ответ клиента что-то по существу к
описанию задачи в партнёрском отделе Альбато. Тебе дан текст ответа клиента на вопрос "готовы
передать задачу партнёрам на оценку?". Верни true, если в ответе есть НОВАЯ информация по задаче
(уточнение деталей, дополнительное условие, изменение требований). Верни false, если это просто
согласие продолжить без новой информации ("да", "хорошо", "давайте", "жду", "спасибо",
"согласен")."""


def describes_addition_to_case(text: str | None) -> bool:
    """Отличает содержательное дополнение к задаче от голого согласия ("да"/"жду"/"хорошо") —
    используется в handle_incoming_reply при позитивном ответе клиента, чтобы не засорять
    примечание и поле "Полное ТЗ" (видит партнёр в проекте "Выдача кейсов к группу")
    бессмысленными репликами. Безопасный дефолт при любой неопределённости — False (не добавлять)."""
    if not text or not text.strip():
        return False
    if not settings.anthropic_api_key:
        return len(text.strip()) >= 15  # тот же грубый фолбэк, что у assess без API-ключа

    response = _client.messages.create(
        model=settings.anthropic_model,
        max_tokens=100,
        system=[
            {"type": "text", "text": _ADDITION_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        tools=[_ADDITION_TOOL],
        tool_choice={"type": "tool", "name": "assess_addition"},
        messages=[{"role": "user", "content": f"Ответ клиента:\n{text}"}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "assess_addition":
            value = block.input.get("adds_information")
            if value is None:
                logger.warning(
                    "assess_addition: ответ модели без обязательного поля, считаем что дополнения нет"
                )
                return False
            return bool(value)
    logger.warning("assess_addition: Claude не вернул tool_use, считаем что дополнения нет")
    return False


_MESSAGING_TOOL = {
    "name": "assess_messaging_work",
    "description": (
        "Оценить, есть ли в описании задачи клиента признаки работы с сообщениями (месседжинг): "
        "мессенджеры, чаты в сервисах, ИИ-ответы на сообщения, работа с отзывами. Автоматизация "
        "звонков/телефонии сама по себе месседжингом НЕ считается."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "mentions_messaging": {
                "type": "boolean",
                "description": (
                    "true, если есть хотя бы один признак: 1) использование мессенджеров "
                    "(Telegram/WhatsApp/Viber и т.п.) как канала связи с клиентом; "
                    "2) использование чатов внутри сервисов (чат на сайте, встроенный чат CRM); "
                    "3) использование ИИ для ответа на сообщения клиентам; 4) работа с отзывами "
                    "(сбор/обработка/автоответ). false в остальных случаях — в том числе для "
                    "автоматизации звонков/телефонии (например Манго Офис/Talker) и смены статуса "
                    "сделки по исходу звонка: звонок — не сообщение"
                ),
            }
        },
        "required": ["mentions_messaging"],
    },
}

_MESSAGING_SYSTEM_PROMPT = """Ты помогаешь понять, нужна ли клиенту партнёрского отдела Альбато
работа с сообщениями (месседжинг) — это отдельно тарифицируется. Тебе дан текст задачи клиента.

Верни true, ТОЛЬКО если в задаче есть хотя бы один из следующих признаков:
1) Использование мессенджеров (Telegram, WhatsApp, Viber и т.п.) как канала связи с клиентом —
   отправка/приём сообщений через мессенджер.
2) Использование чатов внутри сервисов (чат на сайте, встроенный чат CRM/сервиса и т.п.).
3) Использование ИИ для ответа на сообщения клиентам (опциональный признак — усиливает пункты
   1/2, но сам по себе, без мессенджера/чата, недостаточен).
4) Работа с отзывами (сбор, обработка, автоматический ответ на отзывы).

Верни false во всех остальных случаях — в том числе если автоматизация просто связывает системы
без переписки с клиентом: например, автоматизация ЗВОНКОВ через телефонию (Манго Офис/Talker и
т.п.), смена статуса сделки в CRM по исходу звонка, обычная синхронизация данных/CRM/таблиц/счетов.
Звонок — это НЕ сообщение и НЕ месседжинг, даже если он инициируется автоматически по событию в
CRM."""


def mentions_messaging_work(case_text: str | None) -> bool:
    """Определяет, нужно ли предупредить клиента о тарифе на 'операции' (работа с сообщениями) —
    см. core/state_machine.py: process_new_deal и templates.MESSAGING_TARIFF_WARNING. Критерии
    (нужен хотя бы один): 1) мессенджеры как канал связи с клиентом; 2) чаты внутри сервисов;
    3) ИИ отвечает на сообщения (опционально, усиливает 1/2); 4) работа с отзывами. НЕ считается
    месседжингом автоматизация звонков/телефонии (Манго Офис/Talker и т.п.) — звонок не сообщение
    (уточнено 2026-07-29, P-054, после ложного срабатывания на кейсе с Mango Talker). Безопасный
    дефолт при любой неопределённости — False (не предупреждать зря). В отличие от
    describes_addition_to_case, без API-ключа фолбэк тоже False (не эвристика по длине) — ложное
    срабатывание показало бы клиенту пугающий текст про тариф без причины."""
    if not case_text or not case_text.strip():
        return False
    if not settings.anthropic_api_key:
        return False

    response = _client.messages.create(
        model=settings.anthropic_model,
        max_tokens=100,
        system=[
            {"type": "text", "text": _MESSAGING_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        tools=[_MESSAGING_TOOL],
        tool_choice={"type": "tool", "name": "assess_messaging_work"},
        messages=[{"role": "user", "content": f"Задача клиента:\n{case_text}"}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == "assess_messaging_work":
            value = block.input.get("mentions_messaging")
            if value is None:
                logger.warning(
                    "assess_messaging_work: ответ без обязательного поля, считаем что не про сообщения"
                )
                return False
            return bool(value)
    logger.warning("assess_messaging_work: Claude не вернул tool_use, считаем что не про сообщения")
    return False
