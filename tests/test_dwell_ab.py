"""WP7b: the dwell variants change pool order without changing the safety gates."""

from __future__ import annotations

from strength_coach.prescribe import dwell_ab


def test_cap_keeps_catalogue_order_and_draw_moves_the_later_candidate() -> None:
    rows = dwell_ab.ab.CASES["straight"]["rows"]
    cap = dwell_ab._run_variant("cap", "cap", 0.0, rows)
    drawn = dwell_ab._run_variant("cap_draw", "cap_draw", 1.0, rows)
    full = dwell_ab._run_variant("cap_draw_factor", "full", 1.0, rows)
    pure = dwell_ab._run_variant("pure_factor", "pure_factor", 0.0, rows)
    assert cap["pool"] == ["ssb_squat", "competition_squat"]
    assert drawn["pool"][0] == "competition_squat"
    assert full["pool"][0] == "competition_squat"
    assert pure["pool"][0] == "competition_squat"
    assert all(row["feasible"] for row in (cap, drawn, full, pure))
    assert all(row["band_penalty"] == 0 for row in (cap, drawn, full, pure))
    assert all(row["time_over"] == 0.0 for row in (cap, drawn, full, pure))

