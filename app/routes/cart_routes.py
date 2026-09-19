from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from app.extensions import get_db
from app.services import cart as cart_service
from app.utils.db import safe_objectid
from app.utils.http import safe_next_path

bp = Blueprint("cart", __name__, url_prefix="/cart")


def _wants_json():
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


@bp.route("")
def view():
    db = get_db()
    resolved = cart_service.resolve(db)
    for issue in resolved["issues"]:
        flash(issue, "error")
    return render_template("cart.html", cart=resolved)


@bp.route("/add", methods=["POST"])
def add():
    db = get_db()
    product_id = request.form.get("product_id", "")
    size = request.form.get("size", "")
    color = request.form.get("color", "")
    qty = request.form.get("qty", 1, type=int)

    obj_id = safe_objectid(product_id)
    product = db.products.find_one({"_id": obj_id, "is_published": True}) if obj_id else None

    if not product:
        flash("That product is no longer available.", "error")
    elif product.get("sizes") and size not in (product.get("size_stock") or {}):
        flash("Please choose a valid size.", "error")
    else:
        available = (product.get("size_stock") or {}).get(size) if product.get("sizes") else product.get("stock")
        if not available:
            flash(f"{product['name']} is out of stock.", "error")
        else:
            cart_service.add_item(product_id, size, color, qty)
            flash(f"Added {product['name']} to your cart.", "success")

    if _wants_json():
        return jsonify({"count": cart_service.count()})
    next_url = safe_next_path(request.form.get("next")) or url_for("shop.shop")
    return redirect(next_url)


@bp.route("/buy-now", methods=["POST"])
def buy_now():
    db = get_db()
    product_id = request.form.get("product_id", "")
    size = request.form.get("size", "")
    color = request.form.get("color", "")
    qty = request.form.get("qty", 1, type=int)

    obj_id = safe_objectid(product_id)
    product = db.products.find_one({"_id": obj_id, "is_published": True}) if obj_id else None
    if not product:
        flash("That product is no longer available.", "error")
        return redirect(url_for("shop.shop"))
    if product.get("sizes") and size not in (product.get("size_stock") or {}):
        flash("Please choose a valid size.", "error")
        return redirect(url_for("shop.product_detail", slug=product["slug"]))

    cart_service.add_item(product_id, size, color, qty)
    return redirect(url_for("checkout.checkout"))


@bp.route("/update/<path:line_key>", methods=["POST"])
def update(line_key):
    qty = request.form.get("qty", 0, type=int)
    cart_service.update_item(line_key, qty)
    return redirect(url_for("cart.view"))


@bp.route("/remove/<path:line_key>", methods=["POST"])
def remove(line_key):
    cart_service.remove_item(line_key)
    flash("Item removed from cart.", "success")
    return redirect(url_for("cart.view"))
