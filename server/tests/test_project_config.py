import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def checker():
    path = ROOT / "scripts" / "check-config.py"
    assert path.is_file(), "Project configuration checker is not implemented"
    spec = importlib.util.spec_from_file_location("project_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_project


@pytest.fixture
def project(tmp_path):
    package = tmp_path / "agent" / "appPackage"
    package.mkdir(parents=True)
    for name in ("declarativeAgent.json", "ai-plugin.json", "manifest.json"):
        shutil.copyfile(ROOT / "agent" / "appPackage" / name, package / name)
    for name in ("m365agents.yml", "m365agents.local.yml"):
        shutil.copyfile(ROOT / "agent" / name, tmp_path / "agent" / name)
    return tmp_path


@pytest.fixture
def config():
    return {
        "ENTRA_TENANT_ID": "11111111-1111-4111-8111-111111111111",
        "ENTRA_API_CLIENT_ID": "22222222-2222-4222-8222-222222222222",
        "ENTRA_ACCEPTED_AUDIENCES": json.dumps(
            [
                "22222222-2222-4222-8222-222222222222",
                "api://22222222-2222-4222-8222-222222222222",
            ]
        ),
        "ENTRA_IDENTIFIER_URI": "api://22222222-2222-4222-8222-222222222222",
        "ENTRA_REQUIRED_SCOPE": "Replication.Read",
        "MCP_PUBLIC_BASE_URL": "https://replication-demo.example.net",
    }


@pytest.fixture
def agent_config(config):
    return {
        "MCP_PUBLIC_BASE_URL": config["MCP_PUBLIC_BASE_URL"],
        "MCP_DA_OAUTH_CLIENT_ID_REPLICATIO": config["ENTRA_API_CLIENT_ID"],
        "MCP_DA_AUTH_ID_REPLICATIO": "33333333-3333-4333-8333-333333333333",
        "MCP_RESOURCE_SCOPE": f"{config['ENTRA_IDENTIFIER_URI']}/Replication.Read",
    }


def test_matching_server_plugin_and_lifecycle_configuration_passes(project, config, agent_config):
    assert checker()(project, config, agent_config) == []


def test_changed_tunnel_requires_updating_agent_configuration(project, config, agent_config):
    config["MCP_PUBLIC_BASE_URL"] = "https://changed.example.net"
    assert any("MCP URL" in error for error in checker()(project, config, agent_config))


def test_mismatched_sso_api_client_is_rejected(project, config, agent_config):
    agent_config["MCP_DA_OAUTH_CLIENT_ID_REPLICATIO"] = config["ENTRA_TENANT_ID"]
    assert any("client ID" in error for error in checker()(project, config, agent_config))


@pytest.mark.parametrize("reference", ["", "${{MISSING}}", "REPLACE_ME", "example-auth-id"])
def test_unresolved_auth_references_are_not_ready(project, config, agent_config, reference):
    agent_config["MCP_DA_AUTH_ID_REPLICATIO"] = reference
    assert any("auth reference" in error for error in checker()(project, config, agent_config))


def test_declared_action_must_reference_an_existing_plugin(project, config, agent_config):
    path = project / "agent" / "appPackage" / "declarativeAgent.json"
    data = json.loads(path.read_text())
    data["actions"][0]["file"] = "missing-plugin.json"
    path.write_text(json.dumps(data))
    assert any("plugin" in error for error in checker()(project, config, agent_config))


def test_wrong_explicit_widget_origin_is_rejected(project, config, agent_config):
    config["MCP_WIDGET_ORIGIN"] = "https://wrong.widget-renderer.usercontent.microsoft.com"
    assert any("widget origin" in error for error in checker()(project, config, agent_config))


def test_offline_fixture_cannot_be_provisioned(project, config, agent_config):
    agent_config["TEAMSFX_ENV"] = "offline"
    assert any("offline" in error.lower() for error in checker()(project, config, agent_config))


def test_no_database_or_azure_hosting_provisioning_is_present(project):
    for name in ("m365agents.yml", "m365agents.local.yml"):
        lifecycle = (project / "agent" / name).read_text()
        assert "check-config.py" in lifecycle
        assert "arm/deploy" not in lifecycle
        assert "azure/cli" not in lifecycle
        assert "sqlcmd" not in lifecycle
