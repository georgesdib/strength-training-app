# Deterministic Template Generator — implementation plan

**Status:** planning only. No code, schema, configuration, API, CLI, UI or test change is part
of this document.

**Scope:** replace the fixed, manually maintained session templates with a deterministic
generator that produces a complete set of four valid `SessionTemplate` instances. The generator
does **not** replace the rolling scheduler, prescription engine, volume engine, workout
execution or history.

This document replaces the earlier “parallel Programme Builder” plan. That plan introduced a
separate programme/block/session lifecycle and was too large. The current direction is smaller:
generate templates once, review them, activate a version, and keep using the existing training
system.

**Related:** [METHODOLOGY.md](METHODOLOGY.md), [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md),
[WORKOUT-GENERATION.md](WORKOUT-GENERATION.md), [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md),
[LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md), [ROADMAP.md](../ROADMAP.md).

---

## 1. Executive summary

1. The app keeps one training system: the rolling four-session-type scheduler and
   `build_prescription`.
2. The only new capability is a **template generator**: it produces a complete set of four
   `SessionTemplate` objects using the existing schema, exercise taxonomy, constraints,
   suitability, volume landmarks and prescription rules.
3. A generated set is stored as an immutable **template version**. The active version is a
   single pointer. The shipped YAML template file remains the default fallback.
4. Generation is explicit and one-off. There is no automatic regeneration, no programme
   lifecycle and no programme-level progression engine.
5. Existing runtime behaviour continues to adapt every prescription: readiness, e1RM, RIR,
   double progression, deload, volume budget, spinal cap and validation.
6. Power is a required part of the generated configuration, using the existing `Slot.power`
   and `quality_stop` mechanism.
7. No new athlete inputs are added for the MVP. The generator uses existing frequency, duration,
   constraints, suitability, history and taxonomy. Objectives, equipment, experience and
   muscle-group priorities are deliberately out of scope.
8. The work is delivered on a `feature/template-generator` branch and merged back at phase
   gates, never as one long-lived divergence.

---

## 2. Verified current architecture

These are facts about the current `development` branch.

| Component | Current behaviour | Consequence |
|---|---|---|
| Template schema | `prescribe/templates.py` defines `Slot` and `SessionTemplate`; `validate_text` requires exactly the four canonical types, at least one essential slot, valid load sources, and power slots with a quality stop and no RIR. | Generated templates can reuse the schema and most validation. The generator must emit exactly four valid types. |
| Template loading | `SessionTemplate.load(session_type)` reads `config/templates/session-types.v1.yaml`. | A generated set needs a resolver separate from the shipped file; otherwise every caller would read the default. |
| Prescription | `build_prescription(..., template=...)` accepts an optional template. The normal CLI/web path does not pass one; only `features/programme.py` does. | Injection exists but is not wired. This is the main integration point. |
| Scheduler | `schedule.next_session_type` loads a template to read `primary_exercise` and choose among the four types. | It must read the active template set, not the shipped file. No new scheduler is needed. |
| Volume | `volume_budget.template_rows`, `plan_drop`, `report`, `apply` and related functions load templates by `session_type`. | They need the active template set or an explicit template argument. Do not create a second volume engine. |
| Selection | `selection.py`, `fatigue_selection.py` and `demand_scope.py` load templates by type. | They need the active set when choosing exercises for a generated template. |
| Critique | `critique/facts.py` loads the template by `session_type` at critique time for rep ranges. | A template change can alter an old session's critique. New prescriptions need a template-version link and critique must use that snapshot. |
| History | Prescriptions and workouts are append-only; prescription items already store the actual prescribed work. | Add a nullable template-version link; never rewrite old rows. |
| UI | The forecast lives on the Programme page. The YAML template editor lives on Exercises and writes the single shipped file with backups. | Programme becomes template management; forecast becomes its own view; the YAML editor moves under Programme and edits versions. |

---

## 3. Architecture

### 3.1 One execution path

```text
                 shipped default YAML
                         |
generator -> template version (YAML snapshot) -> active template set
                         |
athlete readiness -> rolling scheduler -> SessionTemplate -> build_prescription
                                                               |
                                                        workout / history
```

The scheduler still chooses `squat`, `hinge`, `bench_squat` or `bench_hinge`. The
prescription engine still computes loads, RIR, readiness, volume, spinal limits and validation.
The only difference is where the four `SessionTemplate` instances come from.

### 3.2 TemplateSet and TemplateVersion

- `TemplateVersion`: immutable snapshot of one complete four-template YAML document.
- `TemplateSet`: resolved mapping `session_type -> SessionTemplate` for one version, plus the
  version id and content hash.
- `active version`: the version currently used for future prescriptions. Null/default is the
  shipped fallback.

The resolver is explicit:

- future-session callers load the active version;
- historical readers use the version linked to the prescription;
- tests can pass a synthetic TemplateSet without touching the database or file system.

Do **not** make `SessionTemplate.load()` silently read the active database version. That would
make historical critique and tests depend on mutable state.

### 3.3 What is reused, extended and new

**Reused unchanged**

- `Slot`, `SessionTemplate`, `validate_text`, four canonical identities.
- Rolling scheduler logic.
- `build_prescription` load, RIR, readiness, e1RM, continuity, deload, spinal, volume and
  validation logic.
- Exercise taxonomy, suitability, constraints and selection comparability rules.
- Workout execution, prescription persistence, history and append-only rules.
- Existing config landmarks and modifiers.

**Extended with small, explicit changes**

- `build_prescription` accepts a `TemplateSet`/resolved template for the future path while
  keeping its current signature compatible.
- `schedule`, `volume_budget`, selection and critique accept the resolved template/version
  instead of loading the shipped file.
- `prescription` gets a nullable `template_version_id`.
- The template API/UI can write versioned database rows instead of only the shipped YAML file.

**New**

- A deterministic generator module and a generator configuration spec.
- Template version/state persistence and repositories.
- Generator-specific validation (weekly volume, power placement, duration, overlap).
- Programme-page version management UI and a separate Forecast view.
- Tests for all of the above.

**Not new**

- No second scheduler.
- No second prescription engine.
- No second volume-management engine.
- No programme/block/session lifecycle or event sourcing.
- No automatic regeneration.
- No LLM generation.
- No cardio programming.

### 3.4 Dependency map for template resolution

Every current `SessionTemplate.load` call site must be classified:

| call site | future session | historical/read-only | required change |
|---|---|---|---|
| `prescribe/engine.py` | yes | no | use passed TemplateSet, default fallback |
| `prescribe/schedule.py` | yes | no | use active TemplateSet |
| `prescribe/volume_budget.py` | yes | no | accept template/template set in template rows, drop, report, apply |
| `prescribe/selection.py` | yes | no | use active template for the requested session |
| `prescribe/fatigue_selection.py` | yes | no | same |
| `prescribe/demand_scope.py` | both | yes | use explicit template/version |
| `critique/facts.py` | no | yes | use the prescription's template version snapshot |
| `features/programme.py` | forecast | no | use active TemplateSet |
| `prescribe/summary.py` | docs/summary | no | render from active/selected version |
| `agents/proposal.py` | future | no | defer; use active TemplateSet when LLM work resumes |

This map is the core of the implementation. Missing one call site would silently mix the default
file with a generated set.

---

## 4. Inputs and scope

### 4.1 Existing inputs only

No new athlete-state fields are added. The generator uses:

- `sessions_per_week_target` for intended frequency;
- `max_session_minutes` for session duration;
- `athlete_constraint` for hard exclusions and injury constraints;
- `exercise_suitability` for can-do/will-do/feels-bad;
- stored training history and e1RM for availability and load history;
- the exercise taxonomy for patterns, muscles, loadability and power classification;
- the existing volume landmarks/targets and session-time estimates.

### 4.2 Deliberately excluded

- **Objectives and priorities:** no stored primary/secondary goal; MVP is a fixed
  strength-with-power configuration.
- **Equipment availability:** not stored in athlete state and not a taxonomy property. The
  generator cannot filter by equipment and must say so.
- **Training experience:** not stored. It does not change volume or load in the MVP.
- **Muscle-group priorities:** volume remains movement-pattern based; priorities are not a new
  input.
- **Exercise preferences:** existing suitability and constraints are the only preference
  mechanism; there is no new preference list.
- **Cardio:** outside the app's prescription scope.
- **LLM:** deferred.

This is a deliberate reduction from the earlier brief. The generator is athlete-specific through
constraints, suitability, history, frequency and duration, not through a general objective
model.

### 4.3 Generator configuration (new config, later)

A new `config/template-generator.v1.yaml` would define the generation rules, not athlete data:

- per session type: required slot roles and allowed patterns;
- exercise pools per slot, with canonical ids or pattern selectors;
- strength/power/accessory slot priorities;
- sets, rep ranges, RIR ranges, rest and essential flags;
- power placement and dose rules;
- volume allocation weights within the existing pattern landmarks;
- duration assumptions and maximum slot counts;
- generation/spec version.

The generator must be driven by this config plus existing state. No hard-coded exercise lists in
Python.

---

## 5. Generator design

### 5.1 Output contract

The generator emits exactly four complete templates:

- `squat`
- `hinge`
- `bench_squat`
- `bench_hinge`

Each template:

- has a non-empty ordered slot list;
- has at least one essential slot;
- has a `primary_exercise` that the scheduler can use for availability;
- conforms to the current template schema and `validate_text`;
- is a valid `SessionTemplate` instance consumable by `build_prescription`.

The generator never emits a partial set. If any template is invalid, generation fails and
returns field-level validation errors.

### 5.2 Slot model

Reuse the existing `Slot` fields:

- `exercise` or `exercise_variants`;
- `sets`, `reps`, `rir`, `rest_s`, `essential`, `load_source`;
- `power` and `quality_stop`;
- existing flare fields where a generated slot needs them.

No new slot type is needed for the MVP. Top set/back-off, clusters and other advanced set
structures remain out of scope because the schema and validator cannot represent them.

### 5.3 Power pillar

Power is required, not optional. Use the existing quality-limited model:

- power slots are first in the session, before strength work;
- 2–3 sets of 3–5 reps, full recovery (around 120 s);
- maximal intent and a quality stop, never an RIR target;
- no load progression and no double progression;
- no Olympic lifts; use taxonomy power exercises such as `box_jump`, `depth_jumps` or
  `jump_squats`;
- power pattern sets stay outside the MEV/MAV/MRV ledger, as today.

Default placement: the squat and hinge templates each carry one power slot. The bench
templates do not carry power in the MVP because the taxonomy has no validated upper-body power
pool and equipment is not modelled. Placement target: two quality exposures per rolling week
when the frequency allows. At one or two sessions per week, the generator gives the available
session a power exposure and records a warning that twice-weekly power is not feasible; it does
not add sessions. The plan should not claim power is equivalent to strength for strength
outcomes; the evidence supports a modest functional benefit.

### 5.4 Strength and accessory allocation

The generator uses the existing movement-pattern vocabulary and volume landmarks:

1. Fix the four template roles.
2. Assign required strength slots per role (main lift, supporting compound, accessories).
3. Allocate weekly sets per pattern within the configured MEV/MAV/MRV guardrails.
4. Use existing session-time estimates to keep each template within
   `max_session_minutes`.
5. Prefer compound slots before isolation; the configured slot roles express the balance.
6. Avoid duplicate exercises in one template and excessive overlap across templates unless the
   existing programme deliberately repeats a main lift for frequency.

The generator must not create a second volume ledger. It can call the existing
`pattern_key`, `pattern_sets`, `template_rows`-style projection and landmark config to check
its output. Runtime volume budget behavior remains unchanged.

### 5.5 Exercise selection

For each slot:

1. Resolve the configured exercise pool/pattern.
2. Remove exercises vetoed by hard constraints, suitability, or missing history where a load
   source requires history.
3. Apply deterministic ordering: configured priority, then canonical id.
4. Use the existing selection/comparability rules where a slot allows variants.
5. If no candidate is valid, fail generation with the slot and reason.

No free-text exercise names. No equipment filtering in the MVP.

### 5.6 Determinism

Same inputs + config + generator version + history snapshot = same four-template YAML.

- No randomness; no wall-clock-dependent choices.
- No LLM.
- Stable ordering for exercise pools and tie-breaks.
- Store an input hash and generator/config version with the generated version.
- Loads are not generated: the generator writes rep/RIR/load-source intent; the runtime engine
  computes kg from current e1RM and readiness.

### 5.7 Validation

Generation must pass:

**Structural**
- `templates.validate_text` and `SessionTemplate` parsing;
- exactly four identities; no extra/missing types;
- at least one essential slot per session;
- valid slot ids, sets, reps, RIR, rest and load source;
- power slots have `quality_stop` and no RIR;
- no unknown or excluded exercise ids.

**Programme-level**
- each template has a valid primary exercise;
- required patterns/roles are present;
- weekly pattern volume is inside configured landmarks;
- session duration estimate fits the athlete target;
- power dose/placement is valid for the available frequency;
- no contradictory essential/accessory or duplicate-slot structure;
- no exercise that fails suitability/constraints.

**Pipeline compatibility**
- each generated template can be loaded as a `SessionTemplate`;
- a dry-run `build_prescription` for each template succeeds or returns only expected
  warnings, not structural errors;
- the scheduler can read `primary_exercise` for all four.

**Historical**
- activation does not change any existing prescription/workout/session row;
- new prescriptions link to the active version;
- old prescriptions keep their existing version link/null.

---

## 6. Generation versus runtime

The boundary must be explicit:

| Concern | Generator | Runtime system |
|---|---|---|
| Four session identities | chooses structure | unchanged |
| Exercise/slot selection | yes, from configured pools | selection may substitute only within template/variant rules |
| Sets/reps/RIR ranges | yes, as template intent | readiness, deload and modifiers may adjust |
| Power placement | yes | quality-stop enforcement and warnings |
| Weekly volume allocation | yes, as a target check | volume budget/MRV cap remains authoritative |
| kg loads | no | e1RM solver/load history |
| Readiness, continuity, deload | no | existing engine |
| Workout execution | no | existing workout system |
| History | no writes | append-only |

A generated template is **not** a prescription. It is the active session recipe that the existing
engine turns into a prescription.

---

## 7. Persistence, versioning and activation

### 7.1 Minimum tables

| table | purpose |
|---|---|
| `template_version` | immutable full YAML snapshot: `version_id`, `source` (`default`/`generated`), `body_yaml`, `schema_version`, `generator_version`, `config_hash`, `input_hash`, `parent_version_id`, `created_at`, `label` |
| `template_state` | singleton current pointer: `active_version_id`, `updated_at`, optional note |

And one nullable column:

- `prescription.template_version_id` — the version that produced the prescription. Existing rows
  remain null; no backfill.

This is the smallest model that supports review, activation, rollback, previous versions and
historical provenance without a programme/block lifecycle. No event-sourcing table is needed.

### 7.2 Default fallback

- The shipped `config/templates/session-types.v1.yaml` remains the canonical default source.
- On first use, the app seeds a `template_version` row with `source='default'` from that file.
- Revert to defaults sets `template_state.active_version_id` to the seeded default version.
- A release that changes the shipped YAML creates a new default version; the previous default
  version remains for rollback and history.

### 7.3 Review and activation

- Generation creates a **candidate** version (not active).
- Review shows all four templates, validation warnings and a diff against the active version.
- Activation updates only `template_state.active_version_id`, transactionally.
- The active version remains unchanged while a new candidate is generated or edited.
- Rollback activates a previous version; it does not delete anything.
- Historical prescriptions are unaffected by activation changes.

### 7.4 YAML editor and structured editor

The YAML editor moves under **Programme → Templates**.

Option B applies:

- the editor loads the selected/active version's YAML;
- saving creates a **new immutable version** (candidate);
- the active version does not change until explicit activation;
- the structured slot editor edits the same version content and uses the same save-as-new-version
  path;
- neither editor mutates an active version in place.

The shipped default YAML file is not edited from the UI. It remains the fallback seed; a generated
or edited version is a database version.

### 7.5 Historical association

- New prescriptions store `template_version_id`.
- Existing prescriptions keep null; they remain readable from their stored items.
- Critique for a new session uses the linked template version's rep ranges.
- Critique for an old session with no link continues as today; do not invent a historical template
  version or retroactively relabel old critiques.
- `build_facts` should accept an explicit template snapshot; the current global loader remains
  only as a fallback for unlinked legacy sessions.

### 7.6 Migration

- Additive migration: new tables and one nullable column.
- No backfill of old prescriptions.
- Seed the default version on startup/migration if the table is empty.
- Feature-flag generation off until the generator and UI are complete.
- No destructive migration; rollback is disabling the feature, not dropping tables.

---

## 8. UI and API

### 8.1 Navigation

- **Programme** becomes template management.
- The current forecast moves to a separate **Forecast** view/tab.
- There is no separate “programme pathway” selector. The active template set is simply what the
  existing training system uses.

### 8.2 Programme view

Sections:

1. **Active templates** — active version, source, created date, validation status.
2. **Generate** — explicit action using existing state; no auto-regeneration.
3. **Review** — four template cards/table, slot details, power placement, volume summary,
   duration estimate, warnings and diff against active.
4. **Versions** — generated/default versions, activate, rollback, archive/visibility.
5. **YAML editor** — active/selected version; saving creates a candidate.
6. **Structured slot editor** — swap exercise, sets, reps, RIR, rest, essential, power fields;
   saving creates a candidate.

The YAML editor and structured editor must not create two different validation paths. Both call
the same template parser/validator and persist through the same version repository.

### 8.3 Forecast view

The current Programme forecast form/result moves unchanged to **Forecast**. It continues to use
the active template set for its projection. No new programme scheduling.

### 8.4 API (proposed)

- `GET /api/template-versions`
- `GET /api/template-versions/{id}`
- `POST /api/template-versions/generate`
- `POST /api/template-versions` (YAML save)
- `POST /api/template-versions/{id}/activate`
- `POST /api/template-versions/{id}/revert`
- `GET /api/template-versions/diff?from=&to=`
- Existing `/api/templates` can be repurposed or kept as the raw YAML surface.

### 8.5 CLI

The generator is UI-first for the MVP. A read-only CLI status/show can follow in a later step.
Do not rename the existing `programme` command; it remains the forecast. Document the temporary
parity gap in [UI-CLI-PARITY.md](UI-CLI-PARITY.md).

### 8.6 Mobile

- Programme view: one section per screen/step, not a wide table.
- Review: collapsible template cards; show warnings first; slot details on demand.
- Editors: grouped fields, sticky save, explicit “save as new version” wording.
- Activation: confirm the version and effective date; no hidden switch.

---

## 9. Testing strategy

### 9.1 Test layers

| layer | coverage |
|---|---|
| unit | version repository, default seed, TemplateSet resolution, generator ordering, power placement, volume check, duration check |
| integration | generated four templates -> `validate_text` -> `SessionTemplate` -> `build_prescription`; scheduler reads primary exercise; volume budget consumes generated templates |
| regression | existing template outputs, golden prescriptions, forecast, rules, workout/history unchanged |
| historical | switching active version does not change old prescriptions/sessions; critique uses linked version |
| migration | old DB upgrades; default version seeded; no existing rows changed |
| UI/API | generate/review/activate/revert/YAML save; candidate not active until activation; validation errors shown |
| determinism | same input/config/history snapshot produces the same structural YAML |

### 9.2 Existing invariants that must remain

- Four canonical session identities and their order.
- Rolling scheduler behavior with default templates.
- `build_prescription` output for existing templates.
- Readiness, RIR, e1RM, volume, spinal and deload semantics.
- Append-only prescriptions/workouts/history.
- Existing forecast `/api/programme`.
- Existing template YAML schema.

### 9.3 Test cases that must exist

1. Generate four templates; each passes `validate_text` and `SessionTemplate` parse.
2. Generated set is deterministic across two runs with same inputs.
3. Generated set fails cleanly for impossible constraints (no valid main lift, no power
   candidate, duration impossible).
4. Power slot is first, has no RIR and has a quality stop; zero power slots fails validation.
5. Weekly pattern volume is inside configured landmarks; an over-MRV candidate is rejected or
   trimmed only by existing config rules, not a second engine.
6. Generated templates produce a valid prescription through the existing engine.
7. Scheduler sees the generated `primary_exercise` and available session types.
8. `volume_budget` uses the generated template, not the shipped default.
9. Activating a new version leaves old prescriptions and history unchanged.
10. Critique for a new prescription reads its linked template version.
11. YAML save creates a candidate and does not activate it.
12. Revert to default works and is explicit.
13. Existing template/golden/forecast tests are unchanged.

---

## 10. Implementation steps

Work happens on `feature/template-generator` off `development`. Each step is a merge gate, not
a calendar date.

### Step 0 — Branch, contracts and decision records

**Objective:** lock the smaller architecture before code.

**Scope:** replace the old plan; record the template-generator decision, versioning/activation
rules, YAML-editor semantics, power dose and the explicit no-new-inputs limitation.

**Changes:** documentation only.

**Tests:** docs consistency; no runtime tests.

**Acceptance:** plan approved; no code starts before approval.

**Merge gate:** documentation can merge to `development` first (this plan is the design record).

### Step 1 — Data and domain foundation

**Objective:** persist template versions and resolve a default version without changing existing
behaviour.

**Scope:** `template_version`, `template_state`, default seed, template-version repository,
nullable `prescription.template_version_id`, feature flag.

**Architecture:** new template-version domain module; no generator yet; no UI.

**Data:** additive migration; seed default from shipped YAML; no backfill.

**API/UI/CLI:** none visible.

**Tests:** migration, seed, repository, rollback pointer, old DB upgrade, no existing row changes.

**Acceptance:** app behaves exactly as today with the flag off; default version resolves to the
shipped YAML; old prescriptions remain null and readable.

**Merge gate:** merge behind a disabled feature flag after full regression suite.

### Step 2 — Active TemplateSet plumbing

**Objective:** make future-session code read the active template set while historical/default
paths remain stable.

**Scope:** `TemplateSet` resolver; thread active set through `build_prescription`, scheduler,
volume budget, selection, fatigue selection, demand scope and forecast. Add explicit template
snapshot support to critique.

**Architecture:** do not put active-DB reads inside `SessionTemplate.load()`. Pass explicit
context. Keep default fallback for omitted arguments.

**Data:** no new schema beyond Step 1.

**API/UI/CLI:** no visible change yet.

**Tests:** default-path regression; generated-set injection tests with synthetic templates;
critique link test; scheduler/volume/selection parity.

**Acceptance:** with no active generated version, every existing test and output is unchanged.
With a synthetic active set, all future-session components use it and no default file leaks in.

**Merge gate:** merge after full suite and a default-path golden check.

**Risk:** this is the highest-risk step. A missed `SessionTemplate.load` silently mixes
defaults and generated templates.

### Step 3 — Deterministic generator core

**Objective:** generate a complete, valid four-template set from existing state and the generator
spec.

**Scope:** generator config, exercise pools, pattern/slot allocation, power placement, volume
check, duration check, four-template validation, deterministic ordering, generation metadata.

**Architecture:** pure generator module; calls existing validator and (dry-run)
`build_prescription`; no runtime scheduler/volume changes.

**Data:** candidate `template_version` rows; no activation yet.

**API/UI/CLI:** internal generation API/service; no activation UI.

**Tests:** all §9.3 cases 1–6, 10; impossible inputs; determinism; power; volume; duration.

**Acceptance:** a generated set can be reviewed as data and consumed by the existing engine; it
cannot be activated yet.

**Merge gate:** merge behind the flag after generation tests and default-path regression.

### Step 4 — Programme UI, editors and activation

**Objective:** make versions usable.

**Scope:** Programme view tabs/sections; active version; generation/review; version list;
activate/revert; YAML editor under Programme; structured slot editor; Forecast separate view.

**Architecture:** one persistence/validation path for both editors; candidate not active until
explicit activation.

**Data:** no new tables; use Step 1.

**API/UI/CLI:** proposed endpoints; UI mobile checklist; read-only CLI status/show optional.

**Tests:** §9.3 cases 7–13; API 400/409; YAML save candidate; activation; rollback; mobile
contract; docs links.

**Acceptance:** athlete can generate, review, edit, activate, revert and still use the existing
Forecast. No separate programme pathway selector.

**Merge gate:** merge after UI/API, default fallback and historical tests pass.

### Step 5 — Historical provenance and critique hardening

**Objective:** ensure template changes do not rewrite or reinterpret history.

**Scope:** set `prescription.template_version_id` on new prescriptions; critique uses linked
version; legacy null path documented; no backfill.

**Architecture:** explicit snapshot, no global active read in critique.

**Data:** nullable column already added in Step 1; no new table.

**Tests:** old vs new prescription/critique; activation/rollback; switch default/generated.

**Acceptance:** old sessions remain interpretable; new sessions cite the exact version.

**Merge gate:** merge after historical-integrity tests.

### Step 6 — Hardening and rollout

**Objective:** finish the feature without changing the fallback.

**Scope:** power/volume edge cases, duration warnings, error UX, docs, feature flag default off,
manual verification, performance check on the real database.

**Architecture:** no new abstractions.

**Data:** none.

**Tests:** full suite, generator golden, migration on a copy of the real DB, UI smoke test.

**Acceptance:** generated templates work end-to-end; default templates still work; no regression;
feature can be disabled without data loss.

**Merge gate:** final merge to `development` after review; no direct release from the feature
branch.

---

## 11. Branch and delivery strategy

- Cut `feature/template-generator` from `development`.
- Keep commits small and phase-aligned.
- Rebase/merge `development` into the feature branch regularly; do not let it drift.
- Merge back at gates:
  1. Step 1 behind a disabled flag (foundation only).
  2. Step 2 after default-path regression (still no user-visible generator).
  3. Step 3 behind the flag (generator, no activation).
  4. Step 4 when UI/activation is usable.
  5. Step 5 after historical tests.
  6. Step 6 after full acceptance.
- Never release/tag from the feature branch. Releases remain from `main`.
- If a phase needs to be abandoned, the additive schema and disabled flag keep the default
  pathway working.

---

## 12. Risks and conflicts

1. **Template resolution leakage.** Any missed `SessionTemplate.load` call site mixes defaults
   and generated sets. Step 2 must be exhaustive and tested.
2. **Volume budget signatures.** Several functions reload templates by session type. Extending
   them risks changing default behavior; regression tests are mandatory.
3. **Historical critique drift.** The current critique reads the active template by session type.
   New prescriptions need a version link; legacy rows must not be retroactively relabeled.
4. **Generator scope.** Without objectives/equipment/experience, the generator is a constrained
   strength/power template builder, not a general optimiser. UI copy must not overclaim.
5. **Power evidence.** Power is a required quality exposure, not a proven equal pillar for
   strength. The plan uses a modest two-exposure target and preserves quality-stop semantics.
6. **Volume duplication.** The generator must check against the existing landmarks, not create a
   second allocation engine. If it cannot reuse the ledger, stop and redesign.
7. **YAML editor bypass.** Option B must save a candidate, never mutate active. If the editor can
   activate directly, the approval boundary is lost.
8. **Default seed drift.** A release changing the shipped YAML needs a new default version, not a
   silent overwrite of the active generated version.
9. **Frequency edge cases.** Two power exposures per week are impossible at one or two sessions;
   the generator must warn, not add sessions.
10. **Migration safety.** Additive only; seed default version; no backfill; feature flag off.

---

## 13. Resolved design decisions

- Replace the old Programme Builder plan with this template-generator plan.
- Four canonical session types; no new identities.
- Explicit `TemplateSet` resolver; do not make `SessionTemplate.load` read active state.
- DB-backed immutable template versions plus a current active pointer.
- Nullable `prescription.template_version_id`.
- Generated sets are candidates until explicit activation.
- YAML editor moves under Programme; saving creates a new candidate version; structured slot
  editor shares the same save path.
- Forecast becomes a separate view; Programme becomes template management.
- Power: required, quality-limited, first in session, two exposures/week where frequency allows.
- No new athlete inputs; no equipment/experience/objective model in the MVP.
- No new scheduler, prescription engine, volume engine, programme lifecycle or LLM.

## 14. Open design decisions for Step 0

These do not block the plan but must be settled before Step 3:

1. **Generator spec shape:** per-slot fixed ids vs pattern selectors vs mixed. Recommended:
   pattern/role selectors with a canonical fallback, so the generator can adapt to suitability
   without hard-coding exercises.
2. **Default-version seeding:** seed on first startup vs a migration-time insert. Recommended:
   first startup after migration, because the YAML file is the source and the migration should
   not read runtime config.
3. **Power at low frequency:** one exposure with a warning at 1–2 sessions/week vs a hard
   refusal. Recommended: generate with one exposure and an explicit warning; do not add sessions.
4. **Legacy critique:** leave unlinked sessions on the current default loader vs attempt a
   historical default snapshot. Recommended: leave them, and document the limitation.

---

## 15. Related

- **Methodology:** [METHODOLOGY.md](METHODOLOGY.md)
- **Templates:** [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md)
- **Workout generation:** [WORKOUT-GENERATION.md](WORKOUT-GENERATION.md)
- **Volume:** [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md)
- **LLM workstream:** [LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
