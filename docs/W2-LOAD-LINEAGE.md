# W2 — LOAD LINEAGE AND INCOMPLETE SESSIONS

**Status:** audit complete and fixes implemented 2026-10-23. Regression tests added.
**Method:** code-path trace, synthetic fixtures and existing tests. No personal data.
**Scope:** e1RM → load → validation; incomplete workouts; variants and bodyweight work.

---

## 1. Load-lineage table

| input | function | output | validation / visibility |
|---|---|---|---|
| formula e1RM from clean working sets | `_latest_e1rm` | best effective e1RM in the window | `PRG-RIR-001` + `set:<session>/<set>` ref; `MOD-E1RM-DECAY-001` when decayed |
| measured-test calibration | `e1rm_calibration.factors` | bounded correction factor | `MOD-E1RM-001`; calibration table |
| manual e1RM override | `queries.e1rm_override` | override × decay | `e1rm_override:<id>` ref + warning |
| stale/no e1RM | `_last_working_set` | last working load, rounded down | ref `set:...`; warning names the stale window |
| no history at all | `build_item` | `load_kg=None` + reason | `NO_LOAD` issue; prescription not executable |
| bodyweight movement | `build_item` | `load_kg=0` for unweighted | `bodyweight_total`; no tonnage |
| added load | clean/load resolver | added load basis | `added`; total mass only for e1RM |
| rounding | `loads.solve_load` / `round_down` | increment-safe load | `LOAD_NOT_EXECUTABLE` if not a multiple |
| main-lift effort | `build_item` | RIR target | `RIR_OUTSIDE_WINDOW` |
| spine | `validate_prescription` | weekly cost | `SPINAL_CAP` |
| variants | `history_equivalents` + selection | source history for the chosen identity | selection A/B/C; date-scoped trap bar |
| workout actual sets | `workout._materialise` | session + clean_set | no planned-vs-actual load check |

### Precedence

```text
manual override
  → formula e1RM (calibration → decay)
  → last working load fallback
  → NO_LOAD
```

The override outranks formula and calibration. Calibration does not override a manual test.
Decay is suppressed when continuity already handles a 28+ day gap.

## 2. Confirmed defects

### W2-01 — RESOLVED — Workout materialisation misclassified added bodyweight load

**Classification:** confirmed defect; fixed.

`workout._materialise` does not reuse `domain.load.resolve_load_basis`. For a
`bodyweight_type` exercise with a positive logged load it writes:

```text
load_basis = "external"
external_load_kg = 5
```

instead of:

```text
load_basis = "added"
external_load_kg = 5
```

Synthetic reproduction:

```text
back_extension @ 5 kg
→ clean_set.load_basis = external
→ expected: added
```

The workout path now calls `domain.load.resolve_load_basis` with the date's bodyweight when
available. Missing bodyweight becomes `unknown` with a flag, not a false `external` basis.

### W2-02 — RESOLVED — Incomplete workouts claimed unperformed main lifts

**Classification:** confirmed defect / provenance gap; fixed.

A workout with a five-set squat and four-set bench plan was ended after one squat set. The
materialised session contained:

```text
set_count = 1
working_set_count = 1
exercise_count = 1
main_lifts = ["ssb_squat", "bench_press"]
flags = []
```

`main_lifts` comes from the frozen **plan**, not from the performed sets. The bench press was
never performed but is reported as a session main lift. There is no `incomplete` flag or
planned-versus-performed completion field.

Effects:

- session summaries/UI can claim a lift was trained when it was not;
- attendance counts the session as completed;
- volume/under-MEV sees actual sets, but the session-level description is contradictory;
- the next prescription has no way to know the session was ended early.

The session now derives `main_lifts` from performed sets and adds an `incomplete` flag when
the performed sets are below the modified plan. The e1RM itself still comes from performed
sets.

## 3. Provenance gaps without a wrong load

### W2-03 — RESOLVED — e1RM source width is recorded

**Classification:** fixed.

`_latest_e1rm` selects the best effective set; there is no minimum set count, working-set
coverage or `incomplete` marker. A single hard set from an early-ended workout becomes the
next e1RM source and is cited accurately, but the prescription does not say the estimate came
from one set.

The estimate is arithmetically valid; the confidence is not represented. Do not treat it as a
phantom progression without deciding what “enough work for an e1RM” means.

### W2-04 — Last-working-load fallback is visible but has no decay

**Classification:** confirmed trade-off.

When no e1RM exists in the window, the last working load is reused and a warning is emitted.
The load is real, but it is not decayed; continuity handles the return separately. The
provenance is visible, so this is not a hidden fallback.

## 4. Cases that behave correctly

| case | result |
|---|---|
| manual override precedence | override wins; ref and warning present |
| measured test calibration | bounded factor; `MOD-E1RM-001`; tests pass |
| e1RM decay inside window | decayed; `MOD-E1RM-DECAY-001` |
| gap ≥28 days | e1RM decay suppressed; continuity handles load |
| no e1RM, last working load exists | reused load; warning and set ref |
| no history | `NO_LOAD`; prescription not executable |
| bodyweight 0 | valid `bodyweight_total`; not treated as missing |
| variant substitution | load re-solved from the selected identity; A/B/C guard applies |
| warm-up RIR 6 | excluded from working volume/e1RM |
| rounding | rounds down; validator checks increment |

## 5. Exit-criteria assessment

- **Every prescribed load traceable to an input and citation:** mostly yes; `NO_LOAD`, fallback,
  override, calibration and set refs are visible.
- **Incomplete work does not create phantom progression:** no phantom e1RM found, but the
  incomplete session is not labelled and can claim unperformed main lifts.
- **Variant changes never silently reuse incompatible loads:** no confirmed violation in the
  tested paths; selection comparability and history equivalence are explicit.

## 6. Implemented fixes

1. Workout materialisation now uses `resolve_load_basis`; missing bodyweight is `unknown`.
2. Session `main_lifts` come from performed sets.
3. `session.flags` carries `incomplete` when performed sets are below the modified plan.
4. Single-set e1RM sources emit a confidence warning and the item records `e1rm_source_sets`.
5. Regression tests cover bodyweight basis and incomplete main-lift provenance.

Remaining: the last-working-load fallback is still undecayed; continuity handles the gap. A
full e1RM coverage field was not added; the warning is the visible provenance.
