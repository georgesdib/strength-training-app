"""Deployment units: the analytics maintenance worker follows backend deployments."""

from __future__ import annotations

import configparser
import os
import pwd
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False)
    parser.read(ROOT / "deploy" / name)
    return parser


def test_maintenance_worker_uses_the_backend_checkout_and_venv():
    service = _unit("strength-analytics-maintenance.service")["Service"]
    assert service["WorkingDirectory"] == "/home/dsh/strength-app/strength-training-app"
    assert service["ExecStart"].startswith(
        "/home/dsh/strength-app/strength-training-app/.venv/bin/python"
    )
    assert "strength_coach.cli" in service["ExecStart"]
    assert "--db data/coach.db" in service["ExecStart"]
    assert service["ExecStart"].endswith("analytics build")
    assert service["Type"] == "oneshot"
    assert int(service["TimeoutStartSec"]) <= 3600


def test_web_restart_triggers_one_maintenance_run():
    web = _unit("strength-coach-web.service")["Service"]
    post = web["ExecStartPost"]
    assert "strength-analytics-maintenance.service" in post
    assert post.startswith("-"), "a missing maintenance unit must not fail the web service"
    assert post.startswith("-/bin/systemctl --no-block start")


def test_timer_runs_periodically_and_on_boot():
    timer = _unit("strength-analytics-maintenance.timer")["Timer"]
    assert timer["OnBootSec"] == "5min"
    assert timer["OnUnitActiveSec"] == "15min"
    assert timer["Persistent"] == "true"


def test_worker_and_web_share_the_same_deployment_root():
    service = _unit("strength-analytics-maintenance.service")["Service"]
    web = _unit("strength-coach-web.service")["Service"]
    assert service["WorkingDirectory"] == web["WorkingDirectory"]
    assert service["User"] == web["User"]


def test_mcp_unit_passes_the_database_before_the_subcommand():
    service = _unit("strength-intelligence-mcp.service")["Service"]
    start = service["ExecStart"]
    # --db is a global CLI option. After the subcommand argparse rejects it and the unit exits.
    assert start.index("--db") < start.index("intelligence serve")
    assert start.endswith("intelligence.local.yaml")


INSTALLER = ROOT / "deploy" / "install-intelligence-mcp.sh"


def _run_installer(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALLER), *args], capture_output=True, text=True, check=False
    )


def test_mcp_installer_renders_the_host_unit():
    result = _run_installer("--print")
    assert result.returncode == 0, result.stderr
    unit = result.stdout
    assert "ExecStart=" in unit
    # A wrong option order makes argparse reject the unit at startup.
    assert unit.index("--db") < unit.index("intelligence serve")
    assert f"WorkingDirectory={ROOT}" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectHome=read-only" in unit
    expected_user = os.environ.get("SUDO_USER") or pwd.getpwuid(
        os.stat(ROOT).st_uid
    ).pw_name
    assert f"User={expected_user}" in unit


def test_mcp_installer_refuses_without_root():
    if os.geteuid() == 0:
        pytest.skip("running as root; the refusal path cannot be exercised")
    result = _run_installer()
    assert result.returncode != 0
    assert "root" in (result.stdout + result.stderr).lower()
