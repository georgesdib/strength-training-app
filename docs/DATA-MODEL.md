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

Nothing is ever deleted. `(null)` dates live here permanently.

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
| form_score | INTEGER | null; direction unconfirmed (Q5) |
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
| day_guess | TEXT | `A` \| `B` \| `C` \| `unknown` + `day_confidence` |
| day_reason | TEXT | why the day was assigned or left unknown, so "do not force a bucket" is auditable |
| tonnage_kg | REAL | sum of non-null `tonnage_kg` |
| duration_min | REAL | **null by default** — no timestamps exist |
| duration_basis | TEXT | `measured` \| `unavailable` |
| flags | TEXT | `POSSIBLE_DOUBLE_SESSION`, `NO_MAIN_LIFT`, … |

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
| hrv_ms, rhr_bpm, bodyweight_kg, fat_pct | null when 0 sentinel |
| composite | derived, 0–1, with `composite_basis` listing which inputs existed |
| merge_note | JSON: which duplicate rows were considered and why one won |

Duplicate-readiness merge rule is DQ-RD-01; implemented as most-complete-row, ties to the
latest (`DEC-READINESS-01`, `ingest/readiness.py`). `composite` stays null until the metric
directions in Q6 part 2 are declared.

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
| session_day | A/B/C |
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
| substitution_for | nullable |

## 9. `critique` / `rubric_score`

`critique` stores the narrative plus `facts_hash`; `rubric_score` stores one row per
rubric item (`RIR_ADHERENCE` …) with `score`, `weight`, `evidence_refs`, `rule_ids`, and
`measurable` (0/1). Metrics that the data cannot support — session duration, within-set
velocity loss — are stored with `measurable = 0` rather than a guessed score.

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
| primary_goal | `strength` \| `hypertrophy` \| `body_comp` \| `pain_free` \| `competition` |
| goal_rank | JSON ordered list; a conflict between erector ramp and squat volume is resolved by this |
| focus_lifts | JSON list of exercise ids that matter most |
| competition_date | nullable |
| sessions_per_week_target | the *intended* frequency, so the rubric can separate intent from execution |
| max_session_minutes | the real ceiling, used once duration becomes measurable |

### 11.2 `constraint` — injuries, contraindications, mobility limits

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

### 11.4 `metric_definition` — the normalisation layer for new readiness inputs

Every readiness metric, existing or future (Bevel score, HRV, RHR, grip strength L/R), is
declared here before use:

| column | notes |
|---|---|
| metric_key PK | e.g. `bevel_readiness`, `grip_left_kg` |
| label | human name |
| scale_min / scale_max | bounds |
| higher_is_better | **0/1 — mandatory.** The documented trap (stress 5 = good) is exactly this field |
| aggregation | `mean` \| `max` \| `best_of_3` \| `last` |
| unit | `ms`, `bpm`, `kg`, `score`, `1-5` |
| source | device / app |
| active_from | |

Adding a new readiness metric therefore requires **no code change and no prompt change**:
insert a row, and the composite picks it up. A metric with no row is rejected rather than
assumed to be higher-is-better.

### 11.5 `symptom_log` — the manual input the constitution needs

| column | notes |
|---|---|
| logged_on | |
| timing | `pre_session` \| `post_session` \| `next_morning` |
| region | `low_back` \| `mid_back` \| `si_joint` \| … |
| level | 0–3 agreed scale (see INFO-REQUESTS §6) |
| settled_within_48h | nullable boolean |
| note | |

Until this table has rows, MOD-BACK-001 and the PRG-EREC-001 stability gate return
`unknown` — visibly, in the run report.
