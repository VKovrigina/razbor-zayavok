from core.templates import (
    DEFAULT_CLOSING_QUESTIONS,
    FAQ_FOLLOWUP_QUESTIONS,
    FIRST_MESSAGE_VARIANTS,
    TASK_TEXT_FAQ_LIMIT_REACHED,
    clarify_missing_data_question,
    faq_answer_with_followup,
    first_message,
    full_spec_field_text,
    spec_note,
    task_text_faq_answered,
)


def test_first_message_substitutes_placeholders():
    text = first_message("Иван", "CRM + Sheets", "Синхронизация лидов")
    assert "Иван" in text
    assert "CRM + Sheets" in text
    assert "Синхронизация лидов" in text


def test_first_message_uses_fallbacks_for_missing_data():
    text = first_message("", "", "")
    assert "Здравствуйте" in text
    assert "—" in text


def test_first_message_picks_one_of_known_variants():
    # тело сообщения и закрывающий вопрос варьируются НЕЗАВИСИМО (см. _closing_question) —
    # полное множество допустимых текстов — все комбинации body × closing_question.
    all_combinations = {
        v.format(name="Имя", stack="Стек", case="Кейс", closing_question=cq)
        for v in FIRST_MESSAGE_VARIANTS
        for cq in DEFAULT_CLOSING_QUESTIONS
    }
    seen = set()
    for _ in range(50):
        seen.add(first_message("Имя", "Стек", "Кейс"))
    assert seen <= all_combinations
    # за 50 попыток при 4 body × 4 closing_question случайный выбор почти наверняка даст >1 текст
    assert len(seen) > 1


def test_every_variant_has_required_compliance_and_disclaimer_text():
    for variant in FIRST_MESSAGE_VARIANTS:
        rendered = variant.format(name="Имя", stack="Стек", case="Кейс", closing_question="X")
        assert "интегратор" in rendered.lower()
        assert "альбато" in rendered.lower()
        assert "ии-помощник" in rendered.lower()


def test_no_warning_when_checklist_has_no_issues():
    text = first_message("Иван", "amoCRM + Sheets", "Синхронизация лидов", [])
    assert "не хватает данных" not in text


def test_warning_inserted_before_payment_consent_paragraph():
    text = first_message("Иван", "amoCRM", "надо", ["stack", "case"])
    assert "не хватает данных" in text
    assert "минимум два сервиса" in text
    assert "ни данные, которые нужно обработать" in text
    warning_pos = text.index("не хватает данных")
    consent_pos = text.index("❗️Важно")
    assert warning_pos < consent_pos


def test_warning_mentions_only_missing_field():
    text = first_message("Иван", "amoCRM", "Синхронизировать лиды из форм сайта в CRM", ["stack"])
    assert "минимум два сервиса" in text
    assert "ни данные, которые нужно обработать" not in text


def test_clarify_missing_data_question_mentions_reasons():
    text = clarify_missing_data_question(["stack", "case"])
    assert "минимум два сервиса" in text
    assert "ни данные, которые нужно обработать" in text


def test_clarify_missing_data_question_mentions_only_missing_field():
    text = clarify_missing_data_question(["stack"])
    assert "минимум два сервиса" in text
    assert "ни данные, которые нужно обработать" not in text


def test_no_topic_questions_uses_default_closing_question():
    text = first_message("Иван", "amoCRM + Sheets", "Синхронизация лидов", [], [])
    assert any(cq in text for cq in DEFAULT_CLOSING_QUESTIONS)


def test_topic_questions_replace_default_closing_question():
    topic_questions = ["для кого предназначен ИИ-агент/чат-бот", "какой результат нужен"]
    text = first_message("Иван", "amoCRM", "ИИ-агент для поддержки", [], topic_questions)
    assert "для кого предназначен ИИ-агент/чат-бот" in text
    assert "какой результат нужен" in text
    assert not any(cq in text for cq in DEFAULT_CLOSING_QUESTIONS)


def test_spec_note_formats_stack_and_case():
    note = spec_note("amoCRM + Sheets", "Синхронизировать лиды")
    assert note == "🔸Сервисы: amoCRM + Sheets\n🔸Задача: Синхронизировать лиды"


def test_spec_note_uses_dash_fallback_for_missing_fields():
    note = spec_note(None, None)
    assert note == "🔸Сервисы: —\n🔸Задача: —"


def test_full_spec_field_text_has_no_emoji():
    """Поле «Полное ТЗ» партнёры видят дословно при публикации кейса — без эмодзи, в отличие
    от примечания (spec_note)."""
    text = full_spec_field_text("amoCRM + Sheets", "Синхронизировать лиды")
    assert text == "Сервисы: amoCRM + Sheets\nЗадача: Синхронизировать лиды"
    assert "🔸" not in text


def test_full_spec_field_text_uses_dash_fallback_for_missing_fields():
    text = full_spec_field_text(None, None)
    assert text == "Сервисы: —\nЗадача: —"


def test_faq_answer_with_followup_appends_one_of_known_questions():
    combined = faq_answer_with_followup("Оценка бесплатная.")
    assert combined.startswith("Оценка бесплатная.\n\n")
    assert any(combined.endswith(q) for q in FAQ_FOLLOWUP_QUESTIONS)


def test_task_text_faq_answered_includes_question_and_answer():
    text = task_text_faq_answered("Сколько стоит?", "Точная цена после оценки.")
    assert "Сколько стоит?" in text
    assert "Точная цена после оценки." in text


def test_task_text_faq_limit_reached_is_non_empty():
    assert isinstance(TASK_TEXT_FAQ_LIMIT_REACHED, str) and TASK_TEXT_FAQ_LIMIT_REACHED
