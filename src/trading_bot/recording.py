import asyncio
import json
import time
from collections import deque
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .event_bus import EventBus, EventType
from .models import BestBidAsk


@dataclass(slots=True, frozen=True)
class RecordedTick:
    sequence: int
    symbol: str
    bid_price: str
    bid_qty: str
    ask_price: str
    ask_qty: str
    event_time_ms: int
    received_time_ms: int
    recorded_time_ms: int

    @property
    def midpoint(self) -> Decimal:
        return (Decimal(self.bid_price) + Decimal(self.ask_price)) / Decimal(2)

    @property
    def spread(self) -> Decimal:
        return Decimal(self.ask_price) - Decimal(self.bid_price)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecordedTick":
        return cls(
            sequence=int(data["sequence"]),
            symbol=str(data["symbol"]),
            bid_price=str(data["bid_price"]),
            bid_qty=str(data["bid_qty"]),
            ask_price=str(data["ask_price"]),
            ask_qty=str(data["ask_qty"]),
            event_time_ms=int(data["event_time_ms"]),
            received_time_ms=int(data["received_time_ms"]),
            recorded_time_ms=int(data["recorded_time_ms"]),
        )

    def to_quote(self) -> BestBidAsk:
        return BestBidAsk(
            symbol=self.symbol,
            bid_price=Decimal(self.bid_price),
            bid_qty=Decimal(self.bid_qty),
            ask_price=Decimal(self.ask_price),
            ask_qty=Decimal(self.ask_qty),
            event_time_ms=self.event_time_ms,
            received_time_ms=self.received_time_ms,
        )


class MarketRecorder:
    """Non-blocking market-tick recorder with an in-memory ring and optional JSONL persistence."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        max_events: int,
        path: str | None = None,
        flush_batch_size: int = 250,
    ) -> None:
        self.event_bus = event_bus
        self.max_events = max_events
        self.path = Path(path) if path else None
        self.flush_batch_size = flush_batch_size
        self._events: deque[RecordedTick] = deque(maxlen=max_events)
        self._queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._pending_lines: list[str] = []
        self._recorded = 0
        self._write_error: str | None = None
        self._started_at_ms: int | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        if self.path is not None:
            await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
        self._queue = self.event_bus.subscribe(EventType.MARKET_TICK, max_queue=8192)
        self._started_at_ms = int(time.time() * 1000)
        self._task = asyncio.create_task(self._run(), name="market-recorder")

    async def stop(self) -> None:
        if self._queue is not None:
            self.event_bus.unsubscribe(EventType.MARKET_TICK, self._queue)
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._queue = None
        await self._flush()

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            quote = event.payload.get("quote")
            if not isinstance(quote, BestBidAsk):
                continue
            tick = RecordedTick(
                sequence=event.sequence,
                symbol=quote.symbol,
                bid_price=str(quote.bid_price),
                bid_qty=str(quote.bid_qty),
                ask_price=str(quote.ask_price),
                ask_qty=str(quote.ask_qty),
                event_time_ms=quote.event_time_ms,
                received_time_ms=quote.received_time_ms,
                recorded_time_ms=int(time.time() * 1000),
            )
            self._events.append(tick)
            self._recorded += 1
            if self.path is not None:
                self._pending_lines.append(json.dumps(tick.as_dict(), separators=(",", ":")))
                if len(self._pending_lines) >= self.flush_batch_size:
                    await self._flush()

    async def _flush(self) -> None:
        if self.path is None or not self._pending_lines:
            return
        lines = self._pending_lines
        self._pending_lines = []
        text = "\n".join(lines) + "\n"
        try:
            await asyncio.to_thread(self._append_text, text)
            self._write_error = None
        except OSError as exc:
            self._write_error = f"{type(exc).__name__}: {exc}"
            self._pending_lines = lines + self._pending_lines

    def _append_text(self, text: str) -> None:
        assert self.path is not None
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    def status(self) -> dict[str, Any]:
        return {
            "running": self._task is not None and not self._task.done(),
            "started_at_ms": self._started_at_ms,
            "recorded_total": self._recorded,
            "buffered_events": len(self._events),
            "max_events": self.max_events,
            "persist_path": None if self.path is None else str(self.path),
            "pending_persist_events": len(self._pending_lines),
            "last_write_error": self._write_error,
        }

    def events(
        self,
        *,
        limit: int = 1000,
        start_sequence: int | None = None,
        end_sequence: int | None = None,
    ) -> list[RecordedTick]:
        selected = []
        for tick in self._events:
            if start_sequence is not None and tick.sequence < start_sequence:
                continue
            if end_sequence is not None and tick.sequence > end_sequence:
                continue
            selected.append(tick)
        if limit < len(selected):
            selected = selected[-limit:]
        return selected

    async def clear(self) -> None:
        self._events.clear()
        self._recorded = 0
        self._pending_lines.clear()
        if self.path is not None and self.path.exists():
            await asyncio.to_thread(self.path.unlink)


class ReplayEngine:
    """Replays recorded quotes through an isolated event bus and returns deterministic metrics."""

    async def run(self, ticks: list[RecordedTick], *, speed: float = 0.0) -> dict[str, Any]:
        if not ticks:
            return {
                "ticks": 0,
                "source_duration_ms": 0,
                "replay_elapsed_ms": 0,
                "first_midpoint": None,
                "last_midpoint": None,
                "min_midpoint": None,
                "max_midpoint": None,
                "average_spread": None,
            }
        if speed < 0:
            raise ValueError("speed must be >= 0")

        bus = EventBus()
        started = time.monotonic_ns()
        previous_event_time = ticks[0].event_time_ms
        mids: list[Decimal] = []
        spreads: list[Decimal] = []

        for tick in ticks:
            if speed > 0:
                delta_ms = max(0, tick.event_time_ms - previous_event_time)
                if delta_ms:
                    await asyncio.sleep((delta_ms / 1000) / speed)
            previous_event_time = tick.event_time_ms
            quote = tick.to_quote()
            bus.publish(EventType.MARKET_TICK, {"quote": quote, "replay": True})
            mids.append(tick.midpoint)
            spreads.append(tick.spread)

        elapsed_ms = (time.monotonic_ns() - started) // 1_000_000
        source_duration_ms = max(0, ticks[-1].event_time_ms - ticks[0].event_time_ms)
        average_spread = sum(spreads, Decimal(0)) / Decimal(len(spreads))
        return {
            "ticks": len(ticks),
            "source_duration_ms": source_duration_ms,
            "replay_elapsed_ms": elapsed_ms,
            "speed": speed,
            "first_sequence": ticks[0].sequence,
            "last_sequence": ticks[-1].sequence,
            "first_midpoint": str(mids[0]),
            "last_midpoint": str(mids[-1]),
            "min_midpoint": str(min(mids)),
            "max_midpoint": str(max(mids)),
            "average_spread": str(average_spread),
            "published_events": bus.stats()["published"].get("market_tick", 0),
        }
