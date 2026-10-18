import type { DashboardBridge } from "./bridge";
import type {
  DashboardPayload, DatabaseDetails, DatabasePage, DatabaseRecord,
  HistoryQuery, MetricHistory, SnapshotRequest,
} from "./contracts";

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K, text = "", className = "",
): HTMLElementTagNameMap[K] {
  const result = document.createElement(tag);
  result.textContent = text;
  result.className = className;
  return result;
}

function measurement(value: number | null | undefined, unit: string) {
  return value == null ? "Unknown" : `${Number(value.toFixed(2))} ${unit}`;
}

function chart(history: MetricHistory): HTMLElement {
  const figure = element("figure");
  const label = `${history.metric.replaceAll("_", " ")} (${history.unit})`;
  figure.append(element("figcaption", label));
  const known = history.points.filter((point) => point.value !== null);
  if (known.length === 0) {
    figure.append(element("p", "No measurements available", "muted"));
    return figure;
  }
  const max = Math.max(...known.map((point) => point.value ?? 0), 1);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 400 100");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${label}: ${history.hours} hours of synthetic history`);
  let segment: string[] = [];
  function appendSegment() {
    if (!segment.length) return;
    const line = document.createElementNS(svg.namespaceURI, "polyline");
    line.setAttribute("points", segment.join(" "));
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", "currentColor");
    line.setAttribute("stroke-width", "3");
    svg.append(line);
    segment = [];
  }
  history.points.forEach((point, index) => {
    if (point.value === null) { appendSegment(); return; }
    segment.push(`${5 + index * 390 / Math.max(history.points.length - 1, 1)},${95 - point.value / max * 85}`);
  });
  appendSegment();
  figure.append(svg, element("p",
    `${history.hours}h synthetic history · latest ${measurement(history.points.at(-1)?.value, history.unit)}`,
    "muted"));
  return figure;
}

export function mountDashboard(root: HTMLElement, bridge: DashboardBridge): void {
  root.innerHTML = `
    <header><div><p class="eyebrow">REPLICATION OPERATIONS</p><h1>Replication Insights</h1>
    <p class="muted">Fictional on-premises to Azure database estate</p></div>
    <span class="demo">Demo / simulated data</span></header>
    <section class="toolbar" aria-label="Dashboard controls">
      <label>Scenario<select id="scenario">
        <option value="healthy">Healthy baseline</option><option value="lagging">Increasing lag</option>
        <option value="outage">Replication outage</option><option value="capacity">Capacity pressure</option>
      </select></label><button id="refresh" type="button">Refresh snapshot</button>
    </section>
    <p id="snapshot" class="muted"></p>
    <p id="loading" role="status" aria-live="polite">Waiting for protected Copilot tool result...</p>
    <p id="error" role="alert" hidden></p>
    <section id="summary" class="cards" aria-label="Estate summary"></section>
    <section class="panel">
      <div class="section-heading"><h2>Database estate</h2>
      <div class="filters"><label>Health<select id="status-filter">
        <option value="">All statuses</option><option>healthy</option><option>warning</option>
        <option>critical</option><option>unknown</option>
      </select></label><label>Environment<select id="environment-filter">
        <option value="">All environments</option><option>production</option><option>staging</option>
      </select></label></div></div>
      <p id="count" class="muted"></p><div id="databases" class="table-scroll"></div>
    </section>
    <section id="details" class="panel" hidden aria-label="Database details"></section>`;
  const get = <T extends HTMLElement>(id: string) => {
    const found = root.querySelector<T>(`#${id}`);
    if (!found) throw new Error(`Missing dashboard element ${id}`);
    return found;
  };
  let state: DashboardPayload | undefined;
  let generation = 0;
  function request(): SnapshotRequest {
    if (!state) throw new Error("No snapshot has been received");
    return { scenario_id: state.scenario_id, snapshot_id: state.snapshot_id };
  }
  function errorMessage(error: unknown) {
    const target = get("error");
    target.hidden = false;
    target.textContent = error instanceof Error ? error.message : "Unexpected dashboard error";
    get("loading").textContent = "";
  }
  async function run<T>(load: () => Promise<T>, apply: (value: T) => void) {
    const current = ++generation;
    get("loading").textContent = "Loading simulated insights...";
    get("error").hidden = true;
    try {
      const value = await load();
      if (current === generation) apply(value);
    } catch (error) {
      if (current === generation) errorMessage(error);
    } finally {
      if (current === generation) get("loading").textContent = "";
    }
  }
  function renderPage(page: DatabasePage) {
    const container = get("databases");
    container.replaceChildren();
    get("count").textContent = `Showing ${page.items.length} of ${page.total} databases`;
    if (!page.items.length) {
      container.append(element("p", "No databases match these filters."));
      return;
    }
    const table = element("table");
    const head = element("thead");
    const titles = element("tr");
    for (const title of ["Database / route", "Health", "Lag", "Last successful sync (UTC)",
                          "Storage used / allocated", "Throughput"]) {
      const th = element("th", title); th.scope = "col"; titles.append(th);
    }
    head.append(titles);
    const body = element("tbody");
    for (const record of page.items) {
      const row = element("tr");
      const identity = element("td");
      const open = element("button", record.name, "database-link");
      open.dataset.database = record.id;
      open.addEventListener("click", () => void openDetails(record));
      identity.append(open, element("small", `${record.source} → ${record.target}`, "route"));
      const status = element("td");
      status.append(element("span", record.status ?? "unknown", `badge ${record.status ?? "unknown"}`));
      row.append(identity, status, element("td", measurement(record.lag_seconds, "s")),
        element("td", record.last_success_at ?? "Unknown"),
        element("td", `${measurement(record.storage_used_gib, "GiB")} / ${measurement(record.storage_allocated_gib, "GiB")}`),
        element("td", measurement(record.throughput_mib_per_second, "MiB/s")));
      body.append(row);
    }
    table.append(head, body); container.append(table);
  }
  function renderDashboard(value: DashboardPayload) {
    state = value;
    get<HTMLSelectElement>("scenario").value = value.scenario_id;
    get<HTMLSelectElement>("status-filter").value = "";
    get<HTMLSelectElement>("environment-filter").value = "";
    get("snapshot").textContent = `As of ${value.as_of} · ${value.snapshot_id}`;
    get("details").hidden = true;
    const summary = get("summary");
    summary.replaceChildren();
    const items = [
      ["Databases", value.summary.total_databases],
      ["Critical", value.summary.health_counts.critical ?? 0],
      ["Stale syncs", value.summary.stale_databases],
      ["Failed runs · 24h", value.summary.failed_runs_24h],
    ];
    for (const [label, count] of items) {
      const card = element("article", "", "card");
      card.append(element("p", String(label), "muted"), element("strong", String(count)));
      summary.append(card);
    }
    renderPage(value.databases);
    get("loading").textContent = "";
  }
  function renderDetails(value: DatabaseDetails, histories: MetricHistory[]) {
    const target = get("details");
    target.hidden = false; target.replaceChildren();
    target.append(element("h2", value.database.name), element("p",
      `${value.database.environment} · ${value.database.engine} · ${value.database.replication_method}`,
      "muted"));
    const reasons = element("ul", "", "reasons");
    for (const [dimension, health] of Object.entries(value.database.health ?? {})) {
      reasons.append(element("li", `${dimension}: ${health.status} — ${health.reason}`));
    }
    target.append(reasons, element("p",
      `Expected sync interval: ${value.database.expected_sync_interval_seconds}s · Failed runs in last 24h: ${value.database.failed_runs_24h}`));
    const trends = element("div", "", "trends");
    trends.append(...histories.map(chart));
    target.append(trends, element("h3", "Simulated incidents"));
    if (!value.incidents.length) target.append(element("p", "No incidents in this simulated snapshot"));
    for (const incident of value.incidents) {
      target.append(element("h4", `${incident.severity}: ${incident.title}`),
        element("p", incident.description), element("small", incident.at));
    }
  }
  async function openDetails(database: DatabaseRecord) {
    const pinned = request();
    const metrics: HistoryQuery["metric"][] = [
      "lag_seconds", "throughput_mib_per_second", "storage_used_gib",
    ];
    await run(async () => {
      const detail = await bridge.callTool("get_database_details",
        { request: pinned, database_id: database.id });
      const histories = await Promise.all(metrics.map((metric) => bridge.callTool("get_metric_history",
        { query: { ...pinned, database_id: database.id, metric, hours: 24 } })));
      return { detail, histories };
    }, ({ detail, histories }) => renderDetails(detail, histories));
  }
  function changeScenario() {
    const scenario = get<HTMLSelectElement>("scenario").value;
    if (!["healthy", "lagging", "outage", "capacity"].includes(scenario)) {
      errorMessage(new Error("Unknown scenario")); return;
    }
    const scenario_id = scenario as SnapshotRequest["scenario_id"];
    void run(() => bridge.callTool("show_dashboard", { request: { scenario_id } }), renderDashboard);
  }
  function filter() {
    if (!state) return;
    const status = get<HTMLSelectElement>("status-filter").value;
    const environment = get<HTMLSelectElement>("environment-filter").value;
    const query = {
      ...request(), status: status ? status as "healthy" | "warning" | "critical" | "unknown" : null,
      environment: environment ? environment as "production" | "staging" : null, offset: 0, limit: 20,
    };
    get("details").hidden = true;
    void run(() => bridge.callTool("list_databases", { query }), renderPage);
  }
  get("scenario").addEventListener("change", changeScenario);
  get("refresh").addEventListener("click", changeScenario);
  get("status-filter").addEventListener("change", filter);
  get("environment-filter").addEventListener("change", filter);
  bridge.onInitialResult((value) => { if (generation === 0) renderDashboard(value); });
  bridge.onError?.(errorMessage);
  void bridge.connect().catch(errorMessage);
}
