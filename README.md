# Binance Fast Trading Platform

Cloud-first, strategy-agnostic Binance trading infrastructure.

## Current scope: Phase 0–3

- Secure environment-based configuration
- Binance Spot REST connectivity
- Binance Spot live WebSocket `bookTicker` market feed
- In-memory best bid/ask state
- Reconnect and stale-data monitoring
- Health and market APIs
- Optional authenticated read-only account check
- Docker-ready always-on worker
- GitHub Actions CI
- Hard safety block: live order execution is not implemented and cannot be enabled

## Security

**Never commit Binance API credentials to this repository.** Use cloud environment variables/secrets named `BINANCE_API_KEY` and `BINANCE_API_SECRET`.

For this phase, keep Binance trading permission and withdrawals disabled. `TRADING_ENABLED=true` is deliberately rejected at startup.

## Cloud architecture

```text
GitHub -> CI/tests -> always-on Docker worker -> Binance WebSocket/REST
                    \
                     -> Vercel dashboard (later phase)
```

The trading engine must run as an always-on worker; Vercel is reserved for the dashboard/control plane because serverless functions are not appropriate for a persistent exchange WebSocket.

## Health endpoints

- `GET /health`
- `GET /market`
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
