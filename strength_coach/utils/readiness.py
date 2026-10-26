"""Readiness fields shared by storage, configuration and the CLI.

The 1-5 fields are subjective scores; the device fields are measurements. Keeping the list in
one place means a new field cannot be accepted by the CLI and rejected by the table (or the
reverse), and it keeps the sentinel policy in `ingest.readiness` as the only place that decides
what a zero means.

The movement/muscle categories live here too because two layers need the same list: the score
maps an exercise pattern to its category, and the store rejects a `category:<name>` override
scope that names no category. The store may not import `features` (layering), so the shared
vocabulary belongs below both. The category is the training unit; the injury region remains
the evidence unit.
"""

from __future__ import annotations

SCORE_FIELDS = (
    "sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration",
    "squat_readiness", "bench_readiness", "deadlift_readiness",
)
MEASURE_FIELDS = ("hrv_ms", "rhr_bpm", "bodyweight_kg", "fat_pct", "wearable_score")
# `grip_strength_kg` is deliberately absent: grip is a periodic capacity measurement, not a
# daily readiness input (DEC-GRIP-01). The readiness_day/readiness_entry columns remain for
# historical rows but no readiness path accepts new ones; use `measure --metric grip_strength_kg`.
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
    "grip_strength_kg": "grip strength (kg, legacy readiness field)",
    "wearable_score": "wearable readiness (0-100)",
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
    elif field == "wearable_score":
        if not 0 <= number <= 100:
            raise ValueError("wearable_score must be from 0 to 100")
    elif number <= 0:
        raise ValueError(f"{field} must be positive")


# Movement/muscle categories. The category is the training unit the athlete chooses between;
# the region is the injury-evidence unit. The exact list is a config-level proposal
# (docs/READINESS-SCORE.md §2.6), not a measurement.
CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "hinge": ("hinge", "hinge_unilateral", "hinge_ballistic"),
    "squat": ("squat", "squat_unilateral"),
    "horizontal_push": ("horizontal_push", "horizontal_push_bw"),
    "vertical_push": ("vertical_push",),
    "horizontal_pull": ("horizontal_pull",),
    "vertical_pull": ("vertical_pull",),
    "elbow_flexion": ("elbow_flexion",),
    "knee_extension": ("knee_extension",),
    "knee_flexion": ("knee_flexion", "hamstring_eccentric"),
    "dorsiflexion": ("dorsiflexion",),
    "spinal_extension": ("erector_extension",),
    "core_carry": ("core_flexion", "core_anti_extension", "core_isometric",
                   "core_stability", "carry"),
}
PATTERN_TO_CATEGORY = {
    pattern: category for category, patterns in CATEGORY_PATTERNS.items() for pattern in patterns
}
