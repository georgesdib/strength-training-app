# Dynamic Template Resolver — implementation plan

**Status:** planning only. No code, schema, configuration, API, CLI, UI or test change is part
of this document.

**Scope:** make the four canonical session templates **dynamic at prescription time** while
keeping the existing scheduler, prescription engine, volume engine and workout system. A fixed
four-template YAML version remains the structural blueprint and the fallback.

This document replaces the earlier “parallel Programme Builder” and one-off template-generator
plans. The stable artifact is the template **blueprint/policy**, not a permanently fixed
exercise list.

**Related:** [METHODOLOGY.md](METHODOLOGY.md), [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md),
[WORKOUT-GENERATION.md](WORKOUT-GENERATION.md), [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md),
[LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md), [ROADMAP.md](../ROADMAP.md).

---

## 1. Executive summary

1. The four canonical identities stay: `squat`, `hinge`, `bench_squat`, `bench_hinge`.
2. The fixed four-template YAML becomes a **blueprint and fallback**:
   - slot roles and order;
   - power placement and quality stop;
   - essential slots;
   - base sets/reps/RIR/rest;
   - exercise defaults and allowed categories.
3. At each prescription preview, a deterministic resolver fills the blueprint slots for that
   session using the athlete's current constraints, suitability, history, pattern coverage and
   volume state.
4. The resolved `SessionTemplate` is passed to the existing `build_prescription`; readiness,
   e1RM, RIR, undulation, volume budget, deload, spinal limits and validation still run there.
5. The resolved template and the blueprint/policy versions are frozen with the prescription.
6. There is no separate programme scheduler, prescription engine, volume engine, programme
   lifecycle or pathway selector.
7. Power is a hard structural constant; weak-point targeting is a later feature. The resolver
   uses movement-pattern coverage and under-MEV patterns now.
8. Generation is deterministic. No LLM, no randomness.

---

## 2. Verified current architecture

| Component | Current behaviour | Consequence |
|---|---|---|
| Templates | `SessionTemplate`/`Slot`; `validate_text` requires exactly the four types, essential slots, valid load sources and power slots with quality stop/no RIR. | The fixed YAML is a valid blueprint and fallback; the resolver must emit the same shape. |
| Loading | `SessionTemplate.load(session_type)` reads the shipped YAML. | Dynamic resolution needs an explicit resolver; do not put active database reads inside the global loader. |
| Prescription | `build_prescription(..., template=...)` accepts an optional template. Only the forecast passes one today. | This is the insertion point. The resolver produces the template passed here. |
| Scheduler | `schedule.next_session_type` loads templates to read `primary_exercise`. | It uses the fixed blueprint/fallback; dynamic exercise choice must keep the session's primary pattern valid. |
| Volume | `volume_budget` loads templates by `session_type` in template rows, drop and apply paths. | It must consume the resolved template, not reload the shipped file. No second volume engine. |
| Selection | `selection.py`, `fatigue_selection.py`, `demand_scope.py` load templates. | They must use the resolved/blueprint template for the session. |
| Critique | `critique/facts.py` loads the template by `session_type` for rep ranges. | It must use the frozen resolved template or linked version, not the current active policy. |
| History | Prescriptions, items, workouts and sessions are append-only. | Add provenance columns; no rewrite or backfill. |
| UI | Forecast is on Programme; the YAML editor is on Exercises and writes the single file. | Programme becomes template/policy management; Forecast becomes its own view; the YAML editor moves under Programme and writes versions, not the shipped file. |

---

## 3. Architecture

### 3.1 Resolution path

```text
fixed four-template YAML version  (blueprint + fallback)
resolver policy version           (categories, pools, coverage, volume rules)
                    |
athlete readiness -> scheduler -> session type
                    |
             deterministic resolver
                    |
          resolved SessionTemplate
                    |
          build_prescription (unchanged)
                    |
       prescription + frozen resolved template
                    |
              workout / history
```

When no resolver policy is active, or dynamic mode is explicitly off, the fixed templates are
used exactly as today.

### 3.2 Stable versus dynamic

**Stable in the blueprint**

- Four session identities and their slot roles/order.
- Power slot placement and quality stop.
- Essential slots and main/secondary structure.
- Base sets, reps, RIR, rest and load source.
- Time cap and session-duration assumptions.
- The fixed YAML fallback.

**Dynamic per session**

- Which exercise fills each slot, from its category/pool.
- Which accessory variants fill the accessory slots.
- Which patterns are covered when the athlete's constraints/suitability narrow the options.
- The resolved template's exercise list, frozen for that prescription.

**Not decided by the resolver**

- kg loads.
- RIR readiness adjustment.
- Set reduction/top-up from readiness or volume budget.
- Deload application.
- Spinal-cap trimming.
- Warm-up generation.

Sets/reps/RIR start from the blueprint and vary only through the existing runtime rules. The
resolver does not create a second set/rep/RIR policy.

### 3.3 What is reused, extended and new

**Reused unchanged**

- `Slot`, `SessionTemplate`, `validate_text`, four canonical identities.
- Rolling scheduler.
- `build_prescription` readiness/e1RM/RIR/volume/deload/spinal/validation.
- Exercise taxonomy, suitability, constraints and selection comparability.
- Workout execution, history and append-only persistence.
- Forecast logic.

**Extended**

- `build_prescription` accepts the resolved template (already supports `template`; caller wiring
  is the change).
- Scheduler, volume budget, selection and critique accept the resolved/blueprint template or a
  frozen snapshot.
- Prescription gains provenance for the fixed template version, resolver policy version and
  resolved template snapshot.

**New**

- Deterministic resolver module.
- Resolver policy config/version.
- Fixed template version/state persistence.
- Resolver-specific validation (pattern coverage, volume, duration, power, suitability).
- Programme-page template/policy management and per-session preview.
- Tests.

**Not new**

- No second scheduler, prescription engine, volume engine or programme lifecycle.
- No automatic regeneration.
- No LLM generation.
- No cardio programming.
- No equipment/experience/objective model.

### 3.4 Template resolution call sites

| call site | path | change |
|---|---|---|
| `prescribe/engine.py` | future | use the resolved template passed by the caller |
| `prescribe/schedule.py` | future | read `primary_exercise` from blueprint/fallback |
| `prescribe/volume_budget.py` | future | accept resolved template; stop reloading by type |
| `prescribe/selection.py` | future | resolve candidates within the resolved template slots |
| `prescribe/fatigue_selection.py` | future | same |
| `prescribe/demand_scope.py` | read-only | use explicit template/version |
| `critique/facts.py` | historical | use frozen resolved template or linked version |
| `features/programme.py` | forecast | use active blueprint/resolver path or fixed fallback |
| `prescribe/summary.py` | docs | render from selected version |
| `agents/proposal.py` | future | defer; use active path when LLM work resumes |

---

## 4. Resolver inputs and policy

### 4.1 Existing athlete inputs only

- `sessions_per_week_target`;
- `max_session_minutes`;
- `athlete_constraint`;
- `exercise_suitability`;
- recent training history, e1RM and pattern exposure;
- taxonomy patterns, primary muscles, loadability and power classification;
- existing volume landmarks/targets and time estimates.

No new objective, equipment, experience or muscle-priority state is added.

### 4.2 Resolver policy

The policy is a versioned configuration document (`config/template-resolver.v1.yaml` in a later
step) that defines:

- per session type: the fixed slot roles/order inherited from the blueprint;
- exercise categories/pools per slot;
- allowed variants and substitution rules;
- coverage rules: required patterns, under-MEV patterns, redundancy avoidance;
- accessory allocation limits;
- power slot requirements;
- duration limits;
- deterministic tie-break order.

The policy contains no athlete data.

### 4.3 Fixed YAML fallback

The fixed four-template YAML remains the structural blueprint and fallback. It is versioned and
activatable. When dynamic resolution is off or no policy is active, it runs exactly as today.

The YAML editor under Programme edits the fixed template version. Saving creates a new immutable
version; activation remains explicit. The structured slot editor edits the same fixed version
content.

---

## 5. Resolver algorithm

### 5.1 Session flow

1. The scheduler selects one of the four session types.
2. Load the active fixed blueprint/fallback for that type.
3. Load the active resolver policy, if dynamic mode is enabled.
4. For each blueprint slot, resolve the exercise from its category/pool:
   - remove hard-constraint and suitability vetoes;
   - remove exercises already used in this session where duplicate/overlap is not allowed;
   - prefer exercises that cover required/under-represented patterns;
   - use deterministic policy order and canonical id for ties;
   - apply the existing selection/comparability rules for variant slots.
5. Build a complete `SessionTemplate` with the same slot fields as the blueprint.
6. Validate the resolved template and the whole session.
7. Pass it to `build_prescription` with the normal fingerprint/rollback history.
8. Freeze the resolved template and the active versions with the prescription.

If any required slot cannot be resolved, the preview fails with a field-level error. Fallback to
the fixed template occurs only when dynamic mode is off or no policy is active.

### 5.2 Main and secondary lifts

- The session type defines the primary pattern category.
- The main lift must be chosen from that category and must preserve a valid
  `primary_exercise` for the scheduler.
- The secondary lift comes from the configured support category for that session.
- If no valid main/secondary lift exists, the session is unavailable; do not silently substitute
  a different session type.

### 5.3 Accessories and coverage

Accessories are chosen to fill the remaining blueprint slots from their configured categories,
with this order of preference:

1. exercise is suitable and not contraindicated;
2. it covers a required pattern not already covered in the session;
3. it covers a pattern below its configured MEV/recent target, when the policy says so;
4. it avoids duplicating an already-trained pattern or muscle emphasis;
5. configured priority order and canonical id.

“Weak-point targeting” is not implemented. The app has no validated weakness metric; automatic
weakness/injury-targeted selection remains a later gated feature. The resolver may call this
**coverage-based accessory selection**, not weakness correction.

Muscle-group balance uses the taxonomy's primary muscles as a diversity heuristic. Volume
minima/maxima remain movement-pattern based; there is no per-muscle volume ledger.

### 5.4 Power

Power is a hard structural constant:

- one slot on the squat blueprint and one on the hinge blueprint;
- first in the session, before strength work;
- 2–3 sets of 3–5 reps, full recovery (about 120 s);
- maximal intent and a quality stop, no RIR;
- no load progression and no double progression;
- no Olympic lifts;
- power pattern sets stay outside MEV/MAV/MRV.

If frequency is one or two sessions per week, the resolver gives the available session a power
slot and records a warning that twice-weekly exposure is not feasible; it never adds sessions.
Bench templates have no power slot in the MVP because the taxonomy has no validated upper-body
power pool and equipment is not modelled.

### 5.5 Volume and duration

- The resolver chooses exercises, not a new weekly volume target.
- Weekly pattern volume is checked against the existing configurable landmarks.
- The existing volume budget remains the runtime authority for trims/top-ups.
- The existing session-time estimate checks that the resolved template fits
  `max_session_minutes`.
- If the blueprint + policy cannot fit, the preview fails or warns according to the validator;
  it never silently exceeds the limit.

### 5.6 Determinism

Same blueprint version + policy version + athlete state/history snapshot + config + date +
session type = same resolved template.

- No randomness; stable ordering.
- No LLM.
- Store an input hash, policy version, template version and resolved template snapshot.
- kg is not resolved here; the runtime engine computes it from current e1RM/readiness.

---

## 6. Resolution versus runtime

| Concern | Resolver | Existing runtime |
|---|---|---|
| Session type | no (scheduler) | scheduler |
| Exercise choice | yes | variant selection only within resolved template |
| Sets/reps/RIR target | blueprint | readiness, undulation, volume, deload |
| kg load | no | e1RM solver/load history |
| Power placement | blueprint/policy | quality-stop enforcement |
| Weekly volume | coverage check | volume budget/MRV cap |
| Duration | fit check | estimate and warnings |
| History | no writes | append-only prescription/workout |

---

## 7. Persistence and provenance

### 7.1 Minimum tables/columns

| object | purpose |
|---|---|
| `template_version` | immutable fixed four-template YAML version: id, source, body, schema/config hashes, parent, created_at |
| `resolver_policy_version` | immutable resolver policy version: id, body, schema version, created_at, parent |
| `template_state` | singleton: `active_template_version_id`, `active_policy_version_id` (nullable), `dynamic_enabled`, `updated_at` |
| `prescription.template_version_id` | fixed blueprint/fallback version used |
| `prescription.resolver_policy_version_id` | policy used, nullable for fixed path |
| `prescription.resolved_template_json` | exact resolved template; null for fixed path |

No programme/block/session lifecycle tables. No event sourcing.

### 7.2 Default and activation

- Seed a default fixed template version from the shipped YAML.
- If `active_policy_version_id` is null or `dynamic_enabled = 0`, the fixed templates run as
  today.
- Activating a policy enables dynamic resolution only when the flag is on.
- Generating/resolving never changes the active versions.
- Rollback activates a previous version or disables dynamic mode.
- A new candidate policy never affects the current session until activated.

### 7.3 Editors

The YAML editor moves under Programme and edits the fixed template version.

Option B:

- saving creates a new immutable template version (candidate);
- the active version does not change until explicit activation;
- the structured slot editor edits the same fixed version content and uses the same save path;
- the resolver policy has its own YAML/structured editing surface later; it is versioned the same
  way.

No editor mutates an active version in place.

### 7.4 Historical integrity

- New prescriptions store the fixed version, policy version and resolved template.
- Old prescriptions keep nulls; their stored items remain readable.
- Critique for new sessions uses the frozen resolved template's rep ranges.
- Critique for old unlinked sessions continues on the current fallback; do not invent history.
- Switching policy/version never rewrites old prescriptions or workouts.

---

## 8. UI and API

### 8.1 Navigation

- **Programme** becomes template and resolver-policy management.
- The existing forecast moves to a separate **Forecast** view/tab.
- No separate pathway selector.

### 8.2 Programme view

- Active fixed template version and active resolver policy.
- Dynamic mode on/off.
- Fixed template versions: review, YAML editor, structured slot editor, activate, revert.
- Resolver policy versions: review, edit, activate, revert.
- Per-session preview: choose the next session type (or let the scheduler choose), see the
  resolved exercises/slots, warnings and the fixed fallback comparison.
- No fixed generated exercise list is stored as the active configuration.

### 8.3 Workflow

The existing preview becomes the per-session review:

1. readiness;
2. scheduler/session type;
3. resolver builds the resolved template;
4. prescription preview shows resolved exercises and normal warnings;
5. start workout freezes the resolved template and prescription.

If the preview is rebuilt after a readiness change, the resolver rebuilds. The started workout
keeps the frozen snapshot.

### 8.4 API (proposed)

- `GET /api/template-versions`
- `POST /api/template-versions` (YAML save)
- `POST /api/template-versions/{id}/activate`
- `GET /api/resolver-policies`
- `POST /api/resolver-policies` (policy save)
- `POST /api/resolver-policies/{id}/activate`
- `POST /api/template-resolve` (preview for a date/session type)
- `GET /api/template-state`
- Existing `/api/programme` remains the forecast.

### 8.5 CLI

UI-first for MVP; read-only status/show later. Document the temporary gap in
[UI-CLI-PARITY.md](UI-CLI-PARITY.md). Do not rename the existing `programme` command.

### 8.6 Mobile

One section per step; resolved session cards with expandable slot details; warnings first;
explicit activation; sticky save. No wide table.

---

## 9. Validation and testing

### 9.1 Resolver validation

- Fixed blueprint parses through `validate_text`.
- Resolved template has all required slots and at least one essential slot.
- Main/secondary lifts match the session pattern category.
- Exercise ids exist, are suitable and not vetoed.
- No duplicate/overlapping slot content beyond policy allowances.
- Power slot is first, no RIR, has quality stop.
- Weekly pattern volume is inside configured landmarks.
- Duration estimate fits the target.
- No unresolved slot; fail with a field-level error.
- Resolved template is consumable by `build_prescription`.

### 9.2 Test layers

| layer | coverage |
|---|---|
| unit | category selection, deterministic ordering, coverage preference, power, volume check, duration check, failure cases |
| integration | resolver -> `SessionTemplate` -> `build_prescription` -> scheduler/volume/selection |
| regression | existing templates, golden prescriptions, forecast, rules, workout/history unchanged |
| historical | prescription links and resolved snapshot; activation/rollback does not change old rows |
| migration | additive tables/columns; default version seed; no backfill |
| UI/API | preview, activation, YAML save candidate, policy activation, fallback |
| determinism | same inputs produce same resolved template |

### 9.3 Existing invariants

- Four canonical identities and default scheduler behavior.
- `build_prescription` output for fixed templates.
- Readiness/RIR/e1RM/volume/spinal/deload semantics.
- Append-only history.
- Forecast `/api/programme`.
- Template schema.

---

## 10. Implementation steps

Work on `feature/template-resolver` off `development`; merge at gates.

### Step 0 — Branch, contracts and decision records

**Objective:** lock the dynamic-resolver model, blueprint/policy/fallback semantics and
provenance.

**Scope:** documentation and decisions only. Confirm:
- fixed YAML = blueprint + fallback;
- resolver changes exercises, not sets/reps/RIR rules;
- failure is a preview error, fallback only when dynamic off;
- fixed template and resolver policy are separately versioned and activated.

**Tests:** docs consistency.

**Acceptance:** no code starts before approval.

**Merge gate:** documentation can merge to development first.

### Step 1 — Fixed template versions and resolver policy persistence

**Objective:** store fixed template versions, policy versions and active state without changing
behaviour.

**Scope:** `template_version`, `resolver_policy_version`, `template_state`; seed default fixed
version; add nullable prescription provenance columns; feature flag.

**Data:** additive migration; no backfill; default seed.

**UI/API/CLI:** none visible.

**Tests:** migration, seed, repositories, activation/rollback, old DB upgrade, old prescriptions
unchanged.

**Acceptance:** app behaves exactly as today; fixed fallback resolves from seeded version.

**Merge gate:** merge behind disabled flag after full regression.

### Step 2 — Deterministic resolver core

**Objective:** build a valid resolved `SessionTemplate` for a session type from blueprint +
policy + current state.

**Scope:** categories/pools, suitability/constraints, coverage preference, power, volume/duration
checks, deterministic ordering, failure cases.

**Data:** no new tables.

**UI/API/CLI:** internal resolve function/API; no visual change.

**Tests:** all §9.1 cases; synthetic fixed templates/policies; determinism; impossible cases.

**Acceptance:** resolver returns valid templates and clear errors; not wired into the main path
yet.

**Merge gate:** merge behind flag after resolver unit/integration tests.

### Step 3 — Pipeline integration and provenance

**Objective:** use the resolved template in the real prescription path and freeze provenance.

**Scope:** wire CLI/web/forecast; extend volume/selection/scheduler/critique to accept the
resolved/blueprint template; store version ids and resolved template on prescriptions.

**Architecture:** explicit template passing; no global active read inside
`SessionTemplate.load`.

**Tests:** full pipeline; default fallback; volume/selection parity; history/critique; scheduler.

**Acceptance:** with dynamic off, outputs unchanged; with dynamic on, prescriptions use resolved
templates; historical rows unchanged.

**Merge gate:** merge after default-path golden regression and resolver integration.

**Risk:** highest-risk step; missed template load site is a silent mix.

### Step 4 — Programme UI, editors and preview

**Objective:** make fixed versions, policies and per-session resolution usable.

**Scope:** Programme view; fixed version list; YAML/structured editors; policy list/editor;
dynamic toggle; per-session preview; activate/revert; Forecast separate view.

**Tests:** API/UI; save-as-candidate; activation; preview; failure UX; mobile; docs links.

**Acceptance:** user can inspect/edit fixed fallback, activate a policy, preview a resolved
session, start it, and still use the fixed path.

**Merge gate:** merge after UI/API and fallback tests.

### Step 5 — Historical hardening

**Objective:** guarantee old sessions and critiques remain stable.

**Scope:** freeze resolved template with prescription; critique uses it; legacy null path
documented; no backfill.

**Tests:** old/new prescriptions; policy switch; fallback; critique rep ranges.

**Acceptance:** historical rows untouched; new sessions explain themselves from their snapshot.

**Merge gate:** merge after historical tests.

### Step 6 — Hardening and rollout

**Objective:** finish without changing the default.

**Scope:** power/volume edge cases, duration warnings, performance, docs, feature flag default
off, real-DB copy migration, smoke test.

**Tests:** full suite, golden resolver fixtures, migration copy, UI smoke.

**Acceptance:** dynamic resolver works end-to-end; fixed fallback works; feature can be disabled
without data loss.

**Merge gate:** final merge to development after review; no release from feature branch.

---

## 11. Branch strategy

- Cut `feature/template-resolver` from `development`.
- Rebase/merge development regularly.
- Merge at the gates above, not as one large drop.
- Never release/tag from the feature branch.
- Additive schema and disabled flag preserve the fallback during rollout.

---

## 12. Risks and open items

1. **Resolver leakage:** missing a template load site mixes fixed and dynamic paths. Step 3 must
   be exhaustive.
2. **Sets/reps/RIR boundary:** the resolver must not become a second periodisation engine. It
   chooses exercises; runtime rules vary sets/reps/RIR.
3. **Weak points:** not implemented. Coverage/under-MEV selection only.
4. **Volume:** no per-muscle ledger; movement patterns only. Resolver checks existing landmarks.
5. **Power at low frequency:** warning, not extra sessions.
6. **Historical critique:** frozen resolved template is mandatory for new sessions.
7. **YAML/version semantics:** save-as-candidate only; activation explicit.
8. **Fallback ambiguity:** fixed fallback only when dynamic off/unavailable; unresolved slot is
   an error.
9. **Policy editing complexity:** policy YAML/structured editor may be large; keep MVP review and
   activation minimal if needed.
10. **No new inputs:** the resolver cannot optimise equipment/experience/objectives; state the
    limitation.

## 13. Resolved decisions

- Dynamic per-session exercise resolution; fixed YAML is blueprint and fallback.
- Resolver changes exercise selection; sets/reps/RIR remain blueprint + existing runtime rules.
- Fixed template version and resolver policy version are separately versioned/activated.
- Resolved template is frozen with the prescription.
- Power is hard-coded structurally.
- Coverage-based accessories now; weakness targeting later.
- Movement-pattern volume only.
- No second scheduler/engine/volume/lifecycle/LLM.

## 14. Related

- **Methodology:** [METHODOLOGY.md](METHODOLOGY.md)
- **Templates:** [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md)
- **Workout generation:** [WORKOUT-GENERATION.md](WORKOUT-GENERATION.md)
- **Volume:** [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md)
- **LLM workstream:** [LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
