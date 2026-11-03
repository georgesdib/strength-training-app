# RESOLVER ACCEPTANCE AUDIT

**Status:** closed 2026-11-03. The resolver remains off by default and is not released.
**Scope:** end-to-end production acceptance of the deterministic template resolver on
`development`.

## Outcome

The read-only audit found no P0 defects. Two P1/P2 implementation issues were confirmed and
fixed:

1. The active Workflow UI omitted top-set/back-off groups and did not prefill their role/load/RIR.
2. Plans were not validated for set-group structure before workout start or prescription append.

The audit also confirmed that resolver-generated snapshots, critique/exemption reads, evaluator
output and flag-off behaviour were already covered by working contracts, while several lifecycle
combinations remain unverified.

## Fixes

| Commit | Change |
|---|---|
| `7d7ab3a` | Made top-set preservation an invariant; retired the unsupported non-preserving option. |
| `8a63212` | Rendered/prefilled set groups in Workflow; validated group totals/roles before start and persistence; cleared stale groups on exercise swap; resized groups on set edits; validated snapshots before append. |
| `4dd1705` | Added resolver top-set lifecycle, snapshot-provenance, modifier-composition and HTTP adversarial tests. |

## Acceptance matrix

| Requirement | Status |
|---|---|
| Resolver-disabled equivalence | **Passed** |
| Eligibility/pattern/injury/suitability/structure | **Passed for covered contracts** |
| Readiness/deload/spinal/volume/modifiers exactly once | **Partially verified** — top-set + volume budget + minimum session covered; deload/drop combinations still release gates |
| Evaluator/final prescription agreement | **Passed for covered contracts**; field-by-field persisted comparison remains a release gate |
| Snapshot reproducibility after policy/catalogue change | **Passed** for reads not consulting current policy; catalogue mutation remains a release gate |
| Completed workouts/actual sets/fragments | **Partially verified** — top-set/back-off roles materialise into `clean_set`; same-date resolver fragments remain a release gate |
| Top-set across prescription/execution/persistence | **Passed for start and materialisation**; e1RM/performance analytics remains a release gate |
| Malformed config/snapshot/infeasible/evaluator failures | **Passed for covered paths** |
| Browser/manual smoke | **Not performed** |

## Residual release gates

These are not unresolved audit findings. They are checks required before enabling the resolver for
normal use:

- resolver + deload + top set;
- resolver + drop/volume-fill;
- resolver-generated workout plus imported/live same-date fragments;
- top-set actual sets in e1RM/performance summaries;
- full evaluator-to-persisted-plan field equality;
- optional integration/regression/slow layers;
- manual browser Workflow smoke.

## Closure

The audit is closed as of 2026-11-03. No P0/P1/P2 implementation item remains open, and the
resolver remains opt-in and off by default. Production enablement is still gated by the residual
release checks above. See [ROADMAP.md](../ROADMAP.md) §4.25 and
[PROGRAMME-BUILDER-PLAN.md](PROGRAMME-BUILDER-PLAN.md).
