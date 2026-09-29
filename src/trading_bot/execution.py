from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(slots=True, frozen=True)
class OrderIntent:
    symbol: str
    side: Side
    quantity: Decimal


class ExecutionBlocked(RuntimeError):
    pass


class DisabledExecutionEngine:
    """Safety placeholder until risk + execution phases are explicitly implemented."""

    async def submit(self, intent: OrderIntent) -> None:
        raise ExecutionBlocked(
            f"Order execution disabled by design: {intent.side} {intent.quantity} {intent.symbol}"
        )
