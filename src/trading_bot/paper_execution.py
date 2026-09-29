import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal

from .event_bus import EventBus, EventType
from .models import BestBidAsk


@dataclass(slots=True)
class PaperOrder:
    order_id: int
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    limit_price: Decimal | None
    status: str
    created_at_ms: int
    filled_quantity: Decimal = Decimal(0)
    average_fill_price: Decimal = Decimal(0)
    fee_paid: Decimal = Decimal(0)


class PaperExecutor:
    """In-memory paper execution simulator. It never calls Binance order endpoints."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        symbol: str,
        starting_quote_balance: Decimal,
        fee_bps: Decimal,
        slippage_bps: Decimal,
    ) -> None:
        self.event_bus = event_bus
        self.symbol = symbol
        self.starting_quote_balance = starting_quote_balance
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self._lock = asyncio.Lock()
        self._next_order_id = 1
        self._orders: dict[int, PaperOrder] = {}
        self._open_order_ids: set[int] = set()
        self._quote_balance = starting_quote_balance
        self._base_balance = Decimal(0)
        self._realized_pnl = Decimal(0)
        self._fees_paid = Decimal(0)
        self._position_cost = Decimal(0)
        self._market_queue: asyncio.Queue | None = None
        self._runner_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._runner_task is not None:
            return
        self._market_queue = self.event_bus.subscribe(EventType.MARKET_TICK, max_queue=2048)
        self._runner_task = asyncio.create_task(self._run(), name="paper-executor")

    async def stop(self) -> None:
        if self._market_queue is not None:
            self.event_bus.unsubscribe(EventType.MARKET_TICK, self._market_queue)
        if self._runner_task is not None:
            self._runner_task.cancel()
            await asyncio.gather(self._runner_task, return_exceptions=True)
        self._runner_task = None
        self._market_queue = None

    async def _run(self) -> None:
        assert self._market_queue is not None
        while True:
            event = await self._market_queue.get()
            quote = event.payload.get("quote")
            if isinstance(quote, BestBidAsk):
                await self.on_quote(quote)

    async def submit(
        self,
        *,
        side: str,
        order_type: str,
        quantity: Decimal,
        quote: BestBidAsk,
        client_order_id: str,
        limit_price: Decimal | None = None,
    ) -> PaperOrder:
        side = side.upper().strip()
        order_type = order_type.upper().strip()
        if side not in {"BUY", "SELL"}:
            raise ValueError("paper order side must be BUY or SELL")
        if order_type not in {"MARKET", "LIMIT"}:
            raise ValueError("paper order type must be MARKET or LIMIT")
        if quantity <= 0:
            raise ValueError("paper order quantity must be positive")
        if order_type == "LIMIT" and (limit_price is None or limit_price <= 0):
            raise ValueError("limit_price is required for LIMIT paper orders")

        async with self._lock:
            order = PaperOrder(
                order_id=self._next_order_id,
                client_order_id=client_order_id,
                symbol=self.symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                limit_price=limit_price,
                status="NEW",
                created_at_ms=int(time.time() * 1000),
            )
            self._next_order_id += 1
            self._orders[order.order_id] = order
            self.event_bus.publish(EventType.ORDER_SUBMITTED, self._event_payload(order))
            if order_type == "MARKET" or self._limit_marketable(order, quote):
                await self._fill_locked(order, quote)
            else:
                self._open_order_ids.add(order.order_id)
                self.event_bus.publish(EventType.ORDER_ACKNOWLEDGED, self._event_payload(order))
            return order

    async def on_quote(self, quote: BestBidAsk) -> None:
        async with self._lock:
            for order_id in tuple(self._open_order_ids):
                order = self._orders[order_id]
                if self._limit_marketable(order, quote):
                    await self._fill_locked(order, quote)

    async def cancel(self, order_id: int) -> PaperOrder:
        async with self._lock:
            order = self._orders.get(order_id)
            if order is None:
                raise KeyError("paper order not found")
            if order_id not in self._open_order_ids:
                raise ValueError("paper order is not open")
            self._open_order_ids.remove(order_id)
            order.status = "CANCELED"
            self.event_bus.publish(EventType.ORDER_CANCELLED, self._event_payload(order))
            return order

    def _limit_marketable(self, order: PaperOrder, quote: BestBidAsk) -> bool:
        assert order.limit_price is not None
        if order.side == "BUY":
            return order.limit_price >= quote.ask_price
        return order.limit_price <= quote.bid_price

    async def _fill_locked(self, order: PaperOrder, quote: BestBidAsk) -> None:
        if order.side == "BUY":
            raw_price = quote.ask_price
            fill_price = raw_price * (Decimal(1) + self.slippage_bps / Decimal(10_000))
            notional = order.quantity * fill_price
            fee = notional * self.fee_bps / Decimal(10_000)
            if notional + fee > self._quote_balance:
                order.status = "REJECTED"
                self.event_bus.publish(
                    EventType.RISK_REJECTED,
                    {
                        **self._event_payload(order),
                        "reason": "insufficient_paper_quote_balance",
                    },
                )
                return
            self._quote_balance -= notional + fee
            self._base_balance += order.quantity
            self._position_cost += notional + fee
        else:
            if order.quantity > self._base_balance:
                order.status = "REJECTED"
                self.event_bus.publish(
                    EventType.RISK_REJECTED,
                    {
                        **self._event_payload(order),
                        "reason": "insufficient_paper_base_balance",
                    },
                )
                return
            raw_price = quote.bid_price
            fill_price = raw_price * (Decimal(1) - self.slippage_bps / Decimal(10_000))
            notional = order.quantity * fill_price
            fee = notional * self.fee_bps / Decimal(10_000)
            average_cost = self._position_cost / self._base_balance if self._base_balance else Decimal(0)
            cost_removed = average_cost * order.quantity
            proceeds = notional - fee
            self._base_balance -= order.quantity
            self._position_cost -= cost_removed
            self._quote_balance += proceeds
            self._realized_pnl += proceeds - cost_removed

        self._fees_paid += fee
        order.filled_quantity = order.quantity
        order.average_fill_price = fill_price
        order.fee_paid = fee
        order.status = "FILLED"
        self._open_order_ids.discard(order.order_id)
        self.event_bus.publish(EventType.ORDER_FILLED, self._event_payload(order))

    async def snapshot(self, mark_price: Decimal | None = None) -> dict:
        async with self._lock:
            unrealized = Decimal(0)
            equity = self._quote_balance
            if mark_price is not None:
                market_value = self._base_balance * mark_price
                unrealized = market_value - self._position_cost
                equity += market_value
            return {
                "mode": "paper",
                "symbol": self.symbol,
                "starting_quote_balance": str(self.starting_quote_balance),
                "quote_balance": str(self._quote_balance),
                "base_balance": str(self._base_balance),
                "position_cost": str(self._position_cost),
                "realized_pnl": str(self._realized_pnl),
                "unrealized_pnl": str(unrealized),
                "fees_paid": str(self._fees_paid),
                "equity": str(equity),
                "open_orders": [self._serialize(self._orders[i]) for i in sorted(self._open_order_ids)],
                "orders": [self._serialize(self._orders[i]) for i in sorted(self._orders)],
            }

    async def base_balance(self) -> Decimal:
        async with self._lock:
            return self._base_balance

    async def open_order_count(self) -> int:
        async with self._lock:
            return len(self._open_order_ids)

    def _event_payload(self, order: PaperOrder) -> dict:
        return {"paper": True, **self._serialize(order)}

    @staticmethod
    def _serialize(order: PaperOrder) -> dict:
        return {
            "order_id": order.order_id,
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "side": order.side,
            "type": order.order_type,
            "quantity": str(order.quantity),
            "limit_price": None if order.limit_price is None else str(order.limit_price),
            "status": order.status,
            "filled_quantity": str(order.filled_quantity),
            "average_fill_price": str(order.average_fill_price),
            "fee_paid": str(order.fee_paid),
            "created_at_ms": order.created_at_ms,
        }
