# Agent workflows — strength-training-app

Detailed procedures for working in the Python server. The lean entry point is
../AGENTS.md; workspace-wide rules are in ../../AGENTS.md.

## 1. Orientation

This is a local-first strength-coaching tool with a fixed methodology. Python computes;
the LLM explains. If the LLM is unavailable, the system still emits a safe, valid
prescription. The server is authoritative for readiness, prescriptions, loads, sets,
progression and scoring.

Read only what the task needs:
- ROADMAP.md — live phase status and next actions.
- docs/DECISIONS.md — expensive-to-reverse decisions.
- docs/DATA-MODEL.md — canonical schema.
- docs/API.md — HTTP contracts.
- docs/README.md and docs/manifest.yaml — public documentation index and metadata.

Keep CI workflow files aligned with main. Main is integration; development is where work
happens.

## 2. Domain rules agents must not undo

### Non-negotiable invariants

1. The constitution (docs/RULES-FORMAT.md, config/rules/) is the source of truth.
2. The LLM never does arithmetic; every prescription number comes from Python.
3. The policy engine may veto/downgrade the LLM; the reverse is forbidden.
4. Readiness is 1–5, higher is better. Stress = 5 means no stress.
5. 0 is column-specific; never apply a global sentinel rule.
6. Unknown thresholds go in config as an ASSUMPTION, never invented science.
7. Prescriptions, critiques, calibrations and rule versions are append-only.
8. Never deduplicate repeated training rows.
9. Unknown exercise names are resolved or reported, never silently dropped.
10. Non-obvious decisions get a one-line domain-reason comment.
11. Goals, injuries and preferences are stored athlete state, not prompt text.
12. Empty/incomplete input produces unknown, never pass.
13. Never commit personal data; data/ and private/ are git-ignored.

### Sentinel rules

| Column | 0 means | Handling |
|---|---|---|
| Avg_velocity, Avg_power, Avg_rom, TUT | device not used | sentinel to NaN |
| Weight_Used | unweighted bodyweight | valid; preserve |
| RIR | true failure | valid; preserve; RIR 6 = warm-up |
| readiness Weight/HRV/RHR | missing | sentinel to NaN |
| readiness *_Readiness | missing | sentinel to NaN |
| readiness Sleep/Energy/Mood/Soreness/Stress | impossible | no sentinel |

Never reuse dates.NULL_DATE_TOKENS for numeric columns; it contains 0 and would erase
genuine RIR 0 observations.

### Exercise identity

- Resolve every raw name through utils.exercises; never branch on a raw log string.
- Preserve DEC-TRAPBAR-02 (date-scoped competition deadlift identity).
- Back extension and hyperextension share history; prefer back_extension when prescribing.
- RIR 6 is a warm-up, excluded from working volume/e1RM adjustment but preserved.
- Bodyweight progression acts on added load; total mass is used only for e1RM.
- Trap-bar RIR uses the default window; the empty override map is intentional.
- Effort window is RIR 1–4 with a 2–3 target; RIR 0 is forbidden.
- Adding an exercise is YAML, not Python. New properties need schema/docs updates.

## 3. Code layout

Import direction points down:
utils ← domain ← ingest/store ← features ← rules/prescribe/critique ← agents/eval.

- Shared computation belongs in utils (pure) or domain (domain arithmetic), never re-implemented.
- Config, not code: taxonomy, templates, rules, thresholds, rep ranges, load increments.
- Prefer small pure functions with explicit inputs; no global mutable state.
- Type-hint public functions; docstrings explain why.
- Python 3.11+; use from __future__ import annotations.
- No new dependency without a reason.

## 4. Tests and definition of done

Run the narrowest relevant tests while iterating. The default suite excludes integration,
golden, regression and slow layers.

    .venv/bin/python -m pytest tests/test_prescribe.py tests/test_rules_policy.py
    .venv/bin/python -m pytest --lf
    .venv/bin/python -m pytest -m "not integration and not golden and not regression and not slow"
    .venv/bin/python -m pytest -n 0

Run the default suite once before handing off. Optional layers run only when the owner
asks or in the release workflow:

    .venv/bin/python -m pytest -m "integration or regression or slow" --dist loadfile

A change is done when:
1. Relevant tests pass, and new behaviour has a test that fails without it.
2. Measured-fact changes still match private/docs/EVIDENCE.md, or both are updated.
3. Config changes carry a domain reason.
4. Judgement calls are recorded as assumptions/open questions.
5. Documentation checks pass when docs change.
6. Multi-statement writes use strength_coach.store.db.transaction.
7. Web handlers use data-action plus delegation, never dynamic inline handlers.
8. Dates use formatLocalDate/today, never UTC slices for machine defaults.
9. Unexpected web errors return a generic 500 and are logged; expected 400/404/409 stay useful.
10. Request bodies respect MAX_BODY_BYTES; never read an unbounded Content-Length.
11. ruff check passes; line length 110; no new per-file ignore without a reason.

Tests assert contracts, not incidental order. Golden fixtures pin full item order only
because the prescription is user-facing. If a test fails only because an unrelated item
moved, the test is too literal. Integration tests that import real exports are marked and
must not run in the fast lane; synthesise public test data.

### Waiting for long suites

Do not poll a running suite in short increments. Estimate from collected count/recent runs,
start it as a managed background job, wait once near that estimate, then inspect once.
Report the final summary.

## 5. Documentation governance

- docs/manifest.yaml is authoritative for public document metadata.
- Current public guidance lives in docs/ and gets a manifest entry.
- Internal design specs live in docs/design/ (maintainer audience).
- Completed plans/audits move to docs/archive/ and get a row in its README.
- Link to the canonical explanation; do not maintain duplicate descriptions.
- Never add private/ to the manifest, viewer or a public index.
- docs/README.md is the human index; docs/manifest.yaml is the machine index.
- tests/test_docs_manifest.py and tests/test_docs_consistency.py enforce coverage, links,
  DEC/LIM references and the public/private boundary.

Do not duplicate the full docs map here. The manifest and docs/README.md are the source.

## 6. CLI/UI parity

Everything built in the CLI should also be available in the local web UI where practicable,
in the same change. The UI calls the same core function as the CLI, never re-implements it.

If a capability cannot reasonably live in the UI (interactive prompt, destructive migration,
host-level operation), record the exception in docs/WEB-UI.md and ROADMAP.md rather than
leaving it silently missing.

The in-browser terminal was removed (DEC-WEB-02). Do not reintroduce a state-changing
browser command runner without authentication.

Standing permission: restart the local web process when code changes make it stale, without
asking first. Restart it the same way it was started (same DB/bind/port, detached), then
verify:
- GET / returns 200.
- POST /api/programme returns 200.
- The served HTML no longer contains removed pages.

Config-only edits do not need a restart; any change under strength_coach/ does.

## 7. Ask before changing

- Adding a hard rule.
- Changing a threshold that affects a prescription.
- Interpreting an ambiguous rule; add it to OPEN-QUESTIONS.md.
- Phase status changes; update ROADMAP.md in the same commit.
- Fixing data that looks wrong: flag/quarantine, never silently delete.

State the ambiguity, options and recommendation, then wait.

## 8. Migrations

See AGENT-MIGRATIONS.md for schema, append-only, transaction, preservation and test rules.
See AGENT-DEBUGGING.md for logs, failure triage and data quarantine.

## 9. Documentation map

| File | Contents |
|---|---|
| `USER-GUIDE.md` | how to install, run and read the output (the human-facing entry point) |
| `ROADMAP.md` | live phase status, next actions, resume checklist |
| `docs/README.md` | documentation index, category map and maintenance rules; `docs/manifest.yaml` is authoritative |
| `docs/AGENT-WORKFLOWS.md` | detailed server agent procedures: orientation, code, tests, docs, CLI/UI parity |
| `docs/AGENT-MIGRATIONS.md` | append-only, schema, migration, transaction and preservation rules |
| `docs/AGENT-DEBUGGING.md` | logs, failure triage, data incidents and long-running test procedures |
| `docs/FORM-PROSPECTIVE.md` | open prospective form evaluation: anchors, sampling, outcomes and limits |
| `docs/FORM-USE-EVIDENCE.md` | form evidence review, retrospective association and allowed uses |
| `docs/FREQUENCY-AND-VOLUME.md` | reproduced `programme --sessions-per-week` behaviour, existing volume rules, evidence and the closed Q26 dates-only decision |
| `docs/archive/VOLUME-MODULATION-PLAN.md` | implemented and closed weekly target/session cap volume budget, exemptions, effective accounting and modality layer |
| `docs/VOLUME-BUDGET.md` | operator guide to the consolidated Volume budget panel: targets, caps, floors, policy, drop, compensation, profile storage and validation |
| `docs/FORM-ASSESSMENT.md` | optional per-lift 1-5 form assessment; Workout/History and rubric 1.2.0 |
| `docs/REGIME-CHANGE.md` | read-only main-lift/substitute regime check; thresholds and limits |
| `docs/archive/AUDIT-CLOSEOUT.md` | final W0–W12 audit outcome, implemented fixes and remaining limitations |
| `docs/archive/audits/W11-W12-CLOSEOUT.md` | W11 documentation consistency (including rubric 1.1.0 duration) and W12 public-data inventory/history decision |
| `docs/archive/audits/W10-AGE.md` | W10 age-in-state audit; optional birth-year, wording and no age-based load rule |
| `docs/archive/audits/W8-VOLUME-BALANCE.md` | W8 weekly set/spinal/time balance and four options; no change |
| `docs/archive/audits/W5-PROSPECTIVE-EVALUATION.md` | W5 prospective protocol and implemented read-only summary |
| `docs/OUTCOMES.md` | read-only 4/8/12-week outcomes review: what changed, not why |
| `docs/archive/audits/W4-PROGRAMME-EVIDENCE.md` | W4 evidence classification and user-facing evidence labels |
| `docs/LIMITATIONS-REGISTER.md` | living index of known limitations from all audits |
| `docs/METHODOLOGY.md` | canonical versioned decision flow, limitations, never-do list and change control |
| `docs/PRIVACY.md` | public/private documentation boundary; no new personal health/performance data; external-LLM payload and sensitive-field rules |
| `docs/RELEASING.md` | CI checks, pinned dependencies, release tagging, artifact generation and branch-protection requirements |
| `docs/DECISIONS.md` | append-only decision log (`DEC-*`) with where each is enforced |
| `docs/REFERENCES.md` | consolidated scientific bibliography with DOIs and where each is used |
| `docs/ARCHITECTURE.md` | layers, data flow, where the LLM sits |
| `docs/DATA-MODEL.md` | canonical schemas, tables, append-only records |
| `docs/DATA-QUALITY.md` | the decision ledger (DQ-*) and open sentinel questions |
| `docs/READINESS.md` | how readiness is derived, merged and used; what is config vs rule |
| `docs/READINESS-SCORE.md` | implemented global, category and per-lift readiness scoring; evidence, phases, overrides and limits |
| `docs/READINESS-WEIGHT-EVIDENCE.md` | readiness-weight evidence and held-out comparison; learned weights closed |
| `docs/CONTINUITY.md` | gap detection and re-entry rules; the injury signal is separate |
| `docs/INJURY-SIGNAL.md` | per-region injury signals, what "tolerated" loading means, injury-to-exercise links |
| `docs/INJURY-ATTRIBUTION-PLAN.md` | injury-signal verification hygiene and optional session/lift symptom attribution (Phases 1–2 closed; Phase 3 is separate roadmap §4.28) |
| `docs/SYMPTOM-LOGGING.md` | the 0-3 reading: what counts as a flare, and what to log when a symptom settles |
| `docs/archive/AUDIT-FOLLOW-UP-PLAN.md` | implemented audit follow-up: back-flare scope, quality-limited power, programme-document drift, same-date accounting and the audit gate |
| `docs/archive/AUDIT-FOLLOW-UP-REPORT.md` | closed audit follow-up report: five fixes verified, all residuals closed, accepted coverage limitations and no follow-up actions |
| `docs/CORE-TRAINING.md` | core/trunk training evidence and the proposed programme amendment |
| `docs/LONGEVITY-REVIEW.md` | modality review against the longevity-first goal: gaps, doses, priorities |
| `docs/FATIGUE-FITNESS.md` | fatigue-fitness evidence, strength recovery, e1RM calibration and why no model drives loads |
| `docs/LIFT-READINESS.md` | per-lift readiness evidence, components, weights and downward-only rule |
| `docs/EXERCISE-VARIANTS.md` | how to add a canonical variant, slot wiring, history caveat, selection tuning |
| `docs/EXERCISE-DEMANDS.md` | companion demand catalogue: six dimensions, per-dimension levels, provenance, coverage, upper-bound rule and no aggregate |
| `docs/FATIGUE-SIGNALS.md` | Parts A–D: exposure ratio, VBT residual, suggest-only substitution, advisories, shadow table, flags and activation gates |
| `docs/SESSION-TEMPLATES.md` | field guide to session templates: scheduling source of truth, prescription blocks, slot fields, variants, day roles and safety rules |
| `docs/archive/VARIANT-PATTERN-AUDIT.md` | 2026-10-20 variant pattern/muscle audit: checked exceptions and applied corrections |
| `docs/SELECTION-COMPARABILITY.md` | evidence and proposed three-class guard for variant substitution |
| `docs/READINESS-EXERCISE-SELECTION-PLAN.md` | implemented readiness/symptom substitution policy and review panel; automatic withholding deferred |
| `docs/STRENGTH-PROGRAM-REVIEW.md` | evidence check and critique of the strength programme (review only) |
| `docs/RUBRIC-CALIBRATION.md` | calibration loop, B1 review outcome, next actions and limits |
| `docs/VOLUME-MANAGEMENT.md` | MEV/MAV/MRV evidence, configured landmarks, ledger and MRV cap |
| `docs/archive/NEXT-PHASE-FATIGUE-PLAN.md` | final lean non-cardio fatigue plan: sRPE/duration backfill, descriptive calibration, optional deload; no experiments |
| `docs/RETROSPECTIVE-VALIDATION.md` | retrospective walk-forward method/result; not prospective; no model adoption |
| `docs/WEAKNESS-INJURY-SELECTION.md` | evidence and deferral of weakness/injury-targeted selection |
| `docs/PARENT-VARIANT-WEAKNESS-EVIDENCE.md` | why parent-variant ratios are not weakness or injury measures |
| `docs/REVERSE-HYPER-BELT-SQUAT-EVIDENCE.md` | reverse hyperextension and belt squat evidence; optional accessories, no programme change |
| `docs/WEAKNESS-TARGETING-PLAN.md` | gated weakness metric, retrospective screen and N-of-1 test plan |
| `docs/LLM-INTEGRATION-PLAN.md` | future LLM analyst/explainer/constrained-proposer architecture: Iteration 1 (practical capabilities, selector retirement), conditional Iteration 2 (retrieval/RAG/advanced orchestration), shared context/evidence contracts, approval, privacy and evaluation gates; plan only |
| `docs/IOS-CLIENT-PLAN.md` | Phase 0, Phase 1 and Phase 2 complete and accepted 2026-11-07 (simulator and physical-iPhone verified); R1 durable pending-mutation journal closed post-acceptance; R3 explicit plan-item selection, R4 form-rating correction UX and R5 recovery/reconciliation UX closed; Phase 3A HealthKit HRV/RHR/bodyweight readiness closed 2026-11-08; R7 asynchronous prescription request with workout settings implemented, simulator-verified and closed 2026-11-08; R2 closed as absorbed by R7; R8 active-workout plan editing closed; Phase 4 offline capture/replay closed 2026-11-08; authenticated online-first native strength workflow; optional Apple on-device/PCC AI |
| `docs/archive/PROGRAMME-BUILDER-PLAN.md` | deterministic dynamic template resolver: fixed four-template blueprint/fallback, per-session exercise resolution, versioned policy and provenance, reuse of the existing scheduler/prescription/volume/history; Steps 0–6 implemented and closed |
| `docs/archive/RESOLVER-ACCEPTANCE-AUDIT.md` | closed end-to-end production acceptance audit: P0/P1/P2 findings, fixes, acceptance matrix and residual release gates |
| `docs/PERFORMANCE-PROFILE.md` | 2026-11-04 resolver prescription benchmark, 2026-11-05 clean-set snapshot A/B, stage profile, cache design/invalidation and parallelism assessment |
| `docs/TRAINING-DAY-MODEL.md` | implemented training-day/session-fragment model: one local date may hold multiple fragments, day-level attendance/e1RM, combined volume/spinal, shared readiness, no schema migration |
| `docs/WEB-UI.md` | local web UI surface and its limitations |
| `docs/API.md` | HTTP API reference: routes, request security and limits, dates, errors and client modules |
| `docs/MONITORING-ANALYSIS.md` | read-only exploratory monitoring analysis: dose, lagged associations, calibration transparency, API/UI/CLI, non-causal limits and privacy |
| `docs/WORKOUT-GENERATION.md` | Plain-English explanation of the deterministic prescription pipeline, inputs, modifiers, validation and limitations |
| `docs/UI-CLI-PARITY.md` | current first-class parity, intentional differences and remaining gaps |
| `docs/UI-MAP.md` | web UI surface map: panels, routes, docs links and the behaviour each panel exposes |
| `docs/archive/UI-IMPROVEMENT-PLAN.md` | UI-04/UI-08 plus the final functionality/code audit: findings ledger, workstreams, permanent guardrails, commit sequence and optional follow-ups; closed 2026-10-27 (implemented and merged into `main`) |
| `docs/archive/UI-MOBILE-AUDIT.md` | consolidated iPhone UI/usability and form-control audit: P0 contract defects, active-workout findings, restricted-choice inventory, verification and checkpoints; closed 2026-10-28 (implemented, verified, native pass complete) |
| `docs/archive/UI-DESIGN-IMPLEMENTATION-PLAN.md` | six-area UI audit, existing API/data inventory, prioritized milestones, acceptance criteria and explicit data/architecture deferrals |
| `docs/RIR-EVIDENCE.md` | why the effort window is RIR 1-4 with a 2-3 target |
| `docs/SPINAL-COST.md` | evidence behind the ordinal spinal-cost ratings |
| `docs/SPINAL-LOAD-EVIDENCE.md` | focused review of load-weighting; keep ordinal, no load/RIR weighting |
| `config/spinal-heavy-exposure.v1.yaml` | heavy-set advisory threshold/window; display only |
| `docs/TRAINING-DYNAMICS.md` | evidence on 1RM testing, rep ranges and DUP; proposal, not decision |
| `docs/JUMP-VARIANTS.md` | jump-training evidence and implementation: box jump on squat, broad jump on hinge, quality limits and alternatives |
| `docs/THROW-VARIANTS.md` | upper-body throw evidence and implementation: medicine-ball chest pass on both bench days, implement-only quality limits |
| `docs/WORKOUT-TYPE-READINESS-EVIDENCE.md` | evidence/decision: readiness and injury adjust load/sets, not the planned rep scheme |
| `docs/HIGH-INTENSITY-EXPOSURE-PLAN.md` | detailed proposal: tests/max attempts/competition exposures, guard windows, evidence and phased evaluation |
| `docs/archive/ENGINE-AUDIT-PLAN.md` | closed W0–W12 audit plan; outcome in `docs/archive/AUDIT-CLOSEOUT.md` |
| `docs/archive/READINESS-AUDIT.md` | W6 audit: readiness vs no readiness is not identifiable retrospectively; descriptive associations and policy options |
| `docs/archive/audits/W2-LOAD-LINEAGE.md` | W2 audit: load lineage; bodyweight-basis and incomplete-workout defects fixed |
| `docs/archive/audits/W9-SPINAL-CAP.md` | W9 audit: explicit high-fatigue costs, at-cap display; cap 3 at close, superseded by cap 6 in §8 |
| `docs/archive/audits/W1-W7-ATTENDANCE.md` | W1 schedule audit and W7 attendance metrics; forecast-deload path and session cap implemented |
| `docs/archive/audits/W0-EXECUTION-MAP.md` | W0 execution map, modifier ownership/order, input risks, test coverage and candidate findings |
| `docs/archive/audits/W3-MODIFIER-MATRIX.md` | W3 audit: six confirmed deload/order/floor/RIR defects, fixed and tested |
| `docs/archive/audits/W3-INTERACTION-MATRIX-2026-10-31.md` | 768-case modifier interaction matrix: method, raw flags, preliminary triage and next pass; LIM-30 remains open |
| `docs/MINIMUM-SESSION.md` | `MOD-MIN-001` user-selected volume-only fallback: targets, floors, precedence, refusal and provenance |
| `docs/archive/IMPLEMENTATION-PLAN-2026-10.md` | approved direction and phased implementation plan; A0–F implemented |
| `docs/archive/TEST-FATIGUE-PLAN.md` | superseded narrow test-fatigue proposal; points to the broader plan |
| `docs/TECHNIQUE-THROTTLE.md` | user-declared one-session load/RIR throttle (`MOD-TECH-001`); why the automatic form was rejected |
| `docs/RULES-FORMAT.md` | citable rule IDs + 5 encoded rules |
| `docs/VBT-CALIBRATION.md` | clean set, sparsity, overrides, versioning, current wiring |
| `docs/VBT-EVIDENCE.md` | VBT evidence, best practices, what our data can and cannot support |
| `docs/VBT-REP-LEVEL.md` | post-hoc rep-level VBT: benefits, limitations and optional device-CSV capture |
| `docs/REP-VELOCITY.md` | optional per-rep CSV contract, storage, analyses and limits |
| `docs/REP-VELOCITY-EVIDENCE.md` | velocity-loss evidence; descriptive only, no RIR/injury prediction |
| `docs/TOP-SET-BACKOFF-EVIDENCE.md` | top set/back-off review; no direct trial, no programme change |
| `docs/archive/MODULE-LAYOUT.md` | file layout and test strategy |
| `docs/V0-SCOPE.md` | smallest end-to-end slice and its exclusions |
| `docs/OPEN-QUESTIONS.md` | ranked design questions blocking the build |
| `docs/SANITY-CHECKS.md` | external verification of classification/formulas |
| `docs/TRAINING-GUIDELINES.md` | programme vs published evidence, with conflicts |
| `private/docs/EVIDENCE.md` | measured profile of a real export (personal) |
| `private/docs/BASELINE.md` | current strength baseline (personal) |
| `private/docs/INFO-REQUESTS.md` | goals/injury/suitability backlog (personal) |
