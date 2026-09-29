import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from .event_bus import EventBus, EventType
from .models import BestBidAsk
from .paper_execution import PaperExecutor
from .risk_engine import RiskEngine


@dataclass(slots=True)
class AutomationConfig:
    quantity: Decimal
    threshold_bps: Decimal
    lookback: int
    cooldown_seconds: int


class MeanReversionAutomation:
    """Deterministic paper-only automation driven by live MARKET_TICK events."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        paper_executor: PaperExecutor,
        risk_engine: RiskEngine,
        config: AutomationConfig,
    ) -> None:
        self.event_bus = event_bus
        self.paper_executor = paper_executor
        self.risk_engine = risk_engine
        self.config = config
        self._enabled = False
        self._prices: deque[Decimal] = deque(maxlen=max(config.lookback, 2))
        self._market_queue: asyncio.Queue | None = None
        self._runner_task: asyncio.Task | None = None
        self._last_action_ms: int | None = None
        self._last_signal: str | None = None
        self._last_decision: str = "idle"
        self._last_deviation_bps: Decimal | None = None
        self._signals = 0
        self._approved = 0
        self._rejected = 0
        self._filled = 0

    async def start(self) -> None:
        if self._runner_task is not None:
            return
        self._market_queue = self.event_bus.subscribe(EventType.MARKET_TICK, max_queue=2048)
        self._runner_task = asyncio.create_task(self._run(), name="mean-reversion-automation")

    async def stop(self) -> None:
        if self._market_queue is not None:
            self.event_bus.unsubscribe(EventType.MARKET_TICK, self._market_queue)
        if self._runner_task is not None:
            self._runner_task.cancel()
            await asyncio.gather(self._runner_task, return_exceptions=True)
        self._runner_task = None
        self._market_queue = None

    def enable(self) -> None:
        self._enabled = True
        self._last_decision = "warming_up"

    def disable(self) -> None:
        self._enabled = False
        self._last_decision = "disabled"

    def reset(self) -> None:
        self._prices = deque(maxlen=max(self.config.lookback, 2))
        self._last_action_ms = None
        self._last_signal = None
        self._last_decision = "idle" if not self._enabled else "warming_up"
        self._last_deviation_bps = None
        self._signals = 0
        self._approved = 0
        self._rejected = 0
        self._filled = 0

    def update_config(self, config: AutomationConfig) -> None:
        self.config = config
        previous = list(self._prices)[-config.lookback :]
        self._prices = deque(previous, maxlen=max(config.lookback, 2))
        self._last_decision = "config_updated"

    async def _run(self) -> None:
        assert self._market_queue is not None
        while True:
            event = await self._market_queue.get()
            quote = event.payload.get("quote")
            if isinstance(quote, BestBidAsk):
                await self.on_quote(quote)

    async def on_quote(self, quote: BestBidAsk) -> None:
        midpoint = quote.midpoint
        self._prices.append(midpoint)
        if not self._enabled:
            self._last_decision = "disabled"
            return

        if len(self._prices) < self.config.lookback:
            self._last_decision = "warming_up"
            return

        now_ms = int(time.time() * 1000)
        if self._last_action_ms is not None:
            cooldown_ms = self.config.cooldown_seconds * 1000
            if now_ms - self._last_action_ms < cooldown_ms:
                self._last_decision = "cooldown"
                return

        baseline = sum(self._prices, Decimal(0)) / Decimal(len(self._prices))
        if baseline <= 0:
            self._last_decision = "invalid_baseline"
            return
        deviation_bps = (midpoint - baseline) / baseline * Decimal(10_000)
        self._last_deviation_bps = deviation_bps

        base_balance = await self.paper_executor.base_balance()
        open_orders = await self.paper_executor.open_order_count()
        if open_orders:
            self._last_decision = "open_order_exists"
            return

        side: str | None = None
        quantity = self.config.quantity
        if base_balance < quantity and deviation_bps <= -self.config.threshold_bps:
            side = "BUY"
        elif base_balance >= quantity and deviation_bps >= self.config.threshold_bps:
            side = "SELL"

        if side is None:
            self._last_decision = "observe"
            return

        self._signals += 1
        self._last_signal = side
        client_order_id = f"auto-{uuid.uuid4().hex[:20]}"
        risk_price = quote.ask_price if side == "BUY" else quote.bid_price
        paper_snapshot = await self.paper_executor.snapshot(midpoint)
        self.risk_engine.set_daily_realized_pnl(Decimal(paper_snapshot["realized_pnl"]))
        current_position_notional = base_balance * risk_price
        market_age_ms = max(0, now_ms - quote.received_time_ms)

        self.event_bus.publish(
            EventType.SIGNAL_CREATED,
            {
                "paper": True,
                "automation": "mean_reversion",
                "side": side,
                "quantity": str(quantity),
                "deviation_bps": str(deviation_bps),
                "baseline": str(baseline),
                "midpoint": str(midpoint),
            },
        )

        decision = self.risk_engine.evaluate(
            side=side,
            quantity=quantity,
            price=risk_price,
            market_age_ms=market_age_ms,
            open_orders_count=open_orders,
            current_position_notional=current_position_notional,
            client_order_id=client_order_id,
            consume=True,
        )
        self.event_bus.publish(
            EventType.RISK_APPROVED if decision.approved else EventType.RISK_REJECTED,
            {
                "paper": True,
                "automation": "mean_reversion",
                "client_order_id": client_order_id,
                "side": side,
                "quantity": str(quantity),
                "price": str(risk_price),
                "reason": decision.reason.value,
            },
        )
        if not decision.approved:
            self._rejected += 1
            self._last_decision = f"risk_rejected:{decision.reason.value}"
            return

        self._approved += 1
        order = await self.paper_executor.submit(
            side=side,
            order_type="MARKET",
            quantity=quantity,
            quote=quote,
            client_order_id=client_order_id,
        )
        self._last_action_ms = now_ms
        if order.status == "FILLED":
            self._filled += 1
            self._last_decision = f"filled_{side.lower()}"
        else:
            self._last_decision = f"order_{order.status.lower()}"

    def status(self) -> dict:
        return {
            "name": "mean_reversion",
            "mode": "paper_only",
            "enabled": self._enabled,
            "state": self._last_decision,
            "last_signal": self._last_signal,
            "last_action_ms": self._last_action_ms,
            "last_deviation_bps": None
            if self._last_deviation_bps is None
            else str(self._last_deviation_bps),
            "samples": len(self._prices),
            "signals": self._signals,
            "approved": self._approved,
            "rejected": self._rejected,
            "filled": self._filled,
            "config": {
                "quantity": str(self.config.quantity),
                "threshold_bps": str(self.config.threshold_bps),
                "lookback": self.config.lookback,
                "cooldown_seconds": self.config.cooldown_seconds,
            },
        }
