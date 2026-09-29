import asyncio
from decimal import Decimal

from trading_bot.event_bus import EventBus
from trading_bot.models import BestBidAsk
from trading_bot.paper_execution import PaperExecutor


def quote(bid: str = "100", ask: str = "101") -> BestBidAsk:
    return BestBidAsk(
        symbol="BTCUSDT",
        bid_price=Decimal(bid),
        bid_qty=Decimal(10),
        ask_price=Decimal(ask),
        ask_qty=Decimal(10),
        event_time_ms=1,
        received_time_ms=1,
    )


def test_market_buy_and_sell_update_paper_pnl() -> None:
    async def run() -> None:
        executor = PaperExecutor(
            event_bus=EventBus(),
            symbol="BTCUSDT",
            starting_quote_balance=Decimal(1000),
            fee_bps=Decimal(10),
            slippage_bps=Decimal(0),
        )
        buy = await executor.submit(
            side="BUY",
            order_type="MARKET",
            quantity=Decimal(1),
            quote=quote(),
            client_order_id="buy-1",
        )
        assert buy.status == "FILLED"
        snap = await executor.snapshot(Decimal(100))
        assert snap["base_balance"] == "1"
        assert Decimal(snap["fees_paid"]) > 0

        sell = await executor.submit(
            side="SELL",
            order_type="MARKET",
            quantity=Decimal(1),
            quote=quote("102", "103"),
            client_order_id="sell-1",
        )
        assert sell.status == "FILLED"
        snap = await executor.snapshot(Decimal(102))
        assert snap["base_balance"] == "0"
        assert Decimal(snap["realized_pnl"]) > 0

    asyncio.run(run())


def test_resting_limit_fills_on_later_quote() -> None:
    async def run() -> None:
        executor = PaperExecutor(
            event_bus=EventBus(),
            symbol="BTCUSDT",
            starting_quote_balance=Decimal(1000),
            fee_bps=Decimal(0),
            slippage_bps=Decimal(0),
        )
        order = await executor.submit(
            side="BUY",
            order_type="LIMIT",
            quantity=Decimal(1),
            limit_price=Decimal(99),
            quote=quote("100", "101"),
            client_order_id="limit-1",
        )
        assert order.status == "NEW"
        assert await executor.open_order_count() == 1

        await executor.on_quote(quote("98", "99"))
        assert order.status == "FILLED"
        assert await executor.open_order_count() == 0

    asyncio.run(run())


def test_cancel_open_limit_order() -> None:
    async def run() -> None:
        executor = PaperExecutor(
            event_bus=EventBus(),
            symbol="BTCUSDT",
            starting_quote_balance=Decimal(1000),
            fee_bps=Decimal(0),
            slippage_bps=Decimal(0),
        )
        order = await executor.submit(
            side="SELL",
            order_type="LIMIT",
            quantity=Decimal("0.1"),
            limit_price=Decimal(110),
            quote=quote(),
            client_order_id="limit-2",
        )
        assert order.status == "NEW"
        cancelled = await executor.cancel(order.order_id)
        assert cancelled.status == "CANCELED"
        assert await executor.open_order_count() == 0

    asyncio.run(run())
