# Taddy: staged migration toward real-money execution

This document defines engineering and validation gates only. It does not imply expected profitability and does not authorize real-money execution.

## Current state

- Live market data: enabled
- Private account stream: enabled
- Paper executor: enabled
- Deterministic risk engine: enabled
- Strategy research lab: enabled
- Automated paper strategy: available but disabled by default
- Real-money order placement code: **not present**
- `TRADING_ENABLED=true`: **still hard blocked**

## Stage 1 — Research data quality

Before considering any exchange test environment:

1. Move recorder persistence off ephemeral `/tmp` storage.
2. Collect continuous BTCUSDT data across multiple sessions and volatility regimes.
3. Record reconnects, gaps and latency so bad datasets can be excluded.
4. Keep train and holdout samples strictly separated.
5. Run cost sensitivity with fee and slippage assumptions above observed defaults.

The built-in research gate currently requires at least 50,000 ticks and at least six hours of source duration, but these are only minimum software gates. A serious decision should use materially longer datasets.

## Stage 2 — Candidate selection

For each candidate:

- evaluate on a training segment;
- freeze the selected parameters;
- evaluate the frozen candidate on an untouched holdout segment;
- report net P&L after fees and slippage;
- report maximum drawdown, round trips, win rate and turnover;
- repeat with stressed costs;
- reject strategies that depend on one short market regime or a tiny number of fills.

No parameter should be changed after seeing holdout results without creating a new holdout period.

## Stage 3 — Forward paper soak

Run the selected candidate continuously in paper mode using live Binance market data.

Required operational checks:

- no duplicate submissions;
- no stale-data actions;
- reconnects do not create unexpected actions;
- user-data and market streams recover cleanly;
- kill switch works;
- order-rate limits are respected;
- P&L and position reconciliation remain consistent;
- strategy remains stable across several days rather than a short favorable window.

## Stage 4 — Binance Spot Testnet

Add a separate execution adapter for Binance Spot Testnet. It must use separate testnet credentials and endpoints. Production credentials must never be reused.

The testnet stage validates exchange mechanics rather than profitability:

- signature generation;
- timestamp / recvWindow handling;
- exchange filters such as LOT_SIZE, PRICE_FILTER and minimum notional;
- order acknowledgements and fills;
- cancel/replace behavior;
- user-data reconciliation;
- request and order-rate limit handling;
- restart recovery and idempotent client order IDs.

## Stage 5 — Shadow mode against production

Before any production order is permitted, run the production strategy and risk path in shadow mode:

- consume real production market data;
- compute signals and intended orders;
- run the exact production risk checks;
- log the order that *would* have been sent;
- send **no** order to Binance.

Compare shadow intent with the paper executor for several sessions. Any divergence must be explained before progressing.

## Stage 6 — Production readiness gates

The `/live-readiness` endpoint is intentionally fail-closed. It checks the current environment but cannot enable execution.

Minimum security requirements before a production implementation is even reviewed:

- dedicated bot API key;
- reading enabled;
- Spot order permission enabled only when rollout is approved;
- withdrawals disabled;
- IP restriction enabled and bound to a stable outbound IP;
- no margin/futures permissions unless separately required;
- hard global kill switch;
- stale market protection;
- daily loss cap;
- per-order notional cap;
- total position cap;
- order-frequency cap;
- exchange filter validation before submission;
- idempotent client order IDs;
- restart reconciliation before new orders are allowed.

## Stage 7 — Micro-live rollout

Only after the prior stages pass should a production order adapter be implemented and code-reviewed.

Initial rollout principles:

- one symbol only;
- minimal permitted notional;
- one position at a time;
- no leverage;
- no withdrawals;
- manual arming required after every deployment/restart;
- automatic disarm on stale data, reconciliation error, user-stream failure, loss-limit breach or unknown order state;
- no automatic size increases.

Scaling must be a separate decision based on forward evidence, not a consequence of the strategy making money for a short period.

## What Phase 12 adds

Phase 12 introduces an isolated research engine that cannot place exchange orders. It evaluates mean-reversion and momentum candidates using recorded top-of-book ticks, including:

- train / holdout split;
- fee and slippage cost model;
- stressed cost test;
- ending equity and net P&L;
- maximum drawdown;
- round trips and win rate;
- turnover;
- explicit promotion gates.

Endpoints:

- `POST /research/run`
- `GET /research/latest`
- `GET /live-readiness`

Passing a research gate never enables live execution.
