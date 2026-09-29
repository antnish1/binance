"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import TaddyBear from "./components/TaddyBear";

type Wrapped<T> = { ok: boolean; data?: T; status?: number; error?: string };
type Generic = Record<string, unknown>;
type Order = {
  order_id?: number;
  side?: string;
  type?: string;
  quantity?: string;
  limit_price?: string | null;
  status?: string;
  average_fill_price?: string;
  fee_paid?: string;
  created_at_ms?: number;
};

type DashboardPayload = {
  ok?: boolean;
  fetched_at?: string;
  health?: Wrapped<Generic>;
  market?: Wrapped<Generic>;
  "paper/status"?: Wrapped<Generic>;
  "risk/status"?: Wrapped<Generic>;
  "automation/status"?: Wrapped<Generic>;
  "recording/status"?: Wrapped<Generic>;
  "events/stats"?: Wrapped<Generic>;
  error?: string;
};

type EquityPoint = { at: number; value: number };

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

function orderRows(value: unknown): Order[] {
  return Array.isArray(value) ? (value as Order[]) : [];
}

function EquityChart({ points }: { points: EquityPoint[] }) {
  if (points.length < 2) return <div className="chart-empty">Collecting account history…</div>;
  const width = 760;
  const height = 180;
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 0.01);
  const path = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * width;
      const y = height - ((point.value - min) / span) * (height - 18) - 9;
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Paper account equity history">
        <path className="equity-line" d={path} fill="none" />
      </svg>
      <div className="chart-scale"><span>{money(min)}</span><span>{money(max)}</span></div>
    </div>
  );
}

export default function Home() {
  const [payload, setPayload] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [side, setSide] = useState("BUY");
  const [orderType, setOrderType] = useState("MARKET");
  const [quantity, setQuantity] = useState("0.0001");
  const [limitPrice, setLimitPrice] = useState("");
  const [riskResult, setRiskResult] = useState<Generic | null>(null);
  const [replayEvents, setReplayEvents] = useState("10000");
  const [replaySpeed, setReplaySpeed] = useState("0");
  const [replayResult, setReplayResult] = useState<Generic | null>(null);
  const [equityHistory, setEquityHistory] = useState<EquityPoint[]>([]);
  const [autoQuantity, setAutoQuantity] = useState("0.0001");
  const [autoThreshold, setAutoThreshold] = useState("20");
  const [autoLookback, setAutoLookback] = useState("50");
  const [autoCooldown, setAutoCooldown] = useState("30");
  const automationSeeded = useRef(false);

  async function refresh() {
    setRefreshing(true);
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      const data = (await response.json()) as DashboardPayload;
      setPayload(data);
      setError(response.ok ? null : data.error ?? "Engine status unavailable");
      const equity = Number(data?.["paper/status"]?.data?.equity);
      if (Number.isFinite(equity)) {
        setEquityHistory((current) => [...current, { at: Date.now(), value: equity }].slice(-120));
      }
      if (!automationSeeded.current) {
        const config = data?.["automation/status"]?.data?.config;
        if (config && typeof config === "object") {
          const values = config as Generic;
          setAutoQuantity(text(values.quantity, "0.0001"));
          setAutoThreshold(text(values.threshold_bps, "20"));
          setAutoLookback(text(values.lookback, "50"));
          setAutoCooldown(text(values.cooldown_seconds, "30"));
          automationSeeded.current = true;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dashboard request failed");
    } finally {
      setRefreshing(false);
    }
  }

  async function control(action: string, body: Generic = {}) {
    setBusy(action);
    setNotice(null);
    try {
      const response = await fetch("/api/control", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action, ...body }),
      });
      const result = (await response.json()) as { ok?: boolean; data?: Generic; error?: string };
      if (!response.ok || result.ok === false) {
        throw new Error(result.error ?? text(result.data?.detail, "Control request failed"));
      }
      await refresh();
      return result.data ?? {};
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Control request failed");
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function submitPaperOrder(event: FormEvent) {
    event.preventDefault();
    const order: Generic = { side, order_type: orderType, quantity };
    if (orderType === "LIMIT") order.limit_price = limitPrice;
    const result = await control("paper_order", { payload: order });
    if (result) setNotice(result.accepted === false ? `Rejected: ${text(result.reason)}` : "Paper order submitted.");
  }

  async function evaluateRisk() {
    const proposal: Generic = { side, quantity };
    if (orderType === "LIMIT" && limitPrice) proposal.price = limitPrice;
    const result = await control("risk_evaluate", { payload: proposal });
    if (result) setRiskResult(result);
  }

  async function runReplay() {
    const result = await control("replay_run", {
      payload: { max_events: Number(replayEvents), speed: Number(replaySpeed) },
    });
    if (result) {
      setReplayResult(result);
      setNotice("Replay completed.");
    }
  }

  async function saveAutomationConfig() {
    const result = await control("automation_config", {
      payload: {
        quantity: autoQuantity,
        threshold_bps: autoThreshold,
        lookback: Number(autoLookback),
        cooldown_seconds: Number(autoCooldown),
      },
    });
    if (result) setNotice("Automation settings saved.");
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
  const automation = payload?.["automation/status"]?.data ?? {};
  const recording = payload?.["recording/status"]?.data ?? {};
  const events = payload?.["events/stats"]?.data ?? {};
  const marketLive = health.market_stream_connected === true && health.market_data_stale === false;
  const privateLive = health.user_stream_connected === true;
  const recorderLive = recording.running === true;
  const automationLive = automation.enabled === true;
  const orders = orderRows(paper.orders);
  const openOrders = orderRows(paper.open_orders);
  const recentOrders = [...orders].reverse().slice(0, 12);

  const published = useMemo(() => {
    const value = events.published;
    return value && typeof value === "object" ? (value as Generic) : {};
  }, [events.published]);

  return (
    <main className="app-frame">
      <aside className="sidebar">
        <div className="brand-mark"><span className="brand-bear">ʕ•ᴥ•ʔ</span><div><b>Taddy</b><small>CONTROL CENTER</small></div></div>
        <nav>
          <a className="nav-item active" href="#overview"><span>⌂</span>Overview</a>
          <a className="nav-item" href="#automation"><span>✦</span>Automation</a>
          <a className="nav-item" href="#paper"><span>◫</span>Paper account</a>
          <a className="nav-item" href="#orders"><span>▤</span>Orders</a>
          <a className="nav-item" href="#replay"><span>▷</span>Replay</a>
          <a className="nav-item" href="#systems"><span>◎</span>Systems</a>
        </nav>
        <div className="sidebar-mascot"><TaddyBear /><p>Small steps.<br />Smarter decisions.</p></div>
        <div className="version">v0.11 · PAPER MODE</div>
      </aside>

      <div className="main-area">
        <section className="topbar">
          <div><span className="crumb">AUTOMATION · OBSERVABILITY · PAPER EXECUTION</span></div>
          <div className="top-actions"><span className={`status ${marketLive ? "ok" : "warn"}`}>{marketLive ? "MARKET LIVE" : "MARKET DEGRADED"}</span><span className="status locked">LIVE LOCKED</span><button className="refresh" onClick={() => void refresh()} disabled={refreshing}>{refreshing ? "Refreshing…" : "Refresh"}</button></div>
        </section>

        <section className="hero-card" id="overview">
          <div className="hero-copy"><span className="phase-chip">PHASE 11 · AUTOMATION</span><h1>Taddy <span>Control Center</span></h1><p>One calm workspace for live market telemetry, paper execution, deterministic risk, replay tools and automated decision testing.</p><div className="hero-badges"><span>Paper only</span><span>Risk gated</span><span>Live data</span></div></div>
          <div className="hero-illustration"><TaddyBear /></div>
          <div className="mode-stack"><div><small>Execution mode</small><b>PAPER ONLY</b><span>Real-money execution is locked</span></div><div><small>Automation</small><b className={automationLive ? "good" : "soft"}>{automationLive ? "ACTIVE" : "STANDBY"}</b><span>{text(automation.state, "idle")}</span></div></div>
        </section>

        {error && <p className="notice danger">{error}</p>}
        {notice && <p className="notice">{notice}</p>}

        <section className="kpi-grid premium">
          <article className="kpi"><span>BTCUSDT</span><strong>{numberText(market.midpoint, 2)}</strong><small>{numberText(health.market_data_age_ms, 0)} ms old</small></article>
          <article className="kpi"><span>Spread</span><strong>{text(market.spread)}</strong><small>Bid {numberText(market.bid, 2)}</small></article>
          <article className="kpi"><span>Paper equity</span><strong>{money(paper.equity)}</strong><small>Start {money(paper.starting_quote_balance)}</small></article>
          <article className="kpi"><span>Unrealized P&amp;L</span><strong>{money(paper.unrealized_pnl)}</strong><small>Fees {money(paper.fees_paid)}</small></article>
          <article className="kpi"><span>Realized P&amp;L</span><strong>{money(paper.realized_pnl)}</strong><small>{orders.length} paper orders</small></article>
          <article className="kpi safety"><span>Open orders</span><strong>{openOrders.length}</strong><small>risk protected</small></article>
        </section>

        <section className="primary-grid">
          <article className="panel order-entry" id="paper">
            <div className="panel-head"><div><p className="label">Paper execution</p><h2>Place paper order</h2></div><span className="tag green-tag">PAPER ONLY</span></div>
            <form onSubmit={submitPaperOrder} className="control-form">
              <div className="segmented"><button type="button" className={side === "BUY" ? "active buy" : ""} onClick={() => setSide("BUY")}>BUY</button><button type="button" className={side === "SELL" ? "active sell" : ""} onClick={() => setSide("SELL")}>SELL</button></div>
              <div className="field-row"><label>Order type<select value={orderType} onChange={(event) => setOrderType(event.target.value)}><option>MARKET</option><option>LIMIT</option></select></label><label>Quantity BTC<input value={quantity} onChange={(event) => setQuantity(event.target.value)} inputMode="decimal" /></label></div>
              {orderType === "LIMIT" && <label>Limit price USDT<input value={limitPrice} onChange={(event) => setLimitPrice(event.target.value)} inputMode="decimal" placeholder={text(market.midpoint, "0")} /></label>}
              <div className="ticket-summary"><span>Indicative midpoint</span><b>{money(market.midpoint)}</b></div>
              <div className="button-row"><button type="button" className="secondary" onClick={() => void evaluateRisk()} disabled={busy !== null}>Check risk</button><button type="submit" className="primary" disabled={busy !== null}>{busy === "paper_order" ? "Submitting…" : "Submit paper order"}</button></div>
            </form>
            {riskResult && <div className={`risk-result ${riskResult.approved === true ? "approved" : "rejected"}`}><b>{riskResult.approved === true ? "Risk approved" : "Risk rejected"}</b><span>{text(riskResult.reason)}</span></div>}
          </article>

          <article className="panel chart-panel">
            <div className="panel-head"><div><p className="label">Paper account performance</p><h2>{money(paper.equity)}</h2></div><span className="tag">LAST {equityHistory.length} SAMPLES</span></div>
            <EquityChart points={equityHistory} />
            <div className="mini-grid four"><div><span>Quote</span><b>{money(paper.quote_balance)}</b></div><div><span>BTC</span><b>{text(paper.base_balance)}</b></div><div><span>Realized</span><b>{money(paper.realized_pnl)}</b></div><div><span>Unrealized</span><b>{money(paper.unrealized_pnl)}</b></div></div>
          </article>

          <article className="panel automation-panel" id="automation">
            <div className="panel-head"><div><p className="label">Automation module</p><h2>Mean Reversion · Starter</h2></div><span className={`status ${automationLive ? "ok" : "warn"}`}>{automationLive ? "ACTIVE" : "STANDBY"}</span></div>
            <div className="automation-intro"><div className="mini-bear"><TaddyBear /></div><p>Observes a rolling midpoint baseline, opens a paper position after a configured downward deviation and closes after reversion. Every action passes the hard risk gate first.</p></div>
            <div className="auto-fields"><label>Quantity BTC<input value={autoQuantity} onChange={(event) => setAutoQuantity(event.target.value)} /></label><label>Threshold bps<input value={autoThreshold} onChange={(event) => setAutoThreshold(event.target.value)} /></label><label>Lookback<input value={autoLookback} onChange={(event) => setAutoLookback(event.target.value)} /></label><label>Cooldown sec<input value={autoCooldown} onChange={(event) => setAutoCooldown(event.target.value)} /></label></div>
            <div className="button-row triple"><button className="secondary" onClick={() => void saveAutomationConfig()} disabled={busy !== null}>Save settings</button><button className="secondary" onClick={() => void control("automation_reset")} disabled={busy !== null}>Reset</button><button className={automationLive ? "danger-button" : "primary"} onClick={() => void control(automationLive ? "automation_disable" : "automation_enable")} disabled={busy !== null}>{automationLive ? "Disable automation" : "Enable automation"}</button></div>
            <dl className="automation-status"><div><dt>State</dt><dd>{text(automation.state)}</dd></div><div><dt>Last signal</dt><dd>{text(automation.last_signal)}</dd></div><div><dt>Deviation</dt><dd>{automation.last_deviation_bps == null ? "—" : `${numberText(automation.last_deviation_bps, 2)} bps`}</dd></div><div><dt>Samples</dt><dd>{numberText(automation.samples, 0)}</dd></div><div><dt>Signals</dt><dd>{numberText(automation.signals, 0)}</dd></div><div><dt>Filled</dt><dd>{numberText(automation.filled, 0)}</dd></div></dl>
          </article>
        </section>

        <section className="two-col equal" id="orders">
          <article className="panel"><div className="panel-head"><div><p className="label">Open paper orders</p><h2>{openOrders.length} open</h2></div><span className="dot green" /></div><div className="table-wrap"><table><thead><tr><th>ID</th><th>Side</th><th>Type</th><th>Qty</th><th>Limit</th><th>Status</th><th /></tr></thead><tbody>{openOrders.length === 0 ? <tr><td colSpan={7} className="empty-cell">No open paper orders</td></tr> : openOrders.map((order) => <tr key={order.order_id}><td>#{order.order_id}</td><td className={order.side === "BUY" ? "buy-text" : "sell-text"}>{text(order.side)}</td><td>{text(order.type)}</td><td>{text(order.quantity)}</td><td>{text(order.limit_price)}</td><td>{text(order.status)}</td><td><button className="tiny" onClick={() => void control("paper_cancel", { order_id: order.order_id })} disabled={busy !== null}>Cancel</button></td></tr>)}</tbody></table></div></article>
          <article className="panel"><div className="panel-head"><div><p className="label">Order &amp; fill history</p><h2>Recent activity</h2></div><span className="tag">{orders.length} TOTAL</span></div><div className="table-wrap"><table><thead><tr><th>ID</th><th>Side</th><th>Status</th><th>Qty</th><th>Fill</th><th>Fee</th></tr></thead><tbody>{recentOrders.length === 0 ? <tr><td colSpan={6} className="empty-cell">No paper orders yet</td></tr> : recentOrders.map((order) => <tr key={order.order_id}><td>#{order.order_id}</td><td className={order.side === "BUY" ? "buy-text" : "sell-text"}>{text(order.side)}</td><td>{text(order.status)}</td><td>{text(order.quantity)}</td><td>{numberText(order.average_fill_price, 2)}</td><td>{numberText(order.fee_paid, 4)}</td></tr>)}</tbody></table></div></article>
        </section>

        <section className="systems-grid" id="systems">
          <article className="panel compact"><div className="panel-head"><div><p className="label">Risk engine</p><h2>{risk.kill_switch_engaged === true ? "KILL SWITCH" : "Ready"}</h2></div><span className={`dot ${risk.kill_switch_engaged === true ? "red" : "green"}`} /></div><dl><div><dt>Mode</dt><dd>{text(risk.mode)}</dd></div><div><dt>Daily P&amp;L</dt><dd>{money(risk.daily_realized_pnl)}</dd></div><div><dt>Orders/min</dt><dd>{text(risk.approved_orders_last_minute, "0")}</dd></div><div><dt>Execution</dt><dd>Paper only</dd></div></dl></article>
          <article className="panel compact"><div className="panel-head"><div><p className="label">Recorder</p><h2>{recorderLive ? "Recording" : "Stopped"}</h2></div><span className={`dot ${recorderLive ? "green" : "amber"}`} /></div><dl><div><dt>Total ticks</dt><dd>{numberText(recording.recorded_total, 0)}</dd></div><div><dt>Buffered</dt><dd>{numberText(recording.buffered_events, 0)}</dd></div><div><dt>Capacity</dt><dd>{numberText(recording.max_events, 0)}</dd></div><div><dt>Write error</dt><dd>{text(recording.last_write_error, "None")}</dd></div></dl><button className="secondary full" onClick={() => void control("recording_reset")} disabled={busy !== null}>Reset buffer</button></article>
          <article className="panel compact" id="replay"><div className="panel-head"><div><p className="label">Replay</p><h2>Backtest feed</h2></div><span className="tag">ISOLATED</span></div><div className="inline-fields"><label>Events<input value={replayEvents} onChange={(event) => setReplayEvents(event.target.value)} /></label><label>Speed<input value={replaySpeed} onChange={(event) => setReplaySpeed(event.target.value)} /></label></div><button className="primary full" onClick={() => void runReplay()} disabled={busy !== null}>{busy === "replay_run" ? "Running…" : "Run replay"}</button>{replayResult && <p className="result-line">Ticks {numberText(replayResult.tick_count, 0)} · Avg spread {numberText(replayResult.average_spread, 6)}</p>}</article>
          <article className="panel compact"><div className="panel-head"><div><p className="label">Event bus</p><h2>Sequence {text(events.last_sequence)}</h2></div><span className="dot green" /></div><dl><div><dt>Market ticks</dt><dd>{numberText(published.market_tick, 0)}</dd></div><div><dt>Signals</dt><dd>{numberText(published.signal_created, 0)}</dd></div><div><dt>Risk approved</dt><dd>{numberText(published.risk_approved, 0)}</dd></div><div><dt>Paper fills</dt><dd>{numberText(published.order_filled, 0)}</dd></div></dl></article>
          <article className="panel compact system-health"><div className="panel-head"><div><p className="label">System status</p><h2>Healthy</h2></div><span className="dot green" /></div><ul><li><span>Market data</span><b>{marketLive ? "Connected" : "Degraded"}</b></li><li><span>User stream</span><b>{privateLive ? "Connected" : "Offline"}</b></li><li><span>Risk engine</span><b>{risk.kill_switch_engaged === true ? "Blocked" : "Ready"}</b></li><li><span>Paper executor</span><b>Ready</b></li><li><span>Automation</span><b>{automationLive ? "Active" : "Standby"}</b></li><li><span>Recorder</span><b>{recorderLive ? "Recording" : "Stopped"}</b></li></ul></article>
        </section>

        <footer><span>Auto-refresh: 2s</span><span>Last fetch: {payload?.fetched_at ? new Date(payload.fetched_at).toLocaleTimeString() : "—"}</span><span>Real-money execution: locked</span></footer>
      </div>
    </main>
  );
}
