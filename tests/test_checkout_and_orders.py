import datetime

from app.services.orders import finalize_paid_order
from app.services.payments import SquadcoService


def _add_to_cart(client, product, size="S", qty=1):
    client.post("/cart/add", data={
        "product_id": str(product["_id"]), "size": size, "color": "Blue", "qty": str(qty),
    })


def test_checkout_without_squadco_creates_pending_order(client, db, product):
    _add_to_cart(client, product)
    resp = client.post("/checkout", data={
        "name": "Jane Doe", "phone": "08012345678", "email": "jane@example.com",
        "address": "12 Allen Ave", "state": "Lagos", "city": "Ikeja", "note": "",
    }, follow_redirects=True)
    assert resp.status_code == 200

    order = db.orders.find_one({"customer.phone": "08012345678"})
    assert order is not None
    assert order["payment_status"] == "pending"
    assert order["items"][0]["qty"] == 1
    assert order["subtotal"] == 15000.0


def test_checkout_rejects_missing_required_fields(client, product):
    _add_to_cart(client, product)
    resp = client.post("/checkout", data={
        "name": "", "phone": "", "address": "", "state": "", "city": "",
    })
    assert resp.status_code == 200
    assert b"required" in resp.data.lower()


def test_checkout_empty_cart_redirects_to_cart(client):
    resp = client.post("/checkout", data={"name": "X"}, follow_redirects=True)
    assert b"cart is empty" in resp.data.lower()


def test_finalize_paid_order_is_idempotent_and_decrements_stock_once(app, db, product):
    order = {
        "order_number": "MRK-TEST-0001",
        "payment_reference": "ref_test_1",
        "items": [{"product_id": str(product["_id"]), "size": "S", "qty": 2, "name": product["name"], "price": 15000.0, "line_total": 30000.0}],
        "subtotal": 30000.0, "delivery_fee": 0, "total": 30000.0,
        "customer": {"name": "Jane", "phone": "080", "email": "", "address": "", "state": "", "city": "", "note": ""},
        "payment_status": "pending", "fulfillment_status": "pending", "payment_method": "squadco",
        "created_at": datetime.datetime.now(datetime.timezone.utc), "updated_at": datetime.datetime.now(datetime.timezone.utc),
    }
    db.orders.insert_one(order)

    with app.app_context():
        first, did_work_1 = finalize_paid_order(db, "ref_test_1")
        second, did_work_2 = finalize_paid_order(db, "ref_test_1")

    assert did_work_1 is True
    assert did_work_2 is False  # second call is a no-op, already finalized

    refreshed = db.products.find_one({"_id": product["_id"]})
    assert refreshed["size_stock"]["S"] == 0  # 2 decremented once, not twice
    assert refreshed["stock"] == 5  # 7 - 2, not 7 - 4


def test_finalize_paid_order_syncs_in_stock_flag_when_depleted(app, db, category):
    product = {
        "name": "Last Piece Top", "slug": "last-piece-top", "description": "",
        "price": 5000.0, "sale_price": None,
        "category_id": category["_id"], "category_name": category["name"], "category_slug": category["slug"],
        "sizes": [], "size_stock": {}, "stock": 1, "in_stock": True, "colors": [],
        "images": [], "is_featured": False, "is_new": False, "is_bestseller": False, "is_published": True,
        "meta_description": "", "created_at": datetime.datetime.now(datetime.timezone.utc),
        "updated_at": datetime.datetime.now(datetime.timezone.utc),
    }
    product_id = db.products.insert_one(product).inserted_id

    order = {
        "order_number": "MRK-TEST-0002", "payment_reference": "ref_test_2",
        "items": [{"product_id": str(product_id), "size": None, "qty": 1, "name": "Last Piece Top", "price": 5000.0, "line_total": 5000.0}],
        "subtotal": 5000.0, "delivery_fee": 0, "total": 5000.0,
        "customer": {"name": "Jane", "phone": "080", "email": "", "address": "", "state": "", "city": "", "note": ""},
        "payment_status": "pending", "fulfillment_status": "pending", "payment_method": "squadco",
        "created_at": datetime.datetime.now(datetime.timezone.utc), "updated_at": datetime.datetime.now(datetime.timezone.utc),
    }
    db.orders.insert_one(order)

    with app.app_context():
        finalize_paid_order(db, "ref_test_2")

    refreshed = db.products.find_one({"_id": product_id})
    assert refreshed["stock"] == 0
    assert refreshed["in_stock"] is False


def test_webhook_signature_verification():
    service = SquadcoService("test_secret_key")
    body = b'{"Event":"charge_successful"}'
    import hmac, hashlib
    valid_sig = hmac.new(b"test_secret_key", body, hashlib.sha512).hexdigest().upper()
    assert service.verify_webhook_signature(body, valid_sig) is True
    assert service.verify_webhook_signature(body, valid_sig.lower()) is True  # comparison is case-insensitive
    assert service.verify_webhook_signature(body, "not-a-real-signature") is False
    assert service.verify_webhook_signature(body, "") is False
