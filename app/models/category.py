def list_active_categories(db):
    return list(db.categories.find({"is_active": True}).sort("sort_order", 1))


def list_all_categories(db):
    return list(db.categories.find().sort("sort_order", 1))


def with_display_images(db, categories):
    """Attach a display-only `image` to categories that don't have one set,
    borrowed from that category's newest published product. Never persisted -
    mirrors the product model's enrich() pattern of computed, read-side fields.
    """
    from app.models.product import primary_image

    for cat in categories:
        if cat.get("image"):
            continue
        product = db.products.find_one(
            {"category_id": cat["_id"], "is_published": True},
            sort=[("created_at", -1)],
        )
        if product:
            cat["image"] = primary_image(product)
    return categories
