import asyncio

import pytest

from trading_bot.event_bus import EventBus, EventType


@pytest.mark.asyncio
async def test_event_bus_delivers_events_and_tracks_stats() -> None:
    bus = EventBus()
    queue = bus.subscribe(EventType.MARKET_TICK, max_queue=1)

    first = bus.publish(EventType.MARKET_TICK, {"price": "100"})
    received = await asyncio.wait_for(queue.get(), timeout=0.1)

    assert received.sequence == first.sequence
    assert received.event_type is EventType.MARKET_TICK
    assert received.payload["price"] == "100"

    bus.publish(EventType.MARKET_TICK, {"price": "101"})
    bus.publish(EventType.MARKET_TICK, {"price": "102"})

    stats = bus.stats()
    assert stats["published"]["market_tick"] == 3
    assert stats["dropped"]["market_tick"] == 1
    assert stats["subscribers"]["market_tick"] == 1

    bus.unsubscribe(EventType.MARKET_TICK, queue)
    assert bus.stats()["subscribers"].get("market_tick", 0) == 0


def test_event_bus_rejects_invalid_queue_size() -> None:
    bus = EventBus()
    with pytest.raises(ValueError, match="max_queue"):
        bus.subscribe(EventType.MARKET_TICK, max_queue=0)
