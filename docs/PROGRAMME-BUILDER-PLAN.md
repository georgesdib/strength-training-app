# Programme Builder — parallel pathway plan

**Status:** planning only. No implementation, schema change, configuration change, API/CLI/UI
change or test change is part of this document.

**Scope:** a second programming pathway that runs alongside the existing template pathway. It is
not a replacement for templates and it does not change the current four session types, rolling
schedule, prescription engine, rules or historical data.

**Related:** [METHODOLOGY.md](METHODOLOGY.md), [WORKOUT-GENERATION.md](WORKOUT-GENERATION.md),
[SESSION-TEMPLATES.md](SESSION-TEMPLATES.md), [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md),
[LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md), [ROADMAP.md](../ROADMAP.md).

---

## 1. Purpose

The current app is a **session generator**. It chooses one of four canonical session types from
recent history, loads a fixed session template, and runs that session through the deterministic
prescription engine. The **Programme** page is a read-only forecast of that rolling process; it
stores no programme.

Some athletes need a coherent multi-week plan: a defined objective, a weekly structure, planned
progression, and an explicit lifecycle for reviewing and changing the plan. The Programme Builder
adds that layer without changing the template pathway.

The product direction is:

- **Pathway A — session templates.** Current behaviour remains the default when no programme is
  active. The rolling schedule, templates and prescription engine are unchanged.
- **Pathway B — Programme Builder.** The athlete defines a programme, the app generates a
  structured plan deterministically, the athlete reviews and approves it, and the active plan
  supplies future sessions to the existing prescription and workout infrastructure.

The two pathways share execution, not programming. They must not silently converge into one
scheduler.

---

## 2. Executive recommendation

1. Build a **programme layer above** the existing prescription engine. A programme declares
   weeks, sessions, roles and slot intent. The existing engine remains the only component that
   resolves kg, RIR, readiness, e1RM, volume trims, spinal limits and validation.
2. Use an explicit **SessionPlan** object (role + ordered slots) as the boundary between the
   programme and the prescription engine. A SessionPlan is template-shaped but not a shipped
   template.
3. Keep the programme **open-ended** as repeated generated cycles (default four weeks). One
   approved programme definition runs until changed; routine next blocks continue automatically
   when they stay inside the approved envelope and pass validation.
4. **MVP objective is strength.** Powerlifting and longevity are later. Cardio is out of scope
   because the current methodology explicitly does not prescribe cardio.
5. **Do not add new athlete-state fields for MVP.** Reuse the existing profile, constraints,
   suitability, frequency, duration, history and e1RM. Programme-specific choices (selected days,
   priority lifts/patterns, allowed alternatives) live in the programme definition.
6. **Deterministic only.** No LLM generates, edits or activates a programme. The LLM workstream
   remains separate and deferred.
7. Implement in phases after v1.2 and before LLM Iteration 1. Phase 0 is a formal decision and
   contract phase; no code starts before it is approved.

---

## 3. Verified current state

These are facts from the current `development` branch, not proposals.

| Area | Current reality | Consequence for this plan |
|---|---|---|
| Programme page | `features/programme.py` projects the rolling session sequence over 1–26 weeks and persists nothing. The page says "forecast only; rebuilt on the day". | The new builder needs its own persistence and lifecycle; the existing forecast remains Pathway A. |
| Scheduling | `prescribe/schedule.py` chooses one of `squat`, `hinge`, `bench_squat`, `bench_hinge` from recent history and family targets. | Pathway B cannot use this as its scheduler; it needs a programme-level calendar. |
| Templates | `config/templates/session-types.v1.yaml` defines ordered slots, sets, reps, RIR, rest, essential status and load source. `templates.SessionTemplate` is session-shaped. | Templates are not programmes. The `Slot` shape is reusable; the session-type lookup is not the programme model. |
| Prescription engine | `prescribe/engine.py::build_prescription` starts from a session type and loads a template, then applies readiness, e1RM, RIR, continuity, deload, volume, spinal and validation logic. | This is the one load/effort calculator. The builder must call it, not duplicate it. |
| Progression | The engine uses e1RM solving for main lifts and `PRG-DP-001` (double progression) for accessories. Weekly undulation exists as a small config cycle (`DEC-UNDUL-01`). | Reuse these; do not add a second progression calculator. |
| Volume | `features/volume.py` and `prescribe/volume_budget.py` use pattern-level MEV/MAV/MRV landmarks and configured targets. The landmarks are coaching guardrails, not measurements. | Reuse the ledger and budget. MVP allocates within movement patterns, not per-muscle constants. |
| Athlete state | `athlete_profile` holds competition date, sessions-per-week target, max session minutes, block/ramp anchor and volume flags. The old primary/secondary goal fields were removed (`DEC-STATE-02`). | There is no stored training objective, equipment list, experience level or selected weekdays. Programme-scoped definition is required for those choices. |
| Persistence | Prescriptions, prescription items, workout sessions and completed sessions are append-only and already snapshot the plan. There are no programme, block or phase tables. | Add new tables; do not rewrite historical prescriptions or sessions. |
| UI | The Programme page is a single forecast form and result table. Workflow owns readiness → preview → workout. | Keep the page name, add an internal toggle, and make Workflow read one global pathway mode. |
| Methodology | `DEC-PROGRAMME-01` says there is no fixed programme block; deloads are reactive with a configured scheduled option (`DEC-PROGRAMME-05`). `METHODOLOGY.md` says the app will never prescribe cardio. | Pathway B introduces an explicit programme/cycle concept. This needs a formal decision scoped to Pathway B, not a silent reversal. |

---

## 4. Design principles and non-goals

### Principles

1. **Python computes; the LLM never does.** The builder is deterministic and works with no
   provider configured.
2. **One load calculator.** The programme supplies structure and intent; `build_prescription`
   supplies kg, RIR, readiness adjustments, volume trims and safety validation.
3. **A programme is not a template collection.** It has identity, versions, weeks, sessions,
   progression rules and a lifecycle.
4. **Hard constraints are above the programme.** A programme cannot make an unsuitable exercise
   suitable, clear an injury, exceed the spinal cap knowingly, or bypass a readiness gate.
5. **History is immutable.** Programme edits and regeneration affect future planned sessions
   only. Old prescriptions, workouts and sessions keep their snapshots and links.
6. **Unknown is not normal.** An impossible or incomplete definition produces a clear,
   actionable validation failure, not a guessed programme.
7. **No false precision.** Volume, fatigue, readiness and spinal cost remain configured
   guardrails or ordinal models, not measured physiological constants.
8. **One pathway mode at a time.** The user can switch, but the app must not mix template and
   programme scheduling silently.

### Non-goals for the MVP

- Replacing or redesigning Pathway A.
- Universal programming for every sport or objective.
- Cardio prescription, cardio load modelling or a longevity programme that claims medical benefit.
- Equipment filtering, training-experience modelling or new athlete-state fields.
- Top set/back-off structures, drop sets, clusters or advanced intensity techniques.
- Block periodisation, meet peaking or weight-class management.
- Automatic programme adaptation from outcomes.
- LLM generation, explanation, proposals or autonomous edits.
- A full per-set programme editor.
- New dependencies.
- Any claim that the builder improves outcomes; it is a deterministic planning aid.

---

## 5. Architecture: where the boundary is

### 5.1 Two pathways, one execution core

```text
Pathway A (unchanged)
  readiness -> schedule.next_session_type -> SessionTemplate -> build_prescription -> workout

Pathway B (new)
  programme definition -> deterministic block generator -> SessionPlan
      -> build_prescription -> workout
```

Shared components:

- rules and policy evaluation;
- e1RM, load solving, RIR, warm-up, readiness, continuity, deload and spinal logic;
- volume ledger, volume budget and safety validators;
- prescription persistence, workout execution and history;
- API/UI shell and exercise taxonomy.

Pathway-specific components:

- Pathway A: rolling family scheduler and shipped session templates.
- Pathway B: programme definition, block generator, programme validator, programme lifecycle.

### 5.2 SessionPlan — the shared boundary

A `SessionPlan` is the programme's ordered slot list, expressed in the same vocabulary as a
session template:

- a **role** (for example `squat`, `hinge`, `bench_squat`, `bench_hinge`, `mixed`,
  `technique`);
- a display label and a time cap;
- ordered slots using the existing `Slot` shape: exercise or permitted variants, sets, rep
  range, RIR target, rest, essential flag, load source, and the existing power/quality fields
  where applicable;
- provenance: programme version, block, planned date and generation hash.

The SessionPlan is **not** a new prescription engine. It is a validated input to the existing
engine. The recommended implementation is to extend `build_prescription` so it accepts a
`SessionPlan` (or a template-like object) instead of only loading a named session type. When a
SessionPlan is supplied, the engine still applies every existing modifier and validator.

### 5.3 What stays template-specific

Some current rules assume a canonical session type:

- the rolling session-type sequence;
- upper-body balance and session ordering;
- the "no direct erector work on a hinge day" check;
- the six-session family targets.

For Pathway B:

- safety, RIR, spinal, volume, duration, readiness, e1RM and validation remain hard.
- the rolling family target is not used; the programme defines the sequence.
- upper-body balance, ordering and similar template-scheduling rules become **advisories** unless
  a later decision makes them hard for a named role.
- the erector check becomes **role-aware**; `mixed` sessions must be explicitly evaluated rather
  than silently exempted.

This is a required extension, not a reinterpretation of Pathway A.

### 5.4 Package boundary

Recommended new package: `strength_coach/programme/`, above `prescribe`, imported by the web
layer, CLI and tests. It may import `prescribe`, `store`, `rules`, `features` and `utils`.
`prescribe` must not import the programme package.

This keeps the dependency direction intact and prevents programme lifecycle concerns from leaking
into the session engine.

---

## 6. User control and programme lifecycle

### 6.1 One global pathway mode

Keep the page name **Programme**. Inside it, add a toggle:

- **Template forecast** — current behaviour, unchanged.
- **Programme Builder** — the new lifecycle.

The toggle is the single source of truth for the pathway. Workflow reads it:

1. athlete records readiness;
2. Workflow shows the next planned programme session when a programme is active;
3. otherwise it shows the template preview as today.

There is no second path selector in Workflow. A per-session selector would let an active programme
be bypassed session by session and would make progression and volume accounting ambiguous.

### 6.2 Lifecycle states

Recommended logical states:

- **draft** — editable generated or manually edited version;
- **proposed** — generated candidate awaiting review;
- **approved** — accepted by the athlete, not yet active;
- **active** — supplies future planned sessions;
- **archived** — preserved but not active;
- **superseded** — replaced by a newer version.

Because the repository is append-only, status is represented by **lifecycle events**, not by
mutating old versions. A version's content is frozen once it is approved. A manual edit creates a
new draft revision; it never edits an approved or active version in place.

### 6.3 Open-ended programme

An open-ended programme is not an infinite unvalidated stream. It is:

- one approved **programme definition** (objective, days, priorities, constraints, methodology
  envelope);
- generated **blocks** (default four weeks) inside that envelope;
- a review at each block boundary;
- automatic continuation for a routine next block only when all validators pass and nothing
  material changes;
- re-approval when the objective, days, methodology, phase structure, manual edit, volume/fatigue
  limits or validator warnings change.

The 4-week block length is a configurable default, not a physiological claim. The programme has no
terminal date; the athlete can archive it at any time.

### 6.4 Multiple programmes and switching

- Multiple programmes can be saved.
- One programme version can be active at a time.
- Activation is explicit and takes effect from a chosen date.
- Switching programmes is an explicit lifecycle event; it does not rewrite prior prescriptions.
- Starting a new workout while a programme session is in progress does not switch the active
  programme.
- Switching back to templates is an explicit event. It archives the programme or leaves it
  approved-but-inactive; the plan recommends **archiving the active version** and retaining history.

### 6.5 Editing

MVP editing is **plan-level**, matching the current workout plan editor's vocabulary:

- change planned sets within configured limits;
- swap an exercise to a validated alternative;
- add or remove a future session slot;
- change selected days or regenerate the next block;
- edit future sessions only.

There is no free-form per-set editor in the MVP. Completed sessions and historical prescriptions
are never edited by the programme builder.

### 6.6 Missed sessions

A missed session is recorded as missed, not silently moved. The next planned session remains on
its date unless the athlete explicitly reschedules or regenerates. The volume ledger sees actual
history, and the programme's future allocation can be regenerated from the new state.

---

## 7. Inputs and MVP scope

### 7.1 MVP objective

**Strength.** The builder optimises a strength plan using the existing strength tools. Powerlifting
meet preparation and longevity are later workstreams.

Longevity is not included because:

- the current methodology explicitly does not prescribe cardio;
- “longevity” would otherwise smuggle in cardio, rehabilitation or medical claims;
- the existing strength/accessory programme already carries the longevity context as a rationale,
  not a separate prescription mode.

A later longevity pathway would need its own methodology decision, not a renamed strength plan.

### 7.2 Programme-scoped definition (not new athlete state)

Reuse existing athlete state for constraints, suitability, frequency, duration, history and e1RM.
Store the following **with the programme**, because they are choices about this plan rather than
permanent athlete attributes:

- programme name and objective (strength for MVP);
- selected training weekdays (derived from the existing sessions-per-week target where possible);
- maximum session duration (default from `athlete_profile.max_session_minutes`, overridable per
  programme);
- priority lifts or movement patterns;
- preferred main lift and allowed alternatives;
- excluded exercises/patterns (in addition to existing constraints/suitability);
- planned cycle length (default four weeks);
- notes and approval context;
- methodology/config version and generation provenance.

No equipment list, training-experience field or primary/secondary goal field is added for the MVP.
That means:

- equipment is assumed to be the athlete's current available equipment; the builder cannot filter
  by equipment yet;
- exercise suitability and hard constraints are the only exclusion mechanisms;
- there is no experience-based volume or load adjustment;
- the plan must say this explicitly rather than pretending those inputs exist.

### 7.3 Validation of inputs

- Objective must be a supported value (only `strength` in MVP).
- Days must be a valid weekday set consistent with the frequency.
- Session duration must be within configured bounds.
- Priority lifts/patterns must be canonical ids/keys.
- Exclusions must be canonical and not contradict a required main lift without an alternative.
- Missing or contradictory input returns a field-level error; it never generates a guessed plan.

---

## 8. Programming methodology

### 8.1 Periodisation

**MVP:** a simple linear-within-cycle structure. A cycle shifts the weekly stimulus (for example
rep-range/RIR targets) and includes a planned lower-volume week or transition at the cycle
boundary when configured. Loads are still solved from the current e1RM at session time.

**Later:** block periodisation and a user-selectable methodology. Weekly undulation already exists
as a config cycle; it remains available to Pathway A and may be offered to Pathway B later.

**Evidence position:** linear and undulating periodisation have comparable strength outcomes in
the current evidence review; DUP is not superior. The app should present these as structure
choices, not as proven optimisation. See [TRAINING-DYNAMICS.md](TRAINING-DYNAMICS.md).

### 8.2 Set structure

**MVP:** straight sets only. The current `Slot` model expresses sets, reps and RIR; it does not
express a top set plus back-off sets.

**Later:** top set/back-off is an idea-backlog item with an evidence review, not a direct trial
against the current prescription ([TOP-SET-BACKOFF-EVIDENCE.md](TOP-SET-BACKOFF-EVIDENCE.md)).
It must not be added silently to the MVP.

### 8.3 Exercise progression

Reuse the existing mechanisms:

- main lifts: e1RM selection/solving and the current RIR windows;
- accessories: `PRG-DP-001` double progression, with its existing increment and comparability
  rules;
- bodyweight: the existing added-load rule;
- power/quality slots: existing quality stop, no load progression.

The programme may set week-level rep/RIR targets; it must not introduce a second
progression calculator or calculate kg independently.

### 8.4 Volume management

Reuse:

- the configured pattern-level MEV/MAV/MRV landmarks;
- the weekly volume budget and its exemptions;
- the under-MEV accessory rule and the MRV cap;
- readiness and deload set reductions.

The programme allocates **targets** across movement patterns. The runtime budget remains the
authority on safety and compensation. If a programme target and a runtime safety trim conflict,
the safety trim wins and the programme records a warning; the builder must not re-add a set that
readiness, deload, the spinal cap or a constraint removed.

MVP does **not** allocate by individual muscle group. The existing ledger is pattern-based; a
per-muscle model would need a new mapping and evidence, and would create false precision. This is
a documented limitation, not an implementation shortcut.

### 8.5 Fatigue and autoregulation

Reuse the existing readiness score, per-lift readiness, continuity, deload and spinal rules.
Do not add a new fatigue model in the MVP.

Planned deloads are part of the programme structure. Reactive/scheduled deload policy also
remains. The plan recommends:

- the programme may designate a planned deload/transition week;
- the existing deload policy still evaluates each session;
- the most restrictive applicable rule wins;
- a session never receives two independent deload reductions that stack without an explicit
  warning.

The exact precedence is a decision required in Phase 0.

### 8.6 Scientific limits to state in the UI

- MEV/MAV/MRV are coaching constructs, not measured individual thresholds.
- Volume and fatigue responses vary; the app cannot estimate individual MRV.
- Readiness weights and cut points are fixed assumptions, not validated personal thresholds.
- Spinal cost is ordinal and load-blind.
- e1RM is an estimate with individual and variant error.
- Linear vs undulating periodisation evidence does not establish superiority.
- A deterministic plan is reproducible, not proven optimal.
- The builder is a planning aid, not medical advice or injury prevention.

---

## 9. Deterministic generation engine

### 9.1 Pipeline

1. **Normalise the definition.** Validate objective, days, duration, priorities, exclusions and
   cycle length. Resolve existing athlete state, constraints, suitability and history as of the
   generation date.
2. **Select weekly roles.** Allocate sessions across the available days, respecting frequency,
   priority patterns, recovery spacing and role coverage. The sequence is deterministic.
3. **Allocate volume targets.** Distribute weekly sets across managed movement patterns within
   configured MEV/MAV/MRV guardrails and priority weights. No target exceeds the configured MRV.
4. **Build SessionPlans.** For each session, choose a role and ordered slots. Exercise choices use
   canonical ids, existing suitability/constraints and (where enabled) the existing selection
   engine. Every session gets sets, rep ranges, RIR targets, rest, essential flags and load source.
5. **Apply cycle progression.** Set week-level rep/RIR and volume targets. Do not write kg.
6. **Insert planned deload/transition.** Use config; do not create a second deload engine.
7. **Validate the programme.** Run programme-level validators and a dry-run of
   `build_prescription` for each session.
8. **Persist a draft and warnings.** No activation without review/approval.

The generator should be a pure function of its explicit inputs plus stored state/date. It must not
depend on wall-clock time, randomness or an LLM. If a choice is ambiguous, use a configured,
documented tie-break.

### 9.2 Reproducibility

Define reproducibility at two levels:

- **Programme structure:** same definition, config, methodology version, state snapshot and
  generation date window -> identical weeks, sessions, roles, slots and targets.
- **Session prescription:** actual kg may change when the session is built on a later date because
  e1RM, readiness, calibration or history changed. That is intended; the programme stores intent,
  not frozen kg.

The version stores an input hash, config hash, code/methodology version and generation timestamp.
A test must assert that the same inputs produce the same structural output.

### 9.3 Impossible or unsafe definitions

The generator must refuse rather than emit an unsafe plan. Examples:

- no valid main lift under constraints;
- selected days cannot fit the requested frequency;
- duration cannot fit the required essential work;
- weekly target cannot fit within MRV no matter how sets are allocated;
- priority pattern has no available exercise;
- a role has no main lift and is not explicitly technique/recovery.

The error must name the field/constraint and an actionable alternative. No silent fallback to a
template programme.

---

## 10. Data model

This is a proposed model, not a migration.

### 10.1 Tables

| table | purpose | key properties |
|---|---|---|
| `programme` | programme identity | `programme_id`, name, created_at; no mutable status field |
| `programme_version` | immutable content snapshot | `version_id`, `programme_id`, `parent_version_id`, `definition_json`, `methodology_version`, `config_hash`, `input_hash`, `created_at` |
| `programme_block` | generated block inside a version | `block_id`, `version_id`, `block_index`, `start_date`, `weeks`, `snapshot_json`, `created_at` |
| `programme_session` | planned future session | `session_id`, `block_id`, `sequence`, `planned_on`, `role`, `planned_json`, `status` |
| `programme_lifecycle_event` | append-only approval/activation/archival history | `event_id`, programme/version/block references, event type, `occurred_at`, note |
| `programme_session_prescription` | append-only link to generated prescriptions | `programme_session_id`, `prescription_id`, `linked_at` |

Optional later: a normalized `programme_slot` table if querying slots is needed. The first
implementation can keep the canonical slot list in `planned_json`; the snapshot is the audit
source, and normalized columns cover date/role/status queries.

### 10.2 Versioning and drafts

Recommendation: **append-only draft revisions plus immutable approved versions**. Every edit
creates a new `programme_version` row; status is derived from `programme_lifecycle_event`. This
avoids mutable programme rows and preserves an audit trail without introducing a second
append-only exception.

Lifecycle events are:

- `generated`, `edited`, `approved`, `activated`, `deactivated`, `archived`, `superseded`.

The current active version is the latest `activated` event that has not been followed by
`deactivated`/`archived`/`superseded`. One active version is enforced in the transaction and by a
unique partial index if the schema permits it.

### 10.3 Historical integrity

| change | effect on history |
|---|---|
| programme regenerated | old version, block and session rows remain; new version is a new row |
| programme manually edited | new draft version; old approved/active versions untouched |
| user switches pathways | no writes to prescriptions, workouts or sessions |
| methodology/config changes | old versions keep their version/hash; new generation uses the new one |
| active programme replaced | new activation event; old prescriptions keep their session/prescription links |

The programme link is a **new join table**, not a rewrite of `prescription` or `workout_session`.
A prescription generated from a programme session links to that session; a template prescription
has no link. Historical rows need no backfill.

### 10.4 Migration strategy

- Additive only: new tables and indexes; no changes to existing tables in the first migration.
- No backfill and no relabelling of historical workouts.
- Feature flag off by default; the app behaves exactly as today until enabled.
- Migration runs in the existing numbered-migration transaction pattern.
- Rollback is a code/feature-flag rollback, not a destructive downgrade; old tables are never
  dropped by the feature.
- A later migration may add indexes after query patterns are known; do not guess them now.

### 10.5 Configuration

A new config file would hold:

- default cycle length and block boundaries;
- supported objective(s) and role taxonomy;
- programme-level session limits (max slots, max sets per pattern);
- progression defaults and deload/transition rules;
- validator thresholds that are policy, not code.

Programme versions store the config hash so an old plan remains explainable after config changes.
No config file is added in this planning task.

---

## 11. UI, API and CLI

### 11.1 Programme page

Keep the name **Programme** and add a top-level toggle:

- **Template forecast** — the current form and result table, unchanged.
- **Programme Builder** — programme list, create/edit, review, approve, activate, archive.

The existing forecast's help text and behaviour stay intact. The toggle must be visible on mobile
and must not hide the current forecast behind an extra advanced disclosure.

### 11.2 Builder workflow

1. **Programmes** — saved programmes with status, active marker and last activity.
2. **Create / edit definition** — name, objective (strength), days, duration, priority
   lifts/patterns, allowed main lift/alternatives, exclusions, cycle length.
3. **Generate** — show progress; deterministic and cancellable.
4. **Review** — weeks and sessions, role, slots, sets/reps/RIR, warnings, validation summary,
   volume allocation, and a diff against the previous version.
5. **Edit** — plan-level actions on future sessions only, matching the existing workout plan
   editor's vocabulary.
6. **Approve and activate** — explicit action, activation date, confirmation of what changes.
7. **Switch / archive** — explicit lifecycle actions; prior history remains.

### 11.3 Reuse and new interactions

Reuse:

- form controls and the searchable exercise select;
- existing dialogs, tables, `table-scroll`, toast/notification pattern, section-help/doc-link
  contract and mobile target sizes;
- the existing exercise catalogue and suitability/constraint displays;
- the existing prescription preview/readout where possible.

New:

- week/block timeline;
- programme diff/version comparison;
- validation summary panel with field-level errors;
- lifecycle action bar;
- programme list and active marker;
- a read-only "next planned session" card in Workflow when a programme is active.

Restricted inputs use selects, segmented controls, checkboxes and date limits. No free-text
exercise names; canonical ids only. Free text is limited to programme name/notes.

### 11.4 API (proposed, not implemented)

- `GET /api/programmes` — list, active marker.
- `POST /api/programmes` — create definition; returns draft.
- `GET /api/programmes/{id}` — versions, blocks, sessions.
- `POST /api/programmes/{id}/generate` — deterministic generation; returns draft/validation.
- `POST /api/programmes/{id}/versions/{version}/approve` — approval event.
- `POST /api/programmes/{id}/versions/{version}/activate` — activation event/date.
- `POST /api/programmes/{id}/archive` — archive event.
- `GET /api/programmes/active/next-session` — next planned session for Workflow.
- `GET /api/programmes/{id}/diff?from=&to=` — version comparison.
- Existing `/api/programme` remains the template forecast; do not overload it.

### 11.5 CLI

The builder is UI-first because it needs the full definition/review workflow and exercise
selection. The plan recommends:

- Phase 4 exposes read-only `programme-builder status` and `programme-builder show` (or a later
  named command) for parity and automation;
- generation/editing/approval may remain UI-only initially, documented in
  [UI-CLI-PARITY.md](UI-CLI-PARITY.md) and ROADMAP §4.11;
- the existing `programme` command remains the template forecast and is not renamed.

This is a scope decision listed in §15.

---

## 12. Validation and testing strategy

### 12.1 Programme validators

Structural:

- supported schema and objective;
- required fields and valid weekday/time values;
- canonical exercise/pattern ids only;
- slot count/set limits;
- unique session sequence and planned dates.

Semantic:

- every session has a role and either a main lift or an explicit technique/recovery role;
- every slot has a valid load source, rep range, RIR window and rest;
- exercise choices satisfy suitability, constraints and exclusions;
- weekly pattern volume is within MEV/MRV guardrails;
- per-session and per-pattern caps hold;
- session duration estimate fits the configured target, with warnings when marginal;
- frequency and recovery spacing are feasible;
- progression is continuous across weeks;
- planned deloads/transitions do not stack with reactive reductions without warning;
- no impossible/contradictory input produces a plan.

Session-level:

- dry-run `build_prescription` for each session;
- existing validators: load executability, RIR window, spinal cap, erector role rule, constraints;
- readiness/continuity/deload/volume modifiers still apply.

Historical:

- a programme edit/regeneration creates new rows and never mutates old prescriptions/workouts;
- switching pathways leaves prior sessions and prescriptions unchanged.

### 12.2 Test layers

| layer | examples |
|---|---|
| unit | definition normalisation, role allocation, volume allocation, progression rules, lifecycle state transitions |
| integration | generator -> SessionPlan -> `build_prescription` -> validation -> persistence |
| regression | existing template golden fixtures, rules policy, volume budget, workout and history tests unchanged |
| golden | one or more synthetic strength programmes with full expected structure and warnings |
| migration | old database upgrades with empty programme tables; no changes to existing rows |
| API | create/generate/approve/activate/switch/next-session; expected 400/409 cases |
| UI contract | panel docs links, no inline handlers, script parse, mobile layout checklist |
| historical | prescription before/after programme switch remains byte-identical in its stored snapshot |
| determinism | same input hash/config/version produces the same structural output twice |

No new test dependency is required. Deterministic table-driven fixtures and invariant loops cover
the plan; Hypothesis is not added in the MVP.

### 12.3 Template-path invariants that must not change

- `schedule.next_session_type` behaviour and its tests;
- `SessionTemplate` parsing/validation and the four canonical types;
- `build_prescription` output for template sessions;
- `features/programme.py` forecast output and `/api/programme`;
- prescription/workout history and append-only rules;
- the current volume budget, readiness, spinal and deload behaviour.

---

## 13. Phased implementation plan

No dates are assigned. Phases are dependency-ordered.

### Phase 0 — Decisions and contracts (docs only)

**Objective:** obtain the formal decisions required to add an explicit Pathway B without
silently reversing existing methodology.

**Scope:** decision record(s) for the Pathway B programme concept, deload precedence, MVP
objective/set-structure/CLI scope; SessionPlan contract; lifecycle/versioning rules; validator
ownership.

**Architecture:** no code. Confirm the programme package boundary and the `build_prescription`
extension shape.

**Data model:** approve the table/link design in §10; no migration.

**UI/API/CLI:** approve the one-toggle Programme page and the API surface; confirm CLI deferral.

**Tests:** none; add acceptance criteria to the decision record.

**Acceptance:** decisions recorded; no implementation starts before approval.

**Risks:** unresolved methodology ambiguity; scope creep into a universal builder.

### Phase 1 — Foundations

**Objective:** create the programme domain, schema and persistence without changing any existing
pathway.

**Scope:** new tables, repositories, version/lifecycle events, SessionPlan contract,
programme-scoped definition validation; feature flag off.

**Architecture:** `strength_coach/programme/` package; no imports from `prescribe` upward.

**Data model:** additive migration; no backfill; link table.

**UI/API/CLI:** internal only; no user-visible builder yet.

**Tests:** migration, repository, lifecycle, schema validation, no changes to template tests.

**Acceptance:** old database upgrades cleanly; existing app behaviour is byte-identical with the
flag off.

**Risks:** schema over-design; accidental coupling to the prescription engine.

### Phase 2 — Deterministic generation MVP

**Objective:** generate a valid strength programme structure from the definition.

**Scope:** role allocation, pattern-level volume allocation within landmarks, SessionPlan building,
linear-within-cycle progression, planned deload/transition, dry-run validation; preview output.

**Architecture:** generator calls `build_prescription` for validation only; no new load maths.

**Data model:** draft versions/blocks/sessions; generation hashes.

**UI/API/CLI:** generation API and a read-only review payload; no activation yet. A CLI preview may
be added if cheap, but UI remains primary.

**Tests:** unit/integration/golden; impossible-input cases; determinism; no template regression.

**Acceptance:** a strength programme can be generated, reviewed and validated; it cannot be
activated.

**Risks:** arbitrary-session holes in validation; volume allocation becoming a second budget.

### Phase 3 — Lifecycle, review and approval

**Objective:** make programmes manageable and safe to switch.

**Scope:** programme list, draft edits, version diff, approval, activation, archive, one-active
enforcement, active mode; Programme page toggle.

**Architecture:** lifecycle events; no mutation of approved versions.

**Data model:** approval/activation events; active-version query.

**UI/API/CLI:** builder UI, lifecycle API; no Workflow prescription change yet.

**Tests:** state transitions, active uniqueness, approval/activation permissions, UI contracts.

**Acceptance:** athlete can create, review, edit, approve and activate a programme; switching is
explicit and history is untouched.

**Risks:** UI complexity/mobile overload; ambiguous approval semantics.

### Phase 4 — Prescription and workout integration

**Objective:** let an active programme supply the next session while preserving the template
pathway.

**Scope:** Workflow reads pathway mode, shows next planned programme session; build prescription
from SessionPlan; link prescriptions to programme sessions; history/provenance; no template
changes.

**Architecture:** extend `build_prescription` with SessionPlan/role support; role-aware validator;
link table.

**Data model:** `programme_session_prescription`; no changes to historical rows.

**UI/API/CLI:** Workflow next-session card; read-only CLI status/show.

**Tests:** integration with readiness/e1RM/volume/spinal; historical immutability; template
regression; API/CLI.

**Acceptance:** an active programme session can be prescribed, started and completed exactly like a
template session; switching to templates still works.

**Risks:** engine coupling; role-rule gaps; double deload/volume application.

### Phase 5 — Progression and volume enhancements

**Objective:** improve programme quality after the core loop works.

**Scope:** richer week-level progression, planned deload refinement, explicit programme volume
targets, session-duration balancing; top set/back-off only if separately approved.

**Architecture:** config-driven progression rules; no new load calculator.

**Data model:** versioned progression config/snapshot.

**UI/API/CLI:** review details; warnings.

**Tests:** progression continuity, volume invariants, deload precedence, golden fixtures.

**Acceptance:** programme quality improves without changing template behaviour or scientific claims.

**Risks:** overfitting to one athlete; false precision.

### Phase 6 — Monitoring, adaptation and refinement

**Objective:** make open-ended programmes reviewable.

**Scope:** adherence/progress summaries, block-boundary review, auto-continue within envelope,
warnings for missed sessions/volume drift; descriptive only.

**Architecture:** read-only reports; no automatic model tuning.

**Data model:** review events; no mutation of history.

**UI/API/CLI:** programme progress panel; review actions.

**Tests:** report correctness, auto-continue gates, no prescription change without approval.

**Acceptance:** the athlete can see whether the programme is being followed and decide whether to
continue, edit or regenerate.

**Risks:** adherence metrics being mistaken for effectiveness; auto-continue bypassing review.

### Phase 7 — Optional LLM assistance (deferred)

**Objective:** later explain/propose assistance, consistent with
[LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md).

**Scope:** none in this workstream. Any future LLM may explain a persisted programme or propose
bounded structural changes for deterministic validation; it may never calculate authoritative
loads/RIR/volume or activate a programme.

**Dependency:** deterministic builder phases 1–4 accepted; separate LLM decision and gates.

---

## 14. Risks and open technical questions

1. **Universal-builder scope creep.** The input list invites a general training platform. The MVP
   must stay strength-first and refuse unsupported objectives.
2. **Two volume models.** Programme allocation and the runtime budget can conflict. The runtime
   safety budget must remain authoritative; the programme must not re-add trimmed sets.
3. **Arbitrary sessions bypassing template assumptions.** The engine's erector/role checks,
   ordering and balance rules assume a session type. The SessionPlan/role validator is the
   mitigation, but it is the highest-risk code change.
4. **Open-ended lifecycle ambiguity.** Automatic next-block continuation must not silently change
   objective/methodology. The envelope and re-approval triggers need explicit tests.
5. **Historical traceability.** A join table is safer than altering prescription columns, but every
   new prescription path must write the link in the same transaction.
6. **Missing inputs.** No equipment/experience data means the builder cannot honour those parts of
   the brief. The plan must state the limitation rather than infer values.
7. **Longevity/cardio conflict.** A longevity pathway that prescribes cardio would violate
   `METHODOLOGY.md`; it is out of scope.
8. **Scientific overclaiming.** Volume landmarks, readiness weights, spinal cost and periodisation
   are not precise individual measurements. UI copy and acceptance tests must reflect that.
9. **Template regression.** The engine extension must be additive; existing template outputs and
   golden fixtures must remain unchanged.
10. **Mobile complexity.** A multi-week review/edit surface can become unusable on a phone. The
    plan requires a mobile checklist and a staged UI, not a desktop table squeezed onto mobile.

---

## 15. Decisions Required

The product direction is settled. These are the remaining decisions that require explicit owner
approval before implementation.

| # | decision | options | recommendation |
|---|---|---|---|
| 1 | **Pathway B methodology record** | (a) Treat explicit programmes as a separate pathway that does not change `DEC-PROGRAMME-01` for templates; (b) supersede the no-fixed-block decision globally | **(a)**. Record a scoped decision before code: Pathway A keeps no fixed block; Pathway B may declare an open-ended programme of rolling cycles. Do not silently reinterpret the existing decision. |
| 2 | **Planned deload authority** | (a) Programme may designate a planned deload, with existing reactive/scheduled policy still evaluated and never double-stacked; (b) programme owns deloads and disables the existing policy for active sessions | **(a)**. Reuse the existing deload machinery and define precedence in config/tests. |
| 3 | **CLI scope** | (a) UI-first builder; read-only status/show in Phase 4, editing/approval later; (b) full CLI parity from the start | **(a)**. The builder needs a multi-step review UI; document the temporary gap in [UI-CLI-PARITY.md](UI-CLI-PARITY.md). |
| 4 | **MVP set structure** | (a) Straight sets only; (b) include top set/back-off in MVP | **(a)**. Top set/back-off is still an evidence-review/idea-backlog item with no direct trial against the current prescription. |

No other product decisions block the plan. The implementation phases remain gated on Phase 0
approval.

---

## 16. Related

- **Methodology:** [METHODOLOGY.md](METHODOLOGY.md)
- **Workout generation:** [WORKOUT-GENERATION.md](WORKOUT-GENERATION.md)
- **Templates:** [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md)
- **Volume:** [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md)
- **Periodisation evidence:** [TRAINING-DYNAMICS.md](TRAINING-DYNAMICS.md)
- **LLM workstream:** [LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
