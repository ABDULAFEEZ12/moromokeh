from flask import Blueprint, render_template, request, current_app, abort

from app.extensions import get_db
from app.models.product import enrich_many, enrich
from app.models.category import list_active_categories
from app.utils.db import convert_cursor, convert_doc
from app.utils.pagination import paginate

bp = Blueprint("shop", __name__)

SORT_OPTIONS = {
    "newest": [("created_at", -1)],
    "price_asc": [("price", 1)],
    "price_desc": [("price", -1)],
    "name_asc": [("name", 1)],
    "bestseller": [("is_bestseller", -1), ("created_at", -1)],
}


def build_filters(args, base_query=None):
    query = dict(base_query or {})
    query["is_published"] = True

    min_price = args.get("min_price", type=float)
    max_price = args.get("max_price", type=float)
    if min_price is not None or max_price is not None:
        price_filter = {}
        if min_price is not None:
            price_filter["$gte"] = min_price
        if max_price is not None:
            price_filter["$lte"] = max_price
        query["price"] = price_filter

    if args.get("sale") == "1":
        query["sale_price"] = {"$gt": 0}
    if args.get("new") == "1":
        query["is_new"] = True
    if args.get("in_stock") == "1":
        query["in_stock"] = True

    return query


def render_listing(template, base_query, page_title, extra_context=None):
    db = get_db()
    query = build_filters(request.args, base_query)
    sort_key = request.args.get("sort", "newest")
    sort = SORT_OPTIONS.get(sort_key, SORT_OPTIONS["newest"])
    page = request.args.get("page", 1, type=int)

    docs, page, total_pages, total = paginate(
        db.products, query, page, current_app.config["PRODUCTS_PER_PAGE"], sort=sort
    )
    products = enrich_many(convert_cursor(docs))
    categories = list_active_categories(db)

    pagination_args = {k: v for k, v in request.args.items() if k != "page"}
    context = dict(
        products=products, categories=categories, page_title=page_title,
        page=page, total_pages=total_pages, total=total,
        pagination_endpoint=request.endpoint, pagination_args=pagination_args,
        sort=sort_key,
    )
    context.update(extra_context or {})
    return render_template(template, **context)


@bp.route("/shop")
def shop():
    category_slug = request.args.get("category")
    base_query = {"category_slug": category_slug} if category_slug else {}
    return render_listing("shop.html", base_query, "Shop All")


@bp.route("/category/<slug>")
def category(slug):
    db = get_db()
    cat = db.categories.find_one({"slug": slug, "is_active": True})
    if not cat:
        abort(404)
    return render_listing("shop.html", {"category_slug": slug}, cat["name"], {"active_category": convert_doc(cat)})


@bp.route("/new-arrivals")
def new_arrivals():
    return render_listing("shop.html", {"is_new": True}, "New Arrivals")


@bp.route("/product/<slug>")
def product_detail(slug):
    db = get_db()
    doc = db.products.find_one({"slug": slug, "is_published": True})
    if not doc:
        abort(404)
    product = enrich(convert_doc(doc))
    related_docs = db.products.find(
        {"category_slug": product.get("category_slug"), "slug": {"$ne": slug}, "is_published": True}
    ).limit(4)
    related = enrich_many(convert_cursor(related_docs))
    return render_template("product.html", product=product, related=related)
