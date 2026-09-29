import asyncio
import logging
import time
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .binance_rest import BinanceRestClient
from .binance_ws import BinanceBookTickerStream
from .config import get_settings
from .event_bus import EventBus, EventType
from .market_state import MarketState
from .portfolio import PortfolioState
from .risk_engine import RiskEngine, RiskLimits
from .user_data_ws import BinanceUserDataStream

logger = logging.getLogger(__name__)

settings = get_settings()
settings.assert_safe_startup()
market_state = MarketState()
event_bus = EventBus()
portfolio_state = PortfolioState()
risk_engine = RiskEngine(
    RiskLimits(
        max_order_notional=settings.risk_max_order_notional,
        max_position_notional=settings.risk_max_position_notional,
        max_daily_loss=settings.risk_max_daily_loss,
        max_open_orders=settings.risk_max_open_orders,
        max_orders_per_minute=settings.risk_max_orders_per_minute,
        market_stale_after_ms=settings.market_stale_after_ms,
    )
)
rest = BinanceRestClient(
    settings.binance_rest_base_url,
    settings.binance_api_key,
    settings.binance_api_secret,
)
stream = BinanceBookTickerStream(
    settings.binance_ws_base_url,
    settings.normalized_symbol,
    market_state,
    event_bus,
)
user_stream = BinanceUserDataStream(
    settings.binance_ws_api_url,
    rest,
    portfolio_state,
    event_bus,
)
_stream_task: asyncio.Task | None = None
_user_stream_task: asyncio.Task | None = None
_reconcile_task: asyncio.Task | None = None
_rest_startup_error: str | None = None
_reconcile_error: str | None = None


class RiskProposal(BaseModel):
    side: str
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    client_order_id: str | None = Field(default=None, max_length=64)


def _credentials_configured() -> bool:
    return bool(settings.binance_api_key and settings.binance_api_secret)


async def _reconcile_once() -> None:
    global _reconcile_error
    account, orders = await asyncio.gather(rest.account(), rest.open_orders())
    now_ms = int(time.time() * 1000)
    await portfolio_state.replace_from_account(account, now_ms)
    await portfolio_state.replace_open_orders(orders, now_ms)
    _reconcile_error = None
    event_bus.publish(
        EventType.PORTFOLIO_RECONCILED,
        {"open_orders": len(orders), "reconciled_at_ms": now_ms},
    )


async def _reconcile_loop() -> None:
    global _reconcile_error
    while True:
        try:
            await _reconcile_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reconciliation failures must not kill service
            _reconcile_error = f"{type(exc).__name__}: {exc}"
            logger.warning("portfolio_reconcile_failed error=%s", _reconcile_error)
        await asyncio.sleep(settings.portfolio_reconcile_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _stream_task, _user_stream_task, _reconcile_task, _rest_startup_error
    try:
        await rest.ping()
        _rest_startup_error = None
    except Exception as exc:  # noqa: BLE001 - startup must stay alive when exchange REST is degraded
        _rest_startup_error = f"{type(exc).__name__}: {exc}"
        logger.warning("binance_rest_startup_degraded error=%s", _rest_startup_error)

    _stream_task = asyncio.create_task(stream.run(), name="binance-book-ticker")
    if _credentials_configured():
        _user_stream_task = asyncio.create_task(user_stream.run(), name="binance-user-data")
        _reconcile_task = asyncio.create_task(_reconcile_loop(), name="portfolio-reconcile")
    try:
        yield
    finally:
        await stream.stop()
        await user_stream.stop()
        tasks = [task for task in (_stream_task, _user_stream_task, _reconcile_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await rest.close()


app = FastAPI(title="Binance Fast Bot", version="0.4.0", lifespan=lifespan)


@app.get("/")
async def root() -> dict:
    return {
        "service": "Binance Fast Trading Platform",
        "status": "online",
        "mode": "safe",
        "trading_enabled": False,
        "phase": 6,
    }


@app.get("/health")
async def health() -> dict:
    age = await market_state.age_ms()
    stale = age is None or age > settings.market_stale_after_ms
    user_stream_expected = _credentials_configured()
    healthy_private = not user_stream_expected or user_stream.connected
    return {
        "status": "ok" if stream.connected and not stale and healthy_private else "degraded",
        "environment": settings.app_env,
        "trading_enabled": False,
        "symbol": settings.normalized_symbol,
        "market_stream_connected": stream.connected,
        "market_data_age_ms": age,
        "market_data_stale": stale,
        "market_reconnect_count": stream.reconnect_count,
        "last_market_stream_error": stream.last_error,
        "user_stream_expected": user_stream_expected,
        "user_stream_connected": user_stream.connected,
        "user_stream_reconnect_count": user_stream.reconnect_count,
        "last_user_stream_error": user_stream.last_error,
        "rest_startup_error": _rest_startup_error,
        "portfolio_reconcile_error": _reconcile_error,
        "risk_kill_switch_engaged": risk_engine.status()["kill_switch_engaged"],
        "event_bus_last_sequence": event_bus.stats()["last_sequence"],
    }


@app.get("/market")
async def market() -> dict:
    snap = await market_state.snapshot()
    if snap is None:
        return {"symbol": settings.normalized_symbol, "ready": False}
    return {
        "symbol": snap.symbol,
        "ready": True,
        "bid": str(snap.bid_price),
        "ask": str(snap.ask_price),
        "bid_qty": str(snap.bid_qty),
        "ask_qty": str(snap.ask_qty),
        "spread": str(snap.spread),
        "midpoint": str(snap.midpoint),
        "event_time_ms": snap.event_time_ms,
        "received_time_ms": snap.received_time_ms,
    }


@app.get("/portfolio")
async def portfolio() -> dict:
    data = await portfolio_state.snapshot()
    return {
        "trading_enabled": False,
        "user_stream_connected": user_stream.connected,
        "reconcile_error": _reconcile_error,
        **data,
    }


@app.post("/portfolio/reconcile")
async def portfolio_reconcile() -> dict:
    await _reconcile_once()
    return {"ok": True, **(await portfolio_state.snapshot())}


@app.get("/risk/status")
async def risk_status() -> dict:
    return {
        "trading_enabled": False,
        "mode": "dry_run_only",
        "base_asset": settings.normalized_base_asset,
        "quote_asset": settings.normalized_quote_asset,
        **risk_engine.status(),
    }


@app.post("/risk/evaluate")
async def risk_evaluate(proposal: RiskProposal) -> dict:
    market_snap = await market_state.snapshot()
    market_age_ms = await market_state.age_ms()
    if proposal.price is not None:
        price = proposal.price
    elif market_snap is not None:
        price = market_snap.midpoint
    else:
        price = Decimal(0)

    base_total = await portfolio_state.balance_total(settings.normalized_base_asset)
    current_position_notional = base_total * price
    open_orders_count = await portfolio_state.open_order_count()
    decision = risk_engine.evaluate(
        side=proposal.side,
        quantity=proposal.quantity,
        price=price,
        market_age_ms=market_age_ms,
        open_orders_count=open_orders_count,
        current_position_notional=current_position_notional,
        client_order_id=proposal.client_order_id,
        consume=False,
    )
    event_bus.publish(
        EventType.RISK_APPROVED if decision.approved else EventType.RISK_REJECTED,
        {
            "dry_run": True,
            "side": proposal.side.upper(),
            "quantity": str(proposal.quantity),
            "price": str(price),
            "reason": decision.reason.value,
        },
    )
    return {
        "dry_run": True,
        "trading_enabled": False,
        "symbol": settings.normalized_symbol,
        "current_position_notional": str(current_position_notional),
        "open_orders_count": open_orders_count,
        "market_data_age_ms": market_age_ms,
        **decision.as_dict(),
    }


@app.get("/events/stats")
async def event_stats() -> dict:
    return event_bus.stats()


@app.get("/binance/time")
async def binance_time() -> dict:
    return {"server_time_ms": await rest.server_time_ms()}


@app.get("/account/check")
async def account_check() -> dict:
    data = await rest.account()
    return {
        "can_trade": bool(data.get("canTrade")),
        "can_withdraw": bool(data.get("canWithdraw")),
        "can_deposit": bool(data.get("canDeposit")),
        "account_type": data.get("accountType"),
    }


@app.get("/api-key/check")
async def api_key_check() -> dict:
    data = await rest.api_restrictions()
    return {
        "ip_restricted": bool(data.get("ipRestrict")),
        "reading": bool(data.get("enableReading")),
        "spot_margin_trading": bool(data.get("enableSpotAndMarginTrading")),
        "withdrawals": bool(data.get("enableWithdrawals")),
        "futures": bool(data.get("enableFutures")),
        "universal_transfer": bool(data.get("permitsUniversalTransfer")),
    }
