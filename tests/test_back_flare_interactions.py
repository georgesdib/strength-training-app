"""Back-flare interactions: assert the final prescription, not just the warnings.

The individual modifier tests already cover each rule. These tests pin what happens when a
flare meets readiness, a deload, a long gap or the spinal cap, and they lock the ceiling rule:
a readiness set cut is never restored by the flare (DEC-SPINE-07).
"""

from __future__ import annotations

from contextlib import contextmanager

from conftest import make_readiness, make_training

from strength_coach.features.deload import DeloadDecision
from strength_coach.prescribe import build_prescription
from strength_coach.store import db, importer, repositories

POOR_READINESS = {
    "Date": "2024-01-02",
    "Sleep": "1",
    "Energy": "1",
    "Mood": "1",
    "Soreness": "1",
    "Stress": "1",
}

SQUAT_ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "5",
     "RIR": "2", "Reps_Done": "12"},
    {"Date": "2024-01-01", "Exercise": "Dumbbell Row", "Weight_Used": "30",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Ab Wheel", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Box Jumps", "Weight_Used": "0",
     "RIR": "4", "Reps_Done": "4"},
]

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
def store_with(rows, *, readiness_rows=None, block_start=None):
    training = make_training(rows)
    readiness = make_readiness(readiness_rows or [{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        if block_start:
            repositories.append_athlete_profile(
                store.connection,
                effective_from=block_start,
                block_start_date=block_start,
            )
        yield store
    finally:
        store.close()


def log_flare(conn, date="2024-01-02"):
    repositories.append_symptom(
        conn, logged_on=date, timing="pre_session", region="low_back",
        level=2, settled_within_48h=None,
    )


def item(prescription, exercise_id):
    return next(i for i in prescription.items if i.exercise_id == exercise_id)


def test_flare_never_restores_a_readiness_cut_erector_set():
    with store_with(
        SQUAT_ROWS, readiness_rows=[{**POOR_READINESS, "Date": "2024-01-02"}]
    ) as store:
        log_flare(store.connection, "2024-01-02")
        prescription = build_prescription(
            store.connection, for_date="2024-01-02", session_type="squat",
        )

    erector = item(prescription, "back_extension")
    assert erector.sets == 2                    # readiness cut, flare did not restore 3
    assert erector.load_kg == 0.0
    assert erector.load_basis == "bodyweight_total"
    assert "MOD-FAT-001" in erector.rationale_refs
    assert "MOD-BACK-001" in erector.rationale_refs   # the load reset did change it
    assert "symptom:2024-01-02" in erector.rationale_refs
    assert "back_extension" in prescription.notes["back_flare_review"]["dose"]
    assert "back_extension" not in prescription.notes["back_flare_review"]["held"]


def test_a_bodyweight_erector_item_is_reviewed_not_cited():
    rows = [
        {**row, "Weight_Used": "0"} if row["Exercise"] == "Back Extension" else row
        for row in SQUAT_ROWS
    ]
    with store_with(rows, readiness_rows=[{**POOR_READINESS, "Date": "2024-01-02"}]) as store:
        log_flare(store.connection, "2024-01-02")
        prescription = build_prescription(
            store.connection, for_date="2024-01-02", session_type="squat",
        )

    erector = item(prescription, "back_extension")
    assert erector.sets == 2
    assert erector.load_kg == 0.0
    assert "MOD-BACK-001" not in erector.rationale_refs
    assert "back_extension" in prescription.notes["back_flare_review"]["reviewed_unchanged"]


def test_sumo_holds_effort_and_is_re_solved_not_relabelled():
    with store_with(HINGE_ROWS) as store:
        plain = build_prescription(
            store.connection, for_date="2024-01-02", session_type="bench_hinge",
        )
    with store_with(HINGE_ROWS) as store:
        log_flare(store.connection, "2024-01-02")
        flare = build_prescription(
            store.connection, for_date="2024-01-02", session_type="bench_hinge",
        )

    plain_sumo = item(plain, "sumo_deadlift")
    flare_sumo = item(flare, "sumo_deadlift")
    assert flare_sumo.essential is True
    assert flare_sumo.rir_target == 3
    assert plain_sumo.rir_target == 2
    assert flare_sumo.load_kg < plain_sumo.load_kg
    assert "MOD-BACK-001" in flare_sumo.rationale_refs
    assert "sumo_deadlift" in flare.notes["back_flare_review"]["held"]


def test_sumo_never_takes_the_maximal_scheme_after_alignment():
    rows = []
    for day in ("2024-01-01", "2024-01-08", "2024-01-15"):
        rows += [{**row, "Date": day} for row in HINGE_ROWS]
    with store_with(rows, block_start="2024-01-01") as store:
        log_flare(store.connection, "2024-01-22")
        prescription = build_prescription(
            store.connection, for_date="2024-01-22", session_type="bench_hinge",
        )

    sumo = item(prescription, "sumo_deadlift")
    assert (sumo.reps_low, sumo.reps_high) == (3, 5)
    assert sumo.rir_target == 3
    assert "MOD-BACK-001" in sumo.rationale_refs


def test_deload_composes_with_the_flare_ceiling():
    with store_with(
        SQUAT_ROWS, readiness_rows=[{**POOR_READINESS, "Date": "2024-01-02"}]
    ) as store:
        log_flare(store.connection, "2024-01-02")
        prescription = build_prescription(
            store.connection, for_date="2024-01-02", session_type="squat",
            deload_decision=DeloadDecision(reason="test deload", trigger="test"),
        )

    erector = item(prescription, "back_extension")
    assert erector.sets == 2
    assert erector.load_kg == 0.0
    assert "MOD-BACK-001" in erector.rationale_refs
    assert "MOD-DELOAD-001" in erector.rationale_refs


def test_a_flare_that_cannot_be_trimmed_reports_the_spinal_cap():
    rows = list(HINGE_ROWS)
    rows += [
        {"Date": "2024-01-15", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-16", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-16", "Exercise": "Competition Squat", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-16", "Exercise": "Back Extension", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "12"},
    ]
    with store_with(rows) as store:
        log_flare(store.connection, "2024-01-17")
        prescription = build_prescription(
            store.connection, for_date="2024-01-17", session_type="bench_hinge",
        )

    sumo = item(prescription, "sumo_deadlift")
    assert sumo.sets == 3
    assert "sumo_deadlift" in prescription.notes["back_flare_review"]["held"]
    assert any(issue.startswith("SPINAL_CAP:") for issue in prescription.issues)
    assert prescription.executable is False
