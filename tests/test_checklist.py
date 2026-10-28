import dataclasses
from types import SimpleNamespace

from core import checklist
from config import settings as base_settings


def _no_llm(monkeypatch):
    no_key_settings = dataclasses.replace(base_settings, anthropic_api_key="")
    monkeypatch.setattr("core.checklist.settings", no_key_settings)


def test_stack_with_two_services_passes(monkeypatch):
    _no_llm(monkeypatch)
    issues = checklist.assess("amoCRM + Google Sheets", "Синхронизировать новые лиды из форм в CRM")
    assert "stack" not in issues


def test_stack_with_one_service_flagged(monkeypatch):
    _no_llm(monkeypatch)
    assert "stack" in checklist.assess("amoCRM", "Синхронизировать новые лиды из форм в CRM")


def test_stack_empty_flagged(monkeypatch):
    _no_llm(monkeypatch)
    assert "stack" in checklist.assess("", "Синхронизировать новые лиды из форм в CRM")


def test_stack_two_services_various_separators(monkeypatch):
    _no_llm(monkeypatch)
    for stack in ["amoCRM, Telegram", "amoCRM и Telegram", "amoCRM/Telegram", "amoCRM\nTelegram"]:
        assert "stack" not in checklist.assess(stack, "Синхронизировать лиды из форм в CRM")


def test_case_empty_flagged_without_llm(monkeypatch):
    _no_llm(monkeypatch)
    assert "case" in checklist.assess("amoCRM + Sheets", "")


def test_case_short_flagged_without_llm_fallback(monkeypatch):
    _no_llm(monkeypatch)
    assert "case" in checklist.assess("amoCRM + Sheets", "надо")


def test_case_detailed_passes_without_llm_fallback(monkeypatch):
    _no_llm(monkeypatch)
    issues = checklist.assess("amoCRM + Sheets", "Синхронизировать новые лиды из форм сайта в CRM")
    assert "case" not in issues


def test_both_fields_missing(monkeypatch):
    _no_llm(monkeypatch)
    assert checklist.assess(None, None) == ["stack", "case"]


# --- assess с LLM: сервисы считает Claude по стеку И тексту задачи (одним вызовом) ---

class _FakeMessages:
    def __init__(self, tool_input):
        self.tool_input = tool_input
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.tool_input is None:
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="...")])
        block = SimpleNamespace(type="tool_use", name="assess_case", input=self.tool_input)
        return SimpleNamespace(content=[block])


def _fake_llm(monkeypatch, tool_input):
    key_settings = dataclasses.replace(base_settings, anthropic_api_key="test-key")
    monkeypatch.setattr("core.checklist.settings", key_settings)
    messages = _FakeMessages(tool_input)
    monkeypatch.setattr("core.checklist._client", SimpleNamespace(messages=messages))
    return messages


def test_llm_two_services_without_separator_passes(monkeypatch):
    # Сделка 40217503: «сеилбот битрикс» — два сервиса через пробел, регулярка видела один
    _fake_llm(monkeypatch, {"has_two_services": True, "describes_problem_or_data": True})
    assert checklist.assess("сеилбот битрикс", "Заявка из бота в сеилботе попадает в битрикс") == []


def test_llm_max_tokens_fits_long_services_list(monkeypatch):
    # Сделка 40328525: 12 сервисов в services_found съели max_tokens=150 (ответ занял 163) —
    # describes_problem_or_data обрезался, подробное ТЗ помечалось как "не описана проблема"
    messages = _fake_llm(monkeypatch, {"has_two_services": True, "describes_problem_or_data": True})
    checklist.assess("сайт, Telegram, VK, Max, Google таблицы, ОК, Дзен", "Подробное ТЗ")
    assert messages.calls[0]["max_tokens"] >= 1024


def test_llm_one_service_flagged(monkeypatch):
    _fake_llm(monkeypatch, {"has_two_services": False, "describes_problem_or_data": True})
    assert checklist.assess("Авито", "Нужна консультация по интеграции") == ["stack"]


def test_llm_single_call_sees_stack_and_case(monkeypatch):
    messages = _fake_llm(monkeypatch, {"has_two_services": True, "describes_problem_or_data": True})
    checklist.assess("Posiflora", "Передавать заказы из формы Tilda в Posiflora")
    assert len(messages.calls) == 1
    content = messages.calls[0]["messages"][0]["content"]
    assert "Posiflora" in content and "Tilda" in content


def test_llm_empty_case_flagged_but_stack_checked(monkeypatch):
    messages = _fake_llm(monkeypatch, {"has_two_services": True, "describes_problem_or_data": True})
    assert checklist.assess("amoCRM Telegram", "") == ["case"]
    assert len(messages.calls) == 1


def test_llm_both_empty_no_call(monkeypatch):
    messages = _fake_llm(monkeypatch, {"has_two_services": True, "describes_problem_or_data": True})
    assert checklist.assess(None, "  ") == ["stack", "case"]
    assert messages.calls == []


def test_llm_missing_services_field_flags_stack(monkeypatch):
    _fake_llm(monkeypatch, {"describes_problem_or_data": True})
    assert checklist.assess("amoCRM Telegram", "Передавать лиды из бота в CRM") == ["stack"]


def test_llm_no_tool_use_flags_both(monkeypatch):
    _fake_llm(monkeypatch, None)
    assert checklist.assess("amoCRM Telegram", "Передавать лиды из бота в CRM") == ["stack", "case"]


# --- assess_topic (тематические чек-листы, keyword-фолбэк без LLM) ---

def test_topic_none_when_no_keywords_match(monkeypatch):
    _no_llm(monkeypatch)
    assert checklist.assess_topic("amoCRM + Sheets", "Синхронизировать лиды") == []


def test_topic_ai_agent_detected_all_criteria_missing(monkeypatch):
    _no_llm(monkeypatch)
    issues = checklist.assess_topic("Telegram", "Хочу настроить ИИ-агента для чата с клиентами")
    assert len(issues) == 4
    assert any("для кого" in i for i in issues)
    assert any("какой результат" in i for i in issues)


def test_topic_tilda_iiko_requires_both_keywords(monkeypatch):
    _no_llm(monkeypatch)
    # Тильда без айко/iiko — тема не должна определяться как tilda_iiko
    assert checklist.assess_topic("Tilda", "Нужен сайт на Тильде") == []


def test_topic_tilda_iiko_detected_all_criteria_missing(monkeypatch):
    _no_llm(monkeypatch)
    issues = checklist.assess_topic("Tilda, iiko", "Нужно связать Тильду и iiko для приёма заказов")
    assert len(issues) == 5
    assert any("модификаторы" in i for i in issues)
    assert any("наличными или картой" in i for i in issues)


def test_topic_yandex_metrika_detected(monkeypatch):
    _no_llm(monkeypatch)
    issues = checklist.assess_topic("Яндекс Метрика", "Нужно настроить Яндекс Метрику на сайте")
    assert len(issues) == 1
    assert "счётчики" in issues[0]


def test_topic_max_bot_detected(monkeypatch):
    _no_llm(monkeypatch)
    issues = checklist.assess_topic("Макс", "Нужен бот в мессенджере Макс для рассылок")
    assert len(issues) == 1
    assert "уже бот в мессенджере Макс" in issues[0]


def test_topic_max_alone_without_bot_keyword_not_detected(monkeypatch):
    _no_llm(monkeypatch)
    # "Макс" может быть именем/словом — без слова "бот" рядом тема не должна определяться
    assert checklist.assess_topic("CRM", "Клиента зовут Макс, нужна интеграция CRM с Sheets") == []


def test_assess_topic_empty_input_returns_no_topic(monkeypatch):
    _no_llm(monkeypatch)
    assert checklist.assess_topic(None, None) == []


# --- describes_addition_to_case (отличаем содержательное дополнение от голого согласия) ---

def test_describes_addition_empty_text_returns_false(monkeypatch):
    _no_llm(monkeypatch)
    assert checklist.describes_addition_to_case(None) is False
    assert checklist.describes_addition_to_case("") is False
    assert checklist.describes_addition_to_case("   ") is False


def test_describes_addition_bare_agreement_returns_false_without_llm(monkeypatch):
    _no_llm(monkeypatch)
    assert checklist.describes_addition_to_case("да, жду") is False


def test_describes_addition_substantial_text_returns_true_without_llm(monkeypatch):
    _no_llm(monkeypatch)
    text = "Да, дополнительно нужно ещё передавать статусы заказов из Bitrix24"
    assert checklist.describes_addition_to_case(text) is True


# --- mentions_messaging_work (предупреждение о тарифе на "операции", P-052) ---

def test_mentions_messaging_empty_text_returns_false(monkeypatch):
    _no_llm(monkeypatch)
    assert checklist.mentions_messaging_work(None) is False
    assert checklist.mentions_messaging_work("") is False
    assert checklist.mentions_messaging_work("   ") is False


def test_mentions_messaging_without_llm_key_returns_false(monkeypatch):
    # В отличие от describes_addition_to_case, без API-ключа фолбэк не эвристика по длине, а
    # всегда False — не гадаем, чтобы не пугать клиента тарифом зря.
    _no_llm(monkeypatch)
    text = "Хочу настроить ИИ-агента, который будет отвечать клиентам в Telegram и обрабатывать отзывы"
    assert checklist.mentions_messaging_work(text) is False
