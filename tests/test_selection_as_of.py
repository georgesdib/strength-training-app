"""Exercise selection is point-in-time: no observation after the evaluation date votes.

The invariant under test is stated once and reused: for an evaluation date D, adding, changing
or deleting observations dated after D must not change the selection result for D. Both entry
points are covered - a direct selection.select() call and the fatigue-selection fallback that
invokes it without a context.
"""

from __future__ import annotations

from conftest import make_readiness, make_training

from strength_coach.prescribe import fatigue_selection, selection
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer, repositories

ON = "2024-01-15"

PAST_ROWS = [
    {"Date": "2024-01-01", "Exercise": "Lat Pulldown", "Weight_Used": "60",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
     "RIR": "2", "Reps_Done": "5"},
]
FUTURE_ROWS = [
    # A different variant performed later would change _current(), and the later date would
    # change the rotation term, if the history were not bounded.
    {"Date": "2024-02-01", "Exercise": "Pull-ups (wide grip)", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-02-01", "Exercise": "Lat Pulldown", "Weight_Used": "65",
     "RIR": "2", "Reps_Done": "10"},
]


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


def report(conn, context, on_date=ON):
    return selection.as_dict(
        selection.select(conn, context, on_date, "hinge", include_different=True)
    )


def pull_slot(rows):
    return next(row for row in rows if row["slot_id"] == "accessory_pull_up")


def test_direct_selection_ignores_observations_after_the_evaluation_date():
    # Same past, different future: the report for D must be identical.
    with store_with(PAST_ROWS) as past, store_with(PAST_ROWS + FUTURE_ROWS) as extended:
        assert report(extended.connection, None) == report(past.connection, None)


def test_a_context_built_to_a_later_end_cannot_change_a_past_selection():
    # The engine usually builds the context to the requested date, but selection must not
    # depend on that: a context carrying later rows is re-cut to the evaluation date.
    with store_with(PAST_ROWS + FUTURE_ROWS) as store:
        conn = store.connection
        early = RuleContext.from_store(conn, end=ON)
        late = RuleContext.from_store(conn, end="2024-02-15")
        assert report(conn, late) == report(conn, early)
        # And the slicing really removed rows rather than the two contexts agreeing by chance.
        assert len(late.sets) > len(late.as_of(conn, ON).sets)


def test_a_rating_recorded_later_does_not_vote_on_an_earlier_selection():
    with store_with(PAST_ROWS) as store:
        conn = store.connection
        repositories.append_exercise_suitability(
            conn, exercise_id="lat_pulldown", rated_on="2024-02-01",
            can_do=False, will_do=False, feels_bad=False,
        )
        before = {c["exercise_id"] for c in pull_slot(report(conn, None))["candidates"]}
        after = {
            c["exercise_id"]
            for c in pull_slot(report(conn, None, "2024-02-01"))["candidates"]
        }
    assert "lat_pulldown" in before
    assert "lat_pulldown" not in after


def test_the_profile_version_is_the_one_in_force_on_the_context_date():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Lat Pulldown", "Weight_Used": "60",
         "RIR": "2", "Reps_Done": "10"},
        {"Date": "2024-01-15", "Exercise": "Lat Pulldown", "Weight_Used": "60",
         "RIR": "2", "Reps_Done": "10"},
    ]
    with store_with(rows) as store:
        conn = store.connection
        repositories.append_athlete_profile(
            conn, effective_from="2024-01-01", block_start_date="2024-01-01",
        )
        repositories.append_athlete_profile(
            conn, effective_from="2024-06-01", block_start_date="2024-06-01",
        )
        early = RuleContext.from_store(conn, end="2024-02-15")
        late = RuleContext.from_store(conn, end="2024-07-15")
    # Two trained ISO weeks since 2024-01-01; the June profile would report week 1 instead.
    assert early.block_week_index == 2
    assert late.block_week_index == 1


# ---------------------------------------------------------------------------
# Fatigue-informed substitution fallback
# ---------------------------------------------------------------------------

FATIGUE_ON = "2026-03-30"
FATIGUE_DATES = (
    "2026-02-24", "2026-02-27", "2026-03-01", "2026-03-04", "2026-03-07",
    "2026-03-10", "2026-03-13", "2026-03-16", "2026-03-19", "2026-03-22",
    "2026-03-24", "2026-03-25", "2026-03-26", "2026-03-27", "2026-03-28", "2026-03-29",
)
FATIGUE_ROWS = [
    {"Date": day, "Exercise": "Dumbbell Row", "Weight_Used": "30",
     "RIR": "2", "Reps_Done": "8"}
    for day in FATIGUE_DATES
]
LATER_ROWS = [
    {"Date": "2026-04-05", "Exercise": "Dumbbell Chest Supported Row",
     "Weight_Used": "30", "RIR": "2", "Reps_Done": "8"},
    {"Date": "2026-04-05", "Exercise": "Dumbbell Row", "Weight_Used": "35",
     "RIR": "2", "Reps_Done": "8"},
]


def fatigue_store(*, rows=None, profiles=()):
    store = store_with(list(FATIGUE_ROWS) if rows is None else rows)
    for profile in profiles:
        repositories.append_athlete_profile(store.connection, **profile)
    return store


def test_the_fatigue_fallback_ignores_observations_after_the_evaluation_date():
    base_profile = {
        "effective_from": "2026-01-01", "block_start_date": "2026-01-01",
        "exposure_trim_enabled": False,
    }
    with (
        fatigue_store(profiles=[base_profile]) as past,
        fatigue_store(rows=FATIGUE_ROWS + LATER_ROWS, profiles=[base_profile]) as extended,
    ):
        bounded = fatigue_selection.suggest(past.connection, FATIGUE_ON, "squat")
        with_future = fatigue_selection.suggest(extended.connection, FATIGUE_ON, "squat")
    assert with_future.as_dict() == bounded.as_dict()
    assert bounded.suggestions, "the fixture must produce a suggestion, not an abstention"


def test_enabling_the_trim_later_does_not_change_an_earlier_suggestion():
    with (
        fatigue_store(profiles=[{
            "effective_from": "2026-01-01", "block_start_date": "2026-01-01",
            "exposure_trim_enabled": False,
        }]) as past,
        fatigue_store(profiles=[
            {
                "effective_from": "2026-01-01", "block_start_date": "2026-01-01",
                "exposure_trim_enabled": False,
            },
            # Recorded later, so it must not gate the earlier evaluation.
            {
                "effective_from": "2026-04-10", "block_start_date": "2026-04-10",
                "exposure_trim_enabled": True,
            },
        ]) as with_future_profile,
    ):
        bounded = fatigue_selection.suggest(past.connection, FATIGUE_ON, "squat")
        with_future = fatigue_selection.suggest(
            with_future_profile.connection, FATIGUE_ON, "squat"
        )
    assert with_future.as_dict() == bounded.as_dict()
    assert bounded.suggestions


def test_an_exposure_report_from_another_day_is_rejected():
    import pytest

    with fatigue_store(profiles=[{
        "effective_from": "2026-01-01", "block_start_date": "2026-01-01",
        "exposure_trim_enabled": False,
    }]) as store:
        from strength_coach.features import exposure

        other_day = exposure.compute(store.connection, "2026-03-23")
        with pytest.raises(ValueError, match="must equal the evaluation date"):
            fatigue_selection.suggest(
                store.connection, FATIGUE_ON, "squat", exposure_report=other_day
            )
