from email_channel import sender


class _FakeSmtp:
    def __init__(self, host, port, timeout=None):
        self.captured_timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        pass

    def send_message(self, msg):
        pass


class _FakeImap:
    def __init__(self, host, port, timeout=None):
        self.captured_timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        pass

    def append(self, folder, flags, date, body):
        pass


def test_send_email_sync_passes_timeout_to_smtp_and_imap(monkeypatch):
    """P-043: без явного timeout imaplib/smtplib блокируются навсегда при зависшем TCP-коннекте,
    занимая поток из общего ThreadPoolExecutor приложения."""
    captured = {}

    def fake_smtp_ssl(host, port, timeout=None):
        instance = _FakeSmtp(host, port, timeout)
        captured["smtp_timeout"] = timeout
        return instance

    def fake_imap_ssl(host, port, timeout=None):
        instance = _FakeImap(host, port, timeout)
        captured["imap_timeout"] = timeout
        return instance

    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", fake_smtp_ssl)
    monkeypatch.setattr(sender.imaplib, "IMAP4_SSL", fake_imap_ssl)

    sender.send_email_sync("client@example.com", "Тема", "Текст письма")

    assert captured["smtp_timeout"] == sender._MAIL_TIMEOUT_SECONDS
    assert captured["imap_timeout"] == sender._MAIL_TIMEOUT_SECONDS
    assert captured["smtp_timeout"] is not None
