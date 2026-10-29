"""Part C suggestions: one at most, accessory only, unknown never compares (DEC-SELECT-12)."""

from __future__ import annotations

from pathlib import Path

from conftest import make_readiness, make_training

from strength_coach.features.demands import DemandCatalogue, DemandClaim
from strength_coach.prescribe import fatigue_selection
from strength_coach.store import db, importer, repositories

ON = "2026-03-30"
DATES = (
    "2026-02-24", "2026-02-27", "2026-03-01", "2026-03-04", "2026-03-07",
    "2026-03-10", "2026-03-13", "2026-03-16", "2026-03-19", "2026-03-22",
    "2026-03-24", "2026-03-25", "2026-03-26", "2026-03-27", "2026-03-28", "2026-03-29",
)


def store_with_rows(rows, *, trim: bool = False):
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    repositories.append_athlete_profile(
        store.connection, effective_from="2026-01-01", primary_goal="strength",
        goal_rank=[], focus_lifts=[], exposure_trim_enabled=trim,
    )
    return store


def row_rows():
    return [
        {"Date": day, "Exercise": "Dumbbell Row", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "8"}
        for day in DATES
    ]


def test_a_high_row_group_suggests_the_lower_axial_variant():
    store = store_with_rows(row_rows())
    try:
        report = fatigue_selection.suggest(store.connection, ON, "squat")
    finally:
        store.close()
    assert report.signal == "high"
    assert len(report.suggestions) == 1
    suggestion = report.suggestions[0]
    assert suggestion.current == "dumbbell_row"
    assert suggestion.candidate == "dumbbell_chest_supported_row"
    assert suggestion.dimension == "axial_spinal"
    assert suggestion.current_level == "moderate"
    assert suggestion.candidate_level == "low"
    assert suggestion.comparison_class in {"A", "B"}
    assert report.applied is False


def test_an_unrated_candidate_is_never_suggested():
    store = store_with_rows(row_rows())
    catalogue = DemandCatalogue(
        claims={"dumbbell_row": {
            "axial_spinal": DemandClaim("axial_spinal", "moderate", "provisional", "kept"),
        }},
        evidence={}, reviewed_on="", digest="", source_path=Path(),
    )
    try:
        report = fatigue_selection.suggest(
            store.connection, ON, "squat", catalogue=catalogue
        )
    finally:
        store.close()
    assert report.suggestions == ()
    assert any("no candidate" in reason for reason in report.abstentions)


def test_the_trim_and_a_substitution_never_both_act():
    store = store_with_rows(row_rows(), trim=True)
    try:
        report = fatigue_selection.suggest(store.connection, ON, "squat")
    finally:
        store.close()
    assert report.suggestions == ()
    assert any("trim is enabled" in reason for reason in report.abstentions)


def test_a_quiet_week_abstains():
    store = store_with_rows([
        {"Date": "2026-01-05", "Exercise": "Dumbbell Row", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "8"},
    ])
    try:
        report = fatigue_selection.suggest(store.connection, ON, "squat")
    finally:
        store.close()
    assert report.suggestions == ()
    assert report.signal != "high"
