import asyncio
import time
from decimal import Decimal

from trading_bot.automation import AutomationConfig, MeanReversionAutomation
from trading_bot.event_bus import EventBus
from trading_bot.models import BestBidAsk
from trading_bot.paper_execution import PaperExecutor
from trading_bot.risk_engine import RiskEngine, RiskLimits


def quote(mid: str) -> BestBidAsk:
    midpoint = Decimal(mid)
    half_spread = Decimal("0.05")
    now_ms = int(time.time() * 1000)
    return BestBidAsk(
        symbol="BTCUSDT",
        bid_price=midpoint - half_spread,
        bid_qty=Decimal(10),
        ask_price=midpoint + half_spread,
        ask_qty=Decimal(10),
        event_time_ms=now_ms,
        received_time_ms=now_ms,
    )


def build_automation() -> tuple[MeanReversionAutomation, PaperExecutor]:
    bus = EventBus()
    executor = PaperExecutor(
        event_bus=bus,
        symbol="BTCUSDT",
        starting_quote_balance=Decimal(1000),
        fee_bps=Decimal(0),
        slippage_bps=Decimal(0),
    )
    risk = RiskEngine(
        RiskLimits(
            max_order_notional=Decimal(500),
            max_position_notional=Decimal(500),
            max_daily_loss=Decimal(100),
            max_open_orders=3,
            max_orders_per_minute=10,
            market_stale_after_ms=5000,
        )
    )
    automation = MeanReversionAutomation(
        event_bus=bus,
        paper_executor=executor,
        risk_engine=risk,
        config=AutomationConfig(
            quantity=Decimal(1),
            threshold_bps=Decimal(100),
            lookback=3,
            cooldown_seconds=0,
        ),
    )
    return automation, executor


def test_disabled_automation_only_observes() -> None:
    async def run() -> None:
        automation, executor = build_automation()
        for price in ("100", "100", "98"):
            await automation.on_quote(quote(price))
        assert await executor.base_balance() == Decimal(0)
        assert automation.status()["state"] == "disabled"

    asyncio.run(run())


def test_mean_reversion_buys_dip_and_sells_reversion() -> None:
    async def run() -> None:
        automation, executor = build_automation()
        automation.enable()
        await automation.on_quote(quote("100"))
        await automation.on_quote(quote("100"))
        await automation.on_quote(quote("98"))

        assert await executor.base_balance() == Decimal(1)
        status = automation.status()
        assert status["filled"] == 1
        assert status["last_signal"] == "BUY"

        await automation.on_quote(quote("103"))
        assert await executor.base_balance() == Decimal(0)
        status = automation.status()
        assert status["filled"] == 2
        assert status["last_signal"] == "SELL"

    asyncio.run(run())


def test_reset_clears_automation_counters() -> None:
    async def run() -> None:
        automation, _ = build_automation()
        automation.enable()
        for price in ("100", "100", "98"):
            await automation.on_quote(quote(price))
        assert automation.status()["signals"] == 1
        automation.reset()
        status = automation.status()
        assert status["signals"] == 0
        assert status["filled"] == 0
        assert status["samples"] == 0
        assert status["state"] == "warming_up"

    asyncio.run(run())
