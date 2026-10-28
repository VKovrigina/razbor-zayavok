from cases import templates


def test_partner_display_nick_prefers_username():
    assert templates.partner_display_nick("ivan_partner", "Иван", "Петров") == "@ivan_partner"


def test_partner_display_nick_falls_back_to_first_last_name_when_no_username():
    assert templates.partner_display_nick(None, "Иван", "Петров") == "Иван Петров"


def test_partner_display_nick_falls_back_to_first_name_only_when_no_last_name():
    assert templates.partner_display_nick(None, "Иван", None) == "Иван"


def test_claimed_suffix_format():
    assert templates.claimed_suffix("@ivan") == "\n\n✅ Взял: @ivan"


def test_already_claimed_alert_format():
    assert templates.already_claimed_alert("@ivan") == "Уже взято: @ivan"


def test_group_title_format():
    assert templates.group_title("@vr_kvr") == "@vr_kvr & Альбато"


def test_client_invite_message_format():
    assert templates.client_invite_message("https://t.me/+abc") == (
        "На вашу заявку отреагировал наш партнер. Вот чат с ним для обсуждения интеграции. "
        "Присоединяйтесь! https://t.me/+abc"
    )


def test_partner_invite_message_format():
    assert templates.partner_invite_message("Текст ТЗ", "https://t.me/+abc") == (
        "Чат для обсуждения интеграции:\nТекст ТЗ\nhttps://t.me/+abc"
    )


def test_email_contact_message_includes_case_before_contact():
    assert templates.email_contact_message("Текст ТЗ", "Иван Клиент", "ivan@example.com") == (
        "Контакт клиента по кейсу:\nТекст ТЗ\n\nИван Клиент\nivan@example.com"
    )


def test_email_contact_message_without_case_only_contact():
    assert templates.email_contact_message(None, "Иван Клиент", "ivan@example.com") == (
        "Контакт клиента по кейсу:\nИван Клиент\nivan@example.com"
    )


def test_case_announcement_text_is_pass_through():
    assert templates.case_announcement_text("🔸Сервисы: amoCRM\n🔸Задача: тест") == (
        "🔸Сервисы: amoCRM\n🔸Задача: тест"
    )


def test_discussion_chat_intro_with_case():
    assert templates.discussion_chat_intro("Текст ТЗ") == "Чат для обсуждения\n\nТекст ТЗ"


def test_discussion_chat_intro_without_case():
    assert templates.discussion_chat_intro(None) == "Чат для обсуждения"


def _utf16_len(text):
    return len(text.encode("utf-16-le")) // 2


def test_claimed_text_short_appends_suffix():
    assert templates.claimed_text("Текст кейса", "@ivan") == "Текст кейса\n\n✅ Взял: @ivan"


def test_claimed_text_long_is_shortened_to_telegram_limit():
    text = "🔸" + "а" * 5000
    result = templates.claimed_text(text, "@ivan_partner")
    assert _utf16_len(result) <= 4096
    assert result.endswith("…\n\n✅ Взял: @ivan_partner")
