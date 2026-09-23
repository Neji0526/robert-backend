from decimal import Decimal

from app.models import Cart, CartItem, Payment, PaymentMethod, User
from app.services.totals import Line, MixedCurrencyError, TotalCalculationService


def money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), ".2f")


def payment_to_dict(payment: Payment, *, replayed: bool | None = None) -> dict:
    payload = {
        "id": str(payment.id),
        "cart_id": str(payment.cart_id),
        "user_id": str(payment.user_id),
        "payment_method_id": str(payment.payment_method_id),
        "amount": money(payment.amount),
        "currency": payment.currency.strip(),
        "status": payment.status,
        "provider_reference": payment.provider_reference,
        "failure_code": payment.failure_code,
        "created_at": payment.created_at.isoformat(),
    }
    if replayed is not None:
        payload["replayed"] = replayed
    return payload


def method_to_dict(method: PaymentMethod) -> dict:
    last_four = method.last_four.strip() if method.last_four else None
    return {
        "id": str(method.id),
        "last_four": last_four or None,
        "is_default": method.is_default,
    }


def user_to_dict(user: User) -> dict:
    return {"id": str(user.id), "email": user.email, "name": user.name}


def item_to_dict(item: CartItem) -> dict:
    line_total = (item.unit_price * item.quantity).quantize(Decimal("0.01"))
    return {
        "id": str(item.id),
        "product_id": str(item.product_id),
        "product_name": item.product.name,
        "quantity": item.quantity,
        "unit_price": money(item.unit_price),
        "line_total": money(line_total),
        "stock_quantity": item.product.stock_quantity,
    }


def cart_to_dict(cart: Cart, payments: list[Payment]) -> dict:
    items = list(cart.items)
    total, currency = _quote(items)
    return {
        "id": str(cart.id),
        "status": cart.status,
        "user": user_to_dict(cart.user),
        "currency": currency,
        "total": total,
        "items": [item_to_dict(item) for item in items],
        "payments": [payment_to_dict(payment) for payment in payments],
    }


def _quote(items: list[CartItem]) -> tuple[str | None, str | None]:
    if not items:
        return "0.00", None
    lines = [
        Line(quantity=item.quantity, unit_price=item.unit_price, currency=item.product.currency.strip())
        for item in items
    ]
    try:
        quoted = TotalCalculationService().calculate(lines)
    except MixedCurrencyError:
        return None, None
    return money(quoted.amount), quoted.currency
