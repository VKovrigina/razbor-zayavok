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


def partner_invite_message(case_text: str, link: str) -> str:
    return f"Чат для обсуждения интеграции:\n{case_text}\n{link}"


def email_contact_message(name: str, email: str) -> str:
    return f"Контакт клиента по кейсу:\n{name}\n{email}"
