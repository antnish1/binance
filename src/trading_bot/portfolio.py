import asyncio
from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class Balance:
    asset: str
    free: Decimal
    locked: Decimal

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


@dataclass(slots=True, frozen=True)
class OpenOrder:
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    order_type: str
    status: str
    price: Decimal
    original_qty: Decimal
    executed_qty: Decimal


class PortfolioState:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._balances: dict[str, Balance] = {}
        self._orders: dict[int, OpenOrder] = {}
        self.last_account_update_ms: int | None = None
        self.last_order_update_ms: int | None = None
        self.last_reconcile_ms: int | None = None

    async def replace_from_account(self, account: dict, now_ms: int) -> None:
        balances: dict[str, Balance] = {}
        for item in account.get("balances", []):
            asset = str(item.get("asset", "")).upper()
            if not asset:
                continue
            balances[asset] = Balance(
                asset=asset,
                free=Decimal(str(item.get("free", "0"))),
                locked=Decimal(str(item.get("locked", "0"))),
            )
        async with self._lock:
            self._balances = balances
            self.last_reconcile_ms = now_ms

    async def replace_open_orders(self, orders: list[dict], now_ms: int) -> None:
        normalized: dict[int, OpenOrder] = {}
        for item in orders:
            order = _parse_order(item)
            normalized[order.order_id] = order
        async with self._lock:
            self._orders = normalized
            self.last_reconcile_ms = now_ms

    async def apply_account_position(self, event: dict) -> None:
        event_time = int(event.get("E", 0) or 0)
        async with self._lock:
            for item in event.get("B", []):
                asset = str(item.get("a", "")).upper()
                if not asset:
                    continue
                self._balances[asset] = Balance(
                    asset=asset,
                    free=Decimal(str(item.get("f", "0"))),
                    locked=Decimal(str(item.get("l", "0"))),
                )
            self.last_account_update_ms = event_time

    async def apply_balance_update(self, event: dict) -> None:
        asset = str(event.get("a", "")).upper()
        if not asset:
            return
        delta = Decimal(str(event.get("d", "0")))
        async with self._lock:
            current = self._balances.get(asset, Balance(asset, Decimal(0), Decimal(0)))
            self._balances[asset] = Balance(asset, current.free + delta, current.locked)
            self.last_account_update_ms = int(event.get("E", 0) or 0)

    async def apply_execution_report(self, event: dict) -> None:
        order_id = int(event["i"])
        status = str(event.get("X", ""))
        event_time = int(event.get("E", 0) or 0)
        async with self._lock:
            if status in {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH"}:
                self._orders.pop(order_id, None)
            else:
                self._orders[order_id] = OpenOrder(
                    symbol=str(event.get("s", "")),
                    order_id=order_id,
                    client_order_id=str(event.get("c", "")),
                    side=str(event.get("S", "")),
                    order_type=str(event.get("o", "")),
                    status=status,
                    price=Decimal(str(event.get("p", "0"))),
                    original_qty=Decimal(str(event.get("q", "0"))),
                    executed_qty=Decimal(str(event.get("z", "0"))),
                )
            self.last_order_update_ms = event_time

    async def snapshot(self) -> dict:
        async with self._lock:
            balances = [
                {
                    "asset": item.asset,
                    "free": str(item.free),
                    "locked": str(item.locked),
                    "total": str(item.total),
                }
                for item in sorted(self._balances.values(), key=lambda x: x.asset)
                if item.total != 0
            ]
            orders = [
                {
                    "symbol": item.symbol,
                    "order_id": item.order_id,
                    "client_order_id": item.client_order_id,
                    "side": item.side,
                    "type": item.order_type,
                    "status": item.status,
                    "price": str(item.price),
                    "original_qty": str(item.original_qty),
                    "executed_qty": str(item.executed_qty),
                }
                for item in self._orders.values()
            ]
            return {
                "balances": balances,
                "open_orders": orders,
                "last_account_update_ms": self.last_account_update_ms,
                "last_order_update_ms": self.last_order_update_ms,
                "last_reconcile_ms": self.last_reconcile_ms,
            }


def _parse_order(item: dict) -> OpenOrder:
    return OpenOrder(
        symbol=str(item.get("symbol", "")),
        order_id=int(item["orderId"]),
        client_order_id=str(item.get("clientOrderId", "")),
        side=str(item.get("side", "")),
        order_type=str(item.get("type", "")),
        status=str(item.get("status", "")),
        price=Decimal(str(item.get("price", "0"))),
        original_qty=Decimal(str(item.get("origQty", "0"))),
        executed_qty=Decimal(str(item.get("executedQty", "0"))),
    )
