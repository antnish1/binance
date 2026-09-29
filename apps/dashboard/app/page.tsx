"use client";

import { useEffect, useMemo, useState } from "react";

type Wrapped<T> = { ok: boolean; data?: T; status?: number; error?: string };

type DashboardPayload = {
  ok?: boolean;
  fetched_at?: string;
  health?: Wrapped<Record<string, unknown>>;
  market?: Wrapped<Record<string, unknown>>;
  "paper/status"?: Wrapped<Record<string, unknown>>;
  "risk/status"?: Wrapped<Record<string, unknown>>;
  "recording/status"?: Wrapped<Record<string, unknown>>;
  "events/stats"?: Wrapped<Record<string, unknown>>;
  error?: string;
};

function text(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function numberText(value: unknown, digits = 2) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return parsed.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function money(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return `${parsed.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT`;
}

export default function Home() {
  const [payload, setPayload] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  async function refresh() {
    setRefreshing(true);
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      const data = (await response.json()) as DashboardPayload;
      setPayload(data);
      setError(response.ok ? null : data.error ?? "Engine status unavailable");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dashboard request failed");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, []);

  const health = payload?.health?.data ?? {};
  const market = payload?.market?.data ?? {};
  const paper = payload?.["paper/status"]?.data ?? {};
  const risk = payload?.["risk/status"]?.data ?? {};
  const recording = payload?.["recording/status"]?.data ?? {};
  const events = payload?.["events/stats"]?.data ?? {};
  const marketLive = health.market_stream_connected === true && health.market_data_stale === false;
  const privateLive = health.user_stream_connected === true;
  const recorderLive = recording.running === true;

  const published = useMemo(() => {
    const value = events.published;
    return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  }, [events.published]);

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">PHASE 9 · OBSERVABILITY · PAPER ONLY</p>
          <h1>Trading Control Center</h1>
          <p className="sub">Live Binance market telemetry, paper P&amp;L, deterministic risk and recorder health in one view.</p>
        </div>
        <div className="hero-actions">
          <span className={`status ${marketLive ? "ok" : "warn"}`}>{marketLive ? "MARKET LIVE" : "MARKET DEGRADED"}</span>
          <button className="refresh" onClick={() => void refresh()} disabled={refreshing}>{refreshing ? "Refreshing…" : "Refresh"}</button>
        </div>
      </section>

      {error && <p className="notice danger">{error}</p>}

      <section className="kpi-grid">
        <article className="kpi"><span>BTC midpoint</span><strong>{numberText(market.midpoint, 2)}</strong><small>{text(health.symbol, "BTCUSDT")}</small></article>
        <article className="kpi"><span>Spread</span><strong>{text(market.spread)}</strong><small>{numberText(health.market_data_age_ms, 0)} ms old</small></article>
        <article className="kpi"><span>Paper equity</span><strong>{money(paper.equity)}</strong><small>Start {money(paper.starting_quote_balance)}</small></article>
        <article className="kpi"><span>Paper P&amp;L</span><strong>{money(Number(paper.realized_pnl ?? 0) + Number(paper.unrealized_pnl ?? 0))}</strong><small>Fees {money(paper.fees_paid)}</small></article>
        <article className="kpi safety"><span>Live trading</span><strong>LOCKED</strong><small>Paper execution only</small></article>
      </section>

      <section className="two-col">
        <article className="panel">
          <div className="panel-head"><div><p className="label">Market</p><h2>BTCUSDT</h2></div><span className={`dot ${marketLive ? "green" : "amber"}`} /></div>
          <div className="price-row"><div><span>Bid</span><strong>{text(market.bid)}</strong></div><div><span>Ask</span><strong>{text(market.ask)}</strong></div></div>
          <div className="mini-grid"><div><span>Bid qty</span><b>{text(market.bid_qty)}</b></div><div><span>Ask qty</span><b>{text(market.ask_qty)}</b></div><div><span>Reconnects</span><b>{text(health.market_reconnect_count, "0")}</b></div><div><span>User stream</span><b>{privateLive ? "Connected" : "Disconnected"}</b></div></div>
        </article>

        <article className="panel">
          <div className="panel-head"><div><p className="label">Paper account</p><h2>{money(paper.equity)}</h2></div><span className="tag">SIMULATED</span></div>
          <div className="mini-grid"><div><span>Quote balance</span><b>{money(paper.quote_balance)}</b></div><div><span>BTC balance</span><b>{text(paper.base_balance)}</b></div><div><span>Realized</span><b>{money(paper.realized_pnl)}</b></div><div><span>Unrealized</span><b>{money(paper.unrealized_pnl)}</b></div></div>
        </article>
      </section>

      <section className="three-col">
        <article className="panel compact">
          <div className="panel-head"><div><p className="label">Risk engine</p><h2>{risk.kill_switch_engaged === true ? "KILL SWITCH" : "Ready"}</h2></div><span className={`dot ${risk.kill_switch_engaged === true ? "red" : "green"}`} /></div>
          <dl><div><dt>Mode</dt><dd>{text(risk.mode)}</dd></div><div><dt>Daily P&amp;L</dt><dd>{money(risk.daily_realized_pnl)}</dd></div><div><dt>Orders/min</dt><dd>{text(risk.approved_orders_last_minute, "0")}</dd></div><div><dt>Trading</dt><dd>Disabled</dd></div></dl>
        </article>

        <article className="panel compact">
          <div className="panel-head"><div><p className="label">Recorder</p><h2>{recorderLive ? "Recording" : "Stopped"}</h2></div><span className={`dot ${recorderLive ? "green" : "amber"}`} /></div>
          <dl><div><dt>Total ticks</dt><dd>{numberText(recording.recorded_total, 0)}</dd></div><div><dt>Buffered</dt><dd>{numberText(recording.buffered_events, 0)}</dd></div><div><dt>Capacity</dt><dd>{numberText(recording.max_events, 0)}</dd></div><div><dt>Write error</dt><dd>{text(recording.last_write_error, "None")}</dd></div></dl>
        </article>

        <article className="panel compact">
          <div className="panel-head"><div><p className="label">Event bus</p><h2>Sequence {text(events.last_sequence)}</h2></div><span className="dot green" /></div>
          <dl><div><dt>Market ticks</dt><dd>{numberText(published.market_tick, 0)}</dd></div><div><dt>Risk approved</dt><dd>{numberText(published.risk_approved, 0)}</dd></div><div><dt>Risk rejected</dt><dd>{numberText(published.risk_rejected, 0)}</dd></div><div><dt>Paper fills</dt><dd>{numberText(published.order_filled, 0)}</dd></div></dl>
        </article>
      </section>

      <footer>
        <span>Auto-refresh: 2s</span>
        <span>Last dashboard fetch: {payload?.fetched_at ? new Date(payload.fetched_at).toLocaleTimeString() : "—"}</span>
        <span>Real Binance order execution: blocked</span>
      </footer>
    </main>
  );
}
