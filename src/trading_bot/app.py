import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .automation import AutomationConfig, MeanReversionAutomation
from .binance_rest import BinanceRestClient
from .binance_ws import BinanceBookTickerStream
from .config import get_settings
from .event_bus import EventBus, EventType
from .market_state import MarketState
from .paper_execution import PaperExecutor
from .portfolio import PortfolioState
from .recording import MarketRecorder, ReplayEngine
from .research import StrategyResearchLab
from .research_dataset import ResearchDatasetStore
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
paper_executor = PaperExecutor(
    event_bus=event_bus,
    symbol=settings.normalized_symbol,
    starting_quote_balance=settings.paper_starting_quote_balance,
    fee_bps=settings.paper_fee_bps,
    slippage_bps=settings.paper_slippage_bps,
)
automation = MeanReversionAutomation(
    event_bus=event_bus,
    paper_executor=paper_executor,
    risk_engine=risk_engine,
    config=AutomationConfig(
        quantity=settings.automation_quantity,
        threshold_bps=settings.automation_threshold_bps,
        lookback=settings.automation_lookback,
        cooldown_seconds=settings.automation_cooldown_seconds,
    ),
)
market_recorder = MarketRecorder(
    event_bus=event_bus,
    max_events=settings.recording_max_events,
    path=settings.recording_path if settings.recording_enabled else None,
)
research_dataset = ResearchDatasetStore(
    event_bus=event_bus,
    directory=settings.research_dataset_dir,
    sample_interval_ms=settings.research_sample_interval_ms,
)
replay_engine = ReplayEngine()
research_lab = StrategyResearchLab(
    starting_quote_balance=settings.paper_starting_quote_balance,
    quantity=settings.automation_quantity,
    fee_bps=settings.paper_fee_bps,
    slippage_bps=settings.paper_slippage_bps,
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
_latest_research: dict | None = None


class RiskProposal(BaseModel):
    side: str
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    client_order_id: str | None = Field(default=None, max_length=64)


class PaperOrderProposal(BaseModel):
    side: str
    order_type: str = "MARKET"
    quantity: Decimal = Field(gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    client_order_id: str | None = Field(default=None, max_length=64)


class ReplayRequest(BaseModel):
    start_sequence: int | None = Field(default=None, ge=1)
    end_sequence: int | None = Field(default=None, ge=1)
    max_events: int = Field(default=10000, ge=1)
    speed: float = Field(default=0.0, ge=0, le=1000)


class AutomationConfigRequest(BaseModel):
    quantity: Decimal = Field(gt=0)
    threshold_bps: Decimal = Field(gt=0, le=1000)
    lookback: int = Field(ge=5, le=5000)
    cooldown_seconds: int = Field(ge=1, le=3600)


class ResearchRequest(BaseModel):
    max_events: int = Field(default=100000, ge=100, le=500000)
    train_fraction: Decimal = Field(default=Decimal("0.70"), ge=Decimal("0.50"), le=Decimal("0.90"))


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

    await paper_executor.start()
    await automation.start()
    if settings.automation_enabled:
        automation.enable()
    if settings.recording_enabled:
        await market_recorder.start()
    if settings.research_dataset_enabled:
        await research_dataset.start()
    _stream_task = asyncio.create_task(stream.run(), name="binance-book-ticker")
    if _credentials_configured():
        _user_stream_task = asyncio.create_task(user_stream.run(), name="binance-user-data")
        _reconcile_task = asyncio.create_task(_reconcile_loop(), name="portfolio-reconcile")
    try:
        yield
    finally:
        await automation.stop()
        if settings.research_dataset_enabled:
            await research_dataset.stop()
        await market_recorder.stop()
        await paper_executor.stop()
        await stream.stop()
        await user_stream.stop()
        tasks = [task for task in (_stream_task, _user_stream_task, _reconcile_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await rest.close()


app = FastAPI(title="Taddy Market Automation", version="0.9.0", lifespan=lifespan)


@app.get("/")
async def root() -> dict:
    return {
        "service": "Taddy Market Automation",
        "status": "online",
        "mode": "paper",
        "live_execution_enabled": False,
        "phase": 13,
    }


@app.get("/health")
async def health() -> dict:
    age = await market_state.age_ms()
    stale = age is None or age > settings.market_stale_after_ms
    user_stream_expected = _credentials_configured()
    healthy_private = not user_stream_expected or user_stream.connected
    dataset_status = await research_dataset.status() if settings.research_dataset_enabled else {}
    return {
        "status": "ok" if stream.connected and not stale and healthy_private else "degraded",
        "environment": settings.app_env,
        "live_execution_enabled": False,
        "paper_execution_enabled": True,
        "automation_enabled": automation.status()["enabled"],
        "recording_enabled": settings.recording_enabled,
        "recording_running": market_recorder.status()["running"],
        "research_available": True,
        "research_dataset_running": bool(dataset_status.get("running", False)),
        "research_dataset_persistent": bool(dataset_status.get("persistent_path_configured", False)),
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
        "live_execution_enabled": False,
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
        "live_execution_enabled": False,
        "mode": "paper_only",
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

    base_total = await paper_executor.base_balance()
    current_position_notional = base_total * price
    open_orders_count = await paper_executor.open_order_count()
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
        "live_execution_enabled": False,
        "symbol": settings.normalized_symbol,
        "current_position_notional": str(current_position_notional),
        "open_orders_count": open_orders_count,
        "market_data_age_ms": market_age_ms,
        **decision.as_dict(),
    }


@app.get("/paper/status")
async def paper_status() -> dict:
    snap = await market_state.snapshot()
    mark_price = None if snap is None else snap.midpoint
    return await paper_executor.snapshot(mark_price)


@app.get("/paper/orders")
async def paper_orders() -> dict:
    snap = await paper_executor.snapshot()
    return {"orders": snap["orders"], "open_orders": snap["open_orders"]}


@app.post("/paper/orders")
async def paper_submit(proposal: PaperOrderProposal) -> dict:
    quote = await market_state.snapshot()
    market_age_ms = await market_state.age_ms()
    if quote is None:
        raise HTTPException(status_code=503, detail="market data unavailable")

    side = proposal.side.upper().strip()
    order_type = proposal.order_type.upper().strip()
    if order_type not in {"MARKET", "LIMIT"}:
        raise HTTPException(status_code=400, detail="order_type must be MARKET or LIMIT")
    if order_type == "LIMIT" and proposal.limit_price is None:
        raise HTTPException(status_code=400, detail="limit_price is required for LIMIT orders")

    if order_type == "LIMIT":
        risk_price = proposal.limit_price or Decimal(0)
    elif side == "BUY":
        risk_price = quote.ask_price
    else:
        risk_price = quote.bid_price

    paper_snap = await paper_executor.snapshot(quote.midpoint)
    risk_engine.set_daily_realized_pnl(Decimal(paper_snap["realized_pnl"]))
    current_position_notional = await paper_executor.base_balance() * risk_price
    open_orders_count = await paper_executor.open_order_count()
    client_order_id = proposal.client_order_id or f"paper-{uuid.uuid4().hex[:20]}"
    decision = risk_engine.evaluate(
        side=side,
        quantity=proposal.quantity,
        price=risk_price,
        market_age_ms=market_age_ms,
        open_orders_count=open_orders_count,
        current_position_notional=current_position_notional,
        client_order_id=client_order_id,
        consume=True,
    )
    event_bus.publish(
        EventType.RISK_APPROVED if decision.approved else EventType.RISK_REJECTED,
        {
            "paper": True,
            "client_order_id": client_order_id,
            "side": side,
            "quantity": str(proposal.quantity),
            "price": str(risk_price),
            "reason": decision.reason.value,
        },
    )
    if not decision.approved:
        return {"accepted": False, "paper": True, **decision.as_dict()}

    try:
        order = await paper_executor.submit(
            side=side,
            order_type=order_type,
            quantity=proposal.quantity,
            quote=quote,
            client_order_id=client_order_id,
            limit_price=proposal.limit_price,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    current = await paper_executor.snapshot(quote.midpoint)
    risk_engine.set_daily_realized_pnl(Decimal(current["realized_pnl"]))
    return {
        "accepted": order.status != "REJECTED",
        "paper": True,
        "order": PaperExecutor._serialize(order),
        "risk": decision.as_dict(),
    }


@app.post("/paper/orders/{order_id}/cancel")
async def paper_cancel(order_id: int) -> dict:
    try:
        order = await paper_executor.cancel(order_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"paper": True, "order": PaperExecutor._serialize(order)}


@app.get("/automation/status")
async def automation_status() -> dict:
    return {"live_execution_enabled": False, **automation.status()}


@app.post("/automation/enable")
async def automation_enable() -> dict:
    automation.enable()
    return {"ok": True, "live_execution_enabled": False, **automation.status()}


@app.post("/automation/disable")
async def automation_disable() -> dict:
    automation.disable()
    return {"ok": True, "live_execution_enabled": False, **automation.status()}


@app.post("/automation/reset")
async def automation_reset() -> dict:
    automation.reset()
    return {"ok": True, "live_execution_enabled": False, **automation.status()}


@app.post("/automation/config")
async def automation_config(request: AutomationConfigRequest) -> dict:
    automation.update_config(
        AutomationConfig(
            quantity=request.quantity,
            threshold_bps=request.threshold_bps,
            lookback=request.lookback,
            cooldown_seconds=request.cooldown_seconds,
        )
    )
    return {"ok": True, "live_execution_enabled": False, **automation.status()}


@app.get("/recording/status")
async def recording_status() -> dict:
    return {"enabled": settings.recording_enabled, **market_recorder.status()}


@app.get("/recording/events")
async def recording_events(
    limit: int = 1000,
    start_sequence: int | None = None,
    end_sequence: int | None = None,
) -> dict:
    limit = max(1, min(limit, settings.replay_max_events))
    ticks = market_recorder.events(
        limit=limit,
        start_sequence=start_sequence,
        end_sequence=end_sequence,
    )
    return {"count": len(ticks), "events": [tick.as_dict() for tick in ticks]}


@app.post("/recording/reset")
async def recording_reset() -> dict:
    await market_recorder.clear()
    return {"ok": True, **market_recorder.status()}


@app.post("/replay/run")
async def replay_run(request: ReplayRequest) -> dict:
    max_events = min(request.max_events, settings.replay_max_events)
    ticks = market_recorder.events(
        limit=max_events,
        start_sequence=request.start_sequence,
        end_sequence=request.end_sequence,
    )
    result = await replay_engine.run(ticks, speed=request.speed)
    return {"mode": "replay", "live_execution_enabled": False, **result}


@app.get("/research/dataset/status")
async def research_dataset_status() -> dict:
    return {
        "enabled": settings.research_dataset_enabled,
        **(await research_dataset.status()),
    }


@app.post("/research/run")
async def research_run(request: ResearchRequest) -> dict:
    global _latest_research
    max_events = min(request.max_events, settings.research_max_samples)
    if settings.research_dataset_enabled:
        ticks = await research_dataset.events(limit=max_events)
        source = "persistent_sampled_dataset"
    else:
        ticks = market_recorder.events(limit=min(max_events, settings.recording_max_events))
        source = "volatile_recorder_buffer"
    _latest_research = research_lab.run_suite(ticks, train_fraction=request.train_fraction)
    _latest_research["run_at_ms"] = int(time.time() * 1000)
    _latest_research["dataset_source"] = source
    _latest_research["dataset_status"] = await research_dataset.status()
    return _latest_research


@app.get("/research/latest")
async def research_latest() -> dict:
    if _latest_research is None:
        dataset_status = await research_dataset.status()
        return {
            "mode": "research_only",
            "live_execution_enabled": False,
            "status": "not_run",
            "dataset_status": dataset_status,
            "recorded_events_available": market_recorder.status()["buffered_events"],
        }
    return _latest_research


@app.get("/live-readiness")
async def live_readiness() -> dict:
    api_permissions: dict | None = None
    api_error: str | None = None
    if _credentials_configured():
        try:
            api_permissions = await rest.api_restrictions()
        except Exception as exc:  # noqa: BLE001 - readiness must report failures, not crash
            api_error = f"{type(exc).__name__}: {exc}"

    research = _latest_research or {}
    gates = research.get("promotion_gates", {}) if isinstance(research, dict) else {}
    dataset_status = await research_dataset.status()
    checks = {
        "live_code_present": False,
        "research_dataset_persistent": bool(dataset_status.get("persistent_path_configured")),
        "research_run_exists": _latest_research is not None,
        "research_promotion_eligible": bool(research.get("promotion_eligible", False)),
        "api_reading_enabled": bool(api_permissions and api_permissions.get("enableReading")),
        "api_spot_permission_enabled": bool(
            api_permissions and api_permissions.get("enableSpotAndMarginTrading")
        ),
        "api_withdrawals_disabled": bool(
            api_permissions is not None and not api_permissions.get("enableWithdrawals")
        ),
        "api_ip_restricted": bool(api_permissions and api_permissions.get("ipRestrict")),
        "risk_kill_switch_clear": not bool(risk_engine.status()["kill_switch_engaged"]),
        "market_stream_healthy": bool(stream.connected),
        "user_stream_healthy": bool(user_stream.connected) if _credentials_configured() else False,
    }
    return {
        "mode": "readiness_only",
        "live_execution_enabled": False,
        "ready": False,
        "checks": checks,
        "research_gates": gates,
        "dataset_status": dataset_status,
        "api_error": api_error,
        "blocking_reasons": [name for name, passed in checks.items() if not passed],
        "note": (
            "This endpoint cannot enable real-money execution. A separate reviewed implementation and explicit rollout decision are required."
        ),
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
