"""Readiness fields shared by storage, configuration and the CLI.

The 1-5 fields are subjective scores; the device fields are measurements. Keeping the list in
one place means a new field cannot be accepted by the CLI and rejected by the table (or the
reverse), and it keeps the sentinel policy in `ingest.readiness` as the only place that decides
what a zero means.
"""

from __future__ import annotations

SCORE_FIELDS = (
    "sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration",
    "squat_readiness", "bench_readiness", "deadlift_readiness",
)
MEASURE_FIELDS = ("hrv_ms", "rhr_bpm", "bodyweight_kg", "fat_pct", "grip_strength_kg")
# Old per-lift values from the previous app. They are calibration labels, not inputs.
LEGACY_FIELDS = ("squat_readiness", "bench_readiness", "deadlift_readiness")
CORE_SCORE_FIELDS = ("sleep", "energy", "mood", "stress", "soreness")
INPUT_SCORE_FIELDS = tuple(f for f in SCORE_FIELDS if f not in LEGACY_FIELDS)
READINESS_FIELDS = SCORE_FIELDS + MEASURE_FIELDS

FIELD_LABELS = {
    "sleep": "sleep",
    "energy": "energy",
    "mood": "mood",
    "soreness": "soreness",
    "stress": "stress",
    "nutrition": "nutrition",
    "hydration": "hydration",
    "squat_readiness": "squat readiness",
    "bench_readiness": "bench readiness",
    "deadlift_readiness": "deadlift readiness (legacy label)",
    "hrv_ms": "HRV (ms)",
    "rhr_bpm": "resting HR (bpm)",
    "bodyweight_kg": "bodyweight (kg)",
    "fat_pct": "body fat (%)",
    "grip_strength_kg": "grip strength (kg)",
}


def validate(field: str, value: float) -> None:
    """Refuse values the export's scales cannot represent.

    A 1-5 score has no zero bucket, so zero is invalid rather than "missing" (the export's
    zero-as-missing rule applies only to the device fields). Device values must be positive;
    zero bodyweight or HRV is not a measurement.
    """
    if field not in READINESS_FIELDS:
        raise ValueError(f"unknown readiness field {field!r}")
    number = float(value)
    if field in SCORE_FIELDS:
        if not 1 <= number <= 5 or number != int(number):
            raise ValueError(f"{field} must be an integer from 1 to 5")
    elif number <= 0:
        raise ValueError(f"{field} must be positive")
