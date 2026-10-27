"""Generic engine contract against a synthetic template, not the shipped programme.

The shipped programme is pinned separately by the golden test. This test exists so engine
mechanics (slot order, sets/reps, variant selection) can change without forcing a golden edit,
and so a programme edit does not silently invalidate every engine test.
"""

from __future__ import annotations

import yaml

from strength_coach.prescribe import build_prescription, templates
from strength_coach.store import db
from strength_coach.utils import paths

SYNTHETIC = {
    "schema_version": "1.0.0",
    "session_types": {
        "squat": {
            "label": "Squat",
            "prescription": {
                "time_cap_s": 3600,
                "slots": [
                    {"id": "main", "exercise": "ssb_squat", "sets": 3,
                     "reps": {"low": 5, "high": 5}, "rir": {"low": 2, "high": 2},
                     "rest_s": 180, "essential": True, "load_source": "e1rm"},
                    {"id": "accessory", "exercise": "dumbbell_row", "sets": 2,
                     "reps": {"low": 8, "high": 10}, "rir": {"low": 2, "high": 3},
                     "essential": False, "load_source": "e1rm"},
                ],
            },
        },
        "hinge": {
            "label": "Hinge",
            "prescription": {
                "time_cap_s": 3600,
                "slots": [
                    {"id": "main", "exercise": "trap_bar_deadlift", "sets": 3,
                     "reps": {"low": 3, "high": 5}, "rir": {"low": 2, "high": 3},
                     "essential": True, "load_source": "e1rm"},
                ],
            },
        },
        "bench_squat": {
            "label": "Bench squat",
            "prescription": {
                "time_cap_s": 3600,
                "slots": [
                    {"id": "main", "exercise": "ssb_squat", "sets": 3,
                     "reps": {"low": 3, "high": 5}, "rir": {"low": 2, "high": 3},
                     "essential": True, "load_source": "e1rm"},
                ],
            },
        },
        "bench_hinge": {
            "label": "Bench hinge",
            "prescription": {
                "time_cap_s": 3600,
                "slots": [
                    {"id": "main", "exercise": "trap_bar_deadlift", "sets": 3,
                     "reps": {"low": 3, "high": 5}, "rir": {"low": 2, "high": 3},
                     "essential": True, "load_source": "e1rm"},
                ],
            },
        },
    },
}


def test_engine_contract_uses_a_synthetic_template(tmp_path, monkeypatch):
    source = tmp_path / "session-types.v1.yaml"
    source.write_text(yaml.safe_dump(SYNTHETIC, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(paths, "session_types_yaml", lambda: source)
    templates._parse_session_template.cache_clear()
    try:
        with db.Store(":memory:") as store:
            prescription = build_prescription(
                store.connection, for_date="2024-02-01", session_type="squat"
            )
    finally:
        templates._parse_session_template.cache_clear()

    assert prescription.session_type == "squat"
    assert [(item.exercise_id, item.sets, item.reps_low, item.reps_high)
            for item in prescription.items] == [
        ("ssb_squat", 3, 5, 5),
        ("dumbbell_row", 2, 8, 10),
    ]
