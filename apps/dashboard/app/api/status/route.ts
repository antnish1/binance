import { NextResponse } from "next/server";

const ENDPOINTS = [
  "health",
  "market",
  "paper/status",
  "risk/status",
  "automation/status",
  "recording/status",
  "research/latest",
  "live-readiness",
  "events/stats",
] as const;

async function fetchJson(base: string, path: string) {
  try {
    const response = await fetch(`${base}/${path}`, { cache: "no-store" });
    if (!response.ok) {
      return { ok: false, status: response.status };
    }
    return { ok: true, data: await response.json() };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "request failed",
    };
  }
}

export async function GET() {
  const base = process.env.TRADING_ENGINE_URL?.replace(/\/$/, "");
  if (!base) {
    return NextResponse.json(
      { ok: false, error: "TRADING_ENGINE_URL is not configured" },
      { status: 503 },
    );
  }

  const results = await Promise.all(ENDPOINTS.map((path) => fetchJson(base, path)));
  const payload = Object.fromEntries(ENDPOINTS.map((path, index) => [path, results[index]]));

  return NextResponse.json({
    ok: results.some((item) => item.ok),
    fetched_at: new Date().toISOString(),
    engine_url_configured: true,
    ...payload,
  });
}
