# Replication Insights

A Microsoft 365 Copilot declarative agent with a local, Entra-protected Python
FastMCP server and an embedded MCP App dashboard. **All operational data is
simulated. No databases are created or connected.**

The agent is scaffolded and managed using the official Microsoft Work IQ Dev
Tools (`wiqd@wiqd` from `microsoft/wiqd`). It retains VS Code Agents Toolkit
manifests and lifecycle files. Copilot provides orchestration; there is no custom
Agents SDK runtime.

## What is implemented

Six fictional databases and four deterministic scenarios (`healthy`, `lagging`,
`outage`, `capacity`), seven read-only MCP tools, and a self-contained dashboard
with estate indicators, health/environment filters, database details, 24-hour
synthetic trends, incidents, scenario switching, and refresh.

All results carry `simulated: true`. Related queries reuse a `snapshot_id` and
UTC `as_of`; the scenario catalogue is not a snapshot. Missing metrics remain
unknown, never zero. Lag above 300/900 seconds is warning/critical; storage at
80%/90% is warning/critical. Freshness is separately evaluated against the expected
sync interval. A failed replication service is critical.

**Tenant setup and development OAuth are verified.** Secretless Entra
registrations, the protected public tunnel, native SSO auth registration,
personal agent installation, and real delegated development OAuth are working.
The user also confirmed Copilot-native SSO, inline dashboard controls, and
scenario-based answers in the installed Copilot view. `agent\env\.env.offline`
contains explicitly synthetic packaging IDs: never provision, upload, or
publish its package.

## Prerequisites and restore

Use Python 3.12+, `uv`, Node 22.12+ (dashboard), PowerShell 7, VS Code with
Microsoft 365 Agents Toolkit, and Microsoft Dev Tunnels. The official WIQD
0.18 CLI needs Node 24.15+; it can run in an isolated user-local installation
without switching the machine's Node runtime. You also need an appropriate
Microsoft 365 Copilot license, custom-app upload permission, and permission to
register/consent Entra applications.

From the repository root:

```powershell
uv sync --project server --python 3.12
Push-Location .\dashboard
npm ci
npm run build
Pop-Location
Copy-Item .env.example .env
```

On Windows ARM machines choose an **x64 Python interpreter** if native dependency
wheels are unavailable for ARM. The development lock was resolved against the
machine's configured Microsoft package mirror; its URLs are recorded in
`server\uv.lock`. Outside that environment, regenerate the lock against your
approved registry rather than disabling certificate verification:

```powershell
uv lock --project server --default-index https://pypi.org/simple
uv sync --project server --python <path-to-supported-python>
```

The checked-in `scripts\wiqd.ps1` prefers
`$HOME\.copilot\tools\wiqd\wiqd.ps1` (the isolated installation used here), then
falls back to `wiqd` on PATH. Install Microsoft's official `wiqd@wiqd` plugin
from `microsoft/wiqd`; do not substitute workplace-data Work IQ tools. In this
host the newly installed skill was not registered, so implementation followed
the actual installed official skill/workflow files and CLI directly.
The matching `scripts\devtunnel.ps1` wrapper prefers
`$HOME\.copilot\tools\devtunnel\devtunnel.exe`, then `devtunnel` on PATH.

## Entra: resource server and Copilot SSO

These steps modify tenant security configuration. Perform them only in your
intended development tenant with its administrator's authorization. Never paste
tokens or secrets into chat, source control, dashboard code, or command output.

1. Register a **single-tenant API application** securing this server. Expose the
   delegated `Replication.Read` scope under its Application ID URI. Set the API's
   requested access-token version to **2**; the verifier intentionally rejects
   v1 tokens, ID tokens, role-only tokens and tokens from other tenants.
   Once the tunnel origin is known, also add its exact canonical MCP URL
   (`https://<actual-tunnel-host>/mcp`, with no trailing slash) to the API's
   `identifierUris`, retaining the original API URI. MCP OAuth clients send
   this HTTPS URL as the RFC 8707 `resource`; Entra rejects token exchange with
   `AADSTS9010010` if it does not resolve to this same API registration.
   [Microsoft's MCP registration guidance](https://learn.microsoft.com/entra/agent-id/secure-mcp-server-with-entra-id)
   explains the v2-token prerequisite and exact resource-URI matching.
2. Populate root `.env`: tenant ID, API client ID, exact identifier URI, scope,
   stable public origin, and a JSON array of explicitly accepted audiences.
   Include only the actual intended API and SSO audiences. Do not put an OAuth
   development client's ID or the token-store client ID in `aud` merely because
   it is an authorized caller. There is no wildcard or anonymous fallback.
3. Synchronize nonsecret values into the ignored local agent environment:

   ```powershell
   .\server\.venv\Scripts\python.exe .\scripts\check-config.py --sync-agent-env --before-provision
   ```

   This preserves generated app/auth IDs. Both generated lifecycles use
   `identityProvider: MicrosoftEntra`, the same `/mcp` URL, and the API's scope.
   The generated plugin uses `OAuthPluginVault` and dynamic tool discovery.
4. Use WIQD's local provisioning lifecycle (below) to create the SSO auth config,
   or create/manage it in Teams Developer Portal under **Microsoft Entra SSO
   client ID registration**. Use the API application client ID and exact MCP
   URL. Restrict access to the intended organization/app where supported. If
   registering manually, store its auth-config ID in the ignored
   `agent\env\.env.local.user` as `MCP_DA_AUTH_ID_REPLICATIO`.
5. Copy the **Application ID URI generated by the SSO auth config** into the API
   application's `identifierUris` without removing the original API URI or
   canonical HTTPS MCP URI. Add
   `https://teams.microsoft.com/api/platform/v1.0/oAuthConsentRedirect` as a **Web**
   redirect. Under **Expose an API**, preauthorize Microsoft Enterprise token
   store client `ab3be6b7-f5df-413d-ac2d-abf1e3fd9c0b` for the delegated scope.
6. Add the generated SSO URI to `ENTRA_ACCEPTED_AUDIENCES`. Update the auth
   config's scope if required by that identifier URI, align `ENTRA_IDENTIFIER_URI`
   and `MCP_RESOURCE_SCOPE`, resynchronize, and restart the server. Confirm the
   actual v2 token audience during real sign-in without logging the token.
   Creating the auth config alone does **not** finish SSO configuration.

The resource server has **no client secret**. All authorized demo users see the
same synthetic estate. JWT signatures use Entra JWKS, exact tenant v2 issuer,
explicit audiences, expiration/not-before and delegated-scope checks.

See [Microsoft's Entra SSO setup](https://learn.microsoft.com/microsoft-365/copilot/extensibility/plugin-authentication-entra-sso)
for the authoritative token-store registration steps.

## Separate OAuth development client

Entra does **not** support dynamic client registration. Register a separate
single-tenant **public development client** and grant its delegated access to
the API's `Replication.Read` scope, with consent as required by tenant policy.
Set `DEV_OAUTH_CLIENT_ID` in root `.env` for your reference; it is not an API
audience. Configure the approved public-client/PKCE redirect for your client:
Agents Toolkit tool-fetching uses `https://vscode.dev/redirect`.

The checked-in `.vscode\mcp.json` uses VS Code's supported `oauth.clientId`
setting. Start it manually using **MCP: List Servers**, provide the exact public
origin and development client ID, and complete the host's browser sign-in.
The host manages tokens; neither this dashboard nor its bridge handles them.
Use the exact callback emitted by your VS Code version if it differs, and
register that callback using the appropriate Entra public-client platform.

Agents Toolkit currently cannot fetch tools using Copilot Entra SSO. Use this
separate OAuth development connection for discovery. If adding a separate
OAuth-authenticated Copilot plugin for testing, its callback is
`https://teams.microsoft.com/api/platform/v1.0/oAuthRedirect`; keep that distinct
from SSO's `oAuthConsentRedirect`. Confidential-client secrets, if your chosen
host requires one, belong only in the host's secure credential store or an
ignored `.env.*.user`, never the public server settings.

## Stable HTTPS tunnel and local server

Create a persistent Dev Tunnel only after authorizing that external exposure:

```powershell
.\scripts\devtunnel.ps1 user login --entra --use-device-code-auth
.\scripts\devtunnel.ps1 create replication-insights --allow-anonymous
.\scripts\devtunnel.ps1 port create <returned-tunnel-id> -p 8000 --protocol http
.\scripts\devtunnel.ps1 host <returned-tunnel-id> --origin-header unchanged
```

Use the actual **port-specific HTTPS forwarding origin** as
`MCP_PUBLIC_BASE_URL`, not the inspection URL or a guessed hostname. Anonymous
tunnel transport allows Copilot to reach the API; `/mcp` remains Entra-protected.
Keep the listener loopback-only. Never expose an unprotected replacement server.
Preserve the incoming `Origin` header so the widget's exact CORS origin is not
rewritten to localhost by the tunnel.
Resynchronize agent configuration after every hostname change; existing token
store registrations must also be updated if their base URL changes.

```powershell
.\server\.venv\Scripts\python.exe .\scripts\check-config.py
.\server\.venv\Scripts\python.exe -m replication_insights.server
```

Before the first auth config is created, use `--before-provision` to check all
other configuration; the ordinary check correctly rejects a missing vault ID.
The default server port is 8000 (`MCP_PORT` overrides it). A dashboard build is
mandatory. OAuth protected-resource metadata is public at
`/.well-known/oauth-protected-resource/mcp`; data tools and the HTML resource
require a valid delegated token.

CORS permits only
`https://SHA256(public-hostname).widget-renderer.usercontent.microsoft.com`.
The MCP App bundles all scripts/styles, has empty outbound resource/connect
allowlists, and calls tools only through the host bridge. No CDN, direct data
HTTP fetch, browser token storage, or database connection is used.
JSON Schema validators are generated at build time, so dashboard initialization
and validation do not require CSP `unsafe-eval`.

## Agents Toolkit and official WIQD lifecycle

Open `replication-insights.code-workspace` to expose both the root Python/
dashboard folder and the nested `agent` Toolkit project. Tasks build the
dashboard, check configuration, run the protected server, and host an **existing**
tunnel in visible terminals. F5's Python profile builds the dashboard first.
Nothing provisions resources or starts a local service merely by opening it.
The official agent LSP is launched through the isolated WIQD wrapper.

Offline structural checks do not contact/provision your tenant:

```powershell
.\scripts\wiqd.ps1 agent validate --path .\agent --env offline --json --skill wiqd --workflow wiqd-core
.\scripts\wiqd.ps1 agent package --path .\agent --env offline --json --skill wiqd --workflow wiqd-core
```

After explicit authorization for the intended tenant and personal development
installation:

```powershell
.\scripts\wiqd.ps1 auth login --interactive
.\scripts\wiqd.ps1 agent provision --path .\agent --env local --json --skill wiqd --workflow wiqd-core
```

On Windows, WIQD normally uses the native sign-in broker. If no dialog appears,
the documented `config set disableBrokeredAuth=true` switches to browser
authentication. This is a **shared WIQD setting**, not a project setting:
record its original value and restore it after sign-in. If the key was
originally absent, `config set disableBrokeredAuth=false` removes it again.
Use **Use another account** when necessary and verify the resulting identity
with `auth status --json` before provisioning.

Provisioning is a **tenant write** and the generated `copilotAgent/publish` step
installs the personal development agent; it is not an offline build. The
preflight blocks the offline fixture. Finish the SSO URI/preauthorization steps
above before expecting calls to work. Replace generated developer/contact
example metadata before distributing the agent. Do not run the separate
`publish` lifecycle, share the agent, or target tenant scope as a testing shortcut.

## Local verification and demo prompts

```powershell
.\server\.venv\Scripts\python.exe -m pytest server\tests -q
.\server\.venv\Scripts\ruff.exe check server scripts
.\server\.venv\Scripts\python.exe scripts\export-contracts.py --check
Push-Location .\dashboard
npm run check:contracts
npm run typecheck
npm test -- --run
npm run build
Pop-Location
```

Observed local evidence: **56 Python tests**, **13 frontend tests**, type/schema
and lint checks, single-file production build, and official WIQD offline static
validation/package. A real local server process returned **200** for public
metadata and **401** for an unauthenticated MCP call, then was stopped.
That smoke check used synthetic configuration. Cryptographic
tests use locally signed RSA tokens, not real tenant tokens. The dependency emits
an Authlib deprecation warning; bundling reports third-party Zod comment
annotation warnings. Neither is hidden.

Observed tenant evidence: the real public endpoint serves protected-resource
metadata, denies unauthenticated MCP calls, and accepts the exact widget CORS
origin. Secretless authorization-code/PKCE sign-in using the separate development
client exercised all seven protected tools, all four scenarios, coherent
snapshot reads, and the protected dashboard HTML. Tokens stayed in process-local
memory; signature-verified claims confirmed the selected tenant, API client-ID
audience, v2 token version, and `Replication.Read`. This is not evidence of
Copilot-native SSO or inline rendering by itself.

User-confirmed Copilot acceptance: the inline lagging dashboard rendered;
scenario switching, filters, database drill-down and refresh worked. Staleness,
the finance outage, capacity pressure and storage-trend prompts produced
answers clearly labeled as simulated. This was manual acceptance in the
installed Copilot view, not an automated browser test. The VS Code-specific
OAuth UI has not been separately exercised; its static-client configuration
is provided, while real development OAuth was exercised using FastMCP.

The optional WIQD `agent ask --env local` check could not resolve its generated
title-based agent ID through the Work IQ provider in this installation.
The official `agent info` lookup and the personal Copilot link worked; the
Copilot view was used for runtime acceptance. No unrelated authentication
caches were cleared to work around the headless command.

Try: "Show the lagging replication dashboard", "Which databases are stale and
why?", "Explain the finance replication outage", and "Show capacity pressure and
storage trends." The agent must identify the data as simulated and must not
claim repairs or real operational outcomes.

If calls return 401, check v2 issuer, exact `aud`, tenant and `scp`, expiry,
token-store preauthorization, consent and the two distinct callbacks. Never
disable auth to fix discovery. If the widget fails, check the built bundle,
exact tunnel hostname/CORS hash, resource URI metadata, and host MCP App support.
If a scenario/filter result is late, the UI ignores it rather than replacing a
newer selection. Tool audit events include generated correlation IDs, tool names,
bounded scenario/snapshot identifiers, elapsed time and error classes, not raw
arguments, bearer tokens or headers.
