import { McpDashboardBridge } from "./bridge";
import { mountDashboard } from "./dashboard";
import "./styles.css";

const root = document.getElementById("app");
if (!root) throw new Error("Dashboard root is missing");
mountDashboard(root, new McpDashboardBridge());
