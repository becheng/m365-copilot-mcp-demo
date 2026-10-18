# Replication Insights

A Microsoft 365 Copilot declarative agent with a local, Entra-protected Python
FastMCP server and an embedded MCP App dashboard. **All operational data is
simulated. No databases are created or connected.**

The agent is scaffolded and managed using the official Microsoft Work IQ Dev
Tools (`wiqd@wiqd` from `microsoft/wiqd`). It retains VS Code Agents Toolkit
manifests and lifecycle files. Copilot provides orchestration; there is no custom
Agents SDK runtime.

Implementation is in progress. `agent\env\.env.offline` is a synthetic packaging
fixture, not a tenant app registration. Never provision or publish that
environment. Actual local development requires your tenant's Entra registrations,
auth configuration, and a reachable HTTPS tunnel.
