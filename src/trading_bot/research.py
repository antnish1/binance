from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Literal

from .recording import RecordedTick

StrategyKind = Literal["mean_reversion", "momentum"]


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    name: str
    kind: StrategyKind
    lookback: int
    entry_threshold_bps: Decimal
    exit_threshold_bps: Decimal = Decimal(0)


@dataclass(slots=True)
class BacktestResult:
    name: str
    kind: str
    lookback: int
    entry_threshold_bps: str
    exit_threshold_bps: str
    ticks: int
    source_duration_ms: int
    starting_equity: str
    ending_equity: str
    net_pnl: str
    return_pct: str
    max_drawdown: str
    max_drawdown_pct: str
    fees_paid: str
    turnover: str
    round_trips: int
    wins: int
    losses: int
    win_rate_pct: str
    forced_exit: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class StrategyResearchLab:
    """Deterministic research harness over recorded top-of-book data.

    This class is deliberately isolated from the live event bus and from exchange
    order clients. It only consumes immutable RecordedTick data and returns metrics.
    """

    def __init__(
        self,
        *,
        starting_quote_balance: Decimal,
        quantity: Decimal,
        fee_bps: Decimal,
        slippage_bps: Decimal,
    ) -> None:
        if starting_quote_balance <= 0:
            raise ValueError("starting_quote_balance must be positive")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if fee_bps < 0 or slippage_bps < 0:
            raise ValueError("fee_bps and slippage_bps must be non-negative")
        self.starting_quote_balance = starting_quote_balance
        self.quantity = quantity
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    @staticmethod
    def default_candidates() -> list[StrategyCandidate]:
        candidates: list[StrategyCandidate] = []
        for lookback in (50, 100):
            for threshold in (Decimal(5), Decimal(10), Decimal(20), Decimal(30)):
                candidates.append(
                    StrategyCandidate(
                        name=f"mean_reversion_l{lookback}_t{threshold}",
                        kind="mean_reversion",
                        lookback=lookback,
                        entry_threshold_bps=threshold,
                    )
                )
            for threshold in (Decimal(5), Decimal(10), Decimal(20)):
                candidates.append(
                    StrategyCandidate(
                        name=f"momentum_l{lookback}_t{threshold}",
                        kind="momentum",
                        lookback=lookback,
                        entry_threshold_bps=threshold,
                    )
                )
        return candidates

    def run_suite(
        self,
        ticks: list[RecordedTick],
        *,
        train_fraction: Decimal = Decimal("0.70"),
        candidates: list[StrategyCandidate] | None = None,
    ) -> dict[str, Any]:
        if not ticks:
            return self._empty_suite()
        if not (Decimal("0.50") <= train_fraction <= Decimal("0.90")):
            raise ValueError("train_fraction must be between 0.50 and 0.90")

        ordered = sorted(ticks, key=lambda tick: tick.sequence)
        split = int(Decimal(len(ordered)) * train_fraction)
        split = min(max(split, 1), len(ordered) - 1) if len(ordered) > 1 else 1
        train = ordered[:split]
        holdout = ordered[split:]
        suite = candidates or self.default_candidates()

        train_results = [self.run_candidate(train, candidate) for candidate in suite]
        selected = self._select_candidate(train_results)
        selected_candidate = next((item for item in suite if item.name == selected.name), suite[0])
        holdout_results = [self.run_candidate(holdout, candidate) for candidate in suite] if holdout else []
        selected_holdout = next(
            (item for item in holdout_results if item.name == selected_candidate.name),
            None,
        )

        stressed_lab = StrategyResearchLab(
            starting_quote_balance=self.starting_quote_balance,
            quantity=self.quantity,
            fee_bps=self.fee_bps * Decimal("1.5"),
            slippage_bps=self.slippage_bps * Decimal(2),
        )
        stressed_holdout = (
            stressed_lab.run_candidate(holdout, selected_candidate) if holdout else None
        )

        source_duration_ms = max(0, ordered[-1].event_time_ms - ordered[0].event_time_ms)
        gates = self._promotion_gates(
            total_ticks=len(ordered),
            source_duration_ms=source_duration_ms,
            holdout=selected_holdout,
            stressed=stressed_holdout,
        )
        return {
            "mode": "research_only",
            "live_execution_enabled": False,
            "ticks": len(ordered),
            "source_duration_ms": source_duration_ms,
            "train_fraction": str(train_fraction),
            "train_ticks": len(train),
            "holdout_ticks": len(holdout),
            "cost_model": {
                "fee_bps_per_side": str(self.fee_bps),
                "slippage_bps_per_side": str(self.slippage_bps),
                "quantity": str(self.quantity),
                "starting_quote_balance": str(self.starting_quote_balance),
            },
            "train_results": [item.as_dict() for item in train_results],
            "holdout_results": [item.as_dict() for item in holdout_results],
            "selected_on_train": selected.as_dict(),
            "selected_holdout": None if selected_holdout is None else selected_holdout.as_dict(),
            "stressed_selected_holdout": (
                None if stressed_holdout is None else stressed_holdout.as_dict()
            ),
            "promotion_gates": gates,
            "promotion_eligible": all(gates.values()),
            "note": (
                "Promotion eligibility is only a research gate. It never enables real-money execution."
            ),
        }

    def run_candidate(
        self,
        ticks: list[RecordedTick],
        candidate: StrategyCandidate,
    ) -> BacktestResult:
        if candidate.lookback < 2:
            raise ValueError("candidate lookback must be >= 2")
        if candidate.entry_threshold_bps <= 0:
            raise ValueError("entry threshold must be positive")
        if not ticks:
            return self._empty_result(candidate)

        quote_balance = self.starting_quote_balance
        base_balance = Decimal(0)
        entry_cost = Decimal(0)
        fees_paid = Decimal(0)
        turnover = Decimal(0)
        round_trips = 0
        wins = 0
        losses = 0
        peak_equity = self.starting_quote_balance
        max_drawdown = Decimal(0)
        prices: deque[Decimal] = deque(maxlen=candidate.lookback)
        forced_exit = False

        for tick in ticks:
            midpoint = tick.midpoint
            prices.append(midpoint)
            if len(prices) < candidate.lookback:
                peak_equity, max_drawdown = self._update_drawdown(
                    quote_balance + base_balance * midpoint,
                    peak_equity,
                    max_drawdown,
                )
                continue

            signal = self._signal(candidate, prices, midpoint)
            if base_balance < self.quantity and signal == "BUY":
                fill_price = Decimal(tick.ask_price) * (
                    Decimal(1) + self.slippage_bps / Decimal(10_000)
                )
                notional = self.quantity * fill_price
                fee = notional * self.fee_bps / Decimal(10_000)
                total_cost = notional + fee
                if total_cost <= quote_balance:
                    quote_balance -= total_cost
                    base_balance += self.quantity
                    entry_cost += total_cost
                    fees_paid += fee
                    turnover += notional
            elif base_balance >= self.quantity and signal == "SELL":
                quote_balance, base_balance, entry_cost, fees_paid, turnover, outcome = (
                    self._sell(
                        tick=tick,
                        quote_balance=quote_balance,
                        base_balance=base_balance,
                        entry_cost=entry_cost,
                        fees_paid=fees_paid,
                        turnover=turnover,
                    )
                )
                round_trips += 1
                if outcome > 0:
                    wins += 1
                else:
                    losses += 1

            equity = quote_balance + base_balance * midpoint
            peak_equity, max_drawdown = self._update_drawdown(
                equity, peak_equity, max_drawdown
            )

        if base_balance >= self.quantity:
            forced_exit = True
            last = ticks[-1]
            quote_balance, base_balance, entry_cost, fees_paid, turnover, outcome = self._sell(
                tick=last,
                quote_balance=quote_balance,
                base_balance=base_balance,
                entry_cost=entry_cost,
                fees_paid=fees_paid,
                turnover=turnover,
            )
            round_trips += 1
            if outcome > 0:
                wins += 1
            else:
                losses += 1

        ending_equity = quote_balance
        net_pnl = ending_equity - self.starting_quote_balance
        return_pct = net_pnl / self.starting_quote_balance * Decimal(100)
        drawdown_pct = max_drawdown / peak_equity * Decimal(100) if peak_equity > 0 else Decimal(0)
        win_rate = (
            Decimal(wins) / Decimal(round_trips) * Decimal(100)
            if round_trips
            else Decimal(0)
        )
        source_duration_ms = max(0, ticks[-1].event_time_ms - ticks[0].event_time_ms)
        return BacktestResult(
            name=candidate.name,
            kind=candidate.kind,
            lookback=candidate.lookback,
            entry_threshold_bps=str(candidate.entry_threshold_bps),
            exit_threshold_bps=str(candidate.exit_threshold_bps),
            ticks=len(ticks),
            source_duration_ms=source_duration_ms,
            starting_equity=str(self.starting_quote_balance),
            ending_equity=str(ending_equity),
            net_pnl=str(net_pnl),
            return_pct=str(return_pct),
            max_drawdown=str(max_drawdown),
            max_drawdown_pct=str(drawdown_pct),
            fees_paid=str(fees_paid),
            turnover=str(turnover),
            round_trips=round_trips,
            wins=wins,
            losses=losses,
            win_rate_pct=str(win_rate),
            forced_exit=forced_exit,
        )

    def _signal(
        self,
        candidate: StrategyCandidate,
        prices: deque[Decimal],
        midpoint: Decimal,
    ) -> str | None:
        if candidate.kind == "mean_reversion":
            baseline = sum(prices, Decimal(0)) / Decimal(len(prices))
            if baseline <= 0:
                return None
            deviation = (midpoint - baseline) / baseline * Decimal(10_000)
            if deviation <= -candidate.entry_threshold_bps:
                return "BUY"
            if deviation >= candidate.exit_threshold_bps:
                return "SELL"
            return None

        reference = prices[0]
        if reference <= 0:
            return None
        move = (midpoint - reference) / reference * Decimal(10_000)
        if move >= candidate.entry_threshold_bps:
            return "BUY"
        if move <= candidate.exit_threshold_bps:
            return "SELL"
        return None

    def _sell(
        self,
        *,
        tick: RecordedTick,
        quote_balance: Decimal,
        base_balance: Decimal,
        entry_cost: Decimal,
        fees_paid: Decimal,
        turnover: Decimal,
    ) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        fill_price = Decimal(tick.bid_price) * (
            Decimal(1) - self.slippage_bps / Decimal(10_000)
        )
        notional = self.quantity * fill_price
        fee = notional * self.fee_bps / Decimal(10_000)
        proceeds = notional - fee
        average_cost = entry_cost / base_balance if base_balance else Decimal(0)
        removed_cost = average_cost * self.quantity
        outcome = proceeds - removed_cost
        return (
            quote_balance + proceeds,
            base_balance - self.quantity,
            entry_cost - removed_cost,
            fees_paid + fee,
            turnover + notional,
            outcome,
        )

    @staticmethod
    def _update_drawdown(
        equity: Decimal,
        peak_equity: Decimal,
        max_drawdown: Decimal,
    ) -> tuple[Decimal, Decimal]:
        peak_equity = max(peak_equity, equity)
        drawdown = peak_equity - equity
        return peak_equity, max(max_drawdown, drawdown)

    @staticmethod
    def _select_candidate(results: list[BacktestResult]) -> BacktestResult:
        if not results:
            raise ValueError("candidate result list cannot be empty")

        def score(item: BacktestResult) -> tuple[Decimal, int, Decimal]:
            return (
                Decimal(item.net_pnl),
                item.round_trips,
                -Decimal(item.max_drawdown),
            )

        return max(results, key=score)

    @staticmethod
    def _promotion_gates(
        *,
        total_ticks: int,
        source_duration_ms: int,
        holdout: BacktestResult | None,
        stressed: BacktestResult | None,
    ) -> dict[str, bool]:
        return {
            "at_least_50000_ticks": total_ticks >= 50_000,
            "at_least_6_hours_source_data": source_duration_ms >= 6 * 60 * 60 * 1000,
            "holdout_has_20_round_trips": bool(holdout and holdout.round_trips >= 20),
            "holdout_net_positive": bool(holdout and Decimal(holdout.net_pnl) > 0),
            "holdout_drawdown_below_2pct": bool(
                holdout and Decimal(holdout.max_drawdown_pct) <= Decimal(2)
            ),
            "stressed_costs_net_positive": bool(stressed and Decimal(stressed.net_pnl) > 0),
        }

    def _empty_suite(self) -> dict[str, Any]:
        return {
            "mode": "research_only",
            "live_execution_enabled": False,
            "ticks": 0,
            "source_duration_ms": 0,
            "train_results": [],
            "holdout_results": [],
            "selected_on_train": None,
            "selected_holdout": None,
            "stressed_selected_holdout": None,
            "promotion_gates": {
                "at_least_50000_ticks": False,
                "at_least_6_hours_source_data": False,
                "holdout_has_20_round_trips": False,
                "holdout_net_positive": False,
                "holdout_drawdown_below_2pct": False,
                "stressed_costs_net_positive": False,
            },
            "promotion_eligible": False,
            "note": "No recorded data is available yet.",
        }

    def _empty_result(self, candidate: StrategyCandidate) -> BacktestResult:
        return BacktestResult(
            name=candidate.name,
            kind=candidate.kind,
            lookback=candidate.lookback,
            entry_threshold_bps=str(candidate.entry_threshold_bps),
            exit_threshold_bps=str(candidate.exit_threshold_bps),
            ticks=0,
            source_duration_ms=0,
            starting_equity=str(self.starting_quote_balance),
            ending_equity=str(self.starting_quote_balance),
            net_pnl="0",
            return_pct="0",
            max_drawdown="0",
            max_drawdown_pct="0",
            fees_paid="0",
            turnover="0",
            round_trips=0,
            wins=0,
            losses=0,
            win_rate_pct="0",
            forced_exit=False,
        )
