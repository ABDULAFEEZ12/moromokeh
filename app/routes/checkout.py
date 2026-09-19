import datetime
import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, abort

from app.extensions import get_db, limiter, csrf
from app.services import cart as cart_service
from app.services.payments import SquadcoService, PaymentServiceUnavailable
from app.services.orders import finalize_paid_order
from app.services.notify import send_order_notification
from app.models.order import generate_order_number, generate_payment_reference
from app.utils.db import convert_doc

bp = Blueprint("checkout", __name__)
logger = logging.getLogger("moromokeh")

NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno",
    "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu", "FCT - Abuja", "Gombe",
    "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi", "Kwara", "Lagos",
    "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto",
    "Taraba", "Yobe", "Zamfara",
]

# How much slack to allow between what was charged and what the order says it
# should cost. SquadCo (like most Nigerian gateways) can round kobo slightly
# differently than we do, so a *tiny* tolerance avoids false "mismatch"
# rejections on otherwise-legitimate payments, without opening the door to
# someone paying meaningfully less than the order total.
AMOUNT_MATCH_TOLERANCE = 0.99


def get_delivery_fee(db):
    settings = db.settings.find_one({"_id": "general"}) or {}
    return float(settings.get("delivery_fee", 0))


def get_payment_service():
    return SquadcoService(current_app.config["SQUADCO_SECRET_KEY"], current_app.config["SQUADCO_ENV"])


def _callback_url(payment_reference):
    # SquadCo's docs don't pin down what query param (if any) it appends to
    # callback_url on redirect, so we don't rely on one - we embed our own
    # reference here and treat that as the only thing that determines which
    # order the callback is about. The actual payment status is never taken
    # from this redirect either way; see `callback()` below.
    return url_for("checkout.callback", ref=payment_reference, _external=True)


def _amount_matches(paid_kobo, order_total_naira):
    expected_kobo = round(order_total_naira * 100)
    return paid_kobo >= expected_kobo * AMOUNT_MATCH_TOLERANCE


def _reconciliation_fields(txn, finalized_via):
    # Recorded on the order at the moment it's finalized so an admin can see
    # exactly what SquadCo confirmed - gateway reference, channel used, and
    # which trigger (browser callback vs webhook) finalized it - without
    # needing to go digging through application logs.
    return {
        "gateway_reference": txn.get("gateway_reference"),
        "payment_channel": txn.get("channel"),
        "verified_amount_kobo": txn.get("amount_kobo"),
        "finalized_via": finalized_via,
    }


@bp.route("/checkout", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def checkout():
    db = get_db()
    resolved = cart_service.resolve(db)
    for issue in resolved["issues"]:
        flash(issue, "error")

    if not resolved["lines"]:
        flash("Your cart is empty.", "error")
        return redirect(url_for("cart.view"))

    delivery_fee = get_delivery_fee(db)
    total = round(resolved["subtotal"] + delivery_fee, 2)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        state = request.form.get("state", "").strip()
        city = request.form.get("city", "").strip()
        note = request.form.get("note", "").strip()

        errors = []
        if not name:
            errors.append("Full name is required.")
        if not phone or len(phone) < 7:
            errors.append("A valid phone number is required.")
        if not address:
            errors.append("Delivery address is required.")
        if state not in NIGERIAN_STATES:
            errors.append("Please select a valid state.")
        if not city:
            errors.append("City/town is required.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "checkout.html", cart=resolved, delivery_fee=delivery_fee, total=total,
                states=NIGERIAN_STATES, form=request.form,
            )

        order = {
            "order_number": generate_order_number(),
            "payment_reference": generate_payment_reference(),
            "items": resolved["lines"],
            "subtotal": resolved["subtotal"],
            "delivery_fee": delivery_fee,
            "total": total,
            "customer": {
                "name": name, "phone": phone, "email": email,
                "address": address, "state": state, "city": city, "note": note,
            },
            "payment_status": "pending",
            "fulfillment_status": "pending",
            "payment_method": "squadco",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
        }
        db.orders.insert_one(order)
        cart_service.clear()

        payments = get_payment_service()
        if not payments.is_configured:
            flash(
                f"Your order {order['order_number']} has been received. Online payment isn't set up yet - "
                f"please call or WhatsApp us on {current_app.config['STORE_PHONE']} to complete payment.",
                "success",
            )
            return redirect(url_for("checkout.order_status", order_number=order["order_number"]))

        try:
            result = payments.initialize_transaction(
                email=email or "orders@moromokeh.com",
                amount_naira=total,
                reference=order["payment_reference"],
                callback_url=_callback_url(order["payment_reference"]),
                customer_name=name,
                metadata={"order_number": order["order_number"]},
            )
            return redirect(result["checkout_url"])
        except PaymentServiceUnavailable as exc:
            logger.error("Payment init failed for %s: %s", order["order_number"], exc)
            flash(
                f"Your order {order['order_number']} was saved, but we couldn't start payment ({exc}). "
                f"Please call or WhatsApp us on {current_app.config['STORE_PHONE']} to complete payment.",
                "error",
            )
            return redirect(url_for("checkout.order_status", order_number=order["order_number"]))

    return render_template(
        "checkout.html", cart=resolved, delivery_fee=delivery_fee, total=total,
        states=NIGERIAN_STATES, form={},
    )


@bp.route("/checkout/retry/<order_number>", methods=["POST"])
@limiter.limit("10 per minute")
def retry_payment(order_number):
    db = get_db()
    order = db.orders.find_one({"order_number": order_number})
    if not order or order.get("payment_status") == "paid":
        flash("This order can't be retried.", "error")
        return redirect(url_for("checkout.order_status", order_number=order_number))

    payments = get_payment_service()
    try:
        result = payments.initialize_transaction(
            email=order["customer"].get("email") or "orders@moromokeh.com",
            amount_naira=order["total"],
            reference=order["payment_reference"],
            callback_url=_callback_url(order["payment_reference"]),
            customer_name=order["customer"].get("name"),
            metadata={"order_number": order["order_number"]},
        )
        return redirect(result["checkout_url"])
    except PaymentServiceUnavailable as exc:
        flash(f"Could not start payment: {exc}", "error")
        return redirect(url_for("checkout.order_status", order_number=order_number))


@bp.route("/checkout/callback")
def callback():
    """Browser-side landing page after SquadCo's checkout. This is a
    convenience redirect only - it re-verifies with SquadCo's API before
    finalizing anything, and the webhook (below) is the path that's actually
    relied on if the customer closes the tab before landing back here."""
    db = get_db()
    reference = request.args.get("ref", "")
    order = db.orders.find_one({"payment_reference": reference}) if reference else None
    if not order:
        flash("We couldn't find that order.", "error")
        return redirect(url_for("main.home"))

    if order.get("payment_status") != "paid":
        payments = get_payment_service()
        try:
            txn = payments.verify_transaction(reference)
        except PaymentServiceUnavailable:
            txn = None
        if txn and txn["status"] == "success" and _amount_matches(txn["amount_kobo"], order["total"]):
            order, did_work = finalize_paid_order(db, reference, _reconciliation_fields(txn, "callback"))
            if did_work:
                send_order_notification(current_app.config, order)

    return redirect(url_for("checkout.order_status", order_number=order["order_number"]))


@bp.route("/webhooks/squadco", methods=["POST"])
@csrf.exempt
def squadco_webhook():
    """Server-to-server confirmation - the reliable path that doesn't depend
    on the customer's browser making it back to the site after paying.

    Configure this URL (https://<your-domain>/webhooks/squadco) as the
    Webhook URL on the SquadCo dashboard under Profile > API & Webhook.
    """
    db = get_db()
    payments = get_payment_service()
    raw_body = request.get_data()
    signature = request.headers.get("x-squad-encrypted-body", "")

    if not payments.verify_webhook_signature(raw_body, signature):
        return jsonify({"status": "invalid signature"}), 401

    payload = request.get_json(silent=True) or {}
    event, reference, status, _body = payments.parse_webhook_event(payload)

    if event != "charge_successful" or not reference:
        return jsonify({"status": "ignored"}), 200

    # Don't trust the webhook body's amount/status directly - re-verify against
    # SquadCo's API, which is the one source of truth for what was actually paid.
    try:
        txn = payments.verify_transaction(reference)
    except PaymentServiceUnavailable:
        # Ask SquadCo to retry later rather than silently dropping the event.
        return jsonify({"status": "verify unavailable, will retry"}), 503

    if not txn or txn["status"] != "success":
        return jsonify({"status": "not successful"}), 200

    order = db.orders.find_one({"payment_reference": reference})
    if not order:
        logger.error("Webhook for unknown payment_reference %s", reference)
        return jsonify({"status": "unknown reference"}), 200

    if not _amount_matches(txn["amount_kobo"], order["total"]):
        logger.error("Webhook amount mismatch for %s: paid %s kobo, expected ~%s kobo",
                     reference, txn["amount_kobo"], order["total"] * 100)
        return jsonify({"status": "amount mismatch"}), 200

    order, did_work = finalize_paid_order(db, reference, _reconciliation_fields(txn, "webhook"))
    if did_work and order:
        send_order_notification(current_app.config, order)
    return jsonify({"status": "ok"}), 200


@bp.route("/order/<order_number>")
@limiter.limit("30 per minute")
def order_status(order_number):
    db = get_db()
    order = db.orders.find_one({"order_number": order_number})
    if not order:
        abort(404)
    return render_template("order_status.html", order=convert_doc(order))
