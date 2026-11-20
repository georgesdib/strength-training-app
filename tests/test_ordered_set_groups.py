"""WP1a: ordered planned set groups on the wire, in persistence and in the engine.

Order is the only identity a client, a stored row or an analysis layer sees. A legacy plan
that still carries a role is read by list position, never rejected and never rewritten
(DEC-RESOLVER-18).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strength_coach.features.deload import DeloadConfig, DeloadDecision
from strength_coach.prescribe import deload, engine, loads, warmup
from strength_coach.prescribe.models import (
    Prescription,
    PrescriptionItem,
    SetGroup,
    group_payload,
    validate_plan_set_groups,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "resolver_structure"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _group(index: int, sets: int, load: float, rir: int = 3) -> dict:
    return {
        "group_index": index,
        "sets": sets,
        "load_kg": load,
        "reps_low": 3,
        "reps_high": 5,
        "rir_target": rir,
    }


def _model_group(role: str, sets: int, load: float, rir: int = 3) -> SetGroup:
    return SetGroup(
        role=role, sets=sets, load_kg=load, reps_low=3, reps_high=5, rir_target=rir,
    )


def _item(
    groups: tuple[SetGroup, ...] = (),
    *,
    sets: int | None = None,
    load: float | None = 100.0,
    e1rm: float | None = 130.0,
) -> PrescriptionItem:
    return PrescriptionItem(
        order_index=0,
        exercise_id="ssb_squat",
        sets=sum(group.sets for group in groups) if sets is None else sets,
        reps_low=3,
        reps_high=5,
        load_kg=load,
        load_basis="external",
        rounding_increment_kg=2.5,
        rir_target=3,
        rest_s=180,
        essential=True,
        e1rm_kg=e1rm,
        set_groups=groups,
    )


def test_legacy_role_groups_validate_and_are_read_by_list_order() -> None:
    item = _fixture("legacy_two_group_plan.json")["item"]
    validate_plan_set_groups(item)
    # A role is neither required nor validated: any value is read by position, including one
    # the engine never emitted.
    item["set_groups"][0]["role"] = "primary"
    validate_plan_set_groups(item)
    assert [group["load_kg"] for group in item["set_groups"]] == [120, 102.5]


def test_a_single_full_item_group_is_accepted() -> None:
    validate_plan_set_groups({"exercise_id": "ssb_squat", "sets": 4,
                              "set_groups": [_group(0, 4, 100.0)]})


@pytest.mark.parametrize(
    "indexes", [(0, 0), (1, 0), (0, 2), ("0", 1), (True, 1)],
)
def test_group_index_must_restate_the_list_position(indexes: tuple) -> None:
    groups = [
        {**_group(position, 1, 100.0), "group_index": index}
        for position, index in enumerate(indexes)
    ]
    with pytest.raises(ValueError, match="groups are read by list order"):
        validate_plan_set_groups(
            {"exercise_id": "ssb_squat", "sets": 2, "set_groups": groups}
        )


def test_group_payload_has_order_as_the_only_identity() -> None:
    group = SetGroup(
        role="top_set", sets=1, load_kg=120.0, reps_low=3, reps_high=5,
        rir_target=1, percent_of_top=None,
    )
    assert group_payload(group, 0) == {
        "group_index": 0,
        "sets": 1,
        "load_kg": 120.0,
        "reps_low": 3,
        "reps_high": 5,
        "rir_target": 1,
    }


def test_as_rows_writes_ordered_groups_without_a_role() -> None:
    item = _item(
        (
            _model_group("top_set", 1, 120.0, rir=1),
            _model_group("back_off", 3, 100.0, rir=3),
        )
    )
    row = Prescription(
        for_date="2026-11-01",
        session_type="squat",
        fallback_level="full",
        rule_document_version="test",
        items=(item,),
    ).as_rows()[0]
    assert [group["group_index"] for group in row["set_groups"]] == [0, 1]
    assert [
        set(group) for group in row["set_groups"]
    ] == [{"group_index", "sets", "load_kg", "reps_low", "reps_high", "rir_target"}] * 2


def test_warmup_uses_the_heaviest_group_not_the_first() -> None:
    groups = (
        _model_group("back_off", 2, 100.0),
        _model_group("top_set", 1, 140.0, rir=1),
        _model_group("back_off", 1, 110.0, rir=2),
    )
    item = _item(groups)
    cfg = warmup.WarmupConfig.load()
    ramp = warmup.for_item(item)
    assert ramp
    assert ramp[0].load_kg == cfg.bar_kg
    first_rung = ramp[1]
    assert first_rung.percent == cfg.percents[0]
    assert first_rung.load_kg == loads.round_down(
        max(group.load_kg for group in groups) * cfg.percents[0],
        item.rounding_increment_kg,
    )
    # The first group is deliberately not the reference.
    assert first_rung.load_kg != loads.round_down(
        groups[0].load_kg * cfg.percents[0], item.rounding_increment_kg
    )


def test_structure_intensity_is_the_set_weighted_mean() -> None:
    item = _item(
        (
            _model_group("top_set", 1, 120.0, rir=1),
            _model_group("back_off", 3, 100.0),
        ),
        e1rm=150.0,
        load=100.0,
    )
    assert engine._set_weighted_intensity(item) == pytest.approx(
        (1 * 120.0 + 3 * 100.0) / 4 / 150.0
    )
    # The summary ratio is the back-off load and understates the structured item.
    assert engine._set_weighted_intensity(item) > item.load_kg / item.e1rm_kg


def test_intensity_is_unknown_without_an_e1rm_or_a_group_load() -> None:
    item = _item((_model_group("top_set", 1, 120.0, rir=1),), e1rm=None)
    assert engine._set_weighted_intensity(item) is None
    item = _item((_model_group("top_set", 1, None, rir=1),))
    assert engine._set_weighted_intensity(item) is None


def test_deload_scales_every_group_and_the_resize_keeps_the_sum() -> None:
    cfg = DeloadConfig.load()
    item = _item(
        (
            _model_group("top_set", 1, 120.0, rir=1),
            _model_group("back_off", 3, 100.0),
        ),
        sets=4,
        load=100.0,
    )
    items, warning, _note, _level = deload.apply_items(
        (item,), DeloadDecision(reason="test deload", trigger="test")
    )
    scaled = items[0]
    assert warning
    assert scaled.set_groups[0].load_kg == loads.round_down(
        120.0 * cfg.load_multiplier, item.rounding_increment_kg
    )
    assert scaled.set_groups[1].load_kg == loads.round_down(
        100.0 * cfg.load_multiplier, item.rounding_increment_kg
    )
    resized, _warnings = engine._resize_top_set_groups((scaled,))
    assert sum(group.sets for group in resized[0].set_groups) == resized[0].sets
