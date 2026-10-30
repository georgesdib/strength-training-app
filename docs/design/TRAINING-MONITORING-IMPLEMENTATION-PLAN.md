# Training monitoring implementation plan

**Repository-specific implementation plan for the approved monitoring specification**

| Item | Value |
|---|---|
| Status | Planning only. **No implementation approved or started.** |
| Repository | strength-training-app |
| Branch | development |
| Baseline commit | 2711a6e (approved specification) |
| Specification | [Training monitoring design specification](TRAINING-MONITORING-SPEC.md) |
| Document date | 2026-10-30 |
| Scope | Phase 0 through Phase 5 planning; individual calibration architecture; no code, schema, config or test changes |
| Intended reader | Human approver first, then one coding agent per phase |

> The approved specification is authoritative for metric definitions. If this plan and the specification disagree, the specification wins and the discrepancy must be raised rather than silently resolved.

---

## 1. Executive summary

### 1.1 What this plan does

This plan translates the approved multi-dimensional monitoring design into a staged implementation sequence that:

- starts with a reproducible, read-only historical audit;
- creates one shared load-base e1RM selector without changing prescription behaviour;
- creates a separate raw formula-derived performance layer;
- adds the descriptive workout summary;
- adds longitudinal strength, dose and relative-strength views;
- prepares, but does not activate, individual calibration from genuine measured tests.

It reuses the existing store, enrichment, workout comparison, volume, exposure, spinal, high-intensity, demand, feedback and web layers. It does not create a second monitoring store or a parallel calculation stack.

### 1.2 Recommended sequence

| Phase | Name | Primary outcome | Migration? |
|---|---|---|---|
| 0 | Historical data and estimator audit | Reproducible report on what existing data can support | No |
| 1 | Shared measurement core | Load-base selector extracted; raw performance observations; monitoring definitions | No |
| 2 | Descriptive workout summary | Session summary API, CLI and end-screen UI | Conditional: productivity only |
| 3 | Longitudinal strength and relative strength | Performance view, trends, configured ratios | No |
| 4 | Exploratory analysis and calibration preparation | Descriptive analysis, calibration observation read model | No |
| 5 | Prospective validation and future calibration | Deferred activation of individual calibration | Deferred, only if approved |

### 1.3 Key engineering conclusions

1. **Do not build the UI first.** Phase 0 must establish coverage, eligibility, measured-test availability and formula behaviour. The existing local data may contain few or no genuine measured tests; that must be measured, not assumed.
2. **The load base and the performance series are separate code paths.** The prescription selector keeps its existing median/best/most-recent, decay, calibration and override behaviour. Monitoring uses a raw formula-derived estimator with no decay and no calibration.
3. **The only near-term migration is productivity, and it is not a simple ALTER.** The existing session_feedback table has a CHECK requiring sRPE, duration or note. A productivity-only row would fail. The plan therefore proposes a table rebuild migration, conditional on Domain G approval.
4. **The biggest behaviour-preservation risk is the load-base extraction.** It must be an adapter around the existing algorithm, with golden-prescription and selector-parity tests before any UI work.
5. **No new dependencies are needed.** The existing pandas/numpy/PyYAML stack and vanilla JavaScript/SVG are sufficient.
6. **Individual calibration is prepared, not activated.** No factor is fitted now. The plan preserves raw observations, defines provenance and validation requirements, and defers promotion criteria until data exists.

### 1.4 What is explicitly not planned

No composite score, no automatic prescription change, no injury prediction, no fatigue-fitness integration, no calibration or age decay on the performance series, no ordinary training set treated as a criterion test, no new monitoring tables, and no UI redesign outside the monitoring views.

---

## 2. Repository architecture findings

### 2.1 Layering and service boundaries

The repository follows the documented direction: utils → domain → ingest/store → features → rules/prescribe/critique → agents/eval, with workout.py and history.py as operational services over the store. The web server serialises and routes; it does not compute metrics.

Implications for this work:

- A new **features** module may import domain, store.queries and utils, but not prescribe, rules, web or workout.
- **workout.summary** is the correct orchestration point for a completed workout because it may import features and has access to the frozen plan and comparison.
- The web layer must call workout.summary or features functions; it must not reimplement calculations.
- The CLI must call the same core functions as the UI.

### 2.2 Existing modules by monitoring domain

| Domain | Existing implementation | Reuse |
|---|---|---|
| Set/session data | store/queries.clean_sets, sessions; ingest/clean.py; ingest/sessions.py | Reuse; do not re-clean |
| RIR semantics | domain/rir.py; features/derived.add_effort_fields | Reuse the classifier |
| e1RM formula | domain/e1rm.py; features/derived.add_e1rm | Reuse Epley/Epley+RIR; new raw estimator applies the monitoring guard |
| Load-base selector | prescribe/engine.py::_latest_e1rm | Extract pure selector; preserve exactly |
| Calibration | features/e1rm_calibration.py | Reuse report/points; do not change activation |
| Age decay | features/e1rm_decay.py | Reuse for load base only |
| Completion comparison | workout.py::_comparison and workout.get | Reuse directly |
| Workout lifecycle | workout.py start/add/update/end/_materialise | Extend with summary and feedback only |
| Session feedback | features/session_feedback.py; session_feedback table | Extend with per-field merge and productivity |
| Volume | features/volume.py | Reuse pattern keys and weekly ledger |
| Hard-set exposure | features/exposure.py | Reuse hard-set definition/config |
| High-intensity exposure | features/high_intensity_exposure.py | Reuse status and records |
| Spinal | rules/registry.py::weekly_spinal_costs; features/heavy_spinal.py | Reuse; never recompute |
| Demands | features/demands.py | Reuse; never aggregate dimensions |
| Power | features/derived.py power exclusion; workout quality_stop/effort_model; features/rep_velocity.py | Reuse; no within-set loss from mean velocity |
| Longitudinal progress | features/progress.py | Keep Today view; do not reuse its ratio as the new series |
| Fatigue-fitness | features/fatigue_fitness.py | Do not connect |

### 2.3 e1RM implementations and their differences

There are multiple independent e1RM computations today:

| Location | What it computes | Window/aggregation | Decay/calibration | Suitability |
|---|---|---|---|---|
| prescribe/engine.py::_latest_e1rm | Prescription load base | 84 days; median 28 days, best usable, or most recent | Decay and calibration; override wins | Correct for prescription; extract, do not change |
| features/e1rm_calibration.py::build | Calibration report and points | 84 days; max per lift, decayed once | Reports correction | Reuse points for audit; do not use as monitoring series |
| features/baseline.py::lift_baselines | Baseline report | 84-day window, all-time best | None | Display only |
| features/progress.py::_session_lift_e1rms | Today performance ratio | Per session max | None | Does not check e1rm_applicable; keep separate |
| features/fatigue_fitness.py | Shadow model observations | Per session max | None | Do not connect |

Consequences:

- A new raw monitoring estimator is needed; it must not be a sixth load-base selector.
- The load-base extraction must be a pure adapter, not a second implementation.
- The known progress applicability defect and the e1rm_calibration date-label defect are recorded as out-of-scope existing behaviour. Fixing either is a separate change with its own review.

### 2.4 Data structures and constraints

| Structure | Relevant fields | Planning implication |
|---|---|---|
| clean_set | set_id, session_id, occurred_on, exercise_id, load_kg, load_basis, external_load_kg, reps, reps_unit, rir, rir_source, velocity_mps, velocity_present, tonnage_kg, is_working_set, flags, supersedes_id | Primary source; computed on read |
| session | session_id, occurred_on, session_type, duration_min, duration_basis, session_rpe, tonnage_kg, flags | Summary identity; manual duration is stored as measured today |
| workout_session | workout_id, plan_json, plan_modified_json, started_at, ended_at, duration_min, duration_source, session_rpe | Plan snapshot and start-time ordering |
| workout_set | exercise_id, set_index, load_kg, reps, rir, velocity, source | Draft only; summary reads materialised clean_set |
| workout_event | event_type, target_set_id, payload_json | Plan swaps, removals, quality-stop event if later added |
| session_feedback | srpe, duration_min, note, recorded_at, CHECK at least one | Row-wise append-only; needs per-field merge |
| e1rm_override | exercise_id, e1rm_kg, effective_from, expires_on, reason, source | Measured tests live here; lacks protocol/equipment/formula version |
| high_intensity_exposure | kind, exercise_id, performed_on, test_type, source_id, set_id | Links a test to e1rm_override via source_id |
| clean_rep | clean_set_id, rep_index, velocity_mps | Optional per-rep detail; no within-set loss from mean velocity |

### 2.5 Discrepancies between the specification and current code

| # | Specification statement | Current code | Decision for this plan |
|---|---|---|---|
| 1 | Add one nullable productivity column to session_feedback | No productivity column; CHECK requires srpe, duration or note | Conditional Phase 2 migration must rebuild the table, not merely add a column |
| 2 | plan_json can carry the load-base e1RM provenance | PrescriptionItem has intensity/e1rm_source_sets, but _item_dict omits e1RM value/reference/quality/age | Phase 1/2 adds optional plan provenance fields; no DB migration |
| 3 | Monitoring uses raw formula-derived e1RM | No raw session-best module; derived.add_e1rm is set-level and does not cap reps+rir | Phase 0/1 creates separate raw observation module |
| 4 | No decay/calibration on performance series | Existing selectors differ; progress uses none, calibration max uses decay | New raw module applies neither; load base unchanged |
| 5 | Manual duration is labelled manual in monitoring | workout._materialise writes duration_basis = measured even for manual | Summary reads workout_session.duration_source and labels manual; do not change duration_basis |
| 6 | e1rm_calibration source date is transparent | latest_e1rm is window max but latest_on is latest date | Out of scope; new monitoring does not use latest_on |
| 7 | progress respects e1rm applicability | _session_lift_e1rms does not check e1rm_applicable | Out of scope; new monitoring does not use progress |
| 8 | Power quality stop is structured | quality_stop is text; effort_model is quality; no event | Phase 2 displays "not recorded"; no inference |
| 9 | session_feedback read merges per field | queries.session_feedback returns latest row only | Phase 2 adds merged() for monitoring |
| 10 | No measured-test assumption | Local data may have zero or few measured tests | Phase 0 establishes count; no assumption |
| 11 | e1rm_override provenance supports future calibration | No test_type/equipment/protocol/formula version | Future migration; Phase 4 read model can link existing exposure |
| 12 | queries.clean_sets total load is correct for added load | total_load_kg = load_kg, bodyweight contribution lost for added basis | Latent because current bodyweight exercises are e1rm_applicable false; defer unless enabling weighted bodyweight e1RM |

### 2.6 API, CLI and UI architecture

- GET API dispatch is a path chain in web/server.py. A new /api/workout/<id>/summary route must be placed before the generic /api/workout/<id> route.
- POST workout actions use workout._workout_action; end already accepts session_rpe, not_recorded, duration_min and notes.
- The web client is vanilla JavaScript with no framework and no chart library. New charts should be inline SVG or HTML/CSS.
- app.js setView() owns navigation and per-view loaders; index.html owns nav buttons, view sections and script tags.
- Existing UI tests require every referenced script to exist, script order, no inline handlers, and a doc-link per panel.
- The CLI uses argparse with explicit subparsers; add summary and performance subcommands calling the same core.

### 2.7 Test and CI architecture

- pytest with xdist; default addopts: -q --strict-markers -n auto --dist loadfile.
- Markers: integration (real CSVs) and golden (snapshot regression).
- conftest.py provides make_training, make_readiness, populated_db and fixture helpers.
- Golden prescription tests pin all four session types and exact loads.
- Existing e1RM selector tests are in tests/test_e1rm_source.py; calibration tests in test_e1rm_calibration.py; workout lifecycle in test_workout.py; web API in test_web.py; frontend static contracts in test_ui_frontend.py.
- ruff line length 110; no new dependencies.


## 3. Specification-to-code mapping

| Specification area | Required output | Existing code to reuse | Gap to close | Phase |
|---|---|---|---|---|
| A1 completed work | Working sets, reps, per-exercise tonnage | queries.clean_sets, derived.working_sets, workout._comparison | Session summary composition | 2 |
| A1 hard sets | RIR ≤4 count, near-failure ≤2 | exposure.ExposureConfig.effort_max_rir, exposure._hard logic | Public shared helper; session count | 1/2 |
| A1 pattern distribution | Sets by volume_target_key | volume.volume_target_key, volume.compute | Session-scoped count | 2 |
| A2 relative intensity | load / load_base_e1rm | clean_set fields, thresholds, e1rm_source | Bands, coverage, unknown denominator | 1/2 |
| A3 RIR distribution | Counts, missing, warm-up | domain.rir.classify, clean_set.rir | Session distribution | 2 |
| A4 tonnage | Per-exercise external load × reps | clean_set.tonnage_kg, session tonnage | Per-exercise report; no cross-exercise total | 2 |
| B session load | sRPE × duration AU | session_feedback, session, workout_session | Per-field merge; session load function | 1/2 |
| C raw performance | session best, recent reference, best recent, personal best, difference | domain.e1rm, derived, taxonomy | New raw observation module; no decay/calibration | 0/1 |
| C pre/post cutoff | Strictly before current session | queries.clean_sets, workout_session.started_at | Cutoff rules and tests | 1 |
| C source set | load, reps, RIR, method, quality | clean_set + derived metadata | Summary source table | 2 |
| D relative strength | Configured ratio, dates, counts, data sufficiency | clean_set, taxonomy | Config and relative_strength module | 3 |
| E power exposure | sets, reps, mean velocity change | derived power exclusion, clean_set.velocity | Power classifier and descriptive calculation | 1/2 |
| E quality stop | recorded/not recorded only | prescription_item.quality_stop, workout_event | Structured event deferred; no inference | 2 |
| F spinal exposure | ordinal effective cost, weekly cap | rules.registry.weekly_spinal_costs, heavy_spinal | Session summary adapter | 2 |
| F axial demand | counts by axial level | features.demands | Session count with unknown | 2 |
| G productivity | optional 1–5 item | session_feedback | Column, merge, end/review UI | 2 |
| Longitudinal | raw series, rolling median, breaks | none beyond progress ratio | strength_trend module and Performance view | 3 |
| Comparable sessions | median of prior comparable sessions | workout comparison, volume | Comparability key and summary | 3 |
| Calibration preparation | measurement observations, provenance | e1rm_override, high_intensity_exposure, e1rm_calibration | Read model; future schema | 4/5 |

---

## 4. Phase 0 — Historical data and estimator audit

### 4.1 Objective

Produce a deterministic, reproducible, read-only report of what existing training history can support before building any monitoring UI. Establish coverage, eligibility, measured-test availability, formula behaviour, outliers and comparability. Do not fit a correction factor.

### 4.2 Why Phase 0 is first

The specification makes strong claims about raw formula-derived estimates and explicitly refuses to assume measured tests exist. Building summaries, ratios or a Performance view before measuring coverage would risk:

- presenting sparse accessory series as trends;
- treating ordinary sets as criterion tests;
- building a ratio view with no pairs that meet the 2-observation rule;
- choosing windows or quality cuts without seeing how many observations survive.

### 4.3 Scope

In scope:

- data coverage by exercise, rep range, RIR and load basis;
- eligible raw e1RM observations under the approved eligibility/quality rules;
- measured 1RM/3RM/5RM test count and linkability;
- formula behaviour, outliers and comparability breaks;
- simple baseline comparison on next-observation errors;
- a local-only or redacted report;
- a pure raw-observation module needed by the audit and reused later.

Out of scope:

- UI or API;
- any correction factor;
- any change to prescription, calibration activation or age decay;
- any write to historical records;
- any new database table.

### 4.4 Audit script design

New file: tools/monitoring_historical_audit.py

Responsibilities:

- open SQLite with a read-only URI (file:...?mode=ro) and PRAGMA query_only;
- load clean sets through store.queries.clean_sets and enrich through the shared raw observation helper;
- group by canonical exercise, session, rep range and RIR;
- optionally filter by --since, --until and --exercise;
- emit Markdown and JSON through --format;
- default output to private/docs/MONITORING-HISTORICAL-AUDIT.md, which is git-ignored;
- support --out to an explicit path, but never write into data/ or private/ unless the caller asks;
- be deterministic: stable sorting, no wall-clock timestamp in the body, include arguments and data fingerprint;
- return non-zero only on a genuine read/analysis failure, not on sparse data.

Required report sections:

1. **Data inventory** — sessions, sets, working sets, date range, canonical exercises, load-basis counts, RIR coverage, warm-up share.
2. **Eligibility** — eligible raw e1RM observations per exercise and rep range; rejected reasons (warm-up, missing RIR, reps+rir >20, load basis unknown, not applicable, power/test).
3. **Measured tests** — count of e1rm_override rows with source measured; test_type from linked high_intensity_exposure; whether each test links to a prior raw estimate; date gap; protocol/equipment availability (expected unknown).
4. **Formula behaviour** — session-best distribution, rep/RIR strata, outliers, change across equipment/variant boundaries.
5. **Simple baselines** — next-observation error for: last session best, rolling median of 3, rolling median of 5 (sensitivity), 84-day best. Report MAE and median absolute error; label these as descriptive stability checks, not criterion accuracy.
6. **Measured-test error** — only if genuine tests exist: per-lift bias, MAE and MAPE of the formula estimate available before each test; sample size and rep coverage; chronological holdout where sample permits.
7. **Limitations and recommendations** — what is not established, which exercises have enough data, whether ratio pairs meet the 2-observation rule, whether individual calibration is currently possible.

### 4.5 Pure raw-observation module (created in Phase 0)

To avoid the audit computing a different e1RM from the future UI, Phase 0 creates:

New file: strength_coach/features/strength_observations.py

Public functions:

- raw_set_e1rm(set_row, taxonomy_props) -> RawEstimate | Unavailable
- session_best(frame, session_id, exercise_id) -> RawEstimate | Unavailable
- session_observations(frame, exercise_id, before_date, cutoff_session_id) -> list[SessionObservation]
- recent_reference(observations, n=3, max_age_days=84) -> Reference | Unavailable
- best_recent(observations, max_age_days=84) -> RawEstimate | Unavailable
- personal_best(observations) -> RawEstimate | Unavailable
- difference_vs_recent(post, reference) -> Difference | Unavailable (requires both ok and at least 2 reference observations; status explicit)

Rules enforced:

- Epley/Epley+RIR only; no decay, no calibration;
- reps+rir ≤20;
- exercise e1rm_applicable;
- working set, not warm-up, not RIR 6;
- ok quality: reps ≤10, RIR ≤3; degraded: reps 11–20 or RIR 4–5; invalid otherwise;
- bodyweight total-load resolvability is a precondition; if unknown, unavailable;
- one observation per session, not per set;
- exact exercise identity; no variant pooling;
- strict cutoff, excluding the current session and unordered same-date sessions.

This module is pure, read-only and has no store writes.

### 4.6 Audit tests

New file: tests/test_monitoring_historical_audit.py

Cases:

- synthetic DB with warm-up, missing RIR, RIR 5, reps 11, reps+rir >20, bodyweight-added, power, test-linked;
- report counts match the synthetic fixture;
- no writes: database file hash and row counts unchanged after audit;
- deterministic output: two runs with the same args produce identical bytes, excluding an explicit data fingerprint;
- no measured tests: report says criterion calibration is not possible;
- measured tests: report links e1rm_override to high_intensity_exposure and prior formula estimate;
- privacy: default output path is private/docs, not docs/;
- malformed/missing DB produces a clear error and no partial report.

Optional integration file: tests/test_monitoring_historical_audit_integration.py

- marked integration;
- uses populated_db or real data only when available;
- asserts report structure, read-only behaviour and coverage fields, not personal values.

### 4.7 Acceptance criteria

- Report is generated from the existing DB without modifying it.
- Coverage, missingness, eligible observations and measured-test counts are explicit.
- Measured tests are not assumed; absence is reported.
- Simple baselines are compared descriptively.
- No correction factor is fitted.
- The report states whether monitoring can proceed descriptively and which exercises/pairs are too sparse.
- All Phase 0 tests pass; ruff passes.

### 4.8 Risks and exclusions

Risks:

- Local data may be too sparse for some exercises; that is a finding, not a failure.
- The report may contain personal data; default private path mitigates.
- The raw module could drift from the later UI; shared module and tests mitigate.

Exclusions:

- no UI, API, schema, migration or prescription change;
- no calibration engine;
- no ordinary training set treated as measured strength.

---

## 5. Phase 1 — Shared measurement core and definitions

### 5.1 Objective

Create the reusable measurement layer that the summary and history views will call, while proving that prescription behaviour is unchanged.

### 5.2 Scope

- Extract the load-base selector into a pure function and adapt prescribe/engine.py to call it.
- Add raw performance observation helpers (Phase 0 module if not already done).
- Add monitoring dose, feedback, power and spinal adapters.
- Add config/monitoring.v1.yaml.
- Add optional plan snapshot provenance fields.
- No UI, API or migration.

### 5.3 Load-base extraction

New file: strength_coach/features/e1rm_source.py

Pure function contract:

    select_load_base(
        sets: pandas.DataFrame,
        *,
        exercise_id: str,
        for_date: str,
        window_days: int,
        robust_window_days: int,
        source: str,
        override: Override | None,
        calibration_factor: float,
        decay_factor: Callable[[float], float],
        history_equivalents: tuple[str, ...],
    ) -> LoadBaseEstimate | None

The function must reproduce _latest_e1rm exactly, including:

- override precedence and age decay for the override;
- history_equivalents;
- 84-day cutoff and 28-day robust median;
- best_usable, median and most_recent selectors;
- age-decay calculation per set and the median decay ratio;
- calibration factor application;
- the returned reference string and coverage count;
- the long-gap decay exception currently in engine._e1rm_decay.

prescribe/engine.py keeps a thin adapter:

- query the override;
- read context.sets and context.gap_days;
- call select_load_base;
- return the same tuple shape.

Do not change the selector semantics, config keys or warnings.

### 5.4 Raw performance layer

Use or finalize strength_coach/features/strength_observations.py from Phase 0. It must not import prescribe or rules.

Add a formula/method constant in strength_coach/domain/e1rm.py:

- method: epley or epley_plus_rir;
- method_version: E1RM_METHOD_VERSION = "epley_rir_v1", defined once and returned with every raw estimate.

No database column is required now.

### 5.5 Monitoring definitions

New file: strength_coach/features/monitoring.py

Public functions (pure where possible):

- completed_working_sets(frame, session_id)
- completed_reps(frame, session_id)
- exercise_tonnage(frame, exercise_id)
- hard_sets(frame, config) and near_failure_sets(frame)
- rir_distribution(frame)
- relative_intensity(set_row, load_base)
- relative_intensity_distribution(sets, load_base_by_exercise)
- session_load(feedback) -> session_load_au | Unavailable
- power_exposure(frame, taxonomy)
- mean_velocity_change(frame, exercise_id, load_kg)
- spinal_summary(precomputed_weekly_costs, session_id) — the registry call stays in workout.summary; features.monitoring must not import rules
- axial_demand_counts(frame, catalogue)

Rules:

- add a public is_hard_set helper in features/exposure.py and reuse effort_max_rir; do not duplicate the predicate
- reuse volume_target_key;
- reuse weekly_spinal_costs;
- reuse demands.profile;
- no composite return and no score field;
- statuses observed/estimated/unknown/not_applicable/invalid/unavailable/zero;
- no missing-to-zero conversion.

### 5.6 Configuration

New file: config/monitoring.v1.yaml

Contents:

- relative-intensity bands;
- recent-reference observation count (3) and max age (84 days);
- difference statuses;
- ratio max gap (14), max age (42), min observations (2);
- session comparability key parameters (8 weeks, 50% overlap, 3 priors);
- late feedback threshold and long-session multiplier;
- display precision;
- feature flags for optional sections.

All values that are product assumptions must be marked as PA-* in comments. Do not add a meaningful-change threshold.

### 5.7 Plan snapshot provenance

Modify prescribe/models.py:

- add optional fields to PrescriptionItem: e1rm_kg, e1rm_ref, e1rm_quality, e1rm_age_days.
- do not add them to as_rows, so the prescription_item table is unchanged.

Modify prescribe/engine.py:

- populate those fields when _latest_e1rm returns;
- leave intensity unchanged.

Modify web/server.py::_item_dict:

- include the new fields; old snapshots omit them.

Modify workout.start/plan JSON only if needed to pass them through; the plan dict is already JSON.

No migration.

### 5.8 Session feedback merge (preparation)

Modify features/session_feedback.py:

- add merged(conn, session_id) returning latest non-null srpe, duration_min and note;
- keep latest() unchanged for existing callers;
- do not query a productivity column before the Phase 2 migration; the signature may accept an optional productivity later;
- do not change write behaviour yet.

### 5.9 Tests

New or extended:

- tests/test_e1rm_source_shared.py — selector parity across overrides, selectors, windows, decay, calibration, history equivalents;
- tests/test_strength_observations.py — raw eligibility, no decay/calibration, reps+rir cap, quality, cutoff, same-date ordering, sparse reference;
- tests/test_monitoring_definitions.py — dose, RIR, hard sets, tonnage, session load, power, spinal and demand adapters;
- tests/test_golden_prescription.py — all four session types unchanged;
- tests/test_prescribe.py and tests/test_e1rm_source.py — existing expectations unchanged;
- tests/test_workout.py — workout.get and comparison unchanged.

### 5.10 Acceptance criteria

- Golden prescriptions byte-identical.
- Load-base selector parity test proves the same result, reference, calibration flag, decay flag, coverage and decay factor.
- Raw observations apply no age decay or calibration factor.
- Raw series uses exact exercise identity and rejects invalid sets.
- No new composite scalar.
- No migration.
- ruff and relevant tests pass.

### 5.11 Risks and exclusions

Risks:

- subtle selector drift; mitigated by parity tests over synthetic and populated data;
- plan JSON provenance omitted in old snapshots; summary recomputes and flags reconstructed;
- bodyweight-added total load remains latent; excluded until weighted bodyweight e1RM is approved.

Exclusions:

- no summary UI/API yet;
- no ratio or trend;
- no calibration activation;
- no changes to volume, exposure, spinal, critique or fatigue-fitness.



## 6. Phase 2 — Descriptive workout summary

### 6.1 Objective

Add a read-only, completed-workout summary that composes existing data into the six approved sections, while preserving the existing end-screen comparison and adding no automatic behaviour.

### 6.2 Scope

- workout.summary orchestration;
- GET /api/workout/<workout_id>/summary;
- CLI summary;
- end-screen UI sections 1–5 (historical context section 6 and ratios are deferred to Phase 3);
- conditional productivity capture;
- per-field session feedback merge;
- plan snapshot e1RM provenance consumption.

Out of scope:

- ratios and Performance view;
- longitudinal trends;
- calibration activation;
- any prescription change.

### 6.3 Orchestration and files

No new features/session_summary.py. Put the orchestration in workout.py, not features, because it needs the frozen plan, workout events and _comparison. Put only pure calculations in features.monitoring and features.strength_observations.

Modify strength_coach/workout.py:

- add summary(conn, workout_id) -> dict;
- call get(conn, workout_id) to obtain plan, plan_modified, original_plan, comparison, original_comparison, sets, forms, started_at;
- reject a missing workout with a clear error; reject an in-progress workout for the summary endpoint with 409;
- call features.strength_observations for each relevant exercise;
- call features.monitoring for dose, RIR, relative intensity, hard sets, tonnage, session load, power and spinal;
- call features.session_feedback.merged for sRPE/duration/productivity;
- call the existing _comparison and original_comparison; do not alter them;
- for relative intensity, use the matching plan item's e1RM provenance when present; if the actual exercise is a substitution or the provenance is missing, recompute the load base with the strict pre-session cutoff and flag it reconstructed;
- never use the raw performance estimate as the relative-intensity denominator;
- return a JSON-safe dict with explicit nulls and statuses.

New file: strength_coach/web/static/summary.js

Responsibilities:

- fetch /api/workout/<id>/summary;
- render sections 1–5 into the ended panel; historical context is Phase 3;
- use data-action delegation, never inline handlers;
- render "Unavailable"/"Not recorded" for nulls;
- keep the existing renderWorkoutEnded comparison and post-e1RM form intact;
- no chart in Phase 2; tables and status badges only.

Modify strength_coach/web/static/workout.js:

- after renderWorkoutEnded has rendered the existing comparison, call loadWorkoutSummary(workoutId);
- do not remove or rewrite the existing comparison, rep-velocity block or post-e1RM form.

Modify strength_coach/web/static/index.html:

- add the summary.js script tag after workout.js;
- add any small detail containers needed inside the ended panel.

Modify strength_coach/web/static/app.js only if a shared formatter or nav hook is needed; do not redesign navigation.

Modify strength_coach/web/server.py:

- add GET /api/workout/<id>/summary before the generic /api/workout/<id> branch;
- return 404 for unknown workout, 409 for in-progress, 200 for completed;
- return a generic 500 on unexpected errors, preserving existing error handling.

### 6.4 API contract

GET /api/workout/<workout_id>/summary

Response:

    {
      "summary": {
        "workout_id": "...",
        "session_id": "...",
        "for_date": "...",
        "session_type": "...",
        "status": "complete",
        "completion": { ...existing comparison-derived counts... },
        "strength": [ ...raw recent reference/post/difference... ],
        "dose": { ...per exercise, relative intensity, RIR, patterns... },
        "special": { ...power, high-intensity, spinal... },
        "feedback": { srpe, duration_min, duration_source, session_load_au, productivity },
        "comparison": { n, key, metrics } or null,
        "quality": { flags, coverage },
        "basis": { performance: "raw_formula_epley_rir", decay: "not_applied", calibration: "not_applied" }
      }
    }

Rules:

- no composite "score", "workload", "fatigue" or "quality" scalar;
- null means unknown/unavailable; 0 is a real zero;
- strength rows include source set and excluded-set reasons in a details block;
- feedback includes merged values and source flags.

### 6.5 CLI

Modify strength_coach/cli.py:

- add summary subcommand with a session or workout id;
- --json emits the same dict as the API;
- text output prints section headings and "Unavailable"/"Not recorded";
- calls workout.summary; no duplicate calculations.

### 6.6 Productivity migration and feedback

This is the only Phase 2 migration and it is conditional on Domain G remaining approved.

Critical constraint: SQLite cannot drop or alter the existing CHECK on session_feedback. A simple ALTER TABLE ADD COLUMN would allow the column but still reject a productivity-only row. The migration must rebuild the table.

New file: strength_coach/store/migrations/0045_session_productivity.sql

Required steps:

1. Drop the append-only triggers on session_feedback.
2. Rename session_feedback to session_feedback_old.
3. Create session_feedback with the same columns plus productivity INTEGER NULL CHECK (productivity IS NULL OR productivity BETWEEN 1 AND 5).
4. The table CHECK becomes: srpe IS NOT NULL OR duration_min IS NOT NULL OR note IS NOT NULL OR productivity IS NOT NULL.
5. Copy all rows with productivity NULL.
6. Drop session_feedback_old.
7. Recreate the session_id/recorded_at index.
8. Recreate the no-update and no-delete triggers.
9. Verify row count and that old rows retain ids and values.

Tests must cover:

- old rows survive with null productivity;
- productivity-only row accepted;
- out-of-range productivity rejected;
- append-only triggers still reject update/delete;
- latest-row and merged reads work;
- migration is idempotent through the normal migration runner.

Modify store/repositories.py::append_session_feedback:

- add productivity: int | None = None;
- validate 1–5;
- include in the INSERT and in the at-least-one-field check.

Modify features/session_feedback.py:

- record(... productivity=...);
- merged(conn, session_id) returns latest non-null per field plus sources and recorded_at;
- latest() remains for existing callers.
- summary read precedence: sRPE = latest non-null session_feedback.srpe, else session.session_rpe when recorded, else workout_session.session_rpe; duration = latest non-null session_feedback.duration_min, else session.duration_min. Do not use a default or zero.

Modify workout.py:

- end(... productivity: int | None = None);
- _materialise(..., productivity=...);
- append feedback if srpe, duration, note or productivity is present;
- do not add productivity to workout_session; summary reads session_feedback.

Modify web/server.py::_workout_action end branch to pass productivity; modify _save_review to pass productivity; add validation errors with field names.

Modify web/static/workout.js:

- add the five optional productivity choices to the end form;
- pass productivity to /end;
- do not require it;
- show "Not recorded" when skipped.

Modify web/static/app.js review form:

- add the same optional productivity field;
- pass productivity to /api/review;
- no required field.

Modify CLI review:

- add --productivity 1-5;
- pass through to session_feedback.record.

### 6.7 Summary content

Section 1 — Completion:

- use _comparison and original_comparison;
- completed working sets, reps, per-item status, substitutions, extra sets;
- no zero dose for missing items.

Section 2 — Strength performance:

- raw recent reference, best recent single session, post best, difference kg/%;
- status descriptive/limited/single_prior/insufficient_quality/unavailable;
- source set and excluded-set reasons;
- no clear/meaningful/significant labels.

Section 3 — External dose:

- per-exercise sets/reps/tonnage, coverage;
- relative-intensity distribution and unknown count;
- RIR distribution and coverage;
- hard/near-failure sets;
- pattern distribution using volume_target_key.

Section 4 — Special exposure:

- power sets/reps and mean velocity change;
- high-intensity exposures linked to the session;
- spinal effective cost, weekly position, heavy-spinal count;
- axial demand mix with unknown count;
- quality stop "not recorded" unless an explicit event exists.

Section 5 — Feedback:

- merged sRPE, duration with source, session load AU, productivity;
- labels: immediate sRPE, internal load, arbitrary units;
- missing values show "Not recorded".

Section 6 — Historical context (Phase 3 only):

- Phase 2 renders no comparison; it may show "Not available until the historical view is enabled".
- Phase 3 adds the comparable-session summary, only if at least 3 comparable sessions exist;
- median of prior comparable sessions, n, comparison key;
- withhold deload/technique/minimum or <50% overlap.

### 6.8 Tests

New file: tests/test_session_summary.py

Cases:

- completed workout with known sets produces expected completion, dose, RIR, tonnage, hard sets;
- warm-up excluded;
- missing RIR yields unknown, not zero;
- no e1RM denominator yields unavailable relative intensity;
- degraded post yields insufficient_quality;
- session load missing when either input missing;
- productivity-only feedback accepted after migration;
- merged feedback uses latest non-null per field;
- spinal cost equals weekly_spinal_costs for the session;
- power excluded from RIR/hypertrophy counts;
- no composite key in payload.

New file: tests/test_monitoring_api.py

Cases:

- GET summary returns 200 for completed workout;
- 404 unknown;
- 409 in-progress;
- nulls render as null, not 0;
- no score/workload/fatigue/quality scalar;
- response includes basis raw/not_applied.

Extend tests/test_workout.py:

- end with productivity materialises session_feedback;
- summary after edit uses corrected sets;
- plan-versus-actual comparison unchanged.

Extend tests/test_web.py and test_ui_frontend.py:

- new script exists and loads after workout.js;
- no inline handlers;
- end form productivity is optional;
- summary panel has section-help and one doc-link where applicable.

### 6.9 Acceptance criteria

- Summary is read-only and deterministic.
- Existing comparison, rep-velocity block and post-e1RM form unchanged.
- Every headline number traceable to a set, feedback row or registry call.
- Raw performance series has no decay/calibration.
- Productivity optional and absent from every calculation.
- No automatic prescription change.
- Migration tested with old and new rows.
- No ratios, longitudinal trends or historical comparison yet.

### 6.10 Risks and exclusions

Risks:

- session_feedback rebuild is the highest-risk change; require backup, migration tests and a rollback plan;
- summary payload may become too dense; enforce progressive disclosure;
- productivity may be skipped; default null and no friction;
- old plan snapshots lack e1RM provenance; recompute load base and flag reconstructed.

Exclusions:

- no ratio display on the end screen in Phase 2 (Phase 3 adds at most two);
- no Performance page;
- no calibration factor;
- no automatic conclusions.

---

## 7. Phase 3 — Longitudinal strength and relative strength

### 7.1 Objective

Add the Performance view with raw e1RM observations, rolling median, exercise selection, series breaks, dose context, configured relative-strength ratios and comparable-session comparison.

### 7.2 Scope

- features/strength_trend.py;
- features/relative_strength.py;
- config/strength-relationships.v1.yaml;
- GET /api/performance/e1rm, /dose, /ratios;
- CLI performance subcommands;
- Performance view and script;
- comparable-session summary added to the end screen section 6;
- no migration.

### 7.3 Strength trend design

New file: strength_coach/features/strength_trend.py

Functions:

- observations(conn, exercise_id, from_date, to_date) -> list[RawObservation]
- rolling_median(observations, n=3) -> list[TrendPoint]
- series_breaks(observations, taxonomy) -> list[Break]
- summarize(observations, config) -> TrendSummary

Rules:

- one point per session, raw e1RM;
- exact exercise identity; no variant pooling;
- no interpolation or extrapolation;
- <3 observations: points only; <5: no trend statement;
- rolling median of 3 is descriptive, not a model;
- series break markers on exercise/equipment/load-basis changes;
- degraded observations shown separately, not in the primary line.

### 7.4 Relative strength design

New file: strength_coach/features/relative_strength.py

Config: config/strength-relationships.v1.yaml

Functions:

- load_relationships(path) -> list[Relationship]
- validate_relationships(taxonomy, relationships) -> issues
- current_ratio(conn, relationship, on_date) -> Ratio | Unavailable
- ratio_trend(conn, relationship, from_date, to_date) -> list[RatioPoint]

Rules:

- latest eligible raw session best per side;
- both sides ok;
- at least 2 eligible observations per side;
- date gap ≤14 days; age ≤42 days;
- dates, gap, counts and data-sufficiency status always returned;
- no independent smoothing then division;
- no target ratio or diagnosis.

### 7.5 API and CLI

GET /api/performance/e1rm?exercise_id=&from=&to=

GET /api/performance/dose?from=&to=&group_by=session

GET /api/performance/ratios?relationship_id=&from=&to=

Response rules:

- no composite score;
- null/unavailable explicit;
- ratio status available/insufficient_history/insufficient_quality/stale_or_gap/unavailable;
- include method/basis raw_formula_epley_rir.

CLI:

- performance e1rm
- performance dose
- performance ratios
- --json parity with API.

### 7.6 Performance UI

New file: strength_coach/web/static/performance.js

Modify index.html:

- add Performance nav button and view section;
- add performance.js script tag;
- add filters: exercise, date range, session type, include deloads, minimum quality.

Modify app.js:

- route Performance to loadPerformance;
- no changes to unrelated views.

UI components:

- summary cards for latest, recent median, change from median (descriptive), coverage;
- inline SVG line/points with accessible title and table fallback;
- ratio table with numerator/denominator dates, gap, counts, status;
- sparse states;
- no hover-only tooltips; use details blocks.

### 7.7 Comparable-session comparison

Reuse workout._comparison for individual sessions; implement a comparison key:

- same session_type;
- at least one common main lift;
- not deload/technique/minimum;
- within 8 weeks;
- ≥50% exercise overlap;
- ≥3 prior comparable sessions.

Return medians and n. Withhold otherwise.

### 7.8 Tests

New files:

- tests/test_strength_trend.py
- tests/test_relative_strength.py
- tests/test_performance_api.py
- tests/test_comparisons.py

Cases:

- 0/1/2/3/5 observations;
- no interpolation;
- series break on identity/equipment change;
- raw only; no decay/calibration;
- ratio with 1 observation per side -> unavailable due to insufficient history;
- ratio with 2+ both sides and gap/age gates -> available;
- dates/counts/status present;
- no target ratio or ranking;
- API nulls and no composite keys.

UI tests:

- script exists and parses;
- nav/view exists;
- mobile CSS does not force page-level horizontal scroll;
- no inline handlers.

### 7.9 Acceptance criteria

- Trend lines only with ≥3 observations; no change statement with <5.
- Ratio only with ≥2 per side; latest raw per side; dates/counts/status visible.
- No interpolation or target ratios.
- No diagnostic or confidence language.
- Performance view works in iPhone portrait/landscape.
- No migration.

### 7.10 Risks and exclusions

Risks:

- sparse accessory data; show unavailable rather than lower the bar;
- UI density; progressive disclosure;
- SVG accessibility; table fallback.

Exclusions:

- no exploratory dose-response modelling;
- no calibration factor;
- no automatic conclusions.



## 8. Phase 4 — Exploratory analysis and calibration preparation

### 8.1 Objective

Add defensible comparable-session summaries and descriptive analysis, and prepare the calibration observation layer without activating any calibration factor.

### 8.2 Scope

- descriptive dose-response and recovery analysis;
- calibration observation read model;
- formula/method version exposure;
- no new comparison engine (Phase 3 owns the comparable-session summary);
- no active calibration factor;
- no new schema.

### 8.3 Comparison boundary

Phase 3 owns the comparable-session key and summary. Phase 4 must not create a second comparison engine. If additional comparison metrics are needed later, extend the Phase 3 function and its tests; do not duplicate the key or the median calculation.

### 8.4 Exploratory analysis

New file: tools/monitoring_analysis.py

Outputs:

- descriptive dose-response tables;
- lagged associations with next-session performance;
- missingness and n;
- simple baseline comparisons;
- reproducibility seed.

Rules:

- no causal language;
- no model adoption;
- no automatic prescription change;
- report file local-only if personal data is present;
- public summary only if redacted.

No new dependency. Use pandas/numpy only.

### 8.5 Calibration observation read model

New file: strength_coach/features/calibration_observations.py

This is a read-only builder, not a calibration engine.

Function:

    observations(conn, *, exercise_id=None, from_date=None, to_date=None)
        -> list[CalibrationObservation]

CalibrationObservation fields:

- observation_id / source override id;
- exercise_id;
- performed_on;
- test_type (from high_intensity_exposure, if linked);
- measured_kg;
- measured_source (user, measured, clinician);
- prior_raw_e1rm_kg;
- prior_raw_method;
- prior_raw_method_version;
- prior_raw_observed_on;
- prior_raw_ref / set id;
- date_gap_days;
- protocol: unknown (not captured);
- equipment: unknown (not captured);
- eligibility / exclusion reason;
- linked_exposure_id.

Linking rules:

- only e1rm_override.source = measured (or clinician, explicitly labelled);
- link high_intensity_exposure by source_id = e1rm_override:<id>;
- prior raw estimate must be strictly before the test date;
- same exercise identity;
- no ordinary training set used as a criterion.

No factor, no promotion, no historical rewrite.

### 8.6 Formula version

Reuse the Phase 1 E1RM_METHOD_VERSION constant from strength_coach/domain/e1rm.py. Return it in raw estimates and calibration observations. Do not add a database column yet.

### 8.7 Tests

- tests/test_calibration_observations.py
  - measured test links to exposure;
  - prior estimate strictly before test;
  - missing exposure yields test_type unknown;
  - ordinary set is never a criterion;
  - no calibration factor is produced;
  - method version present.
- tests/test_monitoring_analysis.py
  - lags, missingness, reproducible output;
  - no writes to training records.

### 8.8 Acceptance criteria

- Phase 3 comparable-session summaries remain the only comparison engine.
- Calibration observation read model is read-only and does not fit a factor.
- Formula/method version is exposed in raw outputs.
- No new schema.
- No automatic promotion.

### 8.9 Risks and exclusions

Risks:

- tiny measured-test sample;
- protocol/equipment unknown makes calibration observations incomplete;
- exploratory analysis overinterpretation.

Exclusions:

- no calibration engine;
- no factor table;
- no prospective activation;
- no causal claims.

---

## 9. Phase 5 — Prospective validation and future calibration (deferred activation)

### 9.1 Objective

Define the gate for any future individual calibration. Do not implement an active factor in this plan.

### 9.2 Required data before activation

- repeated standardised measured tests with known test_type, protocol, equipment and date;
- per-lift coverage across rep ranges and time;
- prospective sessions with raw observations and load-base outputs;
- a pre-registered validation plan.

### 9.3 Future schema (deferred; not part of current implementation)

Proposed, not approved:

1. Extend e1rm_override with nullable columns:
   - test_type;
   - protocol;
   - equipment;
   - formula_version;
   - prior_estimate_kg;
   - prior_estimate_ref.
   Existing rows remain unknown.

2. New append-only e1rm_calibration_factor table:
   - factor_id;
   - exercise_id;
   - method_version;
   - factor;
   - sample_n;
   - validation_method;
   - validation_mae;
   - validation_mape;
   - effective_from / expires_on;
   - supersedes_id;
   - created_at.

3. No monitoring-metric table and no rewriting of clean_set.

### 9.4 Promotion criteria

A calibration factor may be promoted only when all hold:

- derived from genuine measured tests, not ordinary sets;
- per-lift sample size and rep-range coverage are pre-registered and adequate for the method;
- chronological out-of-sample validation shows lower MAE/MAPE than the uncalibrated formula;
- the improvement is stable across rep ranges and time periods;
- the factor is bounded and its uncertainty is reported;
- no historical observation is rewritten; the factor applies only to future load-base calculations;
- versioned, auditable and reversible;
- reviewed and approved as a decision record.

| Gate | Criterion | Current status |
|---|---|---|
| G1 | Genuine measured tests only; no ordinary training set is a criterion | Required |
| G2 | Per-lift sample and rep-range coverage are pre-registered from the Phase 0/4 data, not invented in advance | Open; depends on data |
| G3 | Chronological out-of-sample validation: fit on earlier tests, evaluate on later tests | Required |
| G4 | Calibrated MAE/MAPE is lower than the uncalibrated formula by a pre-specified margin | Required |
| G5 | The improvement is stable across rep ranges and time periods, and does not worsen any stratum | Required |
| G6 | Factor is bounded, its uncertainty is reported, and the existing MOD-E1RM-001 gates are satisfied | Required |
| G7 | Factor is versioned, auditable, reversible, and never rewrites raw historical observations | Required |

No factor is promoted because a sample-count threshold was reached. G1–G7 are process gates; G2 is deliberately unresolved until the audit establishes what the data can support.

The existing MOD-E1RM-001 gates (minimum tests, bootstrap CI excluding 1, ±10% bound) remain the starting point, not a sufficient promotion rule.

### 9.5 What remains deferred

- active factor calculation or application;
- automatic promotion on sample count;
- calibration on the raw performance series;
- calibration of relative-strength ratios;
- any prescription change from monitoring data.

---

## 10. File-level change inventory

| File | Action | Phase | Purpose |
|---|---|---|---|
| strength_coach/features/strength_observations.py | Create | 0 | Raw set/session observations, recent reference, best/personal best, difference |
| tools/monitoring_historical_audit.py | Create | 0 | Read-only historical audit |
| tests/test_monitoring_historical_audit.py | Create | 0 | Audit tests |
| tests/test_strength_observations.py | Create | 0/1 | Raw estimator tests |
| private/docs/MONITORING-HISTORICAL-AUDIT.md | Generate locally | 0 | Private audit report |
| strength_coach/features/e1rm_source.py | Create | 1 | Pure load-base selector |
| strength_coach/features/monitoring.py | Create | 1 | Dose, feedback, power, spinal adapters |
| strength_coach/features/exposure.py | Modify | 1 | Expose is_hard_set; no behaviour change |
| config/monitoring.v1.yaml | Create | 1 | Display bands, windows, statuses, flags |
| strength_coach/prescribe/engine.py | Modify | 1 | Delegate to e1rm_source; preserve behaviour |
| strength_coach/prescribe/models.py | Modify | 1 | Optional e1RM provenance fields |
| strength_coach/web/server.py | Modify | 1/2/3 | _item_dict fields; summary/performance routes |
| strength_coach/features/session_feedback.py | Modify | 1/2 | merged(); productivity |
| tests/test_e1rm_source_shared.py | Create | 1 | Selector parity |
| tests/test_monitoring_definitions.py | Create | 1 | Definition tests |
| strength_coach/workout.py | Modify | 2 | summary(); end productivity; plan fields |
| strength_coach/store/migrations/0045_session_productivity.sql | Create conditional | 2 | Rebuild session_feedback with productivity |
| strength_coach/store/repositories.py | Modify | 2 | append_session_feedback productivity |
| strength_coach/web/static/summary.js | Create | 2 | End-screen summary |
| strength_coach/web/static/workout.js | Modify | 2 | End form and summary hook |
| strength_coach/web/static/app.js | Modify | 2/3 | Review productivity; Performance route |
| strength_coach/web/static/index.html | Modify | 2/3 | Script tags, summary containers, Performance view |
| strength_coach/web/static/performance.js | Create | 3 | Performance view |
| strength_coach/cli.py | Modify | 2/3 | summary and performance commands |
| strength_coach/features/strength_trend.py | Create | 3 | Raw series and rolling median |
| strength_coach/features/relative_strength.py | Create | 3 | Configured ratios |
| config/strength-relationships.v1.yaml | Create | 3 | Explicit ratio pairs |
| strength_coach/features/comparisons.py | Create | 3 | Comparable-session key and summary |
| strength_coach/features/calibration_observations.py | Create | 4 | Read-only calibration observations |
| tools/monitoring_analysis.py | Create | 4 | Descriptive analysis |
| tests/test_session_summary.py | Create | 2 | Summary definitions/API |
| tests/test_monitoring_api.py | Create | 2 | Summary API contract |
| tests/test_web.py | Modify | 2/3 | Include new client scripts in the served bundle; API assertions |
| tests/test_strength_trend.py | Create | 3 | Trend tests |
| tests/test_relative_strength.py | Create | 3 | Ratio tests |
| tests/test_performance_api.py | Create | 3 | Performance API |
| tests/test_comparisons.py | Create | 3 | Comparability |
| tests/test_calibration_observations.py | Create | 4 | Calibration read model |
| docs/UI-MAP.md | Modify at implementation | 2/3 | New view/panel map |
| docs/WEB-UI.md | Modify at implementation | 2/3 | API/UI documentation |
| ROADMAP.md | Modify at implementation | 2/3 | Phase status |
| docs/DECISIONS.md | Modify only if a new decision is approved | 2/4 | Productivity/migration/calibration decisions |

No other application files should be changed.

---

## 11. Data and schema implications

### 11.1 No migration for monitoring metrics

All monitoring metrics are computed on read from immutable rows. Do not create tables for session summaries, e1RM series, ratios, tonnage or trends.

### 11.2 Phase 2 productivity migration

Only if Domain G remains approved. Because of the existing CHECK, use a rebuild migration, not a bare ALTER.

SQL shape (implementation detail, not executed here):

    -- 0045_session_productivity.sql
    DROP TRIGGER session_feedback_no_update;
    DROP TRIGGER session_feedback_no_delete;

    ALTER TABLE session_feedback RENAME TO session_feedback_old;

    CREATE TABLE session_feedback (
        feedback_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES session(session_id),
        srpe REAL CHECK (srpe IS NULL OR (srpe >= 1 AND srpe <= 10)),
        duration_min REAL CHECK (duration_min IS NULL OR (duration_min > 0 AND duration_min <= 600)),
        productivity INTEGER CHECK (productivity IS NULL OR (productivity >= 1 AND productivity <= 5)),
        note TEXT,
        recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        CHECK (srpe IS NOT NULL OR duration_min IS NOT NULL OR note IS NOT NULL OR productivity IS NOT NULL)
    );

    INSERT INTO session_feedback (feedback_id, session_id, srpe, duration_min, productivity, note, recorded_at)
    SELECT feedback_id, session_id, srpe, duration_min, NULL, note, recorded_at
    FROM session_feedback_old;

    DROP TABLE session_feedback_old;
    CREATE INDEX idx_session_feedback_session ON session_feedback(session_id, recorded_at);
    CREATE TRIGGER session_feedback_no_update BEFORE UPDATE ON session_feedback
    BEGIN SELECT RAISE(ABORT, 'append-only: session_feedback rows cannot be updated'); END;
    CREATE TRIGGER session_feedback_no_delete BEFORE DELETE ON session_feedback
    BEGIN SELECT RAISE(ABORT, 'append-only: session_feedback rows cannot be deleted'); END;

Migration tests must verify old rows, productivity-only rows, range checks, triggers, index and latest/merged reads.

### 11.3 No migration for plan provenance

PrescriptionItem and plan_json are JSON/serialisation changes. Do not add prescription_item columns for e1RM provenance in this plan.

### 11.4 Future calibration migrations (deferred)

Only after Phase 4/5 and approval:

- nullable measured-test metadata on e1rm_override, or a companion table;
- append-only e1rm_calibration_factor;
- no raw-estimate persistence and no monitoring-metric tables.

### 11.5 Indexes and performance

Existing indexes on clean_set support session, date and exercise queries. Do not add speculative indexes. Phase 0 must time the audit; if a query is slow, add an index only with evidence and a migration review.

---

## 12. Testing and acceptance matrix

| Phase | Unit | Regression | Integration/API | UI | Data/privacy |
|---|---|---|---|---|---|
| 0 | Raw observation rules; audit counts | None | Synthetic DB; optional populated_db | None | Read-only, private default |
| 1 | Selector parity; monitoring definitions | Golden prescriptions; existing e1RM tests | Selector on populated data | None | No writes |
| 2 | Summary definitions; feedback merge | Workout end/comparison unchanged | Summary API; migration | End form, summary rendering | Migration rehearsal; backup |
| 3 | Trend, ratios, comparability | Existing progress unchanged | Performance API | Performance view | No writes |
| 4 | Calibration observations; exploratory analysis | None | Descriptive analysis | Table only | Local report |
| 5 | Future | Future | Future | Future | Deferred |

### 12.1 Required regression gates

- tests/test_golden_prescription.py passes unchanged.
- tests/test_prescribe.py and tests/test_e1rm_source.py pass unchanged.
- tests/test_workout.py comparison and end behaviour pass.
- tests/test_web.py existing endpoints pass.
- tests/test_ui_frontend.py script and handler contracts pass.
- tests/test_docs_consistency.py passes after any doc update.

### 12.2 Test data policy

- Public tests use make_training/make_readiness or tiny synthetic frames.
- No test reads data/raw unless marked integration and kept private.
- Audit tests must assert read-only behaviour.
- No test asserts personal counts or values.

### 12.3 Performance tests

- Audit on a synthetic 10k-set database completes within a documented bound and uses one pass where practical.
- Summary on a session with 100 sets returns in interactive time.
- Trend query on 5 years of a main lift returns in interactive time.
- Benchmark tests may be marked integration or run manually; do not add flaky timing assertions to the fast lane.

### 12.4 CI gates

- ruff check .
- python -m pytest (full suite before handoff/commit).
- python tools/check_ui_docs.py after adding a UI view or panel.
- tests/test_docs_consistency.py and the docs-PDF collection test after documentation changes.
- No new dependency.

---

## 13. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Load-base extraction changes prescriptions | Medium | High | Pure adapter, parity tests, golden prescriptions, no formula changes |
| session_feedback rebuild loses rows/triggers | Medium | High | Backup, migration test, row-count check, trigger/index recreation, rehearsal on copy |
| Raw and calibrated series get mixed | Medium | High | Separate modules, explicit basis fields, tests with calibration/decay active |
| Ratio displays with <2 observations | Medium | Medium | Single status gate, API/UI tests |
| UI becomes too dense on iPhone | High | Medium | Progressive disclosure, cards, details blocks, SVG with table fallback |
| Audit leaks personal data | Medium | High | private/docs default, no commit, redacted summary only if approved |
| Sparse accessory data creates misleading trends | High | Medium | Unavailable/insufficient states, no interpolation |
| Formula bias is mistaken for accuracy | Medium | High | Phase 0 report, raw bias caveat, no criterion from ordinary sets |
| Future calibration overfits | Medium | High | Chronological holdout, promotion gates, no auto activation |
| Duplicate calculations | Medium | Medium | Shared features modules; code review against mapping |
| Existing e1rm_calibration date/progress defects confuse monitoring | Low | Medium | Do not reuse those outputs; document as out of scope |
| Migration ordering/CI | Low | High | Numbered migration, test on copy, docs consistency |

---

## 14. Individual calibration roadmap

### 14.1 Current state

- Measured tests are recorded through the test path into e1rm_override(source=measured) and a linked high_intensity_exposure(source_id=e1rm_override:<id>).
- e1rm_calibration.build reports calibration points from measured overrides and prior formula estimates.
- e1rm_calibration.factors supplies a correction to the load-base selector only.
- No formula version, protocol, equipment, calibration-factor table or promotion workflow exists.
- Ordinary training sets are not criterion measurements.

### 14.2 Architectural separation

| Layer | Definition | State now | Future |
|---|---|---|---|
| Raw performance observation | Epley/Epley+RIR set/session best, no decay/calibration | New module in Phase 0/1 | Permanent primary series |
| Load-base e1RM | Existing selector + calibration + decay + override | Existing engine; extracted adapter | May consume a validated factor later |
| Individual calibration | Measured-test observations and factor | Read model only in Phase 4 | Versioned factor table and promotion in Phase 5 |

### 14.3 Now

- raw observation method/version;
- keep raw series untouched by calibration/decay;
- expose method version in API/pseudocode outputs;
- no factor engine.

### 14.4 Prepared

- calibration observation read model (Phase 4);
- linking e1rm_override to high_intensity_exposure;
- prior raw estimate before the test;
- method version;
- explicit unknown protocol/equipment fields;
- tests for linkability and no leakage.

### 14.5 Deferred

- measured-test metadata schema;
- calibration-factor table;
- fitting/promotion;
- applying a factor to the load base;
- prospective validation.

### 14.6 Promotion principles

- genuine measured tests only;
- pre-registered sample/rep-range requirements;
- chronological out-of-sample validation;
- calibrated error lower than uncalibrated, stable across strata;
- bounded, versioned, reversible;
- no rewriting of raw history;
- explicit decision record.

### 14.7 What would make calibration inappropriate

- too few tests;
- unknown protocol/equipment;
- bias not stable across rep ranges;
- improvement disappears out of sample;
- factor larger than the existing bounded correction without justification.

---

## 15. Dependencies and recommended execution order

    0. Phase 0 audit
    1. Phase 1 core (depends on Phase 0)
    2. Phase 2 summary (depends on Phase 1; productivity decision/migration)
    3. Phase 3 trends/ratios (depends on Phase 2)
    4. Phase 4 exploratory analysis/calibration prep (depends on Phase 3)
    5. Phase 5 prospective/future calibration (depends on Phase 4 and data)

Phase 0 and Phase 1 must not be merged: the audit informs whether the raw observation rules leave enough data, and Phase 1 should not build UI on unmeasured assumptions.

Phase 2 and Phase 3 may be developed in parallel only after Phase 1 stabilizes the observation API; the summary should land first because it validates the metric composition.

---

## 16. Explicit items that must not be implemented

1. A universal 0–100 workout, workload, quality, stimulus or fatigue score.
2. A composite readiness, fatigue or performance score.
3. Any automatic prescription, deload or exercise-selection change from monitoring.
4. Injury-risk prediction or an ACWR "sweet spot".
5. Age decay or calibration on raw performance observations.
6. Treating ordinary training sets as measured strength tests.
7. Within-set velocity loss from mean velocity.
8. RIR inference or imputation from velocity/reps.
9. Power quality inference from mean velocity.
10. A measured spinal load or injury probability from ordinal spinal cost.
11. Productivity as a workload or prescription input.
12. Cross-exercise e1RM conversion or variant pooling.
13. Ratio targets, population norms or weakness diagnosis.
14. A new monitoring-metric table or persisted derived metrics.
15. A calibration factor engine or active calibration now.
16. A second specification or parallel calculation stack.
17. Changes to critique, fatigue-fitness, volume, exposure or spinal models.
18. New dependencies or chart libraries.
19. A UI redesign outside the monitoring views.
20. Any commit of personal training data.

---

## 17. Unresolved questions and decisions required before execution

| # | Question | Why it blocks | Recommendation |
|---|---|---|---|
| Q1 | Is the productivity migration approved, given the table rebuild? | It is the only Phase 2 migration and carries data risk | Approve rebuild with backup and migration tests, or defer Domain G |
| Q2 | Should the Phase 0 report be committed or local-only? | Privacy | Default private/docs; commit only a redacted summary if approved |
| Q3 | Are plan-JSON e1RM provenance fields added in Phase 1 or recomputed in Phase 2? | Affects summary traceability | Add optional fields in Phase 1; old snapshots recompute |
| Q4 | How many genuine measured tests are available? | Determines whether calibration is possible | Phase 0 establishes; do not assume |
| Q5 | What sample size and strata are required for future calibration promotion? | Cannot be invented now | Phase 0/4 feasibility; separate decision |
| Q6 | Should the progress applicability and e1rm_calibration date-label defects be fixed in this work? | They are existing behaviour | No; separate change, documented |
| Q7 | Should manual duration be reclassified from measured to manual? | Affects rubric/attendance | No; summary labels it, preserves behaviour |
| Q8 | Is a new Performance top-level view approved? | UI scope | Yes per specification; implement as specified |
| Q9 | Should ratios appear on the end screen in Phase 2? | Density | No; Phase 3 adds at most two |
| Q10 | Should best-recent/personal-best appear on the summary or only details? | UI density | Summary context line; details expandable |

---

## 18. Final checklist for approving implementation

- [ ] The specification remains unchanged and authoritative.
- [ ] Phase 0 is approved as the first deliverable.
- [ ] The load-base selector extraction plan has a parity test and golden-prescription gate.
- [ ] Raw performance observations are explicitly raw; no decay/calibration.
- [ ] Ratio minimum 2 per side is implemented in one place and tested.
- [ ] session_feedback migration is approved as a rebuild, or Domain G is deferred.
- [ ] No monitoring metric is persisted in a new table.
- [ ] No composite score exists in API/UI.
- [ ] No automatic prescription/injury/fatigue connection exists.
- [ ] UI plan is mobile-first and uses existing components.
- [ ] Tests are mapped to every phase.
- [ ] Privacy plan keeps personal data out of Git.
- [ ] Future calibration is read-only/preparatory, not active.
- [ ] Unresolved questions have owners and decisions.

---

## 19. Related documents

- [Training monitoring design specification](TRAINING-MONITORING-SPEC.md)
- [Data model](../DATA-MODEL.md)
- [Decisions](../DECISIONS.md)
- [Data quality](../DATA-QUALITY.md)
- [References](../REFERENCES.md)
- [Web UI](../WEB-UI.md)
- [UI map](../UI-MAP.md)
- [Roadmap](../../ROADMAP.md)
- [Fatigue, fitness and strength](../FATIGUE-FITNESS.md)
- [Volume management](../VOLUME-MANAGEMENT.md)
- [High-intensity exposure](../HIGH-INTENSITY-EXPOSURE-PLAN.md)
- [Spinal cost](../SPINAL-COST.md)
- [Exercise demands](../EXERCISE-DEMANDS.md)
- [Per-rep velocity](../REP-VELOCITY.md)
- [VBT evidence](../VBT-EVIDENCE.md)
- [Parent-variant ratios and weakness](../PARENT-VARIANT-WEAKNESS-EVIDENCE.md)
- [Privacy](../PRIVACY.md)
- [Limitations register](../LIMITATIONS-REGISTER.md)
- [Repository instructions](../../AGENTS.md)

---

## 20. Plan revision

| Date | Revision | Change |
|---|---|---|
| 2026-10-30 | 1 | Initial implementation plan for the approved specification at 2711a6e |

