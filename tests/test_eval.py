"""The backtest harness and labelled set.

The point of a labelled set is that the comparison is against a judgement made outside the
engine. These tests pin the mechanics: what counts as comparable, what counts as agreement,
and what must be refused rather than scored.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from conftest import make_readiness, make_training
from strength_coach.critique.rubric import RUBRIC_WEIGHTS, Critique, RubricItem
from strength_coach.eval import (
    ITEM_KEYS,
    LabelError,
    LabelledSession,
    LabelledSet,
    backtest,
    compare,
    load_labels,
    template,
    write_template,
)
from strength_coach.store import db, importer

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_critique(scores: dict[str, float | None], session_id="2024-01-01") -> Critique:
    items = []
    for key, weight in RUBRIC_WEIGHTS.items():
        score = scores.get(key)
        items.append(
            RubricItem(
                key=key,
                weight=weight,
                score=score,
                measurable=score is not None,
                evidence_refs=(),
                rule_ids=(),
                detail="",
            )
        )
    return Critique(
        session_id=session_id, facts_hash="h", items=tuple(items), narrative=""
    )


def make_labels(scores: dict[str, float | None], session_id="2024-01-01") -> LabelledSession:
    return LabelledSession(session_id=session_id, scores=scores)


# --- loading and validation ------------------------------------------------


def test_the_committed_example_parses():
    labelled = load_labels(REPO_ROOT / "eval" / "labelled.example.yaml")
    assert set(labelled.sessions) == {"2024-01-08", "2024-01-15"}
    assert labelled.tolerance == 0.25


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(LabelError, match="not found"):
        load_labels(tmp_path / "nope.yaml")


def test_unknown_rubric_item_is_rejected(tmp_path):
    path = tmp_path / "labels.yaml"
    path.write_text(yaml.safe_dump({
        "version": 1,
        "sessions": {"2024-01-01": {"scores": {"NOT_A_KEY": 0.5}}},
    }), encoding="utf-8")
    with pytest.raises(LabelError, match="unknown rubric items"):
        load_labels(path)


def test_out_of_range_score_is_rejected(tmp_path):
    path = tmp_path / "labels.yaml"
    path.write_text(yaml.safe_dump({
        "version": 1,
        "sessions": {"2024-01-01": {"scores": {"RIR_ADHERENCE": 1.5}}},
    }), encoding="utf-8")
    with pytest.raises(LabelError, match="outside 0..1"):
        load_labels(path)


def test_null_scores_are_allowed_and_mean_not_marked(tmp_path):
    path = tmp_path / "labels.yaml"
    path.write_text(yaml.safe_dump({
        "version": 1,
        "sessions": {"2024-01-01": {"scores": {"RIR_ADHERENCE": None, "REDUNDANCY": 1.0}}},
    }), encoding="utf-8")
    labelled = load_labels(path)
    assert labelled.sessions["2024-01-01"].scores["RIR_ADHERENCE"] is None


def test_the_guide_covers_every_item_and_is_rendered():
    from strength_coach.eval import ITEM_GUIDE
    from strength_coach.eval.labels import render_template

    assert set(ITEM_GUIDE) == set(ITEM_KEYS)
    text = render_template(["2024-01-01"])
    # Direction is the whole point: a backtest against the opposite reading measures nothing.
    assert "HIGHER IS ALWAYS BETTER" in text
    assert "MORE work is a LOWER score" in text
    for key in ITEM_KEYS:
        assert key in text


def test_template_covers_every_item(tmp_path):
    payload = template(["2024-01-01"])
    assert set(payload["sessions"]["2024-01-01"]["scores"]) == set(ITEM_KEYS)

    path = write_template(tmp_path / "out.yaml", ["2024-01-01"])
    assert path.exists()
    with pytest.raises(LabelError, match="already exists"):
        write_template(path, ["2024-01-01"])
    write_template(path, ["2024-01-01"], overwrite=True)


# --- comparison ------------------------------------------------------------


def test_agreement_within_tolerance():
    critique = make_critique({"RIR_ADHERENCE": 0.75})
    comparison = compare(critique, make_labels({"RIR_ADHERENCE": 0.5}), tolerance=0.25)
    item = next(i for i in comparison.items if i.key == "RIR_ADHERENCE")
    assert item.comparable
    assert item.within_tolerance is True
    assert item.delta == pytest.approx(-0.25)


def test_disagreement_outside_tolerance_is_named():
    critique = make_critique({"RIR_ADHERENCE": 1.0})
    comparison = compare(critique, make_labels({"RIR_ADHERENCE": 0.25}), tolerance=0.25)
    assert comparison.disagreements == ("RIR_ADHERENCE",)
    assert comparison.agreement_rate == 0.0


def test_unmeasurable_items_are_never_counted_as_agreement():
    # The human marked it; the engine could not measure it. That is neither agreement nor
    # disagreement, so it must not enter the denominator.
    critique = make_critique({"RIR_ADHERENCE": 1.0})
    comparison = compare(
        critique,
        make_labels({"RIR_ADHERENCE": 1.0, "SESSION_DURATION": 0.5}),
        tolerance=0.25,
    )
    duration = next(i for i in comparison.items if i.key == "SESSION_DURATION")
    assert duration.comparable is False
    assert len(comparison.comparable_items) == 1


def test_mae_and_rate_over_several_items():
    critique = make_critique({"RIR_ADHERENCE": 1.0, "REDUNDANCY": 0.5})
    comparison = compare(
        critique,
        make_labels({"RIR_ADHERENCE": 0.75, "REDUNDANCY": 0.5}),
        tolerance=0.25,
    )
    assert comparison.agreement_rate == 1.0
    assert comparison.mean_abs_error == pytest.approx(0.125)


# --- the harness on a store ------------------------------------------------


@contextmanager
def store_with(rows):
    training = make_training(rows)
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


SESSION_ROWS = [
    {"Date": "2024-01-01", "Exercise": "Competition Deadlift", "Weight_Used": "150",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5", "RIR": "2",
     "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30", "RIR": "3",
     "Reps_Done": "8"},
]


def test_backtest_against_a_perfect_label_agrees_completely():
    from strength_coach.critique import score_session

    with store_with(SESSION_ROWS) as store:
        critique = score_session(store.connection, "2024-01-01")
        scores = {i.key: i.score for i in critique.items if i.measurable}
        labels = LabelledSet(
            sessions={"2024-01-01": LabelledSession("2024-01-01", scores)},
            tolerance=0.25,
        )
        report = backtest(store.connection, labels)

    assert report.agreement_rate == 1.0
    assert report.mean_abs_error == pytest.approx(0.0)
    assert len(report.comparable_items) == len(scores)


def test_backtest_reports_per_item_agreement():
    from strength_coach.critique import score_session

    with store_with(SESSION_ROWS) as store:
        critique = score_session(store.connection, "2024-01-01")
        scores = {i.key: i.score for i in critique.items if i.measurable}
        # Deliberately wrong on one item.
        scores["RIR_ADHERENCE"] = 0.0
        labels = LabelledSet(
            sessions={"2024-01-01": LabelledSession("2024-01-01", scores)},
            tolerance=0.25,
        )
        report = backtest(store.connection, labels)

    per_item = report.per_item
    assert per_item["RIR_ADHERENCE"]["agreement"] == 0.0
    assert per_item["WEEKLY_SPINAL_COST"]["agreement"] == 1.0
