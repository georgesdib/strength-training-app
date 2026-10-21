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
EXERCISE_OVERRIDES_YAML = "exercises/overrides.v1.yaml"
PROGRAMME_RULES_YAML = "rules/programme.v1.yaml"
THRESHOLDS_YAML = "thresholds.v1.yaml"
READINESS_YAML = "readiness.v1.yaml"
INJURIES_YAML = "injuries.v1.yaml"
CARDIO_YAML = "cardio.v1.yaml"
MEASUREMENTS_YAML = "measurements.v1.yaml"
STRESS_YAML = "stress.v1.yaml"
E1RM_CALIBRATION_YAML = "e1rm-calibration.v1.yaml"
E1RM_DECAY_YAML = "e1rm-decay.v1.yaml"
FATIGUE_FITNESS_YAML = "fatigue-fitness.v1.yaml"
CONTINUITY_CALIBRATION_YAML = "continuity-calibration.v1.yaml"
SELECTION_YAML = "selection.v1.yaml"
SCHEMES_YAML = "schemes.v1.yaml"
UNDULATION_YAML = "undulation.v1.yaml"


def training_log_csv() -> Path:
    return raw_data_dir() / TRAINING_LOG_CSV


def readiness_csv() -> Path:
    return raw_data_dir() / READINESS_CSV


def taxonomy_yaml() -> Path:
    return config_dir(TAXONOMY_YAML)


def exercise_overrides_yaml() -> Path:
    return config_dir(EXERCISE_OVERRIDES_YAML)


def programme_rules_yaml() -> Path:
    return config_dir(PROGRAMME_RULES_YAML)


def thresholds_yaml() -> Path:
    return config_dir(THRESHOLDS_YAML)


def readiness_yaml() -> Path:
    return config_dir(READINESS_YAML)


def injuries_yaml() -> Path:
    return config_dir(INJURIES_YAML)


def cardio_yaml() -> Path:
    return config_dir(CARDIO_YAML)


def measurements_yaml() -> Path:
    return config_dir(MEASUREMENTS_YAML)


def stress_yaml() -> Path:
    return config_dir(STRESS_YAML)


def e1rm_calibration_yaml() -> Path:
    return config_dir(E1RM_CALIBRATION_YAML)


def e1rm_decay_yaml() -> Path:
    return config_dir(E1RM_DECAY_YAML)


def fatigue_fitness_yaml() -> Path:
    return config_dir(FATIGUE_FITNESS_YAML)


def continuity_calibration_yaml() -> Path:
    return config_dir(CONTINUITY_CALIBRATION_YAML)


def selection_yaml() -> Path:
    return config_dir(SELECTION_YAML)


def schemes_yaml() -> Path:
    return config_dir("templates", SCHEMES_YAML)


def undulation_yaml() -> Path:
    return config_dir("templates", UNDULATION_YAML)
