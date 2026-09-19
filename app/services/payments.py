"""SquadCo integration, isolated behind this one class.

Nothing outside this module knows SquadCo's endpoint shapes, field names, or
signing scheme - the rest of the app calls `initialize_transaction`,
`verify_transaction`, and `verify_webhook_signature` and gets back plain,
normalized dicts/booleans. If the store ever needs a different processor,
this is the only file that changes.

Reference (current as of this writing): https://docs.squadco.com/Payments/Initiate-payment ,
https://docs.squadco.com/Payments/verify-transaction ,
https://docs.squadco.com/webhook-direct-url/signature-validation

Only one credential is required: a SquadCo secret key (Authorization: Bearer
<secret key> on every request). There is no separate public key to configure
here - the customer never touches SquadCo's API directly, they're redirected
to the hosted checkout_url SquadCo returns and SquadCo redirects them back.
"""

import hashlib
import hmac
import logging

import requests

logger = logging.getLogger("moromokeh")

SANDBOX_BASE_URL = "https://sandbox-api-d.squadco.com"
LIVE_BASE_URL = "https://api-d.squadco.com"

# SquadCo's own transaction_status values, lowercased for comparison.
_STATUS_MAP = {"success": "success", "failed": "failed", "abandoned": "abandoned", "pending": "pending"}


class PaymentServiceUnavailable(Exception):
    """Raised when SquadCo isn't configured, rejects a request, or can't be reached."""


class SquadcoService:
    def __init__(self, secret_key, environment="live"):
        self.secret_key = secret_key
        self.base_url = SANDBOX_BASE_URL if environment == "sandbox" else LIVE_BASE_URL

    @property
    def is_configured(self):
        return bool(self.secret_key)

    def _headers(self):
        return {"Authorization": f"Bearer {self.secret_key}", "Content-Type": "application/json"}

    def initialize_transaction(self, email, amount_naira, reference, callback_url, customer_name=None, metadata=None):
        """Start a hosted-checkout transaction. Returns {"checkout_url", "reference"}."""
        if not self.is_configured:
            raise PaymentServiceUnavailable("Payments are not configured yet.")

        payload = {
            "amount": int(round(amount_naira * 100)),  # kobo - 10000 = 100 NGN
            "email": email,
            "currency": "NGN",
            "initiate_type": "inline",
            "transaction_ref": reference,
            "callback_url": callback_url,
        }
        if customer_name:
            payload["customer_name"] = customer_name
        if metadata:
            payload["metadata"] = metadata

        try:
            resp = requests.post(f"{self.base_url}/transaction/initiate", headers=self._headers(), json=payload, timeout=15)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("SquadCo initiate failed: %s", exc)
            raise PaymentServiceUnavailable("Could not reach the payment service.")

        if not isinstance(data, dict):
            # SquadCo is down/misbehaving and returned something that parsed as
            # JSON but isn't the object shape documented - e.g. an HTML error
            # page that happens to parse, or a bare array. Treat it the same
            # as unreachable rather than letting a stray AttributeError/
            # KeyError turn into an unhandled 500 at checkout.
            logger.error("SquadCo initiate returned unexpected response shape: %r", data)
            raise PaymentServiceUnavailable("Payment could not be started.")

        body = data.get("data") or {}
        if not isinstance(body, dict):
            body = {}
        if data.get("status") != 200 or not body.get("checkout_url"):
            logger.error("SquadCo initiate rejected: %s", data)
            raise PaymentServiceUnavailable(data.get("message", "Payment could not be started."))

        return {"checkout_url": body["checkout_url"], "reference": body.get("transaction_ref", reference)}

    def verify_transaction(self, reference):
        """Query SquadCo for a transaction's true status.

        Returns None if the reference is unknown/invalid; otherwise a dict
        {"status": "success"|"failed"|"abandoned"|"pending"|"unknown",
         "amount_kobo": float, "email": str, "reference": str,
         "gateway_reference": str|None, "channel": str|None}.
        `gateway_reference` (SquadCo's own `gateway_transaction_ref`) and
        `channel` (card/bank/ussd/transfer) are for order-level reconciliation
        against SquadCo's own dashboard/statements - see app/routes/checkout.py.
        """
        if not self.is_configured:
            raise PaymentServiceUnavailable("Payments are not configured yet.")

        try:
            resp = requests.get(f"{self.base_url}/transaction/verify/{reference}", headers=self._headers(), timeout=15)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("SquadCo verify failed: %s", exc)
            raise PaymentServiceUnavailable("Could not reach the payment service.")

        if not isinstance(data, dict):
            logger.error("SquadCo verify returned unexpected response shape: %r", data)
            raise PaymentServiceUnavailable("Could not verify the payment.")

        body = data.get("data")
        if data.get("status") != 200 or not isinstance(body, dict) or not body:
            return None

        return {
            "status": _STATUS_MAP.get(str(body.get("transaction_status", "")).lower(), "unknown"),
            "amount_kobo": float(body.get("transaction_amount") or 0),
            "email": body.get("email"),
            "reference": body.get("transaction_ref", reference),
            "gateway_reference": body.get("gateway_transaction_ref"),
            "channel": body.get("transaction_type"),
        }

    def verify_webhook_signature(self, raw_body, signature_header):
        """Constant-time check of the `x-squad-encrypted-body` header:
        HMAC-SHA512(secret_key, raw_body), hex, uppercase."""
        if not self.secret_key or not signature_header:
            return False
        expected = hmac.new(self.secret_key.encode("utf-8"), raw_body, hashlib.sha512).hexdigest().upper()
        return hmac.compare_digest(expected, signature_header.upper())

    def parse_webhook_event(self, payload):
        """Pull (event, reference, status, body) out of a decoded webhook JSON payload."""
        event = payload.get("Event")
        body = payload.get("Body") or {}
        reference = body.get("transaction_ref")
        status = _STATUS_MAP.get(str(body.get("transaction_status", "")).lower(), "unknown")
        return event, reference, status, body
