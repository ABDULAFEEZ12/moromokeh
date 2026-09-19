def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_home_page_renders(client, product):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Moromokeh" in resp.data
    assert product["name"].encode() in resp.data


def test_product_detail_page(client, product):
    resp = client.get(f"/product/{product['slug']}")
    assert resp.status_code == 200
    assert product["name"].encode() in resp.data
    # Size M has zero stock and must render as disabled, never purchasable.
    assert b'value="M" disabled' in resp.data


def test_product_detail_404_for_unknown_slug(client):
    resp = client.get("/product/does-not-exist")
    assert resp.status_code == 404


def test_shop_listing_and_category_page(client, product, category):
    resp = client.get("/shop")
    assert resp.status_code == 200
    assert product["name"].encode() in resp.data

    resp = client.get(f"/category/{category['slug']}")
    assert resp.status_code == 200
    assert product["name"].encode() in resp.data


def test_category_hides_unpublished_products(client, db, product):
    db.products.update_one({"_id": product["_id"]}, {"$set": {"is_published": False}})
    resp = client.get("/shop")
    assert product["name"].encode() not in resp.data
