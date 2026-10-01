from calls.contact import extract_telegram_username, first_name

FIELD_ID = 949077


def _contact(value):
    if value is None:
        return {"custom_fields_values": []}
    return {"custom_fields_values": [{"field_id": FIELD_ID, "values": [{"value": value}]}]}


def test_extracts_username_from_telegram_link():
    assert extract_telegram_username(_contact("https://t.me/Alexandr_hom"), FIELD_ID) == "Alexandr_hom"


def test_phone_number_in_field_is_not_a_username():
    assert extract_telegram_username(_contact("+79198778653"), FIELD_ID) is None


def test_missing_field_returns_none():
    assert extract_telegram_username(_contact(None), FIELD_ID) is None


def test_first_name_from_full_name():
    assert first_name("Александр Калачиков") == "Александр"


def test_first_name_single_word():
    assert first_name("Nurassyl") == "Nurassyl"


def test_first_name_none():
    assert first_name(None) is None


def test_first_name_blank():
    assert first_name("") is None
    assert first_name("   ") is None
