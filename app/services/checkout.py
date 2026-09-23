"""Start a payment for one cart.

The provider call runs inside the database transaction. That is safe for this
in-process mock: the cart row stays locked until the charge is stored, so two
requests cannot both succeed. A provider on the network would record a pending
payment first and confirm it after the provider responds.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.errors import AppError
from app.extensions import db
from app.models import Cart, CartItem, Payment, PaymentMethod, Product
from app.services.provider import PaymentProvider
from app.services.totals import Line, MixedCurrencyError, Money, TotalCalculationService

_MAX_IDEMPOTENCY_KEY_LENGTH = 255
_STATUS_WORDS = {
    "checked_out": "checked out",
    "abandoned": "abandoned",
}


class StartedPayment:
    def __init__(self, payment: Payment, created: bool) -> None:
        self.payment = payment
        self.created = created


def start_payment(
    *,
    cart_id: uuid.UUID,
    payment_method_id: uuid.UUID | None,
    idempotency_key: str,
    provider: PaymentProvider,
) -> StartedPayment:
    key = _validated_key(idempotency_key)

    replay = _replay(key, cart_id)
    if replay is not None:
        return replay

    cart = db.session.scalar(select(Cart).where(Cart.id == cart_id).with_for_update())
    if cart is None:
        raise AppError("cart_not_found", "Cart was not found.", 404)

    replay = _replay(key, cart_id)
    if replay is not None:
        return replay

    _ensure_cart_can_be_paid(cart)
    items = list(cart.items)
    if not items:
        raise AppError("cart_empty", "Cart has no items.", 422)

    products = _lock_products(items)
    _ensure_stock(items, products)
    total = _total(items)
    method = _payment_method(cart.user_id, payment_method_id)
    result = provider.charge(
        provider_token=method.provider_token,
        amount=total.amount,
        currency=total.currency,
    )

    payment = Payment(
        cart_id=cart.id,
        user_id=cart.user_id,
        payment_method_id=method.id,
        amount=total.amount,
        currency=total.currency,
        status="succeeded" if result.succeeded else "failed",
        provider_reference=result.provider_reference,
        failure_code=result.failure_code,
        idempotency_key=key,
    )
    if result.succeeded:
        _mark_cart_paid(cart, items, products)

    db.session.add(payment)
    try:
        db.session.commit()
    except IntegrityError as exc:
        return _recover_from_conflict(exc, key, cart_id)

    db.session.refresh(payment)
    return StartedPayment(payment, created=True)


def _validated_key(value: str) -> str:
    key = value.strip()
    if not key:
        raise AppError(
            "idempotency_key_required",
            "Send an Idempotency-Key header so a retried request is not charged twice.",
            400,
        )
    if len(key) > _MAX_IDEMPOTENCY_KEY_LENGTH:
        raise AppError(
            "idempotency_key_invalid",
            "Idempotency-Key must be 255 characters or fewer.",
            400,
        )
    return key


def _replay(key: str, cart_id: uuid.UUID) -> StartedPayment | None:
    existing = db.session.scalar(select(Payment).where(Payment.idempotency_key == key))
    if existing is None:
        return None
    if existing.cart_id != cart_id:
        raise AppError(
            "idempotency_key_conflict",
            "This idempotency key was already used for a different cart.",
            409,
        )
    payment_id = existing.id
    db.session.rollback()
    payment = db.session.get(Payment, payment_id)
    if payment is None:
        raise AppError("internal_error", "The original payment could not be reloaded.", 500)
    return StartedPayment(payment, created=False)


def _ensure_cart_can_be_paid(cart: Cart) -> None:
    if cart.status == "active":
        return
    word = _STATUS_WORDS.get(cart.status, cart.status)
    raise AppError(
        "cart_not_active",
        f"Only an active cart can be paid. This cart is {word}.",
        409,
    )


def _lock_products(items: list[CartItem]) -> dict[uuid.UUID, Product]:
    product_ids = sorted({item.product_id for item in items})
    products = db.session.scalars(
        select(Product).where(Product.id.in_(product_ids)).order_by(Product.id).with_for_update()
    ).all()
    return {product.id: product for product in products}


def _ensure_stock(items: list[CartItem], products: dict[uuid.UUID, Product]) -> None:
    for item in items:
        product = products.get(item.product_id)
        if product is None:
            raise AppError("product_not_found", "A product in the cart no longer exists.", 409)
        if product.stock_quantity < item.quantity:
            raise AppError(
                "insufficient_stock",
                f"Not enough stock for {product.name}.",
                409,
            )


def _total(items: list[CartItem]) -> Money:
    lines = [
        Line(
            quantity=item.quantity,
            unit_price=item.unit_price,
            currency=item.product.currency.strip(),
        )
        for item in items
    ]
    try:
        total = TotalCalculationService().calculate(lines)
    except MixedCurrencyError as exc:
        raise AppError(
            "mixed_currency",
            "Every item in the cart must use the same currency.",
            422,
        ) from exc
    if total.amount <= 0:
        raise AppError(
            "amount_not_positive",
            "The cart total must be greater than zero.",
            422,
        )
    return total


def _payment_method(user_id: uuid.UUID, payment_method_id: uuid.UUID | None) -> PaymentMethod:
    if payment_method_id is not None:
        method = db.session.get(PaymentMethod, payment_method_id)
        if method is None:
            raise AppError("payment_method_not_found", "Payment method was not found.", 404)
        if method.user_id != user_id:
            raise AppError(
                "payment_method_not_owned",
                "Payment method does not belong to the cart owner.",
                422,
            )
        return method

    defaults = db.session.scalars(
        select(PaymentMethod).where(
            PaymentMethod.user_id == user_id,
            PaymentMethod.is_default.is_(True),
        )
    ).all()
    if not defaults:
        raise AppError(
            "no_payment_method",
            "This user has no default payment method.",
            422,
        )
    if len(defaults) > 1:
        raise AppError(
            "ambiguous_default_payment_method",
            "This user has more than one default payment method.",
            422,
        )
    return defaults[0]


def _mark_cart_paid(cart: Cart, items: list[CartItem], products: dict[uuid.UUID, Product]) -> None:
    now = datetime.now(timezone.utc)
    cart.status = "checked_out"
    cart.updated_at = now
    for item in items:
        product = products[item.product_id]
        product.stock_quantity -= item.quantity
        product.updated_at = now


def _recover_from_conflict(exc: IntegrityError, key: str, cart_id: uuid.UUID) -> StartedPayment:
    db.session.rollback()
    detail = str(getattr(exc, "orig", exc))
    if "uq_payments_idempotency_key" in detail:
        replay = _replay(key, cart_id)
        if replay is None:
            raise exc
        return replay
    if "uq_payments_one_success_per_cart" in detail:
        raise AppError(
            "cart_not_active",
            "Only an active cart can be paid. This cart is checked out.",
            409,
        ) from exc
    raise exc
