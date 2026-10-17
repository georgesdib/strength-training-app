"""Shared fixtures.

Tests fall into two groups:

* pure unit tests that build tiny frames in memory (fast, no repo data);
* `integration` tests that read the real CSVs in `data/raw`. Those are allowed to
  be slow but must stay deterministic — they assert measured facts recorded in
  docs/EVIDENCE.md, so a silent change in cleaning shows up as a test failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def data_available() -> bool:
    from strength_coach.utils import paths

    return paths.training_log_csv().exists() and paths.readiness_csv().exists()


@pytest.fixture(scope="session")
def training_frame(data_available):
    """Real training log, raw strings, untouched by cleaning."""
    if not data_available:
        pytest.skip("raw CSVs not present")
    from strength_coach.utils import io_utils

    return io_utils.read_training_log()


@pytest.fixture(scope="session")
def readiness_frame(data_available):
    if not data_available:
        pytest.skip("raw CSVs not present")
    from strength_coach.utils import io_utils

    return io_utils.read_readiness()
