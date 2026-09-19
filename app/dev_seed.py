"""Populate the in-memory mongomock database with sample data for local
development only. Never runs against a real MONGO_URI."""

import datetime

from werkzeug.security import generate_password_hash

PLACEHOLDER = "/static/images/product-placeholder.svg"


def seed(app):
    from app.extensions import get_db

    with app.app_context():
        db = get_db()
        if db.admins.count_documents({}) == 0:
            email = app.config["ADMIN_EMAIL"] or "owner@moromokeh.com"
            password = app.config["ADMIN_PASSWORD"] or "devpassword123"
            db.admins.insert_one({
                "email": email, "password_hash": generate_password_hash(password),
                "created_by": "dev_seed", "created_at": datetime.datetime.now(datetime.timezone.utc),
            })
            app.logger.info("Dev seed: admin created (%s / %s)", email, password)

        if db.categories.count_documents({}) > 0:
            return

        categories = ["Dresses", "Two-Piece Sets", "Tops", "Bags"]
        cat_docs = {}
        for i, name in enumerate(categories):
            slug = name.lower().replace(" ", "-")
            db.categories.insert_one({
                "name": name, "slug": slug, "description": "",
                "is_active": True, "sort_order": i,
                "created_at": datetime.datetime.now(datetime.timezone.utc),
            })
            cat_docs[name] = slug

        sample_products = [
            ("Ankara Wrap Dress", "Dresses", 18500, 15500, ["S", "M", "L"], True, True, False),
            ("Satin Slip Dress", "Dresses", 22000, None, ["S", "M", "L", "XL"], False, True, False),
            ("Co-ord Two-Piece Set", "Two-Piece Sets", 25000, None, ["S", "M", "L"], True, False, True),
            ("Ribbed Crop Top", "Tops", 8000, 6500, ["S", "M", "L"], False, False, True),
            ("Structured Tote Bag", "Bags", 14000, None, [], False, True, False),
        ]
        for i, (name, cat, price, sale, sizes, featured, is_new, bestseller) in enumerate(sample_products):
            slug = name.lower().replace(" ", "-")
            size_stock = {s: 5 for s in sizes}
            db.products.insert_one({
                "name": name, "slug": slug, "description": f"{name} - a Moromokeh Essential Store pick.",
                "price": float(price), "sale_price": float(sale) if sale else None,
                "category_id": db.categories.find_one({"name": cat})["_id"],
                "category_name": cat, "category_slug": cat_docs[cat],
                "sizes": sizes, "size_stock": size_stock,
                "stock": sum(size_stock.values()) if size_stock else 12,
                "in_stock": True, "colors": ["Black", "Wine"],
                "images": [{"id": f"seed{i}", "thumb": PLACEHOLDER, "medium": PLACEHOLDER, "large": PLACEHOLDER}],
                "is_featured": featured, "is_new": is_new, "is_bestseller": bestseller, "is_published": True,
                "meta_description": name,
                "created_at": datetime.datetime.now(datetime.timezone.utc),
                "updated_at": datetime.datetime.now(datetime.timezone.utc),
            })
        app.logger.info("Dev seed: sample categories and products created.")
