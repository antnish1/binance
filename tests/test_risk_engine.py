from decimal import Decimal

from trading_bot.risk_engine import RiskEngine, RiskLimits, RiskReason


def make_engine() -> RiskEngine:
    return RiskEngine(
        RiskLimits(
            max_order_notional=Decimal(100),
            max_position_notional=Decimal(250),
            max_daily_loss=Decimal(50),
            max_open_orders=3,
            max_orders_per_minute=2,
            market_stale_after_ms=1000,
        )
    )


def test_approves_order_inside_limits() -> None:
    decision = make_engine().evaluate(
        side="BUY",
        quantity=Decimal("0.5"),
        price=Decimal(100),
        market_age_ms=10,
        open_orders_count=0,
        current_position_notional=Decimal(20),
    )
    assert decision.approved is True
    assert decision.reason == RiskReason.APPROVED
    assert decision.order_notional == Decimal(50)
    assert decision.projected_position_notional == Decimal(70)


def test_rejects_stale_market_and_oversized_order() -> None:
    engine = make_engine()
    stale = engine.evaluate(
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(10),
        market_age_ms=1001,
        open_orders_count=0,
        current_position_notional=Decimal(0),
    )
    assert stale.reason == RiskReason.MARKET_DATA_STALE

    oversized = engine.evaluate(
        side="BUY",
        quantity=Decimal(2),
        price=Decimal(60),
        market_age_ms=1,
        open_orders_count=0,
        current_position_notional=Decimal(0),
    )
    assert oversized.reason == RiskReason.MAX_ORDER_NOTIONAL


def test_rejects_position_daily_loss_and_open_order_limits() -> None:
    engine = make_engine()
    position = engine.evaluate(
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(60),
        market_age_ms=1,
        open_orders_count=0,
        current_position_notional=Decimal(200),
    )
    assert position.reason == RiskReason.MAX_POSITION_NOTIONAL

    engine.set_daily_realized_pnl(Decimal(-50))
    loss = engine.evaluate(
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(10),
        market_age_ms=1,
        open_orders_count=0,
        current_position_notional=Decimal(0),
    )
    assert loss.reason == RiskReason.MAX_DAILY_LOSS

    engine.set_daily_realized_pnl(Decimal(0))
    open_orders = engine.evaluate(
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(10),
        market_age_ms=1,
        open_orders_count=3,
        current_position_notional=Decimal(0),
    )
    assert open_orders.reason == RiskReason.MAX_OPEN_ORDERS


def test_kill_switch_duplicate_and_rate_limit() -> None:
    engine = make_engine()
    engine.engage_kill_switch("operator")
    killed = engine.evaluate(
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(10),
        market_age_ms=1,
        open_orders_count=0,
        current_position_notional=Decimal(0),
    )
    assert killed.reason == RiskReason.KILL_SWITCH

    engine.release_kill_switch()
    first = engine.evaluate(
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(10),
        market_age_ms=1,
        open_orders_count=0,
        current_position_notional=Decimal(0),
        client_order_id="same",
        consume=True,
        now_ms=1_000_000,
    )
    assert first.approved is True

    duplicate = engine.evaluate(
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(10),
        market_age_ms=1,
        open_orders_count=0,
        current_position_notional=Decimal(0),
        client_order_id="same",
        now_ms=1_000_001,
    )
    assert duplicate.reason == RiskReason.DUPLICATE_ORDER

    second = engine.evaluate(
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(10),
        market_age_ms=1,
        open_orders_count=0,
        current_position_notional=Decimal(0),
        client_order_id="two",
        consume=True,
        now_ms=1_000_002,
    )
    assert second.approved is True

    limited = engine.evaluate(
        side="BUY",
        quantity=Decimal(1),
        price=Decimal(10),
        market_age_ms=1,
        open_orders_count=0,
        current_position_notional=Decimal(0),
        client_order_id="three",
        now_ms=1_000_003,
    )
    assert limited.reason == RiskReason.ORDER_RATE_LIMIT
