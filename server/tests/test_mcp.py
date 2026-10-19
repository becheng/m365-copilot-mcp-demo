import json
import logging
from datetime import UTC, datetime

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import RemoteAuthProvider
from pydantic import AnyHttpUrl
from test_auth import settings, token, verifier


def make_server(tmp_path):
    from replication_insights.insights import InsightsService
    from replication_insights.server import create_server

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    config = settings()
    auth = RemoteAuthProvider(
        token_verifier=verifier(key),
        base_url=str(config.public_base_url),
        authorization_servers=[AnyHttpUrl(config.issuer)],
        scopes_supported=[f"{config.identifier_uri}/Replication.Read"],
    )
    html = tmp_path / "dashboard.html"
    html.write_text("<!doctype html><html><body>Demo / simulated data</body></html>")
    service = InsightsService(clock=lambda: datetime(2026, 10, 18, 21, 0, tzinfo=UTC))
    return create_server(service, auth, html), key


async def test_tool_contracts_share_snapshots_and_read_only_annotations(tmp_path):
    mcp, _ = make_server(tmp_path)
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {
            "list_demo_scenarios",
            "get_estate_summary",
            "list_databases",
            "get_database_details",
            "get_metric_history",
            "list_incidents",
            "show_dashboard",
        }
        assert all(tool.annotations.readOnlyHint is True for tool in tools)
        for scenario in ("healthy", "lagging", "outage", "capacity"):
            result = await client.call_tool(
                "get_estate_summary", {"request": {"scenario_id": scenario}}
            )
            summary = result.structured_content
            result = await client.call_tool(
                "show_dashboard",
                {
                    "request": {
                        "scenario_id": scenario,
                        "snapshot_id": summary["snapshot_id"],
                    }
                },
            )
            dashboard = result.structured_content
            assert dashboard["simulated"] is True
            assert dashboard["summary"] == summary
            assert len(dashboard["databases"]["items"]) == summary["total_databases"]
        result = await client.call_tool("list_demo_scenarios")
        assert len(result.structured_content["scenarios"]) == 4


async def test_bad_input_is_a_tool_error_not_a_fallback(tmp_path):
    mcp, _ = make_server(tmp_path)
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Unknown database"):
            await client.call_tool(
                "get_database_details",
                {
                    "request": {"scenario_id": "healthy"},
                    "database_id": "missing",
                },
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "list_databases", {"query": {"scenario_id": "healthy", "limit": 101}}
            )


async def test_dashboard_resource_is_linked_and_has_mcp_app_mime_type(tmp_path):
    mcp, _ = make_server(tmp_path)
    async with Client(mcp) as client:
        tools = await client.list_tools()
        dashboard = next(tool for tool in tools if tool.name == "show_dashboard")
        assert dashboard.meta["ui"]["resourceUri"] == "ui://replication-insights/dashboard.html"
        resources = await client.read_resource("ui://replication-insights/dashboard.html")
        assert resources[0].mimeType == "text/html;profile=mcp-app"
        assert "Demo / simulated data" in resources[0].text


async def test_http_metadata_is_public_but_mcp_requires_valid_access_token(tmp_path):
    mcp, key = make_server(tmp_path)
    app = mcp.http_app(path="/mcp", stateless_http=True, json_response=True)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://replication-demo.example.com"
        ) as client,
    ):
        response = await client.get("/.well-known/oauth-protected-resource/mcp")
        assert response.status_code == 200
        assert response.json()["scopes_supported"][0].endswith("/Replication.Read")
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream"}
        for method in ("tools/list", "resources/read"):
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": method,
                    "params": {},
                },
                headers=headers,
            )
            assert response.status_code == 401
        response = await client.post(
            "/mcp",
            json=initialize,
            headers={
                **headers,
                "Authorization": f"Bearer {token(key)}",
            },
        )
        assert response.status_code == 200
        assert "serverInfo" in response.json()["result"]


def test_missing_dashboard_build_fails_explicitly(tmp_path):
    from replication_insights.auth import build_auth
    from replication_insights.insights import InsightsService
    from replication_insights.server import create_server

    with pytest.raises(FileNotFoundError, match="dashboard"):
        create_server(InsightsService(), build_auth(settings()), tmp_path / "missing.html")


async def test_tool_audit_logs_have_safe_context_timing_and_errors(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="replication_insights.audit")
    mcp, _ = make_server(tmp_path)
    async with Client(mcp) as client:
        await client.call_tool("get_estate_summary", {"request": {"scenario_id": "healthy"}})
        with pytest.raises(ToolError):
            await client.call_tool(
                "get_database_details",
                {
                    "request": {"scenario_id": "outage"},
                    "database_id": "do-not-log-arguments",
                },
            )
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "replication_insights.audit"
    ]
    assert len(events) == 2
    assert events[0]["tool"] == "get_estate_summary"
    assert events[0]["scenario_id"] == "healthy"
    assert events[0]["snapshot_id"] == "v1:healthy:1792357200"
    assert events[0]["outcome"] == "success"
    assert events[1]["outcome"] != "success"
    assert all(event["duration_ms"] >= 0 and event["correlation_id"] for event in events)
    assert events[0]["correlation_id"] != events[1]["correlation_id"]
    assert "do-not-log-arguments" not in json.dumps(events)


async def test_invalid_scenario_shape_does_not_break_error_auditing(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="replication_insights.audit")
    mcp, _ = make_server(tmp_path)
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="scenario_id"):
            await client.call_tool("get_estate_summary", {"request": {"scenario_id": {}}})
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "replication_insights.audit"
    ]
    assert len(events) == 1
    assert events[0]["scenario_id"] is None
    assert events[0]["outcome"] != "success"
