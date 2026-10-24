# WEB UI

A local browser interface over the same Python core. It is an additional surface, not a
replacement for the CLI.

## Run

```bash
./run-web.sh                       # launcher: finds the venv, opens the browser
./run-web.sh --no-open --port 8001
./run-web.sh --db other.db

strength-coach web                 # http://127.0.0.1:8000
strength-coach web --open
strength-coach web --port 8001
```

`run-web.sh` refuses a non-loopback `--host` and moves `--db` before the subcommand (it is a
global option in the CLI). It is convenience only: it ends in the same `strength-coach web`.

**Local only, no authentication.** The default bind is 127.0.0.1. Do not pass a public host.

## Pages

- **Today** — goal, block week, readiness, injury signal, unreviewed count, recent sessions, and a **Descriptive progress** panel (sRPE coverage, performance ratio, weekly volume status, latest back symptom; monitoring only).
- **Import** — upload the training and readiness CSVs; parsed in memory, hashed and stored in
  SQLite, never written to the repository. New cumulative exports are overlap-matched against
  stored rows, so old history is not duplicated. An **After the import** panel states the
  procedure: check the report, review recent sessions to create marks, then calibrate later —
  importing alone does not require a calibration.
- **Review** — unreviewed/recent session sheet; engine scores shown for context; human marks, optional session RPE and session length,
  plus a **Run rubric calibration** button (same report as `strength-coach calibrate`),
  confidence and note; calibration report after saving.
- **Readiness** — any subset of 1-5 and device fields, including optional wearable readiness;
  manual values win per field; the computed global/category score is shown; per-athlete
  baseline settings and the shadow baseline report are available; overrides take 0.00–1.00
  with a reason; the **Volume valve** sets the poor-readiness accessory set reduction; the volume ledger and MRV cap are on Prescribe. A current workout is refused until readiness is ready.
- **Prescribe** — date + session type (`auto` rolling, squat, hinge, bench+squat, bench+hinge); deterministic prescription, warnings and notes; every item cites
  rule ids. A `recent stress` column, a `readiness` column, the **strength fatigue model**
  panel (shadow: per-lift + overall fitness/fatigue/state with approximate 95% intervals,
  R²/status; no load effect), the **weekly volume** panel (hard sets by pattern against MEV/MAV/MRV landmarks; the MRV cap trims accessory sets; a separate heavy-spinal-set count at RIR ≤ 1 is context only), the **continuity calibration** panel (per-band returns/fixed/applied and the
  `allow_relax_fixed` setting) and the **exercise selection** panel (preview rankings with A/B/C
  comparison classes and a display-only own-history e1RM ratio; optional LLM chooser). The session is chosen by the rolling emphasis rule;
  **Apply selection** makes A candidates replace the slot exercises, **Confirm near-comparable**
  is required for B, and C is hidden unless **show different lifts** is ticked (and can never be
  applied automatically). **Use LLM** appears only when Apply is ticked. Without the toggle the
  prescription is unchanged. The **Retrospective validation** panel runs the walk-forward check. A scheduled deload is shown as a suggestion with an **Apply deload** button; it is not applied until confirmed. Reactive deloads are automatic. Applied deloads cite `MOD-DELOAD-001`. Main lifts show their warm-up ramp; the strength-test cadence is shown in the notes. The volume ledger now applies `MOD-VOL-002` (one accessory set after three weeks below MEV).
- **Workout** — start from a prescription, confirm the seven required readiness fields (device fields optional), log sets manually, remove a set, end with measured/manual duration and sRPE or mark sRPE not recorded, or abandon. A prescription snapshot is frozen at start. During the workout the plan is editable: adjust planned sets, swap/add/remove exercises; each change is an append-only event and the original prescription stays frozen. On completion the workout materialises, the end screen shows actual vs modified plan and actual vs original prescription, and the deterministic rubric is persisted. **Review workout** opens the rubric sheet; saving marks runs calibration and closes the workout. In-workout CSV import is available by paste or file with columns `Exercise,Set,RPE,Value,Weight,Reps`; preview first, then apply. A recognised exercise absent from the prescription is added to the workout plan; an unrecognised exercise is shown as unknown and blocks apply. The file has no date, so backfill is not supported.
- **Programme** — rolling session-type forecast; choose weeks, sessions/week, optional start
  date and first session type (`auto` or a specific type).
  every session is rebuilt on the day and nothing is persisted.
- **Cardio** — log a session (modality, minutes, HR, distance, sRPE) choose the window (4/12/26/52 weeks) and an optional as-of date:
  sessions, total/average minutes, weekly breakdown and the WHO reference as context. Capture
  only; no load changes.
- **Measures** — periodic outcomes (VO2max, grip, 5x sit-to-stand, steps, sitting), with latest
  value, change and entries, filtered by metric. Metrics and directions are config;
  nothing changes a load.
- **Exercises** — full canonical catalogue with search/filter, all properties per row, and an
  add/edit form. Edits are written to `config/exercises/overrides.v1.yaml`; ids are immutable.
- **Athlete** — append-only editing of profile, constraints, suitability, e1RM overrides,
  strength tests, block start and symptoms; shows the current tables, injury signal and the
  **e1RM calibration** report (current formula e1RM and last set for every lift, plus
  measured tests vs formula; a bounded correction is applied only when the confidence interval
  excludes 1.0).
- **Terminal** — restricted `strength-coach` command runner bound to the UI database.
- **Docs** — local Markdown rendered without external assets.

## API

| route | purpose |
|---|---|
| `GET /api/overview` | dashboard data |
| `POST /api/import` | `{training: {name, text}, readiness: {name, text}}` -> import report |
| `POST /api/prescribe` | `{date, session_type?, apply_selection?, selection_confirmed?, selection_llm?}` -> prescription; `session_type=auto` uses the rolling rule |
| `POST /api/workout/start` | `{date, plan, readiness, note?}` -> live workout; seven readiness fields required |
| `GET /api/workout/active` | active workout, or `{workout: null}` |
| `GET /api/workout/<id>` | workout detail |
| `POST /api/workout/<id>/sets` | `{exercise_id, load_kg, reps, rir, velocity?}` -> add manual set |
| `POST /api/workout/<id>/remove-set` | `{set_id}` -> append a removal event |
| `POST /api/workout/<id>/end` | `{session_rpe?, not_recorded?, duration_min?, notes?}` -> completed |
| `POST /api/workout/<id>/update-set` | `{set_id, load_kg, reps, rir, velocity}` -> append correction event |
| `POST /api/workout/<id>/import` | `{text, apply}` -> parse/preview/apply workout CSV; no date column |
| `POST /api/workout/<id>/import/undo` | undo the latest import batch |
| `POST /api/workout/<id>/abandon` | abandon the active workout |
| `GET /api/review/<session>` | session sheet |
| `POST /api/review/<session>` | `{scores, confidence, note, session_rpe, session_minutes}` -> marks + optional session detail |
| `GET /api/readiness/<date>` | merged readiness |
| `POST /api/readiness` | `{date, values, note}` -> merged readiness + score |
| `POST /api/readiness/override` | `{date, scope, value, reason}` -> merged readiness + score |
| `GET /api/readiness/calibrate` | calibration report text (no auto-apply) |
| `GET /api/state` | profile, constraints, suitability, e1RM, symptoms, injury signal |
| `GET /api/exercises` | canonical exercise catalogue for the pickers |
| `POST /api/programme` | rolling forecast; returns dated entries and prescriptions |
| `GET /api/cardio?weeks=N` | cardio summary for the window |
| `POST /api/cardio` | `{date, modality, minutes, avg_hr, max_hr, distance_km, srpe, note}` -> summary |
| `GET /api/fatigue?date=N` | strength fitness-fatigue shadow model (per-lift state and status) |
| `GET /api/validation?max_dates=N` | retrospective walk-forward report (not prospective) |
| `GET /api/continuity?date=N` | return-to-training calibration: per-band n/median/CI/fixed/applied and `allow_relax_fixed` |
| `GET /api/volume?date=N&weeks=4` | weekly hard-set ledger by movement pattern (advisory) |
| `GET /api/progress?date=N` | descriptive progress: sRPE coverage, performance ratio, volume status, latest back symptom |
| `GET /api/exposures?date=N` | recent high-intensity exposures and recovery guard |
| `POST /api/exposures` | log a manual max/competition/unplanned exposure; tests use the test endpoint |
| `POST /api/continuity/settings` | `{allow_relax_fixed}` -> update the calibration policy |
| `POST /api/readiness/volume` | update the readiness volume valve (enabled, score below, sets, include essentials) |
| `GET /api/selection?date=N&session_type=X&llm=0\|1&include_different=0\|1` | exercise-selection rankings with A/B/C comparability classes |
| `GET /api/exercises/catalog` | full exercise catalogue with source/properties |
| `POST /api/exercises` | create/update an entity in `config/exercises/overrides.v1.yaml` |
| `GET /api/measurements` | metric catalogue, per-metric summary and recent entries |
| `POST /api/measurements` | `{metric, value, date, method, note}` -> summary |
| `POST /api/terminal` | one restricted `strength-coach` command |
| `POST /api/state/profile` / `constraint` / `suitability` / `e1rm` / `test` / `symptom` / `block` | append-only state writes |
| `GET /api/calibrate` | calibration report |
| `GET /api/docs` / `GET /api/docs/<name>` | doc list / rendered doc |

## Design

The web layer is serialisation and routing only. It calls the same functions as the CLI:
`build_prescription`, `build_facts`/`score_session`, `record_marks`, `record_manual`, and
`backtest`. A missing value is still `unknown`; the UI does not fill it in.

## Limitations

- No LLM proposal/chat UI; this is closed as CLI-only (`run --propose`), not pending.
- Workout mode is UI-first for start; CLI covers status/add/update/remove/end/import. Completed workouts materialise into `session`/`clean_set`; review/rubric is built.
- State editing is available; the taxonomy itself and programme rules remain config/CLI.
- No authentication; never expose beyond localhost.
- No delete/void action for a completed workout; only active-workout abandon and set removal/edit. See DATA-MODEL §17 for the recommended void design.
