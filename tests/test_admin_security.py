"""Pre-launch admin security checks - each test proves one specific claim
about the admin surface rather than just exercising a happy path."""

import pytest

from app import create_app
from app.config import TestConfig


def test_password_is_hashed_not_stored_in_plaintext(db, admin_user):
    stored = db.admins.find_one({"_id": admin_user["_id"]})
    assert stored["password_hash"] != "supersecret1"
    assert stored["password_hash"].startswith(("pbkdf2:", "scrypt:"))


def test_logout_invalidates_the_session(client, admin_user):
    client.post("/admin/login", data={"email": admin_user["email"], "password": "supersecret1"})
    assert client.get("/admin/dashboard").status_code == 200

    client.get("/admin/logout")

    resp = client.get("/admin/dashboard", follow_redirects=True)
    assert b"log in" in resp.data.lower()


@pytest.mark.parametrize("path", ["/admin/products", "/admin/orders", "/admin/categories", "/admin/settings", "/admin/staff", "/admin/messages"])
def test_every_admin_page_requires_login(client, path):
    resp = client.get(path, follow_redirects=True)
    assert b"log in" in resp.data.lower()


def test_staff_list_never_exposes_password_hashes(client, admin_user):
    client.post("/admin/login", data={"email": admin_user["email"], "password": "supersecret1"})
    resp = client.get("/admin/staff")
    assert b"pbkdf2:" not in resp.data
    assert b"scrypt:" not in resp.data
    assert b"password_hash" not in resp.data


def test_login_is_rate_limited():
    """A dedicated app instance with CSRF off but rate limiting on (the
    default `client` fixture shares limiter state across tests in ways that
    would make this flaky, so this spins up its own)."""
    app = create_app(TestConfig)
    with app.test_client() as client:
        responses = [
            client.post("/admin/login", data={"email": "nobody@x.com", "password": "wrong"})
            for _ in range(10)
        ]
    assert any(r.status_code == 429 for r in responses)


def test_csrf_is_enforced_on_admin_forms():
    """TestConfig disables CSRF for test convenience elsewhere in this suite -
    this proves the *production* posture (CSRF enabled) actually rejects a
    state-changing POST that arrives without a token."""

    class _CsrfEnabledConfig(TestConfig):
        WTF_CSRF_ENABLED = True

    app = create_app(_CsrfEnabledConfig)
    with app.test_client() as client:
        with app.app_context():
            from app.extensions import get_db
            from werkzeug.security import generate_password_hash
            import datetime
            get_db().admins.insert_one({
                "email": "owner@moromokeh.com",
                "password_hash": generate_password_hash("supersecret1"),
                "created_at": datetime.datetime.now(datetime.timezone.utc),
            })

        resp = client.post("/admin/login", data={"email": "owner@moromokeh.com", "password": "supersecret1"})
        assert resp.status_code == 400  # CSRF token missing/invalid
