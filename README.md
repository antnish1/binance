# Binance Fast Trading Platform

Cloud-first, strategy-agnostic Binance trading infrastructure.

## Current scope: Phase 0–4

- Secure environment-based configuration
- Binance Spot REST connectivity
- Binance Spot live WebSocket `bookTicker` market feed
- In-memory best bid/ask state
- Reconnect and stale-data monitoring
- Non-blocking in-process event bus
- Market and connection events published from the WebSocket hot path
- Per-subscriber bounded queues with drop accounting
- Event telemetry endpoint
- Health and market APIs
- Optional authenticated read-only account check
- Docker-ready always-on worker
- GitHub Actions CI
- Hard safety block: live order execution is not implemented and cannot be enabled

## Security

**Never commit Binance API credentials to this repository.** Use cloud environment variables/secrets named `BINANCE_API_KEY` and `BINANCE_API_SECRET`.

For this phase, keep Binance trading permission and withdrawals disabled. `TRADING_ENABLED=true` is deliberately rejected at startup.

## Event flow

```text
Binance WebSocket
       ↓
Market normalizer
       ↓
In-memory MarketState
       ↓
EventBus
  ┌────┼───────────┐
  ↓    ↓           ↓
Risk  Strategy   Portfolio
(future phases)
```

Publishing to the event bus never waits for consumers. Each subscriber gets a bounded queue; a slow consumer drops only its own events and increments telemetry instead of blocking market-data processing.

## Cloud architecture

```text
GitHub -> CI/tests -> Railway Singapore worker -> Binance WebSocket/REST
```

The trading engine runs as an always-on service because a persistent exchange WebSocket is required.

## Service endpoints

- `GET /`
- `GET /health`
- `GET /market`
- `GET /events/stats`
- `GET /binance/time`
- `GET /account/check` (requires API credentials)

Default market: `BTCUSDT`.

## Local/Docker run

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
trading-bot
```

Or:

```bash
docker build -t binance-fast-bot .
docker run --rm --env-file .env -p 8000:8000 binance-fast-bot
```

See `ARCHITECTURE.md` and `docs/CLOUD_SETUP.md` for the project plan and deployment model.
