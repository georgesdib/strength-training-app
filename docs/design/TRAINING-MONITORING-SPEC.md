# Training monitoring design specification

**Strength performance, external dose, internal load, relative strength and specialised exposure**

| Item | Value |
|---|---|
| Status | **Implemented for Phases 0–4; Phase 5A prospective validation active. Authoritative for metric definitions.** |
| Repository | strength-training-app |
| Branch audited | development |
| Commit audited | aeba4ff (implementation closure baseline) |
| Commit date | 2026-10-30 |
| Document date | 2026-10-30 |
| Revision | 4 — implementation status reconciled |
| Revision basis commit | 0fa4711 (baseline document); implementation closed from aeba4ff |
| Scope | Metrics and methodology; implementation plan closed after Phase 0–4; Phase 5A active, Phase 5B gated. |
| Intended next reader | Phase 5A reviewer and future evidence-driven implementation. |
| Location note | This file lives in docs/design/ rather than directly in docs/ because the repository's documentation-map test requires every top-level docs/*.md to be listed in AGENTS.md, and this task forbids editing AGENTS.md. Adoption should add it to that map. |

> **Non-negotiable framing.** The system described here is a set of **separate descriptive measurements**. It is not a universal workout score, not a fatigue model, not an injury predictor and not a prescription controller. Where the evidence is weak, this document says so and withholds the feature.

---

## 1. Executive summary

### 1.1 What was audited

The audit covered the branch and commit above, the set-level schema and ingest path, the e1RM and RIR domain code, the store read/write layer, the prescription engine's e1RM selector, the workout lifecycle and its end screen, the critique rubric, the volume ledger, the hard-set exposure ratio, high-intensity exposure, exercise demands, spinal cost, session feedback, the web API and UI, the migrations, and the test suite. The detailed findings are in §2.

### 1.2 The central finding

The repository already contains most of the **raw material** for the proposed system, and several computations are better than the proposal assumes. It does **not** contain a monitoring layer that turns those materials into a coherent, explicitly labelled set of session-level and longitudinal measurements. The gap is therefore mostly **definitions, composition, eligibility and presentation**, not new data capture.

Three existing facts change the proposal:

1. **"Pre-workout e1RM" is overloaded.** The app already has a prescription e1RM selector (median by default, 28-day robust window, 84-day outer window, age decay, measured-test calibration, overrides). That value is the **load base** used to solve the prescribed load. It is not the same quantity as "recent demonstrated performance". Using one number for both relative intensity and the recent comparison would mix a robust median load base with a session-level performance reference. This specification defines the load base, the recent reference, the best recent single session and the all-time best as separate quantities.
2. **A within-session e1RM difference is not a strength gain, and the 4.2% figure is not a threshold for this application.** Grgic 2020 reports test–retest reliability for direct 1RM tests. This app estimates 1RM from load, repetitions and self-reported RIR, so formula error and RIR error add uncertainty. The 4.2% figure is retained only as a literature reference for actual 1RM test–retest variability; it is not a validated measurement-error or meaningful-change threshold for estimated 1RM. The UI shows the absolute and percentage difference descriptively and does not classify it as clear, meaningful or within typical variation.
3. **The existing session-RPE capture is immediate, not the validated 30-minute protocol.** Sweet 2004 and Day 2004 collected session RPE about 30 minutes after exercise. The app asks at the end of the workout. That is a defensible friction trade-off, but it must be labelled as immediate sRPE, and the app must not claim the 30-minute protocol until it collects a delayed value.

### 1.3 What is recommended

- **Keep the domains separate**: external dose, internal load, estimated strength, relative strength, power exposure, axial/spinal exposure, subjective productivity, longitudinal response. Present them together; never add them into one score.
- **Reuse** the existing clean_set, session, workout tables, e1rm_override, session_feedback, high_intensity_exposure, taxonomy, demand catalogue, spinal-cost registry, volume ledger, exposure ratio and rubric. Do not reimplement any of them.
- **Add one shared load-base e1RM selector** for the prescription engine and calibration report, and a **separate raw session-best estimator** for monitoring. Do not use the calibrated/age-decayed load base as a performance observation. Keep the performance series raw: no age decay and no calibration factor. Today there are at least four independent "latest/best e1RM" computations with different windows, aggregations and eligibility.
- **Add a read-only monitoring module** that composes session summaries and trend series on demand. Do not persist derived metrics.
- **Add one nullable productivity column** to session_feedback if Domain G is approved. That is the only schema change this specification can justify. Everything else fits existing fields, the frozen plan JSON snapshot, or a new configuration file.
- **Withhold** velocity-loss claims, injury prediction, universal ratios, automatic prescription changes, complex forecasting and any composite 0–100 score.

### 1.4 The one-sentence verdict on each proposed domain

| Domain | Verdict |
|---|---|
| A. External dose | **Build it**, from completed clean_set rows only. Tonnage stays exercise-specific. |
| B. Internal load | **Build it** as sRPE × duration in AU, with explicit missingness and timing labels. |
| C. Estimated strength | **Build it** from raw formula-derived observations, split the load base from the recent-reference comparison, and do not call the difference adaptation. |
| D. Relative strength | **Build it as a descriptive, explicitly configured, date-stamped ratio**, with no targets and no weakness diagnosis. |
| E. Power exposure | **Build the count and a descriptive mean velocity change across sets**; do not call it retention or a quality score, and do not claim within-set loss from mean velocity. |
| F. Axial/spinal exposure | **Present the existing ordinal exposure**; do not create a new spinal-load number. |
| G. Productivity | **Add one optional item**; keep it subjective and out of every calculation. |

### 1.5 What would make this design wrong

- If the athlete's measured tests show that the Epley+RIR estimator has large, rep-range-dependent bias, the best-set comparison should be replaced by a test-anchored estimate.
- If prospective data show that session load AU or productivity predicts subsequent performance better than a simple baseline, that is a reason to **study** them, not to automate them.
- If the exercise taxonomy gains a validated equivalence system for variants, Domain D could use it. Until then, explicit configuration is the only defensible route.

---

## 2. Repository audit and current-state architecture

### 2.1 Layering and data flow

The repository follows the documented direction utils ← domain ← ingest / store ← features ← rules / prescribe / critique ← agents / eval, with workout.py and history.py as operational services over the store. The web server only serialises and routes; deterministic computation lives in the core. This is the correct place for a monitoring layer: features/, read-only, no new controller.

The relevant flow for this design is:

    raw export / live workout
            ↓
    raw_row  →  clean_set  →  session
                     ↓
            features.derived.enrich
            (e1rm_kg, e1rm_method, e1rm_quality, velocity_present, in_rir_window)
                     ↓
       prescription (reads history before the date)
       critique (reads a stored session)
       volume / exposure / demands / spinal / high-intensity
       monitoring (new; reads completed sessions and their plan snapshot)

### 2.2 Existing functionality that must be reused

| Area | Existing implementation | What it already does | Reuse decision |
|---|---|---|---|
| Set identity and load | ingest/clean.py, domain/load.py | Canonical exercise id, load basis, external/total/progression load, bodyweight resolution, flags | Reuse unchanged. Do not recompute load basis in monitoring. |
| RIR semantics | domain/rir.py | RIR 6 = warm-up (DEC-RIR-01), RIR 0–5 effort, allowed window 1–4, target 2–3 (DEC-RIR-02) | Reuse the classifier. Do not add a second RIR rule. |
| e1RM formula | domain/e1rm.py | Epley and Epley+RIR, rep caps, method and quality tags | Reuse the formula. Add a **shared selector** around it. |
| Per-set enrichment | features/derived.py | e1RM applicability, e1RM, velocity presence, RIR window, power exclusion | Reuse, then extend eligibility for monitoring display. |
| Prescription e1RM | prescribe/engine.py::_latest_e1rm | Override first; best_usable / median / most_recent; 84-day window; 28-day robust median; age decay; calibration factor | Extract into a shared feature. Preserve behaviour exactly for prescriptions. |
| Calibration | features/e1rm_calibration.py | Measured-test ratio, bootstrap CI, bounded correction, per-lift coverage | Reuse for confidence and correction; do not create a second calibration. |
| Decay | features/e1rm_decay.py | Bounded 1%/week after 21 days, max 10% | Reuse. Show the factor. |
| Session feedback | features/session_feedback.py, session_feedback table | Optional sRPE (1–10), duration (minutes), note; append-only; blank allowed | Reuse. Add per-field merge and timing labels. |
| Live workout | workout.py, workout_session / workout_set / workout_event | Plan snapshot, in-workout edits, actual sets, end, materialisation, comparison | Reuse. Add monitoring to the summary, not to the active workout. |
| Completion comparison | workout.py::_comparison | Actual vs frozen plan, status, extra sets | Reuse; do not reimplement. |
| Volume ledger | features/volume.py | Working/hard sets by pattern, MEV/MAV/MRV landmarks, effective accounting | Reuse for weekly context. Do not duplicate landmarks. |
| Hard-set exposure | features/exposure.py | 7/28-day hard-set ratio, abstention, coverage, groups | Reuse the hard-set definition. Do not build a second ratio. |
| High-intensity exposure | features/high_intensity_exposure.py | Tests, max attempts, competition, unplanned; guard windows | Reuse for the "special exposure" section. Never count as volume. |
| Demand catalogue | features/demands.py, config/exercises/demands.v1.yaml | Qualitative axial/trunk/technical/local dimensions with provenance | Reuse for axial/spinal context. Never aggregate dimensions. |
| Spinal cost | rules/registry.py (spinal_exposures, weekly_spinal_costs), features/heavy_spinal.py | Ordinal cost per (session, exercise), bounded set/intensity policy factors, weekly cap | Reuse. The summary must call the registry, not recompute. |
| Critique | critique/facts.py, critique/rubric.py | Adherence/execution rubric with a weighted composite | Keep separate. Never present the rubric composite as a workout load or stimulus. |
| Progress dashboard | features/progress.py | sRPE coverage, attendance, volume, 84-day performance ratio, back symptom | Reuse as context; do not treat its ratio as an e1RM series. |
| Fatigue-fitness | features/fatigue_fitness.py | Shadow per-lift model; rejected retrospectively | Do not connect. Do not assume new metrics improve it. |

### 2.3 Set-level data audit

| Field | Meaning in the schema | Sufficient for the proposal? | Ambiguity / gap |
|---|---|---|---|
| set_id, session_id, occurred_on | Identity and date | Yes | Imported sessions have a date, not a timestamp; two sessions on one date cannot be ordered. Live workouts use a UUID and a started_at. |
| exercise_id, raw_exercise | Canonical and raw identity | Yes | Equivalence is explicit only for documented relations; trap bar / sumo / conventional are separate. |
| load_kg | Normalised load | Partly | Three meanings (external, total bodyweight, added load) are disambiguated by load_basis. |
| load_basis | external / bodyweight_total / added / unknown | Yes | For added, the read helper queries.clean_sets sets total_load_kg = load_kg, losing the bodyweight contribution. This is latent because current bodyweight-typed exercises are e1rm_applicable: false, but it must be fixed before any bodyweight e1RM or relative-intensity feature. |
| external_load_kg | Load actually added | Yes | 0 is valid for pure bodyweight. |
| reps, reps_unit | Repetitions or seconds | Yes | Timed sets are not repetitions; do not sum them into rep totals. |
| rir, rir_source | Proximity-to-failure report | Partly | RIR is self-reported with substantial error (Zourdos 2021; Refalo 2024). RIR 4 is almost absent in the local history and RIR 5 is common, so the configured hard-set threshold ≤4 behaves as ≤3 in practice. |
| velocity_mps, velocity_present | Mean velocity per set | Partly | A mean has no within-set variance. 0 is a device-unused sentinel. |
| power_w | Power | **No** | The column exists but is never populated by ingest or workout materialisation. The raw Avg_power column is not mapped. Do not use it. |
| rom_mm, tut_s | Range and time under tension | Partly | Present in schema; not used by the proposal. Do not infer ROM changes from it without a standard measurement. |
| form_score | Per-set form | **Retired** | Migration 0034 cleared it; the source remains in raw_row.payload. Use session_form_rating instead. |
| tonnage_kg | External load × reps | Yes, per exercise | Null for bodyweight/time-based. Do not sum across unrelated exercises and call it a universal workload. |
| is_working_set | Warm-up exclusion | Yes | Derived from RIR 6. A missing RIR is still a working set (assisting accessories). |
| flags | Data-quality flags | Yes | JSON list; REPS_TYPO, LOAD_BASIS_UNKNOWN, SECONDS_NOT_REPS, NO_RIR, SUSPECT_RIR, WARMUP. |
| source_row | Traceability to raw | Yes | Rejoin through raw_row. |
| prescription_item_index | Link to the plan item | Yes | Set on materialisation; useful for completion and substitution. |

**Conclusion:** the set-level schema is sufficient for Domains A, B (with feedback), C, E (counts only), F and G (with one new column). It is not sufficient for within-set velocity loss, jump height, contact time, or a measured spinal load. Those must be explicitly withheld or collected prospectively. Weighted bodyweight movements (for example a weighted pull-up) cannot have an e1RM under the current taxonomy because pull_up carries e1rm_applicable: false; enabling that is a separate identity/product decision, not part of this proposal.

### 2.4 Session feedback audit

Current implementation:

- session_feedback stores srpe (1–10), duration_min (>0, ≤600), note, recorded_at; append-only; at least one field must be non-null.
- session also carries duration_min, duration_basis (measured / unavailable), session_rpe, session_rpe_recorded.
- workout_session also carries duration_min, duration_source (measured / manual), session_rpe, session_rpe_recorded, notes.
- workout.end requires an sRPE or an explicit "not recorded"; duration defaults to the measured clock, with manual override.
- The end screen shows workout_session values, not a merged session_feedback read.

Audit findings:

1. **Three copies of the same facts.** session_feedback, session and workout_session can disagree. A canonical read policy is required.
2. **Row-wise append-only feedback loses fields.** A correction that supplies only sRPE creates a latest row with a null duration. Reading "the latest row" then makes session load unknown even though an earlier row had the duration. The read must merge **per field**, taking the latest non-null value of each.
3. **Manual duration is mislabelled as measured.** workout._materialise writes duration_basis = 'measured' unconditionally, and history.py does the same on edit. The session schema has no manual value. This affects the rubric's SESSION_DURATION item and attendance. The monitoring layer must label duration_source from workout_session when available and must not silently treat manual as objective.
4. **Immediate sRPE is not the 30-minute protocol.** The UI asks at the end. Label it.
5. **No productivity field.** This is the only genuine capture gap in Domain G.
6. **No interruption field.** Only duration and notes. Do not infer an interruption.

### 2.5 Existing systems that must remain conceptually separate

| System | What it measures | What it must not become |
|---|---|---|
| Programme critique (critique/rubric.py) | Adherence and execution against the programme, with a weighted composite over measurable items | A workout workload, physiological stimulus, fatigue, strength-development or recovery score. The composite is an adherence index, not a load. |
| Weekly volume ledger (features/volume.py) | Working/hard sets by pattern against configurable MEV/MAV/MRV landmarks | A measured personal threshold. The landmarks are assumptions. Do not duplicate the weekly computation in the session summary. |
| Hard-set exposure (features/exposure.py) | A 7/28-day ACWR-shaped descriptive ratio, with abstention | An injury-risk model. It is contested and must remain descriptive. |
| High-intensity exposure (features/high_intensity_exposure.py) | Tests, max attempts, competition and unplanned near-max work, separate from volume | Ordinary hypertrophy volume. Do not count a test as a working set for dose. |
| Exercise demands (features/demands.py) | Qualitative, dimension-specific claims with provenance | A spinal-load measurement or an aggregate score. unknown is not low. |
| Spinal cost (rules/registry.py) | Ordinal exposure with bounded policy factors against a weekly cap | Lumbar compression/shear in newtons, or an injury probability. |
| Fitness-fatigue (features/fatigue_fitness.py) | A shadow diagnostic that was rejected retrospectively | A load controller, or a reason to adopt new metrics. |

### 2.6 Existing e1RM computations: four implementations, four answers

This is the most important architectural finding for Domain C.

| Location | Window | Aggregation | Decay | Calibration | Override | Exercise applicability |
|---|---|---|---|---|---|---|
| prescribe/engine.py::_latest_e1rm | 84 days, robust 28 days | median (default), best_usable, most_recent | Yes, per set | Yes | Yes, wins | Uses e1rm_kg, so applicability is respected |
| features/e1rm_calibration.py::build | 84 days | max per lift | Yes, applied once to the max | Reports correction | Reports | Uses e1rm_kg |
| features/baseline.py::lift_baselines | 84 days for window, all-time for best | max | No | No | No | Uses e1rm_kg |
| features/progress.py::_session_lift_e1rms | Per session | max per exercise | No | No | No | **Does not check e1rm_applicable**; computes for RDL, back extension, etc. |
| features/fatigue_fitness.py | Per session | max per canonical lift | No | No | No | Uses e1rm_kg |

Consequences:

- A "recent reference" or performance series implemented with any of these would give a different number.
- e1rm_calibration reports latest_e1rm as the maximum over the window but latest_on as the latest date in the group, so the displayed date can belong to a different set than the value. That is a labelling defect, not a calculation-defining one, but it matters for source transparency.
- progress already violates the taxonomy's e1rm_applicable: false decision.
- The new monitoring layer must **not** add a fifth load-base computation. It must call the shared selector for relative intensity and a separate raw session-best estimator for performance observations.

### 2.7 Existing plan snapshot: a free extension point

workout_session.plan_json freezes the prescription shown at start. It is JSON, so new fields can be added **without a migration**. Today _item_dict and PrescriptionItem.as_rows expose e1rm_source_sets but not the e1RM value, the reference, or the planned intensity. The monitoring layer needs the load base for relative intensity and the raw session best for performance. The cleanest fix is to add e1rm_kg, e1rm_ref, e1rm_quality, e1rm_age_days and intensity to the plan item dict at generation time; the raw performance series is computed separately from clean_set. Old snapshots without these fields can be recomputed with a **strict pre-session cutoff** and flagged reconstructed.

### 2.8 Test and fixture landscape

The suite already has focused tests for e1RM, RIR, load, exposure, spinal cap, high-intensity exposure, session feedback, workout lifecycle, history, progress, critique and the web API. The monitoring work should extend those patterns:

- synthetic make_training / make_readiness fixtures (never data/raw);
- pure-function tests for definitions;
- API contract tests for the summary and trend endpoints;
- no golden prescription changes unless a shared e1RM refactor accidentally changes behaviour.

### 2.9 Data sufficiency (qualitative, from the local store)

The local store contains several years of training history and dense main-lift records, but the monitoring layer must be designed for the **actual** coverage, not an ideal one:

- **Main lifts** have dense history; **variation/accessory** lifts are sparser and more irregular.
- **RIR** is present on essentially all imported working sets, but RIR 4 is almost absent and RIR 5 is common. Live-workout RIR is optional.
- **Session feedback** covers only a subset of sessions; older sessions were intentionally left blank. Session-load trends must show coverage, not assume completeness.
- **Measured e1RM tests** may be absent or few; do not assume they exist. Phase 0 establishes the exact count and linkability. The calibration report may have no points, so there may be no athlete-specific criterion error estimate yet. The 4.2% figure from Grgic 2020 is a literature reference for direct 1RM test–retest variability, not a personal measurement-error estimate for this application's e1RM.
- **Per-rep velocity** is sparse. Mean velocity exists on some sets. Power data is essentially box jumps; there is no jump height or contact time.
- **High-intensity exposures** may be absent. A zero is a valid zero only when the recording path was available.
- **Trap-bar history** starts after the documented switch, so trap-bar/sumo ratios are not contemporaneous over most of the record.

This is why Phase 2 must show coverage and "unavailable" states prominently, and why Phase 4 is exploratory.

### 2.10 Extension versus genuine gap

| Category | Items |
|---|---|
| Exists and is reused unchanged | clean_set and load resolution; RIR classes; Epley/Epley+RIR; measured-test calibration; age decay; workout plan snapshot and completion comparison; volume ledger; hard-set exposure; high-intensity exposure; demand catalogue; spinal registry; session_form_rating; progress dashboard; rubric |
| Exists but requires a bounded extension | e1RM selector (extract a shared function with a session cutoff); session feedback (per-field merge and timing label); plan JSON (add e1RM value/reference/quality/intensity at generation); bodyweight total read for added-load rows; power classification (config, not names) |
| Genuinely missing | session-level recent-reference and descriptive difference; relative intensity; exercise-specific tonnage report; session hard-set/near-failure summary; session load AU; configured relative-strength ratios; longitudinal e1RM series and rolling median; comparable-session comparison; power mean velocity change across sets; productivity field; structured power quality-stop event |
| Data structures sufficient? | Yes for Domains A, B, C, E (counts and mean velocity change), F, and D (via config). No for G without one nullable productivity column. No for within-set velocity loss or measured spinal load, which are explicitly excluded. |

The free-text session_feedback.note is **not** a substitute for a productivity field: it is unvalidated free text, cannot be queried as an ordinal scale, and would conflate a subjective judgement with a comment. If Domain G is approved, the one nullable integer column is the minimum sufficient change.

**Recommendation on sRPE timing.** Keep the single end-of-workout prompt. It is the lowest-friction option and preserves completion rates. Label the value "immediate sRPE" and do not claim the 30-minute protocol. If the athlete wants the validated timing, add an optional "Record 30-minute sRPE" action on the review screen and store a timing field; do not make the delayed value mandatory. Until then, any session-load trend mixes immediate values and must say so.

---

## 3. Proposed monitoring architecture

### 3.1 Principles

1. **Separate constructs, shared data.** One clean_set frame feeds every domain. The domains are composed for display, never arithmetically combined.
2. **Completed work only.** Prescribed, modified and actual are all shown; only actual counts toward dose.
3. **No new controller.** Nothing here changes a load, set, RIR, deload or exercise selection.
4. **No hidden defaults.** Every eligibility rule, window, band and threshold is named, configurable and marked as evidence or assumption.
5. **Unknown is a first-class result.** It is rendered as "Unavailable" or "Not recorded", never 0.
6. **Recompute, do not persist.** Derived metrics are computed on read from immutable rows. A cached view is optional, keyed to the database version.
7. **One definition per concept.** If a definition is needed in two places, it lives in domain/ or features/ and is imported.
8. **Transparency over polish.** Every headline number can be opened to its source rows.

### 3.2 Module layout (proposed)

| Module | Responsibility | Layer |
|---|---|---|
| features/e1rm_source.py (new) | Prescription load-base selector: eligibility, window, estimator, decay, calibration, override, cutoff; behaviour unchanged | features |
| features/monitoring.py (new) | Pure definitions: raw session-best estimator, completion, dose, relative intensity, RIR distribution, hard sets, tonnage, session load, power, spinal, productivity | features |
| features/strength_trend.py (new, or part of monitoring) | Per-session e1RM observations, rolling median, series breaks, sparse-data rules | features |
| features/relative_strength.py (new) | Configured ratio pairs, date comparability, trend | features |
| config/monitoring.v1.yaml (new) | Bands, windows, thresholds, flags, display policy | config |
| config/strength-relationships.v1.yaml (new) | Explicit numerator/denominator relationships | config |
| web/server.py | New read-only routes; no computation | web |
| web/static/summary.js (new) or workout.js extension | Rendering only | web |
| cli.py | summary / performance commands calling the same core | CLI |

features/monitoring.py must not import prescribe or web. features/e1rm_source.py may import domain, store.queries and taxonomy utilities, but **not** prescribe. The engine imports the feature; the dependency arrow does not reverse.

### 3.3 The e1RM reference quantities

| Quantity | Purpose | Estimator | Window | Used by |
|---|---|---|---|---|
| load_base_e1rm | Denominator for relative intensity; the load the prescription was solved from | Prescription selector: median by default, fallback best_usable | 84 days outer, 28 days robust | Strictly before the session; override in force | A2 relative intensity; plan-drift check |
| recent_reference_e1rm | Typical recent performance; primary comparator for today's best | Median of the last 3 eligible per-session best **raw** e1RM observations | Each observation within 84 days | Strictly before the session | C1/C3 difference vs recent performance |
| best_recent_e1rm | Best single recent performance; separate reference | Highest eligible per-session best **raw** e1RM | 84 days | Strictly before the session | C1.2 display only; never a typical baseline |
| personal_best_e1rm | All-time best estimate; PR display | Highest eligible per-session best **raw** e1RM | All time | Strictly before the session | C1.3 display only |
| post_best_e1rm | Best demonstrated performance in the session | Highest eligible set-level **raw** e1RM | Current session only | Current session | C2/C3, longitudinal series |
| difference_vs_recent | Descriptive difference between today's best and the recent reference | post_best − recent_reference (both raw) | Current session vs recent reference | Both sides eligible | C3 display only |

All five performance quantities above are **raw formula-derived Epley or Epley+RIR estimates**. Age decay is not applied, and the measured-test calibration factor is not applied, to the performance series. This keeps historical and current observations on one method. Raw estimates may carry systematic bias; method consistency does not make them criterion-valid measurements. The calibration factor and age decay belong to the separate prescription load base described below. A validated calibration factor may be displayed as separate supplementary context for that load base; it is never applied to the performance series.

Why these are separate: a historical maximum is selected from many more sets than today's maximum, so comparing a maximum to a maximum from a different sampling opportunity is not a like-for-like change. The primary comparison is today's best against the **median of the last three eligible per-session bests**, which reduces the influence of one exceptional day and equalises the sampling unit (one session, one best set). A separate best-performance reference is retained for context, but it is never presented as a typical baseline. The load base remains separate again, because it is the robust median the prescription used to solve the load.

### 3.4 Data flow for a completed workout

    workout_session (plan_json snapshot, plan_modified_json, events)
            │
            ├── actual sets → materialised clean_set (same session_id)
            │
            ├── session_feedback (sRPE, duration, note, productivity)
            │
            ├── high_intensity_exposure (linked by set/date)
            │
            └── monitoring.summary(conn, session_id)
                     ├── completion: _comparison(original/modified/actual)
                     ├── strength: e1rm_source before/after
                     ├── dose: clean_set working sets, tonnage, RIR, relative intensity
                     ├── special: power, high-intensity, spinal (registry)
                     ├── feedback: merged sRPE/duration → AU, productivity
                     └── comparison: comparable prior sessions (if any)

**Critical ordering rule:** the summary is computed **after** materialisation, but the recent-reference observations must exclude the current session. The cutoff is by session_id and by date, not by "today". See §5.6.

### 3.5 What is persisted

Nothing new, except session_feedback.productivity if approved. All monitoring values are derived. This avoids a second source of truth and makes corrections (append-only clean_set supersedes) automatically flow through.

If caching is needed, use an in-process cache keyed by (database_path, mtime_ns, size, session_id), as fatigue_fitness.compute_cached already does. Do not write a cache table.

---

## 4. Exact metric definitions and formulas

### 4.1 Status vocabulary

Every metric returns one of these statuses. The UI must render them distinctly.

| Status | Meaning | Example |
|---|---|---|
| observed | A logged fact | 14 completed working sets |
| estimated | A formula result with a method tag | e1RM 156.0 kg (Epley+RIR) |
| unknown | Data that should exist but does not | session RPE not recorded |
| not_applicable | The quantity has no meaning for this exercise/set | e1RM for a plank |
| invalid | Data present but fails validation | 21-rep set for e1RM; negative load |
| unavailable | Data exists but eligibility prevents use | e1RM older than 84 days; ratio dates too far apart |
| zero | A real measured zero | 0 hard sets when all working sets have RIR 5 |

A metric must not collapse unknown, unavailable and zero into one value.

### 4.2 Common rules

- **Completed work** = clean_set rows with voided = 0, session.voided = 0, not superseded, is_working_set = 1.
- **Warm-up** = rir_class == "warmup" (RIR 6, DEC-RIR-01). Excluded from every dose, e1RM, relative-intensity and hard-set metric; counted only as "warm-up sets" for visibility.
- **Test/high-intensity set** = a set linked to a high_intensity_exposure by set_id or by an exact (session_id, exercise_id) match. It remains a working set for completion but is excluded from the ordinary RIR/relative-intensity distribution and shown in "Special exposure". If it cannot be linked, it stays in the ordinary distribution and the summary says "possible test not linked" rather than guessing. A linked test set still counts once in the completed-set and hard-set totals (the exposure row is not added again), but it is shown in Special exposure and kept out of the ordinary RIR/relative-intensity distribution.
- **Timed set** (reps_unit = seconds) is not a repetition and has no tonnage. It counts as a working set and as time, not reps.
- **Bodyweight**:
  - bodyweight_total: load_kg is total mass; use it for e1RM and relative intensity.
  - added: load_kg is the added load; total mass = added + bodyweight for e1RM/relative intensity; progression and tonnage use the added load only (DEC-LOAD-02).
  - unknown: no e1RM, no relative intensity, no tonnage.
  - Bodyweight comes from the merged readiness row on the session date or the nearest within ±7 days; if absent, the total is unknown. Do not guess.
- **Exercise identity**: exact exercise_id for e1RM and ratios. The only documented history equivalence is history_equivalent_of (currently hyperextension → back extension, DEC-BACKEXT-02); use it only where the app already does, and label the merge. Never merge trap bar/sumo/conventional, SSB/competition/high-bar/front, or bench/narrow/pause/DB/machine.
- **No imputation**: never fill a missing RIR, load, duration or RPE from another field. The existing Epley fallback for a missing RIR is a **formula convention**, not an imputation; monitoring must treat it as a separate, lower-quality method and must not headline it.

### 4.3 Metric catalogue

The table below is the normative definition. "Type" uses D = descriptive, I = inferential, P = predictive. No metric in this specification is P.

| # | Metric | Definition / formula | Inputs | Unit | Eligibility | Missing behaviour | Key flags | Comparability | Known limits | Type | UI | May influence programming? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1.1 | Completed working sets | Count of working clean_set rows in the session, excluding warm-ups and superseded rows | clean_set | sets | Valid session; is_working_set | unknown if no set rows; zero only if a session exists with no working sets and the absence is real | WARMUP_EXCLUDED | Same session only | A "set" is a logged row; a drop set or cluster may be one or several rows by logging convention | D | Summary card 1 | No |
| A1.2 | Completed repetitions | Sum of reps over working sets with reps_unit = reps | clean_set | reps | Working sets only | Exclude timed sets; unknown if no rep-bearing sets | TIMED_SETS_EXCLUDED | Same exercise/session | Partial reps are not captured; a failed rep is not a row | D | Card 1 | No |
| A1.3 | Exercise tonnage | Σ(external_load_kg × reps) over working sets of one exercise | clean_set | kg | Loadable, non-time-based, external/added load present | Sum known sets; report coverage; not_applicable if all undefined | TONNAGE_PARTIAL | **Within exercise only**; not across exercises | Ignores bodyweight, ROM, tempo, mechanics | D | Card 3, per exercise | No |
| A1.4 | Session tonnage (optional) | Sum of A1.3 over exercises | clean_set | kg | At least one tonnage-bearing set | unknown if none; partial otherwise | TONNAGE_PARTIAL | Only sessions with high exercise overlap; never a universal workload | Exercise-mix dependent; bodyweight excluded | D | Advanced only | No |
| A1.5 | Hard sets | Count of working sets with 0 ≤ rir ≤ effort_max_rir (config default 4) | clean_set, exposure config | sets | Working sets with known RIR | If any working set has unknown RIR, report known_hard and unknown_rir; do not call the total 0 | RIR_UNKNOWN | Same exercise/session; weekly comparison via exposure | RIR error; RIR 4 nearly unused locally | D | Card 3 | No |
| A1.6 | Near-failure sets | Count of working sets with rir ≤ 2 | clean_set | sets | Known RIR | Same as A1.5 | RIR_UNKNOWN | Same exercise/session | Not a measure of stimulus; RIR error | D | Card 3 | No |
| A1.7 | Pattern distribution | Count of working sets per volume_target_key(pattern) | clean_set, taxonomy, volume config | sets | Working sets | unknown pattern bucket if taxonomy missing | PATTERN_UNKNOWN | Same pattern grouping as the ledger | Grouping is a config decision, not a measurement | D | Card 3 | No |
| A2.1 | Load-base e1RM | Prescription selector: highest-priority override, else median of eligible set e1RMs in the 28-day robust window, else best usable in 84 days; age-decayed; calibration factor; **strictly before the session** | clean_set, e1rm_override, calibration, decay | kg | Exercise e1rm_applicable; load basis resolvable; eligible set | unknown/unavailable if no eligible estimate | E1RM_STALE, E1RM_OVERRIDE, E1RM_CALIBRATED, E1RM_RECONSTRUCTED | Exact exercise only | Formula error, decay assumption, median is not a max | D | Card 3, details | No (already used by prescription) |
| A2.2 | Relative intensity (set) | load_used_kg / load_base_e1rm_kg | A2.1, set load, load basis, bodyweight | fraction / % | Load base known; set load resolvable; working set; not a warm-up; not a test; e1RM applicable | unknown if either side missing; not_applicable for non-e1RM exercises | RI_NO_DENOM, RI_LOAD_UNKNOWN | **Within exercise and same load basis**; never across exercises | Load base error propagates directly; bodyweight convention | D | Card 3 | No |
| A2.3 | Relative-intensity distribution | Counts of working sets in configured bands (<60%, 60–<70%, 70–<80%, 80–<90%, ≥90%) + unknown count | A2.2 | sets | As A2.2 | Excluded sets are reported, not silently dropped | RI_PARTIAL_COVERAGE | Same exercise | Bands are display bins, not validated thresholds; 80% anchored to ACSM 2026 strength finding | D | Card 3 | No |
| A3.1 | RIR distribution | Counts at RIR 0,1,2,3,4,5, missing, warm-up | clean_set | sets | Working sets; exclude power/test | Missing is its own bin, not zero | RIR_UNKNOWN, RIR_OFF_SCALE | Same exercise/session | Self-report error; ordinal, do not average | D | Card 3 | No |
| A3.2 | RIR coverage | known_RIR_working_sets / working_sets | clean_set | fraction | Working sets | unknown if no working sets | RIR_UNKNOWN | Same session | A high coverage does not mean accurate RIR | D | Card 3, advanced | No |
| A4.1 | Exercise tonnage | Same as A1.3 | — | kg | — | — | — | Within exercise | See A1.3 | D | Card 3 | No |
| B1.1 | Session RPE | Latest non-null srpe for the session, with source and timing | session_feedback, session, workout_session | 1–10 | Session completed | unknown; never 0 | FEEDBACK_LATE, SRPE_IMMEDIATE | Within athlete only | Perceived, not objective; immediate vs 30-min | D | Card 5 | No |
| B1.2 | Duration | Latest non-null duration_min, with source (measured / manual / unavailable) | Same | minutes | Session completed | unknown if absent | DURATION_MANUAL | Within athlete only | Manual may include idle time; imported rows have no clock | D | Card 5 | No |
| B1.3 | Session load | srpe × duration_min | B1.1, B1.2 | AU | Both known | unknown if either missing; never 0 | SESSION_LOAD_UNKNOWN, FEEDBACK_LATE | Within athlete, same feedback protocol | Internal load, not physiological stress; arbitrary units | D | Card 5 | No |
| C1.1 | Recent reference e1RM | Median of the last 3 eligible per-session best **raw** e1RM observations strictly before the session, each within 84 days | clean_set | kg | ok session bests only; same exercise; each observation within 84 days; raw formula only | unavailable if none; single_prior if 1; limited if 2; never a historical maximum presented as typical | E1RM_REFERENCE_SPARSE, E1RM_DEGRADED | Exact exercise only | Raw Epley/Epley+RIR; no age decay or calibration factor; systematic formula bias may remain | D | Card 2 | No |
| C1.2 | Best recent performance e1RM | Highest eligible per-session best **raw** e1RM in the 84 days before the session | clean_set | kg | ok, same exercise, within 84 days; raw formula only | unavailable if none | E1RM_DEGRADED | Exact exercise only | Raw estimate; a maximum selected from more sets than today is not a typical baseline | D | Card 2, details | No |
| C1.3 | Personal best estimate | Highest eligible per-session best **raw** e1RM all time | clean_set | kg | ok, same exercise; raw formula only | unavailable if none | E1RM_DEGRADED | Exact exercise only | Raw estimate; all-time best may be old or from a different rep range; PR display only | D | Card 2, details | No |
| C2.1 | Post-session best e1RM | Highest eligible set-level **raw** e1RM in the current session | clean_set | kg | ok only for the headline; degraded display only; current session; same exercise; raw formula only | unavailable if none | E1RM_POST_MISSING, E1RM_DEGRADED | Exact exercise only | Raw best-of-set max; fatigue/back-off selection; a single-set estimate is noisy | D | Card 2 | No |
| C3.1 | Difference vs recent reference (kg) | post_best − recent_reference (both raw) | C1.1, C2.1 | kg | both ok and recent_reference has ≥2 observations | unavailable/insufficient if either missing, degraded or <2 | E1RM_DIFFERENCE_INSUFFICIENT_OBS, E1RM_DIFFERENCE_INSUFFICIENT_QUALITY | Same exercise, same raw method | A descriptive difference of raw estimates; not a measured change, not significance, not adaptation; 2 observations is limited | D | Card 2 | No |
| C3.2 | Difference vs recent reference (%) | 100 × (post_best − recent_reference) / recent_reference | C1.1, C2.1 | % | same as C3.1; recent_reference > 0 | unavailable | same | Same | No threshold; do not classify as clear/meaningful/within typical; measurement error not established | D | Card 2 | No |
| C3.3 | Difference data sufficiency | descriptive / limited / single_prior / insufficient_quality / unavailable | C1.1, C2.1 | status | derived from C1.1 count and C2.1 quality | status only, never a substitute value | E1RM_REFERENCE_SPARSE, E1RM_DIFFERENCE_INSUFFICIENT_QUALITY | Same exercise | Data sufficiency is not statistical confidence; single_prior shows no difference | D | Card 2 badge | No |
| C4.1 | Source set | The set_id, load, reps, RIR, exercise, method, quality, flags of the post estimate | clean_set | row | C2.1 known | unknown | E1RM_DEGRADED | Same exercise | One set can be an outlier | D | Expandable details | No |
| C5.1 | Exercise identity | Exact exercise_id, with display and documented equivalence | taxonomy | id | — | unknown if unresolved | IDENTITY_EQUIVALENT | Exact only, except documented history equivalence | Variant differences are real | D | Card 2/3 | No |
| C6.1 | e1RM observation | Per-session best eligible e1RM for one exercise | clean_set | kg | ok sets only for the primary series; degraded points shown separately | Gap, not interpolation | E1RM_DEGRADED | Exact exercise | Selection of best set; sparse | D | Performance view | No |
| C6.2 | Rolling median | Median of the last 3 observations (configurable) | C6.1 | kg | ≥3 observations | No line below 3; points only | SPARSE_SERIES | Exact exercise | Descriptive smoother, not a model | D | Performance view | No |
| D1.1 | Relative-strength ratio | 100 × latest_raw_e1RM(numerator) / latest_raw_e1RM(denominator) | C6.1 for both, config relationship | % | Both ok; latest eligible per-session best per side; **≥2 eligible observations per side**; date gap ≤ configured; both within max age | unavailable if either missing, stale, degraded or <2 observations | RATIO_GAP, RATIO_SPARSE, RATIO_ONE_SIDED | Explicitly configured pair only | Ratio of two noisy estimates; latest observation can be unrepresentative; no diagnostic validity | D | Performance view; max 2 on summary | No |
| D1.2 | Ratio dates/gap | Numerator date, denominator date, absolute gap | C6.1 | days | As D1.1 | unknown | RATIO_GAP | Same pair | A large gap makes the ratio historical, not current | D | Ratio detail | No |
| D1.3 | Ratio trend | Paired observations over time; no interpolation | D1.1 | % | ≥2 paired observations for a line; ≥5 for a change statement | Points only if sparse | SPARSE_SERIES | Same pair | Selection and measurement drift | D | Performance view | No |
| E1.1 | Power sets | Count of working sets on power-classified exercises (pattern == power_jump) | clean_set, taxonomy | sets | Power-classified exercise | unknown if classification missing; zero is valid if classification is complete | POWER_CLASS_UNKNOWN | Same exercise/session | Taxonomy coverage; Olympic lifts absent | D | Card 4 | No |
| E1.2 | Power repetitions | Sum of reps on power sets | clean_set | reps | Power sets | As E1.1 | — | Same exercise | Reps are not a quality measure | D | Card 4 | No |
| E1.3 | Mean velocity change across sets | 100 × (last_set_mean_velocity − first_set_mean_velocity) / first_set_mean_velocity for the same exercise and load | clean_set | % | ≥2 power sets, same exercise and load, velocity_present | unavailable if not measurable | POWER_VELOCITY_PARTIAL | Same exercise/load/equipment | Descriptive only; rest, technique, readiness, noise and execution can change mean velocity; not power quality or within-set loss | D | Card 4 | No |
| E1.4 | Power quality stop | Whether the athlete recorded a quality stop (height/technique/velocity drop) | workout_event payload or explicit flag | yes/no/not recorded | Power set | unknown; never inferred from velocity | POWER_QUALITY_UNRECORDED | Same exercise | Current prescription has text, not a structured event | D | Card 4 | No |
| E1.5 | Within-set velocity loss | Not computable from a mean | — | — | — | unavailable | VELOCITY_LOSS_UNAVAILABLE | — | A mean has no within-set variance | D | "Not available" | No |
| F1.1 | Spinal exposures | Per (session, exercise) effective ordinal cost from weekly_spinal_costs | clean_set, rule params, taxonomy | ordinal units | Working sets on high_fatigue_spinal exercises | zero if none and sets are present; unknown if no sets | SPINAL_UNRATED | Same rule/config; weekly ledger | Ordinal, not load; policy factors are assumptions | D | Card 4 | No |
| F1.2 | Heavy spinal sets | Working sets on high_fatigue_spinal exercises with rir ≤ 1, last 4 weeks | features/heavy_spinal | sets | Known RIR | unknown if RIR missing | RIR_UNKNOWN | Same window as the advisory | Context only; no cap effect | D | Card 4 / weekly | No |
| F1.3 | Axial demand mix | Counts of working sets by axial_spinal level (high/moderate/low/unknown) | features/demands | sets | Working sets | unknown count is explicit | SPINAL_UNRATED | Same dimension only | Qualitative; unknown ≠ low | D | Card 4, advanced | No |
| G1.1 | Productivity | Single optional item: 1–5 | session_feedback.productivity (new) | 1–5 | Session completed | unknown if skipped; never 0 | PRODUCTIVITY_NOT_RECORDED | Within athlete only | Single item, unvalidated; subjective | D | Card 5 | No |
| H1.1 | Feedback completeness | Which of sRPE, duration, productivity are present | Same | booleans | Session completed | unknown | — | Same session | — | D | Card 5 | No |
| H2.1 | Comparable-session summary | Median of a metric over up to 5 prior comparable sessions | clean_set, session type, main lifts | metric unit | Comparability rule (§10.3) | unavailable if <3 comparable sessions | COMPARISON_WITHHELD | Same session type + common main lift + no deload/minimum/technique | Still observational; exercise mix varies | D | Card 6 | No |

The Type column (D/I/P) describes whether a metric is descriptive, inferential or predictive. It is **not** an evidence grade. The decision basis for each design choice is in §11.5, and the product assumptions are in §11.7.

### 4.4 Detailed notes on the contentious metrics

#### A1.3/A4.1 Tonnage

Tonnage is external load × reps. It is meaningful **within one exercise** across sessions when the execution, equipment and ROM are stable. It is not a universal workload:

- a 100 kg bench rep and a 100 kg squat rep do not represent the same mechanical work;
- bodyweight movements exclude body mass by design, so a pull-up session can look small;
- ROM, tempo and technique change the work without changing load × reps;
- a substitution changes the exercise identity and breaks the comparison.

Therefore: show tonnage per exercise on the session summary and in exercise-specific trends. Do **not** show a session "total workload" as a headline. If a total is shown at all, label it "sum of external load × reps (not comparable across exercise mix)" and restrict comparisons to sessions with high exercise overlap.

#### A2.2 Relative intensity

The denominator is load_base_e1rm, not the post-session best. It must be the estimate that was available **before** the session. If the frozen plan snapshot carries the e1RM used, use it; otherwise recompute with the strict cutoff and flag reconstructed.

Bands (product assumption PA-04, to be registered):

| Band | Range | Interpretation |
|---|---|---|
| Very light | <60% | Warm-up/technique or high-rep accessory |
| Light | 60–<70% | Accessory/hypertrophy |
| Moderate | 70–<80% | Mixed |
| Heavy | 80–<90% | Strength-oriented; ACSM 2026 found ≥80% 1RM enhanced voluntary strength at group level |
| Near-max | ≥90% | Maximal/near-max; often a test |

The 80% cut is anchored to the ACSM overview of reviews. The other cuts are **display bins**, not physiological thresholds. Do not label a set "hypertrophy" or "strength" solely from its band; the adaptation depends on volume, effort, frequency and the individual.

#### A3.1 RIR distribution

RIR is an ordinal self-report with error that grows with distance from failure (Zourdos 2021: roughly 2 reps at 1 RIR, 3.7 at 3 RIR, 5 at 5 RIR in the squat; Refalo 2024 shows similar issues in the bench). Therefore:

- show counts per RIR value, not a mean;
- show missing and warm-up separately;
- do not convert RIR to a "proximity-to-failure score";
- do not infer RIR from velocity or reps;
- do not treat RIR 5 as a hard set;
- do not call RIR 4 "hard" with confidence when it is almost never used in the actual log (it is a config threshold, not a measured behaviour).

#### B1.3 Session load

session_load_au = sRPE × duration_min. Both inputs are required. This is an **internal-load** measure in arbitrary units. It reflects perceived session demand, not objective physiological stress. It must not be added to tonnage, hard sets or the e1RM difference vs recent performance. It must not be compared across athletes.

Missingness:

- sRPE missing → unknown.
- duration missing → unknown.
- both present → compute; label duration source and sRPE timing.
- late feedback → compute; flag FEEDBACK_LATE; do not correct.
- interrupted or unusually long → compute from the recorded duration; flag LONG_SESSION if >2× the recent comparable median (descriptive only); do not split or truncate.
- imported session with no feedback → unknown, never 0.

#### C1/C2 e1RM methodology

Formula: load × (1 + (reps + rir)/30) for an RIR-adjusted estimate; load × (1 + reps/30) only as the plain Epley fallback. The RIR-adjusted form is an approximation (ASSUMPTION-03 in the existing code), not a validated equation.

All monitoring performance quantities (session best, recent reference, best recent, personal best, post best, difference) use this **raw formula-derived** method. Do not apply age decay or a calibration factor to them. Do not mix a calibrated historical estimate with an uncalibrated current estimate. The prescription load base is separate and keeps its existing selector, calibration, decay and override behaviour.

Eligibility for the **monitoring headline**:

1. exercise_id is canonical and e1rm_applicable is true.
2. is_working_set and rir_class == "effort" (not warm-up, not RIR 6).
3. reps_unit == "reps" and 1 ≤ reps ≤ 20.
4. 0 ≤ rir ≤ 5; RIR 0 is allowed and flagged SUSPECT_RIR.
5. reps + rir ≤ 20 for an RIR-adjusted estimate. **This is a new guard**: the current add_e1rm checks only reps, so 20 reps + RIR 5 produces an effective 25-rep extrapolation. Reject it for the headline.
6. load > 0; load_basis in external / bodyweight_total / added.
7. For bodyweight_total or added, total mass is resolvable; otherwise unavailable.
8. No REPS_TYPO, SECONDS_NOT_REPS or LOAD_BASIS_UNKNOWN flag.
9. Not a set that the session summary classifies as a power set (no RIR target; e1RM for a jump is not meaningful unless loaded and e1rm_applicable).

Quality:

- ok: reps ≤ 10 and rir ≤ 3. This is the headline-eligible band.
- degraded: reps 11–20 or rir 4–5. Show with a warning; do not use for Δ or a new PR.
- invalid: fails any eligibility rule.

Why rir ≤ 3 for ok: RIR error grows with distance from failure, RIR 4 is nearly absent in the local log, and Robinson 2024's strength models show a plateau across a wide estimated-RIR range while hypertrophy favours closer-to-failure work. This is a **display-quality rule**, not a claim that RIR 4–5 sets are useless.

The existing prescription must keep its current e1RM behaviour (including degraded sets) to avoid changing loads. The stricter quality rule applies to the **new monitoring headline**, not to the load solver.

#### C3 interpretation

**No automatic classification.** A difference between two e1RM estimates is displayed as an absolute value and a percentage, with the observation count and dates. It is not labelled "clear", "meaningful", "significant" or "within typical variation". No threshold is applied. The 4.2% figure from Grgic 2020 is retained only as a literature reference for direct 1RM test–retest variability; it is not a validated threshold for this app's estimated 1RM.

**What the difference can and cannot mean.** The observed difference is a mixture of at least:

| Component | What it is | Can the current app estimate it? |
|---|---|---|
| Measurement error | Technical/protocol variability of the measurement itself (load, reps, RIR, device, test protocol) | Not for e1RM. The existing calibration reports prediction error against measured tests, not test–retest error. |
| Day-to-day biological variation | Real short-term fluctuation in capacity due to sleep, readiness, fatigue, stress, nutrition, motivation | No. It is confounded with measurement error in a single session. |
| Actual training adaptation | A slow change in capacity over weeks or months | No. It requires repeated observations and a design that separates it from noise. |
| Equation and RIR uncertainty | Error from Epley extrapolation and from self-reported RIR | Partly. The calibration report estimates formula-vs-test bias/MAE; RIR error is not directly measured. |
| Set-selection and sampling | Which sets were performed, how many, and whether they were top sets or back-offs | No. It is visible only as the difference between sessions and is not modelled. |

A single session difference cannot separate these. The UI therefore says "descriptive difference", not "strength increased" or "strength decreased".

**Status vocabulary.**

| Status | Condition | Display |
|---|---|---|
| descriptive | both sides ok; recent reference has ≥3 observations | show values, absolute and percentage difference, n and dates |
| limited | both sides ok; recent reference has exactly 2 observations | show values and difference, label "limited recent observations; not a trend" |
| single_prior | both sides ok; recent reference has exactly 1 observation | show the single prior value and date; no difference |
| insufficient_quality | either side degraded | show both estimates with their quality labels; no difference |
| unavailable | either side missing | show "unavailable" and the reason; no substitute |

**Improved / lower / unchanged.** If the post estimate is higher, say "today's best estimate was higher than the recent reference"; if lower, say "lower". Add possible explanations from the list above. Do not say "you gained/lost strength". If the values are equal, say "no difference at the displayed precision"; do not imply adaptation.

**New personal best.** Compare the post raw estimate with the all-time raw best (same exercise, ok quality). If higher, "new best estimate" and show the previous best/date. Do not call it a competition PR; it is an estimate. Do not use a decayed historical value as the record.

**Different rep range or a long interruption.** Label the source reps/RIR and the age of the reference observations. A 3-rep estimate and a 10-rep estimate have different error. After a break, the recent reference may be old; show the dates and the gap. Do not apply decay to the performance series. Do not interpret the difference as adaptation.

#### C4 individual measurement error (future)

The app has no defensible individual measurement-error estimate. Three quantities must be kept distinct:

1. **Direct-test repeatability.** Variation between repeated, standardised measured 1RM or 3RM assessments under the same protocol. A within-athlete **typical error** or **coefficient of variation (CV)** may be estimated from repeated tests. ICC is not used: it is a relative-reliability statistic that depends on between-participant variability and is not suitable for a single athlete. Estimates from a small number of tests are highly uncertain, and repeated tests close together estimate repeatability plus short-term biological variation, not pure measurement error.
2. **Formula prediction error.** The difference between a formula-derived e1RM and a genuinely measured criterion test. The existing e1rm_calibration points report per-lift bias, MAE and, where appropriate, MAPE. This is **not** test–retest error and must not be presented as one.
3. **Day-to-day biological variation.** Real short-term variation in performance due to sleep, readiness, fatigue, stress, nutrition and motivation. A small number of repeated tests cannot separate this cleanly from measurement error; the two are confounded.

A feasible future protocol may use repeated standardised tests separated enough to avoid acute fatigue, with the same equipment, ROM, warm-up and attempt protocol. The number and spacing of tests are a **feasibility-dependent product/measurement assumption** (PA-16), not a validated minimum. The protocol must be pre-registered and checked for feasibility before use.

If measured tests exist:

- Compare the formula-derived estimate available before each test with the measured result.
- Report n, rep-range coverage, bias, MAE and, where appropriate, MAPE.
- Use chronological validation where the sample permits; do not randomly split observations.
- Do not fit a correction factor to a tiny sample, and do not use the same observations both to fit and to claim independent validation.

Do **not** use any resulting typical-error or CV estimate as an automatic significant/not-significant threshold. Do **not** create a confidence interval or error band unless the data and a pre-specified statistical method genuinely support it; otherwise report the estimate with a qualitative statement of uncertainty. The estimate is descriptive and does not by itself license a programming change.

If measured tests are absent or insufficient, explicitly report that criterion-based individual calibration is not currently possible. Do not manufacture a substitute criterion from ordinary training sets, and do not treat the population 4.2% as the athlete's error.

#### D1 ratios

The ratio is 100 × latest eligible per-session best raw e1RM(numerator) / latest eligible per-session best raw e1RM(denominator). Both sides must be ok estimates, within max_age_days of the evaluation date, within max_gap_days of each other, and have **at least two eligible observations per side**. With fewer than two, the ratio is unavailable due to insufficient history; the available estimates and dates may still be shown. The dates, gap and per-side observation counts are always shown; data sufficiency is not statistical confidence. Defaults are product assumptions PA-05 and PA-06: max_gap_days = 14, max_age_days = 42. The gap is a product judgement: short enough that both reflect the same training period, long enough to occur at 2–3 sessions/week. It is not a validated window. If the gap is larger, show the ratio as historical with both dates and a warning, or withhold it.

Do not use raw training loads as substitutes for e1RM. Do not infer a relationship from programme_slot_of, vbt_family or names. Configure each pair explicitly.

#### E1 power

Power work is classified by pattern == power_jump today. The taxonomy does not include Olympic lifts; if they are added, the classification must be extended in config, not by name matching. Power sets are quality-limited, not RIR-scored (DEC-POWER-02). Count them, show the stop rule text, and exclude them from the ordinary RIR/relative-intensity distributions.

velocity_mps is a **mean per set**. It cannot yield within-set velocity loss. When the same exercise and load are repeated, the app may compute a **mean velocity change across sets**:

    mean_velocity_change_pct = 100 × (last_set_mean_velocity − first_set_mean_velocity) / first_set_mean_velocity

Its only practical value is to show whether later sets at the same exercise and load were slower; it cannot attribute the cause. This is a descriptive calculation, not a validated power-retention or movement-quality score. Mean velocity can change because of rest intervals, technique, readiness, measurement noise, execution differences or fatigue, and the app cannot attribute the cause. If the load changes between sets, do not compute it; report unavailable. Do not call it "retention". Do not infer a quality stop from it.

A structured quality-stop event does not exist. quality_stop is a text field on the prescription item and effort_model = quality marks the item. Until an explicit event/flag is recorded, power_quality_stop = unknown, not "met".

#### F1 spinal

Use weekly_spinal_costs from the rule registry. It creates one exposure per (session, exercise) for high_fatigue_spinal exercises, applies bounded set-count and mean-%e1RM policy factors, and sums per ISO week against the configured cap. The session summary should show:

- the session's exposures with their effective cost;
- the weekly total and cap position;
- the heavy-spinal advisory count (RIR ≤1) as context;
- the axial demand level from the demand catalogue, with unknown count.

Do not sum per-set costs into a new "spinal load". Do not describe the result as lumbar compression or shear. Do not use it as an injury predictor.

#### G1 productivity

Exact wording:

> **How productive did this session feel?**
>
> 1. Not at all productive
> 2. Slightly productive
> 3. Moderately productive
> 4. Very productive
> 5. Extremely productive
>
> *Optional. This is your own judgement, not a training-load measure.*

Store 1–5; null if skipped. Do not use a 0. Do not compute a session "quality" or "stimulus" from it. Do not require it to end the workout. Do not feed it into prescription, deload or selection. Report the distribution; a mean or median is acceptable only as a descriptive summary of an ordinal item, with that caveat.

---


## 5. e1RM recent-reference methodology (normative)

### 5.1 Definitions

- session_best(exercise, session) = the highest eligible **ok** set-level **raw** e1RM in that session. One observation per session. No age decay and no calibration factor are applied. Degraded estimates are excluded from the reference series and displayed separately.
- recent_reference_e1rm = the median of the last **3** raw session_best observations strictly before the current session, each within 84 days. This is the primary comparator.
- best_recent_e1rm = the highest raw session_best in the 84 days before the session. This is a separate best-performance reference; it is never used as a typical baseline.
- personal_best_e1rm = the highest raw session_best all time. This is for the PR display only.
- post_best_e1rm = the raw session_best for the current session.
- difference_vs_recent = post_best_e1rm − recent_reference_e1rm; both raw; the percentage uses recent_reference as the denominator.
- load_base_e1rm = the prescription selector value (median by default, with decay, calibration and override), used only for relative intensity. It is never substituted into the performance series.

### 5.2 Why a rolling median rather than a historical maximum

The previous draft compared today's best set with the highest eligible set in the preceding 84 days. That is not like-for-like:

- the historical maximum is selected from many sessions and many sets, while today's maximum is selected from one session;
- a single exceptional day in the window can set the reference for weeks;
- the maximum is an optimistic estimator by construction;
- recency is ignored inside the window, so an 80-day-old session competes equally with a 3-day-old one.

The alternatives:

| Method | Advantages | Disadvantages | Verdict |
|---|---|---|---|
| Historical maximum in 84 days | Simple; represents a known best | Unequal sampling; upward bias; one outlier dominates; ignores recency | Do not use as the typical baseline |
| Last single session best | Most recent; no lag | Very noisy; one bad day dominates | Display only, not a reference |
| Median of the last 3 session bests | Equal sampling unit; robust to one outlier; recency-bounded; transparent | Lags a real change by up to 3 sessions; can span a long break if sessions are sparse | **Primary comparator** |
| Median of the last 5 session bests | More robust | More lag; hides short blocks; needs more data | Optional sensitivity, not default |
| Complex time-series model | Could model trend and uncertainty | Overfits sparse data; adds assumptions; unvalidated | Do not implement |

The median of three is a **product/engineering choice**, not a statistically validated threshold. It is the smallest sample that is not simply the latest value and is still easy to explain. When only 2 or 1 observations exist, the median of the available observations is shown with the limited or single_prior status; it is not treated as a 3-observation median. Observations must be the same exercise identity; variants and equipment changes are not pooled. The observation dates are always shown. If fewer than three eligible observations exist, the comparison is labelled limited (2 observations), single_prior (1 observation) or unavailable (0); the app does not invent a reference.

### 5.3 Which value goes where

| Display | Value | Why |
|---|---|---|
| "Recent reference" | recent_reference_e1rm (raw) | Typical recent raw performance; primary comparator |
| "Best recent single session" | best_recent_e1rm (raw) | Context only; not a baseline |
| "Personal best estimate" | personal_best_e1rm (raw) | PR display only |
| "Best estimate today" | post_best_e1rm (raw) | Same session-level estimator |
| "Difference vs recent performance" | post_best_e1rm − recent_reference_e1rm (both raw) | Descriptive; no significance or adaptation claim |
| "Relative intensity" | load_base_e1rm | The load was solved from this estimate |

Do **not** use recent_reference as the relative-intensity denominator. Do **not** use the historical maximum as the recent reference. Do **not** call the difference "acute strength change" or "adaptation".

### 5.4 Minimum observations and sparse display

| Eligible session observations before the current session | Status | Display |
|---|---|---|
| ≥3 | descriptive | show median, n, date range, post value, absolute and percentage difference |
| 2 | limited | show median, n, dates, values and difference; label "limited recent observations; not a trend" |
| 1 | single_prior | show the single prior value and date; no difference; label "insufficient recent observations for a comparison" |
| 0 | unavailable | show "no recent eligible session best"; no substitute |

A session observation requires an **ok** estimate. A session with only degraded estimates does not enter the reference series; it is shown separately with its quality label.

### 5.5 Degraded, invalid and missing estimates

One policy, applied everywhere:

| Class | Meaning | Display | Used in difference? |
|---|---|---|---|
| ok | High-quality estimate: reps ≤10, RIR ≤3, reps+rir ≤20, load basis resolvable, not warm-up or power; a test is eligible and marked as test | normal estimate with method | yes |
| degraded | Low-quality estimate: reps 11–20, RIR 4–5, or another quality limitation | show the number with a visible "degraded" label, method and reason | **no** |
| invalid | Fails a hard eligibility rule (reps+rir >20, load basis unknown, typo flag, non-e1RM exercise) | do not show as an estimate; show the exclusion reason | no |
| missing | No eligible set | "unavailable" | no |

Rules:

- If either side is degraded, the difference status is **insufficient_quality**. Both estimates may be displayed if useful, clearly labelled, but no difference is calculated. Do not silently replace the degraded estimate with a different set, exercise or method.
- If either side is missing, the difference status is **unavailable**.
- A degraded estimate may be shown next to the "best recent" or "personal best" context with the same label; it is never used as the reference value or to claim a PR.
- The existing prescription keeps its current e1RM behaviour, including degraded sets, to avoid changing loads. The stricter policy applies to the monitoring headline, not to the load solver.

### 5.6 The cutoff rule (the circularity guard)

The session summary is computed after materialisation, so the current session's sets are already in clean_set. A naive date <= session_date filter would include them.

The rule:

- Exclude session_id == current_session_id always.
- Include occurred_on < session_date.
- For occurred_on == session_date, include a set only if it belongs to a different session whose workout_session.started_at is earlier than the current workout's started_at. If either timestamp is missing (imported rows), exclude same-date sets.
- Never use a set from the current session, even if its date is earlier (for example, a workout that spans midnight).

Regression test: compute recent_reference, add the current session's sets, recompute, and assert equality.

### 5.7 planned vs reconstructed load base

The load base is not a performance observation. It is the prescription's calibrated, age-decayed selector value.

- If plan_json has e1rm_kg, e1rm_ref, e1rm_quality and e1rm_age_days, mark source = planned.
- Else recompute the load base with the prescription selector on history strictly before the session and mark source = reconstructed.
- If both exist and differ, show both load-base values and the difference. Do not apply a tolerance or classify one as correct. The plan may have been generated earlier and the history may have changed.
- Do **not** compare the plan load base with the raw recent reference and call the difference a performance change. They are different constructs.
- The plan-drift note is descriptive: "The plan was generated from X kg; the load base immediately before the session was Y kg." It is not a verdict.

### 5.8 Individual measurement error

The method and its limits are in §4.4 C4. Until a defensible individual estimate exists, the app does not apply a meaningful-change threshold. It shows the difference descriptively and states that measurement error is not established for that lift. It does not substitute the population 4.2% or a formula prediction MAE for a test–retest error.

### 5.9 Worked examples

See §16.4–§16.5.

## 6. Longitudinal e1RM methodology

### 6.1 Observation

One point per (exercise_id, session_id): the session's raw post_best_e1rm. Use the same eligibility and quality rules as §5. Do not apply age decay or a calibration factor. Do not use the load-base median, and do not use the 84-day "best" repeatedly (that would create a step function, not a series).

### 6.2 Series breaks

Break the series when any of these changes:

- exercise_id (including a substitution);
- equipment or load basis (bar, SSB, trap bar, dumbbells, machine, belt, ROM convention);
- the documented history equivalence (only where the app already merges, e.g. hyperextension → back extension); show a marker;
- a change in the rep/RIR protocol that makes the estimates non-comparable (e.g., a switch from 5s to 1s).

Do not interpolate across a break. Do not silently concatenate trap bar and sumo. Show a vertical marker and a note.

### 6.3 Smoothing

Default: **rolling median of the last 3 observations**. It is simple, robust to one bad session, does not assume a functional form, and handles irregular spacing because it is observation-based. Alternatives:

| Method | Advantage | Disadvantage | Verdict |
|---|---|---|---|
| Last observation | No lag | Noisy; one bad day dominates | Use as the raw point |
| Rolling median of 3 | Robust, simple, explainable | Lags a real change by ~1 session | **Default** |
| Rolling median of 5 | More robust | More lag; hides short blocks | Offer as an option |
| Linear regression | Summarises slope | Assumes linearity; sensitive to outliers; encourages over-interpretation | Do not default |
| Spline/state-space | Flexible | Overfits sparse data; unvalidated; dependency | Do not implement |
| Fitness-fatigue | Mechanistic | Rejected retrospectively; non-identifiable (Marchal 2025) | Do not connect |

No interpolation. No extrapolation. If there are fewer than 3 observations, show points only. If there are fewer than 5, do not state a trend change.

### 6.4 Display

- Raw points: one dot per session, tooltip with date, load, reps, RIR, quality.
- Trend: rolling median line, dashed to signal "smoothed".
- Y-axis: kg, zero not forced (strength changes are small); label the unit.
- X-axis: date, with gaps; do not compress gaps to equal spacing without saying so.
- Series breaks: vertical line + label.
- Sparse state: "3 observations; no trend line yet."
- Data sufficiency: sufficient / limited / insufficient / unavailable based on observation count, recency and quality. This is not statistical confidence, and no numeric confidence is shown.

### 6.5 Interpretation

- "The latest estimate is above/below the recent median" — descriptive.
- "The trend over the last N observations is upward/downward" — only with ≥5 observations and a clear separation; still not proof of adaptation.
- "No automatic meaningful-change label. The app shows the raw difference and the observation dates; it does not classify the change."
- "After a break" if the gap is ≥28 days; show the gap. Do not decay the performance series; decay belongs to the load base, not the observation.
- "Exercise changed" if the series broke; do not compare across the break.

### 6.6 Accessory and variation lifts

The same method applies, but the data are sparser. Do not lower the eligibility bar to create a line. Show "insufficient observations" rather than a misleading trend. Do not compare an accessory's e1RM to a main lift's e1RM as if they were the same quantity; that is Domain D, with its own rules.

---

## 7. Accessory-to-main-lift ratio methodology

### 7.1 Configuration, not inference

Create config/strength-relationships.v1.yaml with entries like:

    schema_version: "1.0.0"
    relationships:
      - id: front_squat_to_competition_squat
        label: "Front squat / competition squat"
        numerator: front_squat
        denominator: competition_squat
        relationship_type: variant_to_main
        max_gap_days: 14        # proposed assumption PA-05
        max_age_days: 42        # proposed assumption PA-06
        min_observations: 2
        notes: "Descriptive relative performance only; not a weakness diagnosis."

Required fields: id, numerator, denominator, relationship_type, max_gap_days, max_age_days, min_observations, notes. Validate:

- both ids exist in the taxonomy;
- numerator ≠ denominator;
- no duplicate (numerator, denominator) pair;
- max_gap_days > 0, max_age_days >= max_gap_days;
- relationship_type is one of a small enum (variant_to_main, accessory_to_main, equipment_variant, range_variant);
- notes is non-empty.

Do **not** use programme_slot_of as the relationship graph. It is a prescription-slot hint (currently one entry), not a strength comparison. Do **not** use vbt_family; it pools load-velocity data for calibration, not strength.

### 7.2 Which observation to use

The ratio can be built from several observation choices, and they can give materially different answers:

| Method | What it uses | Advantages | Limitations | Verdict |
|---|---|---|---|---|
| Latest eligible per-session best, each side | The most recent ok session best for the numerator and denominator | Transparent; dates explicit; no smoothing; reflects current performance | A single session can be unrepresentative; needs both sides recent | **Primary provisional method** |
| Median of recent per-session bests, each side | Median of up to 3 recent session bests per side | More stable; less sensitive to one day | Requires equal-ish sampling; blurs dates; can mix different training periods; more complex to explain | Sensitivity check only, when both sides have ≥3 observations |
| Best in a rolling window, each side | Maximum session best in a window | Represents best known performance | Optimistic; unequal sampling; one outlier dominates | Do not use as the typical ratio |
| Independently smoothed series, then divide | Two smoothed lines divided at a date | Looks stable | Loses observation dates; double-smooths noise; can create a ratio where no paired data exist | **Reject** |

Recommendation: use the **latest eligible per-session best for each side**, each within max_age_days of the evaluation date, with a date gap no larger than max_gap_days. **At least two eligible observations per side are required before a ratio is displayed.** The dates and per-side counts are always visible. A recent-median ratio may be shown as a **sensitivity check** only when both sides have at least 3 observations and the two methods are displayed side by side; it is not the primary number.

### 7.3 Calculation, data sufficiency and quality

    ratio_pct = 100 × raw_e1RM(numerator) / raw_e1RM(denominator)

Both sides:

- exact configured exercise ids;
- ok quality; a degraded side makes the ratio unavailable for the headline (it may be shown with both estimates and a degraded label, but not as a current ratio);
- latest eligible session best within max_age_days of the evaluation date;
- date gap ≤ max_gap_days for a contemporaneous ratio;
- at least 2 eligible session observations per side; with exactly 1 the ratio is unavailable due to insufficient history, and with 0 or a missing estimate it is unavailable.

Data sufficiency is **not** statistical confidence:

| Status | Condition | Display |
|---|---|---|
| available | ≥2 eligible observations per side; both within max_age; gap ≤ max_gap; both ok | show ratio, both latest values, both dates, gap, n per side |
| insufficient_history | exactly 1 eligible observation on either side | show the available estimate and date; label the ratio "unavailable — insufficient history"; do not compute a ratio |
| insufficient_quality | either side degraded | show both estimates with quality labels; no ratio |
| stale_or_gap | either side older than max_age, or gap > max_gap | show "unavailable" and the reason; historical display only with both dates and a warning |
| unavailable | 0 observations or a missing estimate on either side | show "unavailable" and the reason |

If the gap is larger than max_gap_days but both sides are within max_age_days and both have at least 2 observations, show a **historical** ratio with both dates and a warning, or withhold it. Do not silently divide a recent numerator by an old denominator. If two sessions share a date and no start timestamp can order them, the latest observation cannot be determined; mark the ratio insufficient rather than guessing.

### 7.4 Display

| Field | Example |
|---|---|
| Ratio | 75.5% |
| Numerator | Front squat 123.3 kg (2026-10-20; 2 observations) |
| Denominator | Competition squat 163.3 kg (2026-10-23; 4 observations) |
| Gap | 3 days |
| Observation counts | numerator 2; denominator 4 |
| Data sufficiency | available (at least 2 per side; not a confidence statement) |
| Quality | both ok |
| Sensitivity check | recent-median ratio 75.0% (only if both sides have ≥3 observations) |

Do not show a target band. Do not colour a low ratio as "bad". Do not use a "confidence" label based on n alone. Do not rank the athlete against a population.

### 7.5 What a ratio can and cannot be used for

| Use | Status | Reason |
|---|---|---|
| Descriptive individual monitoring | **Supported as a display** | It is the ratio of two explicitly configured estimates, with dates and quality. It can prompt a review of technique, equipment, familiarity or fatigue. |
| Population reference values | **Not appropriate** | There are no validated individual norms; anthropometry, technique, ROM, equipment and specialisation differ. |
| Evidence that a ratio predicts or explains main-lift performance | **None found** | The literature supports task specificity and performance profiling, not a causal or diagnostic ratio. Any longitudinal association is an exploratory hypothesis. |

### 7.6 Interpretation and limitations

A ratio is influenced by anthropometry, technique, execution, ROM, equipment, specialisation, fatigue and e1RM error. A low ratio does not identify a weak muscle. A change in ratio does not establish that the accessory caused a change in the main lift. The existing evidence review PARENT-VARIANT-WEAKNESS-EVIDENCE.md already reached this conclusion; this specification adopts it rather than reopening it.

Labels: "relative performance", "ratio of estimates", "descriptive". Never "weakness", "imbalance", "diagnostic", "injury risk" or "target".

### 7.7 Historical ratio trends

Use **paired observations** only: a numerator and denominator observation whose dates are within max_gap_days. Each point displays both dates. Do not independently smooth the two series and divide the smoothed values. Do not interpolate between pairs. If fewer than 2 paired observations exist, show points only and do not state a trend.

### 7.8 Future analysis (Domain D6)

Only after enough paired observations:

- pre-register the question: "Are changes in the ratio associated with subsequent main-lift performance?"
- use chronological out-of-sample validation;
- compare against simple baselines (last observation, rolling median, main-lift trend);
- report n, missingness, effect size and stability;
- no causal language;
- no automatic exercise selection, volume change or "weakness" targeting.

## 8. Data-quality and missing-data rules

### 8.1 Zero, missing, unknown, not applicable, invalid, estimated

| Value | Meaning | Rendering | Example |
|---|---|---|---|
| 0 | A real measured zero | 0 | 0 power sets in a non-power session |
| Missing | No value was recorded | "Not recorded" | sRPE blank |
| Unknown | A value should exist but cannot be determined | "Unknown" | hard sets when all RIR are missing |
| Not applicable | The quantity has no meaning | "Not applicable" | e1RM for a plank |
| Invalid | A value exists but fails validation | "Excluded: invalid" | 21-rep e1RM |
| Estimated | A formula result | "Estimated" + method | e1RM 156.0 kg (Epley+RIR) |

Do not convert missing to zero. Do not convert unknown to zero. Do not render an empty cell as a dash without a legend.

### 8.2 Metric-specific missing-data behaviour

| Situation | Behaviour |
|---|---|
| No session feedback | sRPE, duration, session load, productivity = unknown; card 5 says "Not recorded" with an "Add feedback" link. |
| sRPE only | session load = unknown until duration is added; do not use a default duration. |
| Duration only | session load = unknown until sRPE is added. |
| Feedback entered late | compute; FEEDBACK_LATE if recorded >24 h after ended_at for a live workout; imported sessions have no timing, so the flag is not_applicable. |
| Manual duration | compute; DURATION_MANUAL; do not call it measured. |
| Interrupted session | compute from recorded duration; LONG_SESSION if >2× recent comparable median; no automatic adjustment. |
| RIR missing on a working set | hard set = unknown for that set; RIR distribution has a missing bin; e1RM headline excludes it. |
| RIR 6 | warm-up; excluded from dose, e1RM, RI, hard sets; counted separately. |
| Load basis unknown | e1RM/RI/tonnage = not applicable; set still counts for completion. |
| Bodyweight unknown | e1RM/RI = unavailable for bodyweight lifts; set still counts. |
| No eligible post set | post e1RM = unavailable; do not substitute another exercise or a warm-up. |
| Degraded estimate on either side | show both estimates with their method/quality labels; difference status = insufficient_quality; no difference. |
| Fewer than 3 recent session observations | recent reference = limited (2) or single_prior (1); at 2 show a limited comparison, at 1 show the value/date and no comparison; show the available dates. |
| e1RM older than 84 days | unavailable; show the last date and "too old". |
| Tonnage partial | sum known sets; show known/total; never impute. |
| Ratio one side missing, degraded or fewer than 2 observations | unavailable; if degraded or insufficient history, show the available estimates and dates but no headline ratio. |
| Ratio gap too large | unavailable or historical with warning; data sufficiency is not confidence. |
| Power quality not recorded | unknown, not "met". |
| No power work | 0 if the session's exercise classification is complete; unknown if classification is missing. |
| No spinal exposures | 0 if working sets are present and all are classified; unknown if no sets or classification missing. |
| Productivity skipped | unknown; never 0. |

### 8.3 Data-quality flags (derived, not stored)

E1RM_REFERENCE_MISSING, E1RM_REFERENCE_SPARSE, E1RM_REFERENCE_RECONSTRUCTED, E1RM_POST_MISSING, E1RM_DEGRADED, E1RM_DEGRADED_ONLY, E1RM_REPS_RIR_OVER_CAP, E1RM_NO_RIR, E1RM_LOAD_BASIS_UNKNOWN, E1RM_BODYWEIGHT_UNKNOWN, E1RM_STALE, E1RM_OVERRIDE, E1RM_CALIBRATED, E1RM_DIFFERENCE_INSUFFICIENT_OBS, E1RM_DIFFERENCE_INSUFFICIENT_QUALITY, RI_NO_DENOM, RI_PARTIAL_COVERAGE, TONNAGE_PARTIAL, SESSION_LOAD_UNKNOWN, FEEDBACK_LATE, DURATION_MANUAL, LONG_SESSION, RIR_UNKNOWN, RIR_OFF_SCALE, POWER_CLASS_UNKNOWN, POWER_QUALITY_UNRECORDED, POWER_VELOCITY_PARTIAL, VELOCITY_LOSS_UNAVAILABLE, SPINAL_UNRATED, RATIO_GAP, RATIO_SPARSE, RATIO_ONE_SIDED, COMPARISON_WITHHELD, PRODUCTIVITY_NOT_RECORDED.

These are **derived display flags**, not new persisted state. E1RM_CALIBRATED, E1RM_STALE and E1RM_OVERRIDE apply to the load base only; they are never applied to the raw performance series. Do not reuse an existing ingest flag for a different meaning.

### 8.4 Warm-up, working, failed, partial, testing and substitution

| Case | Handling |
|---|---|
| Warm-up (RIR 6) | Excluded from all dose/e1RM/RI/hard-set metrics. Show count and share as a coaching signal. |
| Working set | is_working_set = 1; RIR known or missing. |
| Failed set (RIR 0) | Included; flagged SUSPECT_RIR; eligible for e1RM; not a warm-up. |
| Partial set / missed reps | No field; count actual reps; report completion status under; do not infer a partial ROM. |
| Testing attempt | Separate high_intensity_exposure; if also a clean_set, count once for completion but not as ordinary volume; exclude from the RIR/RI distribution when linked; show in Special exposure. |
| Substitution | Compare against the modified plan; show the swap event and the original slot; do not map e1RM across exercises. |
| Abandoned workout | No materialised session; no summary. |
| Technique session | No template; show duration/feedback only; no completion/strength sections. |
| Minimum session (MOD-MIN-001) | Show the target/estimate/measured block; do not compare dose to a full session. |
| Deload (MOD-DELOAD-001) | Show a badge; withhold or restrict historical comparisons. |

---


## 9. Workout-end UI specification

### 9.1 Principles

- **Mobile-first**: design for a 390 px portrait viewport; landscape uses a two-column grid only where it does not squeeze tables.
- **Three primary numbers per card**, maximum. Everything else is progressive disclosure.
- **No composite score.** Do not add a single "workout score", "quality score" or "stimulus score".
- **No false precision.** Round kg to 0.5, percentages to 1 decimal, AU to whole numbers. Do not show 4 significant figures for an estimate.
- **No colour-only meaning.** Pair colour with text ("above", "within", "unavailable").
- **No inline handlers.** Use data-action plus event delegation and escaped attributes (AGENTS §7.8).
- **Accessible**: labels, aria-live for async updates, 44 px touch targets, focus states.

### 9.2 Information hierarchy

| Tier | Content | Always visible? |
|---|---|---|
| 1 | Completion, strength performance, feedback summary | Yes |
| 2 | External dose (sets, tonnage per exercise, RIR, relative intensity, hard sets) | Yes, condensed |
| 3 | Special exposure (power, high-intensity, spinal) | Yes, condensed; details expandable |
| 4 | Historical comparison | Only if ≥3 comparable sessions |
| 5 | Ratios | At most 2, only if data-sufficient (≥2 observations per side) and both sides ok; otherwise a link |
| 6 | Source sets, excluded sets, methods, flags | Expandable |
| 7 | Full historical analysis | Separate Performance view |

### 9.3 Wireframe (iPhone portrait)

    ┌──────────────────────────────────────────────┐
    │  WORKOUT SUMMARY                 Tue 28 Oct │
    │  Bench + Squat · 65 min · sRPE 7 · 455 AU   │
    │  Productivity 4/5                            │
    ├──────────────────────────────────────────────┤
    │  1  COMPLETION                    3/4 items  │
    │  ████████████████░░  14/16 sets · 62/70 reps │
    │  Bench press       complete        4/4       │
    │  Competition squat under           3/4       │
    │  Back extension    complete        3/3       │
    │  [substitution: none]                        │
    ├──────────────────────────────────────────────┤
    │  2  STRENGTH PERFORMANCE                     │
    │  Bench press                                 │
    │  recent ref   157.5 kg  median of 3 sessions │
    │  best recent  158.4 kg  single session       │
    │  best today   158.7 kg  set 2: 140×3 @2      │
    │  difference   +1.2 kg (+0.8%) · descriptive  │
    │  measurement error not established           │
    │  [Why this set?]  [All eligible sets]        │
    ├──────────────────────────────────────────────┤
    │  3  TRAINING DOSE                            │
    │  Bench press   3 sets · 1,980 kg tonnage     │
    │  Relative intensity  [80%][85%][70%]         │
    │  RIR  0:0  1:1  2:2  3:0  4:0  5:0  ?:0      │
    │  Hard sets 3 · near failure 3 · unknown 0    │
    │  Patterns  push 3 · squat 3 · hinge 3        │
    ├──────────────────────────────────────────────┤
    │  4  SPECIAL EXPOSURE                         │
    │  Power      3 sets · 15 reps · velocity −5.7%│
    │  Quality    not recorded                     │
    │  High int.  none                             │
    │  Spinal     trap bar 2.0 · back ext 0.85 ... │
    │             weekly 4.0 / 6.0                 │
    ├──────────────────────────────────────────────┤
    │  5  HOW IT FELT                              │
    │  sRPE 7 (immediate) · 65 min (measured)      │
    │  Session load 455 AU                         │
    │  Productive 4/5                              │
    ├──────────────────────────────────────────────┤
    │  6  COMPARED WITH 3 COMPARABLE SESSIONS      │
    │  sets 14 vs 15 (median) · hard 8 vs 9        │
    │  top set 85% vs 84% · session load 455 vs 470│
    │  [View all]                                  │
    ├──────────────────────────────────────────────┤
    │  [Review workout]  [Record e1RM]  [Details]  │
    └──────────────────────────────────────────────┘

### 9.4 Component-level specification

**Header**

- Date, session type label, duration, sRPE, session load AU, productivity.
- If any is missing: "Not recorded", with an "Add feedback" link that opens the existing review flow.
- Do not show the rubric composite.

**Section 1 — Completion**

- Progress bar: completed working sets / planned working sets (modified plan), plus reps if available.
- Per-item table: exercise display name, status (complete / under / over / missing / extra), actual/planned sets, actual reps.
- Substitution badge: "Substituted for X" from the plan/event, if applicable.
- "Original prescription" disclosure: the existing original_comparison table, unchanged.
- Do not count a missing item as zero dose.

**Section 2 — Strength performance**

- One row per main lift that has a post estimate or at least one recent reference observation; not every accessory.
- Columns: exercise, recent reference (median, n, date range), best recent single session (context), best today (source set), difference kg, difference %, status.
- Status labels: descriptive, limited, single_prior, insufficient_quality, unavailable. Do not use clear increase, clear decrease, within typical variation or significance language.
- The difference is descriptive only. Show the observation count and dates next to it. State that the estimates are raw Epley/Epley+RIR and may carry systematic bias; state "measurement error not established for this lift" unless a defensible individual error estimate exists.
- [Why this set?] expands: load, reps, RIR, exercise, method, quality, flags, source (planned/reconstructed/override). Calibration and age decay are load-base context only and are not applied to this performance estimate.
- [All eligible sets] expands a table with each set's e1RM and exclusion reason (warm-up, RIR missing, reps >10, reps+rir >20, load basis unknown, quality degraded). Test-linked sets are marked and shown in Special exposure, not excluded from e1RM.
- If no post set: "No eligible set today" + the reason. If exactly 2 recent observations: show the limited comparison. If fewer than 2: "Insufficient recent observations for a comparison" + the available dates.
- Do not label the difference "strength gain", "acute strength change", "adaptation" or "PR". Use "new best estimate" only when the PR rule is met.

**Section 3 — External training dose**

- Per-exercise table: sets, reps, tonnage (with coverage), hard sets, near-failure sets, RIR distribution summary.
- Relative-intensity distribution: counts per band + unknown count. Use a small stacked bar or a table; do not use a single average without the distribution.
- Pattern distribution: counts by volume_target_key; do not compare to MEV/MAV here (weekly context is elsewhere).
- "Tonnage is external load × reps; compare within an exercise only."
- If any set has no load base, show "N sets uncategorised".

**Section 4 — Special exposure**

- Power: sets, reps, exercise, mean velocity change across sets if measurable (same exercise and load), and quality stop status. Label it "mean velocity change", not retention or quality. "Within-set velocity loss is not available from mean velocity."
- High-intensity: list exposures linked to the session, kind, exercise, intensity class, guard status. "Not counted as working volume."
- Spinal: per-exercise effective cost, weekly total/cap, heavy-spinal count, axial demand mix with unknown count. Label "ordinal exposure, not lumbar load".
- If no special exposure: "None recorded" — a valid zero if the session's classification is complete.

**Section 5 — Feedback**

- sRPE, duration with source, session load AU, productivity.
- "sRPE is immediate, not the 30-minute protocol" helper.
- "Session load is sRPE × minutes in arbitrary units; it is not a physiological measurement."
- Missing values show "Not recorded" and an action, never 0.
- Productivity helper: "Optional self-report; not used for prescription."

**Section 6 — Historical comparison**

- Only if ≥3 comparable sessions (§10.3).
- Show median of the prior comparisons, n, and the comparison key ("same session type + common main lift").
- Withhold for deload, technique, minimum sessions or <50% exercise overlap.
- Do not compare by date proximity alone.

**Section 6b — Ratios (only if shown)**

- Show at most two ratios, and only when both sides have at least 2 eligible observations.
- Display the ratio, numerator value and date, denominator value and date, date gap, per-side observation counts, and data-sufficiency status. Do not call 2 observations "confidence" or "validation".
- If either side has exactly 1 observation, show the available estimate and date but label the ratio "unavailable — insufficient history". If either side has 0 observations or a missing estimate, label it "unavailable". Do not compute a ratio.
- Link to the Performance view for the full ratio table and paired trend.

**Section 7 — Actions**

- "Review workout" (existing).
- "Record an e1RM" (existing test/override flow).
- "Performance" (link to the historical view).
- "Details" (source sets, methods, flags).

### 9.5 Landscape and tablet

- Two columns: left = completion + strength; right = dose + special + feedback.
- Tables keep horizontal scroll within .table-scroll; the page itself must not scroll horizontally.
- The header remains one line; the action bar remains at the bottom of the content, not fixed over the safe area.

### 9.6 Copy rules

| Do say | Do not say |
|---|---|
| "Recent reference (median of 3 sessions)" | "Typical max" |
| "Best recent single session" | "Current max" |
| "Best estimate today" | "New 1RM" |
| "Difference vs recent performance" | "Strength gain" |
| "Descriptive difference; measurement error not established" | "No progress" or "clear change" |
| "Estimated from Epley + RIR" | "Measured" |
| "Unavailable" | "0" or "—" without explanation |
| "Hard sets (RIR ≤ 4)" | "Effective sets" |
| "Session load (AU)" | "Training stress" |
| "Ordinal spinal exposure" | "Spinal load" |
| "Relative performance ratio" | "Weakness ratio" |

---

## 10. Historical monitoring and analysis

### 10.1 Trends

The Performance view (new top-level page, or a section under Outcomes) should support:

- exercise-specific e1RM observations and rolling median;
- exercise-specific tonnage and hard-set counts;
- relative-intensity distribution over time;
- session load AU over time, with sRPE coverage;
- power sets/reps and mean velocity change across sets;
- axial/spinal exposure over time;
- configured ratios using latest contemporaneous observations, and paired observations for historical trends.

Filters: date range, exercise, session type, include/exclude deloads, minimum quality. Always show n and coverage. Never interpolate.

The Performance view shows the raw session observations and the rolling median. It does not apply the 4.2% figure, a "clear change" label or a "within typical variation" band. If it shows a difference between the latest observation and the rolling median, that difference is descriptive and accompanied by the observation dates and n; no significance or adaptation claim is made.

### 10.2 Dose–response (exploratory)

Define a small, pre-registered set of exposures and outcomes:

| Exposure | Outcome | Lag |
|---|---|---|
| Session load AU | Next-session best e1RM (same lift) | 1 session |
| Hard sets (per pattern) | Next-session best e1RM (same lift) | 1 session, 1 week |
| Relative-intensity distribution (e.g., sets ≥80%) | Next-session best e1RM | 1 session |
| Spinal effective cost | Next-session best e1RM / sRPE | 1 session |
| Power sets | Next-session jump/speed if available | 1 session |
| Productivity | Next-session performance / sRPE | 1 session |

Method: within-lift, within-athlete descriptive comparisons; report n, missingness, effect size, and uncertainty. Do not use causal language. Do not fit a complex model to sparse data. If a model is ever attempted, it needs chronological out-of-sample validation against the baselines in §12.3.

### 10.3 Comparable-session comparison

A prior session is comparable when **all** hold:

1. same session_type (or a documented equivalent);
2. at least one common main lift;
3. not a deload, technique or minimum session;
4. within the last 8 weeks (config);
5. exercise overlap ≥50% by working sets;
6. at least 3 prior comparable sessions.

Do not compare sessions merely because they are a week apart. Do not compare a squat day to a hinge day. Do not compare a full session to a minimum session.

Metrics to compare: completed working sets, hard sets, top-set relative intensity, session load AU (if both have feedback), post e1RM (same lift). Show medians, not means, and n.

### 10.4 Recovery and fatigue associations

Investigate whether session load, hard sets, relative intensity or spinal cost are associated with subsequent performance. Do not assume a high load impairs performance. Account for:

- days between sessions;
- exercise-specific exposure (a heavy squat does not necessarily affect bench);
- training frequency;
- exercise selection and substitutions;
- training interruptions;
- missing observations;
- readiness and sleep, if available.

Report descriptive associations; no causal claims. A null result is a result.

### 10.5 Programme evaluation

The system can describe:

- 2 vs 3 sessions/week attendance and dose;
- volume changes;
- exercise substitutions;
- missed sessions and interruptions;
- periodisation blocks;
- ratio changes.

It cannot, from observational data alone, establish that one configuration is better. Confounding by readiness, selection, life stress and time is severe. Use the existing attendance, outcomes, prospective and reviews features; do not build a parallel experiment engine. No automatic programming recommendations.

---

## 11. Scientific evidence review

### 11.0 Decision basis

| Basis | Meaning | How it is labelled |
|---|---|---|
| A — Evidence-supported | A finding directly supported by relevant research, with the population and limits stated | cites a source; the inference is limited to what the source supports |
| B — Engineering decision | A deterministic, testable choice needed to make the software consistent: cutoffs, status vocabulary, missing-data rules, date handling | states why it is needed and what test pins it |
| C — Product assumption | A pragmatic choice about windows, display bands, sample sizes or user experience that is not a validated scientific rule | states the choice, why it was chosen and what evidence would justify changing it |

A source grade (A–F in §11.1) describes the **study design**, not the decision basis. For example, a meta-analysis can support a general principle (basis A) while the specific window used in the app remains a product assumption (basis C).

### 11.1 Evidence grades

| Grade | Meaning |
|---|---|
| A | Systematic review / meta-analysis / overview of reviews |
| B | Randomised or controlled trial |
| C | Observational, measurement or validation study |
| D | Biomechanical/mechanistic study |
| E | Narrative review, expert consensus or proposal |
| F | Engineering/product judgement |

A grade describes the **source**, not the strength of the inference for this athlete. A group-level meta-analysis does not validate an individual metric. The decision-basis labels in §11.0 are the ones that say whether a specific design choice is evidence-supported or a product assumption.

### 11.2 Required sources, verified

| # | Verified record | Design | What it supports | What it does not support | Grade |
|---|---|---|---|---|---|
| 1 | Currier BS, D'Souza AC, Singh MAF, Lowisz CV, Rawson ES, Schoenfeld BJ, Smith-Ryan AE, Steen JP, Thomas GA, Triplett NT, Washington TA, Werner TJ, Phillips SM. **American College of Sports Medicine Position Stand. Resistance Training Prescription for Muscle Function, Hypertrophy, and Physical Performance in Healthy Adults: An Overview of Reviews.** Med Sci Sports Exerc. 2026;58(4):851–872. DOI 10.1249/MSS.0000000000003897. PMID 41843416. | Overview of 137 systematic reviews, >30,000 participants | Resistance training improves strength, size, power, endurance, velocity, gait, balance and function. Strength was enhanced by ≥80% 1RM, full ROM, 2–3 sets, at the start of sessions, ≥2 sessions/week. Hypertrophy was enhanced by ≥10 sets/week and eccentric overload. Power was enhanced by 30–70% 1RM, low-to-moderate volume (≤24 reps·sets), Olympic-style lifting and fast concentric power training. Failure, equipment, complexity, set structure, TUT, BFR and periodisation did not consistently affect outcomes. | It does not validate an individual's %1RM, an e1RM formula, a session score or a ratio. The recommendations are group-level and heterogeneous. "Power" is not the same as box-jump quality. | A |
| 2 | Sweet TW, Foster C, McGuigan MR, Brice G. **Quantitation of resistance training using the session rating of perceived exertion method.** J Strength Cond Res. 2004;18(4):796–802. DOI 10.1519/14153.1. PMID 15574104. | Controlled validation, 20 habituated adults, aerobic and resistance bouts | Session RPE collected 30 min after exercise tracked relative intensity; resistance session RPE increased with %1RM despite less total work. Supports sRPE as an internal-load measure and the 30-min timing. | It does not validate an immediate end-of-workout rating, a session-load AU threshold, or a fatigue model. The sample is small and short-term. | B |
| 3 | Helms ER, Kwan K, Sousa CA, Cronin JB, Storey AG, Zourdos MC. **Methods for Regulating and Monitoring Resistance Training.** J Hum Kinet. 2020;74:23–42. DOI 10.2478/hukin-2020-0011. PMID 33312273. | Narrative review of 90 studies, 11 themes | Many monitoring methods exist; physiological, performance and perceptual measures can correlate strongly with performance, but practical methods are limited. Velocity, RIR-based RPE and jump height are practical; evidence for enhancing performance is preliminary. | It does not establish one best method or validate a composite. "Strong correlation" is not causal or individual-level. | E |
| 4 | Pelland JC, Robinson ZP, Remmert JF, Cerminaro RM, Benitez B, John TA, Helms ER, Zourdos MC. **Methods for Controlling and Reporting Resistance Training Proximity to Failure: Current Issues and Future Directions.** Sports Med. 2022;52(7):1461–1472. DOI 10.1007/s40279-022-01667-2. PMID 35247203. | Narrative/critical review | Proximity to failure has no consistent quantification. %1RM prescription produces wide per-set RIR variation; velocity loss–RIR relationships vary by set, load and exercise; self-reported RIR is subjective and often unreported. | It does not validate RIR as precise, velocity loss as a universal RIR proxy, or a single prescription method. | E |
| 5 | Robinson ZP, Pelland JC, Remmert JF, Refalo MC, Jukic I, Steele J, Zourdos MC. **Exploring the Dose-Response Relationship Between Estimated Resistance Training Proximity to Failure, Strength Gain, and Muscle Hypertrophy: A Series of Meta-Regressions.** Sports Med. 2024;54(9):2209–2231. DOI 10.1007/s40279-024-02069-2. PMID 38970765. | Exploratory multilevel meta-regressions | Strength gains were similar across a wide estimated-RIR range; hypertrophy tended to improve closer to failure. Supports keeping strength and hypertrophy interpretations distinct and a buffer rather than a tight RIR veto. | Estimated RIR was inferred from study descriptions, not measured; model fit was modest; it does not validate an individual's RIR or a specific target. | A |
| 6 | Pareja-Blanco F, Loturco I. **Level of Effort: A Practical Approach for Resistance Training Monitoring and Prescription.** J Hum Kinet. 2026;102:259–266. DOI 10.5114/jhk/221229. PMID 42211812. | Conceptual/practical proposal | Argues that identical RIR values may not represent equivalent stimuli across rep ranges; proposes "level of effort" as reps performed / max reps, quantified via fastest-rep velocity and velocity loss. | It is a proposal, not a validated monitoring metric. It does not establish that the composite predicts adaptation, nor that velocity loss is accurate for every lift (see the hex-bar evidence). | E |
| 7 | Sousa CA, Zourdos MC, Storey AG, Helms ER. **The Importance of Recovery in Resistance Training Microcycle Construction.** J Hum Kinet. 2024;91(Spec Issue):205–223. DOI 10.5114/jhk/186659. PMID 38689583. | Review of 24 studies | Failure may lengthen recovery; higher volume increases recovery demands; lower-body, multi-joint, eccentric and lengthened-position work may need longer; individual variation is wide. Supports cautious recovery interpretation and not assuming a high load always impairs performance. | It does not provide individual recovery windows or validate a session-load threshold. | E |
| 8 | Marchal A, Benazieb O, Weldegebriel Y, Méline T, Imbach F. **Statistical flaws of the fitness-fatigue sports performance prediction model.** Sci Rep. 2025;15:3706. DOI 10.1038/s41598-025-88153-7. PMID 39881202. | Bayesian re-analysis of two datasets with cross-validation | The fitness-fatigue model was ill-conditioned; fitness and fatigue parameters were poorly identifiable; adding fatigue parameters did not improve out-of-sample prediction (p > 0.40). Supports rejecting complex forecasting and requiring out-of-sample validation. | It does not prove every fatigue model is useless; it shows this model class is fragile on these data. | A/C |
| 9 | Scott BR, Duthie GM, Thornton HR, Dascombe BJ. **Training Monitoring for Resistance Exercise: Theory and Applications.** Sports Med. 2016;46(5):687–698. DOI 10.1007/s40279-015-0454-0. PMID 26780346. | Narrative review | Resistance training is complex; volume load, perceived intensity and subjective questionnaires are useful; no consensus on how to integrate them; velocity may be valuable. Supports a multi-dimensional, non-composite approach. | It does not validate a universal metric or a combined score. | E |

### 11.3 Additional sources used

| # | Verified record | Supports | Grade |
|---|---|---|---|
| 10 | Day ML, McGuigan MR, Brice G, Foster C. Monitoring exercise intensity during resistance training using the session RPE scale. J Strength Cond Res. 2004;18(2):353–358. DOI 10.1519/R-13113.1. PMID 15142026. | Session RPE reliability across resistance-training intensities (between-participant ICC 0.88). This is not an N-of-1 reliability estimate. | B |
| 11 | Grgic J, Lazinica B, Schoenfeld BJ, Pedisic Z. Test-Retest Reliability of the One-Repetition Maximum (1RM) Strength Assessment: a Systematic Review. Sports Med Open. 2020;6(1):31. DOI 10.1186/s40798-020-00260-z. PMID 32681399. | 32 studies, median between-participant ICC 0.97, median CV 4.2% for **direct 1RM tests**. This is a literature reference for actual 1RM test–retest variability; it is not a validated threshold for this application's estimated e1RM, which adds formula and RIR error. | A |
| 12 | Zourdos MC, Goldsmith JA, Helms ER, et al. Proximity to Failure and Total Repetitions Performed in a Set Influences Accuracy of Intraset Repetitions in Reserve-Based Rating of Perceived Exertion. J Strength Cond Res. 2021;35(2S):S158–S165. DOI 10.1519/JSC.0000000000002995. | RIR error grows with distance from failure (~2 reps at 1 RIR, ~3.7 at 3, ~5 at 5 in the squat). | B |
| 13 | Refalo MC, Remmert JF, Pelland JC, Robinson ZP, Zourdos MC, Hamilton DL, Fyfe JJ, Helms ER. Accuracy of Intraset Repetitions-in-Reserve Predictions During the Bench Press Exercise in Resistance-Trained Male and Female Subjects. J Strength Cond Res. 2024;38(3):e78–e85. DOI 10.1519/JSC.0000000000004653. PMID 37967832. | RIR prediction error is a property of the method, not just experience. | B |
| 14 | Reynolds JM, Gordon TJ, Robergs RA. Prediction of one repetition maximum strength from multiple repetition maximum testing and anthropometry. J Strength Cond Res. 2006;20(3):584–592. DOI 10.1519/R-15304.1. PMID 16937972. | 1RM prediction from multiple-RM testing has non-trivial standard error; accuracy varies by lift. | C |
| 15 | Mayhew JL, Johnson BD, Lamonte MJ, Lauber D, Kemmler W. Accuracy of prediction equations for determining one repetition maximum bench press in women before and after resistance training. J Strength Cond Res. 2008;22(5):1570–1577. DOI 10.1519/JSC.0b013e31817b02ad. PMID 18714230. | Prediction accuracy is population- and training-state-dependent; a single equation is not a measurement. | C |
| 16 | Jukic I, Castilla AP, Ramos AG, Van Hooren B, McGuigan MR, Helms ER. The Acute and Chronic Effects of Implementing Velocity Loss Thresholds During Resistance Training: A Systematic Review, Meta-Analysis, and Critical Evaluation of the Literature. Sports Med. 2023;53(1):177–214. DOI 10.1007/s40279-022-01754-4. PMID 36178597. | Velocity-loss thresholds trade volume against fatigue; higher loss is not automatically better. | A |
| 17 | Spitz RW, Gonzalez AM, Ghigiarelli JJ, Sell KM, Mangine GT. Load-Velocity Relationships of the Back vs. Front Squat Exercises in Resistance-Trained Men. J Strength Cond Res. 2019;33(2):301–306. DOI 10.1519/JSC.0000000000002962. PMID 30688871. | Front and back squat do not share a load–velocity relationship; variants are not interchangeable. | B |
| 18 | Lockie RG, Callaghan SJ, Moreno MR, et al. Relationships between Mechanical Variables in the Traditional and Close-Grip Bench Press. J Hum Kinet. 2017;60:19–28. DOI 10.1515/hukin-2017-0109. PMID 29339982. | Close-grip and traditional bench differ mechanically; supports separate identity. | B |
| 19 | Herrera-Bermudo JC, Puente-Alcaraz C, Díaz-Sánchez P, González-Badillo JJ, Rodríguez-Rosell D. Influence of Grip Width on the Load-Velocity Relationship and 1RM in the Bench Press. J Strength Cond Res. 2024;38(12):2013–2021. DOI 10.1519/JSC.0000000000004920. PMID 39178098. | Grip width changes the load–velocity relationship and 1RM; equipment/execution changes break comparability. | B |
| 20 | Parkinson AO, Apps CL, Morris JG, Barnett CT, Lewis MGC. The Calculation, Thresholds and Reporting of Inter-Limb Strength Asymmetry: A Systematic Review. J Sports Sci Med. 2021;20(4):594–617. DOI 10.52082/jssm.2021.594. PMID 35321131. | Strength-ratio calculation, thresholds and reporting are inconsistent; supports no universal ratio target. | A |
| 21 | Impellizzeri FM, Tenan MS, Kempton T, Novak A, Coutts AJ. Acute:Chronic Workload Ratio: Conceptual Issues and Fundamental Pitfalls. Int J Sports Physiol Perform. 2020;15(6):907–913. DOI 10.1123/ijspp.2019-0864. PMID 32502973. | ACWR has conceptual and statistical problems; supports descriptive-only use. | E |
| 22 | Morán-Navarro R, Pérez CE, Mora-Rodríguez R, et al. Time course of recovery following resistance training leading or not to failure. Eur J Appl Physiol. 2017;117(12):2387–2399. DOI 10.1007/s00421-017-3725-7. PMID 28965198. | Failure slowed recovery of jump height and bar velocity at 24–48 h versus equal-volume non-failure sets. | B |
| 23 | Balachandran AT, Steele J, Angielczyk D, et al. Comparison of Power Training vs Traditional Strength Training on Physical Function in Older Adults: A Systematic Review and Meta-analysis. JAMA Netw Open. 2022;5(5):e2211623. DOI 10.1001/jamanetworkopen.2022.11623. PMID 35544136. | Power training modestly improves physical function vs traditional strength training in older adults (low certainty). Supports a separate power domain, but the population is older adults. | A |
| 24 | El Hadouchi M, Kiers H, de Vries R, Veenhof C, van Dieën J. Effectiveness of power training compared to strength training in older adults: a systematic review and meta-analysis. Eur Rev Aging Phys Act. 2022;19:18. DOI 10.1186/s11556-022-00297-x. PMID 35953775. | Power training improves muscle power (SMD 0.99) and activity tests in older adults. Same population caveat. | A |
| 25 | Swinton PA, Stewart A, Agouris I, Keogh JW, Lloyd R. A biomechanical analysis of straight and hexagonal barbell deadlifts using submaximal loads. J Strength Cond Res. 2011. DOI 10.1519/JSC.0b013e3181e73f87. | Trap bar produced lower peak lumbar, hip and ankle moments; supports a lower ordinal spinal cost than a straight bar. | D |
| 26 | Hanen NC, Ben Mansour K, Ertel GN, Duchene Y, Gauchard GC. Biomechanical analysis of conventional and sumo deadlift. Front Bioeng Biotechnol. 2025. DOI 10.3389/fbioe.2025.1597209. | Sumo had lower erector spinae activation and more upright posture but greater frontal/transverse moments; supports ordinal, not a load measurement. | D |
| 27 | Cholewicki J, McGill SM, Norman RW. Lumbar spine loads during the lifting of extremely heavy weights. Med Sci Sports Exerc. 1991;23(10):1179–1186. DOI 10.1249/00005768-199110000-00012. | Heavy deadlifting loads the lumbar spine; sumo reduced but did not remove the load. Supports "axial demand is real", not a per-exercise score. | D |
| 28 | Wiedenmann T, Kunellis D, Rappelt L, Held S, Wicker P, Donath L. Trainability of repetitions-in-reserve estimation in younger and older adults: a parallel-group repeated-measures study. BMC Sports Sci Med Rehabil. 2026;18(1):375. DOI 10.1186/s13102-026-01997-y. PMID 42632893. | RIR estimation error decreases with practice (up to ~2.3 reps); supports a buffer, not a tight veto. | B |
| 29 | Moura RE, Bezerra da Silva RF, Gomes LMS, Ramos da Silva JL, Henrique RDS, Sousa FAB, Fonseca FS. Monitoring Bar Velocity to Quantify Fatigue in Resistance Training. Int J Sports Med. 2024;45(8):624–632. DOI 10.1055/a-2316-7966. PMID 38684188. | Back-squat mean propulsive velocity was sensitive to acute fatigue, especially at 40% and 80% 1RM; supports velocity as context. | B |
| 30 | Refalo MC, Helms ER, Trexler ET, Hamilton DL, Fyfe JJ. Influence of Resistance Training Proximity-to-Failure on Skeletal Muscle Hypertrophy: A Systematic Review with Meta-analysis. Sports Med. 2023;53(3):649–665. DOI 10.1007/s40279-022-01784-y. PMID 36334240. | No hypertrophy advantage for momentary failure over non-failure; no advantage of >25% over 20–25% velocity loss. Supports not treating failure as mandatory. | A |

### 11.4 What the evidence does not establish

- No source validates a **composite 0–100 workout score**.
- No source validates **cross-exercise e1RM ratios** as a weakness diagnosis or a predictor of main-lift performance. The evidence supports specificity and descriptive profiling, not diagnosis.
- No source validates **session load AU** as an objective physiological stress or a precise recovery dose.
- No source validates **mean velocity per set** as a within-set velocity-loss measure.
- No source validates **RIR** as precise enough to compare 1-rep differences.
- No source validates **productivity** as a workload or a predictor; it is a product hypothesis.
- No source validates **spinal_cost** as lumbar compression/shear or as an injury probability.

### 11.4a Evidence gaps specific to this proposal

| Question | What exists | What is missing |
|---|---|---|
| Does a difference vs recent performance measure adaptation? | No. It is a re-estimate from a different set. Indirect context: bar velocity is sensitive to acute fatigue (Moura 2024), and RIR error is large (Zourdos 2021; Refalo 2024). | No study validates a difference vs recent performance as a meaningful change, and none establishes a minimal detectable change for Epley+RIR. The 4.2% direct-1RM CV is a literature reference, not a validated e1RM threshold; using it as one would confuse direct 1RM test–retest variability with formula-plus-RIR error. |
| Does an accessory-to-main ratio explain main-lift performance? | Specificity evidence (Spitz 2019; Lockie 2017; Herrera-Bermudo 2024) and ratio-reporting inconsistency (Parkinson 2021). | No prospective study showing that a ratio change predicts a main-lift change, or that targeting a ratio improves the main lift. |
| Does session load AU predict recovery or adaptation? | sRPE is a reliable internal-load rating (Sweet 2004; Day 2004). | No resistance-training study validates AU thresholds, a dose-response curve, or an individual recovery window. |
| Does power quality relate to adaptation? | Power training improves power/function in older adults (Balachandran 2022; El Hadouchi 2022); velocity loss has trade-offs (Jukic 2023). | No validated field metric for jump quality in this athlete, and no within-set loss from mean velocity. |
| Does spinal ordinal cost predict injury? | Biomechanical load is real (Cholewicki 1991; Swinton 2011; Hanen 2025). | No validated mapping from the ordinal cost to injury probability; no individual load threshold. |

### 11.5 Evidence-to-design trace

| Design choice | Basis | Evidence | What would change it |
|---|---|---|---|
| Keep domains separate | A | Scott 2016; Helms 2020; ACSM 2026 | A validated composite that outperforms separate interpretation |
| sRPE × duration as internal load | A/B | Sweet 2004; Day 2004 | Evidence that another internal-load measure is more valid and practical |
| Label immediate sRPE | B | Sweet 2004; Day 2004 | Adopting a delayed 30-minute capture with a timing field |
| e1RM as estimate, not measurement | A | Reynolds 2006; Mayhew 2008; Grgic 2020 | A test-anchored estimator with lower individual error |
| Monitoring series uses raw formula-derived e1RM; calibration/decay are load-base only | B/C | Epley convention; Grgic 2020; existing e1rm_calibration/e1rm_decay code | A validated calibration that can be applied consistently to all historical observations and displayed separately |
| 4.2% retained only as a direct-1RM literature reference | C (source grade A, but no threshold is a product decision) | Grgic 2020 | Repeated measured tests producing an individual error estimate; even then, no binary threshold is planned |
| Median of last 3 session bests as primary comparator | C | Engineering judgement; no direct trial | Prospective comparison showing another simple reference predicts better or is more interpretable |
| Best recent single session displayed separately | B/C | Measurement logic | Evidence that a best-performance reference is misleading or unused |
| Difference displayed descriptively, no classification | B/C | Grgic 2020 (source only); RIR error evidence | A validated individual error model; still no automatic significance label planned |
| RIR distribution, no mean | A/B | Zourdos 2021; Refalo 2024; Pelland 2022 | A validated RIR measurement method |
| Hard sets RIR ≤4 | B/C | Existing config; ACSM/Robinson | A validated per-athlete effort threshold |
| Relative-intensity bands | C (80% anchor A) | ACSM 2026 (80%); other cuts product judgement | Individual load–velocity/1RM data supporting different bins |
| Tonnage within exercise only | A/B | Mechanics; ACSM volume-load discussion | A validated cross-exercise common currency |
| Power separate, 30–70% 1RM, low volume | A | ACSM 2026; Balachandran 2022; El Hadouchi 2022 | Direct evidence in adult recreational lifters that contradicts the general prescription |
| Mean velocity change across sets, descriptive only | B/C | Moura 2024; Jukic 2023 | A validated quality metric with a known error model |
| No within-set velocity loss | B | DEC-VELOCITY-01; mean-only data | Per-rep velocity capture for the sets in question |
| Spinal ordinal, not load | A/D | Swinton 2011; Hanen 2025; Cholewicki 1991; SPINAL-COST | A validated individual load–tissue model |
| Ratios descriptive only | A/C | PARENT-VARIANT-WEAKNESS-EVIDENCE; Parkinson 2021; Spitz 2019 | Prospective evidence that a ratio predicts or explains main-lift performance |
| No fitness-fatigue controller | A/C | Marchal 2025; RETROSPECTIVE-VALIDATION | Out-of-sample improvement over simple baselines across lifts and periods |
| Productivity optional, subjective | C | No direct validation | Prospective evidence of a stable, useful relationship; still not a workload |

### 11.6 Direct links for the verified sources

- [ACSM 2026 overview of reviews](https://doi.org/10.1249/MSS.0000000000003897) · [PubMed 41843416](https://pubmed.ncbi.nlm.nih.gov/41843416/)
- [Sweet 2004, session RPE](https://doi.org/10.1519/14153.1) · [PubMed 15574104](https://pubmed.ncbi.nlm.nih.gov/15574104/)
- [Helms 2020, methods for regulating and monitoring](https://doi.org/10.2478/hukin-2020-0011) · [PubMed 33312273](https://pubmed.ncbi.nlm.nih.gov/33312273/)
- [Pelland 2022, proximity to failure](https://doi.org/10.1007/s40279-022-01667-2) · [PubMed 35247203](https://pubmed.ncbi.nlm.nih.gov/35247203/)
- [Robinson 2024, dose-response meta-regressions](https://doi.org/10.1007/s40279-024-02069-2) · [PubMed 38970765](https://pubmed.ncbi.nlm.nih.gov/38970765/)
- [Pareja-Blanco & Loturco 2026, level of effort](https://doi.org/10.5114/jhk/221229) · [PubMed 42211812](https://pubmed.ncbi.nlm.nih.gov/42211812/)
- [Sousa 2024, recovery in microcycle construction](https://doi.org/10.5114/jhk/186659) · [PubMed 38689583](https://pubmed.ncbi.nlm.nih.gov/38689583/)
- [Marchal 2025, statistical flaws of fitness-fatigue](https://doi.org/10.1038/s41598-025-88153-7) · [PubMed 39881202](https://pubmed.ncbi.nlm.nih.gov/39881202/)
- [Scott 2016, training monitoring for resistance exercise](https://doi.org/10.1007/s40279-015-0454-0) · [PubMed 26780346](https://pubmed.ncbi.nlm.nih.gov/26780346/)
- [Day 2004, session RPE scale](https://doi.org/10.1519/R-13113.1) · [PubMed 15142026](https://pubmed.ncbi.nlm.nih.gov/15142026/)
- [Grgic 2020, 1RM test-retest reliability](https://doi.org/10.1186/s40798-020-00260-z) · [PubMed 32681399](https://pubmed.ncbi.nlm.nih.gov/32681399/)
- [Zourdos 2021, intraset RIR accuracy](https://doi.org/10.1519/JSC.0000000000002995)
- [Refalo 2024, bench press RIR accuracy](https://doi.org/10.1519/JSC.0000000000004653) · [PubMed 37967832](https://pubmed.ncbi.nlm.nih.gov/37967832/)
- [Reynolds 2006, 1RM prediction](https://doi.org/10.1519/R-15304.1) · [PubMed 16937972](https://pubmed.ncbi.nlm.nih.gov/16937972/)
- [Mayhew 2008, bench press prediction equations](https://doi.org/10.1519/JSC.0b013e31817b02ad) · [PubMed 18714230](https://pubmed.ncbi.nlm.nih.gov/18714230/)
- [Jukic 2023, velocity-loss thresholds](https://doi.org/10.1007/s40279-022-01754-4) · [PubMed 36178597](https://pubmed.ncbi.nlm.nih.gov/36178597/)
- [Spitz 2019, front vs back squat load-velocity](https://doi.org/10.1519/JSC.0000000000002962) · [PubMed 30688871](https://pubmed.ncbi.nlm.nih.gov/30688871/)
- [Lockie 2017, traditional vs close-grip bench](https://doi.org/10.1515/hukin-2017-0109) · [PubMed 29339982](https://pubmed.ncbi.nlm.nih.gov/29339982/)
- [Herrera-Bermudo 2024, grip width and 1RM](https://doi.org/10.1519/JSC.0000000000004920) · [PubMed 39178098](https://pubmed.ncbi.nlm.nih.gov/39178098/)
- [Parkinson 2021, inter-limb asymmetry review](https://doi.org/10.52082/jssm.2021.594) · [PubMed 35321131](https://pubmed.ncbi.nlm.nih.gov/35321131/)
- [Impellizzeri 2020, ACWR pitfalls](https://doi.org/10.1123/ijspp.2019-0864) · [PubMed 32502973](https://pubmed.ncbi.nlm.nih.gov/32502973/)
- [Morán-Navarro 2017, recovery after failure](https://doi.org/10.1007/s00421-017-3725-7) · [PubMed 28965198](https://pubmed.ncbi.nlm.nih.gov/28965198/)
- [Balachandran 2022, power vs strength training](https://doi.org/10.1001/jamanetworkopen.2022.11623) · [PubMed 35544136](https://pubmed.ncbi.nlm.nih.gov/35544136/)
- [El Hadouchi 2022, power training review](https://doi.org/10.1186/s11556-022-00297-x) · [PubMed 35953775](https://pubmed.ncbi.nlm.nih.gov/35953775/)
- [Swinton 2011, straight vs hex bar](https://doi.org/10.1519/JSC.0b013e3181e73f87)
- [Hanen 2025, conventional vs sumo](https://doi.org/10.3389/fbioe.2025.1597209)
- [Cholewicki 1991, lumbar loads in heavy lifting](https://doi.org/10.1249/00005768-199110000-00012)
- [Wiedenmann 2026, RIR trainability](https://doi.org/10.1186/s13102-026-01997-y) · [PubMed 42632893](https://pubmed.ncbi.nlm.nih.gov/42632893/)
- [Moura 2024, bar velocity and fatigue](https://doi.org/10.1055/a-2316-7966) · [PubMed 38684188](https://pubmed.ncbi.nlm.nih.gov/38684188/)
- [Refalo 2023, proximity to failure and hypertrophy](https://doi.org/10.1007/s40279-022-01784-y) · [PubMed 36334240](https://pubmed.ncbi.nlm.nih.gov/36334240/)

### 11.7 Product assumptions register

These are the important **product/engineering assumptions** in this specification. They are not presented as physiological thresholds. Each must be registered as an ASSUMPTION-n at approval; the local IDs are for review.

| ID | Assumption | Why chosen | Evidence that would justify changing it |
|---|---|---|---|
| PA-01 | Load-base e1RM outer window 84 days; robust median window 28 days | About one mesocycle; matches the existing prescription selector; long enough to smooth one outlier, short enough to track form | Individual error/trend analysis showing a different window predicts or describes better |
| PA-02 | ok estimate: reps ≤10, RIR ≤3, reps+rir ≤20 | RIR error grows with distance from failure; a 20-rep extrapolation is not a strength estimate | Repeated measured tests with per-rep-range error estimates |
| PA-03 | Recent reference = median of last 3 session bests | Smallest sample that is not the latest value; robust to one outlier; explainable | Prospective comparison of 3 vs 5 observations or a simple time-series baseline |
| PA-04 | Relative-intensity bands <60/60–70/70–80/80–90/≥90% | 80% is anchored to the ACSM strength finding; the other cuts are display bins | Individual load–velocity/1RM data or a validated %1RM taxonomy |
| PA-05 | Ratio max gap 14 days | Short enough to represent the same training period at 2–3 sessions/week; long enough to occur | Paired-observation analysis showing 14 days is too short or too long |
| PA-06 | Ratio max age 42 days | Allows a recent observation while limiting staleness | Evidence that older observations still represent current performance |
| PA-07 | Ratio requires ≥2 eligible observations per side before display; fewer -> unavailable due to insufficient history | Data-sufficiency gate, not confidence; one observation is a single-session value and is not displayed as a ratio | Evidence that a different minimum is needed for a stable ratio |
| PA-08 | Ratio uses latest eligible per-session best per side | Transparent, date-stamped, no smoothing; avoids dividing independently smoothed series | Evidence that a recent median is more stable without hiding real change |
| PA-09 | Longitudinal trend = rolling median of last 3 observations | Simple, robust, observation-based; handles irregular spacing | Prospective comparison against last observation or a simple model |
| PA-10 | Comparable session: same type, ≥1 common main lift, ≥50% exercise overlap, ≥3 priors, 8-week window | Avoids comparing unlike sessions; still yields enough comparisons | Analysis showing the key is too strict or too loose |
| PA-11 | Hard set = working set with RIR ≤4 | Existing exposure config; broad enough to include hard work | A validated effort threshold or a change in RIR reporting behaviour |
| PA-12 | Late feedback = >24 h after a live workout; long session = >2× recent comparable median | Practical data-quality flags, not physiological rules | Data showing a different threshold identifies problematic feedback |
| PA-13 | Productivity is a 5-point labelled item | Consistent with the app's 1–5 scales; low friction | Cognitive testing or prospective evidence supporting a different scale |
| PA-14 | Mean velocity change requires the same exercise and load | Otherwise the comparison is uninterpretable | A validated method that adjusts for load/equipment changes |
| PA-15 | Degraded estimates are displayed but excluded from headline differences | Preserves transparency without pretending precision | An individual error model that quantifies degraded estimates |
| PA-16 | Repeated-test protocol: standardised 1RM/3RM assessments separated enough to avoid acute fatigue, same protocol, no training between; number/spacing to be pre-registered | Feasibility-dependent way to estimate within-athlete typical error; no validated minimum number of tests | Feasibility or reliability data showing a different spacing/count is needed; a larger sample may reduce uncertainty |
| PA-17 | Monitoring performance observations are raw formula-derived e1RM; age decay and calibration factor are not applied | Keeps historical and current observations on one method; decay/calibration are load-selection policies | A validated calibration that can be applied consistently to the whole historical series without creating artificial steps |

## 12. Validation methodology

### 12.1 Stage 1 — Measurement validity

Test that the calculations reflect the data. Required unit tests:

| Test | Setup | Expected |
|---|---|---|
| Warm-up exclusion | RIR 6 set + RIR 2 set | Warm-up excluded from working sets, e1RM, RI, hard sets; counted as warm-up |
| Working-set classification | RIR null + RIR 5 | Both working; RIR null contributes to unknown; RIR 5 not hard |
| RIR off-scale | RIR -1, 7, 99 | Classified missing/off-scale; not hard |
| Load basis | external / bodyweight_total / added / unknown | Correct total/external/tonnage; unknown → not applicable |
| Bodyweight missing | added-load set, no bodyweight | e1RM/RI unavailable; set still counts |
| e1RM eligibility | 20 reps + RIR 5 | Rejected for headline (reps+rir >20) |
| e1RM eligibility | 11 reps @ RIR 2 | Degraded; not headline |
| e1RM eligibility | 3 reps @ RIR 0 | ok, flagged suspect |
| Raw performance series | Same session with/without a calibration factor or age decay | recent_reference, best_recent, personal_best, post_best and difference unchanged |
| Load-base separation | Same session, load base recomputed | load_base may change with calibration/decay; performance series does not |
| Reference cutoff | Compute recent reference, then add current sets, recompute | Reference unchanged |
| Same-date ordering | Two workouts same date, one earlier start | Earlier included; later not |
| Post source | Two eligible sets | Best selected; source set correct |
| Post missing | Only warm-up/unknown RIR | Unavailable, not 0 |
| Recent reference count | 0, 1, 2, 3 eligible session bests | unavailable, single_prior, limited, descriptive respectively |
| Degraded post | Post estimate degraded | insufficient_quality; both estimates shown with labels; no difference |
| No threshold classification | Any difference value | Only descriptive/limited/single_prior/insufficient_quality/unavailable; never clear/meaningful/within typical |
| Ratio method | Latest per side, dates, gap and counts | Latest values used; dates/counts visible; ≥2 per side; gap/age/degraded gates applied |
| Ratio insufficient history | Either side has 1 observation | ratio unavailable due to insufficient history; estimates/dates shown |
| Velocity quality | 0.000000 | velocity_present = false; not a measurement |
| Power exclusion | Box jump set | Not in RIR/RI/hard-set counts; counted in power |
| Substitution | Plan A, actual B | Completion against modified plan; original comparison shows A missing; no e1RM mapping |
| Partial workout | 3/4 sets | Status under; no zero dose |
| Missing feedback | No feedback row | Session load unknown; not 0 |
| Feedback merge | Row 1 sRPE+duration, row 2 sRPE only | sRPE from row 2, duration from row 1; flag |
| Manual duration | duration_source=manual | Session load computed; manual flag |
| Ratio gap | 40-day gap | Unavailable/historical; no current ratio |
| Ratio one-sided | Missing denominator | Unavailable |
| Spinal reuse | Session with 3 spinal exercises | Effective cost equals registry output |
| No composite | API payload | No score, workload, fatigue or quality scalar added |

Representative edge cases: empty session, one-set session, all-warm-up session, all-RIR-missing session, bodyweight-only session, test-only session, timed-only session, session with a 1015-rep typo (quarantined/flagged), session with a 0 load on an external lift, session with a negative load (invalid).

### 12.2 Stage 2 — Construct validity

Check that each metric behaves like what it claims:

- **External dose** changes only when completed working sets/reps/load change; it is invariant to prescribed changes.
- **Internal load** changes with sRPE and duration, and is independent of tonnage (except through perception).
- **e1RM estimates** change when the underlying raw session-best observations change; the difference is a derived descriptive value, not a significance label. It is invariant to unrelated exercises, calibration factors and age decay, and does not change when only the plan changes.
- **Relative strength** changes only when one of the two configured raw e1RMs changes; it is unavailable when either is stale, degraded or has fewer than 2 observations.
- **Power exposure** counts only power-classified sets; it does not increase hypertrophy hard sets.
- **Axial/spinal exposure** equals the registry output; it is invariant to tonnage.
- **Productivity** is independent of every objective metric in the payload; it is not used in any calculation.

Add a **negative test**: search the API/UI payload for a composite key and assert absence. This is a permanent guardrail.

### 12.3 Stage 3 — Predictive validity

Only if a metric is claimed to predict. Requirements:

- chronological out-of-sample validation (walk-forward), never random splits;
- baselines: last eligible observation, rolling median of 3, comparable-session median, exercise-specific mean;
- report n, missingness, horizon, MAE (and RMSE/bias if useful), baseline comparison, stability across exercises and time periods;
- a complex model is retained only if it materially and consistently beats the baseline; "materially" must be defined before the analysis (e.g., ≥10% MAE reduction and no exercise with a worse result);
- no causal claims;
- no automatic prescription change.

The existing RETROSPECTIVE-VALIDATION.md and fatigue_fitness backtest are the precedent: a model that loses to persistence is not adopted.

### 12.4 Stage 4 — Prospective validation

Before any metric influences programming, collect prospectively:

- 12–16 weeks of sessions with sRPE, duration and productivity (duration is a feasibility assumption, not a validated minimum);
- measured 1RM/3RM/5RM tests for the main lifts where feasible; the number is a feasibility-dependent assumption, not a validated minimum;
- power quality-stop events and, where available, per-rep velocity;
- exercise substitutions and interruptions;
- a pre-registered analysis plan with a primary outcome and a small number of exposures.

Do not change prescriptions, deloads, exercise selection or injury rules during this period. Do not peek and adjust the plan without recording it.

### 12.5 Acceptance criteria for the measurement layer

- All Stage 1 tests pass.
- No existing golden prescription changes.
- No new composite scalar in any API response.
- Every "unavailable" state is rendered as such, not as 0.
- Every headline estimate exposes its method and source.
- Degraded estimates never enter a headline difference.
- No automatic clear/meaningful/significant/within-typical classification exists for any e1RM difference.
- The recent reference requires 3 eligible session observations for a descriptive comparison; 2 is limited; 1 is single_prior; 0 is unavailable.
- The performance series is raw formula-derived; no age decay or calibration factor is applied.
- A ratio is displayed only when both sides have at least 2 eligible observations; otherwise it is labelled unavailable due to insufficient history.
- ruff check . and python -m pytest pass at the end of the phase.

---

## 13. Phased implementation roadmap

### Phase 0 — Retrospective data and estimator audit

**Scope**

Before building the monitoring UI or introducing any new calibration behaviour, audit the existing training dataset and establish what can genuinely be learned from it. This is a retrospective descriptive audit, not a validation study.

**A. Data audit**

Inspect existing historical records and report:

- sessions and sets per canonical exercise;
- distribution of repetitions and recorded RIR;
- coverage of RIR, load basis, equipment and exercise identity;
- eligible e1RM observations by exercise and rep range;
- the number of genuinely measured 1RM/3RM tests, if any;
- whether measured tests can be linked reliably to the formula-derived estimate available before the test;
- changes in variants, equipment, technique or data-entry conventions that break comparability.

Do not assume measured tests exist; establish this from the records.

**B. Formula-derived e1RM behaviour**

Using existing history:

- report observation coverage by lift, rep range and RIR;
- examine the distribution and stability of session-best raw estimates;
- compare the last-observation baseline, the rolling median of three session bests and other simple descriptive baselines;
- identify sensitivity to RIR, rep range, outliers and exercise/equipment changes;
- examine whether the proposed eligibility and quality rules leave enough observations for useful monitoring;
- identify data-quality issues or historical changes that could create artificial trends.

This is a descriptive audit. Ordinary training records do not provide a true 1RM criterion merely because an e1RM can be calculated from them.

**C. Measured tests where genuinely available**

If valid measured tests exist:

- compare the formula-derived estimate available before the test with the measured result;
- report per-lift bias, MAE and, where appropriate, MAPE;
- report sample size, rep-range coverage and limitations;
- use chronological validation where the sample permits; do not randomly split observations;
- do not fit a correction factor to a tiny sample;
- do not use the same observations both to fit and to claim independent validation.

If measured tests are absent or insufficient, report that criterion-based individual calibration is not currently possible. Do not manufacture a substitute criterion from ordinary training sets.

**D. Deliverable and gate**

Deliverable: a reproducible report, for example docs/MONITORING-HISTORICAL-AUDIT.md, containing data coverage, analysis methodology, results, limitations and recommendations. It is generated from existing data without changing historical training records.

If repository data-access or privacy constraints make a committed report unsuitable, specify a local-only report workflow and keep private athlete data out of Git.

The report informs whether any calibration, quality rule or estimator needs reconsideration. It must not automatically introduce a fitted correction factor. Phase 0 must precede implementation of the monitoring UI. It must not become a reason to delay basic descriptive metrics indefinitely: if criterion calibration is unavailable, implement the measurement layer with transparent limitations.

**Dependencies**

- Existing clean_set/session data and existing measured-test records, if any.
- No new capture.

**Files**

- New: tools/monitoring_historical_audit.py; tests/test_monitoring_historical_audit.py.
- New report: docs/MONITORING-HISTORICAL-AUDIT.md if public-safe, or a local-only equivalent.

**Schema changes**

- None.

**Testing**

- Audit is deterministic and read-only.
- No historical training record is modified.
- Counts reproduce from the stated SQL/filters.
- The report states the exact filters and joins used.

**Acceptance criteria**

- Data coverage and missingness are reported by exercise and rep range.
- Eligible e1RM observations and measured-test counts are established, not assumed.
- Simple baselines are compared.
- Limitations and data-quality issues are explicit.
- No fitted correction factor is introduced automatically.
- The report recommends whether monitoring can proceed descriptively, and with what caveats.

**Scientific limitations**

- Retrospective, observational and descriptive.
- Ordinary training sets are not a criterion.
- No causal or validated predictive claim is made.
- Small samples and changing exercise identity limit inference.

### Phase 1 — Definitions and shared measurement core

**Scope**

- Extract the prescription e1RM selector (load base) into features/e1rm_source.py.
- Add a separate raw formula-derived session-best estimator for monitoring; do not apply decay or calibration to it.
- Add features/monitoring.py pure definitions and config/monitoring.v1.yaml.
- Add config/strength-relationships.v1.yaml (config only; no UI).
- Add conformance fixtures and Stage 1 tests.
- No user-visible feature, no migration.

**Dependencies**

- Phase 0 completed and reviewed.
- Agreement on §4–§8 definitions.
- Existing clean_set columns; no new data.

**Files**

- New: strength_coach/features/e1rm_source.py, strength_coach/features/monitoring.py, config/monitoring.v1.yaml, config/strength-relationships.v1.yaml, tests/test_monitoring_definitions.py, tests/test_e1rm_source_shared.py.
- Modified: strength_coach/prescribe/engine.py (import the shared selector; behaviour-preserving), strength_coach/features/derived.py (add the reps+rir guard for the monitoring path only, or a separate helper), strength_coach/features/progress.py (fix e1rm_applicable if the shared selector is used there).

**Schema changes**

- None.

**Testing**

- All existing e1RM/calibration/prescription tests.
- New tests for eligibility, cutoff, quality, missingness, and no-composite.
- Property test: recent reference invariant to current-session sets.

**Acceptance criteria**

- Golden prescriptions byte-identical.
- The shared load-base selector reproduces _latest_e1rm for the same inputs.
- The raw monitoring estimator is separate and applies no decay or calibration.
- Every metric has a definition, status and flag in the config.
- ruff and tests pass.

**Scientific limitations**

- Bands, windows and quality cuts are assumptions; register them (PA-01 to PA-17).
- No meaningful-change threshold is implemented; 4.2% is a direct-1RM literature reference only.

### Phase 2 — Descriptive workout summary

**Scope**

- API GET /api/workout/<id>/summary and CLI summary.
- UI sections 1, 2, 3, 5, and a condensed 4.
- Raw recent reference, raw post best, descriptive difference vs recent performance, relative intensity, RIR distribution, hard sets, tonnage per exercise, session load AU.
- Optional productivity (see migration).

**Dependencies**

- Phase 1.
- Decision on productivity and on the 30-min sRPE protocol.

**Files**

- New: strength_coach/features/session_summary.py (or in monitoring), strength_coach/web/static/summary.js, tests/test_session_summary.py, tests/test_web_summary.py.
- Modified: strength_coach/web/server.py, strength_coach/cli.py, strength_coach/workout.py (plan JSON fields), strength_coach/web/static/workout.js (end form + render), strength_coach/web/static/index.html (markup), strength_coach/features/session_feedback.py (merge/productivity).

**Schema changes**

- ALTER TABLE session_feedback ADD COLUMN productivity INTEGER with CHECK (productivity IS NULL OR productivity BETWEEN 1 AND 5), if Domain G is approved. This is the only migration.
- If the 30-min protocol is adopted, add srpe_timing; otherwise do not.

**Testing**

- API contract, missing data, source transparency, recent-reference count, degraded policy, no threshold classification, manual duration, late feedback, productivity skip, no composite.
- UI rendering tests for "Unavailable"/"Not recorded".

**Acceptance criteria**

- The summary is read-only and deterministic.
- Every number is traceable to a set, feedback row or registry call.
- Performance estimates are raw formula-derived; no decay/calibration is applied.
- Any ratio shown requires at least 2 eligible observations per side; otherwise it is unavailable due to insufficient history.
- No automatic prescription change.
- The existing end-screen comparison is preserved.

**Scientific limitations**

- The difference vs recent performance is descriptive, not acute strength change or adaptation.
- Session load is internal, not objective stress.
- Tonnage is exercise-specific.
- Power quality is not measurable from mean velocity.

### Phase 3 — Historical strength and workload trends

**Scope**

- Performance view: raw e1RM series, rolling median, exercise filters, series breaks.
- Dose trends: hard sets, relative intensity, tonnage per exercise, session load.
- Accessory-to-main ratios (configured, latest raw observation per side, ≥2 per side, date-stamped).
- Comparable-session comparison.
- CLI performance with parity.

**Dependencies**

- Phase 2.
- Relationship config approved.

**Files**

- New: strength_coach/features/strength_trend.py, strength_coach/features/relative_strength.py, strength_coach/web/static/performance.js, tests/test_strength_trend.py, tests/test_relative_strength.py.
- Modified: web/server.py, cli.py, index.html, app.js (navigation).

**Schema changes**

- None.

**Testing**

- Sparse data: 1, 2, 3, 5 points.
- Series break on identity/equipment change.
- No interpolation.
- Ratio gap/staleness/one-sided/degraded/insufficient-history; latest-observation method.
- No target ratio, no ranking, no confidence label from n alone.

**Acceptance criteria**

- Trend lines only with ≥3 observations.
- No statement of change with <5 observations.
- Ratio unavailable when dates are too far apart, either side is degraded, or either side has fewer than 2 observations; insufficient history shows estimates/dates but no ratio.
- Every ratio displays both dates, both estimates, per-side counts and data sufficiency (not confidence).

**Scientific limitations**

- Rolling median is descriptive, not a model; 3 observations is a product assumption.
- Ratios have no diagnostic validity.
- Cross-exercise comparisons are limited by specificity.

### Phase 4 — Exploratory modelling

**Scope**

- Descriptive dose–response and recovery associations.
- Document the repeated-measured-test error protocol (see §4.4 C4); do not implement a threshold.
- Pre-registered, small set of exposures/outcomes.
- Reports, not controllers.
- Compare against simple baselines.

**Dependencies**

- Phase 3; enough data; a written pre-registration.

**Files**

- New: tools/monitoring_analysis.py (or a features/monitoring_analysis.py), docs/MONITORING-ANALYSIS.md (result report, when run).
- No UI or prescription changes.

**Schema changes**

- None.

**Testing**

- Unit tests for lag construction, missingness, baseline comparison.
- Reproducible output with a seed.

**Acceptance criteria**

- n, missingness, effect size and uncertainty reported.
- No causal language.
- No model retained without out-of-sample improvement over baselines.
- No automatic change.

**Scientific limitations**

- Observational; confounding; multiple comparisons; short series.

### Phase 5 — Prospective validation

**Scope**

- Collect the data needed to validate the metrics before any programming influence.
- Pre-register the analysis.
- No feature changes beyond capture.

**Dependencies**

- Phase 4; a decision that a metric is a candidate for prediction.

**Files**

- Capture changes only if justified: session_feedback.srpe_timing, structured power quality event, per-rep velocity capture.
- Conduct repeated standardised 1RM/3RM/5RM tests for the main lifts where feasible and record them through the existing measured-test path; do not prescribe a validated minimum number.
- docs/MONITORING-PROSPECTIVE.md (protocol and results).

**Schema changes**

- Only if a capture gap is proven (e.g., sRPE timing, structured quality stop). Do not add speculative fields.

**Testing**

- Capture completeness; no default values; no missing-to-zero.
- Analysis reproduces the pre-registered plan.

**Acceptance criteria**

- 12–16 weeks of prospective data.
- Pre-registered primary outcome.
- Out-of-sample comparison against baselines.
- No programming change until the gate is met.

**Scientific limitations**

- One athlete; N-of-1; limited generalisability.
- Prospective data collection changes behaviour (Hawthorne effect).

### Deferred phases/features

- Velocity-loss-based autoregulation.
- Injury-risk prediction.
- Automatic deload/prescription changes.
- Population percentile comparisons.
- A universal score.
- Complex forecasting.
- Jump height/contact time (unless a device is added and the question is pre-registered).

---

## 14. Open design decisions and unresolved questions

| # | Decision | Options | Recommendation | Evidence | Revisit if |
|---|---|---|---|---|---|
| Q1 | Primary recent comparator | historical max / last session / median of last 3 / median of last 5 | **Median of last 3 eligible per-session bests**, with best-recent and all-time best kept separate | Engineering judgement; no direct trial | Prospective data show another simple reference is more stable or interpretable |
| Q2 | Meaningful-change rule | none / individual error model / validated minimal detectable change | **None initially**; display descriptively; develop an individual error estimate from repeated measured tests | Grgic 2020 is direct-1RM only; its 4.2% is not transferable to estimated e1RM | Repeated-test data produce a defensible individual error model |
| Q3 | Ratio observation, gap and minimum history | latest per side / recent median / best in window / smoothed | **Latest eligible per-session best per side**, at least 2 observations per side, gap ≤14 days, max age 42 days; recent median only as a sensitivity check | Product judgement; PARENT-VARIANT evidence | Paired data show the latest method is too noisy, the minimum is wrong, or the gap is wrong |
| Q4 | Productivity scale | 5-point / 7-point / free text | **5-point labelled**, optional | Product judgement | Users find it ambiguous |
| Q5 | sRPE timing | immediate / 30 min / both | **Keep immediate, label it; add delayed later** | Sweet 2004; Day 2004 | Friction data show a delayed value is feasible |
| Q6 | Session tonnage total | hide / advanced / headline | **Advanced only**, with a caveat | Mechanics; ACSM | Users need a total for a specific comparison |
| Q7 | Ratios on the end screen | none / 2 / all | **Max 2, only if data-sufficient and both sides ok** | PARENT-VARIANT evidence | The Performance view is enough |
| Q8 | Performance view location | new page / Outcomes / Today | **New top-level Performance page** | UI complexity | The page becomes too large |
| Q9 | Persist derived metrics | yes / no | **No**, recompute; cache in memory only | Single source of truth | Performance becomes a problem |
| Q10 | Same-date multiple sessions | include / exclude | **Include only with a proven earlier start**, else exclude | No timestamps for imports | Timestamps are captured for all sessions |
| Q11 | Tests in the e1RM series | include / separate | **Include as observations, mark as test**; do not mix with ordinary volume | ACSM; high-intensity plan | Tests distort the trend |
| Q12 | RIR 5 | hard / not hard / unknown | **Not hard; keep as a working set** | DQ-RIR-03 | The athlete confirms a different meaning |
| Q13 | Relative intensity for accessories | show / hide | **Show when a load base exists**, else "unavailable" | ACSM | Accessory data are too sparse |
| Q14 | Bodyweight total for added | fix read / leave | **Fix the read path** before bodyweight e1RM | DEC-LOAD-02 | No bodyweight e1RM is ever used |
| Q15 | Power quality stop | infer from velocity / require event | **Require an event; no inference** | DEC-POWER-02 | A validated velocity rule exists |
| Q16 | Comparable-session key | date / type+lift / type+lift+overlap | **Type + common main lift + overlap + exclusions** | Product judgement | Too few comparisons |
| Q17 | Productivity in analysis | no / descriptive only | **Descriptive only** | No validation | Prospective data support a hypothesis |
| Q18 | Warm-up display | hide / count | **Count separately**, never in dose | DEC-RIR-01 | None |
| Q19 | e1RM display precision | 0.1 / 0.5 / integer | **0.5 kg** | Measurement error | None |
| Q20 | Late feedback threshold | 24 h / 7 days / none | **24 h for live workouts**, N/A for imports | Product judgement | Data show a different pattern |
| Q21 | Degraded estimate display | hide / show with label / use in difference | **Show with label; never in headline difference**; if either side degraded, insufficient_quality | Engineering decision | An individual error model quantifies degraded estimates |
| Q22 | Mean velocity change across sets | hide / descriptive / quality score | **Descriptive only**, same exercise and load; never a quality or retention score | Engineering decision; Moura 2024 | A validated quality metric with known error |
| Q23 | Raw vs calibrated/decayed performance series | raw / calibrated / decayed / mixed | **Raw formula-derived** for all monitoring performance observations; calibration and decay remain load-base only | Epley convention; Grgic 2020; existing e1rm_calibration/e1rm_decay code | A validated calibration that can be applied consistently to the entire historical series without artificial steps |

---

## 15. Features that should NOT be implemented yet

The following are explicitly **out of scope** and should be rejected in review unless new evidence and a new decision record appear.

1. **A universal 0–100 workout effort, workload, quality, stimulus or fatigue score.** No validation; would combine incommensurable constructs.
2. **A composite readiness/fatigue/performance score.** Readiness already exists as a bounded heuristic; do not multiply constructs.
3. **ACWR-based injury-risk prediction or a "sweet spot" recommendation.** The project already rejected this (DEC-ACWR-01, DEC-EXPOSURE-02); the ratio stays descriptive.
4. **Automatic prescription changes** from any new metric: load, sets, RIR, deload, exercise selection or substitution.
5. **A "strength gain" or "acute strength change" label for a difference vs recent performance.** It is a descriptive difference of estimates, not adaptation.
6. **A "weakness" diagnosis from an accessory-to-main ratio.** Ratios are descriptive relative performance.
7. **Universal target ratios or population percentiles.** No validated individual targets.
8. **Cross-exercise e1RM conversion** (trap bar ↔ sumo ↔ conventional; SSB ↔ competition squat; bench ↔ close-grip). Identity is explicit.
9. **Within-set velocity loss from mean velocity.** Not computable; DEC-VELOCITY-01.
10. **RIR inference from velocity, reps or RPE.** No validated per-set conversion; do not impute.
11. **A "quality-limited" power claim without a recorded quality stop.** Mean velocity alone is insufficient.
12. **A measured spinal load (newtons, compression, shear) or an injury probability.** The ordinal cost is not a measurement.
13. **Aggregating tonnage across unrelated exercises into a universal workload.** Exercise-mix dependent.
14. **Treating a test/max attempt as ordinary hypertrophy volume.** It is a separate exposure.
15. **Productivity as a workload, stimulus, readiness or prescription input.** It is a subjective single item.
16. **A complex fitness-fatigue or machine-learning forecast.** The existing model was rejected; Marchal 2025 documents the statistical problems.
17. **A population benchmark or "normal range" for e1RM, ratios or session load.** The app is for one athlete.
18. **A ranking of exercises by tonnage or "effectiveness".** Mechanics and load basis differ.
19. **A session "completion score"** beyond the existing status counts. Completion is descriptive.
20. **A new database table for derived metrics, ratios or summaries.** Compute on read; avoid a second source of truth.
21. **A required new wearable/telemetry integration.** Optional per-rep velocity exists; do not make it mandatory.
22. **A change to the rubric weights or composite** to accommodate monitoring. Keep the rubric separate.
23. **A change to the volume ledger landmarks** based on the new metrics. They remain config assumptions.
24. **A change to the spinal cap** based on the new metrics. It remains an ordinal guard.
25. **Any automatic clear/meaningful/significant/within-typical classification of an e1RM difference.** No threshold is implemented; the 4.2% figure is a direct-1RM literature reference only.
26. **A mean-velocity "retention" or power-quality score.** The calculation is descriptive only and cannot attribute cause.
27. **An ICC-based N-of-1 reliability estimate or an automatic typical-error/CV threshold.** ICC is unsuitable for one athlete; small-sample CV is too uncertain to act as a threshold.

---


## 16. Worked numerical examples

All examples are synthetic. They use the Epley+RIR convention load × (1 + (reps + rir)/30), rounded for display only.

### 16.1 Relative intensity

Inputs:

- load_base_e1rm (competition squat, median 28-day, decayed) = **150.0 kg**.
- Set A: 120 kg × 5 @ RIR 2.
- Set B: 127.5 kg × 4 @ RIR 1.
- Set C: 105 kg × 8 @ RIR 3.

Calculation:

- A: 120 / 150 = 0.800 = **80.0%** → heavy.
- B: 127.5 / 150 = 0.850 = **85.0%** → heavy.
- C: 105 / 150 = 0.700 = **70.0%** → moderate.

Interpretation: three of three working sets have a denominator; distribution 2 heavy, 1 moderate, 0 unknown. Do not say "average intensity 78.3%" unless you also show the distribution; the average hides the range and weights sets equally. Do not use a best recent single-session estimate (for example 158.4) as the denominator; that would produce different percentages and would not match the load base the prescription used.

### 16.2 Session load

Inputs: sRPE = **7**, duration = **65 min**.

Calculation: 7 × 65 = **455 AU**.

Interpretation: internal load, arbitrary units, same athlete only. If duration is missing, the result is **unknown**, not 0. If sRPE is missing, **unknown**. If the feedback was recorded 3 days later, still 455 AU with FEEDBACK_LATE; do not "correct" it. If duration is 130 min (unusually long), 910 AU with LONG_SESSION; no automatic adjustment.

### 16.3 Hard-set classification

Working sets: RIR 2, 3, 4, 5, missing.

- Hard sets (RIR ≤ 4): **3** (RIR 2, 3, 4).
- Near-failure sets (RIR ≤ 2): **1**.
- Unknown: **1** (the missing RIR).
- RIR 5: not hard.
- A warm-up RIR 6 is excluded from the working set count entirely.

If all five had missing RIR, the hard-set result is **unknown**, not 0. If the session had five working sets all at RIR 5, the hard-set result is a valid **0**, with RIR 5 sets shown.

### 16.4 Recent reference and descriptive difference

All values in this example are **raw Epley+RIR estimates**. No age decay and no calibration factor are applied to the performance series.

Synthetic session-level best observations for the bench press before the current session:

- 2026-10-14: 130 kg × 4 @ RIR 2 → 130 × (1 + 6/30) = 156.0 kg (ok).
- 2026-10-18: 135 kg × 3 @ RIR 2 → 135 × (1 + 5/30) = 157.5 kg (ok).
- 2026-10-23: 132 kg × 4 @ RIR 2 → 132 × (1 + 6/30) = 158.4 kg (ok).

recent_reference = median(156.0, 157.5, 158.4) = **157.5 kg**; n = 3; dates span 9 days.
best_recent_e1rm = **158.4 kg** (a separate best-performance reference, not the baseline).

Current session:

- 140 kg × 3 @ RIR 1 → 140 × (1 + 4/30) = 158.67 → **158.7 kg** (ok).
- post_best = 158.7 kg.

Difference vs recent performance:

- Absolute: 158.7 − 157.5 = **+1.2 kg**.
- Percentage: 1.2 / 157.5 × 100 = **+0.76%**.
- Status: **descriptive** (both ok; n = 3).
- Display: "Today's best estimate was 1.2 kg (0.8%) higher than the recent reference (median of 3 sessions, 14–23 Oct). Descriptive difference; measurement error not established for this lift."
- Do not say "strength increased", "clear increase", "within typical variation" or "adaptation".

A larger descriptive difference, still not a verdict:

- Post 150 kg × 2 @ RIR 1 → 165.0 kg.
- Difference = +7.5 kg; +4.76%.
- Display the number and the observation dates. Do not label it significant or meaningful. Do not use 4.2% as a cutoff.

A lower value:

- Post 135 kg × 2 @ RIR 2 → 135 × (1 + 4/30) = 153.0 kg.
- Difference = 153.0 − 157.5 = −4.5 kg; −2.86%.
- Display descriptively; possible explanations include fatigue, set selection, RIR error, technique, equipment and readiness. Do not say "lost strength".

Degraded estimate:

- Post 100 kg × 15 @ RIR 5 → 15 + 5 = 20; reps >10 and RIR >3 → **degraded**.
- Show the estimate with the degraded label; difference status = **insufficient_quality**; do not compute a headline difference. Do not substitute another set.

Sparse reference:

- Only 2 prior session bests → status **limited**; show the median and the difference, but label "limited recent observations; not a trend".
- Only 1 prior session best → status **single_prior**; show the value and date; no difference.
- No prior session best → **unavailable**.

### 16.5 Difference examples and status

The formula is in §16.4. The table is descriptive; no row is a significance test.

| Case | Recent reference | Post | Δ kg | Δ % | Status |
|---|---:|---:|---:|---:|---|
| Descriptive, n=3 | 157.5 | 158.7 | +1.2 | +0.76% | descriptive |
| Descriptive, larger difference | 157.5 | 165.0 | +7.5 | +4.76% | descriptive |
| Descriptive, lower | 157.5 | 153.0 | −4.5 | −2.86% | descriptive |
| Limited, n=2 | 157.5 | 158.7 | +1.2 | +0.76% | limited |
| Single prior, n=1 | 158.4 | 158.7 | — | — | single_prior (no difference) |
| Degraded post | 157.5 | 158.7 (degraded) | — | — | insufficient_quality |
| No reference | — | 158.7 | — | — | unavailable |
| No post | 157.5 | — | — | — | unavailable |

Do not add a "clear", "meaningful", "significant" or "within typical" column. Do not use a fixed percentage threshold.

### 16.6 Exercise-specific tonnage

Bench press working sets:

- 120 kg × 5 = 600 kg
- 125 kg × 4 = 500 kg
- 110 kg × 8 = 880 kg
- Total = **1,980 kg**

Pull-up with added load:

- +10 kg × 8 = **80 kg** tonnage (not (bodyweight + 10) × 8).
- If bodyweight is 80 kg, total mass is 90 kg; e1RM/relative intensity use 90 kg, tonnage uses 10 kg.

Do not add 1,980 kg (bench) to a squat tonnage and call it "session workload". If a total is shown, label it and restrict comparisons to similar exercise mixes.

### 16.7 Accessory-to-main-lift ratio

All e1RM values are **raw Epley+RIR estimates**. No age decay or calibration factor is applied.

Inputs:

- Front squat latest eligible session best: 100 kg × 5 @ RIR 2 → 100 × (1 + 7/30) = 123.33 → 123.3 kg, date 2026-10-20; 2 observations.
- Competition squat latest eligible session best: 140 kg × 3 @ RIR 2 → 140 × (1 + 5/30) = 163.33 → 163.3 kg, date 2026-10-23; 4 observations.

Calculation: 100 × 123.3 / 163.3 = **75.5%**.

Dates: gap = 3 days ≤ 14; both within 42 days; both ok; both have at least 2 observations → **data sufficiency: available** (not "confidence"). Display both dates and n.

Sensitivity check (optional): if the recent medians were front squat 120.0 kg and competition squat 160.0 kg, the recent-median ratio would be 75.0%. Show it only as a side-by-side sensitivity check when both sides have at least 3 observations; the primary ratio remains the latest-observation ratio.

Do not say "the front squat is 75.5% of the competition squat, therefore the quads are weak". Do say "the ratio of the two estimates is 75.5%; both are estimates and the ratio is descriptive".

If the denominator were 2026-09-01, the gap would be 49 days > 14 → **stale_or_gap** as a current ratio; show it as historical with both dates, or withhold it. Do not divide a recent numerator by an old denominator without a warning.

If either side has exactly 1 eligible observation → **unavailable due to insufficient history**; show the available estimate and date, but do not display a ratio. If either side has 0 observations or a missing estimate → **unavailable**.

If either side is degraded → **insufficient_quality**; show both estimates with their labels and no ratio.

Do not independently smooth the two series and divide the smoothed values. For a historical trend, use paired observations whose dates are within the gap window.

### 16.8 Power exposure and mean velocity change

Inputs: box jump 3 × 5, mean velocities 2.10, 2.05, 1.98 m/s; same exercise and load.

- Power sets = **3**.
- Explosive repetitions = **15**.
- Mean velocity change across sets = 100 × (1.98 − 2.10) / 2.10 = **−5.7%**.
- Within-set loss: **unavailable** (mean only).
- Quality stop: if no explicit event, **not recorded**. Do not infer "quality maintained" or "quality lost" from the change.
- Label: "mean velocity change across sets; descriptive only; rest, technique, readiness and noise may explain it". Do not call it retention or a power-quality score.

If per-rep data exist (2.20, 2.10, 2.00, 1.90, 1.75), first-to-last loss = (2.20 − 1.75) / 2.20 = 20.5%; this is descriptive, not an RIR proxy and not a quality score.

Do not count the 15 reps as 15 hypertrophy working sets. They are power exposure and, where the weekly ledger already includes power_jump, they count in that group.

### 16.9 Spinal exposure

Session: trap bar 4 sets, back extension 3 sets, competition squat 3 sets.

- Base ordinal costs: trap bar 2, back extension 1, competition squat 1.
- The registry applies bounded set-count and intensity policy factors; do not recompute them by hand.
- Suppose the registry returns effective costs 2.00, 0.85, 0.85 → session total **3.70**; weekly total **3.70 / 6.0**.
- Label: "ordinal exposure units, not lumbar load".
- Do not add tonnage or set counts to this number.

---

## 17. Traceability table

| Metric | Purpose | Source data | Calculation | Existing implementation / gap | Evidence | Validation | UI |
|---|---|---|---|---|---|---|---|
| Completed working sets | How much was done | clean_set | Count working rows | _comparison has counts; no monitoring card | ACSM volume | Stage 1 | Card 1 |
| Completed reps | Volume | clean_set | Sum reps (reps unit) | Partial in comparison | ACSM volume | Stage 1 | Card 1 |
| Exercise tonnage | Within-exercise load | clean_set.tonnage_kg | Sum external × reps | session.tonnage_kg exists; no per-exercise display | Mechanics; ACSM | Stage 1/2 | Card 3 |
| Session tonnage | Optional context | clean_set | Sum A1.3 | Session column exists | Mechanics | Stage 2 | Advanced |
| Hard sets | Effort dose | clean_set.rir | Count RIR ≤4 | exposure._hard (private) | ACSM; Robinson | Stage 1 | Card 3 |
| Near-failure sets | Proximity | clean_set.rir | Count RIR ≤2 | Gap | RIR evidence | Stage 1 | Card 3 |
| Pattern distribution | Balance | taxonomy, volume keys | Count by group | volume.compute | Volume evidence | Stage 1 | Card 3 |
| Load-base e1RM | Intensity denominator | clean_set, overrides, calibration, decay | Selector | engine._latest_e1rm (private) | Reynolds; Grgic | Stage 1 | Card 3 |
| Relative intensity | How heavy vs capacity | A2.1 + set load | load/e1RM | Gap | ACSM 80% | Stage 1/2 | Card 3 |
| RI distribution | Range | A2.2 | Count bands | Gap | ACSM | Stage 2 | Card 3 |
| RIR distribution | Proximity profile | clean_set.rir | Counts | Gap | Zourdos; Refalo | Stage 1 | Card 3 |
| RIR coverage | Data quality | clean_set | known/total | Gap | Data quality | Stage 1 | Advanced |
| sRPE | Perceived difficulty | session_feedback | Latest non-null | Exists | Sweet; Day | Stage 1 | Card 5 |
| Duration | Time | feedback/session/workout | Latest non-null | Exists, duplicated | DQ-SESSION-01 | Stage 1 | Card 5 |
| Session load AU | Internal load | sRPE × duration | Multiply | Gap | Sweet | Stage 1 | Card 5 |
| Recent reference e1RM | Typical recent performance | clean_set | Median of last 3 raw session bests | Gap; no shared estimator | Engineering judgement | Stage 1/2 | Card 2 |
| Best recent e1RM | Best single recent session | clean_set | Max raw session best in 84 days | Gap | Measurement logic | Stage 1 | Card 2/details |
| Personal best estimate | PR display | clean_set | Max raw session best all time | baseline.best_e1rm (different) | Grgic | Stage 1 | Card 2/details |
| Post best e1RM | Performance today | clean_set | Max eligible raw | Gap | Grgic | Stage 1 | Card 2 |
| Difference vs recent performance | Descriptive comparison | C1/C2 | post_best − recent_reference (both raw); % | Gap | Grgic (source only; no threshold) | Stage 1/2 | Card 2 |
| Difference status | Data sufficiency/quality | C1/C2 | descriptive/limited/single_prior/insufficient_quality/unavailable | Gap | Engineering decision | Stage 1 | Card 2 badge |
| Source set | Transparency | C4 | Row fields | Gap | — | Stage 1 | Details |
| Exercise identity | Comparability | taxonomy | Exact id | Exists | Spitz; Lockie; Herrera | Stage 1 | Card 2/3 |
| e1RM series | Longitudinal | C6 | Per-session best | progress ratio (different) | Grgic; FFM rejection | Stage 2/3 | Performance |
| Rolling median | Smoother | C6 | Median of last 3 | Gap | Descriptive | Stage 3 | Performance |
| Ratio | Relative strength | C6 + config | latest raw per side; ≥2 per side; num/den ×100 | Gap; programme_slot_of insufficient | PARENT-VARIANT; Parkinson | Stage 1/2/3 | Performance; max 2 on summary |
| Ratio dates | Comparability | C6 | Dates/gap | Gap | Product judgement | Stage 1 | Ratio detail |
| Power sets | Power exposure | clean_set, taxonomy | Count power_jump | derived excludes from RIR; no count | ACSM; Balachandran | Stage 1 | Card 4 |
| Power reps | Power volume | clean_set | Sum reps | Gap | ACSM | Stage 1 | Card 4 |
| Mean velocity change across sets | Descriptive power context | clean_set.velocity | 100 × (last − first)/first | rep_velocity has within-set; no power summary | Moura; Jukic | Stage 1/2 | Card 4 |
| Power quality stop | Quality | workout_event/plan | Event/flag | Gap; text only | DEC-POWER-02 | Stage 1 | Card 4 |
| Within-set loss | Not available | mean velocity | — | Explicitly unavailable | DEC-VELOCITY-01 | Stage 1 | "Unavailable" |
| Spinal exposures | Ordinal exposure | clean_set, registry | weekly_spinal_costs | Exists | Swinton; Hanen; Cholewicki | Stage 1 | Card 4 |
| Heavy spinal sets | Context | clean_set | RIR ≤1, 4 weeks | heavy_spinal | SPINAL-COST | Stage 1 | Card 4 |
| Axial demand mix | Qualitative | demands | Count levels | demands | EXERCISE-DEMANDS | Stage 2 | Card 4 |
| Productivity | Subjective usefulness | session_feedback (new) | 1–5 | Gap | No validation | Stage 1 | Card 5 |
| Comparable summary | Historical context | Prior sessions | Median of up to 5 | Gap | Descriptive | Stage 2/3 | Card 6 |
| Feedback completeness | Data quality | feedback/session/workout | Presence flags | Gap | Data quality | Stage 1 | Card 5 |
| e1RM quality/flags | Transparency | C1/C2 | Eligibility/quality | Gap | Grgic; RIR evidence | Stage 1 | Details |

---

## 18. Appendix: glossary, formulas and implementation contracts

### 18.1 Glossary

| Term | Meaning |
|---|---|
| raw_e1RM | Formula-derived Epley or Epley+RIR estimate with no age decay and no calibration factor |
| load_base_e1rm | The e1RM the prescription used to solve the load; median selector by default, with decay/calibration/override; separate from the performance series |
| recent_reference_e1rm | Median of the last 3 eligible raw per-session best e1RM observations before the session; primary comparator |
| best_recent_e1rm | Highest eligible raw per-session best in the 84 days before the session; separate best-performance reference |
| personal_best_e1rm | Highest eligible raw per-session best all time; PR display only |
| difference_vs_recent | post_best − recent_reference; descriptive, no significance claim |
| data_sufficiency | For ratios: available / insufficient_history / insufficient_quality / stale_or_gap / unavailable. For the recent comparison: descriptive / limited / single_prior / insufficient_quality / unavailable. Not statistical confidence. |
| post_best_e1rm | Best eligible raw estimate in the session |
| hard set | Working set with RIR ≤ effort_max_rir (default 4) |
| near-failure set | Working set with RIR ≤2 |
| session load | sRPE × duration in minutes, AU |
| relative intensity | Set load / load_base_e1rm |
| relative strength ratio | Configured numerator e1RM / denominator e1RM ×100 |
| power exposure | Count of power-classified sets/reps; the quality stop is separate and may be unknown; not hypertrophy volume |
| spinal exposure | Ordinal (session, exercise) cost from the rule registry; not lumbar load |
| productivity | Optional 1–5 self-report of how productive the session felt |
| comparable session | Same type + common main lift + overlap + not deload/technique/minimum + ≥3 priors |

### 18.2 Formulas

    raw_e1RM             = load × (1 + (reps + rir) / 30)   # or plain Epley fallback
    session_best(s)      = max(raw_e1RM_i) over eligible ok sets in session s
    recent_reference     = median(last 3 session_best observations strictly before current session)
    best_recent          = max(session_best in the 84 days before current session)
    personal_best        = max(session_best all time)
    post_best            = session_best(current session)
    difference_kg        = post_best - recent_reference
    difference_pct       = 100 × difference_kg / recent_reference
    load_base_e1RM       = selector(history) × decay(age) × calibration_factor  # prescription only
    relative_intensity   = load / load_base_e1RM
    session_load_au      = sRPE × duration_min
    ratio_pct            = 100 × raw_e1RM(numerator) / raw_e1RM(denominator)
    mean_velocity_change = 100 × (last_set_mean_velocity - first_set_mean_velocity) / first_set_mean_velocity
    tonnage_exercise     = Σ(external_load_kg × reps)
    hard_sets            = count(working sets with 0 <= rir <= effort_max_rir)
    near_failure_sets    = count(working sets with 0 <= rir <= 2)

The performance quantities (session_best through difference_pct and ratio_pct) use raw_e1RM only. Decay and calibration_factor appear only in load_base_e1RM, whose existing prescription behaviour is unchanged. When fewer than 3 eligible observations exist, recent_reference is the median of the available observations but the status is limited (2) or single_prior (1); it is not treated as a 3-observation median.

The constants 21 days, 1%/week and 10% max are the existing e1rm_decay assumptions, not new findings. The Epley divisor 30 is the existing formula convention. The 4.2% figure from Grgic 2020 is a direct-1RM test–retest reference only; it is not used in any formula or threshold here.

### 18.3 Pseudocode contracts

    # features/e1rm_source.py
    def select_e1rm(
        conn,
        exercise_id: str,
        on_date: str,
        *,
        session_id: str | None = None,   # exclude this session (strict cutoff)
        estimator: str = "median",        # prescription selector; not the monitoring best
        window_days: int = 84,
        robust_window_days: int = 28,
    ) -> Estimate | Unavailable:
        ...

    # features/monitoring.py
    def raw_e1rm(set_row) -> Estimate | Unavailable: ...
    def session_best(conn, session_id: str, exercise_id: str) -> Estimate | Unavailable: ...
    def recent_reference(conn, session_id: str, exercise_id: str) -> Reference | Unavailable: ...
    def best_recent(conn, session_id: str, exercise_id: str) -> Estimate | Unavailable: ...
    def personal_best(conn, session_id: str, exercise_id: str) -> Estimate | Unavailable: ...
    def post_best(conn, session_id: str, exercise_id: str) -> Estimate | Unavailable: ...
    def difference(conn, session_id: str, exercise_id: str) -> Difference | Unavailable: ...
    def load_base(conn, session_id: str, exercise_id: str) -> Estimate | Unavailable: ...
    def session_load(conn, session_id: str) -> Load | Unavailable: ...
    def relative_intensity(set_row, load_base: Estimate) -> float | Unavailable: ...
    def hard_sets(sets, config) -> HardSetCount: ...
    def exercise_tonnage(sets, exercise_id) -> Tonnage | Unavailable: ...
    def power_exposure(sets, taxonomy) -> PowerExposure: ...
    def spinal_exposure(conn, session_id) -> SpinalExposure: ...  # calls registry

    # features/relative_strength.py
    def ratio(conn, relationship, on_date) -> Ratio | Unavailable:
        # both sides eligible, ok, >=2 observations each, within max_age, gap <= max_gap
        ...

### 18.4 API contract sketch

    {
      "summary": {
        "workout_id": "…",
        "session_id": "…",
        "for_date": "2026-10-28",
        "session_type": "bench_squat",
        "status": "complete",
        "completion": {
          "planned_sets": 16, "completed_sets": 14, "planned_reps": 70, "completed_reps": 62,
          "items": [{"exercise_id": "bench_press", "status": "complete", "actual": 4, "planned": 4}],
          "substitutions": []
        },
        "strength": [{
          "exercise_id": "bench_press",
          "recent_reference": {"kg": 157.5, "n": 3, "dates": ["2026-10-14","2026-10-18","2026-10-23"], "method": "median_session_best", "basis": "raw_formula_epley_rir", "decay_applied": false, "calibration_applied": false, "quality": "ok"},
          "best_recent": {"kg": 158.4, "date": "2026-10-23", "basis": "raw_formula_epley_rir", "quality": "ok"},
          "personal_best": {"kg": 158.4, "date": "2026-10-23", "basis": "raw_formula_epley_rir", "quality": "ok"},
          "post": {"kg": 158.7, "set_id": 123, "load_kg": 140, "reps": 3, "rir": 1, "method": "epley_plus_rir", "basis": "raw_formula_epley_rir", "quality": "ok"},
          "difference": {"kg": 1.2, "pct": 0.76, "status": "descriptive", "basis": "raw_minus_raw", "measurement_error": "not_established"},
          "excluded": [{"set_id": 124, "reason": "rir_above_3"}]
        }],
        "dose": {
          "load_base_e1rm": {"kg": 150.0, "selector": "median", "decay": "load_base_policy", "calibration": "load_base_policy", "note": "load-selection only; not a performance observation"},
          "per_exercise": [{"exercise_id": "bench_press", "sets": 3, "reps": 17, "tonnage_kg": 1980, "hard_sets": 3, "near_failure_sets": 3}],
          "relative_intensity": {"bands": {"heavy": 2, "moderate": 1}, "unknown": 0},
          "rir": {"0": 0, "1": 1, "2": 2, "3": 0, "4": 0, "5": 0, "missing": 0, "warmup": 2},
          "patterns": {"horizontal_push": 3, "squat": 3, "hinge": 3}
        },
        "special": {
          "power": {"sets": 3, "reps": 15, "mean_velocity_change_pct": -5.7, "quality_stop": "not_recorded"},
          "high_intensity": [],
          "spinal": {"exposures": [], "weekly_cost": 3.7, "weekly_cap": 6.0, "heavy_sets": 1}
        },
        "feedback": {
          "srpe": 7, "srpe_timing": "immediate", "duration_min": 65, "duration_source": "measured",
          "session_load_au": 455, "productivity": 4
        },
        "comparison": {"n": 3, "key": "type+main_lift+overlap", "metrics": {}},
        "quality": {"flags": [], "coverage": {"rir": 1.0, "e1rm": 0.67}}
      }
    }

Null means unknown/unavailable; the UI must map it to the correct label. A 0 is a real zero.

### 18.5 What the implementation agent must not decide

The agent implementing an approved phase must not invent:

- the e1RM selector or its window;
- the recent-reference estimator or the number of observations;
- the cutoff rule;
- the eligibility/quality bands;
- whether the performance series is raw, calibrated or age-decayed; the settled policy is raw formula-derived with calibration/decay only on the load base;
- the relative-intensity bands;
- any meaningful-change threshold or significance label;
- the ratio gap/age windows or its minimum history (2 per side);
- the individual-error protocol or any threshold derived from it;
- the productivity wording/scale;
- the comparable-session key;
- the decision to add any composite score.

Those are settled here or must be raised as open questions. If a value is missing, return unavailable; do not guess.

### 18.6 Review checklist

- [ ] Does the document distinguish observed, estimated, unknown, not applicable, invalid, unavailable and zero?
- [ ] Is every headline number traceable to a row?
- [ ] Is the pre-session cutoff leakage-proof?
- [ ] Is the load base separate from the recent reference and from the best-performance reference, and is the performance series raw (no decay/calibration)?
- [ ] Is the difference vs recent performance labelled descriptive, not acute change or adaptation?
- [ ] Are ratios configured, latest-observation, ≥2 observations per side, date-stamped and non-diagnostic?
- [ ] Is mean velocity change descriptive only, with power quality explicitly unmeasured without an event?
- [ ] Is the spinal exposure still ordinal?
- [ ] Is productivity optional and outside every calculation?
- [ ] Is there any new composite scalar? (It must be "no".)
- [ ] Is there any automatic prescription change? (It must be "no".)
- [ ] Is every new threshold marked as an assumption, and is the 4.2% figure used only as a direct-1RM literature reference?
- [ ] Is ICC absent from the individual calibration protocol, and is any typical-error/CV estimate treated as uncertain and non-thresholded, with no automatic confidence interval or error band?
- [ ] Are the sources verified with DOI/PMID?
- [ ] Does the plan avoid unnecessary migrations?

---

## 19. Related documents

- [Data model](../DATA-MODEL.md)
- [Decisions](../DECISIONS.md)
- [Limitations register](../LIMITATIONS-REGISTER.md)
- [Data quality](../DATA-QUALITY.md)
- [References](../REFERENCES.md)
- [RIR evidence](../RIR-EVIDENCE.md)
- [Fatigue, fitness and strength](../FATIGUE-FITNESS.md)
- [Volume management](../VOLUME-MANAGEMENT.md)
- [Exercise demands](../EXERCISE-DEMANDS.md)
- [Spinal cost](../SPINAL-COST.md)
- [High-intensity exposure](../HIGH-INTENSITY-EXPOSURE-PLAN.md)
- [Parent-variant ratios and weakness](../PARENT-VARIANT-WEAKNESS-EVIDENCE.md)
- [VBT evidence](../VBT-EVIDENCE.md)
- [Per-rep velocity](../REP-VELOCITY.md)
- [Web UI](../WEB-UI.md)
- [UI map](../UI-MAP.md)
- [Methodology](../METHODOLOGY.md)
- [Frequency and volume](../FREQUENCY-AND-VOLUME.md)
- [Privacy](../PRIVACY.md)
- [Repository instructions](../../AGENTS.md)
- [Roadmap](../../ROADMAP.md)

---

## 20. Revision history

### Revision 3 — 2026-10-30

**Sections changed:** 1.3, 2.6, 2.7, 2.9, 3.2, 3.3, 4.3, 4.4 (C1/C2, C4, D1), 5, 6.1, 6.5, 7, 8.2, 8.3, 9.2, 9.4, 10.1, 11.0, 11.5, 11.7, 12.1, 12.2, 12.4, 12.5, 13, 14, 15, 16.4, 16.7, 17, 18.1–18.6, 20.

**Main methodological changes:**

- Removed ICC from the individual calibration protocol. ICC is a between-participant relative-reliability statistic and is not suitable for N-of-1 reliability. The document now separates direct-test repeatability (within-athlete typical error/CV), formula prediction error against a measured criterion, and day-to-day biological variation. It explicitly says small-sample estimates are highly uncertain, uses no validated minimum number of tests, and does not create a confidence interval or error band without adequate data and a pre-specified method.
- The relative-strength ratio now requires **at least two eligible observations per side** before display. With exactly one, the available estimate and date are shown but the ratio is labelled unavailable due to insufficient history; with zero or a missing estimate it is labelled unavailable. The ratio uses the latest eligible observation per side, not an average or smoothed series.
- All monitoring performance observations are now explicitly **raw formula-derived Epley/Epley+RIR estimates**. Age decay and the measured-test calibration factor are not applied to session_best, recent_reference, best_recent, personal_best, post_best or difference_vs_recent. The prescription load base remains separate, with its existing selector, calibration, decay and override behaviour unchanged. Raw estimates may carry systematic bias; consistency of method is not criterion validity.
- Added **Phase 0 — Retrospective data and estimator audit** before monitoring UI implementation. It audits coverage, eligible observations, measured tests, formula behaviour and simple baselines, and produces a reproducible report (or a local-only equivalent where privacy requires it). It does not automatically introduce a fitted correction factor.
- Added PA-17 (raw performance series) and revised PA-07 and PA-16.

**Still unresolved:** the feasibility and sample size of repeated measured tests; the ratio gap/age windows; the 3-observation reference choice; the productivity scale; the sRPE timing protocol. These remain assumptions or open decisions, not validated rules.



### Revision 2 — 2026-10-30

**Sections changed:** 1.2, 1.4, 2.9, 2.10, 3.3, 4.3, 4.4 (C3, C4, E1), 5, 6.4, 6.5, 7, 8.2, 8.3, 9.3, 9.4, 9.6, 10.1, 11.0, 11.1, 11.3, 11.4a, 11.5, 11.7, 12.1, 12.2, 12.5, 13, 14, 15, 16.4, 16.5, 16.7, 16.8, 17, 18.1–18.6, 20.

**Main methodological changes:**

- The 4.2% figure is retained only as a literature reference for **direct 1RM test–retest variability**. It is no longer a meaningful-change threshold for the app's estimated e1RM. No automatic clear/meaningful/significant/within-typical classification remains.
- The primary recent comparator is now the **median of the last 3 eligible per-session best e1RM observations** (recent reference), not the 84-day historical maximum. The best recent single session and the all-time personal best are separate context values and are not used as typical baselines.
- One degraded-estimate policy applies everywhere: degraded estimates are displayed with their method and limitations, never used in headline differences; if either side is degraded the difference status is insufficient_quality.
- The relative-strength ratio now uses the **latest eligible per-session best for each side**, with visible dates, a 14-day gap and 42-day age gate, and a data-sufficiency status rather than a confidence label. Independent smoothing and division are rejected; historical trends use paired observations.
- The power metric is renamed **mean velocity change across sets** and is explicitly descriptive; it is not retention, quality or within-set velocity loss.
- Evidence is classified by decision basis (A evidence-supported, B engineering decision, C product assumption), with a new product-assumptions register (PA-01–PA-16).

**At Revision 2, still unresolved:** the individual measurement-error model (repeated measured tests), the ratio gap/age windows, the 3-observation reference choice, the productivity scale and the sRPE timing protocol. These were documented as assumptions or open decisions, not presented as validated rules.