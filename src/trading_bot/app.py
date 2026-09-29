import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .binance_rest import BinanceRestClient
from .binance_ws import BinanceBookTickerStream
from .config import get_settings
from .market_state import MarketState

settings = get_settings()
settings.assert_safe_startup()
market_state = MarketState()
rest = BinanceRestClient(
    settings.binance_rest_base_url,
    settings.binance_api_key,
    settings.binance_api_secret,
)
stream = BinanceBookTickerStream(
    settings.binance_ws_base_url, settings.normalized_symbol, market_state
)
_stream_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _stream_task
    await rest.ping()
    _stream_task = asyncio.create_task(stream.run(), name="binance-book-ticker")
    try:
        yield
    finally:
        await stream.stop()
        if _stream_task:
            _stream_task.cancel()
            await asyncio.gather(_stream_task, return_exceptions=True)
        await rest.close()


app = FastAPI(title="Binance Fast Bot", version="0.1.0", lifespan=lifespan)


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
