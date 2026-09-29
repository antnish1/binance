import asyncio
import time

from .models import BestBidAsk


class MarketState:
    def __init__(self) -> None:
        self._best_bid_ask: BestBidAsk | None = None
        self._lock = asyncio.Lock()

    async def update_best_bid_ask(self, value: BestBidAsk) -> None:
        async with self._lock:
            self._best_bid_ask = value

    async def snapshot(self) -> BestBidAsk | None:
        async with self._lock:
            return self._best_bid_ask

    async def age_ms(self) -> int | None:
        snap = await self.snapshot()
        if snap is None:
            return None
        return max(0, int(time.time() * 1000) - snap.received_time_ms)
