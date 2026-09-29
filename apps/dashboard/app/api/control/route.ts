import { NextRequest, NextResponse } from "next/server";

type ControlRequest = {
  action?: string;
  payload?: Record<string, unknown>;
  order_id?: number;
};

type Target = {
  path: string;
  method: "POST";
  body?: Record<string, unknown>;
};

function resolveTarget(input: ControlRequest): Target | null {
  const payload = input.payload ?? {};
  switch (input.action) {
    case "paper_order":
      return { path: "paper/orders", method: "POST", body: payload };
    case "paper_cancel":
      if (!Number.isInteger(input.order_id) || Number(input.order_id) < 1) return null;
      return { path: `paper/orders/${input.order_id}/cancel`, method: "POST" };
    case "risk_evaluate":
      return { path: "risk/evaluate", method: "POST", body: payload };
    case "recording_reset":
      return { path: "recording/reset", method: "POST" };
    case "replay_run":
      return { path: "replay/run", method: "POST", body: payload };
    case "research_run":
      return { path: "research/run", method: "POST", body: payload };
    case "automation_enable":
      return { path: "automation/enable", method: "POST" };
    case "automation_disable":
      return { path: "automation/disable", method: "POST" };
    case "automation_reset":
      return { path: "automation/reset", method: "POST" };
    case "automation_config":
      return { path: "automation/config", method: "POST", body: payload };
    default:
      return null;
  }
}

export async function POST(request: NextRequest) {
  const base = process.env.TRADING_ENGINE_URL?.replace(/\/$/, "");
  if (!base) {
    return NextResponse.json({ ok: false, error: "TRADING_ENGINE_URL is not configured" }, { status: 503 });
  }

  let input: ControlRequest;
  try {
    input = (await request.json()) as ControlRequest;
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON body" }, { status: 400 });
  }

  const target = resolveTarget(input);
  if (!target) {
    return NextResponse.json({ ok: false, error: "Unsupported control action" }, { status: 400 });
  }

  try {
    const response = await fetch(`${base}/${target.path}`, {
      method: target.method,
      cache: "no-store",
      headers: target.body ? { "content-type": "application/json" } : undefined,
      body: target.body ? JSON.stringify(target.body) : undefined,
    });
    const data = await response.json().catch(() => ({ detail: "Engine returned a non-JSON response" }));
    return NextResponse.json({ ok: response.ok, status: response.status, data }, { status: response.ok ? 200 : response.status });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "Engine request failed" },
      { status: 502 },
    );
  }
}
