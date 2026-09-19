"""Startup guards that make production fail fast (at boot) instead of failing
late (500s on first request) when a required credential is missing."""

import pytest

from app import create_app
from app.config import Config


class _ProdNoSecret(Config):
    FLASK_ENV = "production"
    SECRET_KEY = "dev-only-insecure-key"
    MONGO_URI = "mongomock"


class _ProdNoMongo(Config):
    FLASK_ENV = "production"
    SECRET_KEY = "a-real-random-looking-secret-key"
    MONGO_URI = ""


class _ProdConfiguredCorrectly(Config):
    FLASK_ENV = "production"
    SECRET_KEY = "a-real-random-looking-secret-key"
    MONGO_URI = "mongomock"


def test_refuses_to_start_in_production_with_default_secret_key():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(_ProdNoSecret)


def test_refuses_to_start_in_production_without_mongo_uri():
    with pytest.raises(RuntimeError, match="MONGO_URI"):
        create_app(_ProdNoMongo)


def test_starts_fine_in_production_when_properly_configured():
    app = create_app(_ProdConfiguredCorrectly)
    assert app is not None
    with app.test_client() as client:
        assert client.get("/healthz").status_code == 200
