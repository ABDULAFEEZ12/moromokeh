from functools import wraps

from flask import session, redirect, url_for, flash, request

from app.extensions import get_db
from app.utils.db import safe_objectid


def admin_required(view):
    """Gate an admin route on a valid server-side session, and hand the
    current admin document to the view so it never has to re-fetch it."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        admin_id = safe_objectid(session.get("admin_id"))
        admin = None
        if admin_id:
            admin = get_db().admins.find_one({"_id": admin_id})
        if not admin:
            session.pop("admin_id", None)
            flash("Please log in to access the admin area.", "error")
            return redirect(url_for("admin.login", next=request.path))
        return view(admin, *args, **kwargs)

    return wrapped
