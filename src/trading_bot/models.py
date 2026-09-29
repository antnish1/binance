from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class BestBidAsk:
    symbol: str
    bid_price: Decimal
    bid_qty: Decimal
    ask_price: Decimal
    ask_qty: Decimal
    event_time_ms: int
    received_time_ms: int

    @property
    def spread(self) -> Decimal:
        return self.ask_price - self.bid_price

    @property
    def midpoint(self) -> Decimal:
        return (self.ask_price + self.bid_price) / Decimal(2)
