"""Session reconstruction and day inference.

The export has no timestamps (DQ-SESSION-01), so a session is one calendar date and day
inference is a heuristic. These tests pin the heuristic's *honesty*: when the evidence does
not support a day, the result must be `unknown` with a reason, never a guess.
"""

import pytest

from conftest import make_readiness, make_training
from strength_coach.ingest import clean, sessions


def build(rows: list[dict]):
    result = clean.build_clean_sets(make_training(rows), make_readiness([{}]))
    return sessions.build_sessions(result.sets)


def squat_sets(n: int, day: str = "2024-01-01") -> list[dict]:
    return [
        {"Date": day, "Exercise": "Safety Squat Bar", "Weight_Used": "100", "RIR": "2"}
        for _ in range(n)
    ]


def bench_sets(n: int, day: str = "2024-01-01") -> list[dict]:
    return [
        {"Date": day, "Exercise": "Competition Bench Press", "Weight_Used": "80", "RIR": "2"}
        for _ in range(n)
    ]


# --- positive identification ----------------------------------------------
def test_hinge_day_is_b():
    rows = [{"Date": "2024-01-01", "Exercise": "Competition Deadlift", "Weight_Used": "150",
             "RIR": "3"}]
    [session] = build(rows)
    assert session.day == "B"
    assert session.day_reason == "hinge"
    assert session.day_confidence >= 0.9


def test_squat_dominant_day_is_a():
    [session] = build(squat_sets(8) + bench_sets(3))
    assert session.day == "A"
    assert session.day_reason == "squat_emphasis"


def test_bench_dominant_day_is_c():
    [session] = build(squat_sets(3) + bench_sets(8))
    assert session.day == "C"
    assert session.day_reason == "bench_emphasis"


def test_pause_bench_counts_towards_the_bench_family():
    rows = squat_sets(3) + [
        {"Date": "2024-01-01", "Exercise": "Bench Press (2s pause)", "Weight_Used": "80",
         "RIR": "2"} for _ in range(8)
    ]
    [session] = build(rows)
    assert session.day == "C"


# --- honest abstention ----------------------------------------------------
def test_bench_only_session_is_not_forced_into_a_day():
    """Every programme day contains a squat or a hinge, so bench-only is off-programme."""
    [session] = build(bench_sets(8))
    assert session.day == "unknown"
    assert session.day_reason == "bench_only"
    assert sessions.FLAG_OFF_PROGRAMME in session.flags


def test_squat_only_session_is_not_forced_into_a():
    [session] = build(squat_sets(8))
    assert session.day == "unknown"
    assert session.day_reason == "squat_only"


def test_accessory_only_session_has_no_primary():
    rows = [{"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "10",
             "RIR": "2"}]
    [session] = build(rows)
    assert session.day == "unknown"
    assert session.day_reason == "no_primary"
    assert sessions.FLAG_NO_MAIN_LIFT in session.flags


def test_ambiguous_session_is_flagged_as_such():
    [session] = build(bench_sets(5))
    assert sessions.FLAG_AMBIGUOUS_DAY in session.flags


# --- programme substitution ----------------------------------------------
def test_competition_squat_instead_of_ssb_is_flagged_as_substitution():
    """Competition squat is a primary compound but not a constitution main lift."""
    rows = [
        {"Date": "2024-01-01", "Exercise": "Competition Squat", "Weight_Used": "120",
         "RIR": "2"}
    ] + bench_sets(2)
    [session] = build(rows)
    assert session.main_lifts == ("bench_press",)
    assert "competition_squat" in session.primary_compounds
    assert sessions.FLAG_SUBSTITUTED_MAIN_LIFT not in session.flags  # bench IS a main lift
    assert session.day in {"A", "C"}


# --- structural flags -----------------------------------------------------
def test_oversized_session_flags_a_possible_double_session():
    rows = squat_sets(20) + bench_sets(20)
    [session] = build(rows)
    assert sessions.FLAG_DOUBLE_SESSION in session.flags


def test_normal_session_is_not_flagged():
    [session] = build(squat_sets(6) + bench_sets(4))
    assert sessions.FLAG_DOUBLE_SESSION not in session.flags


def test_high_warmup_share_is_flagged():
    rows = [{"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "RIR": "6"} for _ in range(8)]
    rows += squat_sets(2)
    [session] = build(rows)
    assert sessions.FLAG_HIGH_WARMUP_SHARE in session.flags


def test_warmups_are_excluded_from_working_set_count():
    rows = [{"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "RIR": "6"} for _ in range(5)]
    rows += squat_sets(3)
    [session] = build(rows)
    assert session.set_count == 8
    assert session.working_set_count == 3


def test_session_id_is_the_iso_date():
    [session] = build(squat_sets(1, day="2025-03-09"))
    assert session.session_id == "2025-03-09"


def test_multiple_dates_produce_ordered_sessions():
    rows = squat_sets(2, "2024-01-03") + bench_sets(2, "2024-01-03")
    rows += squat_sets(2, "2024-01-01") + bench_sets(2, "2024-01-01")
    result = build(rows)
    assert [s.session_id for s in result] == ["2024-01-01", "2024-01-03"]
