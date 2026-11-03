# W3 modifier interaction matrix — 2026-10-31

**Status:** closed. 768 cases, 0 invariant flags, after three composition fixes.

## Method

Synthetic fixtures, all four session types, every combination of:

- readiness: normal / low
- continuity gap: 7 / 28 / 56 days
- e1RM source: fresh / stale
- deload: off / scheduled
- back flare: none / level 2
- minimum session: off / 30 minutes
- technique throttle: off / on

**768 cases built; 0 build errors; 0 invariant flags.**

Harness: tools/modifier_matrix.py. Raw results: W3-INTERACTION-MATRIX-2026-10-31.json.

## Fixes found and closed

1. **DEC-BACK-03 — flare effort after readiness.** The back-flare hold was solved at a harder
   RIR before readiness raised the shown RIR, so low readiness could load 2 kg higher. The
   hold now runs after readiness and the load is solved for the shown RIR.
2. **Minimum before deload.** A planned deload could preserve box_jump that the same minimum
   session without deload removed. The minimum trim now runs first; deload cannot add work.
3. **Deload compares with the current factor.** Deload was multiplying technique on
   normal-readiness items while low readiness skipped technique, so low readiness could end
   heavier. Deload now uses the item's current load factor, including technique.

Decision record: DEC-W3-03.

## Regression coverage

- test_low_readiness_flare_never_increases_main_load
- test_minimum_note_precedes_deload_and_deload_does_not_add_work
- test_low_readiness_never_ends_above_normal_with_deload_and_technique

## Boundary

The matrix checks structural composition invariants, not whether every combination is
desirable training. LIM-30 is closed under DEC-W3-03; reopen it if a modifier or modifier
order changes.
