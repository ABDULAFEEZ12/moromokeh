"""SquadCo payment integration tests.

Two layers:
- Unit tests for `SquadcoService` itself, with `requests` mocked out so
  nothing here ever makes a real HTTP call.
- Route-level tests for `/webhooks/squadco` and `/checkout/callback`, with
  `checkout.get_payment_service` monkeypatched to a fake so the routing,
  amount-matching, and idempotent-finalize logic is exercised without going
  through real network calls either.
"""

import datetime
import hashlib
import hmac
import json
from unittest.mock import Mock, patch

import pytest
import requests

import app.routes.checkout as checkout_module
from app.services.payments import SquadcoService, PaymentServiceUnavailable, SANDBOX_BASE_URL, LIVE_BASE_URL


# --------------------------------------------------------------------------
# SquadcoService unit tests
# --------------------------------------------------------------------------

def _mock_response(json_body):
    resp = Mock()
    resp.json.return_value = json_body
    return resp


def test_not_configured_raises_without_any_network_call():
    service = SquadcoService("")
    assert service.is_configured is False
    with pytest.raises(PaymentServiceUnavailable):
        service.initialize_transaction("a@b.com", 1000, "ref1", "https://x/callback")
    with pytest.raises(PaymentServiceUnavailable):
        service.verify_transaction("ref1")


def test_sandbox_and_live_base_url_selection():
    assert SquadcoService("key", "sandbox").base_url == SANDBOX_BASE_URL
    assert SquadcoService("key", "live").base_url == LIVE_BASE_URL
    assert SquadcoService("key").base_url == LIVE_BASE_URL  # defaults to live


@patch("app.services.payments.requests.post")
def test_initialize_transaction_success(mock_post):
    mock_post.return_value = _mock_response({
        "status": 200, "message": "success",
        "data": {"checkout_url": "https://sandbox-pay.squadco.com/abc123", "transaction_ref": "ref1"},
    })
    service = SquadcoService("sandbox_sk_test", "sandbox")

    result = service.initialize_transaction("a@b.com", 15000, "ref1", "https://x/callback", customer_name="Jane")

    assert result == {"checkout_url": "https://sandbox-pay.squadco.com/abc123", "reference": "ref1"}
    called_url, called_kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
    assert called_url == f"{SANDBOX_BASE_URL}/transaction/initiate"
    assert called_kwargs["headers"]["Authorization"] == "Bearer sandbox_sk_test"
    assert called_kwargs["json"]["amount"] == 1500000  # naira -> kobo
    assert called_kwargs["json"]["transaction_ref"] == "ref1"
    assert called_kwargs["json"]["initiate_type"] == "inline"
    assert called_kwargs["json"]["currency"] == "NGN"


@patch("app.services.payments.requests.post")
def test_initialize_transaction_rejected_by_squadco_raises(mock_post):
    mock_post.return_value = _mock_response({"status": 401, "message": "Initiate transaction Unauthorized", "data": None})
    service = SquadcoService("bad_key")

    with pytest.raises(PaymentServiceUnavailable):
        service.initialize_transaction("a@b.com", 1000, "ref1", "https://x/callback")


@patch("app.services.payments.requests.post")
def test_initialize_transaction_network_failure_raises(mock_post):
    mock_post.side_effect = requests.ConnectionError("boom")
    service = SquadcoService("sandbox_sk_test")

    with pytest.raises(PaymentServiceUnavailable):
        service.initialize_transaction("a@b.com", 1000, "ref1", "https://x/callback")


@patch("app.services.payments.requests.post")
def test_initialize_transaction_handles_non_dict_response_gracefully(mock_post):
    """An outage can make SquadCo (or a proxy in front of it) return something
    that parses as JSON but isn't the documented object shape - must degrade
    to PaymentServiceUnavailable, never an unhandled AttributeError/KeyError."""
    mock_post.return_value = _mock_response(["unexpected", "array", "response"])
    service = SquadcoService("sandbox_sk_test")

    with pytest.raises(PaymentServiceUnavailable):
        service.initialize_transaction("a@b.com", 1000, "ref1", "https://x/callback")


@patch("app.services.payments.requests.get")
def test_verify_transaction_success(mock_get):
    mock_get.return_value = _mock_response({
        "status": 200, "success": True, "message": "Success",
        "data": {
            "transaction_amount": 15000, "transaction_ref": "ref1", "email": "a@b.com",
            "transaction_status": "Success", "gateway_transaction_ref": "SQABC123_1_1", "transaction_type": "Card",
        },
    })
    service = SquadcoService("sandbox_sk_test")

    result = service.verify_transaction("ref1")

    assert result == {
        "status": "success", "amount_kobo": 15000.0, "email": "a@b.com", "reference": "ref1",
        "gateway_reference": "SQABC123_1_1", "channel": "Card",
    }
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == f"{LIVE_BASE_URL}/transaction/verify/ref1"


@pytest.mark.parametrize("squadco_status,expected", [
    ("Failed", "failed"), ("Abandoned", "abandoned"), ("Pending", "pending"),
])
@patch("app.services.payments.requests.get")
def test_verify_transaction_maps_all_known_statuses(mock_get, squadco_status, expected):
    mock_get.return_value = _mock_response({
        "status": 200, "data": {"transaction_amount": 5000, "transaction_ref": "ref1", "transaction_status": squadco_status},
    })
    service = SquadcoService("sandbox_sk_test")
    assert service.verify_transaction("ref1")["status"] == expected


@patch("app.services.payments.requests.get")
def test_verify_transaction_invalid_reference_returns_none(mock_get):
    mock_get.return_value = _mock_response({"status": 400, "success": False, "message": "Invalid transaction reference", "data": {}})
    service = SquadcoService("sandbox_sk_test")

    assert service.verify_transaction("does-not-exist") is None


@patch("app.services.payments.requests.get")
def test_verify_transaction_network_failure_raises(mock_get):
    mock_get.side_effect = requests.Timeout("timed out")
    service = SquadcoService("sandbox_sk_test")

    with pytest.raises(PaymentServiceUnavailable):
        service.verify_transaction("ref1")


@patch("app.services.payments.requests.get")
def test_verify_transaction_handles_non_dict_response_gracefully(mock_get):
    mock_get.return_value = _mock_response("not even json object")
    service = SquadcoService("sandbox_sk_test")

    with pytest.raises(PaymentServiceUnavailable):
        service.verify_transaction("ref1")


def test_verify_webhook_signature_matches_squadco_algorithm():
    service = SquadcoService("my_secret")
    body = json.dumps({"Event": "charge_successful"}).encode()
    expected = hmac.new(b"my_secret", body, hashlib.sha512).hexdigest().upper()

    assert service.verify_webhook_signature(body, expected) is True
    assert service.verify_webhook_signature(body, expected.lower()) is True
    assert service.verify_webhook_signature(body, "wrong") is False
    assert service.verify_webhook_signature(body, "") is False
    assert service.verify_webhook_signature(b"different body", expected) is False


def test_parse_webhook_event_extracts_reference_and_status():
    service = SquadcoService("secret")
    payload = {
        "Event": "charge_successful",
        "TransactionRef": "SQTEST123",
        "Body": {"transaction_ref": "SQTEST123", "transaction_status": "Success", "amount": 10000},
    }
    event, reference, status, body = service.parse_webhook_event(payload)
    assert event == "charge_successful"
    assert reference == "SQTEST123"
    assert status == "success"
    assert body["amount"] == 10000


# --------------------------------------------------------------------------
# Route-level tests: /webhooks/squadco and /checkout/callback
# --------------------------------------------------------------------------

class FakeSquadcoService:
    """Test double swapped in for the real SquadcoService via monkeypatch,
    so route tests exercise real routing/idempotency logic without any
    network access."""

    def __init__(self, signature_valid=True, verify_result="__unset__", verify_raises=None):
        self.is_configured = True
        self._signature_valid = signature_valid
        self._verify_result = verify_result
        self._verify_raises = verify_raises
        self.verify_calls = 0

    def verify_webhook_signature(self, raw_body, signature_header):
        return self._signature_valid

    def parse_webhook_event(self, payload):
        body = payload.get("Body") or {}
        return payload.get("Event"), body.get("transaction_ref"), "success", body

    def verify_transaction(self, reference):
        self.verify_calls += 1
        if self._verify_raises:
            raise self._verify_raises
        if self._verify_result == "__unset__":
            return {"status": "success", "amount_kobo": 1500000.0, "email": "a@b.com", "reference": reference}
        return self._verify_result

    def initialize_transaction(self, *args, **kwargs):
        raise AssertionError("not used by these tests")


def _insert_pending_order(db, product, reference="ref_webhook_1", order_number="MRK-TEST-WH1", total=15000.0):
    order = {
        "order_number": order_number, "payment_reference": reference,
        "items": [{"product_id": str(product["_id"]), "size": "S", "qty": 1, "name": product["name"], "price": 15000.0, "line_total": 15000.0}],
        "subtotal": total, "delivery_fee": 0, "total": total,
        "customer": {"name": "Jane", "phone": "080", "email": "", "address": "", "state": "", "city": "", "note": ""},
        "payment_status": "pending", "fulfillment_status": "pending", "payment_method": "squadco",
        "created_at": datetime.datetime.now(datetime.timezone.utc), "updated_at": datetime.datetime.now(datetime.timezone.utc),
    }
    db.orders.insert_one(order)
    return order


def _webhook_payload(reference):
    return {"Event": "charge_successful", "TransactionRef": reference, "Body": {"transaction_ref": reference, "transaction_status": "Success", "amount": 15000}}


def test_webhook_invalid_signature_rejected(client, monkeypatch, db, product):
    _insert_pending_order(db, product)
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: FakeSquadcoService(signature_valid=False))

    resp = client.post("/webhooks/squadco", json=_webhook_payload("ref_webhook_1"))

    assert resp.status_code == 401
    assert db.orders.find_one({"payment_reference": "ref_webhook_1"})["payment_status"] == "pending"


def test_webhook_ignores_non_charge_successful_event(client, monkeypatch, db, product):
    _insert_pending_order(db, product)
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: FakeSquadcoService())

    resp = client.post("/webhooks/squadco", json={"Event": "transfer_failed", "Body": {"transaction_ref": "ref_webhook_1"}})

    assert resp.status_code == 200
    assert db.orders.find_one({"payment_reference": "ref_webhook_1"})["payment_status"] == "pending"


def test_webhook_unknown_reference_ignored(client, monkeypatch, db):
    fake = FakeSquadcoService(verify_result={"status": "success", "amount_kobo": 5000.0, "email": "x@y.com", "reference": "ghost"})
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: fake)

    resp = client.post("/webhooks/squadco", json=_webhook_payload("ghost"))

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "unknown reference"


def test_webhook_amount_mismatch_does_not_finalize(client, monkeypatch, db, product):
    _insert_pending_order(db, product, reference="ref_mismatch", total=15000.0)
    fake = FakeSquadcoService(verify_result={"status": "success", "amount_kobo": 100.0, "email": "a@b.com", "reference": "ref_mismatch"})
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: fake)

    resp = client.post("/webhooks/squadco", json=_webhook_payload("ref_mismatch"))

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "amount mismatch"
    assert db.orders.find_one({"payment_reference": "ref_mismatch"})["payment_status"] == "pending"


def test_webhook_failed_verification_does_not_finalize(client, monkeypatch, db, product):
    _insert_pending_order(db, product, reference="ref_failed")
    fake = FakeSquadcoService(verify_result={"status": "failed", "amount_kobo": 15000.0, "email": "a@b.com", "reference": "ref_failed"})
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: fake)

    resp = client.post("/webhooks/squadco", json=_webhook_payload("ref_failed"))

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "not successful"
    assert db.orders.find_one({"payment_reference": "ref_failed"})["payment_status"] == "pending"


def test_webhook_verify_api_failure_returns_503_for_retry(client, monkeypatch, db, product):
    _insert_pending_order(db, product, reference="ref_down")
    fake = FakeSquadcoService(verify_raises=PaymentServiceUnavailable("network down"))
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: fake)

    resp = client.post("/webhooks/squadco", json=_webhook_payload("ref_down"))

    assert resp.status_code == 503
    assert db.orders.find_one({"payment_reference": "ref_down"})["payment_status"] == "pending"


def test_webhook_success_finalizes_and_decrements_inventory_exactly_once(client, monkeypatch, db, product):
    _insert_pending_order(db, product, reference="ref_ok")
    fake = FakeSquadcoService()
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: fake)

    resp1 = client.post("/webhooks/squadco", json=_webhook_payload("ref_ok"))
    assert resp1.status_code == 200
    assert resp1.get_json()["status"] == "ok"

    order = db.orders.find_one({"payment_reference": "ref_ok"})
    assert order["payment_status"] == "paid"
    refreshed_product = db.products.find_one({"_id": product["_id"]})
    assert refreshed_product["size_stock"]["S"] == 1  # 2 -> 1, decremented once

    # SquadCo's own docs warn the same webhook event can be delivered more
    # than once - a duplicate delivery must not double-decrement stock.
    resp2 = client.post("/webhooks/squadco", json=_webhook_payload("ref_ok"))
    assert resp2.status_code == 200

    refreshed_product_again = db.products.find_one({"_id": product["_id"]})
    assert refreshed_product_again["size_stock"]["S"] == 1  # unchanged on the duplicate delivery


def test_callback_route_unknown_reference_redirects_home(client):
    resp = client.get("/checkout/callback?ref=does-not-exist", follow_redirects=True)
    assert resp.status_code == 200
    assert b"couldn" in resp.data.lower() or b"home" in resp.request.path.lower() or resp.request.path == "/"


def test_callback_route_verifies_and_finalizes_on_success(client, monkeypatch, db, product):
    _insert_pending_order(db, product, reference="ref_callback_ok", order_number="MRK-TEST-CB1")
    fake = FakeSquadcoService()
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: fake)

    resp = client.get("/checkout/callback?ref=ref_callback_ok", follow_redirects=True)

    assert resp.status_code == 200
    assert db.orders.find_one({"payment_reference": "ref_callback_ok"})["payment_status"] == "paid"


def test_checkout_redirects_to_squadco_checkout_url_when_configured(client, monkeypatch, db, product):
    client.post("/cart/add", data={"product_id": str(product["_id"]), "size": "S", "color": "Blue", "qty": "1"})
    fake = FakeSquadcoService()
    fake.initialize_transaction = lambda **kwargs: {"checkout_url": "https://sandbox-pay.squadco.com/xyz", "reference": kwargs["reference"]}
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: fake)

    resp = client.post("/checkout", data={
        "name": "Jane Doe", "phone": "08012345678", "email": "jane@example.com",
        "address": "12 Allen Ave", "state": "Lagos", "city": "Ikeja", "note": "",
    })

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://sandbox-pay.squadco.com/xyz"


def test_checkout_survives_payment_api_failure(client, monkeypatch, db, product):
    """If SquadCo can't be reached at checkout time, the order the customer
    just placed must not disappear - it stays pending and they're told how
    to complete payment another way."""
    client.post("/cart/add", data={"product_id": str(product["_id"]), "size": "S", "color": "Blue", "qty": "1"})

    def _raise(**kwargs):
        raise PaymentServiceUnavailable("Could not reach the payment service.")

    fake = FakeSquadcoService()
    fake.initialize_transaction = _raise
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: fake)

    resp = client.post("/checkout", data={
        "name": "Jane Doe", "phone": "08012345678", "email": "jane@example.com",
        "address": "12 Allen Ave", "state": "Lagos", "city": "Ikeja", "note": "",
    }, follow_redirects=True)

    assert resp.status_code == 200
    order = db.orders.find_one({"customer.phone": "08012345678"})
    assert order is not None
    assert order["payment_status"] == "pending"


def test_callback_route_never_trusts_query_string_alone(client, monkeypatch, db, product):
    """The redirect landing on /checkout/callback is not itself proof of
    payment - only a successful server-side verify() can finalize the order,
    regardless of what the browser's query string claims."""
    _insert_pending_order(db, product, reference="ref_callback_unpaid", order_number="MRK-TEST-CB2")
    fake = FakeSquadcoService(verify_result={"status": "pending", "amount_kobo": 0.0, "email": "a@b.com", "reference": "ref_callback_unpaid"})
    monkeypatch.setattr(checkout_module, "get_payment_service", lambda: fake)

    client.get("/checkout/callback?ref=ref_callback_unpaid&status=success", follow_redirects=True)

    assert db.orders.find_one({"payment_reference": "ref_callback_unpaid"})["payment_status"] == "pending"
