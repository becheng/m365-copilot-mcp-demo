// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from "vitest";
import { mountDashboard } from "./dashboard";
import type { DashboardBridge, ToolContracts } from "./bridge";
import type { DashboardPayload } from "./contracts";

function payload(scenario: DashboardPayload["scenario_id"] = "healthy"): DashboardPayload {
  const context = {
    scenario_id: scenario, snapshot_id: `v1:${scenario}:1792357200`,
    as_of: "2026-10-18T21:00:00Z", simulated: true as const,
  };
  return {
    ...context,
    summary: { ...context, total_databases: 1, stale_databases: 0, failed_runs_24h: 0,
      health_counts: { healthy: 1, warning: 0, critical: 0, unknown: 0 } },
    databases: { ...context, total: 1, offset: 0, limit: 20, items: [{
      id: "orders", name: "Contoso Orders", source: "onprem/orders", target: "azure/orders",
      engine: "SQL Server", replication_method: "Simulated replication", environment: "production",
      expected_sync_interval_seconds: 300, last_success_at: "2026-10-18T20:59:00Z",
      lag_seconds: 30, service_health: "running", storage_used_gib: 50,
      storage_allocated_gib: 100, throughput_mib_per_second: 8, failed_runs_24h: 0,
      status: "healthy", health: {
        storage: { status: "healthy", reason: "Storage utilization 50%" },
        freshness: { status: "healthy", reason: "Last success 60 seconds ago" },
      },
    }] },
  };
}

class FakeBridge implements DashboardBridge {
  initial: (value: DashboardPayload) => void = () => {};
  requests: { name: string; args: unknown }[] = [];
  dashboard: (scenario: DashboardPayload["scenario_id"]) => Promise<DashboardPayload> =
    async (scenario) => payload(scenario);
  databasePage: () => Promise<DashboardPayload["databases"]> = async () =>
    ({ ...payload().databases, items: [], total: 0 });

  connect = async () => {};
  onInitialResult(handler: (value: DashboardPayload) => void) { this.initial = handler; }
  async callTool<K extends keyof ToolContracts>(
    name: K, args: ToolContracts[K]["args"],
  ): Promise<ToolContracts[K]["result"]> {
    this.requests.push({ name, args });
    const data = payload();
    let result: unknown;
    if (name === "show_dashboard") {
      const input = args as ToolContracts["show_dashboard"]["args"];
      result = await this.dashboard(input.request.scenario_id);
    } else if (name === "list_databases") {
      result = await this.databasePage();
    } else if (name === "get_database_details") {
      result = { scenario_id: data.scenario_id, snapshot_id: data.snapshot_id,
        as_of: data.as_of, simulated: true, database: data.databases.items[0], incidents: [] };
    } else if (name === "get_metric_history") {
      const input = args as ToolContracts["get_metric_history"]["args"];
      result = { scenario_id: data.scenario_id, snapshot_id: data.snapshot_id,
        as_of: data.as_of, simulated: true, database_id: "orders", metric: input.query.metric,
        unit: "seconds", hours: 24, points: [{ at: data.as_of, value: 30 }] };
    } else { throw new Error(`Unexpected test tool: ${name}`); }
    return result as ToolContracts[K]["result"];
  }
}

let root: HTMLElement;
let bridge: FakeBridge;
beforeEach(() => {
  document.body.innerHTML = "<main id='app'></main>";
  root = document.getElementById("app")!;
  bridge = new FakeBridge();
  mountDashboard(root, bridge);
});

function change(id: string, value: string) {
  const select = root.querySelector<HTMLSelectElement>(`#${id}`)!;
  select.value = value;
  select.dispatchEvent(new Event("change"));
}

it("renders simulated data, reference time, health and database values", async () => {
  bridge.initial(payload());
  expect(root.textContent).toContain("Demo / simulated data");
  expect(root.textContent).toContain("2026-10-18T21:00:00Z");
  expect(root.textContent).toContain("Contoso Orders");
  expect(root.textContent).toContain("50 GiB");
});

it("preserves the snapshot when filtering and shows an explicit empty state", async () => {
  bridge.initial(payload());
  change("status-filter", "critical");
  await vi.waitFor(() => expect(root.textContent).toContain("No databases match"));
  expect(bridge.requests[0]).toEqual({
    name: "list_databases", args: { query: {
      scenario_id: "healthy", snapshot_id: "v1:healthy:1792357200", status: "critical",
      environment: null, offset: 0, limit: 20,
    } },
  });
});

it("drills down with shared snapshot and renders three metric histories", async () => {
  bridge.initial(payload());
  root.querySelector<HTMLButtonElement>("[data-database='orders']")!.click();
  await vi.waitFor(() => expect(root.querySelectorAll("figure").length).toBe(3));
  expect(root.textContent).toContain("Last success 60 seconds ago");
  expect(root.textContent).toContain("No incidents in this simulated snapshot");
  expect(bridge.requests.filter((value) => value.name === "get_metric_history")).toHaveLength(3);
  expect(bridge.requests[0]).toEqual({
    name: "get_database_details", args: {
      request: { scenario_id: "healthy", snapshot_id: "v1:healthy:1792357200" },
      database_id: "orders",
    },
  });
});

it("does not turn missing storage into zero usage", () => {
  const input = payload();
  input.databases.items[0].storage_used_gib = null;
  input.databases.items[0].storage_allocated_gib = null;
  bridge.initial(input);
  expect(root.textContent).toContain("Unknown");
  expect(root.textContent).not.toContain("0 GiB");
});

it("does not allow a late scenario response to replace the current scenario", async () => {
  bridge.initial(payload());
  let late!: (value: DashboardPayload) => void;
  bridge.dashboard = (scenario) => scenario === "lagging"
    ? new Promise((resolve) => { late = resolve; }) : Promise.resolve(payload(scenario));
  change("scenario", "lagging");
  change("scenario", "outage");
  await vi.waitFor(() => expect(root.textContent).toContain("v1:outage:1792357200"));
  late(payload("lagging"));
  await Promise.resolve();
  expect(root.textContent).toContain("v1:outage:1792357200");
  expect(root.textContent).not.toContain("v1:lagging:1792357200");
});

it("shows tool failures rather than creating successful fallback data", async () => {
  bridge.initial(payload());
  bridge.dashboard = async () => { throw new Error("Connection unavailable"); };
  change("scenario", "capacity");
  await vi.waitFor(() => expect(root.querySelector("[role=alert]")?.textContent)
    .toContain("Connection unavailable"));
  expect(root.textContent).not.toContain("v1:capacity:");
});

it("ignores a stale scenario error after a newer response succeeds", async () => {
  bridge.initial(payload());
  let rejectLate!: (error: Error) => void;
  bridge.dashboard = (scenario) => scenario === "lagging"
    ? new Promise((_, reject) => { rejectLate = reject; }) : Promise.resolve(payload(scenario));
  change("scenario", "lagging");
  change("scenario", "capacity");
  await vi.waitFor(() => expect(root.textContent).toContain("v1:capacity:"));
  rejectLate(new Error("Old request failed"));
  await Promise.resolve();
  expect(root.textContent).not.toContain("Old request failed");
  expect(root.textContent).toContain("v1:capacity:");
});

it("does not filter the previous snapshot while a new scenario is loading", () => {
  bridge.initial(payload());
  bridge.dashboard = () => new Promise(() => {});
  change("scenario", "outage");
  change("status-filter", "critical");
  expect(bridge.requests).toHaveLength(1);
  expect(root.querySelector("[data-database='orders']")).toBeNull();
  expect(root.querySelector<HTMLSelectElement>("#status-filter")?.disabled).toBe(true);
});

it("prevents stale-row drilldown from cancelling a pending filter result", async () => {
  bridge.initial(payload());
  let resolveFilter!: (value: DashboardPayload["databases"]) => void;
  bridge.databasePage = () => new Promise((resolve) => { resolveFilter = resolve; });
  change("status-filter", "critical");
  const staleRow = root.querySelector<HTMLButtonElement>("[data-database='orders']")!;
  expect(staleRow.disabled).toBe(true);
  staleRow.click();
  resolveFilter({ ...payload().databases, items: [], total: 0 });
  await vi.waitFor(() => expect(root.textContent).toContain("No databases match"));
  expect(bridge.requests.some((request) => request.name === "get_database_details")).toBe(false);
});
