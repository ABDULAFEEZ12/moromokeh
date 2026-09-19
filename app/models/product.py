"""Read-side helpers for product documents.

Products are stored denormalized (category name/slug copied onto the
product) so the catalog and category pages never need a join query - a
listing page is always a single indexed `find()` against `products`.
"""

PLACEHOLDER_IMAGE = "/static/images/product-placeholder.svg"


def primary_image(product, size="medium"):
    images = product.get("images") or []
    if not images:
        return PLACEHOLDER_IMAGE
    return images[0].get(size) or images[0].get("large") or images[0].get("thumb") or PLACEHOLDER_IMAGE


def enrich(product):
    """Attach display-only computed fields to a product dict. Never persisted."""
    if product is None:
        return None
    price = float(product.get("price") or 0)
    sale_price = product.get("sale_price")
    on_sale = sale_price is not None and float(sale_price) > 0 and float(sale_price) < price

    product["display_price"] = float(sale_price) if on_sale else price
    product["compare_at_price"] = price if on_sale else None
    product["on_sale"] = on_sale
    product["discount_percent"] = round((1 - float(sale_price) / price) * 100) if on_sale and price > 0 else 0
    product["image_url"] = primary_image(product)
    product["gallery"] = product.get("images") or []

    size_stock = product.get("size_stock") or {}
    if size_stock:
        product["in_stock"] = any(qty > 0 for qty in size_stock.values())
    else:
        product["in_stock"] = float(product.get("stock") or 0) > 0
    return product


def enrich_many(products):
    return [enrich(p) for p in products]


def total_stock(size_stock, fallback_stock):
    if size_stock:
        return sum(max(0, int(q)) for q in size_stock.values())
    return max(0, int(fallback_stock or 0))
