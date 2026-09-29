import asyncio
import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .event_bus import EventBus, EventType
from .models import BestBidAsk
from .recording import RecordedTick


class ResearchDatasetStore:
    """Persist a downsampled market dataset for multi-day research.

    The live market feed can publish many updates per second. Research does not need
    every micro-update, so this store keeps one immutable top-of-book snapshot per
    configured interval and rotates files by UTC day. A Railway volume can be mounted
    at the configured directory to make the dataset survive deploys and restarts.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        directory: str,
        sample_interval_ms: int = 1000,
        memory_events: int = 10000,
    ) -> None:
        if sample_interval_ms < 100:
            raise ValueError("sample_interval_ms must be >= 100")
        self.event_bus = event_bus
        self.directory = Path(directory)
        self.sample_interval_ms = sample_interval_ms
        self._recent: deque[RecordedTick] = deque(maxlen=memory_events)
        self._queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._last_sample_time_ms: int | None = None
        self._samples_written = 0
        self._write_error: str | None = None
        self._started_at_ms: int | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        await asyncio.to_thread(self.directory.mkdir, parents=True, exist_ok=True)
        await self._load_recent()
        self._queue = self.event_bus.subscribe(EventType.MARKET_TICK, max_queue=4096)
        self._started_at_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
        self._task = asyncio.create_task(self._run(), name="research-dataset-store")

    async def stop(self) -> None:
        if self._queue is not None:
            self.event_bus.unsubscribe(EventType.MARKET_TICK, self._queue)
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._queue = None

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            event = await self._queue.get()
            quote = event.payload.get("quote")
            if not isinstance(quote, BestBidAsk):
                continue
            if (
                self._last_sample_time_ms is not None
                and quote.event_time_ms - self._last_sample_time_ms < self.sample_interval_ms
            ):
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
                recorded_time_ms=int(datetime.now(tz=UTC).timestamp() * 1000),
            )
            await self.append(tick)

    async def append(self, tick: RecordedTick) -> None:
        if (
            self._last_sample_time_ms is not None
            and tick.event_time_ms - self._last_sample_time_ms < self.sample_interval_ms
        ):
            return
        self._recent.append(tick)
        self._last_sample_time_ms = tick.event_time_ms
        day = datetime.fromtimestamp(tick.event_time_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
        path = self.directory / f"{tick.symbol}-{day}.jsonl"
        line = json.dumps(tick.as_dict(), separators=(",", ":")) + "\n"
        try:
            await asyncio.to_thread(self._append_text, path, line)
            self._samples_written += 1
            self._write_error = None
        except OSError as exc:
            self._write_error = f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _append_text(path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    async def _load_recent(self) -> None:
        ticks = await asyncio.to_thread(self._read_files, self._recent.maxlen or 10000)
        self._recent.clear()
        self._recent.extend(ticks)
        if ticks:
            self._last_sample_time_ms = ticks[-1].event_time_ms

    def _read_files(self, limit: int) -> list[RecordedTick]:
        selected: deque[RecordedTick] = deque(maxlen=limit)
        for path in sorted(self.directory.glob("*.jsonl")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            selected.append(RecordedTick.from_dict(json.loads(line)))
                        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                            continue
            except OSError:
                continue
        return list(selected)

    async def events(self, *, limit: int) -> list[RecordedTick]:
        limit = max(1, limit)
        return await asyncio.to_thread(self._read_files, limit)

    async def status(self) -> dict[str, Any]:
        files = await asyncio.to_thread(lambda: sorted(self.directory.glob("*.jsonl")))
        recent = list(self._recent)
        source_duration_ms = (
            max(0, recent[-1].event_time_ms - recent[0].event_time_ms) if len(recent) >= 2 else 0
        )
        total_bytes = 0
        for path in files:
            try:
                total_bytes += path.stat().st_size
            except OSError:
                pass
        directory_text = str(self.directory)
        return {
            "running": self._task is not None and not self._task.done(),
            "directory": directory_text,
            "persistent_path_configured": not directory_text.startswith("/tmp"),
            "sample_interval_ms": self.sample_interval_ms,
            "files": len(files),
            "recent_samples": len(recent),
            "recent_source_duration_ms": source_duration_ms,
            "samples_written_this_process": self._samples_written,
            "bytes_on_disk": total_bytes,
            "last_write_error": self._write_error,
            "started_at_ms": self._started_at_ms,
        }
