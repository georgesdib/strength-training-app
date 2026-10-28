"""Rolling hard-set exposure: windows, coverage, abstention and deduplication."""

from __future__ import annotations

from dataclasses import replace

from conftest import make_readiness, make_training

from strength_coach.features import exposure
from strength_coach.store import db, importer, repositories

ON = "2026-03-30"


def row(day: str, *, rir: str = "2", exercise: str = "Safety Squat Bar",
        reps: str = "5", weight: str = "100") -> dict:
    return {"Date": day, "Exercise": exercise, "Weight_Used": weight,
            "RIR": rir, "Reps_Done": reps}


def store_with(rows):
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def config(**overrides):
    return replace(exposure.ExposureConfig.load(), **overrides)


def weekly_rows(days, rir="2"):
    return [row(day, rir=rir) for day in days]


def test_windows_are_non_overlapping_and_inclusive():
    rows = weekly_rows([
        "2026-02-24",  # chronic start
        "2026-03-23",  # chronic end
        "2026-03-24",  # acute start
        "2026-03-30",  # acute end
    ])
    store = store_with(rows)
    try:
        report = exposure.compute(store.connection, ON, config(min_sessions=2, gap_days=100))
    finally:
        store.close()
    assert (report.chronic_start, report.chronic_end) == ("2026-02-24", "2026-03-23")
    assert (report.acute_start, report.acute_end) == ("2026-03-24", "2026-03-30")
    assert report.acute_hard_sets == 2
    assert report.chronic_hard_sets == 2
    assert report.ratio == 4.0
    assert report.signal == "high"
    assert report.abstain == ()


def test_a_missing_rir_lowers_coverage_and_abstains():
    rows = weekly_rows(["2026-02-24", "2026-03-02", "2026-03-09"])
    rows.append(row("2026-03-16", rir=""))
    store = store_with(rows)
    try:
        report = exposure.compute(store.connection, ON, config(min_sessions=1, gap_days=100))
    finally:
        store.close()
    assert report.coverage == 0.75
    assert "low_coverage" in report.abstain
    assert report.signal == "unknown"


def test_no_chronic_work_abstains_on_zero_baseline():
    store = store_with(weekly_rows(["2026-03-26", "2026-03-27"]))
    try:
        report = exposure.compute(store.connection, ON, config(min_sessions=1))
    finally:
        store.close()
    assert report.chronic_hard_sets == 0
    assert "zero_baseline" in report.abstain
    assert report.signal == "unknown"


def test_a_long_gap_inside_the_chronic_window_abstains():
    rows = weekly_rows([
        "2026-02-24", "2026-02-25", "2026-02-26", "2026-03-22", "2026-03-23",
    ])
    store = store_with(rows)
    try:
        report = exposure.compute(store.connection, ON, config(min_sessions=1, gap_days=10))
    finally:
        store.close()
    assert report.flags["gap_days"] >= 24
    assert "gap_in_window" in report.abstain


def test_a_declared_break_in_the_window_abstains():
    store = store_with(weekly_rows([
        "2026-02-24", "2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23",
    ]))
    try:
        repositories.append_declared_break(
            store.connection, starts_on="2026-03-01", ends_on="2026-03-03",
            reason="holiday",
        )
        report = exposure.compute(store.connection, ON, config(min_sessions=1))
    finally:
        store.close()
    assert "break_in_window" in report.abstain


def test_a_stored_deload_in_the_window_abstains():
    store = store_with(weekly_rows([
        "2026-02-24", "2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23",
    ]))
    try:
        run = repositories.start_run(store.connection, input_hash="t", code_version="t")
        repositories.append_prescription(
            store.connection, prescription_id="p1", run_id=run.run_id,
            for_date="2026-03-10", session_type="squat", fallback_level="full",
            rule_document_version="t", calibration_ids=(), approved_by="deterministic",
            items=[],
        )
        repositories.append_prescription_modifier(
            store.connection, prescription_id="p1", modifier_key="MOD-DELOAD-001",
            applied_on="2026-03-10", detail={},
        )
        report = exposure.compute(store.connection, ON, config(min_sessions=1))
    finally:
        store.close()
    assert "deload_in_window" in report.abstain


def test_an_exposure_referencing_a_counted_set_is_not_counted_twice():
    store = store_with(weekly_rows(["2026-03-20", "2026-03-26"]))
    try:
        set_row = store.connection.execute(
            "SELECT set_id, session_id FROM clean_set WHERE occurred_on = '2026-03-26'"
        ).fetchone()
        repositories.append_high_intensity_exposure(
            store.connection, performed_on="2026-03-26", kind="unplanned",
            region_load="lower", set_id=int(set_row["set_id"]),
            session_id=str(set_row["session_id"]),
        )
        repositories.append_high_intensity_exposure(
            store.connection, performed_on="2026-03-27", kind="max_attempt",
            region_load="lower",
        )
        report = exposure.compute(store.connection, ON, config(min_sessions=1, gap_days=100))
    finally:
        store.close()
    # The 03-26 set is in the acute window, so chronic is 1 (03-20) + 1 free exposure = 2.
    # Without dedupe the linked exposure would make both windows one higher.
    assert report.acute_hard_sets == 2
    assert report.chronic_hard_sets == 2


def test_a_low_ratio_reads_low_and_the_two_week_rule_drives_the_advisory():
    rows = weekly_rows(["2026-02-24", "2026-03-02", "2026-03-09"])
    store = store_with(rows)
    try:
        report = exposure.compute(
            store.connection, ON, config(min_sessions=1, gap_days=100)
        )
    finally:
        store.close()
    assert report.acute_hard_sets == 0
    assert report.signal == "low"
    assert report.previous_ratio == 0.0
    assert report.advisories


def test_groups_are_reported_with_their_own_ratio():
    rows = [
        *weekly_rows(["2026-02-24", "2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23"]),
        row("2026-03-26", exercise="Competition Bench Press", weight="80"),
    ]
    store = store_with(rows)
    try:
        report = exposure.compute(store.connection, ON, config(min_sessions=1, gap_days=100))
    finally:
        store.close()
    groups = {group.group: group for group in report.groups}
    assert "horizontal_push" in groups
    assert groups["horizontal_push"].acute_hard_sets == 1
