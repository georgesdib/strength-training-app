"""Canonical filesystem locations.

Every other module asks for paths through here instead of building strings, so a
data-directory move is a one-line change and tests can point at fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_ROOT = "STRENGTH_COACH_ROOT"


def repo_root() -> Path:
    """Repository root: $STRENGTH_COACH_ROOT if set, else the package's grandparent."""
    override = os.environ.get(ENV_ROOT)
    if override:
        return Path(override).expanduser().resolve()
    # strength_coach/utils/paths.py -> strength_coach/utils -> strength_coach -> root
    return Path(__file__).resolve().parents[2]


def data_dir(*parts: str) -> Path:
    return repo_root().joinpath("data", *parts)


def raw_data_dir() -> Path:
    return data_dir("raw")


def config_dir(*parts: str) -> Path:
    return repo_root().joinpath("config", *parts)


def docs_dir(*parts: str) -> Path:
    return repo_root().joinpath("docs", *parts)


# --- Named artifacts -------------------------------------------------------
# Same filenames the user supplied, so a refresh of the backup drops straight in.

TRAINING_LOG_CSV = "training_log.csv"
READINESS_CSV = "readiness.csv"

TAXONOMY_YAML = "exercises/taxonomy.v1.yaml"
PROGRAMME_RULES_YAML = "rules/programme.v1.yaml"
THRESHOLDS_YAML = "thresholds.v1.yaml"
READINESS_YAML = "readiness.v1.yaml"
SCHEMES_YAML = "schemes.v1.yaml"
UNDULATION_YAML = "undulation.v1.yaml"


def training_log_csv() -> Path:
    return raw_data_dir() / TRAINING_LOG_CSV


def readiness_csv() -> Path:
    return raw_data_dir() / READINESS_CSV


def taxonomy_yaml() -> Path:
    return config_dir(TAXONOMY_YAML)


def programme_rules_yaml() -> Path:
    return config_dir(PROGRAMME_RULES_YAML)


def thresholds_yaml() -> Path:
    return config_dir(THRESHOLDS_YAML)


def readiness_yaml() -> Path:
    return config_dir(READINESS_YAML)


def schemes_yaml() -> Path:
    return config_dir("templates", SCHEMES_YAML)


def undulation_yaml() -> Path:
    return config_dir("templates", UNDULATION_YAML)
