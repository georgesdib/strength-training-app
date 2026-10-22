"""Volume landmarks and the conservative MRV cap."""

from __future__ import annotations

import pandas as pd

from strength_coach.prescribe.engine import _apply_volume_cap
from strength_coach.prescribe.models import PrescriptionItem
from strength_coach.rules import RuleContext
from strength_coach.utils import exercises


def _item(sets=3, essential=False):
    return PrescriptionItem(
        order_index=0, exercise_id="dumbbell_row", sets=sets, reps_low=8,
        reps_high=12, load_kg=20.0, load_basis="external",
        rounding_increment_kg=0.5, rir_target=2, rest_s=90, essential=essential,
    )


def test_mrv_cap_trims_only_non_essential_sets():
    rows = pd.DataFrame([
        {"date": pd.Timestamp("2026-10-14"), "exercise_id": "dumbbell_row",
         "is_working_set": True}
    ] * 10)
    context = RuleContext(
        sets=rows, sessions=pd.DataFrame(), entities=exercises.taxonomy().entities,
    )
    items, warnings, note = _apply_volume_cap(
        context, (_item(),), "2026-10-20"
    )
    assert items[0].sets == 2
    assert "MOD-VOL-001" in items[0].rationale_refs
    assert note["applied"] is True
    assert any("MOD-VOL-001" in warning for warning in warnings)


def test_mrv_cap_never_cuts_an_essential_item():
    rows = pd.DataFrame([
        {"date": pd.Timestamp("2026-10-14"), "exercise_id": "dumbbell_row",
         "is_working_set": True}
    ] * 20)
    context = RuleContext(
        sets=rows, sessions=pd.DataFrame(), entities=exercises.taxonomy().entities,
    )
    items, warnings, _ = _apply_volume_cap(
        context, (_item(essential=True),), "2026-10-20"
    )
    assert items[0].sets == 3
    assert any("no non-essential sets" in warning for warning in warnings)
