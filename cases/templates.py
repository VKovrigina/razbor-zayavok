from __future__ import annotations


def case_announcement_text(full_spec: str) -> str:
    """Текст сообщения-публикации кейса в группу партнёров — только текст поля "Полное ТЗ",
    без доп. полей (решено на этапе дизайна, см. Логика ИИ агента.md разд. 2). Отдельная функция —
    единственный шов, если формулировка когда-нибудь усложнится."""
    return full_spec


def partner_display_nick(username: str | None, first_name: str, last_name: str | None) -> str:
    """P-063: приоритет @username. P-065: если username не задан (Telegram не требует его) —
    fallback на отображаемое имя (first_name [+ last_name])."""
    if username:
        return f"@{username}"
    if last_name:
        return f"{first_name} {last_name}"
    return first_name


def claimed_suffix(nick: str) -> str:
    return f"\n\n✅ Взял: {nick}"


_TELEGRAM_TEXT_LIMIT = 4096  # в единицах UTF-16, как считает Telegram (эмодзи — 2)


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def claimed_text(original: str, nick: str) -> str:
    """Текст кейса после взятия: + «✅ Взял: @ник». Длинный кейс сокращается («…»), чтобы строка
    влезла в лимит Telegram — иначе edit_text падал с MESSAGE_TOO_LONG (решено 2026-10-28)."""
    suffix = claimed_suffix(nick)
    if _utf16_len(original + suffix) <= _TELEGRAM_TEXT_LIMIT:
        return original + suffix
    budget = _TELEGRAM_TEXT_LIMIT - _utf16_len(suffix) - _utf16_len("…")
    kept, used = [], 0
    for char in original:
        used += _utf16_len(char)
        if used > budget:
            break
        kept.append(char)
    return "".join(kept).rstrip() + "…" + suffix


def already_claimed_alert(nick: str) -> str:
    return f"Уже взято: {nick}"


def not_a_member_alert() -> str:
    return "Кейсы может забирать только участник группы партнёров."


def group_title(client_nick: str) -> str:
    return f"{client_nick} & Альбато"


def client_invite_message(link: str) -> str:
    return (
        "На вашу заявку отреагировал наш партнер. Вот чат с ним для обсуждения интеграции. "
        f"Присоединяйтесь! {link}"
    )


def discussion_chat_intro(case_text: str | None) -> str:
    """Первое сообщение в созданном чате с партнёром — история чата открыта, клиент увидит его,
    зайдя по ссылке (решено 2026-10-28)."""
    if not case_text:
        return "Чат для обсуждения"
    return f"Чат для обсуждения\n\n{case_text}"


def partner_invite_message(case_text: str, link: str) -> str:
    return f"Чат для обсуждения интеграции:\n{case_text}\n{link}"


def email_contact_message(case_text: str | None, name: str, email: str) -> str:
    """Сначала сам кейс (поле «Полное ТЗ»), потом контакт — раньше партнёр получал только имя и
    почту и не видел, о какой задаче речь (решено 2026-10-28)."""
    if not case_text:
        return f"Контакт клиента по кейсу:\n{name}\n{email}"
    return f"Контакт клиента по кейсу:\n{case_text}\n\n{name}\n{email}"
