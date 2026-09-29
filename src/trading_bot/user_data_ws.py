import asyncio
import json
import logging
import random
import time
import uuid

import websockets

from .binance_rest import BinanceRestClient
from .event_bus import EventBus, EventType
from .portfolio import PortfolioState

logger = logging.getLogger(__name__)


class BinanceUserDataStream:
    def __init__(
        self,
        ws_api_url: str,
        rest: BinanceRestClient,
        portfolio: PortfolioState,
        event_bus: EventBus,
    ) -> None:
        self.ws_api_url = ws_api_url
        self.rest = rest
        self.portfolio = portfolio
        self.event_bus = event_bus
        self._stop = asyncio.Event()
        self.connected = False
        self.reconnect_count = 0
        self.last_error: str | None = None
        self.subscription_id: int | None = None
        self.last_event_ms: int | None = None

    async def stop(self) -> None:
        self._stop.set()

    def _subscription_request(self) -> dict:
        if not self.rest.api_key:
            raise RuntimeError("BINANCE_API_KEY is required for private user stream")
        params = {
            "apiKey": self.rest.api_key,
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
        }
        params["signature"] = self.rest.websocket_signature(params)
        return {
            "id": str(uuid.uuid4()),
            "method": "userDataStream.subscribe.signature",
            "params": params,
        }

    async def run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.ws_api_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=3,
                    max_queue=2048,
                ) as ws:
                    request = self._subscription_request()
                    await ws.send(json.dumps(request))
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    response = json.loads(raw)
                    if int(response.get("status", 500)) != 200:
                        raise RuntimeError(f"user stream subscription failed: {response}")
                    result = response.get("result") or {}
                    self.subscription_id = result.get("subscriptionId")
                    self.connected = True
                    self.last_error = None
                    attempt = 0
                    self.event_bus.publish(
                        EventType.USER_STREAM_CONNECTED,
                        {"subscription_id": self.subscription_id},
                    )
                    logger.info("user_stream_connected subscription_id=%s", self.subscription_id)

                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        payload = json.loads(raw)
                        event = payload.get("event", payload)
                        event_type = event.get("e")
                        self.last_event_ms = int(time.time() * 1000)

                        if event_type == "outboundAccountPosition":
                            await self.portfolio.apply_account_position(event)
                            self.event_bus.publish(EventType.ACCOUNT_UPDATED, {"event_time": event.get("E")})
                        elif event_type == "balanceUpdate":
                            await self.portfolio.apply_balance_update(event)
                            self.event_bus.publish(
                                EventType.BALANCE_UPDATED,
                                {"asset": event.get("a"), "delta": event.get("d")},
                            )
                        elif event_type == "executionReport":
                            await self.portfolio.apply_execution_report(event)
                            status = str(event.get("X", ""))
                            mapped = {
                                "PARTIALLY_FILLED": EventType.ORDER_PARTIALLY_FILLED,
                                "FILLED": EventType.ORDER_FILLED,
                                "CANCELED": EventType.ORDER_CANCELLED,
                            }.get(status, EventType.ORDER_ACKNOWLEDGED)
                            self.event_bus.publish(
                                mapped,
                                {
                                    "symbol": event.get("s"),
                                    "order_id": event.get("i"),
                                    "client_order_id": event.get("c"),
                                    "status": status,
                                    "executed_qty": event.get("z"),
                                },
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect boundary must contain stream failures
                self.connected = False
                self.subscription_id = None
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.reconnect_count += 1
                attempt += 1
                self.event_bus.publish(
                    EventType.USER_STREAM_DISCONNECTED,
                    {"error": self.last_error, "reconnect_count": self.reconnect_count},
                )
                delay = min(30.0, (2 ** min(attempt, 5)) + random.random())
                logger.warning("user_stream_disconnected reconnect_in=%.2fs error=%s", delay, self.last_error)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    pass
            finally:
                self.connected = False
