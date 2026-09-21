import datetime
import re

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    current_app, abort,
)
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import get_db, limiter
from app.utils.db import safe_objectid, convert_doc, convert_cursor, unique_slug
from app.utils.decorators import admin_required
from app.utils.http import safe_next_path
from app.utils.pagination import paginate
from app.services.images import process_and_save, delete_image_files, ImageValidationError
from app.models.product import total_stock
from app.models.order import FULFILLMENT_STATUSES

bp = Blueprint("admin", __name__, url_prefix="/admin")

SIZE_PRESETS = {
    "clothing": ["XS", "S", "M", "L", "XL", "XXL"],
    "numeric": ["6", "8", "10", "12", "14", "16", "18", "20"],
}
LOW_STOCK_THRESHOLD = 3


# ---------------------------------------------------------------- auth ----

@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("8 per minute")
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        admin = get_db().admins.find_one({"email": email})
        if not admin or not check_password_hash(admin["password_hash"], password):
            flash("Invalid email or password.", "error")
            return redirect(url_for("admin.login"))
        session.clear()
        session["admin_id"] = str(admin["_id"])
        session.permanent = True
        flash("Welcome back.", "success")
        return redirect(safe_next_path(request.args.get("next")) or url_for("admin.dashboard"))
    return render_template("admin/login.html")


@bp.route("/logout")
def logout():
    session.pop("admin_id", None)
    flash("Logged out.", "success")
    return redirect(url_for("admin.login"))


# ----------------------------------------------------------- dashboard ----

@bp.route("")
@admin_required
def index(admin):
    return redirect(url_for("admin.dashboard"))


@bp.route("/dashboard")
@admin_required
def dashboard(admin):
    db = get_db()
    total_orders = db.orders.count_documents({})
    paid_orders = db.orders.count_documents({"payment_status": "paid"})
    pending_orders = db.orders.count_documents({"payment_status": "pending"})
    revenue_agg = list(db.orders.aggregate([
        {"$match": {"payment_status": "paid"}},
        {"$group": {"_id": None, "total": {"$sum": "$total"}}},
    ]))
    revenue = revenue_agg[0]["total"] if revenue_agg else 0
    total_products = db.products.count_documents({})
    low_stock = list(db.products.find(
        {"stock": {"$lte": LOW_STOCK_THRESHOLD, "$gt": 0}, "is_published": True}
    ).sort("stock", 1).limit(10))
    recent_orders = convert_cursor(db.orders.find().sort("created_at", -1).limit(8))

    return render_template(
        "admin/dashboard.html",
        total_orders=total_orders, paid_orders=paid_orders, pending_orders=pending_orders,
        revenue=revenue, total_products=total_products,
        low_stock=convert_cursor(low_stock), recent_orders=recent_orders,
    )


# ------------------------------------------------------------ products ----

@bp.route("/products")
@admin_required
def products(admin):
    db = get_db()
    q = request.args.get("q", "").strip()
    # re.escape so a product search containing regex metacharacters (parens,
    # "+", "." etc. - all plausible in real names like "Co-ord (2 Piece)")
    # matches literally instead of being interpreted as a pattern, and can't
    # be used to hand MongoDB's regex engine something pathological.
    query = {"name": {"$regex": re.escape(q), "$options": "i"}} if q else {}
    page = request.args.get("page", 1, type=int)
    docs, page, total_pages, total = paginate(db.products, query, page, 20, sort=[("created_at", -1)])
    return render_template(
        "admin/products.html", products=convert_cursor(docs), q=q,
        page=page, total_pages=total_pages, total=total,
        pagination_endpoint="admin.products", pagination_args={"q": q},
    )


def _parse_size_stock(form):
    size_stock = {}
    for key in form.keys():
        if key.startswith("size_qty_"):
            size = key[len("size_qty_"):]
            raw = form.get(key, "").strip()
            if raw:
                try:
                    qty = int(raw)
                    if qty > 0:
                        size_stock[size] = qty
                except ValueError:
                    pass
    return size_stock


def _product_form_context(db, product=None):
    return dict(
        product=product,
        categories=list(db.categories.find().sort("sort_order", 1)),
        size_presets=SIZE_PRESETS,
    )


@bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_new(admin):
    db = get_db()
    if request.method == "POST":
        error = _save_product(db, None)
        if error:
            flash(error, "error")
            return render_template("admin/product_form.html", **_product_form_context(db), form=request.form)
        flash("Product created.", "success")
        return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", **_product_form_context(db), form={})


@bp.route("/products/<product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(admin, product_id):
    db = get_db()
    obj_id = safe_objectid(product_id)
    doc = db.products.find_one({"_id": obj_id}) if obj_id else None
    if not doc:
        abort(404)
    if request.method == "POST":
        error = _save_product(db, doc)
        if error:
            flash(error, "error")
            return render_template("admin/product_form.html", **_product_form_context(db, convert_doc(doc)), form=request.form)
        flash("Product updated.", "success")
        return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", **_product_form_context(db, convert_doc(doc)), form=convert_doc(doc))


def _save_product(db, existing):
    name = request.form.get("name", "").strip()
    price = request.form.get("price", "")
    category_id = safe_objectid(request.form.get("category_id", ""))
    description = request.form.get("description", "").strip()
    sale_price_raw = request.form.get("sale_price", "").strip()
    colors = [c.strip() for c in request.form.getlist("color") if c.strip()]

    if not name:
        return "Product name is required."
    try:
        price = float(price)
        if price < 0:
            return "Price cannot be negative."
    except ValueError:
        return "Price must be a valid number."

    sale_price = None
    if sale_price_raw:
        try:
            sale_price = float(sale_price_raw)
            if sale_price < 0 or sale_price >= price:
                return "Sale price must be positive and less than the regular price."
        except ValueError:
            return "Sale price must be a valid number."

    category = db.categories.find_one({"_id": category_id}) if category_id else None
    if not category:
        return "Please choose a category."

    size_stock = _parse_size_stock(request.form)
    if size_stock:
        stock = total_stock(size_stock, 0)
    else:
        try:
            stock = max(0, int(request.form.get("stock", "0") or "0"))
        except ValueError:
            return "Stock must be a valid whole number."

    doc = {
        "name": name,
        "description": description,
        "price": price,
        "sale_price": sale_price,
        "category_id": category["_id"],
        "category_name": category["name"],
        "category_slug": category["slug"],
        "sizes": list(size_stock.keys()),
        "size_stock": size_stock,
        "stock": stock,
        "in_stock": stock > 0,
        "colors": colors,
        "is_featured": request.form.get("is_featured") == "on",
        "is_new": request.form.get("is_new") == "on",
        "is_bestseller": request.form.get("is_bestseller") == "on",
        "is_published": request.form.get("is_published", "on") == "on",
        "meta_description": (description[:160] if description else name),
        "updated_at": datetime.datetime.now(datetime.timezone.utc),
    }

    if existing:
        doc["slug"] = existing["slug"] if existing["name"] == name else unique_slug(db.products, name, exclude_id=existing["_id"])
        images = existing.get("images", [])
    else:
        doc["slug"] = unique_slug(db.products, name)
        doc["created_at"] = datetime.datetime.now(datetime.timezone.utc)
        images = []

    remove_ids = set(request.form.getlist("remove_image"))
    if remove_ids:
        kept = []
        for img in images:
            if img.get("id") in remove_ids:
                delete_image_files(img, current_app.config["UPLOAD_FOLDER"])
            else:
                kept.append(img)
        images = kept

    uploaded_files = [f for f in request.files.getlist("images") if f and f.filename]
    for file in uploaded_files:
        try:
            urls = process_and_save(file, current_app.config["UPLOAD_FOLDER"])
        except ImageValidationError as exc:
            return str(exc)
        import uuid
        urls["id"] = uuid.uuid4().hex
        images.append(urls)

    if not images:
        return "At least one product image is required."

    doc["images"] = images

    if existing:
        db.products.update_one({"_id": existing["_id"]}, {"$set": doc})
    else:
        db.products.insert_one(doc)
    return None


@bp.route("/products/<product_id>/delete", methods=["POST"])
@admin_required
def product_delete(admin, product_id):
    db = get_db()
    obj_id = safe_objectid(product_id)
    doc = db.products.find_one({"_id": obj_id}) if obj_id else None
    if doc:
        for img in doc.get("images", []):
            delete_image_files(img, current_app.config["UPLOAD_FOLDER"])
        db.products.delete_one({"_id": obj_id})
        flash("Product deleted.", "success")
    return redirect(url_for("admin.products"))


# ---------------------------------------------------------- categories ----

def _create_category(db, name, description=""):
    name = name.strip()
    if not name:
        return None, "Category name is required."
    slug = unique_slug(db.categories, name)
    max_sort = db.categories.count_documents({})
    doc = {
        "name": name, "slug": slug, "description": description.strip(),
        "is_active": True, "sort_order": max_sort,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
    }
    result = db.categories.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc, None


@bp.route("/categories", methods=["GET", "POST"])
@admin_required
def categories(admin):
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "")
        description = request.form.get("description", "")
        _, error = _create_category(db, name, description)
        flash(error or "Category added.", "error" if error else "success")
        return redirect(url_for("admin.categories"))
    cats = convert_cursor(db.categories.find().sort("sort_order", 1))
    return render_template("admin/categories.html", categories=cats)


@bp.route("/categories/quick-add", methods=["POST"])
@admin_required
def category_quick_add(admin):
    db = get_db()
    name = request.form.get("name", "")
    doc, error = _create_category(db, name)
    if error:
        return {"error": error}, 400
    return {"id": str(doc["_id"]), "name": doc["name"]}


@bp.route("/categories/<category_id>/toggle", methods=["POST"])
@admin_required
def category_toggle(admin, category_id):
    db = get_db()
    obj_id = safe_objectid(category_id)
    cat = db.categories.find_one({"_id": obj_id}) if obj_id else None
    if cat:
        db.categories.update_one({"_id": obj_id}, {"$set": {"is_active": not cat.get("is_active", True)}})
    return redirect(url_for("admin.categories"))


@bp.route("/categories/<category_id>/delete", methods=["POST"])
@admin_required
def category_delete(admin, category_id):
    db = get_db()
    obj_id = safe_objectid(category_id)
    if obj_id and db.products.count_documents({"category_id": obj_id}) > 0:
        flash("Can't delete a category that still has products in it.", "error")
    elif obj_id:
        db.categories.delete_one({"_id": obj_id})
        flash("Category deleted.", "success")
    return redirect(url_for("admin.categories"))


# --------------------------------------------------------------- orders ----

@bp.route("/orders")
@admin_required
def orders(admin):
    db = get_db()
    payment_status = request.args.get("payment_status", "")
    fulfillment_status = request.args.get("fulfillment_status", "")
    query = {}
    if payment_status:
        query["payment_status"] = payment_status
    if fulfillment_status:
        query["fulfillment_status"] = fulfillment_status
    page = request.args.get("page", 1, type=int)
    docs, page, total_pages, total = paginate(db.orders, query, page, 20, sort=[("created_at", -1)])
    return render_template(
        "admin/orders.html", orders=convert_cursor(docs), page=page, total_pages=total_pages,
        total=total, payment_status=payment_status, fulfillment_status=fulfillment_status,
        statuses=FULFILLMENT_STATUSES,
        pagination_endpoint="admin.orders",
        pagination_args={"payment_status": payment_status, "fulfillment_status": fulfillment_status},
    )


@bp.route("/orders/<order_number>")
@admin_required
def order_detail(admin, order_number):
    db = get_db()
    order = db.orders.find_one({"order_number": order_number})
    if not order:
        abort(404)
    return render_template("admin/order_detail.html", order=convert_doc(order), statuses=FULFILLMENT_STATUSES)


@bp.route("/orders/<order_number>/status", methods=["POST"])
@admin_required
def order_update_status(admin, order_number):
    db = get_db()
    status = request.form.get("fulfillment_status", "")
    if status not in FULFILLMENT_STATUSES:
        flash("Invalid status.", "error")
    else:
        db.orders.update_one(
            {"order_number": order_number},
            {"$set": {"fulfillment_status": status, "updated_at": datetime.datetime.now(datetime.timezone.utc)}},
        )
        flash("Order status updated.", "success")
    return redirect(url_for("admin.order_detail", order_number=order_number))


# -------------------------------------------------------------- settings --

@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings(admin):
    db = get_db()
    if request.method == "POST":
        try:
            delivery_fee = max(0.0, float(request.form.get("delivery_fee", "0") or "0"))
        except ValueError:
            flash("Delivery fee must be a number.", "error")
            return redirect(url_for("admin.settings"))
        db.settings.update_one({"_id": "general"}, {"$set": {"delivery_fee": delivery_fee}}, upsert=True)
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    current = db.settings.find_one({"_id": "general"}) or {}
    return render_template("admin/settings.html", delivery_fee=current.get("delivery_fee", 0))


# ------------------------------------------------------------- messages ----

@bp.route("/messages")
@admin_required
def messages(admin):
    db = get_db()
    page = request.args.get("page", 1, type=int)
    docs, page, total_pages, total = paginate(db.messages, {}, page, 20, sort=[("created_at", -1)])
    return render_template(
        "admin/messages.html", messages=convert_cursor(docs), page=page, total_pages=total_pages, total=total,
        pagination_endpoint="admin.messages", pagination_args={},
    )


# ---------------------------------------------------------------- staff ----

@bp.route("/staff", methods=["GET", "POST"])
@admin_required
def staff(admin):
    db = get_db()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not email or len(password) < 8:
            flash("Email and an 8+ character password are required.", "error")
        elif password != confirm:
            flash("Passwords don't match.", "error")
        elif db.admins.find_one({"email": email}):
            flash("An admin with that email already exists.", "error")
        else:
            db.admins.insert_one({
                "email": email, "password_hash": generate_password_hash(password),
                "created_by": admin["email"], "created_at": datetime.datetime.now(datetime.timezone.utc),
            })
            flash("Admin account created.", "success")
        return redirect(url_for("admin.staff"))
    admins = convert_cursor(db.admins.find({}, {"password_hash": 0}))
    return render_template("admin/staff.html", admins=admins)
