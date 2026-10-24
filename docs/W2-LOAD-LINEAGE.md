# W2 — LOAD LINEAGE AND INCOMPLETE SESSIONS

**Status:** audit complete 2026-10-23. Two confirmed defects and two provenance gaps;
no fixes applied.
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

### W2-01 — Workout materialisation misclassifies added bodyweight load

**Classification:** confirmed defect.

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

This is a single-source-of-truth violation: imported rows go through
`resolve_load_basis`, live workout rows do not. It can distort tonnage, history equivalence and
future load interpretation for weighted bodyweight work.

### W2-02 — Incomplete workouts look complete and claim unperformed main lifts

**Classification:** confirmed defect / provenance gap.

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

The e1RM itself comes from the performed clean set, not the plan, so this is not a phantom
e1RM. It is a provenance/description defect.

## 3. Provenance gaps without a wrong load

### W2-03 — A single set can drive the e1RM without a quality marker

**Classification:** confirmed limitation.

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

## 6. Recommended fixes — not implemented

1. Use `domain.load.resolve_load_basis` in workout materialisation so added bodyweight load is
   classified once.
2. Derive session `main_lifts` from performed sets, not the frozen plan.
3. Add an explicit incomplete/ended-early marker, or a planned-versus-performed completion
   field, to the session/workout record.
4. Add a `set_count`/coverage field to the e1RM provenance, or document that a single set is
   sufficient.
5. Add regression tests for:
   - weighted bodyweight workout materialisation;
   - incomplete workout with unperformed plan items;
   - single-set e1RM provenance;
   - last-working-load fallback.

No code, config or prescription was changed by W2.
