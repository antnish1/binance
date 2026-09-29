import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .binance_rest import BinanceRestClient
from .binance_ws import BinanceBookTickerStream
from .config import get_settings
from .event_bus import EventBus
from .market_state import MarketState

logger = logging.getLogger(__name__)

settings = get_settings()
settings.assert_safe_startup()
market_state = MarketState()
event_bus = EventBus()
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
_stream_task: asyncio.Task | None = None
_rest_startup_error: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _stream_task, _rest_startup_error
    try:
        await rest.ping()
        _rest_startup_error = None
    except Exception as exc:  # noqa: BLE001 - startup must stay alive when exchange REST is degraded
        _rest_startup_error = f"{type(exc).__name__}: {exc}"
        logger.warning("binance_rest_startup_degraded error=%s", _rest_startup_error)

    _stream_task = asyncio.create_task(stream.run(), name="binance-book-ticker")
    try:
        yield
    finally:
        await stream.stop()
        if _stream_task:
            _stream_task.cancel()
            await asyncio.gather(_stream_task, return_exceptions=True)
        await rest.close()


app = FastAPI(title="Binance Fast Bot", version="0.2.0", lifespan=lifespan)


@app.get("/")
async def root() -> dict:
    return {
        "service": "Binance Fast Trading Platform",
        "status": "online",
        "mode": "safe",
        "trading_enabled": False,
        "phase": 4,
    }


@app.get("/health")
async def health() -> dict:
    age = await market_state.age_ms()
    stale = age is None or age > settings.market_stale_after_ms
    return {
        "status": "ok" if stream.connected and not stale else "degraded",
        "environment": settings.app_env,
        "trading_enabled": False,
        "symbol": settings.normalized_symbol,
        "market_stream_connected": stream.connected,
        "market_data_age_ms": age,
        "market_data_stale": stale,
        "reconnect_count": stream.reconnect_count,
        "last_stream_error": stream.last_error,
        "rest_startup_error": _rest_startup_error,
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
