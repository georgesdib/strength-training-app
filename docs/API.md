# HTTP API

The local server exposes the same core functions as the CLI. This is the API reference;
page behaviour and UI surfaces are in [WEB-UI.md](WEB-UI.md).

---

## Routes

| route | purpose |
|---|---|
| `GET /api/overview` | dashboard data, including the read-only `programme_header` |
| `GET /api/progress?date=&weeks=` | descriptive attendance aggregate, weekly average volume, sRPE coverage, recent performance-ratio observations and observed weekly RIR/tonnage/residual series (`weekly`, `missing_weeks`) |
| `GET /api/adherence/analytics?date=&weeks=&from=&to=&exercise_id=&session_type=&group_by=week\|month` | summed prescription-adherence totals, periods, exercise comparison and completed-workout drill-down; app-tracked completed workouts only |
| `GET /api/outcomes?weeks=&date=` | read-only strength, volume, attendance, readiness, cardio, measurement and symptom summaries |
| `GET /api/performance/e1rm?exercise_id=&from=&to=` | raw e1RM observations, rolling median, breaks and descriptive summary |
| `GET /api/performance/dose?from=&to=&group_by=session` | descriptive session dose |
| `GET /api/performance/ratios?relationship_id=&from=&to=` | configured ratio current value and paired history |
| `GET /api/performance/vbt?from=&to=&exercise_id=` | longitudinal frozen-target cohorts, weekly residuals, band/RIR evidence, within-set velocity drift and per-set drill-down; default range is 84 days |
| `GET /api/performance/relationships` | merged relationship configuration, source provenance and revision |
| `POST /api/performance/relationships` | add a validated local relationship; requires the current revision |
| `POST /api/performance/relationships/{id}/update\|delete\|reset` | edit, hide or reset a local relationship override; requires the current revision; stale revisions return 409 |
| `GET /api/monitoring-analysis?as_of=` | read-only dose, lagged associations, coverage and calibration transparency; no path disclosure |
| `GET /api/settings/monitoring` | read-only monitoring/config inventory, canonical/local/default/code provenance, Phase 5A period and lock, complete effective-inventory revision; no paths or athlete data |
| `POST /api/import` | `{training: {name, text}, readiness: {name, text}}` -> import report |
| `POST /api/prescribe` | `{date, session_type?, apply_selection?, selection_confirmed?, minimum_session?, target_minutes?, minimum_include_main?, allow_unknown_readiness?}` -> prescription; `session_type=auto` uses the rolling rule; unknown readiness requires the explicit flag; with `minimum_session`, `target_minutes` must be one of the configured targets (30/45/60) and is a 400 otherwise |
| `POST /api/workout/start` | `{date, plan, readiness, readiness_ack?, note?}` -> live workout; a score-ready assessment or explicit acknowledgement is required; partial readiness stays partial |
| `GET /api/workout/active` | active workout, or `{workout: null}` |
| `GET /api/workout/<id>` | workout detail |
| `GET /api/workout/<id>/summary` | completed-workout descriptive summary: adherence, VBT, dose, strength, feedback, data-quality flags, reproducible evidence ids and at most one deterministic observation; 404 unknown, 409 in progress |
| `GET /api/form-trend?weeks=N&date=N` | descriptive current/baseline form trend |
| `POST /api/workout/<id>/form` | `{exercise_id, rating 1-5}` -> optional post-lift form rating |
| `POST /api/workout/<id>/sets` | `{exercise_id, load_kg, reps, rir, velocity?, plan_item_index?}` -> add manual set; explicit plan-item identity is validated against the frozen exercise; omitted identity resolves only a unique item |
| `POST /api/workout/<id>/remove-set` | `{set_id}` -> append a removal event |
| `POST /api/workout/<id>/end` | `{session_rpe?, not_recorded?, duration_min?, productivity?, notes?}` -> completed |
| `POST /api/workout/<id>/update-set` | `{set_id, load_kg, reps, rir, velocity}` -> append correction event |
| `POST /api/workout/<id>/import` | `{text, rep_text?, apply}` -> parse/preview/apply workout CSV; optional per-rep table; no date column |
| `POST /api/workout/<id>/import/undo` | undo the latest import batch, including rep detail |
| `GET /api/history?limit=&offset=&start=&end=` | paginated session-fragment history |
| `GET /api/history/days?limit=&offset=&start=&end=` | paginated training days with their fragments; each fragment carries `final_set` (final-set heart-rate recovery, or null) so the list row can show how the session ended without opening it |
| `GET /api/exercise-history?exercise_id=&limit=&offset=&on_or_before=` | read-only completed-session history for one exercise, grouped by session; limit counts sessions and defaults to 5 |
| `GET /api/history/<id>` | current session sets, feedback and completed-workout prescription adherence; `heart_rate` carries Apple's `avg_bpm`/`max_bpm` from the workout currently linked to the session, or `null` when none is linked (never a zero); each set carries `hrr60_bpm` (heart-rate drop 60 s after the set, or null) and the session carries `hr_recovery` with the measured-set count, its caveat, and `final_set` (`hr_end_bpm`, `hrr60_bpm`, `hrr120_bpm`, anchored to the last set's completion rather than the finish tap). All display-only and excluded from adherence, readiness and prescriptions |
| `POST /api/history/<id>/edit` | append-only correction of sets and session metadata; accepts `session_rpe`, `duration_min`, `productivity` (1-5), `notes` and `reason`, and returns the corrected session with merged feedback |
| `POST /api/history/<id>/vbt` | set/rep VBT overrides (also accepted inside `/edit`) |
| `POST /api/history/<id>/void` | void or unvoid a whole session |
| `GET /api/rep-velocity?session=<id>` | descriptive per-rep report after completion |
| `GET /api/rep-velocity/analysis?weeks=&date=` | stratified cross-session descriptive report |
| `POST /api/workout/<id>/abandon` | abandon the active workout |
| `GET /api/review/<session>` | read-only historical rubric sheet: stored `rubric_score` rows and `rubric_mark` marks; nothing is re-scored | session detail |
| `GET /api/readiness/<date>` | merged readiness; `registry_version` names the effective readiness registry |
| `GET /api/readiness/schema?date=` | effective readiness registry: version, metrics with label/scale/direction, min fields, require-any-of and wearable weight; the contract forms render from |
| `GET /api/readiness/registry/history` | append-only registry versions, newest first |
| `POST /api/readiness/registry` | `{payload, note?}` -> validate and append a version effective today; never updates history |
| `POST /api/readiness/registry/metrics` | `{key, label, role, weight, scale_min?, scale_max?, higher_is_better?, unit?, baseline_days?, min_readings?, slope?, counts_as_core?, required?, order?, note?}` -> create a new `metric_definition` and a registry version atomically |
| `POST /api/readiness/registry/preview` | `{payload, date?}` -> validate a draft and list its changes against the effective version |
| `GET /api/readiness/history?from=&to=&fields=` | inclusive observed readiness/bodyweight series with per-field sources; requires date bounds, merges manual-over-import per field, no fill |
| `POST /api/readiness` | `{date, values, note}` -> merged readiness + score |
| `POST /api/readiness/override` | `{date, scope, value, reason}` -> merged readiness + score |
| `GET /api/readiness/calibrate` | calibration report text (no auto-apply) |
| `GET /api/logs?limit=N` | recent in-memory application/HTTP log records (max 500; cleared on restart) |
| `GET /api/state` | profile, constraints, suitability, e1RM overrides, the combined `e1rm_override_ledger` (overrides and dated withdrawals with status), symptoms, attributed symptoms, injury signal |
| `GET /api/symptoms/attribution-options?onset=&timing=` | completed sessions and performed lifts available for an attributed symptom |
| `GET /api/exercises` | canonical exercise catalogue for the pickers: `id`, `display`, `pattern` and `time_based` (the client labels a time-based movement in seconds rather than reps) |
| `GET /api/exercises/<id>/vbt-profile` | display-only load–velocity profile for one exercise: fitted coefficients, residual spread, points, a display-only implied 1RM and its point-in-time weekly series; optional `?rep=N` (1–8). No prescription reads it |
| `POST /api/programme/key` | request body -> `{cache_key}` covering version, request, resolved profile, database revision and relevant config hashes |
| `POST /api/programme/jobs` | starts a background build; returns `202` with `job_id` and status |
| `GET /api/programme/jobs/<id>` | `running` / `done` with entries / `error`; has a one-hour in-memory TTL and is capped at 20 jobs |
| `POST /api/programme` | synchronous compatibility endpoint -> date entries; Apply selection mirrors `/api/prescribe` and is deterministic |
| `GET /api/cardio/summary?weeks=N&as_of=` | imported cardio weeks, policy, rolling windows and coverage; `policy` reports the effective `max_hr_bpm` from the settings profile (default 200, effective-dated), the MET bands and the HR-share bands; always carries an `assessment` block (last completed week's relation to the WHO 150–300 reference as context: `below`/`inside`/`above`/`unknown` (`inside` is presented as "within"), current-week progress with no relation, latest VO₂max with value, unit, date, source/method and `current`/`stale`/`absent`, and `missing` notes) |
| `GET /api/cardio/summary?...&tiz=1&patterns=1` | adds the two optional blocks: `time_in_zone` (elapsed-time integration between workout-interval heart-rate samples, with `covered_minutes`/`workout_minutes`/`unobserved_minutes`/`temporal_coverage_share` and continuity eligibility reported separately) and `patterns` (per-pattern volume headroom from the budget, training-volume context only). Both are off by default; on the ODROID, `patterns` costs ~320 ms and `tiz` ~190 ms, against ~100 ms for the rest of the payload |
| `GET /api/cardio/workouts?limit=N` | imported workouts with their hidden/visible state |
| `POST /api/cardio` | **410** — manual cardio capture was retired 2026-11-17 (CARDIO-STAGE, portfolio plan); imports and the phone sync are the only sources |
| `GET /api/fatigue?date=N` | strength fitness-fatigue diagnostic (per-lift state and status; not a predictor) |
| `GET /api/validation?max_dates=N` | retrospective walk-forward report (not prospective) |
| `GET /api/continuity?date=N` | return-to-training calibration: per-band n/median/CI/fixed/applied and `allow_relax_fixed` |
| `GET /api/volume?date=N&weeks=4&accounting=hard\|effective` | weekly pattern-group ledger with `patterns` and direct/indirect/effective `groups`; optional accounting override defaults to the profile setting |
| `GET /api/shadow?date=N&window_days=84` | shadow review: rows by component/action, applied/applied-nothing counts, high-signal days, abstention reasons and the four gate checks; `activation_allowed` is always false |
| `GET /api/residual?date=N&window_days=84` | VBT execution residual grouped by lift/reps/load basis, lift-scoped only, with the signal/evaluation gates and abstention reasons (shadow) |
| `GET /api/exposure?date=N` | rolling hard-set exposure ratio with windows, coverage, abstention reasons, per-group ratios and Part D advisories (read-only; `DEC-EXPOSURE-02`) |
| `GET /api/volume/budget?date=N` | read-only weekly volume budget: target, exemptions, completed, projection, session cap, feasibility and per-group status/persistent/top-up capacity |
| `GET /api/outcomes?weeks=N&date=N` | read-only 4/8/12-week strength, longevity and coverage review |
| `GET /api/prospective?weeks=N&date=N` | W5 read-only prospective summary: statuses, attendance, work, RIR, duration, flags |
| `GET /api/observations?date=N&weeks=N` | AFC-3 longitudinal observations over the AFC-2 evidence contract: repeated RIR deviation, repeated incomplete work, VBT residual deviation; abstentions carry their reason. Persists new observations append-only (idempotent on the evidence id) |
| `GET /api/nudge?date=N` | at most one AFC-4 review-category nudge from the current AFC-3 observation, or `null` when suppressed or unsupported |
| `POST /api/nudge` | `{action: dismiss\|snooze, key, evidence_id?, date?}` -> append-only suppression and the next nudge; dismiss is permanent for that evidence window, snooze hides the key through `date + 14 days` inclusive and returns the following day |
| `GET /api/regime?weeks=N&date=N` | informational-only, read-only main-lift/substitute regime check |
| `GET /api/settings` | masked LLM settings, drop settings, config/database paths and app version |
| `GET /api/settings/ios` | effective `ios.v1.yaml` values, defaults, ranges, labels, descriptions, path/source and per-request reload semantics |
| `POST /api/settings/ios` | validate and atomically update only the four known `ios.v1.yaml` keys; the next request uses the new values, no restart |
| `GET /api/settings/volume?date=N` | consolidated volume panel: effective budget, volume policy, landmarks, athlete-level values, profile source and local-overlay warning |
| `POST /api/settings/volume` | validate and append a settings-profile version for volume budget/policy; requires reason and typed VOLUME for target/cap/MRV/landmark changes |
| `GET /api/settings/drop/window?date=N` | whether per-session drop confirmation applies on that date; the Prescribe checkbox is hidden when false |
| `POST /api/settings/llm` | save local LLM settings; blank key keeps the stored key |
| `POST /api/settings/drop` | legacy drop-only save path; the consolidated volume panel uses `/api/settings/volume` |
| `GET/POST /api/settings/profile` | read or append a settings-profile version; POST takes set/unset/reset, effective_from, guard_confirmed, reason and resolver_enable_confirmed (required for a false->true resolver.enabled transition). Profile-backed scalars include `cardio.max_hr_bpm` (120–250 bpm), the effective-dated denominator for cardio `%HRmax` classification |
| `GET /api/resolver/policy` | raw resolver policy YAML, path, digest, schema and newest backup metadata |
| `POST /api/resolver/policy` | validate the complete YAML, back up the current file, atomically replace it and prune to the newest 20 backups |
| `POST /api/resolver/policy/restore` | restore the newest normal validated policy backup; the current policy is snapshotted as `template-resolver-prerestore-*` and reported, and pre-restore snapshots are not later restore candidates |
| `POST /api/resolver/preview` | read-only candidate/beam/evaluator preview; returns the prescription directly (not nested), plus choices, alternatives, suggestions, top set, projected week and structured failure stages; the UI compares the full displayed prescription. Candidate pools carry the WP7a dwell order (cap, deterministic draw, bounded factor), and `generated_session.evaluator` carries the WP6 lexicographic `quality` snapshot plus `quality_key`; `classic_score_key` is retained only for the fixed-history A/B. The resolver fingerprint is `prescription-input-v4` and includes the evaluator version and role-quality config digest. The role-quality snapshot is version `role-quality-v3`; its `limitations` list reports the provisional ordinal stimulus rating and any missing stimulus/tax input when an accessory is present. |
| `GET /api/modalities` | module list with class, enabled source, dependencies, citations and factors |
| `GET/POST /api/modalities/<id>` | module state or enabled/factor update; guarded modules need guard_confirmed and reason |
| `POST /api/settings/llm/test` | call the configured model with a tiny connectivity prompt |
| `POST /api/intelligence/explain` | `{question}` -> project-grounded explanation, citations, warnings, `grounded`, sources and tokens; no transcript |
| `GET/POST /api/intelligence/knowledge/settings` | current/save Explain retrieval bounds (`top_k`, `max_context_chars`, `max_answer_words`); persisted in the git-ignored `config/knowledge.local.yaml` |
| `GET /api/intelligence/knowledge/status` | index readiness, file/chunk counts and per-source commit metadata |
| `POST /api/intelligence/chat` | `{messages: [{role, content}]}` -> read-only multi-turn answer from a fresh six-capability fact dossier, `answer`, `suggestions`, source capability names, advisory warnings, tokens, and `raw` (the exact model request and provider response shown by the web UI raw-data disclosure; neither is stored); max 20 turns; writes a run trace |
| `POST /api/intelligence/locate` | `{query}` -> "where in the UI" answer from the configured model over the top eight `GET /api/search` results and any retrieved project sources; returns `answer`, `verified` (false when the prose names a place outside the results), `warning`, the same `results` shape as `/api/search`, `sources` (path, heading, line range) and `tokens`; 400 when the LLM is disabled or the daily budget is spent; writes a run trace, never the prompt or answer |
| `POST /api/intelligence/narrate` | `{capability, payload}` -> run one read-only capability and return its narrative (headline, observations, limitations, warnings, raw facts, model, tokens); unverified numbers are warnings, not errors; writes a run trace; 400 when the LLM is disabled |
| `GET /api/exposures?date=N` | recent high-intensity exposures and recovery guard |
| `POST /api/exposures` | log a manual max/competition/unplanned exposure; tests use the test endpoint |
| `POST /api/continuity/settings` | `{allow_relax_fixed}` -> update the calibration policy |
| `POST /api/readiness/volume` | update the readiness volume valve (enabled, score below, sets, include essentials — main lifts opt-in) |
| `GET /api/readiness/presets` | raw `config/readiness-presets.v1.yaml`, its path and the parsed presets |
| `POST /api/readiness/presets` | `{yaml}` -> validate and atomically replace the preset YAML; no schema change |
| `POST /api/readiness/preset` | write a quick-readiness preset as ordinary entries with `source=preset` |
| `POST /api/readiness/context` | append display-only context flags |
| `GET /api/readiness/feedback?weeks=N&date=N` | descriptive follow-up of MOD-FAT-001 reductions, including completed workout snapshots and set adherence |
| `GET /api/selection?date=N&session_type=X&llm=0\|1&include_different=0\|1` | exercise-selection rankings with A/B/C comparability classes, evaluated as of `date`: history, dated suitability ratings and the profile version after that date never affect the result |
| `GET /api/substitution?date=N&session_type=X` | Part C fatigue-informed suggestion (at most one, suggest-only) plus abstention reasons |
| `POST /api/exercises/demands` | `{exercise_id, dimension, level, confidence?, reason?, evidence?, clear?}` -> writes the git-ignored demand overlay and returns the merged profile; `supported` needs an existing evidence id |
| `GET /api/options` | canonical goal, constraint, severity, region, pattern, VBT-family, muscle and exercise choices |
| `GET /api/exercises/catalog` | full exercise catalogue with source/properties, patterns, VBT families and muscles |
| `POST /api/exercises` | create/update an entity in `config/exercises/overrides.v1.yaml`; unknown new patterns/muscles are rejected, legacy values are preserved |
| `GET /api/measurements?metric_key=&from=&to=&limit=&offset=` | metric catalogue, summary and newest-first exact-record pages; offset walks older, entries stay date-ascending, date bounds are inclusive |
| `POST /api/measurements` | `{metric, value, date, method, note}` -> summary |
| `POST /api/state/profile` / `constraint` / `suitability` / `e1rm` / `test` / `symptom` / `block` | append-only state writes; profile includes `volume_budget_enabled` and `main_lift_policy`; goals, constraint kinds/regions, forbidden patterns/exercises and exercise ids are validated against the canonical vocabulary; `symptom` accepts optional `timing`, `attributed_session_id`, `attributed_exercise_id`, `onset_on` and `attribution_confidence`, plus the short aliases the UI uses |
| `POST /api/state/e1rm/withdraw` | `{exercise_id, effective_from?, reason}` -> appended withdrawal tombstone and refreshed state; `reason` is required and the override row is never deleted |
| `GET /api/docs` / `GET /api/docs/<name>` | doc list and rendered doc from `docs/manifest.yaml`; public entries only, grouped by category; `private/` and maintainer-only design docs are never served |
| `GET /api/search?q=&limit=` | ranked navigation results over the view/panel map, the profile settings and public doc headings; kinds `view`, `panel`, `setting`, `doc` with a DOM id or doc anchor target; `limit` 1–50 (default 20); a query is 1–120 characters (400 otherwise); read-only, no persistence |

### Prescription adherence

Completed workouts expose a versioned `adherence` object in
`GET /api/workout/<id>/summary` and `GET /api/history/<id>`. It is additive: existing
summary and history fields are unchanged. The live `GET /api/workout/<id>` detail does not
carry it, so an in-progress workout is never presented as a completed adherence analysis.

The object holds two independent comparisons:

- `original` — the frozen `plan_json` issued at workout start;
- `final_plan` — `plan_modified_json`, or the original plan when unmodified.

Each view reports prescribed, performed, matched, missing and extra working sets;
`set_completion` (numerator, denominator, ratio); repetition, load and RIR attainment; and
per-exercise/per-set detail. Ratios always carry numerator and denominator and return
`ratio: null` for a zero denominator. Set completion is not target attainment: a set can fill
a prescribed slot and still miss its rep, load or RIR target. There is no composite score.

Adherence for a completed workout reads the current `clean_set` leaf rows, so an audited
history correction is reflected rather than the original live `workout_set` draft.
`adherence` is the single metric source for a completed workout: the old summary `completion`
block was removed in AFC-2 (`DEC-AFC-01`). The raw `comparison`/`original_comparison` on
`GET /api/workout/<id>` remains the display contract for a workout that has not been
materialised (in progress or abandoned); it is not a metric source. The
existing `is_working_set` classification is authoritative and RIR 6 is the logged
warm-up sentinel unconditionally; a stored flag that disagrees is a data-quality note, not a
second classification. Load is compared as external load, using the stored
`load_basis`/`external_load_kg`; a captured bodyweight total is not treated as an added plate.
RIR deviation is actual minus target (positive means further from failure). Unmatched,
ambiguous, mismatched and removed-exercise sets remain visible under `quality`.

Each exercise entry also carries a descriptive `structure`
(`structure`, `confidence`, `load_shape`, `segments`, `limitations`) derived from the recorded
working order, and `substituted`/`planned_exercise_id`/`performed_exercise_id`. A substituted
set is attributed through `substitutes_plan_item_index` and compared with the server-solved
prefill when the execution event is present; without one, load quality is unavailable. An
addition stays extra work outside the planned denominator. Derived structure never changes a raw
set or any training metric.

`changes` separates swaps, additions, removals, set-count edits and target edits. When the
original prescription cannot be attributed reliably (a swap removes that item from the
original denominator), the planned sets appear under `unattributable_planned_sets` with a
reason instead of a fabricated percentage.

The completed-workout summary also returns `quality.flags` and `evidence`. A flag is
`{"code", "detail"}` and means a number on the page is qualified — never that the session
failed; codes are the ones the owning service already emits. `evidence` is a list of
`{evidence_id, evidence_version, source_fingerprint, source, source_ids, window, value, unit, n,
comparability, gate, quality_flags, method_versions, calibration_ids, limitations, rule_ids,
assumption_ids}`. `evidence_id` is the stable identity of the claim (source identities, window
and value); a correction that leaves those unchanged keeps the id. `source_fingerprint` hashes
the exact contributing source rows, so a changed revision changes the fingerprint even when the
aggregate value does not. `source_ids` name the exact contributing rows (for RIR, only the
evaluated RIR sets; never the containing session inventory). `gate` uses the existing
`insufficient`/`signal`/`evaluation` vocabulary. The same envelope is what the future LLM
context builder serialises, so there is one schema.

Imported sessions have no frozen workout prescription and return
`{"status": "unavailable", "reason": "no_prescription_snapshot"}`; a voided session returns
`session_voided`; a workout with no plan items returns `no_prescription_items`.

The summary also carries an optional `observation`: one deterministic sentence about the
session, selected from the strongest qualifying family (RIR deviation beyond the engine's
tolerance, unperformed prescribed slots, or comparable velocity sets outside the calibration
band). It is `null` when nothing qualifies, carries `family`, `text`, `gate`, `n`,
`evidence_id`, `limitations` and the same evidence envelope, and never changes a prescription.
Selection is descriptive; nothing is recalculated (`DEC-AFC-08`).

History set rows also expose `prescription_item_index`, `substitutes_plan_item_index` and the
legacy read-only `set_role`; an audited correction
preserves both, so later comparison and adherence still resolve the same plan item and set
group.

### Longitudinal adherence analytics

`GET /api/adherence/analytics` aggregates completed app-tracked workouts. It accepts
`date` (as-of, default today) plus `weeks` (1–52, default 8), or explicit `from`/`to`
dates, and the filters `exercise_id`, `session_type` and `group_by=week|month`. Training-block
grouping is not offered because no reliable per-workout block identity is stored.

The response keeps `original` and `final_plan` separate. Each contains the summed
`set_completion` (numerator, denominator, ratio), repetition, load and RIR attainment, missing
and extra sets, per-period rows and per-exercise rows. Every ratio is computed from summed
numerators and denominators; per-workout percentages are never averaged. Empty periods return
`{numerator: 0, denominator: 0, ratio: null}`, never a fabricated 0%.

`workouts` provides per-workout drill-down rows, each with both prescription views. `coverage`
reports completed workouts in range, analysed, unavailable, voided, missing materialised
sessions, invalid snapshots and filter exclusions, plus the excluded rows and their reasons.
Imported sessions have no workout prescription and are outside the aggregation.

A documented display guard marks a period or exercise `small_sample` when it has fewer than
three workouts or fewer than five prescribed sets. The Progress UI omits those points from the
trend charts and keeps them in the tables with the exact counts. The guard is not a statistical
confidence claim and never changes a numerator or denominator.

### Longitudinal observations (AFC-3)

`GET /api/observations` reads completed app-tracked workouts and reports at most one repeated
pattern per family: RIR sitting above or below target, sessions ending with unperformed
prescribed slots, and VBT cohorts whose residuals fall outside their calibration band.

- A family only speaks when its own evidence gate allows it: RIR and incomplete work need three
  of the last five comparable sessions (`config/observations.v1.yaml`); VBT inherits the cohort
  gate and additionally requires at most half of comparable sets inside the band.
- A family that cannot support a claim returns an entry in `abstain` with a reason — never a
  zero, never a pass/fail. Excluded sessions (imported, abandoned, technique, voided and
  adherence-unavailable) are counted in `excluded` and listed in `abstain`, so a thin sample is
  explained rather than silent.
- Every observation carries `gate`, `n`, `evidence_id`, `value` and the full `evidence`
  envelope (`source`, `source_ids`, `window`, `comparability`, `limitations`, `rule_ids`).
- The endpoint appends each produced observation to the append-only `observation` table,
  idempotent on its deterministic id; re-requesting the same evidence writes nothing and changed
  evidence appends a new row. Abstentions are never stored.
- It computes no metric: values come from `adherence` and `vbt_performance` and are rendered,
  not recalculated.

### Coaching nudges (AFC-4)

`GET /api/nudge` promotes at most one Today review category: a time-sensitive programme fact
(a scheduled deload suggestion or an active competition peak/taper window) first, otherwise an
AFC-3 observation. A nudge carries its family, statement, gate, `n`, `evidence_id` and the
full evidence envelope; it has no notification channel and never changes a prescription.
Programme nudges carry `family: "programme"` and the programme header's method; the evidence id
is the programme state (deload block week, or competition date/window). The iPhone Today reads
this route too, so the same one card appears on the phone and the web.

Suppression is append-only (`maintenance_review`): `POST /api/nudge` with `action: dismiss`
records a completed review (`not_applicable`) whose note is the observation/evidence identity, so
only that evidence window is silenced; `action: snooze` records a 14-day snooze for the nudge key.
The expiry date is inclusive: a snooze issued on 1 March stays hidden through 15 March and returns
on 16 March.
A new evidence id produces a new nudge. Attendance, volume and other signals are deliberately not
nudge sources; programme context is limited to the two facts above.

### VBT target metadata

Plan items carry `reps_unit` (`reps` or `seconds`) so a time-based hold is displayed
and logged in seconds. Swapping an exercise re-solves the replacement's load, warm-up ramps and
VBT target from that exercise's own history/calibration; an unavailable load keeps an explicit
`unknown_load_reason`.

An issued VBT target now carries an optional `vbt` object on each plan item:

```json
{
  "target_mps": 0.42,
  "low_mps": 0.39,
  "high_mps": 0.45,
  "rep_count": 3,
  "rir_low": 2,
  "rir_high": 3,
  "scope": "lift",
  "family": "squat",
  "n_sets": 18,
  "n_sessions": 3,
  "method_version": "2.0.0",
  "calibration_id": "vbt-...",
  "source": "computed",
  "fit_method": "line",
  "velocity_slope": -0.0045,
  "velocity_intercept": 1.05,
  "velocity_rir_coef": 0.0,
  "velocity_residual_mad": 0.01,
  "load_min": 80,
  "load_max": 125
}
```

`fit_method` is `line` when the target was evaluated at the item's prescribed load and RIR,
and `median` when the flat band was issued instead. The coefficients and load range are frozen
with the target; a per-set comparison evaluates the line at the load actually used and reports
`expected_mps`, `comparison_basis`, `load_conditional` and `extrapolated`, falling back to the
planned target outside the fitted range.

The legacy `velocity_target` and `vbt_basis` fields remain. The structured object is frozen
into `workout_session.plan_json` at workout start, so a later recalibration cannot rewrite the
target a workout was issued with. A swap re-solves the replacement's own target and never borrows
the old lift's; an added exercise is solved the same way and carries a target only when its own
history supports one; a set-count change preserves a still-applicable target. Plans created before this field
existed have no `vbt` object and are treated as legacy; the server does not reconstruct target
bands from the current calibration.

The object is additive and optional, including in the iOS plan payload; no existing field or
semantic changes. No migration is required. `prescription_item` keeps its legacy
`velocity_target`/`vbt_basis` projection; the structured metadata lives in the frozen plan
JSON and the append-only `vbt_calibration` row identified by `calibration_id`.

An in-progress `GET /api/workout/<id>` and its set mutations include a read-only `vbt` block
with per-set comparisons, exercise aggregates and quality counts:

```json
{
  "status": "available",
  "reason": null,
  "plan_target_note": {"status": "available", "targets": 1, "session_modified": false,
                       "calibration_ids": ["vbt-..."], "withheld": []},
  "sets": [{
    "set_id": 1, "set_index": 1, "exercise_id": "ssb_squat",
    "reps": 3, "load_kg": 100, "load_basis": "external",
    "actual_velocity_mps": 0.44, "target_mps": 0.42, "low_mps": 0.39,
    "high_mps": 0.45, "delta_mps": 0.02, "delta_pct": 4.76,
    "within_calibration_band": true, "comparable": true, "reasons": [],
    "actual_rir": 2, "target_rir_low": 2, "target_rir_high": 3,
    "target_source": "final_plan", "velocity_source": "stored",
    "target": {"calibration_id": "vbt-..."}
  }],
  "exercises": [{
    "exercise_id": "ssb_squat", "sets": 3, "comparable_sets": 2,
    "excluded_sets": 1, "mean_signed_delta_mps": 0.0,
    "median_signed_delta_mps": 0.0, "mean_absolute_error_mps": 0.02,
    "within_calibration_band": {"numerator": 2, "denominator": 2, "ratio": 1.0},
    "above_target": {"numerator": 1, "denominator": 2, "ratio": 0.5},
    "below_target": {"numerator": 1, "denominator": 2, "ratio": 0.5}
  }],
  "quality": {"target_items": 1, "logged_sets": 3, "working_sets": 3,
              "comparable_sets": 2, "excluded_sets": 1}
}
```

Completed `GET /api/workout/<id>`, `GET /api/workout/<id>/summary` (under
`summary.vbt`) and `GET /api/history/<id>` (under `vbt`) expose the same shape computed
from corrected `clean_set` leaf rows and the frozen plan. Exercise means, medians, band
fractions and above/below fractions use comparable sets only; the band fraction's denominator
is the comparable sets with a recorded band. A set whose final item was removed
falls back to the target issued in the original plan and is marked
`target_source: "original_plan"`; a swapped exercise never borrows the old target. The latest
set-mean `vbt_override` wins and is marked `velocity_source: "override"`. Per-rep velocity
loss remains a separate field.

`plan_target_note` is the frozen plan's own `notes.vbt` record, copied verbatim: it names the
safety rule that skipped target attachment, the calibration shortfall, the issued targets, or
the lifts withheld by policy. `session_modified` records that a safety rule amended the session
before targets were attached; the targets are still issued, and the per-set rules decide whether
each set stayed comparable. The note is provenance for the workout-level `reason`, which can only
say "no target anywhere"; the web UI shows it beside an `unavailable` result and shows the
modified-session line when targets were issued anyway. When no plan note was recorded (legacy
rows, voided sessions) the field is `null`.

A comparison is marked `comparable: false` with explicit reasons when the set is warm-up,
unattributed, attributed to another exercise, missing/invalid velocity, a different rep count,
a different set-group rep count, has unknown/incompatible load basis, is time-based, carries a
data-quality flag, or has missing/out-of-band actual RIR. The delta may still be present as
context, but it is not a valid target observation. Imported sessions report
`no_prescription_snapshot`; voided sessions report `session_voided`. No cross-exercise
composite score is produced.

### Planned set groups

A prescription item may carry an ordered `set_groups` list; an empty list is straight sets.
Order is the only identity: the server writes `group_index` as the list position, and no role
or back-off ratio is sent.

```json
"set_groups": [
  {"group_index": 0, "sets": 1, "load_kg": 120.0, "reps_low": 3, "reps_high": 5, "rir_target": 1},
  {"group_index": 1, "sets": 3, "load_kg": 102.5, "reps_low": 3, "reps_high": 5, "rir_target": 3}
]
```

Invariants: the group sets sum to `item.sets`, every group carries a numeric load, and
`item.load_kg` stays the summary (back-off) load, never the source for per-set display. The
warm-up ramp follows the heaviest group. The server validates a supplied plan at start:
`group_index` is optional on read but must restate its list position when present, a stored
`role` is ignored, and a group total that disagrees with `item.sets` is a `400`. The plan is
frozen into `workout_session.plan_json` at start, so a client renders the groups it was given
and never recomputes one (`DEC-RESOLVER-18`).

### Longitudinal VBT performance

`GET /api/performance/vbt` is the read-only Performance dashboard feed. It reuses the completed
per-set analysis above and exposes frozen-target cohorts, weekly residuals, band and RIR
evidence, within-set per-rep drift and per-set drill-down rows. The default range is the latest
84 days; `exercise_id` narrows the drill-down without changing the analysis rules.

Cohorts are split by exercise, target scope (`lift` or `family`), target rep count and target
RIR band. The response never pools lift and family targets, never pools different lifts into one
estimate, and never returns a composite score. Key fields:

- `cohorts[]`: `n`, `weeks`, `mean_residual_mps`, `median_residual_mps`,
  `mean_absolute_error_mps`, `spread_mps`, `mad_mps`, relative errors,
  `within_calibration_band`, `band_evidence` (below/within/above), `rir`
  (actual/prescribed, outside/missing), `bootstrap_mean_ci`, `gate` and `reasons`.
- `weekly[]`: one row per observed week with comparable residuals; absent weeks are not zero.
  When more than one cohort is present, top-level `weekly` is empty and each cohort carries
  its own `weekly` series, so unrelated exercises/scopes are not averaged together.
- `drift`: working sets with at least two valid per-rep velocities; median within-set loss and
  weekly medians. The drift gate is 5 sets over 3 consecutive weeks; no trend model is fitted.
- `summary`: target/comparable/excluded counts, cohort and scope counts, metadata coverage,
  `evaluation_ready` and `abstain` reasons.
- `gates`: the reused 5-observation signal gate, 20-observation/8-week evaluation gate and
  drift gate. Gates make a cohort readable; they do not authorize a load or prescription change.

The 95% bootstrap interval is deterministic from the residual vector and is descriptive, not a
prediction interval or a measurement-error bound. Cohort `within_calibration_band` uses
comparable sets; `band_evidence` counts all target rows with a recorded band, including
excluded rows. Band counts are descriptive threshold evidence, not success/failure labels.
Actual RIR is shown even when it falls outside the target band; such sets remain excluded from
comparable residual statistics.

### iOS facade — Phase 1 reads and Phase 2 workflow

/api/ios/v1/ is the authenticated boundary used by the native iPhone client. It is
additive: every unversioned route above keeps its current behaviour and stays unauthenticated.
The authoritative server-side contracts are in [`design/`](design/): Phase 1, Phase 2,
Phase 3A, Phase 4, R7, R8 and the watch companion. The phase rules and client behaviour are in
the [iOS client plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/IOS-CLIENT-PLAN.md)
in the StrengthApp repository.

> **2026-11-19 target amendment (partly implemented).** The [resolver prescription
> structure plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/RESOLVER-PRESCRIPTION-STRUCTURE.md)
> retires the five plan-edit routes, replaces the request `top_set` boolean with `top_set_intent`,
> adds `programme_header` to Today and execution substitutions/additions. Implemented
> 2026-11-20: the plan-edit routes are gone, the plan is frozen and `execution` is live; the
> request accepts `top_set_intent` and the plan payload carries the frozen `top_set` outcome.
> `programme_header` (WP4) is still pending; this table describes the routes that remain.

| route | auth | payload |
|---|---|---|
| `POST /api/ios/v1/pair` | none | `{code, label?}` -> `{api_version, device, token, server_date, server_time, utc_offset_minutes, server_timezone}`; the token is shown once |
| `GET /api/ios/v1/bootstrap` | bearer | `{api_version, server_date, server_time, utc_offset_minutes, server_timezone, capabilities}`; Phase 2 adds `readiness_write`, `prescription` and `workout_write`; Phase 3A adds `healthkit_readiness` (false when mutations are disabled); INT-3 adds `intelligence_read` |
| `GET /api/ios/v1/today` | bearer | `{date, readiness, readiness_score, active_workout, plan, programme_header}`; `readiness` is the existing `/api/readiness/<date>` payload; `active_workout` is null or the live workout detail; `programme_header` is the read-only `{trained_week, dup?, deload, competition?}` context |
| `GET /api/ios/v1/history?limit=&offset=&start=&end=` | bearer | exactly `history.list_sessions`; limit 1-100, default 50; offset >= 0, default 0 |
| `GET /api/ios/v1/history/<id>` | bearer | exactly `history.detail`; session outline, measured/manual duration, sets and feedback; unknown id 404 |
| `GET /api/ios/v1/workouts/<id>/summary` | bearer | `{"summary": ...}` — the same completed-workout summary payload as the web route (adherence, VBT, feedback, quality flags and evidence), plus `reconciliation: {state: none|open|closed, pending_devices, closes_at}` so a client can show that a device's events are still expected and that the totals may still grow; `ratios` is always an empty list here because relative-strength ratios walk the whole lift history and the native report does not render them, so the mobile request stays inside its timeout; unknown id 404, in-progress 409 |
| `GET /api/ios/v1/progress?weeks=&date=` | bearer | exactly `progress_feature.dashboard`; weeks 1-52, default 8 |
| `GET /api/ios/v1/intelligence/weekly-review?week_end=YYYY-MM-DD` | bearer | exactly the `get_weekly_review` envelope (Monday-Sunday week containing `week_end`; default the most recently completed week); unknown query parameter 400, disabled capability 503, malformed envelope never returned |
| `GET /api/ios/v1/intelligence/overview?as_of=&window_weeks=` | bearer | exactly the `get_training_overview` envelope; window 1-52, default 4 |
| `GET /api/ios/v1/intelligence/longevity?as_of=&include_time_in_zone=&include_patterns=` | bearer | exactly the `get_longevity_assessment` envelope: last completed week against the WHO reference as context, current week progress, VO₂max status, optional sample-based time-in-zone and per-pattern headroom; facts only, no advice |
| `GET /api/ios/v1/intelligence/exercises/<id>/progression?as_of=&window_days=&include_sessions=&limit_sessions=` | bearer | exactly the `get_exercise_progression` envelope; window 28-365, default 84; unknown exercise 404 |
| `GET /api/ios/v1/intelligence/readiness?from=&to=&fields=` | bearer | exactly the `get_readiness_history` envelope; `fields` is a comma-separated list, default `score`; the paired app may name raw fields |
| `GET /api/ios/v1/intelligence/session-details?workout_id=&session_id=&include_ratios=` | bearer | exactly the `get_session_details` envelope; exactly one identifier required |
| `GET /api/ios/v1/intelligence/prescription?prescription_id=&for_date=&include_provenance=` | bearer | exactly the `get_prescription` envelope; at most one of `prescription_id` or `for_date`; no identifier returns the current persisted prescription |
| `GET /api/ios/v1/intelligence/programme-summary?as_of=&block_weeks=` | bearer | exactly the `get_programme_block_summary` envelope; `block_weeks` is 4, 6 or 8 |
| `GET /api/ios/v1/intelligence/adherence?as_of=&weeks=&from=&to=&group_by=&exercise_id=&session_type=` | bearer | exactly the `get_adherence_analysis` envelope; `from` and `to` travel together |
| `POST /api/ios/v1/readiness` | bearer + Idempotency-Key | `{values, note?}` -> the existing readiness payload; values are validated against the effective registry; unknown/empty/zero-placeholder fields are rejected |
| `GET /api/ios/v1/readiness/schema` | bearer | effective readiness registry (same payload as the web schema route); the phone form renders from it |
| `POST /api/ios/v1/healthkit/workouts` | bearer + Idempotency-Key | `{workouts:[{key, activity_type, started_at, ended_at, duration_s, source_name, avg_heart_rate?, max_heart_rate?, active_energy_kj?, distance_m?, avg_mets?, srpe?, timezone?}]}` -> `{workouts, created, existing, rejected, rejected_keys}`; key is the HealthKit UUID (16 bytes) or a content digest (32); a workout starting before `history_cutoff` is rejected so history cannot be duplicated; an immutable conflict or malformed workout is rejected per item and its key is returned |
| `POST /api/ios/v1/healthkit/samples` | bearer + Idempotency-Key | `{samples:[{key, workout_key, kind, sampled_at, value, unit, association, source_name?}], metrics?:[{key, kind, measured_at, value, method}]}` -> `{samples, created, existing, rejected, rejected_keys, metrics?}`; samples land beside their workout (uploaded first), metrics in `measurement`; `kind` is `vo2max`, `steps_per_day` or `sitting_hours_per_day`; the two windowed metrics arrive already averaged by the phone (one row per window, `measured_at` is the window's last day, key is the window digest, `source` is `device`, replay of the same key is a no-op) and an implausible value is skipped, not fatal; per-item tolerance, a bad row is counted, its key returned and skipped |
| `GET /api/ios/v1/healthkit/activity/summary?weeks=N` | bearer | `{summary, recent}` — the same computation the browser panel uses, authenticated for the phone |
| `POST /api/ios/v1/healthkit/readiness` | bearer + Idempotency-Key | `{date, samples:[{field, value, sample_id, sample_at, source_name, source_bundle_id?, source_class, source_model?, source_manufacturer?}]}` -> the canonical readiness payload plus `healthkit` provenance; one to three samples (HRV, RHR, bodyweight), server-local today for the import, sample identity deduplicated; see Phase 3A contract |
| `POST /api/ios/v1/prescriptions` | bearer + Idempotency-Key | `{readiness_ack?, confirmations?: {deload?, drop?}, settings?: {session_type?, minimum_session?, minimum_target_minutes?, top_set_intent?, technique_throttle?}}` `minimum_target_minutes` must be one of 30, 45 or 60 when `minimum_session` is true (400 `validation_failed` otherwise) and is ignored when it is false; `top_set_intent` is `off`, `preferred` or `required` (omitted follows the profile) and `technique_throttle` (boolean) applies MOD-TECH-001 to main work at build time -> `202 {issued_plan_id, execution_id, status, for_date, request_expires_at, plan_expires_at, retry_after_ms, settings}`; `execution_id` is the workout this plan will become, minted at issue so an offline start can name it; the request is built in the background (R7) |
| `GET /api/ios/v1/plans/current` | bearer | the pairing's authoritative plan-request state: `{status: queued|building|ready|error|none, issued_plan_id, execution_id, elapsed_seconds, settings, plan?, load_catalogue?, readiness?, warnings?, error?}`; `load_catalogue` is the `load-catalogue/v1` object (one entry per taxonomy exercise with `load_source`, `base_load_kg`, `accessory_load_kg`, `increment_kg`, `bodyweight`, `power`) the phone uses to prefill an offline substitution; null for a plan built before it existed; `none` is a normal answer, not a 404 |
| `POST /api/ios/v1/workouts` | bearer + Idempotency-Key, **either pairing device**; a watch token may start (execution writes after start remain phone-only) | `{issued_plan_id, execution_id?, started_at?}` -> the existing workout detail; any non-revoked device of the plan's pairing starts by id only and binds `execution_id` (the plan's own; a different value is `409 execution_id_mismatch`); `started_at` is the athlete's recorded start, which must fall inside the plan's issue window and whose `for_date` must be today or yesterday (`410 plan_expired` otherwise); identity and state decide a start, never elapsed time: the same `execution_id` returns the running session, and a different execution may start beside an open one (`409 workout_active` is no longer returned by this route); a superseded or consumed plan is `410` |
| `POST /api/ios/v1/workouts/<id>/sets` | bearer + Idempotency-Key, **phone token only**; a watch commits through the phone (`403 watch_read_only`). The same rule applies to `update-set`, `remove-set`, `execution`, `execution-events`, `form`, `complete` and `reconciliation`; `abandon` stays open to any device as the safety valve | `{exercise_id, load_kg?, reps, rir?, velocity_mps?, set_index?, plan_item_index?, substitutes_plan_item_index?, rep_velocities?, performed_at?, origin_device_id?}` -> workout detail; `plan_item_index` is the stable plan-item identity (not the display position); `substitutes_plan_item_index` annotates a set that replaced that slot (the performed exercise must differ, and both stored columns then hold the slot); a stale index with no annotation is kept as extra work with no attribution; `set_index` defaults to the next index for that exercise, allocated inside the same write transaction as the insert; when supplied, it is the set's identity with the exercise: a replay must match the complete immutable payload (exercise, index, load, reps, RIR, mean and per-rep velocity, source, both plan attributions, `origin_device_id`, and `performed_at` when supplied, compared as an instant so equivalent ISO-8601 offsets replay) and a different payload is `400 set_index_conflict`; `velocity_mps` is optional manual mean and `rep_velocities` is optional `[{rep_index, velocity_mps}]`; values must be positive and reps are required; `origin_device_id` is the capturing device and must belong to the workout's pairing |
| `POST /api/ios/v1/workouts/<id>/update-set` | bearer + Idempotency-Key | `{set_id, load_kg?, reps?, rir?, velocity_mps?}` -> workout detail; appends one correction event, so the set keeps its `set_id` and `set_index`; inside an open reconciliation window a completed session accepts a late correction, which appends a superseding `clean_set` row and refreshes the totals; a correction of a removed set is `409 late_event_rejected` and is preserved, never resurrected |
| `POST /api/ios/v1/workouts/<id>/remove-set` | bearer + Idempotency-Key | `{set_id}` -> workout detail; removes a performed set; unknown/invalid set id is 400/404; idempotent replay supported; inside an open reconciliation window a completed session accepts a late removal, which appends a tombstone to `clean_set` (supersedes the row, is itself voided) and refreshes the session totals, and after the window it is preserved as `late_rejected` with `409 reconciliation_window_closed`. A late correction of a removed set is refused with `409 late_event_rejected` (reason `set_removed`) and preserved; it never resurrects the set |
| `POST /api/ios/v1/workouts/<id>/form` | bearer + Idempotency-Key | `{exercise_id, rating 1-5, note?}` -> workout detail; inside an open reconciliation window a completed session still accepts a late rating, which is appended to `session_form_rating` as well so reports see it; after the window it is preserved as `late_rejected` and refused with `409 reconciliation_window_closed` |
| `GET /api/ios/v1/exercises` | bearer | `{exercises:[{id, display, pattern}]}`; canonical catalogue for the R8 picker and exercise library |
| `GET /api/ios/v1/exercises/<id>` | bearer | read-only exercise detail: `{exercise:{id,display,pattern,source}, properties:{...}, e1rm_applicable, e1rm, e1rm_reason}`; `e1rm` is the existing 365-day eligible/degraded series, or `null` when not e1RM-applicable; applicability uses the shared derived structural default when the taxonomy has no explicit flag; unknown id 404 |
| `GET /api/ios/v1/exercises/<id>/history?limit=&offset=` | bearer | exactly `exercise_history_feature.history`; completed sessions with current working sets, 20 default page, equivalents reported; unknown id 404 |
| `POST /api/ios/v1/workouts/<id>/execution` | bearer + Idempotency-Key, phone token only | `{event_id (UUID), change: substitution\|addition, plan_item_index?, after_item_index?, exercise_id, reps_low?, reps_high?, rir_target?, prefill_load_kg?, prefill_catalogue_version?, prefill_as_of?}` (no legacy flag: a value means the phone applied the catalogue; a version with no value records a catalogue miss; neither means the server solves) -> `{execution}` (the same block `GET .../execution` returns). A substitution takes sets/reps/RIR from the frozen plan item; an addition takes the supplied reps/RIR. **Preferred prefill:** the phone applies the `load_catalogue` it was issued and sends `prefill_load_kg`; the server recomputes it from that snapshot and stores `prefill_reason: client_applied`, `prefill_source` (`catalogue_e1rm`, `catalogue_double_progression`, `flare_dose`, `bodyweight`, `power`, `none`), `sets` (the replacement's own count, capped by a live erector dose), `prefill_verified`, `prefill_expected_load_kg` and, on disagreement, `prefill_mismatch_reason` — a disagreement is recorded, never rejected, and the value the athlete saw is kept. A catalogue version that does not match the stored one is recorded unverified rather than refused. Every change also stores `resolved_by` (`server` or `catalogue`), `set_groups` (the slot's structure re-solved for the substitute, empty for straight sets), and `top_set {status, reason_code}` — a substitute's top-set eligibility is not re-decided, so it is `not_applicable` with reason `substituted`. A server solve also stores `vbt`/`vbt_target` when the lift has a trustworthy calibration. Idempotent by `event_id`; the same identity with different content is `400`; a substitution after any set is attributed to that plan slot is `400`, and the status, plan-identity, performed-slot and client-id checks run in the same write transaction as the insert so a concurrent set recording cannot slip between check and event; a concurrent insertion of the same event id with different content is rejected rather than returned as a duplicate; a watch token is `403 watch_read_only` |
| `POST /api/ios/v1/workouts/<id>/complete` | bearer + Idempotency-Key | `{session_rpe? or not_recorded: true, duration_min?, notes?, ended_at?, productivity?, pending_devices?}` -> completed workout detail; `pending_devices` is the list of devices whose events have not arrived, and it opens a seven-day reconciliation window (`ios.v1.yaml: reconciliation_window_days`) during which their late sets are applied; RPE and not-recorded are mutually exclusive; `ended_at` preserves the local finish time and measured duration; `productivity` is 1-5 when present; a retry or a second concurrent completion returns the already-completed workout without repeating materialisation, the dwell advance, the analytics revision or the end event; a completion carrying an **earlier** `ended_at` than the recorded one appends a `late_finish` event with that instant and the completing device, and never rewrites `ended_at` |
| `POST /api/ios/v1/workouts/<id>/abandon` | bearer + Idempotency-Key | `{}` -> abandoned workout detail |
| `POST /api/ios/v1/workouts/<id>/reconciliation` | bearer + Idempotency-Key | `{device_id}` -> `{reconciliation}`; records that one expected device has nothing left to send, so a synced watch does not leave the session `open` for the rest of the window. Idempotent, and an unknown device is a no-op; the session must be completed (`409 workout_not_active` otherwise) |
| `POST /api/ios/v1/workouts/<id>/execution-events` | bearer + Idempotency-Key | `{events:[{event_id, event_type, occurred_at, plan_item_index?, set_id?, local_set_id?, payload?}]}` -> `{workout_id, accepted, duplicates, received_at}`; 1-100 events, all-or-nothing, idempotent by event_id; unknown fields, bad timestamps, wrong ownership/status and conflicting event IDs are 400/404/409; telemetry is observational and bounded by the session's own timestamps, so a completed session still accepts it (no reconciliation window applies) |
| `POST /api/ios/v1/healthkit/hrv-recovery` | bearer + Idempotency-Key | `{samples:[{sample_id, date, value, sample_at, source_name, source_class, sample_count?}]}` -> `{date_from, date_to, accepted, duplicates}`; 1-500 dated nights, history accepted (2014+, not future), each idempotent by `sample_id`, changed immutable data is 409; readiness reads this series for HRV (2026-11-18) |
| `GET /api/ios/v1/workouts/<id>/execution` | bearer | read-only execution timeline and derived metrics (exercise intervals may overlap when a session records a superset; they are folded per plan item), plus the session envelope `{owner_device_id, plan_revision, last_activity_at, stale, plan, execution}`, where `execution` is `{workout_id, watermark, substitutions, additions}` so a watch can apply a payload only when the watermark is at least as new as its own; empty event coverage is valid and historical workouts are never backfilled |
| `GET /api/history/<id>/execution` | none (local web UI) | the same read-only execution payload for a completed workout, keyed by session/workout id, including the `execution` block; imported sessions without a workout row are 404 |

The five R8 plan-edit routes (`.../plan/items/<index>/swap|remove|sets|move` and
`.../plan/exercises`) are **retired**. A plan is frozen at start: they return `404`, nothing writes
`plan_modified_json` or `plan_revision` after start, and a substitution or addition is an
execution change, not a plan edit (`DEC-RESOLVER-23`). `plan_modified_json` remains readable for
historical rows, and the `409 plan_item_mismatch` guard is gone: an unannotated stale index is
preserved as extra work rather than rejected.

Workout-detail sets carry the stable plan-item identity as both `plan_item_index` (the API field)
and `prescription_item_index` (the stored column name kept for existing web consumers). An
unattributed set has both as null.

- **Pairing is CLI-only.** `strength-coach ios pair [--label LABEL] [--ttl 300]` prints a
  one-use 8-digit code (spaces/hyphens are ignored by the exchange); the default TTL is 300
  seconds and the accepted range is 60-3600. `ios devices` lists devices and `ios revoke`
  sets `revoked_at` (idempotent; an unknown id exits 2). No HTTP route issues a code.
- **Credential model.** A successful exchange creates one device and returns a 32-byte
  URL-safe bearer token. Only SHA-256 hex digests of the code and token are stored. A missing
  or unknown token returns `401`; a revoked device returns `403`. Authentication runs before
  route dispatch, so an unknown path under the namespace is `401` unauthenticated and `404`
  authenticated.
- **Pairing errors.** `400` malformed body/code/label, `401` wrong code, `410` expired or
  already used, `429` attempts exhausted. Five failed attempts exhaust one code.
- **Phase 2/3A writes.** Every mutation requires a UUID Idempotency-Key. A successful response is
  stored for 30 days and replayed with Idempotent-Replay: true; the same key with a different body
  or route is 409 idempotency_conflict. The receipt check and mutation run in one BEGIN IMMEDIATE
  transaction, so concurrent duplicates replay the committed response rather than executing twice;
  a receipt uniqueness race is rolled back and re-read instead of returning 500. Mutations are
  authenticated before dispatch and run through the existing readiness, prescription and workout
  services. Phase 3A adds the read-only HealthKit readiness import route; it stores observations,
  never writes HealthKit itself, and does not request sleep or workouts.
- **HealthKit readiness.** Phase 3A is read-only and opt-in. The client sends only HRV and
  resting heart rate; manual/preset readiness wins over HealthKit, which wins over imported
  readiness. HealthKit observations live in `healthkit_readiness`, never in `readiness_day` or
  `readiness_entry`. Sample identity is device + field + HealthKit sample UUID; identical
  observations are no-ops and changed immutable attributes are 409 healthkit_sample_conflict.
  The route accepts only the server-local today, HRV within 48 hours and RHR on that date; the
  canonical readiness payload exposes `sources` and `healthkit` provenance. No raw time series is
  retained and no score is computed in Swift.
- **Per-rep velocity.** The iOS set route accepts optional `rep_velocities` on a manual set. The
  server validates indexes/values, derives `velocity_mps` from the reps when the mean is omitted,
  and returns `reps_detail`/`rep_summary`. This is descriptive detail; it does not change load,
  RIR, prescriptions or scoring. The existing web import/API contract remains authoritative.
- **Issued plans.** POST /api/ios/v1/prescriptions persists the normal prescription and returns a
  single-use issued plan with a 60-minute TTL. Either device of the pairing starts it by id only;
  plan content never comes from the phone. One live plan is allowed per pairing; a newer issue
  supersedes the older one. A watch resolves the plan through its parent phone.
- **Asynchronous issue (R7).** The resolver build outlives the client's 10-second timeout, so the
  request is queued and built by one bounded dispatcher: `202` plus a database-backed request row,
  and `GET /api/ios/v1/plans/current` as the authoritative read for launch, foreground and polling.
  Two deadlines are separate: `request_expires_at` (`plan_request_ttl_seconds`, default 900)
  bounds the build, and `plan_expires_at` (`issued_plan_ttl_seconds`, default 3600) bounds starting
  a ready plan. Prescription rows are written in the start transaction, so an unstarted ready plan
  is a preview and not a prescription. Starting a `queued`/`building` plan is `409 plan_not_ready`;
  a failed build is `410 plan_failed`. Legacy Phase 2 rows are preserved by migration `0056` and
  keep their original prescription id. Replacing or revoking a watch leaves the pairing's live plan
  intact; revoking the phone retires it. `plans/current` is the same answer for both devices.
- **Mutation switch.** Set mutations_enabled: false in config/ios.v1.yaml to return every Phase 2
  mutation as 503 ios_mutations_disabled while bootstrap/today/history/progress remain available.
  The bootstrap capabilities report the writes as disabled. Settings → iOS settings edits this
  switch and the two TTLs without restart; the save validates and rewrites only those keys.
- **Errors.** Phase 2 conflicts use {"error", "code", "fields", "details"} with codes such as readiness_required,
  confirmation_required, workout_active, plan_expired, plan_superseded, plan_consumed,
  workout_not_active, session_rpe_required and idempotency_conflict. Validation failures remain 400.
- **Execution telemetry.** `workout_execution_event` is append-only and separate from
  `workout_event` (the server mutation/audit stream) and `workout_set` (the canonical performed
  set). Events are accepted only for a workout linked to the authenticated device. `occurred_at`
  is the original device time with a timezone; `received_at` is server time. A completed or
  abandoned workout accepts only events whose occurrence time falls inside its start/end bounds,
  which permits delayed offline replay without rewriting history. `set_id` is optional and must
  belong to the workout; `local_set_id` preserves a client identity when no server ID exists yet.
  The batch is all-or-nothing; retrying the same `Idempotency-Key` replays the response, while a
  new batch with an existing event ID is a duplicate or a 409 conflict. Execution events never
  create or modify sets. The read endpoint derives set durations only when both `set_started` and
  `set_completed` exist, rest durations only from explicit start/end events, and reports missing
  coverage rather than inferring it.
- **Offline timestamp preservation.** `performed_at` is optional on a set and must be an
  ISO-8601 timestamp no earlier than the workout start and not in the future; it is retained as
  the set's audit timestamp. `ended_at` is optional on completion and must fall between the start
  and now; when no manual `duration_min` is supplied, measured duration is start-to-`ended_at`.
- **Plan-item attribution.** A set's `plan_item_index` is the stable plan-item identity
  (`order_index`), not its current display position. It is optional. The client auto-attributes a
  unique exercise. When an exercise appears multiple times, the app lists the occurrences and
  defaults to Not attributed; selecting one sends that stable identity, while leaving it unselected
  sends nil. For backward compatibility an old display position is accepted only when it names the
  same exercise. The comparison response exposes `plan_item_index` (stable) and `display_index`
  (current order). An omitted index resolves only for a unique exercise; otherwise the set keeps no
  plan-item attribution.
- **Progress is available to the client in Phase 2.** GET /api/ios/v1/progress is the same
  progress_feature.dashboard payload used by the web UI; the native client has a Progress tab.
- **Retry boundary.** The client records each attempted mutation in a durable, capped journal
  before sending it. After relaunch it replays only those attempted operations with the original
  UUID and exact body, within a 28-day client window inside the server's 30-day receipt retention.
  Definitive 4xx responses remove the entry; idempotency conflicts and stale entries stop
  automatic replay and require review/discard. This is not an offline queue, and the server API is
  unchanged.
- **last_seen_at** is updated at most once per 60 seconds.
- **Dates.** `server_date`/`server_time` come from the server's local clock; the phone must
  not derive the training date from a UTC slice. `bootstrap` sends the numeric UTC offset and
  the platform timezone abbreviation, not an IANA name.

## Request security

**Home-network mode (2026-10-28, `DEC-WEB-03`; permanent 2026-11-25, `DEC-WEB-04`):** the loopback Host, Origin and
`Sec-Fetch-Site` guards were removed by owner decision; the UI binds `0.0.0.0` and has **no
authentication**. The accepted risk is `LIM-57`. Never expose it to the public internet.

What remains:

- `Content-Type: application/json` is required for mutation bodies, so a `text/plain` simple
  request cannot be used as a JSON body;
- request bodies are capped at 64 MiB;
- `/api/ios/v1/` is the only authenticated surface (per-device bearer token); every
  unversioned route remains unauthenticated as described above;
- logs do not record passwords or session tokens;
- authentication, per-user data, password reset, timezone onboarding, CSRF and TLS are **not
  planned** (`DEC-WEB-04`). The server must not be exposed beyond the home LAN.

## Request limits

- A request body is capped at **64 MiB** (`MAX_BODY_BYTES`) before it is read. This covers two
  20 MiB decoded CSVs plus JSON escaping and keys. The per-file limit remains **20 MiB** on the
  decoded UTF-8 text (`MAX_IMPORT_FILE_BYTES`).
- Oversized bodies return **413** before `rfile.read`; a missing length returns **411**;
  invalid, negative or duplicate lengths and chunked transfer return **400**. The connection is
  closed on every framing rejection. The browser maps 411/413 to plain next-action copy:
  “reload and try again” and “split or compress the file and try again.”
- The handler is HTTP/1.0 today. If it ever becomes HTTP/1.1, a rejected body must still be
  closed or drained.
- The import is JSON text, not multipart; the per-file check stays in the import handler.

## Dates

- The **local calendar date in YYYY-MM-DD** is authoritative for UI defaults and daily records.
  The server's local timezone is authoritative today; a profile timezone is not planned
  (`DEC-WEB-04`). Do not assume a remote browser shares it.
- Use `formatLocalDate`/`today`; never `toLocaleDateString` or a UTC
  `toISOString().slice(0, 10)` for a date default.

## Error responses

- Expected validation failures keep their useful 400/404/409 JSON messages.
- Form-validation 400s may add a `fields` map, for example
  `{"error": "...", "fields": {"main_lift_policy": "..."}}`. This is additive; clients that only
  read `error` keep working. Forms mark the named input `aria-invalid` and focus it.
- An unexpected server exception returns a stable `{"error": "internal server error"}` 500 and
  is logged with method, path and traceback. Exception classes, filesystem paths and database
  details are not returned to the client.

## Client modules

No build step and no bundler. The scripts load in this order:

1. `core.js` — API requests, HTML escaping, formatting, notices and local dates.
2. `adherence.js` — original/final prescription adherence rendering for history details.
3. `settings.js` — Settings panels: LLM, iOS, profile, volume, modalities and monitoring.
4. `app.js` — navigation, routing, boot and the shared views.
5. `exercises.js` — exercise catalogue, editor and e1RM override.
6. `history.js` — history list, session details, corrections and VBT backfill.
7. `workout.js` — live workout start, sets, end and post-workout screens.
8. `summary.js` — descriptive workout summary.
9. `performance.js` — performance and relationship panels.

Feature modules use the core helpers. `app.js` dispatches view loaders through `VIEW_LOADERS`
rather than an if-chain. Boot is deferred to `DOMContentLoaded` so every module is loaded
before a deep link can call its loader.


## Related

- **UI surface:** [WEB-UI.md](WEB-UI.md)
- **Architecture:** [ARCHITECTURE.md](ARCHITECTURE.md)
- **UI map:** [UI-MAP.md](UI-MAP.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
