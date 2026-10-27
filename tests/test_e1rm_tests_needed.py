"""P1 coverage: how many measured tests each lift still needs (ROADMAP 4.19).

The gate needs data, not code, so this report is the only way to see whether the missing
piece is a test the athlete has not done or a test that could not be counted.
"""

from __future__ import annotations

from conftest import make_readiness, make_training

from strength_coach.features import e1rm_calibration as cal
from strength_coach.store import db, importer, repositories

MAIN_LIFTS = {
    "bench_press",
    "bench_press_narrow",
    "bench_press_pause",
    "ssb_squat",
    "trap_bar_deadlift",
}

SET_ONCE = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
]


def _store(rows):
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def _three_tests_store():
    """Three tested 3RMs, each with a formula estimate inside the window before it."""
    rows = [
        {"Date": day, "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for day in ("2024-01-20", "2024-02-20", "2024-03-20")
    ]
    store = _store(rows)
    for day in ("2024-02-01", "2024-03-01", "2024-04-01"):
        repositories.append_e1rm_override(
            store.connection, exercise_id="ssb_squat", e1rm_kg=125.0,
            effective_from=day, expires_on=day, reason="3RM test", source="measured",
        )
    return store


def test_every_main_lift_is_listed_even_before_the_first_test():
    # A lift with no usable history is invisible in the calibration report, and it is
    # exactly the lift that needs testing; the coverage view must still list it.
    with _store(SET_ONCE) as store:
        rows = cal.coverage(store.connection)

    main = {row.exercise_id for row in rows if row.is_main_lift}
    assert main == MAIN_LIFTS
    assert all(row.status == "no tests" for row in rows if row.is_main_lift)
    assert all(row.needed == row.min_tests == 3 for row in rows if row.is_main_lift)
    # Main lifts come first so a tested accessory cannot push them off the top.
    assert [row.is_main_lift for row in rows] == sorted(
        (row.is_main_lift for row in rows), reverse=True
    )


def test_a_counted_test_reduces_the_need_by_one():
    with _store(SET_ONCE) as store:
        repositories.append_e1rm_override(
            store.connection, exercise_id="ssb_squat", e1rm_kg=120.0,
            effective_from="2024-02-01", reason="3RM test", source="measured",
        )
        rows = cal.coverage(store.connection)

    ssb = next(row for row in rows if row.exercise_id == "ssb_squat")
    assert ssb.counted == 1 and ssb.recorded == 1
    assert ssb.needed == 2
    assert ssb.status == "1/3 counted"
    assert ssb.next_action == "record 2 more measured test(s)"


def test_three_consistent_tests_report_the_gate_as_met():
    with _three_tests_store() as store:
        rows = cal.coverage(store.connection)
        [calibrated] = cal.build(store.connection)

    ssb = next(row for row in rows if row.exercise_id == "ssb_squat")
    assert ssb.counted == 3 and ssb.needed == 0
    assert ssb.counted == calibrated.n
    assert ssb.status.startswith("applied x")
    assert ssb.next_action == "none: correction in force"


def test_a_test_filed_cold_is_recorded_but_not_counted():
    # The gate counts comparable tests: a test with no formula estimate in the window
    # before it proves nothing, so it must not move the count or hide the real need.
    with _store(SET_ONCE) as store:
        repositories.append_e1rm_override(
            store.connection, exercise_id="ssb_squat", e1rm_kg=140.0,
            effective_from="2024-06-01", reason="test", source="measured",
        )
        rows = cal.coverage(store.connection)

    ssb = next(row for row in rows if row.exercise_id == "ssb_squat")
    assert ssb.recorded == 1 and ssb.counted == 0
    assert ssb.needed == 3
    assert ssb.status == "0/3 counted"
    assert "not counted" in ssb.note


def test_a_measured_test_on_a_variant_counts_against_its_canonical_lift():
    # build() canonicalises history before counting, so coverage must file the same way
    # or the two tables disagree about how many tests a lift has.
    rows = [
        {"Date": "2024-01-01", "Exercise": "Hyperextensions", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "10"},
    ]
    with _store(rows) as store:
        repositories.append_e1rm_override(
            store.connection, exercise_id="hyperextension", e1rm_kg=50.0,
            effective_from="2024-02-01", reason="test", source="measured",
        )
        coverage = cal.coverage(store.connection)

    back = next(row for row in coverage if row.exercise_id == "back_extension")
    assert back.recorded == 1
    assert not any(row.exercise_id == "hyperextension" for row in coverage)


def test_cli_tests_needed_prints_the_gate(tmp_path, capsys):
    from strength_coach import cli

    training = make_training(SET_ONCE)
    readiness = make_readiness([{}])
    path = tmp_path / "coach.db"
    store = db.Store(path)
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()

    assert cli.main(["--db", str(path), "e1rm", "tests-needed"]) == 0
    out = capsys.readouterr().out
    assert "measured-test coverage for MOD-E1RM-001" in out
    assert "trap_bar_deadlift" in out
    assert "record 3 measured test(s)" in out
    assert "* = main lift" in out
