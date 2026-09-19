# Moromokeh Essential Store — Production Verification

This is a working checklist for the two things that can't be verified by the
automated test suite alone: a real MongoDB Atlas cluster and a real SquadCo
sandbox account. Nothing here needs code changes to run — it's a runbook,
not a spec.

---

## 1. Render persistent disk — verified by code inspection

**Status: correct, no mismatch found.** `render.yaml`'s disk is mounted at
`/opt/render/project/src/static/uploads`. `UPLOAD_FOLDER` in
[app/config.py](app/config.py) is computed at runtime as
`<repo root>/static/uploads`, and Render's documented repo root for native
Python services is exactly `/opt/render/project/src` — the two paths match
exactly, not approximately. Every write (`app/services/images.py`) and every
read (Flask's static file handler, `static_url_path="/static"`) goes through
that same `UPLOAD_FOLDER`/`/static/uploads/...` path pair, so uploaded images
survive restarts and redeploys and their URLs keep resolving.

**Real limitation (inherent to Render disks, not fixable in code):**
- A disk-attached service is capped at **one instance** — no horizontal
  autoscaling. `render.yaml` already uses `--workers 3` (multiple *processes
  on one instance*, not multiple instances), which is fine and unaffected.
- Deploys with a disk attached are **not zero-downtime** — there's a brief
  restart window on every deploy.
- If Moromokeh later needs to scale beyond one Render instance, the fix is
  to move `app/services/images.py`'s writes to an object store (S3-compatible
  — Render, Cloudflare R2, Backblaze B2 all work) instead of local disk. That
  file is the only place that would need to change.

**Not verified by me (no live Render deployment exists yet):** that Render
actually mounts the disk before first boot on a brand-new service. This is
standard behavior per Render's own docs, but confirm on first deploy by
checking `/healthz` and uploading one test product image, then triggering a
manual redeploy and confirming that image still loads.

---

## 2. MongoDB Atlas — verification checklist

**Status: verified against the real cluster (`Cluster0`, M0 free tier, AWS
eu-west-3) on 2026-09-19.** Every item below passed: connection, all indexes
across `products`/`categories`/`orders`/`admins`, admin password hash/verify,
product create/read/update, pending-order creation, inventory decrement +
idempotent duplicate-finalize (stock went 3→1 after ordering 2, a simulated
duplicate webhook correctly did nothing the second time), and order tracking
lookup. Test data was created and removed in the same run — nothing was left
behind on the cluster. Kept as a checklist below for re-verification after
any future schema change.

Nothing here should be pasted into this repo or chat — set `MONGO_URI` as an
environment variable only (locally in `.env`, on Render in the dashboard).

- [ ] **Cluster + user exist.** Atlas → Database → your cluster → "Connect" →
  copy the `mongodb+srv://...` string. Create a database user with a strong,
  generated password (Atlas → Database Access), scoped to
  `readWrite` on the `moromokeh` database only (not `Atlas admin`).
- [ ] **Network access allows Render.** Atlas → Network Access → allow
  `0.0.0.0/0` (Render's IPs aren't static on standard plans) or set up
  [Render's static outbound IPs](https://render.com/docs/static-outbound-ip-addresses)
  and allowlist those specifically if you want tighter access control.
- [ ] **Connection works.**
  ```bash
  MONGO_URI="<your real srv string>" MONGO_DB_NAME=moromokeh SECRET_KEY=temp FLASK_ENV=development \
    python -c "from app import create_app; app = create_app(); \
    print(app.test_client().get('/healthz').get_json())"
  ```
  Expect `{'status': 'ok'}`.
- [ ] **Indexes were created.** In Atlas → Browse Collections →
  `moromokeh.products` → Indexes tab: expect `slug_1` (unique),
  `category_slug_1`, two compound `is_published_*` indexes, `created_at_-1`,
  and a text index. Same check on `orders` (`payment_reference_1` unique,
  `order_number_1` unique) and `admins` (`email_1` unique). These are created
  automatically on first app boot against this cluster — no manual step.
- [ ] **Admin account.** `python seed_admin.py` against this `MONGO_URI`,
  then log in at `/admin/login` with it.
- [ ] **Products: create/read/update.** In the admin, create one real
  category and one real product with an image. Confirm it appears on `/shop`
  and its own `/product/<slug>` page. Edit its price and confirm the new
  price shows immediately (no caching layer to invalidate).
- [ ] **Cart.** Add that product to cart from a normal (non-admin) browser
  session, adjust quantity, remove it, add it back.
- [ ] **Checkout → order.** Complete checkout with `SQUADCO_SECRET_KEY`
  unset — confirm the order is created with `payment_status: "pending"` and
  is visible at `/admin/orders`.
- [ ] **Inventory.** Note the product's stock, place an order for it through
  a *real* payment finalization (see the SquadCo section below — this is the
  one step that depends on section 3), and confirm stock decremented by
  exactly the ordered quantity, once.
- [ ] **Order history / tracking.** From the storefront, use "Track Order"
  with the order number + phone from the test order above and confirm it
  finds it. Confirm `/admin/orders/<order_number>` shows full details.

---

## 3. SquadCo sandbox — verification test plan

Keep `SQUADCO_ENV=sandbox` for all of this. Get a sandbox secret key from
<https://sandbox.squadco.com/sign-up> (Dashboard → Profile → API & Webhook).
Set `SQUADCO_SECRET_KEY` as an environment variable only — never in a file
that gets committed or pasted into chat.

**One-time dashboard setup:** Squad dashboard → Profile → API & Webhook →
set **Webhook URL** to `https://<your-domain-or-a-tunnel>/webhooks/squadco`.
(For local testing before you have a domain, use a tool like `ngrok` or
Render's own URL once deployed — SquadCo needs to be able to reach it.)

### 3a. Full happy path (real sandbox transaction — not a real charge)

1. Add a product to cart → checkout → fill in delivery details → submit.
   Confirm an order is created with `payment_status: "pending"` and you're
   redirected to SquadCo's hosted checkout page.
2. On SquadCo's sandbox checkout page, pay with the documented test card:
   **4242 4242 4242 4242**, expiry **06/2090**, CVV **257**
   (from <https://docs.squadco.com/Payments/test-cards> — if the sandbox
   modal asks for anything else like an OTP, it will show the value to use
   on screen).
3. Confirm you land back on `/checkout/callback` → `/order/<order_number>`
   showing `paid`.
4. Confirm the webhook fired: check your server logs for
   `POST /webhooks/squadco` returning `{"status": "ok"}`, or check
   `/admin/orders/<order_number>` for a filled-in **SquadCo reference** and
   **Confirmed via: webhook** (or `callback`, if the webhook hasn't arrived
   yet at the moment you check — both are wired to the same idempotent
   finalize, so either landing first is fine).
5. Confirm inventory decremented by exactly the ordered quantity (check the
   product's stock in `/admin/products` before and after).
6. Confirm the cart is empty after checkout.
7. If `ORDER_NOTIFY_EMAIL`/`MAIL_*` are configured, confirm the notification
   email arrived.

### 3b. Faster alternative for repeatable testing: the Transfer simulator

SquadCo's sandbox has an API to simulate a completed transfer payment
without a browser, useful for testing the webhook/idempotency logic
repeatedly:

1. Start checkout, and on the hosted page choose **Transfer** — this returns
   a dynamic virtual account number.
2. Complete it programmatically:
   ```bash
   curl -X POST https://sandbox-api-d.squadco.com/virtual-account/simulate/payment \
     -H "Authorization: Bearer $SQUADCO_SECRET_KEY" \
     -H "Content-Type: application/json" \
     -d '{"virtual_account_number": "<from step 1>", "amount": "<order total in kobo>"}'
   ```
3. Same checks as 3a steps 3–7.

### 3c. Failure / edge cases (all should be tried at least once)

- [ ] **Failed payment** — sandbox usually has a documented failing test
  card, or decline the payment on the modal if it offers that option.
  Confirm the order stays `pending` and no stock moves.
- [ ] **Abandoned payment** — start checkout, get to SquadCo's page, then
  close the tab without paying. Confirm the order stays `pending`
  indefinitely (no stock movement, no false "paid" state) and that
  **Retry Payment** on `/order/<order_number>` successfully starts a new
  SquadCo session for the same order.
- [ ] **Duplicate webhook** — resend the same webhook payload twice
  (SquadCo's dashboard may offer a "resend" button on delivered webhooks; if
  not, re-run the curl from 3b step 2 for an already-paid transaction). The
  order's `payment_status` must stay `paid` and stock must not decrement a
  second time. This exact behavior already has an automated regression test
  (`tests/test_payments.py::test_webhook_success_finalizes_and_decrements_inventory_exactly_once`)
  — this manual step confirms it holds against the real API too, not just
  the mocked one.
- [ ] **Invalid webhook signature** —
  ```bash
  curl -X POST https://<your-domain>/webhooks/squadco \
    -H "Content-Type: application/json" \
    -H "x-squad-encrypted-body: not-a-real-signature" \
    -d '{"Event":"charge_successful","Body":{"transaction_ref":"whatever"}}'
  ```
  Expect `401`. Confirm nothing in `orders` changed.
- [ ] **Amount mismatch** — hardest to trigger for real (would need SquadCo
  to report a different amount than the order total); this is covered by an
  automated test
  (`tests/test_payments.py::test_webhook_amount_mismatch_does_not_finalize`)
  since it can't happen through the real sandbox checkout UI (you pay
  exactly what's initiated). Treat the automated test as the verification
  here.
- [ ] **Invalid/unknown transaction reference** —
  ```bash
  curl https://sandbox-api-d.squadco.com/transaction/verify/does-not-exist \
    -H "Authorization: Bearer $SQUADCO_SECRET_KEY"
  ```
  Expect a `400` with `"Invalid transaction reference"` from SquadCo, and
  (already covered by an automated test) that this maps to `verify_transaction()`
  returning `None` rather than raising.

**When all of section 3 passes:** switch `SQUADCO_ENV=live`, replace the
sandbox key with the live secret key from the Squad dashboard, and update
the Webhook URL there to point at the real production domain if it doesn't
already.

---

## 4. Payment reconciliation — what's on the order document

Every order carries enough to answer "what happened to this payment" from
the admin UI alone, no log access needed (`/admin/orders/<order_number>`):

| Field | Purpose |
|---|---|
| `order_number` | Customer-facing ID (`MRK-YYYYMMDD-XXXX`) |
| `payment_reference` | Our reference, sent to SquadCo as `transaction_ref` |
| `gateway_reference` | SquadCo's own `gateway_transaction_ref` — cross-reference against their dashboard/statement |
| `payment_channel` | card / bank / ussd / transfer, as reported by SquadCo |
| `verified_amount_kobo` | What SquadCo confirmed was actually paid, captured at finalize time |
| `finalized_via` | `"webhook"` or `"callback"` — which trigger actually finalized it |
| `customer` | name, phone, email, address, state, city, note |
| `subtotal` / `delivery_fee` / `total` | authoritative amount, computed server-side |
| `payment_status` | `pending` / `paid` / `failed` |
| `fulfillment_status` | `pending` / `processing` / `shipped` / `completed` / `cancelled` |
| `created_at` / `paid_at` / `updated_at` | full timeline |
| `stock_issue` | flagged `true` if inventory couldn't be fully decremented (rare race) — surfaced as a warning banner on the order detail page |

---

## Required actions (yours)

See the chat response for the numbered list — kept there so it stays in one
place and doesn't drift out of sync with this file.
