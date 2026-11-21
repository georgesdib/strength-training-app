"""WP4 programme header: trained week, DUP, deload and competition context."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

from conftest import make_readiness, make_training
from intelligence_support import FixedClock, enabled_config

from strength_coach import settings_profile
from strength_coach.features import programme
from strength_coach.intelligence import methods, resources
from strength_coach.intelligence.reports import weekly_review
from strength_coach.store import db, importer, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-08", "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-15", "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"},
]


@contextmanager
def store_with(*, anchor="2024-01-01", competition_date=None):
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        repositories.append_athlete_profile(
            store.connection,
            effective_from="2024-01-01",
            block_start_date=anchor,
            competition_date=competition_date,
        )
        yield store
    finally:
        store.close()


def test_header_without_an_anchor_has_no_trained_week() -> None:
    with store_with(anchor=None) as store:
        header = programme.header(store.connection, "2024-01-15")
    assert header["trained_week"] is None
    assert "dup" not in header
    assert header["deload"]["calendar_week"] is None
    assert header["deload"]["status"] == "none"
    assert "competition" not in header


def test_header_reports_trained_week_dup_and_calendar_week() -> None:
    with store_with() as store:
        header = programme.header(store.connection, "2024-01-15")
    assert header["trained_week"] == 3
    assert header["dup"] == {
        "enabled": True,
        "cycle_weeks": 4,
        "cycle_week": 3,
        "main_scheme": "maximal",
        "accessory_scheme": "accessory",
    }
    assert header["deload"]["calendar_week"] == 3
    assert header["deload"]["status"] == "none"


def test_header_marks_a_live_plan_deload_active() -> None:
    with store_with() as store:
        header = programme.header(
            store.connection,
            "2024-01-15",
            live_plan={"notes": {"deload": {
                "trigger": "reactive",
                "reason": "two consecutive flaring sessions",
            }}},
        )
    assert header["deload"]["status"] == "active"
    assert header["deload"]["trigger"] == "reactive"
    assert "flaring" in header["deload"]["reason"]


def test_header_reports_a_scheduled_deload_as_suggested() -> None:
    with store_with() as store:
        settings_profile.save(
            store.connection,
            set_values={"deload.scheduled.every_weeks": 2},
            effective_from="2024-01-01",
        )
        header = programme.header(store.connection, "2024-01-08")
    assert header["deload"]["status"] == "suggested"
    assert "scheduled deload" in header["deload"]["reason"]


def test_header_reports_competition_days_and_window() -> None:
    with store_with(competition_date="2024-02-01") as store:
        header = programme.header(store.connection, "2024-01-15")
        past = programme.header(store.connection, "2024-02-15")
    assert header["competition"] == {
        "date": "2024-02-01",
        "days_until": 17,
        "window": "peak",
    }
    assert past["competition"]["days_until"] is None
    assert past["competition"]["window"] == "none"


def test_programme_resource_exposes_the_header_facts() -> None:
    with store_with(competition_date="2024-02-01") as store:
        envelope = resources.programme_current(
            store.connection,
            config=enabled_config(),
            clock=FixedClock(day=dt.date(2024, 1, 15)),
        )
    assert envelope.facts["trained_week"].value == 3
    assert envelope.facts["dup"].value["cycle_week"] == 3
    assert envelope.facts["competition"].value["days_until"] == 17
    assert envelope.facts["deload"].value["calendar_week"] == 3
    assert envelope.facts["trained_week"].method in methods.METHODS


def test_weekly_review_programme_section_carries_the_header() -> None:
    with store_with() as store:
        section, _coverage = weekly_review._programme_section(store.connection, "2024-01-15")
    assert section.value["trained_week"] == 3
    assert section.value["dup"]["cycle_week"] == 3
    assert section.value["deload_calendar_week"] == 3
    assert section.method == "strength_coach.features.programme.header"

