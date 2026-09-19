"""Order creation and idempotent payment finalization.

`finalize_paid_order` is the one place stock actually moves. It's written
so that the SquadCo webhook and the browser's callback redirect can both
race to call it for the same reference and only one will do the work - the
`find_one_and_update` with `payment_status: {"$ne": "paid"}` is an atomic
compare-and-set, not a read-then-write, so there's no window for a double
decrement.
"""

import datetime
import logging

from pymongo import ReturnDocument

from app.utils.db import safe_objectid

logger = logging.getLogger("moromokeh")


def decrement_stock_for_line(db, line):
    """Best-effort, race-safe stock decrement for one resolved cart line.

    Uses a conditional update (only decrement if enough is on hand) so two
    concurrent orders can never together oversell a product. If the stock
    genuinely isn't there any more (a real race lost), it clamps to zero
    and reports the shortfall so the order can be flagged for the admin
    instead of silently pretending it shipped.
    """
    product_id = safe_objectid(line.get("product_id"))
    qty = int(line.get("qty") or 0)
    size = line.get("size")
    if not product_id or qty <= 0:
        return True

    if size:
        field = f"size_stock.{size}"
        result = db.products.update_one(
            {"_id": product_id, field: {"$gte": qty}},
            {"$inc": {field: -qty, "stock": -qty}},
        )
    else:
        result = db.products.update_one(
            {"_id": product_id, "stock": {"$gte": qty}},
            {"$inc": {"stock": -qty}},
        )

    ok = True
    if result.matched_count == 0:
        logger.warning("Stock shortfall for product %s (size=%s, qty=%s)", product_id, size, qty)
        if size:
            db.products.update_one({"_id": product_id}, {"$set": {f"size_stock.{size}": 0}})
        else:
            db.products.update_one({"_id": product_id}, {"$set": {"stock": 0}})
        ok = False

    # The `in_stock` flag is denormalized for fast catalog filtering (see
    # shop.build_filters) - keep it in sync now that `stock` just changed,
    # otherwise a sold-out item keeps showing under "In Stock Only".
    refreshed = db.products.find_one({"_id": product_id}, {"stock": 1})
    if refreshed is not None:
        db.products.update_one(
            {"_id": product_id},
            {"$set": {"in_stock": (refreshed.get("stock") or 0) > 0}},
        )
    return ok


def finalize_paid_order(db, payment_reference, extra_fields=None):
    """Atomically transition an order to paid and decrement stock exactly once.

    Safe to call from both the webhook and the callback redirect for the
    same reference; whichever arrives first does the work, the other is a
    no-op that just returns the already-finalized order.
    """
    update_fields = dict(extra_fields or {})
    update_fields["payment_status"] = "paid"
    update_fields["paid_at"] = datetime.datetime.now(datetime.timezone.utc)
    update_fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc)

    claimed = db.orders.find_one_and_update(
        {"payment_reference": payment_reference, "payment_status": {"$ne": "paid"}},
        {"$set": update_fields},
        return_document=ReturnDocument.AFTER,
    )

    if claimed is None:
        existing = db.orders.find_one({"payment_reference": payment_reference})
        if existing:
            return existing, False  # already finalized by the other trigger
        logger.error("finalize_paid_order called with no matching order for %s", payment_reference)
        return None, False

    stock_issue = False
    for line in claimed.get("items", []):
        ok = decrement_stock_for_line(db, line)
        stock_issue = stock_issue or not ok

    if stock_issue:
        db.orders.update_one({"_id": claimed["_id"]}, {"$set": {"stock_issue": True}})
        claimed["stock_issue"] = True

    return claimed, True
