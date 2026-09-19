from unittest.mock import MagicMock, patch

from app.services.notify import send_order_notification


class _FakeConfig(dict):
    """Mirrors Flask's app.config: dict-like, not attribute-like."""


def _order():
    return {
        "order_number": "MRK-TEST-0001",
        "total": 15000.0,
        "items": [{"name": "Ankara Wrap Dress", "size": "S", "qty": 1, "line_total": 15000.0}],
        "customer": {"name": "Jane", "phone": "080", "email": "jane@example.com", "address": "12 Allen Ave", "city": "Ikeja", "state": "Lagos", "note": ""},
    }


def test_send_order_notification_noop_when_not_configured():
    config = _FakeConfig(MAIL_SERVER="", MAIL_USERNAME="", MAIL_PASSWORD="", ORDER_NOTIFY_EMAIL="")
    # Must not raise even though config is a plain dict, not an object with attributes.
    send_order_notification(config, _order())


@patch("app.services.notify.smtplib.SMTP")
def test_send_order_notification_sends_when_configured(mock_smtp_cls):
    mock_server = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_server
    config = _FakeConfig(
        MAIL_SERVER="smtp.example.com", MAIL_PORT=587, MAIL_USE_TLS=True,
        MAIL_USERNAME="store@example.com", MAIL_PASSWORD="secret",
        ORDER_NOTIFY_EMAIL="owner@moromokeh.com",
    )

    send_order_notification(config, _order())

    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("store@example.com", "secret")
    assert mock_server.sendmail.call_count == 1
    args = mock_server.sendmail.call_args[0]
    assert args[0] == "store@example.com"
    assert args[1] == ["owner@moromokeh.com"]
    assert "MRK-TEST-0001" in args[2]


@patch("app.services.notify.smtplib.SMTP", side_effect=OSError("connection refused"))
def test_send_order_notification_never_raises_on_smtp_failure(mock_smtp_cls):
    config = _FakeConfig(
        MAIL_SERVER="smtp.example.com", MAIL_PORT=587, MAIL_USE_TLS=True,
        MAIL_USERNAME="store@example.com", MAIL_PASSWORD="secret",
        ORDER_NOTIFY_EMAIL="owner@moromokeh.com",
    )
    # A broken mail server must never fail a checkout the customer already paid for.
    send_order_notification(config, _order())
