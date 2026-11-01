# W3 modifier interaction matrix — 2026-10-31

**Status:** analysis run; no modifier behaviour was changed. **LIM-30 remains open.**

## Method

Synthetic fixtures, all four session types, every combination of:

- readiness: normal / low
- continuity gap: 7 / 28 / 56 days
- e1RM source: fresh / stale
- deload: off / scheduled
- back flare: none / level 2
- minimum session: off / 30 minutes
- technique throttle: off / on

Total cases: **768**; built: **768**; build errors: **0**; raw invariant flags: **732**.

The run used four parallel session-type shards. The harness is tools/modifier_matrix.py; raw
results are in W3-INTERACTION-MATRIX-2026-10-31.json.

## Invariants checked

- executable and non-empty;
- no duplicate items;
- sets >= 1;
- load present;
- non-power RIR 1-4;
- power RIR null and quality stop present;
- automatic load factor >= 0.80;
- reduction-only modifiers do not add items;
- readiness/deload/flare/minimum/throttle do not increase sets or load;
- readiness/deload/flare/minimum/throttle do not lower a non-power RIR target.

## Raw flags and preliminary triage

| Category | Count | Preliminary classification |
|---|---:|---|
| not_executable | 480 | Fixture limitation: stale-e1RM cases have no usable recent e1RM and no working-load fallback |
| flare_increased_load | 96 | Needs investigation; sampled squat cases differ by 0.5 kg |
| rir_window | 84 | Harness invariant too broad: accessory RIR reaches 5; PRG-RIR-001 applies to primary compounds |
| added_item | 72 | Unresolved harness/cache issue; manual reproduction of the box-jump pair did not reproduce it |

### not_executable

The stale-e1RM scenario deliberately removes recent main-lift e1RM. Without a recent estimate
and without a working-load fallback, the engine correctly marks the session non-executable. This
is not a modifier interaction; the fixture needs a valid fallback before those 480 cases can
test composition.

### flare_increased_load

Adding a low-back flare raised SSB squat load from **123.5 kg to 124.0 kg** in sampled
readiness-low cases, with the same 0.85 readiness factor and the same RIR 4. That direction is
not intended for a reduction-only modifier. It may be a rounding interaction or a real
back-flare load path; it needs a focused reproduction before classification.

### rir_window

The flagged items are accessories such as back extension, lying leg curls and ab wheel after
deload, at RIR 5. The RIR window rule applies to primary compounds. The matrix check should use
the rule's actual scope, not every non-power item.

### added_item

The flags all concern box_jump in minimum-session cases. Manual reproduction showed the base
case already contains box_jump, so the report's missing-base comparison is not yet trusted. This
needs a fresh-store reproduction and cache audit.

## Next pass

1. Replace the stale-e1RM fixture with a valid fallback so all 768 cases are executable.
2. Restrict the RIR check to items citing PRG-RIR-001 or otherwise in the primary-compound scope.
3. Reproduce the added_item pair with fresh stores and no cache reuse.
4. Reproduce the 0.5 kg flare load difference with a focused script.
5. Re-run the 768-case matrix and classify the remaining flags as defect, accepted policy, or
   invalid invariant.

## Boundary

This is an invariant audit, not a claim that every combination is desirable training. No
modifier, threshold, load, RIR or set policy was changed.
