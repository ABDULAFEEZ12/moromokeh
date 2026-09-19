import re
import unicodedata

from bson.objectid import ObjectId


def safe_objectid(value):
    """Parse a Mongo ObjectId from a string, or None if it isn't one.

    Every route that takes an id from the URL or a form must go through this
    instead of trusting the id is well-formed - a malformed id must never
    reach a query as a raw string.
    """
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def convert_doc(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return doc


def convert_cursor(cursor):
    return [convert_doc(doc) for doc in cursor]


def slugify(text, max_length=80):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    text = re.sub(r"[\s-]+", "-", text)
    return text[:max_length].strip("-") or "item"


def unique_slug(collection, base_text, exclude_id=None):
    """Turn a name into a slug, appending -2, -3, ... until it's free in `collection`."""
    base = slugify(base_text)
    slug = base
    n = 2
    while True:
        query = {"slug": slug}
        if exclude_id is not None:
            query["_id"] = {"$ne": exclude_id}
        if not collection.find_one(query, {"_id": 1}):
            return slug
        slug = f"{base}-{n}"
        n += 1
