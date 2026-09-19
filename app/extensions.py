import logging

from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

logger = logging.getLogger("moromokeh")

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])

_db = None


def init_db(app):
    """Create the Mongo client once per process and stash it on the app.

    MONGO_URI == "mongomock" gives an in-memory database for local dev/tests
    that have no real Atlas cluster to point at. Everything else talks to a
    real MongoClient over TLS.
    """
    global _db
    uri = app.config["MONGO_URI"]

    if not uri:
        logger.warning("MONGO_URI is not set - database-backed routes will fail until it is configured.")
        _db = None
        return None

    if uri == "mongomock":
        import mongomock

        client = mongomock.MongoClient()
    else:
        import certifi
        from pymongo import MongoClient

        client = MongoClient(
            uri,
            tls=True,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=8000,
            appname="moromokeh-essential-store",
        )

    db = client[app.config["MONGO_DB_NAME"]]
    _db = db
    return db


def get_db():
    if _db is None:
        raise RuntimeError("Database is not initialized. Check MONGO_URI.")
    return _db
