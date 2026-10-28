from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from email_channel.poller import _extract_body

# Структура — как у реальных ответов клиентов (2026-10), данные вымышленные.

YANDEX_WEB_HTML = (
    "<div>Добрый день Варвара.</div><div>Отвечаю на Ваш вопросы.</div>"
    "<div>1) Модификаторы отсутствуют.</div><div>4) Самовывоз.</div><div><br /></div>"
    "<div><br /></div><div>----------------</div>\n"
    "                        <div>Кому: client@example.ru (client@example.ru);<br /></div>\n"
    "                        <div>Тема: Ваша заявка на интеграцию — Альбато;<br /></div>\n"
    '                        <div>26.10.2026, 10:22, "v.kovrigina@albato.ru" '
    "&lt;v.kovrigina@albato.ru&gt;:<br /></div>\n"
    "                        <blockquote><p>Добрый день!<br />Меня зовут Варвара</p></blockquote>"
)

YANDEX_MOBILE_HTML = (
    "<div>Сервисы: YCLIENTS + amoCRM.</div><div><br /></div><div>Проблема:</div>"
    "<div>* Имя;</div><div>* Фамилию.</div><br />--<br />Отправлено из мобильной Яндекс Почты"
    "<br /><br /><b>Кому</b> client@example.ru &lt;client@example.ru&gt;;<br />"
    "<b>Тема</b> Ваша заявка на интеграцию — Альбато;<br />"
    '16.10.2026, 09:07, "v.kovrigina@albato.ru" &lt;v.kovrigina@albato.ru&gt;:<br />'
    "<blockquote><p>Екатерина, добрый день!<br />Меня зовут Варвара</p></blockquote>"
)


def _html(body: str) -> MIMEText:
    return MIMEText(body, "html", "utf-8")


def _plain(body: str) -> MIMEText:
    return MIMEText(body, "plain", "utf-8")


def test_yandex_web_html_only_reply_without_tags_and_quote():
    assert _extract_body(_html(YANDEX_WEB_HTML)) == (
        "Добрый день Варвара.\nОтвечаю на Ваш вопросы.\n1) Модификаторы отсутствуют.\n4) Самовывоз."
    )


def test_yandex_mobile_html_cuts_signature_and_quote():
    assert _extract_body(_html(YANDEX_MOBILE_HTML)) == (
        "Сервисы: YCLIENTS + amoCRM.\n\nПроблема:\n* Имя;\n* Фамилию."
    )


def test_gmail_plain_cuts_attribution_and_quoted_lines():
    body = (
        "Добрый день!\nМожно через whats up\n\n\n"
        "Ср, 29 июля 2026 г. в 14:28, Варвара Ковригина <v.kovrigina@albato.ru>:\n\n"
        "> Наталья, здравствуйте!\n> Как удобно вас связать?\n"
    )
    assert _extract_body(_plain(body)) == "Добрый день!\nМожно через whats up"


def test_short_attribution_without_name():
    body = "Да\n\nвт, 8 сент. 2026 г., 16:00 <v.kovrigina@albato.ru>:\n\n> Здравствуйте, ваша заявка актуальна?\n"
    assert _extract_body(_plain(body)) == "Да"


def test_plain_without_quote_unchanged():
    assert _extract_body(_plain("Да, передавайте.\nСпасибо")) == "Да, передавайте.\nСпасибо"


def test_multipart_prefers_plain_part():
    msg = MIMEMultipart("alternative")
    msg.attach(_plain("Текст из plain"))
    msg.attach(_html("<div>Текст из html</div>"))
    assert _extract_body(msg) == "Текст из plain"


def test_multipart_html_only_converted():
    msg = MIMEMultipart("alternative")
    msg.attach(_html("<div>Только html</div><div>вторая строка</div>"))
    assert _extract_body(msg) == "Только html\nвторая строка"


def test_html_entities_and_br_converted():
    assert _extract_body(_html("Цена &lt;1000&gt; &quot;руб&quot;<br>итого")) == 'Цена <1000> "руб"\nитого'


def test_bottom_posted_reply_not_lost():
    body = "> Здравствуйте, ваша заявка актуальна?\n\nДа, актуальна"
    assert _extract_body(_plain(body)) == "Да, актуальна"


def test_signature_delimiter_cut():
    assert _extract_body(_plain("Согласны\n-- \nИван Петров\n+7 900 000-00-00")) == "Согласны"


def test_yandex_quote_header_without_separator_cut():
    body = (
        "Хотим, чтобы связался человек)<br /> <br /><b>Кому:</b> \"client@example.ru\" "
        "&lt;client@example.ru&gt;;<br /><b>Тема:</b> Ваша заявка на интеграцию — Альбато;<br />"
        "16:35, 29 июля 2026 г., \"v.kovrigina@albato.ru\" &lt;v.kovrigina@albato.ru&gt;:<br />"
        "<blockquote><p>Добрый день, Андрей!</p></blockquote>"
    )
    assert _extract_body(_html(body)) == "Хотим, чтобы связался человек)"


def test_english_attribution_without_angle_brackets_cut():
    body = (
        "Спасибо!\nВячеслав\n\nOn Mon, 07 Sep 2026 20:30:27 +0300, v.kovrigina@albato.ru wrote:\n\n"
        "Здравствуйте!\n\nМеня зовут Варвара"
    )
    assert _extract_body(_plain(body)) == "Спасибо!\nВячеслав"


def test_wrapped_two_line_attribution_cut():
    body = (
        "Спасибо,\nВячеслав\n\nOn Tue, 15 Sep 2026 23:19:56 -0500, \"Вячеслав Пузырный\"\n"
        "<client@example.com> wrote:\n\n> Варвара, доброе утро.\n"
    )
    assert _extract_body(_plain(body)) == "Спасибо,\nВячеслав"


def test_year_line_before_attribution_kept():
    body = "Запуск планируем в 2026 году\nOn Mon, 07 Sep 2026 20:30:27 +0300, v.kovrigina@albato.ru wrote:\n> Привет"
    assert _extract_body(_plain(body)) == "Запуск планируем в 2026 году"


# --- Пункт 7 аудита 2026-10-28: письма помечаются прочитанными только после обработки ---

import asyncio

import pytest

from email_channel import poller


class _FakeImap:
    def __init__(self, messages):
        self.messages = messages  # {uid: raw bytes}
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        pass

    def select(self, box):
        pass

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "SEARCH":
            return "OK", [b" ".join(self.messages)]
        if command == "FETCH":
            return "OK", [(b"1 (BODY[] {n})", self.messages[args[0]])]
        return "OK", [b""]


def _raw(from_addr, body, charset="utf-8", subject="Re: заявка"):
    return (
        f"From: {from_addr}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset={charset}\r\n\r\n"
    ).encode() + body.encode("utf-8")


def test_fetch_uses_peek_and_does_not_mark_seen(monkeypatch):
    fake = _FakeImap({b"7": _raw("a@example.com", "Да")})
    monkeypatch.setattr(poller.imaplib, "IMAP4_SSL", lambda *a, **k: fake)
    items = poller._fetch_unseen_sync()
    assert [uid for uid, _ in items] == [b"7"]
    assert ("FETCH", b"7", "(BODY.PEEK[])") in fake.commands
    assert not any(c[0] == "STORE" for c in fake.commands)


def test_unknown_charset_is_read_as_utf8():
    msg = poller.email_lib.message_from_bytes(_raw("a@example.com", "Да, передавайте", charset="unknown-8bit"))
    assert poller._extract_body(msg) == "Да, передавайте"


@pytest.fixture()
def mailbox(monkeypatch, repo):
    from core import state_machine
    from db.models import Channel

    monkeypatch.setattr(poller, "settings", type("S", (), {"email_imap_host": "imap.example.com"})())
    monkeypatch.setattr(poller, "_processed_uids", set())
    env = {"seen": [], "handled": [], "alerts": [], "order": []}

    def mark_seen(uid):
        env["seen"].append(uid)
        env["order"].append(("seen", uid))

    async def handle(deal_id, text, channel):
        env["handled"].append((deal_id, text))
        env["order"].append(("handled", deal_id))

    monkeypatch.setattr(poller, "_mark_seen_sync", mark_seen)
    monkeypatch.setattr(state_machine, "handle_incoming_reply", handle)
    monkeypatch.setattr(
        poller.report_webhook, "send_error_notification", lambda marker, message: env["alerts"].append(message)
    )
    repo.create_deal_new(501, 1, "Клиент", None, "client@example.com", "amoCRM", "Кейс")
    repo.set_awaiting_first_sent(501, Channel.EMAIL.value, None, "2026-10-29T11:00:00+00:00")
    return env


def _run(monkeypatch, items):
    monkeypatch.setattr(poller, "_fetch_unseen_sync", lambda: items)
    asyncio.run(poller.poll_once())


def test_client_reply_handled_before_marked_seen(monkeypatch, mailbox):
    _run(monkeypatch, [(b"1", _raw("client@example.com", "Да, передавайте"))])
    assert mailbox["order"] == [("handled", 501), ("seen", b"1")]


def test_broken_email_alerts_and_does_not_block_next(monkeypatch, mailbox):
    def broken_parse(raw):
        if raw == b"BROKEN":
            raise LookupError("unknown encoding: x-weird")
        return original(raw)

    original = poller._parse_message
    monkeypatch.setattr(poller, "_parse_message", broken_parse)
    _run(monkeypatch, [(b"1", b"BROKEN"), (b"2", _raw("client@example.com", "Да"))])
    assert mailbox["handled"] == [(501, "Да")]
    assert set(mailbox["seen"]) == {b"1", b"2"}
    assert len(mailbox["alerts"]) == 1


def test_non_client_and_auto_reply_marked_seen_without_handling(monkeypatch, mailbox):
    _run(monkeypatch, [
        (b"1", _raw("stranger@example.com", "Привет")),
        (b"2", _raw("client@example.com", "Я в отпуске", subject="Автоответ: заявка")),
    ])
    assert mailbox["handled"] == []
    assert set(mailbox["seen"]) == {b"1", b"2"}


def test_failed_mark_seen_not_reprocessed_in_same_run(monkeypatch, mailbox):
    def failing_mark(uid):
        raise OSError("IMAP down")

    monkeypatch.setattr(poller, "_mark_seen_sync", failing_mark)
    items = [(b"1", _raw("client@example.com", "Да"))]
    _run(monkeypatch, items)
    _run(monkeypatch, items)
    assert mailbox["handled"] == [(501, "Да")]
