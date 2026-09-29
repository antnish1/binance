from decimal import Decimal

import pytest

from trading_bot.market_state import MarketState
from trading_bot.models import BestBidAsk


@pytest.mark.asyncio
async def test_market_state_snapshot_and_spread():
    state = MarketState()
    value = BestBidAsk(
        symbol="BTCUSDT",
        bid_price=Decimal("100.00"),
        bid_qty=Decimal("1.2"),
        ask_price=Decimal("100.10"),
        ask_qty=Decimal("1.3"),
        event_time_ms=1,
        received_time_ms=1,
    )
    await state.update_best_bid_ask(value)
    snap = await state.snapshot()
    assert snap is not None
    assert snap.spread == Decimal("0.10")
    assert snap.midpoint == Decimal("100.05")
