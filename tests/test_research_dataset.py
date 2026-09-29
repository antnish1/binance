from decimal import Decimal

import pytest

from trading_bot.event_bus import EventBus
from trading_bot.recording import RecordedTick
from trading_bot.research_dataset import ResearchDatasetStore


@pytest.mark.asyncio
async def test_research_dataset_persists_and_reloads(tmp_path) -> None:
    bus = EventBus()
    store = ResearchDatasetStore(
        event_bus=bus,
        directory=str(tmp_path / "research"),
        sample_interval_ms=1000,
        memory_events=10,
    )
    await store.start()

    base = 1_700_000_000_000
    for index in range(3):
        tick = RecordedTick(
            sequence=index + 1,
            symbol="BTCUSDT",
            bid_price=str(Decimal(100) + Decimal(index)),
            bid_qty="1",
            ask_price=str(Decimal("100.01") + Decimal(index)),
            ask_qty="1",
            event_time_ms=base + index * 1000,
            received_time_ms=base + index * 1000,
            recorded_time_ms=base + index * 1000,
        )
        await store.append(tick)
    await store.stop()

    reloaded = ResearchDatasetStore(
        event_bus=bus,
        directory=str(tmp_path / "research"),
        sample_interval_ms=1000,
        memory_events=10,
    )
    await reloaded.start()
    events = await reloaded.events(limit=10)
    status = await reloaded.status()
    await reloaded.stop()

    assert len(events) == 3
    assert events[0].sequence == 1
    assert events[-1].sequence == 3
    assert status["files"] == 1
    assert status["bytes_on_disk"] > 0


@pytest.mark.asyncio
async def test_research_dataset_downsamples(tmp_path) -> None:
    store = ResearchDatasetStore(
        event_bus=EventBus(),
        directory=str(tmp_path / "research"),
        sample_interval_ms=1000,
    )
    await store.start()
    base = 1_700_000_000_000

    for index, offset in enumerate((0, 100, 999, 1000, 1500, 2000)):
        await store.append(
            RecordedTick(
                sequence=index + 1,
                symbol="BTCUSDT",
                bid_price="100",
                bid_qty="1",
                ask_price="100.01",
                ask_qty="1",
                event_time_ms=base + offset,
                received_time_ms=base + offset,
                recorded_time_ms=base + offset,
            )
        )

    events = await store.events(limit=10)
    await store.stop()

    assert [event.event_time_ms - base for event in events] == [0, 1000, 2000]


def test_data_volume_path_is_marked_non_tmp() -> None:
    store = ResearchDatasetStore(
        event_bus=EventBus(),
        directory="/data/taddy-research",
        sample_interval_ms=1000,
    )

    assert not str(store.directory).startswith("/tmp")
