import asyncio
from decimal import Decimal

from trading_bot.event_bus import EventBus, EventType
from trading_bot.models import BestBidAsk
from trading_bot.recording import MarketRecorder, ReplayEngine


def _quote(price: str, event_time_ms: int) -> BestBidAsk:
    value = Decimal(price)
    return BestBidAsk(
        symbol="BTCUSDT",
        bid_price=value,
        bid_qty=Decimal(1),
        ask_price=value + Decimal(1),
        ask_qty=Decimal(1),
        event_time_ms=event_time_ms,
        received_time_ms=event_time_ms + 1,
    )


def test_recorder_and_replay() -> None:
    async def run() -> None:
        bus = EventBus()
        recorder = MarketRecorder(event_bus=bus, max_events=1000, path=None, flush_batch_size=2)
        await recorder.start()
        bus.publish(EventType.MARKET_TICK, {"quote": _quote("100", 1000)})
        bus.publish(EventType.MARKET_TICK, {"quote": _quote("101", 1100)})
        await asyncio.sleep(0)

        events = recorder.events(limit=10)
        assert len(events) == 2
        assert events[0].bid_price == "100"
        assert recorder.status()["recorded_total"] == 2

        result = await ReplayEngine().run(events, speed=0)
        assert result["ticks"] == 2
        assert result["source_duration_ms"] == 100
        assert result["published_events"] == 2
        assert result["first_midpoint"] == "100.5"
        assert result["last_midpoint"] == "101.5"
        assert result["average_spread"] == "1"
        await recorder.stop()

    asyncio.run(run())


def test_recorder_sequence_filters_and_ring_limit() -> None:
    async def run() -> None:
        bus = EventBus()
        recorder = MarketRecorder(event_bus=bus, max_events=3, path=None)
        await recorder.start()
        for index in range(5):
            bus.publish(EventType.MARKET_TICK, {"quote": _quote(str(100 + index), 1000 + index)})
        await asyncio.sleep(0)

        events = recorder.events(limit=10)
        assert len(events) == 3
        selected = recorder.events(limit=10, start_sequence=4)
        assert all(event.sequence >= 4 for event in selected)
        await recorder.clear()
        assert recorder.status()["buffered_events"] == 0
        await recorder.stop()

    asyncio.run(run())
