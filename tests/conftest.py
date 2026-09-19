import datetime
import shutil
import tempfile

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import get_db


@pytest.fixture()
def app():
    upload_dir = tempfile.mkdtemp(prefix="moromokeh-test-uploads-")

    class _TestConfig(TestConfig):
        UPLOAD_FOLDER = upload_dir

    application = create_app(_TestConfig)
    yield application
    shutil.rmtree(upload_dir, ignore_errors=True)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    with app.app_context():
        yield get_db()


@pytest.fixture()
def category(db):
    doc = {
        "name": "Dresses", "slug": "dresses", "description": "",
        "is_active": True, "sort_order": 0, "created_at": datetime.datetime.now(datetime.timezone.utc),
    }
    result = db.categories.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


@pytest.fixture()
def product(db, category):
    doc = {
        "name": "Ankara Wrap Dress",
        "slug": "ankara-wrap-dress",
        "description": "A wrap dress.",
        "price": 15000.0,
        "sale_price": None,
        "category_id": category["_id"],
        "category_name": category["name"],
        "category_slug": category["slug"],
        "sizes": ["S", "M", "L"],
        "size_stock": {"S": 2, "M": 0, "L": 5},
        "stock": 7,
        "in_stock": True,
        "colors": ["Blue"],
        "images": [{"id": "abc", "thumb": "/static/images/product-placeholder.svg",
                    "medium": "/static/images/product-placeholder.svg",
                    "large": "/static/images/product-placeholder.svg"}],
        "is_featured": True, "is_new": True, "is_bestseller": False, "is_published": True,
        "meta_description": "A wrap dress.",
        "created_at": datetime.datetime.now(datetime.timezone.utc), "updated_at": datetime.datetime.now(datetime.timezone.utc),
    }
    result = db.products.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


@pytest.fixture()
def admin_user(db):
    from werkzeug.security import generate_password_hash
    doc = {
        "email": "owner@moromokeh.com",
        "password_hash": generate_password_hash("supersecret1"),
        "created_at": datetime.datetime.now(datetime.timezone.utc),
    }
    result = db.admins.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc
