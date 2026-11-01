# W3 modifier interaction matrix — 2026-10-31

**Status:** final corrected run; flare and box_jump composition fixed; **LIM-30 remains open.**

## Results

- 768 cases built
- 0 build errors
- **32 invariant flags**
- All remaining flags are **readiness_increased_load**

## Fixes completed

- **DEC-BACK-03:** back-flare effort now runs after readiness; low-readiness flare loads no
  longer increase.
- **DEC-W3-02:** the minimum-session trim now runs before deload. A deload can no longer
  retain box_jump that the same minimum session without deload removed.
- Fixture corrections: every session type has a valid stale-e1RM fallback; RIR checks are
  scoped to primary compounds; 0.5 kg is the approved rounding tolerance.

## Remaining finding

The remaining 32 flags occur only when **low readiness + deload + technique throttle + flare**
coincide. Example:

- normal readiness, deload + flare + technique: SSB **121.0 kg**, factor 0.81
- low readiness, same modifiers: SSB **123.5 kg**, factor 0.85

Readiness alone should never make the load higher than normal. The cause is ordering: the
technique throttle sees low readiness's 0.85 factor as "already reduced" and does not apply,
while the normal case receives technique (0.90) and deload (0.90) as a lower combined factor.
This is a genuine composition interaction, not a fixture issue.

## Decision needed

1. **Fix the inversion — recommended.** Make the combined reduction monotonic across
   readiness, deload and technique; low readiness must never end above normal readiness.
2. **Accept it as an explicit policy exception** and document that technique throttle does not
   stack onto an already-reduced readiness item.

Current recommendation: option 1. No further product change was made in this run.

## Regression coverage

- tests/test_back_flare_interactions.py::test_low_readiness_flare_never_increases_main_load
- tests/test_w3_interactions.py::test_minimum_note_precedes_deload_and_deload_does_not_add_work

## Boundary

LIM-30 remains open pending the readiness/deload/technique ordering decision.
