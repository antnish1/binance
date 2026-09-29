type Health = {
  status?: string;
  symbol?: string;
  market_stream_connected?: boolean;
  market_data_age_ms?: number | null;
  market_data_stale?: boolean;
  reconnect_count?: number;
  trading_enabled?: boolean;
};

async function getHealth(): Promise<Health | null> {
  const base = process.env.TRADING_ENGINE_URL?.replace(/\/$/, "");
  if (!base) return null;
  try {
    const response = await fetch(`${base}/health`, { cache: "no-store" });
    if (!response.ok) return null;
    return (await response.json()) as Health;
  } catch {
    return null;
  }
}

export default async function Home() {
  const health = await getHealth();
  const connected = health?.market_stream_connected === true;

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">PHASE 0–3 · READ ONLY</p>
          <h1>Binance Fast Bot</h1>
          <p className="sub">Cloud trading-engine health. Live order execution is hard-blocked.</p>
        </div>
        <span className={`status ${connected ? "ok" : "warn"}`}>
          {connected ? "MARKET LIVE" : "NOT CONNECTED"}
        </span>
      </section>

      <section className="grid">
        <article className="card"><span>Engine</span><strong>{health?.status ?? "Not configured"}</strong></article>
        <article className="card"><span>Symbol</span><strong>{health?.symbol ?? "—"}</strong></article>
        <article className="card"><span>Market age</span><strong>{health?.market_data_age_ms ?? "—"} ms</strong></article>
        <article className="card"><span>Reconnects</span><strong>{health?.reconnect_count ?? "—"}</strong></article>
        <article className="card safety"><span>Live trading</span><strong>LOCKED</strong></article>
      </section>

      {!process.env.TRADING_ENGINE_URL && (
        <p className="notice">Set TRADING_ENGINE_URL in Vercel after the always-on worker is deployed.</p>
      )}
    </main>
  );
}
