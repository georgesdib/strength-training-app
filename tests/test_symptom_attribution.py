"""Optional symptom attribution: validated, append-only and non-causal."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from conftest import make_readiness, make_training

from strength_coach.features import injury_signal
from strength_coach.store import db, importer, queries, repositories, symptom_attribution

ROWS = [
    {"Date": "2024-01-08", "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-15", "Exercise": "Trap Bar Deadlift", "Weight_Used": "185",
     "RIR": "2", "Reps_Done": "3"},
]


@contextmanager
def store_with(rows=None):
    training = make_training(rows or ROWS)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store.connection
    finally:
        store.close()


def _sessions(conn):
    return [str(value) for value in queries.sessions(conn)["session_id"]]


def _log(conn, **kwargs):
    values = {
        "logged_on": "2024-01-16",
        "timing": "post_session",
        "region": "low_back",
        "level": 1,
    }
    values.update(kwargs)
    return repositories.append_symptom(conn, **values)


def test_attribution_is_optional_and_absent_rows_stay_nullable():
    with store_with() as conn:
        _log(conn)
        row = queries.symptom_entries(conn)[-1]
    assert row["attributed_session_id"] is None
    assert row["attribution_confidence"] is None


def test_attribution_requires_session_onset_and_confidence():
    with store_with() as conn:
        session_id = _sessions(conn)[0]
        with pytest.raises(symptom_attribution.AttributionError, match="onset"):
            _log(conn, attributed_session_id=session_id, attribution_confidence="likely")
        with pytest.raises(symptom_attribution.AttributionError, match="confidence"):
            _log(conn, attributed_session_id=session_id, onset_on="2024-01-08")
        with pytest.raises(symptom_attribution.AttributionError, match="session"):
            _log(conn, onset_on="2024-01-08", attribution_confidence="likely")


def test_attribution_rejects_onset_after_reading_and_session_after_onset():
    with store_with() as conn:
        session_id = _sessions(conn)[-1]  # 15 Jan
        with pytest.raises(symptom_attribution.AttributionError, match="reading date"):
            _log(conn, logged_on="2024-01-15",
                 attributed_session_id=session_id, onset_on="2024-01-16",
                 attribution_confidence="likely")
        with pytest.raises(symptom_attribution.AttributionError, match="after onset"):
            _log(conn, logged_on="2024-01-16",
                 attributed_session_id=session_id, onset_on="2024-01-08",
                 attribution_confidence="likely")


def test_pre_session_cannot_point_at_a_session_on_the_onset_date():
    with store_with() as conn:
        session_id = _sessions(conn)[0]  # 8 Jan
        with pytest.raises(symptom_attribution.AttributionError, match="pre-session"):
            _log(conn, timing="pre_session", logged_on="2024-01-09",
                 attributed_session_id=session_id, onset_on="2024-01-08",
                 attribution_confidence="likely")


def test_post_session_may_point_at_a_session_on_the_onset_date():
    with store_with() as conn:
        session_id = _sessions(conn)[0]  # 8 Jan
        _log(conn, timing="post_session", logged_on="2024-01-08",
             attributed_session_id=session_id, onset_on="2024-01-08",
             attribution_confidence="likely")
        row = queries.symptom_entries(conn)[-1]
    assert row["attributed_session_id"] == session_id


def test_attribution_rejects_a_session_outside_the_lookback():
    with store_with() as conn:
        session_id = _sessions(conn)[0]  # 8 Jan
        with pytest.raises(symptom_attribution.AttributionError, match="lookback"):
            _log(conn, logged_on="2024-01-16",
                 attributed_session_id=session_id, onset_on="2024-01-16",
                 attribution_confidence="likely")


def test_attribution_rejects_a_lift_not_performed_in_the_session():
    with store_with() as conn:
        session_id = _sessions(conn)[0]
        with pytest.raises(symptom_attribution.AttributionError, match="not performed"):
            _log(conn, attributed_session_id=session_id,
                 attributed_exercise_id="competition_bench_press",
                 onset_on="2024-01-08", attribution_confidence="likely")


def test_attribution_accepts_a_performed_lift_and_keeps_the_source_fragment():
    with store_with() as conn:
        session_id = _sessions(conn)[0]
        _log(conn, attributed_session_id=session_id,
             attributed_exercise_id="trap_bar_deadlift",
             onset_on="2024-01-08", attribution_confidence="strong")
        row = queries.symptom_entries(conn)[-1]
    assert row["attributed_session_id"] == session_id
    assert row["attributed_exercise_id"] == "trap_bar_deadlift"
    assert row["attribution_confidence"] == "strong"


def test_attribution_is_append_only_and_latest_row_wins_for_display():
    with store_with() as conn:
        session_id = _sessions(conn)[0]
        _log(conn, attributed_session_id=session_id, onset_on="2024-01-08",
             attribution_confidence="possible")
        _log(conn, attributed_session_id=session_id, onset_on="2024-01-08",
             attribution_confidence="strong")
        entries = queries.symptom_entries(conn)
    assert len(entries) == 2
    assert entries[-1]["attribution_confidence"] == "strong"


def test_attribution_does_not_change_the_injury_signal():
    with store_with() as plain:
        _log(plain, level=1, settled_within_48h=True)
        before = injury_signal.compute(
            plain, "2024-01-16", config=injury_signal.InjuryConfig.load()
        )
    with store_with() as attributed:
        session_id = _sessions(attributed)[0]
        _log(attributed, level=1, settled_within_48h=True,
             attributed_session_id=session_id, onset_on="2024-01-08",
             attribution_confidence="likely")
        after = injury_signal.compute(
            attributed, "2024-01-16", config=injury_signal.InjuryConfig.load()
        )
    assert before.region("low_back").status == after.region("low_back").status
    assert before.region("low_back").tolerated_sessions == after.region("low_back").tolerated_sessions


def test_attribution_candidates_are_limited_to_the_lookback_and_timing():
    with store_with() as conn:
        pre = symptom_attribution.candidates(conn, onset_on="2024-01-09",
                                             timing="pre_session")
        post = symptom_attribution.candidates(conn, onset_on="2024-01-08",
                                              timing="post_session")
    assert [row["occurred_on"] for row in pre] == ["2024-01-08"]
    assert post[0]["occurred_on"] == "2024-01-08"
    assert post[0]["lifts"][0]["exercise_id"] == "trap_bar_deadlift"
