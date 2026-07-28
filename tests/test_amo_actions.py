from amo.actions import _clean_username


def test_clean_username_accepts_plain_username():
    assert _clean_username("ivan_test") == "ivan_test"


def test_clean_username_strips_at_prefix():
    assert _clean_username("@ivan_test") == "ivan_test"


def test_clean_username_strips_telegram_url():
    assert _clean_username("https://t.me/ivan_test") == "ivan_test"


def test_clean_username_rejects_placeholder_dash():
    """Найдено на проде 2026-07-24: поле Telegram в CRM не заполнено, вместо пустой строки
    приходит "-" — это не username, а два разных клиента с такой заглушкой не должны считаться
    одним и тем же человеком при проверке конфликта (см. BACKLOG.md)."""
    assert _clean_username("-") is None


def test_clean_username_rejects_empty_and_none():
    assert _clean_username("") is None
    assert _clean_username(None) is None


def test_clean_username_rejects_too_short():
    assert _clean_username("abcd") is None  # 4 символа — меньше минимума в 5


def test_clean_username_accepts_minimum_length():
    assert _clean_username("abcde") == "abcde"


def test_clean_username_rejects_leading_digit():
    assert _clean_username("12345") is None


def test_clean_username_rejects_placeholder_words():
    assert _clean_username("нет") is None
    assert _clean_username("не указан") is None
