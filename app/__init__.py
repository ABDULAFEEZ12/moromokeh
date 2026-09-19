import logging
import os

from flask import Flask, render_template, request

from app.config import Config
from app.extensions import csrf, limiter, init_db, get_db


def create_app(config_class=Config):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        static_folder=os.path.join(project_root, "static"),
        static_url_path="/static",
        template_folder="templates",
    )
    app.config.from_object(config_class)

    if app.config["FLASK_ENV"] == "production" and app.config["SECRET_KEY"] == "dev-only-insecure-key":
        raise RuntimeError(
            "SECRET_KEY is not set. Refusing to start in production with the default "
            "development key - sessions and CSRF tokens would be forgeable. Set SECRET_KEY "
            "in the environment (see .env.example)."
        )
    if app.config["FLASK_ENV"] == "production" and not app.config["MONGO_URI"]:
        raise RuntimeError(
            "MONGO_URI is not set. Refusing to start in production with no database - every "
            "page would 500 on first request instead of failing clearly at boot. Set MONGO_URI "
            "in the environment (see .env.example)."
        )

    _configure_logging(app)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    csrf.init_app(app)
    limiter.init_app(app)
    init_db(app)

    with app.app_context():
        _ensure_indexes(app)

    _register_blueprints(app)
    _register_context(app)
    _register_error_handlers(app)
    _register_security_headers(app)

    return app


def _configure_logging(app):
    level = logging.DEBUG if app.config["DEBUG"] else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _ensure_indexes(app):
    if not app.config["MONGO_URI"]:
        return
    try:
        db = get_db()
        db.products.create_index("slug", unique=True)
        db.products.create_index("category_slug")
        db.products.create_index([("is_published", 1), ("is_featured", 1)])
        db.products.create_index([("is_published", 1), ("is_new", 1)])
        db.products.create_index([("is_published", 1), ("in_stock", 1)])
        db.products.create_index([("created_at", -1)])
        db.products.create_index([("name", "text"), ("description", "text"), ("category_name", "text")])

        db.categories.create_index("slug", unique=True)
        db.categories.create_index("sort_order")

        db.orders.create_index("payment_reference", unique=True)
        db.orders.create_index("order_number", unique=True)
        db.orders.create_index([("created_at", -1)])
        db.orders.create_index("payment_status")
        db.orders.create_index("fulfillment_status")
        db.orders.create_index([("customer.phone", 1), ("order_number", 1)])

        db.admins.create_index("email", unique=True)
    except Exception as exc:
        app.logger.warning("Index setup skipped/failed: %s", exc)


def _register_blueprints(app):
    from app.routes.main import bp as main_bp
    from app.routes.shop import bp as shop_bp
    from app.routes.cart_routes import bp as cart_bp
    from app.routes.checkout import bp as checkout_bp
    from app.routes.admin import bp as admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(shop_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(admin_bp)


def _register_context(app):
    import datetime

    from app.services import cart as cart_service
    from app.models.category import list_active_categories

    @app.context_processor
    def inject_store():
        try:
            cart_count = cart_service.count()
        except Exception:
            cart_count = 0
        try:
            nav_categories = list_active_categories(get_db())[:6]
        except Exception:
            nav_categories = []
        return dict(
            store_name=app.config["STORE_NAME"],
            store_phone=app.config["STORE_PHONE"],
            store_tiktok=app.config["STORE_TIKTOK"],
            store_instagram=app.config["STORE_INSTAGRAM"],
            store_description=app.config["STORE_DESCRIPTION"],
            cart_count=cart_count,
            nav_categories=nav_categories,
            now_year=datetime.datetime.now(datetime.timezone.utc).year,
        )

    @app.template_filter("naira")
    def naira(amount):
        try:
            return "₦{:,.0f}".format(float(amount))
        except (TypeError, ValueError):
            return "₦0"


def _register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error("Unhandled server error on %s: %s", request.path, e)
        return render_template("500.html"), 500

    @app.errorhandler(413)
    def too_large(e):
        limit_mb = app.config["MAX_UPLOAD_MB"]
        return render_template(
            "500.html",
            message=f"That upload is too large (over {limit_mb}MB total). Try fewer or smaller images.",
        ), 413


def _register_security_headers(app):
    @app.after_request
    def set_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if app.config["FLASK_ENV"] != "development":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Uploaded product photos get a fresh UUID folder on every upload (see
        # app/services/images.py) and are never edited in place, so caching
        # them aggressively can't ever serve a stale image - unlike style.css/
        # main.js, which have no cache-busting and must stay revalidated.
        if request.path.startswith("/static/uploads/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
