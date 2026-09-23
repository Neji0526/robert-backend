import uuid
from decimal import Decimal

import pytest

from app.services.provider import ChargeResult, MockPaymentProvider
from app.services.totals import Line, MixedCurrencyError, TotalCalculationService


def test_total_is_the_sum_of_cart_lines():
    total = TotalCalculationService().calculate(
        [
            Line(quantity=1, unit_price=Decimal("45.00"), currency="USD"),
            Line(quantity=2, unit_price=Decimal("12.50"), currency="USD"),
        ]
    )
    assert total.amount == Decimal("70.00")
    assert total.currency == "USD"


def test_mixed_currencies_are_rejected():
    with pytest.raises(MixedCurrencyError):
        TotalCalculationService().calculate(
            [
                Line(quantity=1, unit_price=Decimal("10.00"), currency="USD"),
                Line(quantity=1, unit_price=Decimal("10.00"), currency="EUR"),
            ]
        )


def test_token_containing_fail_is_declined():
    result = MockPaymentProvider().charge(
        provider_token="tok_fail_alice",
        amount=Decimal("70.00"),
        currency="USD",
    )
    assert result == ChargeResult(succeeded=False, failure_code="card_declined")


def test_any_other_token_is_approved():
    result = MockPaymentProvider().charge(
        provider_token="tok_test_alice_visa",
        amount=Decimal("70.00"),
        currency="USD",
    )
    assert result.succeeded is True
    assert result.provider_reference.startswith("ch_")
    assert result.failure_code is None


def test_successful_charge_cannot_omit_its_reference():
    with pytest.raises(ValueError):
        ChargeResult(succeeded=True, failure_code="card_declined")
