import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.services.provider import MockPaymentProvider

ALICE = "11111111-1111-1111-1111-111111111111"
BOB = "22222222-2222-2222-2222-222222222222"
CART = "c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1"
VISA = "11111111-2222-3333-4444-555555555555"
FAIL_CARD = "11111111-2222-3333-4444-666666666666"
KETTLE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
MUG = "cccccccc-cccc-cccc-cccc-cccccccccccc"
BLANKET = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class CountingProvider(MockPaymentProvider):
    def __init__(self) -> None:
        self.calls = 0

    def charge(self, **kwargs):
        self.calls += 1
        return super().charge(**kwargs)


@pytest.fixture(scope="session")
def app():
    from sqlalchemy.exc import OperationalError

    from app import create_app
    from app.schema import rebuild_schema

    application = create_app("testing")
    with application.app_context():
        try:
            rebuild_schema(db.engine)
        except OperationalError as exc:
            pytest.exit(
                "Cannot connect to the test database on localhost:5433.\n"
                "Start it with: docker compose up -d --wait\n"
                f"{exc}",
                returncode=1,
            )
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    from app.demo_data import reset_demo_data

    app.config["PAYMENT_PROVIDER"] = MockPaymentProvider()
    app.config["DEMO_RESET"] = False
    with app.app_context():
        reset_demo_data()
        db.session.remove()
    return app.test_client()


@pytest.fixture
def database(app, client):
    with app.app_context():
        yield


def write(sql, **params):
    db.session.execute(text(sql), params)
    db.session.commit()


def scalar(sql, **params):
    return db.session.execute(text(sql), params).scalar_one()


def pay(client, cart_id=CART, method_id=None, key=None, extra=None):
    body = dict(extra or {})
    if method_id is not None:
        body["payment_method_id"] = method_id
    headers = {"Idempotency-Key": key or str(uuid.uuid4())} if key is not False else {}
    return client.post(f"/api/carts/{cart_id}/payments", json=body, headers=headers)


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_cart_page_shows_the_sample_total(client):
    response = client.get(f"/api/carts/{CART}")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "active"
    assert body["user"]["name"] == "Alice"
    assert body["total"] == "70.00"
    assert body["currency"] == "USD"
    by_name = {item["product_name"]: item for item in body["items"]}
    assert by_name["Blue Kettle"]["line_total"] == "45.00"
    assert by_name["Ceramic Mug"]["quantity"] == 2
    assert by_name["Ceramic Mug"]["line_total"] == "25.00"
    assert body["payments"] == []


def test_payment_methods_do_not_include_the_provider_token(client):
    response = client.get(f"/api/users/{ALICE}/payment-methods")
    assert response.status_code == 200
    methods = response.get_json()["payment_methods"]
    assert [method["last_four"] for method in methods] == ["4242", "0002"]
    assert "provider_token" not in response.get_data(as_text=True)


def test_pay_checks_out_the_cart_and_reduces_stock(client, database):
    response = pay(client)
    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "succeeded"
    assert body["amount"] == "70.00"
    assert body["currency"] == "USD"
    assert body["failure_code"] is None
    assert body["provider_reference"].startswith("ch_")
    assert body["replayed"] is False
    assert body["payment_method_id"] == VISA

    assert scalar("SELECT status FROM carts WHERE id = :id", id=CART) == "checked_out"
    assert scalar("SELECT stock_quantity FROM products WHERE id = :id", id=KETTLE) == 9
    assert scalar("SELECT stock_quantity FROM products WHERE id = :id", id=MUG) == 98
    assert scalar("SELECT stock_quantity FROM products WHERE id = :id", id=BLANKET) == 5

    cart = client.get(f"/api/carts/{CART}").get_json()
    assert cart["status"] == "checked_out"
    assert len(cart["payments"]) == 1


def test_client_cannot_choose_the_amount(client):
    response = pay(client, extra={"amount": "1.00"})
    assert response.status_code == 201
    assert response.get_json()["amount"] == "70.00"


def test_declined_card_keeps_the_cart_open(client, database):
    response = pay(client, method_id=FAIL_CARD)
    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "failed"
    assert body["failure_code"] == "card_declined"
    assert body["provider_reference"] is None
    assert scalar("SELECT status FROM carts WHERE id = :id", id=CART) == "active"
    assert scalar("SELECT stock_quantity FROM products WHERE id = :id", id=KETTLE) == 10
    assert scalar("SELECT COUNT(*) FROM payments") == 1


def test_a_declined_cart_can_be_paid_with_a_new_key(client, database):
    declined = pay(client, method_id=FAIL_CARD)
    assert declined.status_code == 201
    paid = pay(client, method_id=VISA)
    assert paid.status_code == 201
    assert paid.get_json()["status"] == "succeeded"
    assert scalar("SELECT status FROM carts WHERE id = :id", id=CART) == "checked_out"
    assert scalar("SELECT COUNT(*) FROM payments") == 2
    assert scalar("SELECT stock_quantity FROM products WHERE id = :id", id=KETTLE) == 9


def test_replaying_the_idempotency_key_does_not_charge_again(client, app, database):
    provider = CountingProvider()
    app.config["PAYMENT_PROVIDER"] = provider
    key = "attempt-1"

    first = pay(client, key=key)
    second = pay(client, key=key, extra={"amount": "1.00"})

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.get_json()["id"] == second.get_json()["id"]
    assert second.get_json()["replayed"] is True
    assert provider.calls == 1
    assert scalar("SELECT COUNT(*) FROM payments") == 1
    assert scalar("SELECT stock_quantity FROM products WHERE id = :id", id=KETTLE) == 9


def test_the_same_key_cannot_be_reused_for_another_cart(client, database):
    key = "shared-key"
    assert pay(client, key=key).status_code == 201
    other_cart = str(uuid.uuid4())
    write(
        "INSERT INTO carts (id, user_id, status) VALUES (:id, :user_id, 'active')",
        id=other_cart,
        user_id=ALICE,
    )
    write(
        """
        INSERT INTO cart_items (cart_id, product_id, quantity, unit_price)
        VALUES (:cart_id, :product_id, 1, 45.00)
        """,
        cart_id=other_cart,
        product_id=KETTLE,
    )

    response = pay(client, cart_id=other_cart, key=key)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "idempotency_key_conflict"
    assert scalar("SELECT status FROM carts WHERE id = :id", id=other_cart) == "active"
    assert scalar("SELECT stock_quantity FROM products WHERE id = :id", id=KETTLE) == 9


def test_a_checked_out_cart_cannot_be_paid_again(client):
    assert pay(client).status_code == 201
    response = pay(client)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "cart_not_active"


def test_unknown_cart_is_not_found(client):
    response = pay(client, cart_id=str(uuid.uuid4()))
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "cart_not_found"


def test_empty_cart_is_rejected(client, database):
    write("DELETE FROM cart_items WHERE cart_id = :id", id=CART)
    response = pay(client)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "cart_empty"
    assert scalar("SELECT COUNT(*) FROM payments") == 0


def test_abandoned_cart_is_rejected(client, database):
    write("UPDATE carts SET status = 'abandoned' WHERE id = :id", id=CART)
    response = pay(client)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "cart_not_active"
    assert scalar("SELECT COUNT(*) FROM payments") == 0


def test_insufficient_stock_does_not_charge(client, database):
    write("UPDATE products SET stock_quantity = 0 WHERE id = :id", id=KETTLE)
    response = pay(client)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "insufficient_stock"
    assert scalar("SELECT status FROM carts WHERE id = :id", id=CART) == "active"
    assert scalar("SELECT COUNT(*) FROM payments") == 0
    assert scalar("SELECT stock_quantity FROM products WHERE id = :id", id=KETTLE) == 0


def test_another_users_card_is_rejected(client, database):
    bob_card = str(uuid.uuid4())
    write(
        """
        INSERT INTO user_payment_methods (id, user_id, provider_token, last_four, is_default)
        VALUES (:id, :user_id, 'tok_bob', '1111', TRUE)
        """,
        id=bob_card,
        user_id=BOB,
    )
    response = pay(client, method_id=bob_card)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "payment_method_not_owned"
    assert scalar("SELECT status FROM carts WHERE id = :id", id=CART) == "active"


def test_missing_default_card_is_rejected(client, database):
    write("DELETE FROM user_payment_methods WHERE user_id = :id", id=ALICE)
    response = pay(client)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "no_payment_method"


def test_two_default_cards_are_rejected(client, database):
    write(
        """
        INSERT INTO user_payment_methods (id, user_id, provider_token, last_four, is_default)
        VALUES (:id, :user_id, 'tok_other', '9999', TRUE)
        """,
        id=str(uuid.uuid4()),
        user_id=ALICE,
    )
    response = pay(client)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "ambiguous_default_payment_method"


def test_unknown_payment_method_is_not_found(client):
    response = pay(client, method_id=str(uuid.uuid4()))
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "payment_method_not_found"


def test_mixed_currency_cart_is_rejected(client, database):
    write("UPDATE products SET currency = 'EUR' WHERE id = :id", id=MUG)
    response = pay(client)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "mixed_currency"
    assert scalar("SELECT COUNT(*) FROM payments") == 0
    assert scalar("SELECT stock_quantity FROM products WHERE id = :id", id=MUG) == 100


def test_idempotency_key_is_required(client):
    response = pay(client, key=False)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "idempotency_key_required"


def test_blank_idempotency_key_is_required(client):
    response = pay(client, key="   ")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "idempotency_key_required"


def test_idempotency_key_has_a_length_limit(client):
    response = pay(client, key="k" * 256)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "idempotency_key_invalid"


def test_payment_method_id_must_be_a_uuid(client):
    response = pay(client, extra={"payment_method_id": "nope"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_payment_method_id"


def test_body_must_be_a_json_object(client):
    response = client.post(
        f"/api/carts/{CART}/payments",
        data="[]",
        content_type="application/json",
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_json"


def test_database_rejects_a_second_successful_payment(client, database):
    assert pay(client).status_code == 201
    with pytest.raises(IntegrityError):
        write(
            """
            INSERT INTO payments (
                cart_id, user_id, payment_method_id, amount, currency,
                status, provider_reference, idempotency_key
            ) VALUES (
                :cart_id, :user_id, :method_id, 70.00, 'USD',
                'succeeded', 'ch_second', 'another-key'
            )
            """,
            cart_id=CART,
            user_id=ALICE,
            method_id=VISA,
        )
    db.session.rollback()


def test_demo_reset_is_hidden_unless_enabled(client):
    response = client.post("/api/demo/reset")
    assert response.status_code == 404


def test_demo_reset_restores_the_sample_cart(client, app, database):
    assert pay(client).status_code == 201
    app.config["DEMO_RESET"] = True
    try:
        response = client.post("/api/demo/reset")
        assert response.status_code == 200
        assert scalar("SELECT status FROM carts WHERE id = :id", id=CART) == "active"
        assert scalar("SELECT stock_quantity FROM products WHERE id = :id", id=KETTLE) == 10
        assert scalar("SELECT COUNT(*) FROM payments") == 0
    finally:
        app.config["DEMO_RESET"] = False


def test_checkout_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Checkout" in response.data
