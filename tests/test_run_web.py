"""The web launcher script: local-only, and it forwards options correctly.

These tests run the shell script, not the server (which `test_web.py` covers). They pin the
two things a wrapper can get wrong: exposing the UI beyond loopback, and passing `--db` in a
position the CLI does not accept (it is a global option, so it must precede `web`).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-web.sh"


def run_launcher(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHON": sys.executable, "NO_COLOR": "1"}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
        env=env,
    )


def test_the_script_is_executable():
    assert os.access(SCRIPT, os.X_OK), "run-web.sh must be executable"


def test_a_non_loopback_host_is_accepted():
    for host in ("0.0.0.0", "192.168.1.5", "example.com"):
        result = run_launcher("--host", host, "--help")
        assert result.returncode == 0, host
        assert "refusing" not in result.stderr


def test_a_loopback_host_is_accepted_in_both_forms():
    for args in (("--host", "127.0.0.1"), ("--host=localhost",), ("--host", "::1")):
        result = run_launcher(*args, "--help")
        assert result.returncode == 0, args
        assert "refusing" not in result.stderr


def test_help_shows_the_wrapper_options_and_the_web_options():
    result = run_launcher("--help")
    assert result.returncode == 0
    assert "--no-open" in result.stdout
    assert "--port" in result.stdout
    assert "--open" in result.stdout  # from the underlying command


def test_missing_values_are_rejected_before_starting():
    for flag, expected in (("--db", "--db needs a value"), ("--host", "--host needs a value")):
        result = run_launcher(flag)
        assert result.returncode == 2
        assert expected in result.stderr
