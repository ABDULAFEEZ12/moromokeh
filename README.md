# Moromokeh Essential Store

Production Flask/MongoDB ecommerce platform for Moromokeh Essential Store — a
Nigerian women's fashion and lifestyle brand. Built as a clean-room rewrite
informed by an audit of an earlier project ("Ladeystoree"), not a copy of it.

## Stack

Python, Flask, Jinja2, MongoDB (PyMongo), vanilla JS, Pillow, Gunicorn.
No frontend framework, no build step.

## Project layout

```
app/
  __init__.py       app factory, blueprint/index/error/header wiring
  config.py         env-driven config
  extensions.py     Mongo client, CSRF, rate limiter
  models/           read-side helpers (product/category/order)
  routes/           main, shop, cart, checkout, admin blueprints
  services/         cart engine, image pipeline, SquadCo client,
                     order finalization, email notification
  utils/            db helpers, pagination, admin_required decorator
  templates/        Jinja templates (storefront + admin)
static/
  css/js/images/uploads
tests/              pytest suite (mongomock-backed)
seed_admin.py        CLI to create the first admin account
run.py                app entrypoint
```

## Local setup

```bash
python -m venv venv
venv/Scripts/activate        # venv\Scripts\Activate.ps1 on PowerShell
pip install -r requirements-dev.txt
cp .env.example .env         # then fill in real values
python seed_admin.py         # create your first admin login
python run.py
```

For local development **without** a real MongoDB Atlas cluster, set
`MONGO_URI=mongomock` in `.env`. This runs against an in-memory database that
resets every time the process restarts — it's for poking around the UI only,
never for anything you want to keep. Two things don't work in this mode:
product **search** (`$text` isn't implemented by mongomock) and, obviously,
data persistence across restarts. Point `MONGO_URI` at a real Atlas
connection string for anything real.

Run tests:

```bash
pytest
```

## Required environment variables

See `.env.example` for the full list. At minimum for production:

- `SECRET_KEY` — random, at least 32 bytes
- `MONGO_URI`, `MONGO_DB_NAME`
- `SITE_URL` — your real domain, used for canonical URLs and the sitemap
- `SQUADCO_SECRET_KEY` — from your SquadCo dashboard (Settings > API &
  Webhook). Until this is set, checkout still works end-to-end (an order is
  created) but the customer is told to complete payment by phone/WhatsApp
  instead of being sent to SquadCo. Nothing pretends payment succeeded.
- `SQUADCO_ENV` — `sandbox` or `live`; picks which of SquadCo's two documented
  base URLs (`sandbox-api-d.squadco.com` / `api-d.squadco.com`) gets called
- `ADMIN_EMAIL`, `ADMIN_PASSWORD` — used only by `seed_admin.py`, once

## Payments (SquadCo)

`app/services/payments.py` (`SquadcoService`) wraps the whole integration —
nothing outside that one file knows SquadCo's endpoint shapes, field names,
or signing scheme. Built against SquadCo's current documentation
([Initiate Payment](https://docs.squadco.com/Payments/Initiate-payment),
[Verify Transaction](https://docs.squadco.com/Payments/verify-transaction),
[Signature Validation](https://docs.squadco.com/webhook-direct-url/signature-validation)).
Only one credential is required — `SQUADCO_SECRET_KEY`, sent as
`Authorization: Bearer <key>` on every request. There's no separate public
key to configure: the customer is redirected to the hosted `checkout_url`
SquadCo returns, not driven through a JS SDK on this side.

The flow:

1. Checkout recomputes the cart from the database (price, stock, everything)
   — nothing from the browser is trusted.
2. The authoritative order total (subtotal + delivery fee, both server-side)
   is computed and an order is saved as `pending` *before* the customer is
   sent to SquadCo, so nothing is lost if they never come back.
3. `POST /transaction/initiate` is called with our own `transaction_ref`
   (not SquadCo's auto-generated one, so it lines up with the order) and a
   `callback_url` that embeds that same reference as our own `?ref=`
   query param — SquadCo's docs don't pin down what, if anything, *they*
   append to the redirect, so we never depend on that; our own param is
   the only thing `/checkout/callback` reads to know which order it's about.
4. SquadCo redirects the browser back to `/checkout/callback`, which
   re-verifies with `GET /transaction/verify/{transaction_ref}` — the
   redirect itself is never treated as proof of payment.
5. `/webhooks/squadco` is the authoritative path — it verifies the
   `x-squad-encrypted-body` header (HMAC-SHA512 of the raw body with the
   secret key, hex, uppercase — constant-time compared), then independently
   calls SquadCo's verify endpoint before finalizing (the webhook body's own
   claimed status/amount is never trusted directly). Both the callback and
   the webhook call the same `finalize_paid_order()`, which uses an atomic
   `find_one_and_update(..., payment_status: {"$ne": "paid"})` so the same
   webhook event arriving twice (SquadCo's documented behavior — their own
   docs warn "ensure you have a transaction reference checker... to avoid
   giving double value") can never double-decrement stock or double-fire the
   notification email. The computed order total is also compared against
   what SquadCo says was actually paid before anything is finalized.

**On the SquadCo dashboard** (Profile > API & Webhook), set:
- **Webhook URL**: `https://<your-domain>/webhooks/squadco`
- **Redirect URL**: optional — this app always sends its own `callback_url`
  with every initiate call, so this field is only a fallback.

## Image uploads

Admin-uploaded product photos are decoded and re-encoded (never stored as
the raw upload) into three WebP sizes — thumb/medium/large — under
`static/uploads/products/<id>/`. This strips EXIF data and rejects anything
that isn't actually a decodable image, regardless of its extension.

**On Render**, `static/uploads` needs a persistent disk or uploaded images
will disappear on every deploy — `render.yaml` already declares one mounted
at that path. If you deploy elsewhere without persistent disk support,
point uploads at an object store instead; nothing else in the codebase
assumes local disk beyond `app/services/images.py`.

## Admin access

There is deliberately no web route that creates an admin account — run
`python seed_admin.py` once, locally or as a one-off command on your host.
An admin (once logged in) can create further admin accounts from
`/admin/staff`.

## Deployment (Render or similar)

```
gunicorn run:app --workers 3 --threads 2 --timeout 30
```

- `render.yaml` is ready to use as-is (`render blueprint deploy` or connect
  the repo in the Render dashboard).
- `GET /healthz` pings the database and returns 200/503 — wire it up as the
  platform's health check (already set in `render.yaml`).
- Set every env var from `.env.example` in the platform's dashboard; nothing
  is hardcoded, nothing is committed.

## Known scaling caveat

Rate limiting (`Flask-Limiter`) uses in-memory storage by default
(`RATELIMIT_STORAGE_URI`), which is per-process — with Gunicorn's 3 workers
each process counts limits separately, so the effective limit is roughly
3x what's configured. Fine at the current traffic target; if you outgrow it,
point `RATELIMIT_STORAGE_URI` at Redis and nothing else needs to change.

## What's deliberately not here

- No fake reviews, testimonials, customer counts, or delivery promises —
  the homepage only claims what's true (quality/affordability/convenience,
  the actual phone number, the actual socials).
- No payment method that isn't actually wired up. If SquadCo isn't
  configured, checkout says so and gives the store's phone number instead
  of pretending to charge a card.
- No client-trusted price, stock, or order total anywhere — every number
  used at checkout is re-read from MongoDB server-side.
