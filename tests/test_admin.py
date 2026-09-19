import datetime
import io


def _login(client, admin_user):
    client.post("/admin/login", data={"email": admin_user["email"], "password": "supersecret1"})


def test_admin_dashboard_requires_login(client):
    resp = client.get("/admin/dashboard", follow_redirects=True)
    assert b"log in" in resp.data.lower()


def test_admin_login_and_dashboard(client, admin_user):
    resp = client.post("/admin/login", data={
        "email": admin_user["email"], "password": "supersecret1",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"dashboard" in resp.data.lower()


def test_admin_login_redirects_to_originally_requested_page(client, admin_user):
    # Hitting a protected page while logged out bounces through /admin/login?next=...
    first = client.get("/admin/categories", follow_redirects=True)
    assert b"?next=" in first.request.url.encode() or "next=" in first.request.query_string.decode()

    resp = client.post("/admin/login?next=/admin/categories", data={
        "email": admin_user["email"], "password": "supersecret1",
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert resp.request.path == "/admin/categories"


def test_admin_login_ignores_external_next_url_to_prevent_open_redirect(client, admin_user):
    resp = client.post("/admin/login?next=https://evil.example/phish", data={
        "email": admin_user["email"], "password": "supersecret1",
    })

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/dashboard"


def test_admin_login_ignores_protocol_relative_next_url(client, admin_user):
    resp = client.post("/admin/login?next=//evil.example/phish", data={
        "email": admin_user["email"], "password": "supersecret1",
    })

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/dashboard"


def test_admin_login_rejects_wrong_password(client, admin_user):
    resp = client.post("/admin/login", data={
        "email": admin_user["email"], "password": "wrong-password",
    }, follow_redirects=True)
    assert b"invalid" in resp.data.lower()


def test_admin_can_create_product_with_image(client, admin_user, category):
    client.post("/admin/login", data={"email": admin_user["email"], "password": "supersecret1"})

    image = (io.BytesIO(_tiny_png()), "test.png")
    resp = client.post("/admin/products/new", data={
        "name": "Test Top", "category_id": str(category["_id"]),
        "description": "A top.", "price": "5000", "sale_price": "",
        "stock": "10", "images": [image],
    }, content_type="multipart/form-data", follow_redirects=True)

    assert resp.status_code == 200
    assert b"test top" in resp.data.lower() or b"product created" in resp.data.lower()


def _base_order(product, **overrides):
    order = {
        "order_number": "MRK-TEST-ADMIN1", "payment_reference": "ref_admin_1",
        "items": [{"product_id": str(product["_id"]), "size": "S", "qty": 1, "name": product["name"], "price": 15000.0, "line_total": 15000.0}],
        "subtotal": 15000.0, "delivery_fee": 0, "total": 15000.0,
        "customer": {"name": "Jane", "phone": "080", "email": "", "address": "12 Allen Ave", "city": "Ikeja", "state": "Lagos", "note": ""},
        "payment_status": "pending", "fulfillment_status": "pending", "payment_method": "squadco",
        "created_at": datetime.datetime.now(datetime.timezone.utc), "updated_at": datetime.datetime.now(datetime.timezone.utc),
    }
    order.update(overrides)
    return order


def test_admin_order_detail_renders_with_reconciliation_fields(client, admin_user, db, product):
    _login(client, admin_user)
    db.orders.insert_one(_base_order(product,
        payment_status="paid", paid_at=datetime.datetime.now(datetime.timezone.utc),
        gateway_reference="SQABC123_1_1", payment_channel="Card",
        verified_amount_kobo=1500000.0, finalized_via="webhook",
    ))

    resp = client.get("/admin/orders/MRK-TEST-ADMIN1")

    assert resp.status_code == 200
    assert b"SQABC123_1_1" in resp.data
    assert b"webhook" in resp.data.lower()


def test_admin_order_detail_renders_for_legacy_order_without_reconciliation_fields(client, admin_user, db, product):
    """Orders created before reconciliation fields existed must not crash the
    admin order detail page - the fields just don't render."""
    _login(client, admin_user)
    db.orders.insert_one(_base_order(product))  # no gateway_reference/verified_amount_kobo/finalized_via/paid_at

    resp = client.get("/admin/orders/MRK-TEST-ADMIN1")

    assert resp.status_code == 200


def test_admin_product_search_escapes_regex_metacharacters(client, admin_user, db, category):
    """A product name with regex-special characters must be searchable
    literally, and a search string full of them must not be interpreted as
    a pattern against MongoDB (ReDoS / broken-match risk)."""
    _login(client, admin_user)
    db.products.insert_one({
        "name": "Co-ord Set (2 Piece)", "slug": "co-ord-set-2-piece", "description": "",
        "price": 9000.0, "sale_price": None,
        "category_id": category["_id"], "category_name": category["name"], "category_slug": category["slug"],
        "sizes": [], "size_stock": {}, "stock": 5, "in_stock": True, "colors": [],
        "images": [{"id": "x", "thumb": "/x.webp", "medium": "/x.webp", "large": "/x.webp"}],
        "is_featured": False, "is_new": False, "is_bestseller": False, "is_published": True,
        "meta_description": "", "created_at": datetime.datetime.now(datetime.timezone.utc),
        "updated_at": datetime.datetime.now(datetime.timezone.utc),
    })

    resp = client.get("/admin/products", query_string={"q": "Set (2 Piece)"})

    assert resp.status_code == 200
    assert b"Co-ord Set" in resp.data

    # A pathological regex-looking query must not blow up the request either.
    resp2 = client.get("/admin/products", query_string={"q": "(a+)+$"})
    assert resp2.status_code == 200


def _tiny_png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(120, 40, 60)).save(buf, format="PNG")
    return buf.getvalue()
