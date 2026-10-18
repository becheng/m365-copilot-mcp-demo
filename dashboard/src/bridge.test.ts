import { expect, it, vi } from "vitest";
import { decodeResult } from "./bridge";

it("rejects a dashboard whose nested reference times disagree", () => {
  const context = {
    simulated: true, scenario_id: "healthy",
    snapshot_id: "v1:healthy:1792357200", as_of: "2026-10-18T21:00:00Z",
  };
  const input = {
    ...context,
    summary: { ...context, as_of: "2026-10-18T20:00:00Z",
      total_databases: 0, stale_databases: 0, failed_runs_24h: 0, health_counts: {} },
    databases: { ...context, total: 0, items: [], offset: 0, limit: 20 },
  };
  expect(() => decodeResult("show_dashboard", input)).toThrow("inconsistent snapshots");
});

it("rejects malformed tool results at the bridge boundary", () => {
  expect(() => decodeResult("get_metric_history", { points: [] })).toThrow("Invalid");
});

it("requires the explicit simulated-data marker", () => {
  expect(() => decodeResult("list_demo_scenarios", { scenarios: [] }))
    .toThrow("not marked as simulated");
});

it("initializes and validates without runtime code generation under a strict CSP", async () => {
  vi.resetModules();
  const blocked = vi.spyOn(globalThis, "Function").mockImplementation(() => {
    throw new EvalError("Code generation from strings disallowed");
  });
  try {
    const bridge = await import("./bridge");
    expect(bridge.decodeResult("list_demo_scenarios", { simulated: true, scenarios: [] }))
      .toEqual({ simulated: true, scenarios: [] });
  } finally { blocked.mockRestore(); }
});
