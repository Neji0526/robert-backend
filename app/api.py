import uuid

from flask import Blueprint, abort, current_app, jsonify, request
from sqlalchemy import select

from app.demo_data import reset_demo_data
from app.errors import AppError
from app.extensions import db
from app.models import Cart, Payment, PaymentMethod, User
from app.serializers import cart_to_dict, method_to_dict, payment_to_dict
from app.services.checkout import start_payment

api_bp = Blueprint("api", __name__)


@api_bp.after_request
def _do_not_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@api_bp.get("/health")
def health():
    return jsonify(status="ok")


@api_bp.get("/carts/<uuid:cart_id>")
def get_cart(cart_id: uuid.UUID):
    cart = db.session.get(Cart, cart_id)
    if cart is None:
        raise AppError("cart_not_found", "Cart was not found.", 404)
    payments = db.session.scalars(
        select(Payment).where(Payment.cart_id == cart.id).order_by(Payment.created_at.desc())
    ).all()
    return jsonify(cart_to_dict(cart, payments))


@api_bp.get("/users/<uuid:user_id>/payment-methods")
def list_payment_methods(user_id: uuid.UUID):
    user = db.session.get(User, user_id)
    if user is None:
        raise AppError("user_not_found", "User was not found.", 404)
    methods = db.session.scalars(
        select(PaymentMethod)
        .where(PaymentMethod.user_id == user.id)
        .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at)
    ).all()
    return jsonify(payment_methods=[method_to_dict(method) for method in methods])


@api_bp.post("/carts/<uuid:cart_id>/payments")
def start_cart_payment(cart_id: uuid.UUID):
    body = _json_object()
    started = start_payment(
        cart_id=cart_id,
        payment_method_id=_optional_uuid(body.get("payment_method_id")),
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        provider=current_app.config["PAYMENT_PROVIDER"],
    )
    status = 201 if started.created else 200
    return jsonify(payment_to_dict(started.payment, replayed=not started.created)), status


@api_bp.post("/demo/reset")
def reset_demo():
    if not current_app.config.get("DEMO_RESET"):
        abort(404)
    reset_demo_data()
    return jsonify(status="reset")


def _json_object() -> dict:
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise AppError("invalid_json", "Request body must be a JSON object.", 400)
    return body


def _optional_uuid(value: object) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise AppError(
            "invalid_payment_method_id",
            "payment_method_id must be a UUID.",
            400,
        ) from None
