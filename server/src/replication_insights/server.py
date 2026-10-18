import hashlib
import logging
import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, ResourceCSP
from fastmcp.server.auth import RemoteAuthProvider
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from .auth import build_auth, load_auth_settings
from .insights import InsightsService
from .mock_data import SCENARIOS
from .models import (
    DashboardPayload,
    DatabaseDetails,
    DatabasePage,
    DatabaseQuery,
    EstateSummary,
    HistoryQuery,
    IncidentPage,
    MetricHistory,
    ScenarioCatalogue,
    SnapshotRequest,
)

VIEW_URI = "ui://replication-insights/dashboard.html"
READ_ONLY = {"readOnlyHint": True}


def create_server(
    service: InsightsService,
    auth: RemoteAuthProvider,
    dashboard_html: Path,
) -> FastMCP:
    if not dashboard_html.is_file():
        raise FileNotFoundError(
            f"Missing dashboard bundle: {dashboard_html}. Run npm --prefix dashboard run build."
        )
    mcp = FastMCP("Replication Insights - Demo / simulated data", auth=auth)

    @mcp.tool(annotations=READ_ONLY)
    def list_demo_scenarios() -> ScenarioCatalogue:
        """List repeatable simulated scenarios. No real databases are contacted."""
        return SCENARIOS.model_copy(deep=True)

    @mcp.tool(annotations=READ_ONLY)
    def get_estate_summary(request: SnapshotRequest) -> EstateSummary:
        """Summarize simulated estate health. Reuse the snapshot_id for related reads."""
        return service.summary(request)

    @mcp.tool(annotations=READ_ONLY)
    def list_databases(query: DatabaseQuery) -> DatabasePage:
        """List mock databases by status/environment with bounded pagination."""
        return service.databases(query)

    @mcp.tool(annotations=READ_ONLY)
    def get_database_details(request: SnapshotRequest, database_id: str) -> DatabaseDetails:
        """Explain mock database health, synchronization freshness, lag, capacity, and incidents."""
        return service.database(request, database_id)

    @mcp.tool(annotations=READ_ONLY)
    def get_metric_history(query: HistoryQuery) -> MetricHistory:
        """Read 1-, 6-, or 24-hour synthetic metric history, with explicit units and unknowns."""
        return service.history(query)

    @mcp.tool(annotations=READ_ONLY)
    def list_incidents(request: SnapshotRequest, database_id: str | None = None) -> IncidentPage:
        """List simulated replication incidents for the estate or one known database."""
        return service.incidents(request, database_id)

    @mcp.tool(annotations=READ_ONLY, app=AppConfig(resource_uri=VIEW_URI))
    def show_dashboard(request: SnapshotRequest) -> DashboardPayload:
        """Open the interactive simulated replication dashboard with a coherent snapshot."""
        snapshot = service.snapshot(request)
        pinned = SnapshotRequest(scenario_id=snapshot.scenario_id, snapshot_id=snapshot.snapshot_id)
        summary = service.summary(pinned)
        return DashboardPayload(
            **summary.model_dump(include={"scenario_id", "snapshot_id", "as_of", "simulated"}),
            summary=summary,
            databases=service.databases(DatabaseQuery(**pinned.model_dump())),
        )

    @mcp.resource(
        VIEW_URI,
        mime_type="text/html;profile=mcp-app",
        app=AppConfig(csp=ResourceCSP(connect_domains=[], resource_domains=[])),
    )
    def dashboard() -> str:
        """Bundled replication insights MCP App; data access uses the authenticated host bridge."""
        return dashboard_html.read_text(encoding="utf-8")

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = load_auth_settings()
    bundle = Path(__file__).resolve().parents[3] / "dashboard" / "dist" / "index.html"
    mcp = create_server(InsightsService(), build_auth(settings), bundle)
    hostname = settings.public_base_url.host
    digest = hashlib.sha256(hostname.encode("utf-8")).hexdigest()
    origin = f"https://{digest}.widget-renderer.usercontent.microsoft.com"
    port = int(os.environ.get("MCP_PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("MCP_PORT must be between 1 and 65535")
    mcp.run(
        transport="http",
        host="127.0.0.1",
        port=port,
        path="/mcp",
        stateless_http=True,
        json_response=True,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=[origin],
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                    "MCP-Protocol-Version",
                    "Mcp-Session-Id",
                ],
                expose_headers=["Mcp-Session-Id", "WWW-Authenticate"],
            )
        ],
    )


if __name__ == "__main__":
    main()
