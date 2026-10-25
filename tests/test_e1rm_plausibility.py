"""The e1RM plausibility advisory (DEC-E1RM-PLAUS-01).

Advisory, never policy: it warns when the number behind a load sits far above the athlete's
recent typical performance on that lift, and it changes nothing. These tests pin both halves
of that sentence: it fires on a single-point error in the load base, and the prescription is
byte-identical whether or not it is enabled.
"""

from __future__ import annotations

from dataclasses import replace

from conftest import make_readiness, make_training
from strength_coach.prescribe import build_prescription, config
from strength_coach.store import db, importer, repositories

TRAP_BAR = "Trap Bar Deadlift"
HISTORY_DAYS = ("2024-01-04", "2024-01-11", "2024-01-18")


def store_with(rows, overrides=()):
    dates = sorted({row["Date"] for row in rows})
    training = make_training(rows)
    readiness = make_readiness([{"Date": day} for day in dates])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection,
        training,
        readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    for override in overrides:
        repositories.append_e1rm_override(store.connection, **override)
    return store


def history(loads=None):
    """Three trap-bar sets and three bench sets on each day: enough for a reference median.

    The hinge session's accessories get history too, so the prescription is executable and the
    only thing under test is the advisory.
    """
    rows = []
    for day, load in zip(HISTORY_DAYS, loads or ("150", "152", "151"), strict=False):
        for _ in range(3):
            rows.append({"Date": day, "Exercise": TRAP_BAR, "Weight_Used": load,
                         "RIR": "2", "Reps_Done": "5"})
            rows.append({"Date": day, "Exercise": "Bench Press (narrow grip)",
                         "Weight_Used": "85", "RIR": "2", "Reps_Done": "5"})
            rows.append({"Date": day, "Exercise": "Dumbbell Row", "Weight_Used": "30",
                         "RIR": "2", "Reps_Done": "10"})
            rows.append({"Date": day, "Exercise": "Split Squat", "Weight_Used": "30",
                         "RIR": "3", "Reps_Done": "8"})
    return rows


def prescribe(store, **threshold_overrides):
    thresholds = replace(config.Thresholds.load(), **threshold_overrides)
    return build_prescription(
        store.connection, for_date="2024-01-22", session_type="hinge", thresholds=thresholds
    )


def advisories(prescription):
    return [w for w in prescription.warnings if "DEC-E1RM-PLAUS-01" in w]


def test_an_override_far_above_history_is_flagged():
    override = {"exercise_id": "trap_bar_deadlift", "e1rm_kg": 260.0,
                "effective_from": "2024-01-20", "source": "measured"}
    with store_with(history(), overrides=(override,)) as store:
        prescription = prescribe(store)

    found = advisories(prescription)
    assert len(found) == 1
    assert "trap_bar_deadlift" in found[0]
    assert "above the recent median" in found[0]
    # The advisory is not a veto.
    assert prescription.executable


def test_an_estimate_in_line_with_history_is_not_flagged():
    with store_with(history()) as store:
        prescription = prescribe(store)
    assert advisories(prescription) == []


def test_the_advisory_is_silent_when_the_reference_is_too_thin():
    # One working set is not a distribution: the median would just be that set, so an
    # "excess over the median" would be an artefact of sample size, not evidence.
    rows = [
        {"Date": "2024-01-18", "Exercise": TRAP_BAR, "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-18", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "85",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-18", "Exercise": "Dumbbell Row", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "10"},
        {"Date": "2024-01-18", "Exercise": "Split Squat", "Weight_Used": "30",
         "RIR": "3", "Reps_Done": "8"},
    ]
    override = {"exercise_id": "trap_bar_deadlift", "e1rm_kg": 260.0,
                "effective_from": "2024-01-20", "source": "measured"}
    with store_with(rows, overrides=(override,)) as store:
        prescription = prescribe(store)
    assert advisories(prescription) == []


def test_the_advisory_never_changes_the_prescription():
    override = {"exercise_id": "trap_bar_deadlift", "e1rm_kg": 260.0,
                "effective_from": "2024-01-20", "source": "measured"}
    with store_with(history(), overrides=(override,)) as store:
        flagged = prescribe(store)
        silent = prescribe(store, plausibility_enabled=False)

    def shape(prescription):
        return [(i.exercise_id, i.sets, i.load_kg) for i in prescription.items]

    assert shape(flagged) == shape(silent)
    assert flagged.executable == silent.executable
    assert list(flagged.issues) == list(silent.issues)
    assert advisories(flagged) and advisories(silent) == []


def test_best_usable_flags_the_outlier_that_the_median_ignores():
    # The config flip this advisory was built for: one great day becomes the load base.
    rows = history() + [
        {"Date": "2024-01-20", "Exercise": TRAP_BAR, "Weight_Used": "210",
         "RIR": "2", "Reps_Done": "5"},
    ] * 1
    with store_with(rows) as store:
        by_median = prescribe(store, e1rm_source=config.E1RM_MEDIAN)
        by_best = prescribe(store, e1rm_source=config.E1RM_BEST_USABLE)

    assert advisories(by_median) == []
    assert advisories(by_best)

def test_a_measured_calibration_widens_the_band():
    # A measured-test calibration is evidence, not an error: the advisory must not tell the
    # athlete to distrust the one correction that is checked against reality.
    import pandas as pd

    from strength_coach.prescribe.engine import _e1rm_plausibility
    from strength_coach.rules import RuleContext
    from strength_coach.utils import exercises

    rows = pd.DataFrame([
        {"date": pd.Timestamp(day), "exercise_id": "trap_bar_deadlift",
         "e1rm_kg": 185.0, "is_working_set": True}
        for day in ("2024-01-04", "2024-01-11", "2024-01-18")
    ])
    context = RuleContext(
        sets=rows, sessions=pd.DataFrame(), entities=exercises.taxonomy().entities,
    )
    thresholds = config.Thresholds.load()
    # 203.5 is exactly 10% above the recent median of 185.
    assert _e1rm_plausibility(
        context, "trap_bar_deadlift", 203.5, "2024-01-22", thresholds
    )
    assert _e1rm_plausibility(
        context, "trap_bar_deadlift", 203.5, "2024-01-22", thresholds,
        calibration_factor=1.10,
    ) is None
