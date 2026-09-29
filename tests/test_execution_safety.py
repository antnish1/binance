from decimal import Decimal

import pytest

from trading_bot.execution import DisabledExecutionEngine, ExecutionBlocked, OrderIntent, Side


@pytest.mark.asyncio
async def test_execution_is_hard_blocked():
    engine = DisabledExecutionEngine()
    with pytest.raises(ExecutionBlocked):
        await engine.submit(OrderIntent(symbol="BTCUSDT", side=Side.BUY, quantity=Decimal("0.001")))
