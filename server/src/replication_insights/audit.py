import json
import logging
import re
from time import perf_counter
from uuid import uuid4

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams

logger = logging.getLogger(__name__)
TOOLS = {
    "list_demo_scenarios",
    "get_estate_summary",
    "list_databases",
    "get_database_details",
    "get_metric_history",
    "list_incidents",
    "show_dashboard",
}


class AuditMiddleware(Middleware):
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        started = perf_counter()
        arguments = context.message.arguments or {}
        requested = arguments.get("request", arguments.get("query", {}))
        requested = requested if isinstance(requested, dict) else {}
        event = {
            "correlation_id": str(uuid4()),
            "tool": context.message.name if context.message.name in TOOLS else "unknown",
            "outcome": "success",
        }
        result_context = requested
        try:
            result = await call_next(context)
            result_context = result.structured_content or requested
            return result
        except Exception as error:
            event["outcome"] = type(error).__name__
            raise
        finally:
            scenario = result_context.get("scenario_id")
            snapshot = result_context.get("snapshot_id")
            event["scenario_id"] = (
                scenario
                if isinstance(scenario, str)
                and scenario
                in {
                    "healthy",
                    "lagging",
                    "outage",
                    "capacity",
                }
                else None
            )
            event["snapshot_id"] = (
                snapshot
                if isinstance(snapshot, str)
                and re.fullmatch(r"v1:(healthy|lagging|outage|capacity):[0-9]{1,12}", snapshot)
                else None
            )
            event["duration_ms"] = round((perf_counter() - started) * 1000, 3)
            logger.info(json.dumps(event))
