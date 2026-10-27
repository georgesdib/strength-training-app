"""A plan for a date with a recorded session is a revision, not an addition.

The MRV cap, the spinal cap and the weekly budget all used a completed baseline that included
the prescription date, then added the proposed items on top. These tests pin the revision
semantic from DEC-VOLUME-30: the date's recorded sets are excluded, the plan is counted once,
and an earlier date still counts.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

from conftest import make_readiness, make_training
from strength_coach.features.volume import VolumeConfig
from strength_coach.prescribe import PrescriptionItem, build_prescription, engine, volume_budget
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer, repositories

HINGE_ROWS = [
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Sumo Deadlift", "Weight_Used": "120",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Pull-ups (wide grip)", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Dumbbell Row", "Weight_Used": "30",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Overhead Press (seated)", "Weight_Used": "40",
     "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Hanging Leg Raise", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "10"},
]


@contextmanager
def store_with(rows, *, volume_budget=False):
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        if volume_budget:
            repositories.append_athlete_profile(
                store.connection,
                effective_from="2024-01-01",
                primary_goal="longevity",
                goal_rank=["longevity", "strength"],
                focus_lifts=[],
                block_start_date="2024-01-01",
                volume_budget_enabled=True,
            )
        yield store
    finally:
        store.close()


def split_squat(sets: int) -> PrescriptionItem:
    return PrescriptionItem(
        order_index=0,
        exercise_id="split_squat",
        sets=sets,
        reps_low=8,
        reps_high=10,
        load_kg=30.0,
        load_basis="external",
        rounding_increment_kg=0.5,
        rir_target=2,
        rest_s=90,
        essential=False,
    )


def test_mrv_does_not_count_the_same_date_session_and_the_plan():
    rows = [
        {"Date": "2024-01-08", "Exercise": "Split Squat", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "8"},
        {"Date": "2024-01-08", "Exercise": "Split Squat", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "8"},
    ]
    with store_with(rows) as store:
        context = RuleContext.from_store(store.connection, end="2024-01-08")
        assert len(context.sets) == 2
        assert context.prior_to("2024-01-08").sets.empty
        cfg = replace(
            VolumeConfig.load(),
            landmarks={"squat": (1, 2, 3, 4)},
            apply_mrv_cap=True,
        )
        items, _warnings, note = engine._apply_volume_cap(
            context, (split_squat(3),), "2024-01-08", config=cfg,
        )

    assert items[0].sets == 3
    assert note["applied"] is False


def test_mrv_still_counts_an_earlier_date():
    rows = [
        {"Date": "2024-01-07", "Exercise": "Split Squat", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "8"},
        {"Date": "2024-01-07", "Exercise": "Split Squat", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "8"},
    ]
    with store_with(rows) as store:
        context = RuleContext.from_store(store.connection, end="2024-01-08")
        cfg = replace(
            VolumeConfig.load(),
            landmarks={"squat": (1, 2, 3, 4)},
            apply_mrv_cap=True,
        )
        items, _warnings, note = engine._apply_volume_cap(
            context, (split_squat(3),), "2024-01-08", config=cfg,
        )

    assert items[0].sets == 2          # 2 prior + 3 proposed > MRV 4
    assert "split_squat" in note["reductions"]


def test_spinal_week_excludes_the_same_date_session():
    rows = HINGE_ROWS + [
        {"Date": "2024-01-08", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-08", session_type="bench_hinge",
        )

    assert prescription.notes["spinal_cap"]["cost"] == 2.5   # sumo only, trap bar excluded
    assert prescription.notes["same_date_session"] is not None
    assert any("same-date session" in warning for warning in prescription.warnings)


def test_no_same_date_session_keeps_the_normal_path():
    with store_with(HINGE_ROWS) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-07", session_type="bench_hinge",
        )

    assert prescription.notes["same_date_session"] is None
    assert not any("same-date session" in warning for warning in prescription.warnings)


def budget_config():
    targets = dict(volume_budget.DEFAULT_TARGET)
    targets["squat"] = 3.0
    total = sum(targets.values())
    return replace(
        volume_budget.BudgetConfig.load(),
        weekly_target=targets,
        weekly_target_effective=targets,
        weekly_total=total,
        weekly_total_effective=total,
        tolerance=0.0,
        band_min=0.0,
        trim_enabled=True,
        top_up_enabled=False,
    )


def test_budget_report_and_apply_exclude_the_same_date_session():
    rows = [
        {"Date": "2024-01-08", "Exercise": "Split Squat", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "8"},
        {"Date": "2024-01-08", "Exercise": "Split Squat", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "8"},
    ]
    cfg = budget_config()
    with store_with(rows, volume_budget=True) as store:
        context = RuleContext.from_store(store.connection, end="2024-01-08")
        data = volume_budget.report(
            store.connection, "2024-01-08", config=cfg, session_type="squat",
            projected_items=[{"exercise_id": "split_squat", "sets": 3}],
        )
        out, _warnings, note = volume_budget.apply(
            (split_squat(3),), conn=store.connection, context=context,
            for_date="2024-01-08", session_type="squat", config=cfg,
        )

    assert data["revision"] is True
    assert data["completed"]["squat"] == 0
    assert data["today"]["sets"]["squat"] == 3
    assert out[0].sets == 3
    assert note["changed"] == []
