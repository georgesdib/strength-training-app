"""Deployment units: the analytics maintenance worker follows backend deployments."""

from __future__ import annotations

import configparser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False)
    parser.read(ROOT / "deploy" / name)
    return parser


def test_maintenance_worker_uses_the_backend_checkout_and_venv():
    service = _unit("strength-analytics-maintenance.service")["Service"]
    assert service["WorkingDirectory"] == "/home/dsh/strength-training-app"
    assert service["ExecStart"].startswith("/home/dsh/strength-training-app/.venv/bin/python")
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
