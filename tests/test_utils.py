from app.utils.db import slugify, safe_objectid


def test_slugify_basic():
    assert slugify("Ankara Wrap Dress") == "ankara-wrap-dress"


def test_slugify_strips_punctuation_and_collapses_spaces():
    assert slugify("  Two-Piece   Set!! ") == "two-piece-set"


def test_slugify_empty_falls_back():
    assert slugify("") == "item"


def test_safe_objectid_rejects_garbage():
    assert safe_objectid("not-an-id") is None
    assert safe_objectid(None) is None


def test_unique_slug_appends_suffix_on_collision(db):
    from app.utils.db import unique_slug
    db.categories.insert_one({"slug": "dresses"})
    assert unique_slug(db.categories, "Dresses") == "dresses-2"
