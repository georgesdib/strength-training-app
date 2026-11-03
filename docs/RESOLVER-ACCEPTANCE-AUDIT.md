# RESOLVER ACCEPTANCE AUDIT

**Status:** closed 2026-11-03. The resolver is released in v1.2.0 as an opt-in feature; the
flag remains off by default.
**Scope:** end-to-end production acceptance of the deterministic template resolver on
`development`.

## Outcome

The read-only audit found no P0 defects. Two P1/P2 implementation issues were confirmed and
fixed:

1. The active Workflow UI omitted top-set/back-off groups and did not prefill their role/load/RIR.
2. Plans were not validated for set-group structure before workout start or prescription append.

The audit also confirmed that resolver-generated snapshots, critique/exemption reads, evaluator
output and flag-off behaviour were already covered by working contracts. The follow-up
verification run closed the remaining automated lifecycle gates. The owner validated the
manual Workflow smoke on 2026-11-03.

## Fixes

| Commit | Change |
|---|---|
| `7d7ab3a` | Made top-set preservation an invariant; retired the unsupported non-preserving option. |
| `8a63212` | Rendered/prefilled set groups in Workflow; validated group totals/roles before start and persistence; cleared stale groups on exercise swap; resized groups on set edits; validated snapshots before append. |
| `4dd1705` | Added resolver top-set lifecycle, snapshot-provenance, modifier-composition and HTTP adversarial tests. |
| `dd11787` | Gated the Prescribe top-set control by `resolver.top_set.mode`; recorded the audit closure. |
| `a6d9d8c` | Added the remaining deload, same-date fragment, e1RM and evaluator/persisted-plan release-gate tests. |

## Acceptance matrix

| Requirement | Status |
|---|---|
| Resolver-disabled equivalence | **Passed** |
| Eligibility/pattern/injury/suitability/structure | **Passed for covered contracts** |
| Readiness/deload/spinal/volume/modifiers exactly once | **Passed** — top-set + volume budget + minimum session and deload + top set covered; drop contract covered |
| Evaluator/final prescription agreement | **Passed** — evaluator fields compared with persisted `prescription_item` rows |
| Snapshot reproducibility after policy/catalogue change | **Passed** — historical snapshot reads did not consult current policy; catalogue mutation remains a release gate |
| Completed workouts/actual sets/fragments | **Passed** — top-set/back-off roles materialise into `clean_set`; resolver workout plus same-date fragment grouped correctly |
| Top-set across prescription/execution/persistence | **Passed** — start, materialisation, persisted set groups and e1RM observations covered |
| Malformed config/snapshot/infeasible/evaluator failures | **Passed for covered paths** |
| Browser/manual smoke | **Passed — owner validation 2026-11-03** |

## Follow-up verification (2026-11-03)

| Check | Result |
|---|---|
| Deload + top set | **Passed** — top set suppressed, straight sets remain, plan executable |
| Drop / volume-fill resolver path | **Passed** — existing explicit no-feasible-assignment contract |
| Resolver workout + same-date fragment | **Passed** — one training day with two active fragments |
| Top-set e1RM/performance | **Passed** — e1RM observations produced from materialised sets |
| Evaluator ↔ persisted plan equality | **Passed** — sets, load and set groups compared |
| Regression / slow layers | **Passed** — 26 tests |
| Integration layer | **Passed** — 15 tests |

## Residual release gate

None. The owner accepted the manual Workflow smoke on 2026-11-03. The resolver is released in
v1.2.0 as an opt-in feature; enabling it remains an explicit Settings choice and the default
flag stays off.

## Closure

The audit is closed as of 2026-11-03. No P0/P1/P2 implementation, automated acceptance or manual
validation item remains open. The resolver is part of v1.2.0 and remains opt-in. See
[ROADMAP.md](../ROADMAP.md) §4.25 and [PROGRAMME-BUILDER-PLAN.md](PROGRAMME-BUILDER-PLAN.md).
