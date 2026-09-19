from app.services import cart as cart_service


def test_add_to_cart_and_view(client, product):
    resp = client.post("/cart/add", data={
        "product_id": str(product["_id"]), "size": "S", "color": "Blue", "qty": "2",
    }, follow_redirects=True)
    assert resp.status_code == 200

    resp = client.get("/cart")
    assert product["name"].encode() in resp.data
    assert b"30,000" in resp.data or b"30000" in resp.data  # 2 x 15,000


def test_cart_add_ignores_external_next_url_to_prevent_open_redirect(client, product):
    resp = client.post("/cart/add", data={
        "product_id": str(product["_id"]), "size": "S", "color": "Blue", "qty": "1",
        "next": "https://evil.example/phish",
    })
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/shop"


def test_cart_rejects_out_of_stock_size(client, product):
    resp = client.post("/cart/add", data={
        "product_id": str(product["_id"]), "size": "M", "color": "Blue", "qty": "1",
    }, follow_redirects=True)
    assert b"out of stock" in resp.data.lower() or resp.status_code == 200

    resp = client.get("/cart")
    assert b"empty" in resp.data.lower()


def test_cart_resolve_clamps_quantity_to_available_stock(app, db, product):
    with app.test_request_context():
        cart_service.add_item(str(product["_id"]), "S", "Blue", 1)
        # Manually push qty above stock to simulate a stale session cart.
        items = cart_service.get_raw_items()
        items[0]["qty"] = 99
        cart_service._save(items)

        resolved = cart_service.resolve(db)
        assert resolved["lines"][0]["qty"] == 2  # size S only has 2 in stock
        assert any("Only" in issue for issue in resolved["issues"])


def test_cart_resolve_drops_unpublished_product(app, db, product):
    with app.test_request_context():
        cart_service.add_item(str(product["_id"]), "S", "Blue", 1)
        db.products.update_one({"_id": product["_id"]}, {"$set": {"is_published": False}})
        resolved = cart_service.resolve(db)
        assert resolved["lines"] == []
        assert resolved["issues"]
