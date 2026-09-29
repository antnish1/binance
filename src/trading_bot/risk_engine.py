import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum


class RiskReason(StrEnum):
    APPROVED = "approved"
    KILL_SWITCH = "kill_switch"
    INVALID_ORDER = "invalid_order"
    MARKET_DATA_STALE = "market_data_stale"
    MAX_ORDER_NOTIONAL = "max_order_notional"
    MAX_POSITION_NOTIONAL = "max_position_notional"
    MAX_DAILY_LOSS = "max_daily_loss"
    MAX_OPEN_ORDERS = "max_open_orders"
    ORDER_RATE_LIMIT = "order_rate_limit"
    DUPLICATE_ORDER = "duplicate_order"


@dataclass(slots=True, frozen=True)
class RiskLimits:
    max_order_notional: Decimal
    max_position_notional: Decimal
    max_daily_loss: Decimal
    max_open_orders: int
    max_orders_per_minute: int
    market_stale_after_ms: int


@dataclass(slots=True, frozen=True)
class RiskDecision:
    approved: bool
    reason: RiskReason
    detail: str
    order_notional: Decimal
    projected_position_notional: Decimal

    def as_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reason": self.reason.value,
            "detail": self.detail,
            "order_notional": str(self.order_notional),
            "projected_position_notional": str(self.projected_position_notional),
        }


class RiskEngine:
    """Deterministic pre-trade risk gate.

    This engine contains no strategy logic and no exchange execution. It only decides
    whether a proposed order is allowed by configured hard limits.
    """

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self._kill_switch = False
        self._kill_switch_reason: str | None = None
        self._daily_realized_pnl = Decimal(0)
        self._pnl_day = self._utc_day()
        self._approved_order_times_ms: deque[int] = deque()
        self._approved_client_order_ids: set[str] = set()

    @staticmethod
    def _utc_day() -> date:
        return datetime.now(UTC).date()

    def _roll_day_if_needed(self) -> None:
        current = self._utc_day()
        if current != self._pnl_day:
            self._pnl_day = current
            self._daily_realized_pnl = Decimal(0)
            self._approved_order_times_ms.clear()
            self._approved_client_order_ids.clear()

    def engage_kill_switch(self, reason: str) -> None:
        self._kill_switch = True
        self._kill_switch_reason = reason.strip() or "manual"

    def release_kill_switch(self) -> None:
        self._kill_switch = False
        self._kill_switch_reason = None

    def set_daily_realized_pnl(self, pnl: Decimal) -> None:
        self._roll_day_if_needed()
        self._daily_realized_pnl = pnl

    def evaluate(
        self,
        *,
        side: str,
        quantity: Decimal,
        price: Decimal,
        market_age_ms: int | None,
        open_orders_count: int,
        current_position_notional: Decimal,
        client_order_id: str | None = None,
        consume: bool = False,
        now_ms: int | None = None,
    ) -> RiskDecision:
        self._roll_day_if_needed()
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        side = side.upper().strip()
        client_order_id = (client_order_id or "").strip()
        order_notional = quantity * price
        if side == "BUY":
            projected = current_position_notional + order_notional
        elif side == "SELL":
            projected = max(Decimal(0), current_position_notional - order_notional)
        else:
            projected = current_position_notional

        def reject(reason: RiskReason, detail: str) -> RiskDecision:
            return RiskDecision(False, reason, detail, order_notional, projected)

        if self._kill_switch:
            return reject(
                RiskReason.KILL_SWITCH,
                f"kill switch engaged: {self._kill_switch_reason or 'manual'}",
            )
        if side not in {"BUY", "SELL"} or quantity <= 0 or price <= 0:
            return reject(RiskReason.INVALID_ORDER, "side, quantity, or price is invalid")
        if market_age_ms is None or market_age_ms > self.limits.market_stale_after_ms:
            return reject(RiskReason.MARKET_DATA_STALE, "market data is stale or unavailable")
        if order_notional > self.limits.max_order_notional:
            return reject(
                RiskReason.MAX_ORDER_NOTIONAL,
                f"order notional exceeds {self.limits.max_order_notional}",
            )
        if projected > self.limits.max_position_notional:
            return reject(
                RiskReason.MAX_POSITION_NOTIONAL,
                f"projected position exceeds {self.limits.max_position_notional}",
            )
        if self._daily_realized_pnl <= -self.limits.max_daily_loss:
            return reject(
                RiskReason.MAX_DAILY_LOSS,
                f"daily realized loss limit reached: {self._daily_realized_pnl}",
            )
        if open_orders_count >= self.limits.max_open_orders:
            return reject(
                RiskReason.MAX_OPEN_ORDERS,
                f"open order count reached {self.limits.max_open_orders}",
            )
        if client_order_id and client_order_id in self._approved_client_order_ids:
            return reject(RiskReason.DUPLICATE_ORDER, "client order id was already approved")

        cutoff = now_ms - 60_000
        while self._approved_order_times_ms and self._approved_order_times_ms[0] <= cutoff:
            self._approved_order_times_ms.popleft()
        if len(self._approved_order_times_ms) >= self.limits.max_orders_per_minute:
            return reject(
                RiskReason.ORDER_RATE_LIMIT,
                f"order rate reached {self.limits.max_orders_per_minute} per minute",
            )

        if consume:
            self._approved_order_times_ms.append(now_ms)
            if client_order_id:
                self._approved_client_order_ids.add(client_order_id)

        return RiskDecision(
            True,
            RiskReason.APPROVED,
            "proposal is within configured hard limits",
            order_notional,
            projected,
        )

    def status(self) -> dict:
        self._roll_day_if_needed()
        return {
            "kill_switch_engaged": self._kill_switch,
            "kill_switch_reason": self._kill_switch_reason,
            "daily_realized_pnl": str(self._daily_realized_pnl),
            "pnl_day_utc": self._pnl_day.isoformat(),
            "approved_orders_last_minute": len(self._approved_order_times_ms),
            "limits": {
                "max_order_notional": str(self.limits.max_order_notional),
                "max_position_notional": str(self.limits.max_position_notional),
                "max_daily_loss": str(self.limits.max_daily_loss),
                "max_open_orders": self.limits.max_open_orders,
                "max_orders_per_minute": self.limits.max_orders_per_minute,
                "market_stale_after_ms": self.limits.market_stale_after_ms,
            },
        }
