"""The opt-in exposure trim: off by default, accessory-only, bounded (MOD-EXP-001)."""

from __future__ import annotations

from conftest import make_readiness, make_training

from strength_coach.prescribe import build_prescription
from strength_coach.store import db, importer, repositories

ON = "2026-03-30"

# Ten chronic-window dates (one hard set per exercise) and six acute dates: baseline 2.5/week,
# acute 6 -> ratio 2.4, above the 1.3 threshold.
CHRONIC = ("2026-02-24", "2026-02-27", "2026-03-01", "2026-03-04", "2026-03-07",
           "2026-03-10", "2026-03-13", "2026-03-16", "2026-03-19", "2026-03-22")
ACUTE = ("2026-03-24", "2026-03-25", "2026-03-26", "2026-03-27", "2026-03-28", "2026-03-29")

EXERCISES = (
    ("Safety Squat Bar", "100"), ("Competition Bench Press", "80"),
    ("Box Jumps", "0"), ("Back Extension", "0"), ("Dumbbell Row", "30"),
    ("Lying Leg Curls", "30"), ("Ab Wheel", "0"),
)


def rows(days=CHRONIC + ACUTE):
    out = []
    for day in days:
        for exercise, weight in EXERCISES:
            out.append({"Date": day, "Exercise": exercise, "Weight_Used": weight,
                        "RIR": "2", "Reps_Done": "5"})
    return out


def store_with(trim: bool):
    training = make_training(rows())
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    repositories.append_athlete_profile(
        store.connection, effective_from="2026-01-01",
        exposure_trim_enabled=trim,
    )
    return store


def prescription(store):
    return build_prescription(
        store.connection, for_date=ON, session_type="squat",
    )


def accessory_sets(item_list):
    return sum(item.sets for item in item_list if not item.essential)


def test_the_trim_is_off_by_default():
    store = store_with(trim=False)
    try:
        result = prescription(store)
    finally:
        store.close()
    assert result.notes["exposure_trim"]["enabled"] is False
    assert not any("MOD-EXP-001" in warning for warning in result.warnings)


def test_the_trim_removes_only_accessories_when_enabled():
    base_store = store_with(trim=False)
    try:
        base = prescription(base_store)
    finally:
        base_store.close()
    trim_store = store_with(trim=True)
    try:
        trimmed = prescription(trim_store)
    finally:
        trim_store.close()

    assert trimmed.notes["exposure_trim"]["applied"] is True
    assert trimmed.notes["exposure_trim"]["signal"] == "high"
    # Main lifts never move.
    for exercise_id in ("ssb_squat", "bench_press"):
        before = next(i.sets for i in base.items if i.exercise_id == exercise_id)
        after = next(i.sets for i in trimmed.items if i.exercise_id == exercise_id)
        assert after == before
    # At most two accessory sets are removed, and only cited items moved.
    assert accessory_sets(base.items) - accessory_sets(trimmed.items) in (1, 2)
    moved = [item for item in trimmed.items
             if "MOD-EXP-001" in item.rationale_refs]
    assert moved and all(not item.essential for item in moved)
    assert any("MOD-EXP-001" in warning for warning in trimmed.warnings)


def test_the_flag_survives_a_profile_edit():
    store = store_with(trim=True)
    try:
        conn = store.connection
        repositories.append_athlete_profile(
            conn, effective_from="2026-02-01",
        )
        current = conn.execute(
            "SELECT exposure_trim_enabled FROM athlete_profile "
            "ORDER BY effective_from DESC, profile_id DESC LIMIT 1"
        ).fetchone()
    finally:
        store.close()
    assert current["exposure_trim_enabled"] == 1
