"""Bash setup script syntax and help contract."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "setup-venv.sh"


def test_setup_venv_is_executable_and_parses() -> None:
    bash = shutil.which("bash")
    if bash is None:
        import pytest
        pytest.skip("bash is not installed")
    assert os.access(SCRIPT, os.X_OK)
    subprocess.run([bash, "-n", str(SCRIPT)], check=True, capture_output=True, text=True)


def test_setup_venv_help_does_not_create_a_venv() -> None:
    bash = shutil.which("bash")
    if bash is None:
        import pytest
        pytest.skip("bash is not installed")
    before = (ROOT / ".venv").exists()
    result = subprocess.run(
        [bash, str(SCRIPT), "--help"], check=True, capture_output=True, text=True
    )
    assert "Create .venv and install" in result.stdout
    assert "--locked" in result.stdout
    assert (ROOT / ".venv").exists() == before
