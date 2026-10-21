"""Injury signals: per-region evidence for a review, never a clearance.

The properties that matter:
* the window and the tolerated-session requirement scale with prior flares;
* a loaded session counts as tolerated only when a reading after it shows no flare;
* regions are isolated, so a knee entry cannot drive the back rules;
* an unknown region is `unknown`, never "fine".
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from conftest import make_readiness, make_training
from strength_coach.features import injury_signal
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer, queries, repositories
from strength_coach.utils import exercises

SESSIONS = [
    {"Date": day, "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"}
    for day in ("2024-01-08", "2024-01-15", "2024-01-22", "2024-01-29")
]


@contextmanager
def store_with(rows=None):
    training = make_training(rows or SESSIONS)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store
    finally:
        store.close()


def log(conn, day, level, *, region="low_back", settled=None, timing="pre_session"):
    repositories.append_symptom(
        conn, logged_on=day, timing=timing, region=region,
        level=level, settled_within_48h=settled,
    )


CONFIG = injury_signal.InjuryConfig.load()


def test_no_symptom_data_is_unknown_not_fine():
    with store_with() as store:
        signal = injury_signal.compute(store.connection, "2024-03-01", config=CONFIG)

    assert signal.status == "unknown"
    assert signal.region("low_back").status == "unknown"
    assert signal.region("low_back").symptom_free_days is None
    assert "Not medical clearance" in signal.disclaimer


def test_every_configured_region_is_reported():
    with store_with() as store:
        signal = injury_signal.compute(store.connection, "2024-03-01", config=CONFIG)

    assert set(signal.as_dict()["regions"]) == {"low_back", "biceps", "knee"}


def test_a_region_names_the_patterns_it_loads_not_just_canonical_lifts():
    # Curls are canonical now, but the region must still name the curl variants rather than
    # only pull-ups; this is what makes the biceps link useful after variant canonicalisation.
    rule = CONFIG.regions["biceps"]
    linked = injury_signal.linked_exercises(rule)
    assert "barbell_curl" in linked
    assert "dumbell_curl_alternating" in linked
    assert "pull_up" in linked                # vertical pulls do
    taxonomy = exercises.taxonomy()
    covered = {
        taxonomy.entities[i].get("pattern")
        for i in linked
        if not i.startswith("pattern:")
    }
    for pattern in rule.direct.patterns:
        assert pattern in covered or f"pattern:{pattern}" in linked


def test_an_old_entry_is_insufficient():
    with store_with() as store:
        log(store.connection, "2024-01-01", 0)
        signal = injury_signal.compute(store.connection, "2024-03-01", config=CONFIG)

    assert signal.region("low_back").status == "insufficient"
    assert "days old" in signal.region("low_back").summary


def test_review_needs_loaded_sessions_verified_after_the_load():
    with store_with() as store:
        conn = store.connection
        log(conn, "2024-01-02", 0)
        for day in ("2024-01-09", "2024-01-16", "2024-01-23", "2024-01-30"):
            log(conn, day, 0)  # the next reading after each session
        log(conn, "2024-02-28", 0)  # keeps the newest entry recent
        signal = injury_signal.compute(conn, "2024-03-01", config=CONFIG)

    region = signal.region("low_back")
    assert region.status == "review"
    assert region.symptom_free_days >= 28
    assert region.loaded_sessions >= 4
    assert region.tolerated_sessions >= 4
    assert region.unverified_sessions == 0
    assert region.recommendation is not None


def test_a_loaded_session_with_no_following_reading_is_not_tolerated():
    # This is the difference between "I trained a lot" and "the loading was tolerated".
    with store_with() as store:
        conn = store.connection
        log(conn, "2024-01-02", 0)
        log(conn, "2024-03-01", 0)
        signal = injury_signal.compute(conn, "2024-03-01", config=CONFIG)

    region = signal.region("low_back")
    assert region.status == "monitoring"
    assert region.loaded_sessions == 4
    assert region.tolerated_sessions == 0
    assert region.unverified_sessions == 4


def test_a_flare_resets_the_loaded_session_evidence():
    # A flare after a session means the app must not count that session as tolerated; in the
    # model it is also the new streak start, so only later loading counts.
    with store_with() as store:
        conn = store.connection
        log(conn, "2024-01-02", 0)
        log(conn, "2024-01-09", 0)
        log(conn, "2024-01-16", 2)  # flare the day after the 15 Jan session
        log(conn, "2024-03-01", 0)
        signal = injury_signal.compute(conn, "2024-03-01", config=CONFIG)

    region = signal.region("low_back")
    assert region.symptom_free_days == 45  # measured from the flare, not from the first entry
    assert region.loaded_sessions == 2      # only the 22 and 29 Jan sessions count
    assert region.tolerated_sessions == 0   # nothing was logged after them
    assert region.last_flare_on == "2024-01-16"


def test_a_current_flare_makes_the_region_active():
    with store_with() as store:
        conn = store.connection
        log(conn, "2024-01-02", 0)
        log(conn, "2024-03-01", 2)
        signal = injury_signal.compute(conn, "2024-03-01", config=CONFIG)

    assert signal.region("low_back").status == "active"
    assert signal.status == "active"
    assert "low_back" in signal.active_regions
    assert signal.region("low_back").symptom_free_days == 0
    assert signal.region("low_back").recommendation is None


def test_a_knee_entry_does_not_trigger_the_back_rules():
    with store_with() as store:
        conn = store.connection
        log(conn, "2024-01-10", 2, region="knee")
        context = RuleContext.from_store(conn, end="2024-01-10")
        signal = injury_signal.compute(conn, "2024-01-10", config=CONFIG)
        # The back modifier reads low_back only (DEC-SYMPTOM-03).
        assert queries.latest_symptom(conn, "2024-01-10") is None
        assert context.symptom_flare is None

    assert signal.region("low_back").status == "unknown"
    assert signal.region("knee").status == "active"
    assert signal.status == "active"


def test_the_window_and_the_requirement_scale_with_prior_flares():
    rule = CONFIG.regions["low_back"]
    assert (rule.window_days(0), rule.required_sessions(0)) == (28, 4)
    assert (rule.window_days(1), rule.required_sessions(1)) == (42, 6)
    assert (rule.window_days(2), rule.required_sessions(2)) == (56, 8)
    # Capped, so a long history does not demand an unbounded streak.
    assert rule.window_days(10) == 84
    assert rule.required_sessions(10) == 12


def test_two_prior_flares_raise_the_bar_for_a_30_day_streak():
    with store_with(rows=[{"Date": "2024-01-05", "Exercise": "Trap Bar Deadlift"}]) as store:
        conn = store.connection
        log(conn, "2023-12-01", 2)
        log(conn, "2024-01-01", 2)  # the flare that ended the current streak
        for day in ("2024-01-06", "2024-01-08", "2024-01-10", "2024-01-12"):
            log(conn, day, 0)
        log(conn, "2024-01-30", 0)  # near the assessment date, so the entry is not stale
        signal = injury_signal.compute(conn, "2024-01-31", config=CONFIG)

    region = signal.region("low_back")
    assert region.prior_flares == 1
    assert region.window_days == 42
    assert region.symptom_free_days == 30
    # 30 clean days clears the base 28 but not the scaled 42.
    assert region.status == "monitoring"


def test_curls_load_the_biceps_region():
    rows = [{"Date": "2024-01-08", "Exercise": "Barbell Curl", "Weight_Used": "30",
             "RIR": "2", "Reps_Done": "10"} for _ in range(2)]
    with store_with(rows=rows) as store:
        conn = store.connection
        log(conn, "2024-01-01", 0, region="biceps")
        signal = injury_signal.compute(conn, "2024-01-10", config=CONFIG)

    assert signal.region("biceps").loaded_sessions == 1
    assert signal.region("low_back").loaded_sessions == 0


def test_an_unknown_pattern_in_the_config_is_rejected(tmp_path: Path):
    path = tmp_path / "injuries.v1.yaml"
    path.write_text(
        "regions:\n"
        "  knee:\n"
        "    links:\n"
        "      direct: {patterns: [not_a_real_pattern]}\n",
        encoding="utf-8",
    )
    with pytest.raises(injury_signal.InjuryConfigError, match="unknown exercise patterns"):
        injury_signal.InjuryConfig.load(path)


def test_a_missing_config_file_says_unknown_rather_than_fine(tmp_path: Path):
    config = injury_signal.InjuryConfig.load(tmp_path / "absent.yaml")
    with store_with() as store:
        signal = injury_signal.compute(store.connection, "2024-03-01", config=config)

    assert signal.status == "unknown"
    assert "no injury regions" in signal.summary
