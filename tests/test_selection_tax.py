"""Tax metadata is ordinal, config-authoritative and never guessed."""

from __future__ import annotations

from strength_coach.prescribe import selection_tax


def test_tax_comparison_requires_known_mandatory_axes():
    cfg = selection_tax.TaxConfig.load()
    ssb = cfg.for_exercise("ssb_squat")
    hack = cfg.for_exercise("hack_squat")
    assert ssb is not None and hack is not None
    ok, why = selection_tax.lower_tax(ssb, hack, essential=True)
    assert ok is True
    assert "lower" in why

    unknown = selection_tax.Tax(1, 1, 1, 1)
    ok, why = selection_tax.lower_tax(None, unknown, essential=True)
    assert ok is False
    assert "unknown" in why


def test_accessory_tax_requires_axial_and_skill_only():
    cfg = selection_tax.TaxConfig.load()
    row = cfg.for_exercise("dumbbell_row")
    cable = cfg.for_exercise("seated_cable_row")
    ok, _ = selection_tax.lower_tax(row, cable, essential=False)
    assert ok is True
