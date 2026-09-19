import os


def _bool(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
    FLASK_ENV = os.environ.get("FLASK_ENV", "production")
    DEBUG = FLASK_ENV == "development"
    TESTING = False

    SITE_URL = os.environ.get("SITE_URL", "http://localhost:5000")
    STORE_NAME = "Moromokeh Essential Store"
    STORE_PHONE = "09113044150"
    STORE_TIKTOK = "Moromokeh Essential Store"
    STORE_INSTAGRAM = "Moromokeh Essential Store"
    STORE_DESCRIPTION = (
        "Moromokeh Essential Store is a fashion and lifestyle store offering "
        "quality and affordable wears and carefully selected essential items."
    )

    MONGO_URI = os.environ.get("MONGO_URI", "")
    MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "moromokeh")

    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

    # SquadCo: only a secret key is needed server-side (Bearer auth on every
    # request). SQUADCO_ENV picks which of SquadCo's two documented base URLs
    # to call - "sandbox" (https://sandbox-api-d.squadco.com) while testing,
    # "live" (https://api-d.squadco.com) once real card details are involved.
    SQUADCO_SECRET_KEY = os.environ.get("SQUADCO_SECRET_KEY", "")
    SQUADCO_ENV = os.environ.get("SQUADCO_ENV", "live")

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587") or "587")
    MAIL_USE_TLS = _bool(os.environ.get("MAIL_USE_TLS"), True)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    ORDER_NOTIFY_EMAIL = os.environ.get("ORDER_NOTIFY_EMAIL", "")

    MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "8"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024

    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "uploads")

    PRODUCTS_PER_PAGE = 12

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = FLASK_ENV != "development"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30  # 30 days, so carts survive a return visit

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")


class TestConfig(Config):
    TESTING = True
    MONGO_URI = "mongomock"
    SECRET_KEY = "test-secret"
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False
