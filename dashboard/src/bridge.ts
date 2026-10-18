import { App } from "@modelcontextprotocol/ext-apps";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import schema from "../schemas/responses.json";
import type {
  DashboardPayload, DatabaseDetails, DatabasePage, DatabaseQuery, EstateSummary,
  HistoryQuery, IncidentPage, MetricHistory, ScenarioCatalogue, SnapshotRequest,
} from "./contracts";

export type ToolContracts = {
  list_demo_scenarios: { args: Record<string, never>; result: ScenarioCatalogue };
  get_estate_summary: { args: { request: SnapshotRequest }; result: EstateSummary };
  list_databases: { args: { query: DatabaseQuery }; result: DatabasePage };
  get_database_details: {
    args: { request: SnapshotRequest; database_id: string }; result: DatabaseDetails;
  };
  get_metric_history: { args: { query: HistoryQuery }; result: MetricHistory };
  list_incidents: {
    args: { request: SnapshotRequest; database_id?: string }; result: IncidentPage;
  };
  show_dashboard: { args: { request: SnapshotRequest }; result: DashboardPayload };
};

export interface DashboardBridge {
  connect(): Promise<void>;
  onInitialResult(handler: (value: DashboardPayload) => void): void;
  onError?(handler: (error: unknown) => void): void;
  callTool<K extends keyof ToolContracts>(
    name: K, args: ToolContracts[K]["args"],
  ): Promise<ToolContracts[K]["result"]>;
}

const definitionNames: Record<keyof ToolContracts, string> = {
  list_demo_scenarios: "ScenarioCatalogue", get_estate_summary: "EstateSummary",
  list_databases: "DatabasePage", get_database_details: "DatabaseDetails",
  get_metric_history: "MetricHistory", list_incidents: "IncidentPage",
  show_dashboard: "DashboardPayload",
};
const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
ajv.addSchema(schema, "public");
const references = Object.fromEntries(Object.entries(definitionNames).map(
  ([name, definition]) => [name, { $ref: `public#/$defs/${definition}` }],
));

export function decodeResult<K extends keyof ToolContracts>(
  name: K, value: unknown,
): ToolContracts[K]["result"] {
  const validate = ajv.compile<ToolContracts[K]["result"]>(references[name]);
  if (!validate(value)) {
    throw new Error(`Invalid ${name} response: ${ajv.errorsText(validate?.errors)}`);
  }
  if (value.simulated !== true) throw new Error("Response is not marked as simulated data");
  const parsed: ToolContracts[keyof ToolContracts]["result"] = value;
  if ("summary" in parsed && (
    parsed.summary.snapshot_id !== parsed.snapshot_id ||
    parsed.databases.snapshot_id !== parsed.snapshot_id ||
    parsed.summary.scenario_id !== parsed.scenario_id ||
    parsed.databases.scenario_id !== parsed.scenario_id ||
    parsed.summary.as_of !== parsed.as_of || parsed.databases.as_of !== parsed.as_of
  )) throw new Error("Dashboard response contains inconsistent snapshots");
  return value;
}

export class McpDashboardBridge implements DashboardBridge {
  private app = new App({ name: "Replication Insights", version: "0.1.0" });
  private initial: (value: DashboardPayload) => void = () => {};
  private error: (error: unknown) => void = () => {};

  constructor() {
    this.app.ontoolresult = (result) => {
      try {
        this.initial(decodeResult("show_dashboard", result.structuredContent));
      } catch (error) { this.error(error); }
    };
  }

  onInitialResult(handler: (value: DashboardPayload) => void) { this.initial = handler; }
  onError(handler: (error: unknown) => void) { this.error = handler; }
  async connect() {
    await this.app.connect();
    const theme = this.app.getHostContext()?.theme;
    if (theme) document.documentElement.dataset.theme = theme;
  }
  async callTool<K extends keyof ToolContracts>(
    name: K, args: ToolContracts[K]["args"],
  ): Promise<ToolContracts[K]["result"]> {
    const result = await this.app.callServerTool({ name, arguments: args });
    if (result.isError) {
      const message = result.content.find((item) => item.type === "text");
      throw new Error(message?.type === "text" ? message.text : `${name} failed`);
    }
    return decodeResult(name, result.structuredContent);
  }
}
