# DATA MODEL

Storage: one SQLite file (`data/coach.db`), written through numbered migrations in
`strength_coach/store/migrations/`. Computation is done in pandas; SQLite holds state.

Rules that apply to every table: `created_at` is set by the store, never by caller;
artifacts are **append-only** (a correction inserts a new row and sets `supersedes_id`);
every row that came from a CSV keeps `source_row` so an error is traceable to a line.

---

## 1. `raw_row` — untouched intake

| column | type | notes |
|---|---|---|
| raw_id | INTEGER PK | |
| table_name | TEXT | `training` \| `readiness` |
| source_row | INTEGER | 1-based line in the CSV |
| file_sha256 | TEXT | which import produced it |
| payload | TEXT | the row as JSON, verbatim |

Nothing is ever deleted. `(null)` dates live here permanently. A cumulative re-export reuses
the existing raw row when its canonical payload is identical; duplicates *within* one file
still get separate rows (`DEC-IMPORT-01`, DQ-DUP-01).

## 2. `clean_set` — canonical training record

One row per *set*, not per exercise or session.

| column | type | notes |
|---|---|---|
| set_id | INTEGER PK | |
| raw_id | INTEGER FK | traceability |
| session_id | TEXT FK | e.g. `<YYYY-MM-DD>` |
| occurred_on | DATE | parsed; null dates are quarantined (see §4) |
| exercise_id | TEXT | canonical id from taxonomy |
| raw_exercise | TEXT | as logged |
| load_kg | REAL | normalised to kg |
| load_basis | TEXT | `external` \| `bodyweight_total` \| `added` \| `unknown` |
| external_load_kg | REAL | what was actually added; 0 for pure bodyweight |
| reps | INTEGER | |
| reps_unit | TEXT | `reps` \| `seconds` |
| rir | INTEGER | null when missing |
| rir_source | TEXT | `logged` \| `logged_warmup` (DEC-RIR-01) \| `assumed_default` \| `missing` |
| velocity_mps | REAL | null when device unused |
| velocity_present | INTEGER | 0/1 — one flag for the whole telemetry block; a `0.000000` reading is *absent*, not zero (DQ-SENT-01) |
| power_w | REAL | null |
| rom_mm | REAL | null |
| tut_s | REAL | null |
| form_score | INTEGER | **retired** (migration 0034): historical per-set Form was backfilled to `session_form_rating`; source remains in `raw_row.payload` |
| tonnage_kg | REAL | null when `load_basis != external` or `reps_unit = seconds` |
| is_working_set | INTEGER | excludes warm-up ramps |
| flags | TEXT | JSON list: `REPS_TYPO`, `LOAD_AMBIGUOUS`, `SECONDS_NOT_REPS`… |

`tonnage_kg` is deliberately nullable: `weight × reps` on a plank or a pull-up is
meaningless and must not be summed.

## 3. `session` — reconstructed

| column | type | notes |
|---|---|---|
| session_id | TEXT PK | date-based |
| occurred_on | DATE | |
| workout_label | TEXT | `Sheiko` \| `Freestyle` \| `Template` — provenance for rotation |
| set_count | INTEGER | |
| exercise_count | INTEGER | |
| main_lifts | TEXT | JSON list of canonical ids |
| working_set_count | INTEGER | working sets only (DEC-RIR-01 excludes warm-ups) |
| session_type | TEXT | `squat` \| `hinge` \| `bench_squat` \| `bench_hinge` \| `unknown` |
| tonnage_kg | REAL | sum of non-null `tonnage_kg` |
| duration_min | REAL | null by default; measured for live workouts, unavailable for imported rows |
| duration_basis | TEXT | `measured` \| `unavailable` |
| flags | TEXT | `POSSIBLE_DOUBLE_SESSION`, `NO_MAIN_LIFT`, … |

## 3b. `high_intensity_exposure` — near-max work outside volume

| column | notes |
|---|---|
| exposure_id PK | UUID |
| performed_on | date |
| kind | `test` \| `max_attempt` \| `competition` \| `unplanned` \| `other` |
| exercise_id | nullable for mixed/unknown events |
| session_id / set_id | optional link to an already-counted set; never double-counted |
| region_load | `upper` \| `lower` \| `axial` \| `mixed` \| `unknown` |
| intensity_class | `near_max` \| `high` \| `moderate` \| `unknown` |
| axial_cost | existing taxonomy `spinal_cost` where available |
| novelty | `familiar` \| `novel` \| `unknown` |
| test_type | `1RM` \| `3RM` \| `5RM` \| `other`; tests only |
| source | `test_record` \| `set_link` \| `manual` |
| source_id / supersedes_id | idempotency and append-only correction |
| note | optional |

This table is not part of the volume ledger. Tests auto-create a `test_record` exposure; a
set-linked PR stays in volume and uses the exposure only for the recovery guard.

## 3c. `prescription_modifier` — modifier provenance

| column | notes |
|---|---|
| modifier_id PK | UUID |
| prescription_id | stored prescription |
| modifier_key | `MOD-FAT-001`, `MOD-GAP-001`, `MOD-DELOAD-001`, `MOD-VOL-001/002`, `MOD-SELECT-001`, `MOD-MIN-001` |
| applied_on | date |
| detail_json | before/after and reason references |
| created_at | timestamp |

Append-only. Provenance only; it does not change a prescription. CLI `run` records it after
storing a prescription. The web start-workout path now stores the committed plan as a
prescription and records the same provenance in the same transaction.

## 3d. `readiness_context` — display-only context flags

| column | notes |
|---|---|
| context_id PK | UUID |
| on_date | date |
| flag | `travel`, `timezone_change`, `illness`, `alcohol`, `poor_sleep_environment`, `high_work_stress` |
| note | optional |
| created_at | timestamp |

Append-only. Flags are displayed beside readiness and do not alter the score by default.
`device_suppression_flags` in `config/readiness.v1.yaml` can explicitly suppress HRV/RHR for
selected flags; the default list is empty. `readiness_entry.source` now includes `preset`.

## 3e. `volume_exemption` — safety cuts that lower the weekly target

| column | notes |
|---|---|
| exemption_id PK | autoincrement |
| prescription_id | stored prescription that made the cut |
| effective_on | date of the cut |
| pattern | ledger group (squat, hinge, horizontal_push, ...) |
| sets | positive integer removed |
| source | `MOD-FAT-001`, `MOD-DELOAD-001`, `MOD-SPINE-001` or `CONSTRAINT` |
| recorded_at | timestamp |

Append-only. The weekly volume budget must not re-add volume that readiness, deload, a spinal
trim or a constraint removed (`DEC-VOLUME-06`). The prescription table has no notes column, so
the amount and its source live here. A missed session has no prescription and therefore no row;
the budget reallocates only scheduling shortfalls, never safety cuts.

## 4. Quarantine

`raw_row` rows that cannot be placed (rows with a null date) stay in `raw_row` and get a
`quarantine` row with a reason. They are counted in the run report. They are never
silently dropped, because doing so hid exactly 8 false `RIR 0` bench violations and 6 for
trap bar.

| column | type | notes |
|---|---|---|
| quarantine_id | INTEGER PK | |
| raw_id | INTEGER FK | the line that could not be placed |
| reason | TEXT | `null_date` \| `unknown_exercise` |
| created_at | TEXT | set by the store |

## 5. `readiness_day`

| column | notes |
|---|---|
| on_date PK | |
| sleep, energy, mood, soreness, stress, nutrition, hydration | 1–5, higher better, null when absent |
| squat_readiness, bench_readiness, deadlift_readiness | 1–5 or null |
| hrv_ms, rhr_bpm, bodyweight_kg, fat_pct, grip_strength_kg | null when 0 sentinel |
| wearable_score | 0–100 device-computed readiness; null when absent; 0 is a valid worst score |
| composite | derived, 0–1, with `composite_basis` listing which inputs existed |
| merge_note | JSON: which duplicate rows were considered and why one won |

Duplicate-readiness merge rule is DQ-RD-01; implemented as most-complete-row, ties to the
latest (`DEC-READINESS-01`, `ingest/readiness.py`). `composite` stays null until the metric
directions in Q6 part 2 are declared.

### 5.1 `readiness_entry` (append-only)

| column | notes |
|---|---|
| entry_id PK | opaque id |
| on_date | the day the reading describes |
| field | one of the readiness fields |
| value | numeric; 1–5 for score fields, positive for device fields (including grip strength in kg), 0–100 for wearable_score |
| source | `manual` (currently the only writer) |
| recorded_at | when it was entered |
| note | optional |

Manual readings are one row per field, never an update. `queries.readiness_day` overlays the
latest entry per (date, field) over the imported `readiness_day` row, so a manual value wins
**per field** and the imported fields around it survive (`DEC-READINESS-03`). The returned
dict includes `sources` and `manual_merge_note` (imported value, manual value, winner) so the
override is auditable. `readiness_day` remains the imported, derived row.

### 5.2 `readiness_override` (append-only)

| column | notes |
|---|---|
| override_id PK | opaque id |
| effective_on | the day the override applies to |
| scope | `global` or `category:<name>` |
| value | 0.00–1.00, same scale as the computed score |
| reason | required |
| source | user |
| created_at | when entered |

The latest row per (date, scope) wins. A category override wins over global, which wins over
the computed score; the winning value goes through the load-factor table, but never bypasses a
constraint or injury ceiling. The legacy `squat_readiness`/`bench_readiness`/`deadlift_readiness`
columns are calibration labels, not manual inputs.

The full derivation — sentinels, merge, storage, and what actually moves a load — is
[`docs/READINESS.md`](READINESS.md). Which fields drive MOD-FAT-001, the threshold and the merge
tie-break are config (`config/readiness.v1.yaml`, `DEC-READINESS-04`).

### 5.3 `readiness_setting` (append-only, per athlete)

| column | notes |
|---|---|
| setting_id PK | opaque id |
| effective_from | date the setting takes effect |
| baseline_days / baseline_min_readings | HRV/RHR baseline window and minimum |
| hrv_slope / rhr_slope | ratio half-width for normalisation |
| hrv_weight / rhr_weight / wearable_weight | weights/blend |
| note | optional |
| source | user |
| created_at | when entered |

The latest row with `effective_from <= date` wins. It overrides `config/readiness.v1.yaml`;
no row means config/defaults. Append-only, because changing a baseline changes a prescribed
load.

## 6. `vbt_calibration` — append-only, versioned

| column | notes |
|---|---|
| calibration_id PK | |
| exercise_id / vbt_family | which target this calibrates |
| scope | `lift` \| `family` \| `global_prior` |
| rep_count | target applies at this rep count |
| rir_low / rir_high | the window bounds, e.g. 2 and 3 (stored as two columns so SQL can compare) |
| velocity_median, velocity_mad | m/s |
| velocity_low, velocity_high | robust band with relative floor |
| n_sets, n_sessions, window_start, window_end | provenance |
| method_version | calibration algorithm version |
| params_json | k, floor, exclusions — hashed |
| source | `computed` \| `override` |
| override_reason | required when `source = override` |
| valid_from, valid_until | overrides may expire |
| supersedes_id | |

A prescription stores the `calibration_id` it used, so a past call is reproducible even
after recalibration.

## 7. `rule_document` / `rule`

| column | notes |
|---|---|
| document_id PK-part | `programme.constitution`; the key is (document_id, version), because a new version is a new row |
| version | semver |
| effective_from | date |
| source_hash | hash of the YAML |
| body_yaml | the full document |

`rule` holds one row per rule ID (`PRG-RIR-001` …) with `severity`, `scope`, `check_fn`,
`citations`, and `depends_on_data_decisions`. Rules are immutable; a change is a new
document version.

## 8. `prescription` / `prescription_item` — append-only

| prescription column | notes |
|---|---|
| prescription_id PK | |
| run_id | trace |
| for_date | |
| session_type | squat/hinge/bench_squat/bench_hinge |
| fallback_level | `full` \| `fatigue_reduced` \| `llm_downgraded` |
| rule_document_version | |
| calibration_ids | JSON |
| approved_by | `deterministic` \| `llm+policy` |

| item column | notes |
|---|---|
| item_id PK | |
| prescription_id FK | |
| order_index | |
| exercise_id | |
| sets, reps_low, reps_high | |
| load_kg, load_basis, rounding_increment | |
| rir_target | |
| velocity_target | nullable, with `vbt_basis` |
| rest_s, time_cap_s | |
| essential | 0/1 |
| rationale_refs | JSON list of rule IDs + data-point ids |
| e1rm_source_sets | nullable; usable sets behind a formula e1RM (NULL for overrides/fallbacks) |
| substitution_for | nullable |

### 8.4 `workout_form_rating` / `session_form_rating`

Optional post-lift form assessment, one 1-5 rating per exercise.

| table | purpose |
|---|---|
| `workout_form_rating` | append-only ratings while a workout is open; latest row per exercise wins |
| `session_form_rating` | materialised at workout end; later History edits insert a superseding row |

Rating 1-5, higher is better. The rubric scores the mean over rated lifts; an unrated lift is
not a zero. The imported `Form` column remains separate and unused because its direction is
unconfirmed.

## 9. `critique` / `rubric_score`

`critique` stores the narrative plus `facts_hash`; `rubric_score` stores one row per
rubric item (`RIR_ADHERENCE` …) with `score`, `weight`, `evidence_refs`, `rule_ids`, and
`measurable` (0/1). Metrics that the data cannot support — imported-session duration, within-set velocity loss —
are stored with `measurable = 0` rather than a guessed score. Measured live-workout duration
is scored.

## 10. `run` — the trace

| column | notes |
|---|---|
| run_id PK | |
| started_at, finished_at | |
| input_hash | hash of the source rows used |
| code_version, config_hash | |
| window_start, window_end | |
| llm_model, llm_tokens | null when `NullLLM` |
| status | `ok` \| `llm_failed` \| `llm_downgraded` \| `error` |

`run_event` is the append-only log: ordered `(run_id, seq, kind, payload)` where `kind` is
`input` \| `feature` \| `tool_call` \| `llm_output` \| `policy_verdict` \| `artifact`.

---

## 11. Athlete state — goals, constraints, suitability, metric definitions

These four tables exist so that *you* (goals, injuries, tightness, preferences) are
**state**, not prompt text. A hard constraint stored here can veto a prescription
deterministically, no matter what the LLM says. They are empty until the user answers
`docs/INFO-REQUESTS.md`.

### 11.1 `athlete_profile` — singleton, versioned

| column | notes |
|---|---|
| profile_id PK | |
| effective_from / effective_to | goals change; old prescriptions must still explain themselves |
| primary_goal | `strength` \| `hypertrophy` \| `body_comp` \| `pain_free` \| `longevity` \| `competition` |
| goal_rank | JSON ordered list; a conflict between erector ramp and squat volume is resolved by this |
| focus_lifts | JSON list of exercise ids that matter most |
| competition_date | nullable |
| sessions_per_week_target | the *intended* frequency, so the rubric can separate intent from execution |
| max_session_minutes | planned session-time target; may be raised or lowered by the athlete |
| block_start_date | week 1 of the **erector ramp**, as the athlete declared it; it does not bound the programme (DEC-PROGRAMME-01). Resetting means a new profile row, never an edit (DEC-RAMP-01/02) |
| volume_budget_enabled | master switch for the weekly volume budget; 0 default. With it off the main-lift policy is ignored. With it on, the budget trims/tops up accessories and the main-lift policy controls main-lift treatment (DEC-VOLUME-06/08) |
| main_lift_policy | `preserve` (default) leaves main lifts at template sets; `reduce` trims a filled group's main lift to `main_lift_floor`; `drop` removes it and relabels the session as `volume_fill_<original>`/`technique` (9c) |

### 11.1a `settings_profile` / `prescription_profile` — step 4

| table | contents |
|---|---|
| `settings_profile` | append-only profile versions: `profile_id`, `effective_from`, `overrides_json` (complete map), `reason` (guarded changes), `created_at`; the latest effective row wins |
| `prescription_profile` | one resolved snapshot per prescription: `prescription_id`, `profile_id`, `settings_json` (registry + budget), `config_hash`, `created_at` |

Profile precedence is profile > config > registry default. Guarded-safety keys are rejected
until the step-5 confirmation flow. The snapshot freezes what a prescription actually used;
existing prescriptions without a row are not rewritten.

### 11.2 `athlete_constraint` — injuries, contraindications, mobility limits

Stored as `athlete_constraint`: `constraint` is a reserved SQL keyword (`DEC-STATE-01`).

| column | notes |
|---|---|
| constraint_id PK | |
| kind | `injury` \| `contraindication` \| `mobility` \| `asymmetry` |
| region | `low_back` \| `mid_back` \| `shoulder` \| `knee` \| `hip` \| `ankle` \| … |
| severity | `hard_exclude` \| `caution` \| `monitor` |
| forbidden_patterns | JSON, e.g. `["loaded_spinal_flexion"]` |
| forbidden_exercises | JSON list of exercise ids |
| rom_limit | nullable, e.g. depth constraint |
| since / settled_on | dates; drives the "has it settled in 24-48h" logic |
| evidence | free text from the user, kept verbatim |
| source | `user` \| `clinician` |

`severity: hard_exclude` is evaluated by the policy engine with **veto** severity and is
never overridable by an agent.

### 11.3 `exercise_suitability` — living per-exercise rating

| column | notes |
|---|---|
| exercise_id PK-part | |
| rated_on | last time the user revised it |
| can_do | 0/1 — physically possible |
| will_do | 0/1 — preference; the system may propose around a 0 but must not silently drop it |
| feels_bad | 0/1 — subjective, distinct from contraindicated |
| note | free text |
| source | `user` \| `observed` |

Deliberate distinction: `feels_bad` is a preference the prescription may work around;
`constraint.severity = hard_exclude` is a safety rule that vetoes. Conflating them would let
a preference masquerade as a medical restriction, or the reverse.

### 11.4 `metric_definition` — declared measurement direction

`metric_definition` stores the metadata needed to interpret a periodic measurement:

| column | notes |
|---|---|
| metric_key PK | e.g. `vo2max`, `grip_kg` |
| label | human name |
| scale_min / scale_max | bounds |
| higher_is_better | **0/1 — mandatory.** The documented trap (stress 5 = good) is exactly this field |
| aggregation | `mean` \| `max` \| `best_of_3` \| `last` |
| unit | `ms`, `bpm`, `kg`, `score`, `1-5` |
| source | device / app |
| active_from | |

It is consumed by the periodic **measurement** path (`features/measurements.py`,
`DEC-MEASURE-01`): a measurement whose key has no row, or whose direction changes, is
refused rather than reinterpreted.

**It is not a live readiness-composite driver.** The current readiness score uses hardcoded
core fields plus weights/slopes from `config/readiness.v1.yaml`; `composite.enabled` is false
and `readiness_day.composite` stays null. Adding a new readiness metric therefore still needs
code/config work. The table has no weight/role, baseline or slope columns.

A future dynamic composite would need at least:

1. a declared weight/role per metric;
2. baseline and slope handling for device-derived fields;
3. a missing-data rule that distinguishes absent from zero;
4. a shadow mode before any load effect.

A row alone would still not be sufficient.

### 11.6 `e1rm_override` — a manual estimate that outranks the computed one

| column | notes |
|---|---|
| override_id PK | |
| exercise_id | canonical id |
| e1rm_kg | must be positive |
| effective_from / expires_on | an override may be temporary; NULL expiry means "until replaced" |
| reason | why it exists — a tested single, a post-layoff start |
| source | `user` \| `measured` \| `clinician` |
| created_at | set by the store |

Append-only: a correction is a new row, and the latest row whose window contains the
prescription date wins. A prescription cites the row as `e1rm_override:<id>`, so the number is
auditable even after the override is replaced.

### 11.5 `symptom_log` — the manual input the constitution needs

| column | notes |
|---|---|
| logged_on | |
| timing | `pre_session` \| `post_session` \| `next_morning` |
| region | `low_back` \| `biceps` \| `knee` \| … — one reading per region; the configured regions live in `config/injuries.v1.yaml` |
| level | 0–3 agreed scale (see INFO-REQUESTS §6) |
| settled_within_48h | nullable boolean |
| note | |

v0.1 recorded **one pre-session number for the whole back** (`DEC-SYMPTOM-01`). Since
2026-10-19 the same 0-3 scale is recorded **per region** (`DEC-SYMPTOM-03`): `low_back`,
`biceps`, `knee`, and any region added to the injuries config. The column already existed, so
no migration is needed — but the region is now load-bearing, not decorative. Every back rule
reads `low_back` only, so a knee reading cannot trigger `MOD-BACK-001` or reset the back
signal. Multiple entries per day are allowed and the latest wins (migration 0005), so a
correction is an insert. A reading is a **flare** at level >= 2, or at level 1 that did not
settle within 48 hours (`DEC-SYMPTOM-02`); a level-1 reading with no recorded settlement
counts as not settled (`DEC-SYMPTOM-04`). No reading is `unknown`, never "no flare".

The per-region signal built from this table is documented in
[`INJURY-SIGNAL.md`](INJURY-SIGNAL.md); how to log an episode, and what to record when it
settles, is in [`SYMPTOM-LOGGING.md`](SYMPTOM-LOGGING.md). Which exercises load a region is
config, not schema.

Until this table has rows, MOD-BACK-001 and the PRG-EREC-001 stability gate return
`unknown` — visibly, in the run report.

---

## 15. `exercise_remap_log` — one-off variant identity rewrite

Migration `0014` canonicalised synthetic `pattern:*` identities in `clean_set` to named
variant entities. `clean_set` is normally append-only; the migration temporarily drops its
update trigger, records every change here, then recreates the trigger. Raw rows are untouched.

| column | notes |
|---|---|
| raw_id | source raw row |
| old_exercise_id | previous synthetic or canonical id |
| new_exercise_id | canonical variant id |
| reason | migration reason |
| created_at | |

Exceptions: `Competition Deadlift` keeps date-scoped sumo/trap-bar resolution; `Hyperextensions`
keeps its own id and remains `history_equivalent_of: back_extension`. Migration `0015` later
split `close_grip_pulldown` from `lat_pulldown` using the same audit table.

---

## 16. `workout_session`, `workout_set`, `workout_event` — live workout mode

Migration `0017_workout` adds the live workout lifecycle. A workout is operational state: the
prescription and the sets are immutable, while the workout status and end fields are updated
until completion.

`workout_session`:

| column | notes |
|---|---|
| workout_id | UUID |
| prescription_id | nullable link; the snapshot is `plan_json` because the displayed prescription is frozen at start |
| for_date / session_type | copied from the plan |
| status | `in_progress` \| `completed` \| `abandoned` |
| plan_json | frozen prescription payload; later regeneration cannot rewrite it |
| plan_modified_json | latest in-workout plan after swaps/adds/removes/set edits; null until changed |
| readiness_json | validated readiness fields as supplied; a score-ready snapshot or an explicitly acknowledged partial snapshot |
| started_at / ended_at | ISO timestamps |
| duration_measured_s / duration_min / duration_source | measured timer and optional manual override |
| session_rpe / session_rpe_recorded | required unless explicitly not recorded |
| notes | |
| critique_id | deterministic rubric persisted at End workout |
| reviewed_at | set when human review marks are saved |

`workout_set` is append-only. A removed set is an event, not a DELETE:

| column | notes |
|---|---|
| set_id | autoincrement |
| workout_id | parent |
| exercise_id / set_index | one set per exercise per index |
| load_kg / reps / rir / velocity | actual values |
| source | `manual` \| `import` \| `device` |
| prescription_item_index | index into the frozen plan, when matched |

`workout_event` records `start`, `add_set`, `update_set`, `remove_set`, `restore_set`, `end`,
`abandon`, `reviewed`, `import_applied` and `import_undone` with an optional `target_set_id`;
it is append-only. Actual-set corrections and imports replay these events rather than mutating
`workout_set`.

Optional per-rep velocity detail has its own append-only tables:

- `workout_rep_event` — per-set snapshot while the workout is in progress (`reps_json`, source,
batch); a correction is a new event, not an update;
- `clean_rep` — one row per rep after materialisation, linked to `clean_set.set_id`; the set mean
remains `clean_set.velocity_mps`.

On completion, `workout.py` materialises the workout into the normal pipeline once:

- a `session` row with `session_id = workout_id`, `source = 'workout'`, `prescription_id`,
  `workout_id`, measured duration and sRPE;
- one `raw_row` + `clean_set` row per actual set, preserving `prescription_item_index`;
- optional `session_feedback`.

This keeps e1RM, volume and review on one actual-session source of truth. In-workout CSV
import writes `workout_set` rows (or append-only `update_set` events when replacing a set);
RPE is converted to RIR at import, with RIR 6 marking a warm-up. A second optional per-rep CSV
can attach rep velocities by exercise + set; it never creates a set. Date-less backfill is not
supported.

---

## 17. Deleting or voiding a session

**There is no hard-delete path.** `clean_set`, prescriptions, critiques, rubric marks and
calibrations are append-only; deleting a session would retroactively change e1RM, volume,
review and future prescriptions. The store's delete triggers enforce this for `clean_set`.

What exists:

| Situation | Action |
|---|---|
| Workout still `in_progress` | **Abandon** it; it is not materialised as a completed session |
| Wrong set during an active workout | **Remove** it, or edit load/reps/RIR/velocity |
| Completed workout | Correct it in **History**; append-only supersession, no delete or overwrite |
| Imported session | Correct it in **History**; no delete action |

**Recommended future operation: void, not delete.** A completed session should keep its rows and
gain an append-only `session_void` event with a reason; analytics/review/volume/e1RM would filter
it out, and an unvoid event would restore it. This is **not implemented** and is not scheduled.
Do not disable the append-only triggers to “clean up” history.


### 17.1 Corrections for completed sessions

Migration `0030_session_history` adds `clean_set.voided`, `session.needs_review`,
`session.edited_at` and the append-only `session_edit` audit table.

A correction does **not** update `clean_set`:

- an edited set inserts a new `clean_set` row with `supersedes_id = old.set_id`;
- a removed set inserts a tombstone (`voided = 1`) that supersedes the old row;
- readers use the leaf row: `voided = 0` and no child references it;
- `session` totals and `needs_review` are rebuilt;
- a new critique supersedes the old one;
- old human marks remain but are excluded from calibration while `needs_review = 1`;
- saving marks clears `needs_review`.

Date and session type are read-only in this first version. The correction stores before/after JSON
in `session_edit`, so the edit itself is auditable. Form values are validated before any write;
the set/form/feedback/audit writes run in one transaction, and the derived critique rebuild uses
its own savepoint so a rebuild failure cannot partially commit or roll back the correction.

Whole-session **void/unvoid** is separate: `session.voided` is the operational flag and
`session_void` is the append-only event log. A void keeps every row, excludes the session from
set/session reads and calibration, and can be reversed. It is not a delete.

`vbt_override` stores append-only set-mean and per-rep velocities. A NULL `rep_index` is the set
mean; a numbered row is that rep. Overrides can fill a missing value or supersede a device value;
they never mutate `clean_set` or `clean_rep`.

## 18. `declared_break` — holiday, deload and test weeks

| column | notes |
|---|---|
| break_id | |
| starts_on / ends_on | inclusive ISO dates; `ends_on >= starts_on` is a CHECK |
| reason | `holiday` | `deload` | `test` | `other` |
| note | free text |
| cancels_break_id | set on the row that **cancels** another break; NULL on a real break |
| recorded_at | |

Append-only (no-update and no-delete triggers, migration 0035). A break row is a real interval
unless another row names it in `cancels_break_id`; rows that only cancel are audit records, not
intervals. Reads: the trained-week index subtracts every week that contains a break day, so the
DUP cycle and the erector ramp freeze for that week (`DEC-CONTINUITY-04`, `docs/CONTINUITY.md`).
Nothing else reads this table — no load, RIR or set depends on it.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
