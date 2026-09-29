# Cloud setup

The repository is prepared for a cloud-only workflow.

## 1. GitHub

GitHub stores source code and runs CI. Do not store Binance credentials in repository files, commits, issues, pull requests, or Actions logs.

## 2. Railway trading engine

Create a Railway service from this repository using the root `Dockerfile`.

Set these environment variables in Railway:

- `APP_ENV=production`
- `HOST=0.0.0.0`
- `PORT=8000`
- `BINANCE_SYMBOL=BTCUSDT`
- `BINANCE_API_KEY=<your fresh bot-only key>`
- `BINANCE_API_SECRET=<your fresh bot-only secret>`
- `TRADING_ENABLED=false`

For Phase 0–3, Binance trading permission should remain disabled. Withdrawals must remain disabled.

## 3. Vercel dashboard

Import this repository into Vercel and set the project Root Directory to `apps/dashboard`.

Set:

- `TRADING_ENGINE_URL=https://<your-railway-service-domain>`

The first dashboard is read-only and displays engine health. Trading controls are intentionally not present yet.

## 4. Secret rule

Do not edit `.env.example` with real credentials. It is a template and is committed to Git. Real credentials belong only in Railway encrypted environment variables.

## 5. Phase-completion checks

Phase 0–3 is considered complete when:

- CI is green.
- Railway `/health` returns healthy market-stream status.
- Railway `/market` returns changing BTCUSDT bid/ask values.
- `/account/check` succeeds after read-only API credentials are configured.
- `TRADING_ENABLED` remains `false`.
