import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, current_app

from app.extensions import get_db, limiter
from app.models.product import enrich_many
from app.models.category import list_active_categories
from app.utils.db import convert_cursor

bp = Blueprint("main", __name__)


@bp.route("/")
def home():
    db = get_db()
    featured = enrich_many(convert_cursor(
        db.products.find({"is_published": True, "is_featured": True}).sort("created_at", -1).limit(8)
    ))
    new_arrivals = enrich_many(convert_cursor(
        db.products.find({"is_published": True, "is_new": True}).sort("created_at", -1).limit(8)
    ))
    if len(featured) < 4:
        # Not enough featured picks yet - fall back to the newest published products
        # so the homepage never looks sparse while the catalog is still small.
        featured = enrich_many(convert_cursor(
            db.products.find({"is_published": True}).sort("created_at", -1).limit(8)
        ))
    categories = list_active_categories(db)
    return render_template("home.html", featured=featured, new_arrivals=new_arrivals, categories=categories)


@bp.route("/about")
def about():
    return render_template("about.html")


@bp.route("/contact", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()
        if not name or not message:
            flash("Please fill in your name and message.", "error")
            return redirect(url_for("main.contact"))
        get_db().messages.insert_one({
            "name": name[:200],
            "email": email[:200],
            "subject": request.form.get("subject", "").strip()[:200],
            "message": message[:5000],
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        })
        flash("Thanks - we've received your message and will get back to you soon.", "success")
        return redirect(url_for("main.contact"))
    return render_template("contact.html")


@bp.route("/search")
def search():
    db = get_db()
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config["PRODUCTS_PER_PAGE"]
    products, total_pages, total = [], 1, 0

    if q:
        query = {"is_published": True, "$text": {"$search": q}}
        total = db.products.count_documents(query)
        import math
        total_pages = max(1, math.ceil(total / per_page))
        page = min(max(1, page), total_pages)
        cursor = (
            db.products.find(query, {"score": {"$meta": "textScore"}})
            .sort([("score", {"$meta": "textScore"})])
            .skip((page - 1) * per_page)
            .limit(per_page)
        )
        products = enrich_many(convert_cursor(cursor))

    return render_template(
        "search.html", products=products, query=q, page=page, total_pages=total_pages, total=total,
        pagination_endpoint="main.search", pagination_args={"q": q},
    )


@bp.route("/track-order", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def track_order():
    order = None
    searched = False
    if request.method == "POST":
        searched = True
        order_number = request.form.get("order_number", "").strip().upper()
        phone = request.form.get("phone", "").strip()
        if order_number and phone:
            doc = get_db().orders.find_one({"order_number": order_number, "customer.phone": phone})
            if doc:
                from app.utils.db import convert_doc
                order = convert_doc(doc)
        if not order:
            flash("No order found with that order number and phone number.", "error")
    return render_template("track_order.html", order=order, searched=searched)


@bp.route("/healthz")
def healthz():
    try:
        get_db().command("ping")
        return {"status": "ok"}, 200
    except Exception as exc:
        current_app.logger.error("Health check failed: %s", exc)
        return {"status": "error"}, 503


@bp.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /cart",
        "Disallow: /checkout",
        f"Sitemap: {current_app.config['SITE_URL']}/sitemap.xml",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@bp.route("/sitemap.xml")
def sitemap():
    db = get_db()
    site_url = current_app.config["SITE_URL"].rstrip("/")
    urls = [
        {"loc": f"{site_url}{url_for('main.home')}", "priority": "1.0"},
        {"loc": f"{site_url}{url_for('shop.shop')}", "priority": "0.9"},
        {"loc": f"{site_url}{url_for('shop.new_arrivals')}", "priority": "0.8"},
    ]
    for cat in list_active_categories(db):
        urls.append({"loc": f"{site_url}{url_for('shop.category', slug=cat['slug'])}", "priority": "0.7"})
    for prod in db.products.find({"is_published": True}, {"slug": 1, "updated_at": 1}):
        urls.append({"loc": f"{site_url}{url_for('shop.product_detail', slug=prod['slug'])}", "priority": "0.6"})

    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml.append(f"<url><loc>{u['loc']}</loc><priority>{u['priority']}</priority></url>")
    xml.append("</urlset>")
    return Response("\n".join(xml), mimetype="application/xml")
