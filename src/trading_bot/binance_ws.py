import asyncio
import json
import logging
import random
import time
from decimal import Decimal

import websockets

from .market_state import MarketState
from .models import BestBidAsk

logger = logging.getLogger(__name__)


class BinanceBookTickerStream:
    def __init__(self, ws_base_url: str, symbol: str, state: MarketState):
        self.ws_base_url = ws_base_url.rstrip("/")
        self.symbol = symbol.upper()
        self.state = state
        self._stop = asyncio.Event()
        self.connected = False
        self.reconnect_count = 0
        self.last_error: str | None = None

    @property
    def url(self) -> str:
        return f"{self.ws_base_url}/{self.symbol.lower()}@bookTicker"

    async def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=3,
                    max_queue=2048,
                ) as ws:
                    self.connected = True
                    self.last_error = None
                    attempt = 0
                    logger.info("market_stream_connected symbol=%s", self.symbol)
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        payload = json.loads(raw)
                        received = int(time.time() * 1000)
                        value = BestBidAsk(
                            symbol=payload.get("s", self.symbol),
                            bid_price=Decimal(payload["b"]),
                            bid_qty=Decimal(payload["B"]),
                            ask_price=Decimal(payload["a"]),
                            ask_qty=Decimal(payload["A"]),
                            event_time_ms=int(payload.get("E", received)),
                            received_time_ms=received,
                        )
                        await self.state.update_best_bid_ask(value)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect boundary must contain stream failures
                self.connected = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.reconnect_count += 1
                attempt += 1
                delay = min(30.0, (2 ** min(attempt, 5)) + random.random())
                logger.warning(
                    "market_stream_disconnected symbol=%s reconnect_in=%.2fs error=%s",
                    self.symbol,
                    delay,
                    self.last_error,
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    pass
            finally:
                self.connected = False
