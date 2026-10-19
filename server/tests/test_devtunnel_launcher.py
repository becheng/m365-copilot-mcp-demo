import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(
    os.name != "nt" or POWERSHELL is None,
    reason="The Windows launcher requires PowerShell 7.",
)


@pytest.fixture
def launch_environment(tmp_path):
    home = tmp_path / "home"
    binary_path = tmp_path / "bin"
    home.mkdir()
    binary_path.mkdir()
    return {
        **{
            key: os.environ[key]
            for key in ("SystemRoot", "ComSpec", "TEMP", "TMP", "PATHEXT")
            if key in os.environ
        },
        "USERPROFILE": str(home),
        "PATH": str(binary_path),
    }


def run_launcher(environment, *arguments):
    launcher = ROOT / "scripts" / "devtunnel.ps1"
    assert launcher.is_file(), "Dev Tunnels launcher is missing"
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-File", str(launcher), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def install_test_cli(destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(os.environ["ComSpec"], destination)


def test_isolated_devtunnel_runs_without_a_global_path_entry(launch_environment):
    destination = (
        Path(launch_environment["USERPROFILE"])
        / ".copilot" / "tools" / "devtunnel" / "devtunnel.exe"
    )
    install_test_cli(destination)
    result = run_launcher(launch_environment, "/d", "/c", "echo isolated-tunnel")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "isolated-tunnel"


def test_global_devtunnel_fallback_preserves_cli_failure(launch_environment):
    install_test_cli(Path(launch_environment["PATH"]) / "devtunnel.exe")
    result = run_launcher(launch_environment, "/d", "/c", "exit 23")
    assert result.returncode == 23, result.stderr


def test_missing_devtunnel_fails_explicitly(launch_environment):
    result = run_launcher(launch_environment, "--version")
    assert result.returncode != 0
    assert "devtunnel" in result.stderr.lower()
