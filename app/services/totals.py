from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


class MixedCurrencyError(Exception):
    """The cart lines do not share one currency."""


@dataclass(frozen=True)
class Line:
    quantity: int
    unit_price: Decimal
    currency: str


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str


class TotalCalculationService:
    """The shop's existing total service.

    It sums quantity times the unit price stored on each cart line.
    Tax and shipping are not part of this service.
    """

    def calculate(self, lines: list[Line]) -> Money:
        currencies = {line.currency.strip() for line in lines}
        if len(currencies) != 1:
            raise MixedCurrencyError
        amount = sum(
            (line.unit_price * line.quantity for line in lines),
            Decimal("0"),
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return Money(amount=amount, currency=currencies.pop())
