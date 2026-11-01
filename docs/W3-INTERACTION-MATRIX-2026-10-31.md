# W3 modifier interaction matrix — 2026-10-31

**Status:** corrected 768-case run complete; flare defect fixed; **LIM-30 remains open.**

## Method

Synthetic fixtures, all four session types, every combination of:

- readiness: normal / low
- continuity gap: 7 / 28 / 56 days
- e1RM source: fresh / stale
- deload: off / scheduled
- back flare: none / level 2
- minimum session: off / 30 minutes
- technique throttle: off / on

Total cases: **768**; built: **768**; build errors: **0**; invariant flags: **192**.

Harness: tools/modifier_matrix.py. Raw results: W3-INTERACTION-MATRIX-2026-10-31.json.

## Corrections and fix applied

- Added main-lift history for every session type, so stale-e1RM cases are executable.
- Restricted RIR 1-4 checking to primary compounds, matching PRG-RIR-001.
- Recorded the owner's decision that 0.5 kg is rounding tolerance.
- Fixed DEC-BACK-03: back-flare effort now applies after readiness, so the load is solved for
  the RIR that is actually shown. A focused regression test covers low readiness.
- The 192 flare load increases are gone after the fix.

## Remaining finding

All 192 remaining flags are **added_item: box_jump** in minimum-session comparisons.

This is not a harness artifact. The engine runs deload before the minimum session. A deload
reduces the estimated session time, so the minimum-session trim can retain box_jump that the
no-deload minimum session removed. Relative to no-deload-plus-minimum, that is an added item.

Whether this is acceptable is now a policy question:

1. keep the current order and accept that a deload can preserve a power item the minimum
   session would otherwise trim; or
2. make the minimum-session result monotonic so a deload can never retain more work than the
   same minimum session without deload.

Current recommendation: option 2 if the W3 no-add invariant is intended to apply across the
whole modifier stack; option 1 if deload is allowed to change the minimum-session time budget.

## Regression coverage

- tests/test_back_flare_interactions.py::test_low_readiness_flare_never_increases_main_load
- Existing W3/deload/minimum tests still pass.

## Boundary

This is an invariant audit, not a claim that every combination is desirable training. LIM-30
remains open pending the box_jump policy decision.
