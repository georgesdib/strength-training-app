# Rep-level velocity — optional post-workout detail

**Status:** capture implemented as an optional second CSV in workout mode. Cross-session
analysis and the evidence review are **not yet done**; do not treat the feature as complete.

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
| cross-session descriptive analyses | **pending** |
| evidence review: does this add information beyond existing signals? | **pending** |

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
- `GET /api/rep-velocity?session=...`: descriptive report.
- CLI: `workout import --rep-file ...`.
- End screen: per-set first/last/loss table.

## 7. Tests

- no per-rep table → current import unchanged;
- blank mean only;
- reps only → derived mean;
- main mean wins and mismatch warns;
- unmatched set, unknown metric, duplicate/out-of-range rep block apply;
- undo restores reps;
- materialisation writes `clean_rep`;
- report is descriptive and never changes a prescription.
