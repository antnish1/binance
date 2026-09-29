# Phase 13 — Persistent Research Dataset

Phase 13 separates two data paths:

1. **Replay recorder** — high-frequency short-window data for local replay and debugging.
2. **Research dataset** — one sampled top-of-book snapshot per interval, rotated by UTC day, intended for multi-day research.

The research dataset is deliberately paper/research only. It cannot place Binance orders and does not alter the live-execution safety gate.

## Railway production setup

Attach a persistent Railway volume to the engine service and mount it at:

```text
/data
```

Then add/update these engine service variables:

```text
RESEARCH_DATASET_ENABLED=true
RESEARCH_DATASET_DIR=/data/taddy-research
RESEARCH_SAMPLE_INTERVAL_MS=1000
RESEARCH_MAX_SAMPLES=250000
```

Keep:

```text
TRADING_ENABLED=false
```

Do not enable Binance Spot order permission for this phase.

## How storage works

The engine writes one JSONL file per UTC day, for example:

```text
/data/taddy-research/BTCUSDT-2026-09-29.jsonl
/data/taddy-research/BTCUSDT-2026-09-30.jsonl
```

At the default 1-second sampling interval this is roughly 86,400 samples per day rather than persisting every book-ticker update. This keeps multi-day research practical while preserving bid, ask, quantities, event time, receive time and source sequence.

On restart the store scans the existing daily files, reloads recent samples, and continues appending to the current UTC file.

## Endpoints

```text
GET  /research/dataset/status
POST /research/run
GET  /research/latest
GET  /live-readiness
```

`/research/run` now reads from the persistent sampled dataset when enabled.

## Research diagnostics

Phase 13 expands candidate exploration to smaller diagnostic thresholds and additional lookbacks. A flat or inactive sample no longer produces a fake "winner". If no candidate generates a completed round trip in the training window, the suite reports:

```text
selection_status = NO_SIGNAL
selected_on_train = null
```

This is intentionally different from selecting the first zero-P&L candidate.

## Promotion gates

The software research gates are now stricter:

- at least 100,000 sampled observations
- at least 48 hours of source duration
- at least one active candidate in training
- selected holdout has at least 30 round trips
- selected holdout net P&L is positive after configured costs
- selected holdout max drawdown is at most 2%
- the same selected candidate remains net positive under stressed fees/slippage

Passing these gates still **does not enable real-money execution**. It only means the candidate can advance to longer forward-paper and testnet evaluation.

## Verification after Railway setup

Open:

```text
/research/dataset/status
```

Production should eventually show:

```json
{
  "persistent_path_configured": true,
  "directory": "/data/taddy-research",
  "running": true,
  "sample_interval_ms": 1000
}
```

`/live-readiness` remains fail-closed and will report `research_dataset_persistent` as a blocker until this is configured.
