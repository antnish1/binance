import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .binance_rest import BinanceRestClient
from .binance_ws import BinanceBookTickerStream
from .config import get_settings
from .event_bus import EventBus, EventType
from .market_state import MarketState
from .portfolio import PortfolioState
from .user_data_ws import BinanceUserDataStream

logger = logging.getLogger(__name__)

settings = get_settings()
settings.assert_safe_startup()
market_state = MarketState()
event_bus = EventBus()
portfolio_state = PortfolioState()
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


app = FastAPI(title="Binance Fast Bot", version="0.3.0", lifespan=lifespan)


@app.get("/")
async def root() -> dict:
    return {
        "service": "Binance Fast Trading Platform",
        "status": "online",
        "mode": "safe",
        "trading_enabled": False,
        "phase": 5,
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
