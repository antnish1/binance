# Architecture — Phase 0–3

## Cloud topology

```text
GitHub
  ├─ GitHub Actions: lint + tests + dashboard build
  ├─ Vercel: dashboard/control plane (apps/dashboard)
  └─ Railway: always-on Python trading engine
          ├─ Binance Spot REST
          └─ Binance Spot WebSocket
```

The exchange WebSocket is intentionally hosted in an always-on worker instead of a Vercel serverless function.

## Current critical path

```text
Binance Spot WebSocket
  -> bookTicker parser
  -> in-memory MarketState
  -> /market and /health APIs
```

No database, external AI service, or disk write is placed in the live market-data path.

## Safety state

- Real order submission is not implemented.
- `TRADING_ENABLED=true` causes startup failure.
- `RiskEngine` rejects every order intent.
- `DisabledExecutionEngine` raises on every submit attempt.
- Withdrawals are never required.

## Next phases

1. Typed event bus with bounded queues.
2. Local portfolio and order ledger.
3. Binance user-data WebSocket.
4. Deterministic risk policy configuration and tests.
5. Paper execution with realistic fees, slippage and partial fills.
6. Recorder/replay and deterministic backtesting.
7. Restricted Binance test environment execution.
8. Only after explicit approval: tightly limited live execution.

## Performance principles

- Keep market state and strategy inputs in memory.
- Use persistent exchange WebSockets.
- Timestamp receive/decision/submit/ack/fill boundaries.
- Persist telemetry asynchronously.
- Never let dashboard/database latency block the execution path.
