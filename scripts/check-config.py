"""Check local server/agent configuration without provisioning tenant resources."""

import argparse
import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values, set_key
from pydantic import ValidationError
from replication_insights.auth import AuthSettings

ROOT = Path(__file__).resolve().parents[1]
CLIENT_KEY = "MCP_DA_OAUTH_CLIENT_ID_REPLICATIO"
AUTH_KEY = "MCP_DA_AUTH_ID_REPLICATIO"


def widget_origin(hostname: str) -> str:
    digest = hashlib.sha256(hostname.encode("utf-8")).hexdigest()
    return f"https://{digest}.widget-renderer.usercontent.microsoft.com"


def expand(value: str, values: Mapping[str, str]) -> str:
    return re.sub(
        r"\$\{\{([A-Z0-9_]+)\}\}", lambda match: values.get(match[1], ""), value
    )


def check_project(
    root: Path,
    config: Mapping[str, str],
    agent_config: Mapping[str, str],
    *,
    before_provision: bool = False,
) -> list[str]:
    errors = []
    if agent_config.get("TEAMSFX_ENV") == "offline":
        errors.append(
            "The offline fixture must never be provisioned or used as a ready demo."
        )
    try:
        settings = AuthSettings(
            _env_file=None,
            **{
                **config,
                "ENTRA_ACCEPTED_AUDIENCES": json.loads(
                    config.get("ENTRA_ACCEPTED_AUDIENCES", "[]")
                ),
            },
        )
    except (ValidationError, json.JSONDecodeError) as error:
        if isinstance(error, ValidationError):
            errors.extend(
                f"Configure {'.'.join(map(str, item['loc']))}: {item['msg']}"
                for item in error.errors(include_input=False)
            )
        else:
            errors.append(
                "ENTRA_ACCEPTED_AUDIENCES must be a JSON array of exact audiences."
            )
        return errors
    expected_url = f"{str(settings.public_base_url).rstrip('/')}/mcp"
    expected_origin = widget_origin(settings.public_base_url.host)
    if config.get("MCP_WIDGET_ORIGIN", expected_origin) != expected_origin:
        errors.append(
            "Configured widget origin does not match the public MCP hostname."
        )
    if agent_config.get(CLIENT_KEY) != str(settings.api_client_id):
        errors.append("SSO client ID must equal ENTRA_API_CLIENT_ID.")
    scope = f"{settings.identifier_uri}/{settings.required_scope}"
    if agent_config.get("MCP_RESOURCE_SCOPE") != scope:
        errors.append(
            "MCP_RESOURCE_SCOPE must match the server's exposed delegated scope."
        )
    package = root / "agent" / "appPackage"
    try:
        declarative = json.loads(
            (package / "declarativeAgent.json").read_text(encoding="utf-8")
        )
        actions = declarative.get("actions", [])
        if not actions:
            errors.append("Declarative agent has no MCP plugin action.")
        for action in actions:
            path = (package / action["file"]).resolve()
            if not path.is_relative_to(package.resolve()):
                errors.append("MCP plugin must be inside appPackage.")
                continue
            plugin = json.loads(path.read_text(encoding="utf-8"))
            for runtime in plugin.get("runtimes", []):
                if expand(runtime["spec"]["url"], agent_config) != expected_url:
                    errors.append(
                        "Plugin MCP URL differs from MCP_PUBLIC_BASE_URL; resync agent env."
                    )
                auth = runtime.get("auth", {})
                reference = expand(auth.get("reference_id", ""), agent_config)
                placeholder = re.search(
                    r"\$\{|replace|placeholder|example|<|>", reference, re.IGNORECASE
                )
                if auth.get("type") != "OAuthPluginVault" or (
                    not before_provision and (not reference.strip() or placeholder)
                ):
                    errors.append(
                        "Resolve the OAuthPluginVault auth reference before packaging."
                    )
    except (OSError, KeyError, json.JSONDecodeError) as error:
        errors.append(f"Cannot resolve generated MCP plugin: {type(error).__name__}.")
    for filename in ("m365agents.yml", "m365agents.local.yml"):
        text = (root / "agent" / filename).read_text(encoding="utf-8")
        for url in re.findall(r"^\s*baseUrl:\s*(\S+)", text, re.MULTILINE):
            if expand(url, agent_config) != expected_url:
                errors.append(f"{filename} MCP URL differs from the server.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default="local")
    parser.add_argument("--before-provision", action="store_true")
    parser.add_argument(
        "--sync-agent-env",
        action="store_true",
        help="Copy only nonsecret server settings into the ignored local agent env",
    )
    args = parser.parse_args()
    if args.env == "offline":
        print("ERROR: offline is a structural packaging fixture; never provision it.")
        return 1
    if args.env != "local" and args.sync_agent_env:
        print(
            "ERROR: automatic synchronization is limited to the ignored local environment."
        )
        return 1
    config = {
        key: value
        for key, value in dotenv_values(ROOT / ".env").items()
        if value is not None
    }
    config.update(
        {
            key: value
            for key, value in os.environ.items()
            if key.startswith(("ENTRA_", "MCP_"))
        }
    )
    env_path = ROOT / "agent" / "env" / f".env.{args.env}"
    if args.sync_agent_env:
        required = [
            "MCP_PUBLIC_BASE_URL",
            "ENTRA_API_CLIENT_ID",
            "ENTRA_IDENTIFIER_URI",
            "ENTRA_REQUIRED_SCOPE",
        ]
        missing = [key for key in required if not config.get(key)]
        if missing:
            print(f"ERROR: set {', '.join(missing)} in the root .env first.")
            return 1
        updates = {
            "MCP_PUBLIC_BASE_URL": config["MCP_PUBLIC_BASE_URL"].rstrip("/"),
            CLIENT_KEY: config["ENTRA_API_CLIENT_ID"],
            "MCP_RESOURCE_SCOPE": f"{config['ENTRA_IDENTIFIER_URI']}/{config['ENTRA_REQUIRED_SCOPE']}",
        }
        for key, value in updates.items():
            set_key(env_path, key, value, quote_mode="never")
        print(
            "Synchronized nonsecret local agent settings; preserved generated app/auth IDs."
        )
    agent_config = {}
    for path in (env_path, env_path.with_name(f".env.{args.env}.user")):
        agent_config.update(
            {
                key: value
                for key, value in dotenv_values(path).items()
                if value is not None
            }
        )
    agent_config.update(
        {
            key: value
            for key, value in os.environ.items()
            if key.startswith(("MCP_", "TEAMSFX_"))
        }
    )
    agent_config["TEAMSFX_ENV"] = args.env
    errors = check_project(
        ROOT, config, agent_config, before_provision=args.before_provision
    )
    for error in errors:
        print(f"ERROR: {error}")
    if not errors:
        print(
            "Local configuration is consistent. This does not prove tenant consent or SSO."
        )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
