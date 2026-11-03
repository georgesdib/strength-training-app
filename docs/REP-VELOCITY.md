# Rep-level velocity — optional post-workout detail

**Status:** capture, descriptive cross-session analysis and the evidence review are implemented.
The review supports descriptive use only; no rule or prescription change.

The set-level CSV remains required and unchanged. The per-rep table is optional: if it is
absent, every existing path behaves exactly as before.

---

## 1. Input contract

### Main CSV (required, unchanged)

```csv
Exercise,Set,RPE,Value,Weight,Reps
```

`Value` is the authoritative set-level mean.

### Per-rep CSV (optional)

```csv
Exercise Name,Set Number,Metric Name,Rep Number,Velocity
Push Press,3,Mean Concentric Velocity,,0.780
Push Press,3,Mean Concentric Velocity,1,0.740
Push Press,3,Mean Concentric Velocity,2,0.740
Push Press,3,Mean Concentric Velocity,3,0.750
Push Press,3,Mean Concentric Velocity,4,0.880
```

Rules:

- one file, joined by canonical exercise + set number;
- blank `Rep Number` = optional set mean;
- `Rep Number 1..n` = rep samples;
- only `Mean Concentric Velocity` accepted; one metric per set;
- `Velocity` is m/s;
- the main CSV `Value` wins when both means exist;
- a per-rep set must match an existing set row; it never creates a set;
- missing middle reps are allowed but reported;
- duplicate reps, rep numbers above `Reps`, unknown exercises, unsupported metrics and
  unmatched sets block apply.

The tolerance for a main-mean vs per-rep-mean mismatch is **0.01 m/s**, and a mismatch is a
warning rather than an overwrite.

## 2. Storage

- `workout_rep_event` stores append-only per-set snapshots while the workout is in progress.
- `clean_rep` stores individual rep velocities after completion, linked to `clean_set.set_id`.
- `clean_set.velocity_mps` remains the set mean.
- Import undo restores the previous rep snapshot.

## 3. Status

| phase | status |
|---|---|
| schema, parser, preview/apply, undo | done |
| materialisation into `clean_rep` | done |
| optional Workout UI / CLI / API input | done |
| per-set first/last/loss report | done |
| cross-session descriptive analyses | done |
| evidence review: "does this add information beyond existing signals?" | done — descriptive only |

## 4. What it unlocks

Per set:

- first, last, mean, min/max;
- absolute and percentage velocity loss;
- rep count and missing-rep count;
- main mean vs per-rep mean.

Per session and across sessions:

- loss by exercise and set order;
- trend at similar load/reps;
- descriptive association with RIR/RPE, sRPE, readiness, next-session performance and
  back symptoms;
- data-quality review.

## 5. What it does not do

- no live set termination;
- no load or volume adjustment;
- no automatic RIR inference;
- no prescription or cap input;
- no replacement for sRPE/readiness.

The evidence-supported use of velocity loss is live set termination. Captured after the
workout, it is descriptive.

## 6. Surfaces

- Workout mode: optional per-rep file/paste box, preview table and rep summary.
- `GET /api/rep-velocity?session=...`: per-session report.
- `GET /api/rep-velocity/analysis?weeks=...`: stratified cross-session report.
- **Progress → Per-rep velocity**: correlations (n >= 10), recent session rows and missing-data context.
- CLI: `workout import --rep-file ...`.
- End screen: per-set first/last/loss table.
- Evidence: [REP-VELOCITY-EVIDENCE.md](REP-VELOCITY-EVIDENCE.md).

## 7. How to use it

1. Record the workout with the required set-level CSV/mean. The per-rep table is optional and
   does not replace it.
2. Export the per-rep CSV from the device.
3. In Workout mode, paste/choose the main CSV and the per-rep CSV in the same import panel;
   preview before applying.
4. The preview shows the optional per-rep rows; matching is by canonical exercise + set number.
   An unmatched set, unsupported metric, duplicate rep or value above `Reps` must be fixed
   before apply.
5. After apply, use the end-screen **Per-rep velocity** table and **Progress → Per-rep
   velocity**. The cross-session report shows correlations only at `n >= 10` paired
   observations; `insufficient` means collect more sessions, not that a feature is missing.
6. Treat every output as descriptive. The set-level mean remains the VBT calibration input;
   per-rep data does not set a velocity target, RIR or load.

## 8. Tests

- no per-rep table → current import unchanged;
- blank mean only;
- reps only → derived mean;
- main mean wins and mismatch warns;
- unmatched set, unknown metric, duplicate/out-of-range rep block apply;
- undo restores reps;
- materialisation writes `clean_rep`;
- report is descriptive and never changes a prescription.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REP-VELOCITY-EVIDENCE.md](REP-VELOCITY-EVIDENCE.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
