"""Server-authoritative shopping cart.

The session only ever stores *intent*: which product, which size/color, how
many. Every price and every stock number shown to the customer - and used
at checkout - is read fresh from MongoDB in `resolve()`. The frontend never
supplies a price, and nothing here ever trusts one.
"""

from flask import session

from app.utils.db import safe_objectid
from app.models.product import enrich, primary_image

SESSION_KEY = "cart"
MAX_LINE_QTY = 10


def _line_key(product_id, size, color):
    return f"{product_id}:{size or ''}:{color or ''}"


def get_raw_items():
    return session.get(SESSION_KEY, [])


def _save(items):
    session[SESSION_KEY] = items
    session.permanent = True
    session.modified = True


def add_item(product_id, size, color, qty):
    qty = max(1, min(MAX_LINE_QTY, int(qty or 1)))
    size = (size or "").strip() or None
    color = (color or "").strip() or None
    items = get_raw_items()
    key = _line_key(product_id, size, color)
    for item in items:
        if _line_key(item["product_id"], item.get("size"), item.get("color")) == key:
            item["qty"] = min(MAX_LINE_QTY, item["qty"] + qty)
            _save(items)
            return
    items.append({"product_id": product_id, "size": size, "color": color, "qty": qty})
    _save(items)


def update_item(line_key, qty):
    qty = max(0, min(MAX_LINE_QTY, int(qty or 0)))
    items = get_raw_items()
    if qty == 0:
        items = [i for i in items if _line_key(i["product_id"], i.get("size"), i.get("color")) != line_key]
    else:
        for item in items:
            if _line_key(item["product_id"], item.get("size"), item.get("color")) == line_key:
                item["qty"] = qty
    _save(items)


def remove_item(line_key):
    items = [i for i in get_raw_items() if _line_key(i["product_id"], i.get("size"), i.get("color")) != line_key]
    _save(items)


def clear():
    session.pop(SESSION_KEY, None)


def resolve(db):
    """Join the session's raw cart against live product data.

    Returns dict(lines, subtotal, item_count, issues). Also self-heals the
    session: unavailable lines are dropped and over-quantity lines are
    clamped, so a stale cart never lingers past one page view.
    """
    raw_items = get_raw_items()
    if not raw_items:
        return {"lines": [], "subtotal": 0.0, "item_count": 0, "issues": []}

    ids = {safe_objectid(i["product_id"]) for i in raw_items}
    ids.discard(None)
    products_by_id = {}
    if ids:
        for doc in db.products.find({"_id": {"$in": list(ids)}}):
            products_by_id[str(doc["_id"])] = doc

    lines = []
    issues = []
    healed_items = []

    for raw in raw_items:
        product = products_by_id.get(raw["product_id"])
        if not product or not product.get("is_published", True):
            issues.append("An item in your cart is no longer available and was removed.")
            continue

        size_stock = product.get("size_stock") or {}
        has_sizes = bool(product.get("sizes"))
        size = raw.get("size")

        if has_sizes:
            if not size or size not in size_stock:
                issues.append(f"{product['name']} needs a size to be selected - please add it again.")
                continue
            available = int(size_stock.get(size, 0))
        else:
            available = int(product.get("stock") or 0)

        if available <= 0:
            issues.append(f"{product['name']} is out of stock and was removed from your cart.")
            continue

        qty = min(int(raw["qty"]), available, MAX_LINE_QTY)
        if qty < int(raw["qty"]):
            issues.append(f"Only {available} of {product['name']} left - quantity adjusted.")

        price = float(product.get("sale_price")) if product.get("sale_price") else float(product.get("price") or 0)
        line = {
            "line_key": _line_key(raw["product_id"], size, raw.get("color")),
            "product_id": raw["product_id"],
            "slug": product.get("slug"),
            "name": product["name"],
            "image": primary_image(product, "thumb"),
            "size": size,
            "color": raw.get("color"),
            "price": price,
            "qty": qty,
            "available": available,
            "line_total": round(price * qty, 2),
        }
        lines.append(line)
        healed_items.append({"product_id": raw["product_id"], "size": size, "color": raw.get("color"), "qty": qty})

    if healed_items != raw_items:
        _save(healed_items)

    subtotal = round(sum(l["line_total"] for l in lines), 2)
    item_count = sum(l["qty"] for l in lines)
    return {"lines": lines, "subtotal": subtotal, "item_count": item_count, "issues": issues}


def count(db=None):
    """Cheap badge count without a DB round-trip - good enough for the header icon."""
    return sum(int(i.get("qty", 0)) for i in get_raw_items())
