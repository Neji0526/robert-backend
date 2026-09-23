import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class ChargeResult:
    succeeded: bool
    provider_reference: str | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.succeeded:
            if not self.provider_reference or self.failure_code is not None:
                raise ValueError("A successful charge needs a provider reference and no failure code.")
            return
        if self.provider_reference is not None or not self.failure_code:
            raise ValueError("A declined charge needs a failure code and no provider reference.")


class PaymentProvider(Protocol):
    def charge(self, *, provider_token: str, amount: Decimal, currency: str) -> ChargeResult:
        """Charge a saved card token for an amount."""


class MockPaymentProvider:
    """In-process stand-in for the payment provider.

    A token is declined when it contains "fail" (any letter case).
    Every other token is approved.
    """

    def charge(self, *, provider_token: str, amount: Decimal, currency: str) -> ChargeResult:
        if amount <= 0 or len(currency.strip()) != 3:
            return ChargeResult(succeeded=False, failure_code="invalid_amount")
        if "fail" in provider_token.lower():
            return ChargeResult(succeeded=False, failure_code="card_declined")
        return ChargeResult(succeeded=True, provider_reference=f"ch_{uuid.uuid4().hex}")
