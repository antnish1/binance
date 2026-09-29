from decimal import Decimal

from trading_bot.recording import RecordedTick
from trading_bot.research import StrategyCandidate, StrategyResearchLab


def make_ticks(prices: list[Decimal], *, start_sequence: int = 1) -> list[RecordedTick]:
    ticks: list[RecordedTick] = []
    for index, midpoint in enumerate(prices):
        spread = Decimal("0.01")
        bid = midpoint - spread / Decimal(2)
        ask = midpoint + spread / Decimal(2)
        event_time = 1_700_000_000_000 + index * 1000
        ticks.append(
            RecordedTick(
                sequence=start_sequence + index,
                symbol="BTCUSDT",
                bid_price=str(bid),
                bid_qty="1",
                ask_price=str(ask),
                ask_qty="1",
                event_time_ms=event_time,
                received_time_ms=event_time,
                recorded_time_ms=event_time,
            )
        )
    return ticks


def test_mean_reversion_candidate_round_trip() -> None:
    prices = [Decimal(100)] * 5 + [Decimal(99)] * 3 + [Decimal("100.5")] * 4
    lab = StrategyResearchLab(
        starting_quote_balance=Decimal(1000),
        quantity=Decimal(1),
        fee_bps=Decimal(0),
        slippage_bps=Decimal(0),
    )
    candidate = StrategyCandidate(
        name="test_mr",
        kind="mean_reversion",
        lookback=5,
        entry_threshold_bps=Decimal(20),
    )

    result = lab.run_candidate(make_ticks(prices), candidate)

    assert result.round_trips >= 1
    assert Decimal(result.net_pnl) > 0
    assert result.wins >= 1


def test_suite_is_research_only_and_never_promotes_small_sample() -> None:
    prices = [Decimal(100) + Decimal(index % 10) / Decimal(100) for index in range(500)]
    lab = StrategyResearchLab(
        starting_quote_balance=Decimal(1000),
        quantity=Decimal("0.1"),
        fee_bps=Decimal(10),
        slippage_bps=Decimal(2),
    )

    result = lab.run_suite(make_ticks(prices), train_fraction=Decimal("0.70"))

    assert result["mode"] == "research_only"
    assert result["live_execution_enabled"] is False
    assert result["promotion_eligible"] is False
    assert result["promotion_gates"]["at_least_50000_ticks"] is False
    assert result["selected_on_train"] is not None


def test_stressed_cost_model_is_more_expensive() -> None:
    prices = []
    for _cycle in range(40):
        prices.extend([Decimal(100), Decimal(99), Decimal("100.5")])
    lab = StrategyResearchLab(
        starting_quote_balance=Decimal(1000),
        quantity=Decimal("0.1"),
        fee_bps=Decimal(10),
        slippage_bps=Decimal(2),
    )
    candidate = StrategyCandidate(
        name="mr",
        kind="mean_reversion",
        lookback=2,
        entry_threshold_bps=Decimal(20),
    )
    ticks = make_ticks(prices)
    base = lab.run_candidate(ticks, candidate)
    stressed = StrategyResearchLab(
        starting_quote_balance=Decimal(1000),
        quantity=Decimal("0.1"),
        fee_bps=Decimal(15),
        slippage_bps=Decimal(4),
    ).run_candidate(ticks, candidate)

    assert Decimal(stressed.fees_paid) >= Decimal(base.fees_paid)
    assert Decimal(stressed.net_pnl) <= Decimal(base.net_pnl)
