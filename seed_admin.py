"""Create the first admin account from ADMIN_EMAIL / ADMIN_PASSWORD in .env.

Run once, locally or as a one-off command on the host:
    python seed_admin.py

There is deliberately no web route that does this - an admin-creation
endpoint reachable over HTTP is a standing vulnerability, not a convenience.
"""

import datetime
import getpass
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402
from app.extensions import get_db  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402


def main():
    app = create_app()
    with app.app_context():
        db = get_db()
        email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("ADMIN_PASSWORD", "")

        if not email:
            email = input("Admin email: ").strip().lower()
        if not password:
            password = getpass.getpass("Admin password: ")

        if not email or len(password) < 8:
            print("An email and a password of at least 8 characters are required.")
            sys.exit(1)

        if db.admins.find_one({"email": email}):
            print(f"An admin with email {email} already exists. Nothing to do.")
            return

        db.admins.insert_one({
            "email": email,
            "password_hash": generate_password_hash(password),
            "created_by": "seed_admin.py",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        })
        print(f"Admin account created for {email}.")


if __name__ == "__main__":
    main()
