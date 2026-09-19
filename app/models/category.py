def list_active_categories(db):
    return list(db.categories.find({"is_active": True}).sort("sort_order", 1))


def list_all_categories(db):
    return list(db.categories.find().sort("sort_order", 1))
