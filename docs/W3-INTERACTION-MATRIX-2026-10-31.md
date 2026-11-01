# W3 modifier interaction matrix — 2026-10-31

**Status:** corrected 768-case run complete; no modifier behaviour changed. **LIM-30 remains open.**

## Method

Synthetic fixtures, all four session types, every combination of:

- readiness: normal / low
- continuity gap: 7 / 28 / 56 days
- e1RM source: fresh / stale
- deload: off / scheduled
- back flare: none / level 2
- minimum session: off / 30 minutes
- technique throttle: off / on

Total cases: **768**; built: **768**; build errors: **0**; invariant flags: **384**.

The run used four parallel session-type shards. Harness: tools/modifier_matrix.py. Raw results:
W3-INTERACTION-MATRIX-2026-10-31.json.

## Corrections applied before this run

- Added main-lift history for every session type, so stale-e1RM cases are executable.
- Restricted RIR 1-4 checking to primary compounds, matching PRG-RIR-001.
- Recorded the owner's decision that **0.5 kg** is rounding tolerance, not a policy violation.
- Kept larger load increases as failures.

## Results

| Category | Count | Classification |
|---|---:|---|
| `added_item` | 192 | Unresolved harness/comparison issue; all flags are box_jump in minimum-session pairs |
| `flare_increased_load` | 192 | **Real-looking defect**: low-readiness back flare raises main-lift loads by about 2 kg, above the 0.5 kg rounding tolerance |

The earlier `not_executable` (480) and `rir_window` (84) flags are gone after the fixture and
scope corrections.

## Flare defect detail

A stale-e1RM, low-readiness squat case gives:

- no flare: SSB **120.5 kg**, RIR 4, factor 0.85
- flare: SSB **124.0 kg**, RIR 4, factor 0.85

A fresh-e1RM low-readiness case gives the earlier 123.5 → 124.0 kg change. The low-readiness
flare path can therefore solve a load at a harder RIR before readiness raises the shown RIR,
leaving the final load too high. This is not covered by the 0.5 kg rounding decision.

## Added-item issue

All 192 flags are box_jump in minimum-session comparisons. Manual reproduction still shows
box_jump in the base case, so the comparison/cache path is not trusted. This must be resolved
before the matrix can be used as a LIM-30 closure gate.

## Next decision

The 0.5 kg policy covers small rounding changes, but the corrected matrix found ~2 kg
increases. Those are above the agreed tolerance. The flare path needs either:

1. a product fix so a reduction-only flare cannot increase load; or
2. an explicit wider acceptance decision.

**Recommendation:** fix the flare path and add a focused regression test, then resolve the
added-item harness issue and rerun.

## Boundary

This is an invariant audit, not a claim that every combination is desirable training. No
modifier, threshold, load, RIR or set policy was changed.
