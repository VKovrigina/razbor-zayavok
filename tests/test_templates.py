from core.templates import FIRST_MESSAGE_VARIANTS, first_message


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
    seen = set()
    for _ in range(50):
        text = first_message("Имя", "Стек", "Кейс")
        seen.add(text)
    rendered_variants = {
        v.format(name="Имя", stack="Стек", case="Кейс") for v in FIRST_MESSAGE_VARIANTS
    }
    assert seen <= rendered_variants
    # за 50 попыток при 4+ вариантах случайный выбор почти наверняка даст больше одного текста
    assert len(seen) > 1


def test_every_variant_has_required_compliance_and_disclaimer_text():
    for variant in FIRST_MESSAGE_VARIANTS:
        rendered = variant.format(name="Имя", stack="Стек", case="Кейс")
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
