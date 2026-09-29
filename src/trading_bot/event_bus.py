import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    MARKET_TICK = "market_tick"
    ORDERBOOK_UPDATE = "orderbook_update"
    SIGNAL_CREATED = "signal_created"
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_ACKNOWLEDGED = "order_acknowledged"
    ORDER_PARTIALLY_FILLED = "order_partially_filled"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    CONNECTION_LOST = "connection_lost"
    CONNECTION_RESTORED = "connection_restored"


@dataclass(slots=True, frozen=True)
class Event:
    sequence: int
    event_type: EventType
    wall_time_ms: int
    monotonic_ns: int
    payload: dict[str, Any]


class EventBus:
    """In-process, non-blocking pub/sub bus for the trading hot path.

    Publishing never waits for consumers. Each subscriber receives its own bounded
    asyncio queue. If a consumer falls behind and its queue is full, the event is
    dropped for that consumer and recorded in bus statistics rather than blocking
    market-data processing.
    """

    def __init__(self) -> None:
        self._sequence = 0
        self._subscribers: dict[EventType, set[asyncio.Queue[Event]]] = defaultdict(set)
        self._published: dict[EventType, int] = defaultdict(int)
        self._dropped: dict[EventType, int] = defaultdict(int)

    def subscribe(self, event_type: EventType, *, max_queue: int = 1024) -> asyncio.Queue[Event]:
        if max_queue < 1:
            raise ValueError("max_queue must be at least 1")
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue)
        self._subscribers[event_type].add(queue)
        return queue

    def unsubscribe(self, event_type: EventType, queue: asyncio.Queue[Event]) -> None:
        subscribers = self._subscribers.get(event_type)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(event_type, None)

    def publish(self, event_type: EventType, payload: dict[str, Any]) -> Event:
        self._sequence += 1
        event = Event(
            sequence=self._sequence,
            event_type=event_type,
            wall_time_ms=int(time.time() * 1000),
            monotonic_ns=time.monotonic_ns(),
            payload=payload,
        )
        self._published[event_type] += 1

        for queue in tuple(self._subscribers.get(event_type, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._dropped[event_type] += 1

        return event

    def stats(self) -> dict[str, Any]:
        event_types = set(self._published) | set(self._dropped) | set(self._subscribers)
        return {
            "last_sequence": self._sequence,
            "published": {event_type.value: self._published[event_type] for event_type in event_types},
            "dropped": {event_type.value: self._dropped[event_type] for event_type in event_types},
            "subscribers": {
                event_type.value: len(self._subscribers[event_type]) for event_type in event_types
            },
        }
