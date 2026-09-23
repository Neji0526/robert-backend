# Payment endpoint

A small shop checkout. A customer pays for an active cart with a saved card token. The amount comes from the cart, not from the client.

## What it does

`POST /api/carts/<cart_id>/payments` charges the cart and stores the attempt.

- The cart must be `active` and must contain items.
- The amount is the sum of `quantity * unit_price` on those lines. The page cannot send its own total.
- The card is the payment method in the body, or the user's default card when the body omits it.
- The card token is sent to a mock provider. A token is declined when it contains `fail`. Any other token is approved.
- A successful charge marks the cart `checked_out` and reduces product stock. A decline leaves the cart active so the customer can try another card.
- A cart can have many failed payments and at most one successful payment.
- Send an `Idempotency-Key` header. Repeating the same key returns the original payment and does not charge again.

Cart lines stay on the cart after payment. They are the record of what was bought.

There is no account login. Knowing the cart id is enough to pay it. A production shop would authenticate the caller and check that they own the cart.

The provider call runs inside the database transaction. That is safe because the provider is an in-process mock: the cart row stays locked until the result is stored. A real network provider would save a pending payment first and confirm it after the provider responds.

## Schema

`db/001_base_schema.sql` is the shop schema from the task. It is unchanged.

`db/002_payments.sql` is the payment migration. It adds the `payments` table:

- one row per charge attempt
- `succeeded` or `failed`
- a unique idempotency key
- at most one `succeeded` row per cart
- a check that a success has a provider reference, and a failure has a failure code

`db/003_demo_payment_method.sql` adds a second card for Alice (`tok_fail_alice`, last four `0002`) so the checkout page can show a decline. It is demo data, not part of the payment schema.

## Run it

You need Python 3.11+, Docker, and pip.

```powershell
docker compose up -d --wait
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
flask --app app run --debug
```

Open http://127.0.0.1:5000

The defaults match `docker-compose.yml` (`shop` / `shop` on port 5434). The app database is on 5434 so it does not collide with a Postgres already installed on 5432. Copy `.env.example` to `.env` only if you need different settings.

On macOS or Linux, `python3 -m venv .venv` and `source .venv/bin/activate` replace the Windows venv commands. `make up` and `make run` do the same thing.

Alice's sample cart is one Blue Kettle ($45.00) and two Ceramic Mugs ($12.50), so the charge is **$70.00**. The default card ends in 4242 and is approved. The other card ends in 0002 and is declined.

**Reset sample cart** puts that data back after a payment. That button calls `POST /api/demo/reset`, which exists only when the app runs in development.

### Pay with curl

```powershell
curl.exe -X POST "http://127.0.0.1:5000/api/carts/c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1/payments" -H "Content-Type: application/json" -H "Idempotency-Key: attempt-1" -d '{"payment_method_id":"11111111-2222-3333-4444-555555555555"}'
```

Omit `payment_method_id` to charge the default card. A declined attempt looks the same, with `"status": "failed"` and `"failure_code": "card_declined"`. Use a new idempotency key for the next attempt.

### Other routes

These exist so the checkout page can load. They are not the payment endpoint.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Process is up |
| GET | `/api/carts/<cart_id>` | Cart, lines, total, and payment attempts |
| GET | `/api/users/<user_id>/payment-methods` | Saved cards. The provider token is not returned |
| POST | `/api/demo/reset` | Restore sample data. Development only |

### Response codes

| HTTP | `error.code` | When |
| --- | --- | --- |
| 201 | | The attempt was stored. Read `status` in the body. A decline is still 201 |
| 200 | | The idempotency key was already used for this cart |
| 400 | `idempotency_key_required` | Missing or blank `Idempotency-Key` |
| 400 | `idempotency_key_invalid` | Key longer than 255 characters |
| 400 | `invalid_json` | Body is not a JSON object |
| 400 | `invalid_payment_method_id` | `payment_method_id` is not a UUID |
| 404 | `cart_not_found` | No such cart |
| 404 | `payment_method_not_found` | No such card |
| 404 | `user_not_found` | No such user |
| 409 | `cart_not_active` | Cart is checked out or abandoned |
| 409 | `insufficient_stock` | A line asks for more units than are in stock |
| 409 | `idempotency_key_conflict` | That key was used for a different cart |
| 422 | `cart_empty` | Cart has no lines |
| 422 | `mixed_currency` | Lines do not share one currency |
| 422 | `amount_not_positive` | The total is zero or less |
| 422 | `payment_method_not_owned` | The card belongs to someone else |
| 422 | `no_payment_method` | The user has no default card |
| 422 | `ambiguous_default_payment_method` | The user has more than one default card |

Errors look like:

```json
{"error": {"code": "cart_not_active", "message": "Only an active cart can be paid. This cart is checked out."}}
```

## Tests

The tests use the database on port **5433** (`shop_test`). They drop and recreate its `public` schema. Do not point `TEST_DATABASE_URL` at a database you need to keep.

```powershell
docker compose up -d --wait
pytest
```

`tests/test_provider_and_totals.py` does not need Postgres. `tests/test_payments.py` does.

## Assumptions

- The charge finishes in this request. There is no webhook and no `pending` status.
- The total service sums line prices only. It does not add tax or shipping.
- Stock is checked and reduced only when the charge succeeds. The products are locked in id order so two carts cannot deadlock on the same products.
- If `payment_method_id` is omitted, the user must have exactly one default card.
- Repeating an idempotency key returns the stored attempt, including a decline. A new try needs a new key.
- Payment rows are not deleted when a cart changes. The foreign keys do not cascade.
- `python -m app.schema` applies the three SQL files to `DATABASE_URL`. Use it on an empty database you manage yourself. Docker already applies them the first time the `db` volume is created.
