# Dynamic Template Resolver — implementation plan

**Status:** **Steps 0, 1 and 2 are complete 2026-11-01. Step 3 (top set/back-off) is not
started.** Step 2 added the deterministic generator core only; it is not wired into any
prescription path, the top set and joint evaluator are absent, and the resolver flag remains
off.

**Scope:** make the four canonical session templates a **deterministic session generator** at
generation time while keeping the existing scheduler, prescription engine, volume engine and
workout system. The fixed four-template YAML remains the structural blueprint and the fallback.
The generator selects exercises every session; it does not pin a block-level exercise list.

This document replaces the earlier “parallel Programme Builder” and one-off template-generator
plans. The stable artifacts are the template **blueprint** and the versioned **resolver policy**,
not a permanently fixed exercise list.

### 1A. Confirmed design (2026-11-01)

These decisions supersede any older wording in this document that still describes block-level
pinning, a two-stage volume pass, or a hinge top-set RIR cap.

- **Session generator, no block pin.** Every generation resolves the exercise for every slot.
  A generated session is frozen when the workout starts; a later generation can differ. There
  is no multi-session exercise pin.
- **Session identity stays.** The scheduler still chooses squat, hinge, bench_squat or
  bench_hinge. The main lift rotates only within that pattern family; the secondary/support
  lift rotates within its support pattern; accessories are pattern-flexible.
- **Reusable signals.** Exercise choice uses readiness (per-lift and global), recent
  stress/fatigue, spinal load, injury signal, suitability, movement-pattern coverage, history
  and rotation. Missing readiness is neutral, not "low". No LLM and no randomness.
- **Exercise Rotation 0-1.** 0 keeps the slot's last exercise unless a hard constraint,
  required pattern or volume objective cannot be met; 1 changes every session; intermediate
  values use a deterministic dwell (dwell = 1 + round((1 - rotation) * (D - 1)), default
  D = 8). Recommended defaults: 0.2 main/secondary, 0.5 accessories.
- **Eligibility.** With require_can_do on (the shipped default), auto-select only with explicit
  can_do = 1; will_do = 0 or feels_bad = 1 is suggestion-only. Unrated exercises are
  suggestion-only under unrated_mode = confirm and hidden under exclude. A default or fallback
  never bypasses this. If no automatically eligible candidate exists, generation is a field-level
  error that names the slot and the available suggestions; it does not silently keep the
  blueprint default.
- **Joint optimisation.** The resolver is a bilevel search: the outer loop chooses exercises;
  the inner evaluator runs the existing readiness set cuts, deload, spinal trim, volume budget,
  time estimate and validation in read-only mode; the score is the post-budget outcome. The
  final build runs the same pipeline once. The volume budget is not applied twice and is not
  reimplemented.
- **Top set / back-off is an opt-in main-lift structure.** One top set plus back-off sets,
  preserving the blueprint's total working sets; back-off load 85% of the top-set load
  (configurable); top set protected from volume trim, back-off sets trimmable; first-class
  set-group model; no AMRAP and no RIR 0. Default mode is ask (visible in generation, not
  applied unless chosen).
- **Top-set RIR source.** Use the DUP main scheme actually applied to the item:
  maximal -> RIR 1, strength -> RIR 2; DUP off/no anchor -> RIR 2. A competition-date
  override sets the base to RIR 1 inside the configured peak window (default 4 weeks). Then
  apply readiness/deload **once**; if the resolved RIR would exceed 2, use straight sets.
  No top set on a deload week; no top set inside the configured taper (recommended default
  7 days) before competition.
- **Hinge is allowed on a maximal week.** Remove the hinge exclusion from the DUP maximal
  scheme for the prescribed hinge lifts (trap bar, sumo and conventional deadlift) and remove
  the separate top-set RIR-2 cap for hinge. This is a programme change with a spinal/fatigue
  cost and needs its own decision, golden updates and a warning. Keep the accessory/risk hinge
  exclusions (good morning, rack pull, Jefferson curl) unless separately approved.
- **Settings -> Resolver.** All resolver configuration lives under a Settings section named
  **Resolver**: enable, rotation, eligibility, coverage, readiness/fatigue/spinal/injury
  weights or modes, top-set mode/defaults, DUP/competition mapping, pools/required patterns,
  preview/regenerate, policy digest and validation. High-level controls in the normal UI with
  an advanced validated YAML policy editor; scalar keys use the append-only settings profile.
- **Blueprint source of truth.** The shipped config/templates/session-types.v1.yaml remains
  the blueprint; config/template-resolver.v1.yaml is the policy file; a settings-profile flag
  enables dynamic generation. No database template versions in the MVP. Prescriptions store
  blueprint/policy digests, the input hash, the generated-session snapshot and the top-set
  structure.
- **Forecast.** Use option (c): the forecast shows the blueprint/expected pattern and volume,
  labelled "exercises generated at session start"; the actual session is generated when the
  workout starts. It never claims a future exercise list it cannot know.
- **Historical integrity.** The generated session is frozen at workout start; old prescriptions
  keep their stored items and null snapshots; no backfill and no rewrite.

**Related:** [METHODOLOGY.md](METHODOLOGY.md), [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md),
[WORKOUT-GENERATION.md](WORKOUT-GENERATION.md), [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md),
[LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md), [ROADMAP.md](../ROADMAP.md).

---

## 1. Executive summary

1. The four canonical identities stay: squat, hinge, bench_squat, bench_hinge.
2. The fixed four-template YAML becomes a **blueprint and fallback**:
   - slot roles and order;
   - power placement and quality stop;
   - essential slots;
   - base sets/reps/RIR/rest;
   - exercise defaults and allowed categories.
3. Every generation runs a deterministic resolver over the blueprint slots using the athlete's
   constraints, suitability, readiness, fatigue, spinal load, injury signal, history, pattern
   coverage, volume state and rotation. There is no block-level exercise pin.
4. The generated SessionTemplate is passed to the existing build_prescription. Readiness, e1RM,
   RIR, DUP, volume budget, deload, spinal limits and validation still run there.
5. The resolver is a **joint bilevel search**: candidate exercises are scored after the existing
   readiness/deload/spinal/volume pipeline in read-only mode; the final build runs that pipeline
   once. The volume budget is not reimplemented.
6. The generated session, blueprint/policy digests, input hash and top-set structure are frozen
   when the workout starts. There is no separate programme scheduler, prescription engine,
   volume engine, programme lifecycle or pathway selector.
7. Power is a hard structural constant; top set/back-off is an optional main-lift structure.
   Weak-point targeting remains a later feature. Coverage is movement-pattern based.
8. Generation is deterministic. No LLM and no randomness; Exercise Rotation controls how often
   the choice changes, not whether it is deterministic.
9. All resolver configuration is exposed under **Settings -> Resolver**; the shipped template
   YAML remains the blueprint, with a separate versioned resolver policy file.

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
| History | Prescriptions, items, workouts and sessions are append-only. | Add generated-session/policy digests and top-set structure to provenance; no rewrite or backfill. |
| UI | Forecast is on Programme; the YAML editor is on Exercises and writes the single file. | Add a Settings -> Resolver section and a generation preview; keep the template editor on Exercises; the forecast shows the blueprint/expected pattern (option c). |

---

## 3. Architecture

### 3.1 Resolution path

```text
fixed four-template YAML  (blueprint + fallback)
resolver policy file     (pools, patterns, weights, rotation, top set)
                    |
athlete state (readiness, fatigue, spinal, injury, suitability, history, DUP, competition)
                    |
scheduler -> session type -> deterministic session generator
                    |
        joint evaluator: readiness + deload + spinal + volume budget (read-only)
                    |
          generated SessionTemplate (exercises + top-set structure)
                    |
          build_prescription (same pipeline, once)
                    |
     generated session + digests + top-set structure (frozen at workout start)
                    |
               workout / history
```

When the Settings -> Resolver flag is off, the fixed templates are used exactly as today. A
generated session is frozen when the workout starts; it is not a block-level exercise pin.

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
- Which patterns the accessory slots cover (pattern-flexible).
- The optional top-set/back-off structure.
- The generated session's exercise list, frozen at workout start, not for a block.

**Not decided by the generator**

- kg loads: the engine solves them from e1RM/history.
- The exact final set counts after readiness/deload/volume: the joint evaluator scores them,
  but the existing pipeline remains the authority.
- Warm-up generation.

Sets/reps/RIR start from the blueprint and DUP; the permitted variations are the optional
top-set structure and the joint volume allocation. The generator does not create a second
periodisation or volume engine.

### 3.3 What is reused, extended and new

**Reused unchanged**

- Slot, SessionTemplate, validate_text, four canonical identities.
- Rolling scheduler.
- build_prescription readiness/e1RM/RIR/volume/deload/spinal/validation.
- Exercise taxonomy, suitability, constraints and selection comparability.
- Workout execution, history and append-only persistence.
- Forecast logic (blueprint mode, option c).

**Extended**

- build_prescription accepts the generated template and the top-set structure (already supports
  template; caller wiring is the change).
- Scheduler, volume budget, selection and critique accept the generated/blueprint template or a
  frozen snapshot.
- A read-only evaluator exposes the existing pipeline for candidate scoring.
- Prescription gains blueprint/policy digests, input hash, generated-session snapshot and
  top-set structure.

**New**

- Deterministic session generator (exercise choice, rotation, eligibility, top-set RIR).
- Resolver policy file and Settings -> Resolver section.
- Joint evaluator for post-budget scoring.
- Top-set/back-off set-group model and load solver support.
- Generator-specific validation (pattern coverage, volume, duration, power, suitability,
  top-set rules).
- Generation preview and per-session regenerate.
- Tests.

**Not new**

- No second scheduler, prescription engine, volume engine or programme lifecycle.
- No LLM generation.
- No cardio programming.
- No equipment/experience/objective model beyond the existing suitability state.
- No block-level exercise pin.

### 3.4 Template resolution call sites

| call site | path | change |
|---|---|---|
| `prescribe/engine.py` | future | use the resolved template passed by the caller |
| `prescribe/schedule.py` | future | read `primary_exercise` from blueprint/fallback; availability must not depend on a fixed primary when the main pool can substitute (see §12.11) |
| `prescribe/volume_budget.py` | future | accept resolved/effective template rows; stop reloading by type in `template_rows`, `plan_drop`, `report` and `record_exemptions` |
| `prescribe/templates.py` | global read | `all_rep_ranges()` pools rep ranges across all four shipped templates; its scope under dynamic resolution must be stated (blueprint ranges or resolved ranges, not an implicit current-file read) |
| `rules/context.py` | future | the `RuleContext` rep-range map passed by `engine.py` is built from `all_rep_ranges()`; decide its dynamic-mode source (`PRG-DP-001`) |
| `prescribe/selection.py` | future | resolve candidates within the resolved template slots |
| `prescribe/fatigue_selection.py` | future | same |
| `prescribe/demand_scope.py` | read-only | use explicit template/version |
| `critique/facts.py` | historical | use frozen resolved template or linked version; it currently receives only `session_type` and must resolve the linked prescription/snapshot |
| `features/programme.py` | forecast | use active blueprint/resolver path or fixed fallback; define how future dates resolve against projected rows |
| `prescribe/summary.py` | docs | render from selected version |
| `agents/proposal.py` | current live path | it loads the template by `session_type`; under dynamic mode it must use the active resolved template or proposals must be unavailable until the LLM work resumes |
| `tools/workout_generation_example.py` | dev tool | low priority; it reads the shipped YAML directly |

---

## 4. Resolver inputs and policy

### 4.1 Existing athlete inputs

- sessions_per_week_target;
- max_session_minutes;
- athlete_constraint and exercise_suitability (can_do, will_do, feels_bad);
- readiness (per-lift and global) and the existing missing-readiness rules;
- recent stress/fatigue, spinal load/cap and injury signal;
- recent training history, e1RM and pattern exposure;
- taxonomy patterns, primary muscles, loadability and power classification;
- existing volume landmarks/targets and time estimates;
- DUP week/scheme and competition_date;
- resolver settings (rotation, top-set mode, coverage priority and weights).

No new objective, equipment, experience or muscle-priority state is added. Missing readiness is
neutral; unrated suitability is not auto-selectable. The generator may use stored state only; it
may not invent a value for a missing input.

### 4.2 Resolver policy

The policy is a versioned **structural** configuration file
(config/template-resolver.v1.yaml) that defines:

- per session type: required movement patterns inherited from the blueprint;
- the candidate catalogue reference (config/variants.v1.yaml), with optional per-session/slot
  pools that must not duplicate the catalogue;
- allowed patterns per slot and pattern-flexibility boundaries;
- redundancy limits by pattern and primary muscle;
- top-set eligible main lifts and explicit exceptions;
- schema version and digest.

Scalar tunables live in the settings profile (append-only, effective-dated): enable, Exercise
Rotation and dwell, eligibility/confirmation, coverage priority, readiness/fatigue/spinal/
injury weights, tie-break, top-set mode/back-off percentage/RIR mapping, competition
window and taper, and forecast mode. Keeping the structural policy and the scalar tunables
separate avoids two competing sources for the same value.

The policy contains no athlete data. It is tracked in git, validated on load, and identified by
its digest; there is no database template-version table in the MVP.

### 4.3 Fixed YAML fallback and source of truth

The fixed four-template YAML remains the structural blueprint and fallback. When the
Settings -> Resolver flag is off, it runs exactly as today.

The YAML editor stays on Exercises and writes the shipped file with the existing backups. The
Settings -> Resolver section edits the policy file, not the blueprint. No database
template-version or template-state table is added; git and the backup directory are the
blueprint history, and the policy file is versioned the same way.

---

## 5. Resolver algorithm

### 5.1 Session flow

1. The scheduler selects one of the four session types.
2. Load the fixed blueprint for that type.
3. Load the resolver policy if dynamic generation is enabled.
4. Read the athlete state: readiness, recent stress, spinal load, injury signal, suitability,
   history, DUP week/scheme and competition date.
5. Build the candidate set per slot, applying hard constraints, eligibility and pattern rules.
6. Run the joint evaluator for candidate assignments: readiness set cuts, deload, spinal trim,
   volume budget, time estimate and validation, in read-only mode. Score the post-budget
   outcome.
7. Choose the best proposal with a fixed deterministic order and tie-break.
8. Build the generated SessionTemplate with the chosen exercises and top-set structure.
9. Validate the generated template and the whole session.
10. Pass it to build_prescription; the same pipeline runs once.
11. Freeze the generated session, policy/blueprint digests, input hash and top-set structure
    when the workout starts. A later generation can differ; there is no block pin.

If a required slot cannot be resolved, generation fails with a field-level error and the UI/CLI
offers an explicit "disable dynamic generation" action. Fallback to the fixed template occurs
only when the flag is off. There is no silent fallback.

### 5.2 Main and secondary lifts

- The session type defines the primary pattern family: squat, hinge, bench_squat or bench_hinge.
- The main lift rotates only within that family (for example SSB, competition, front or high-bar
  squat on a squat session). It never changes the session identity.
- The secondary/support lift rotates within its support pattern (bench support stays a
  horizontal push; squat support stays a squat; hinge support stays a hinge).
- If no valid main/secondary lift exists, the session is unavailable; do not silently substitute
  a different session type.
- The scheduler's availability check must be pool-aware and must not veto a session because one
  fixed default is contraindicated when another valid candidate exists.
- The generated template sets primary_exercise to the chosen main lift, so the engine's
  constraint handling and the scheduler identity stay correct.

### 5.3 Accessories, patterns and coverage

Accessory slots are pattern-flexible within the policy. The policy must define:

- required patterns per session (for example at least one horizontal pull, one vertical pull or
  press, one knee-flexion pattern; erector work only where the blueprint allows it);
- allowed patterns per slot and the main/secondary boundary;
- redundancy limits by pattern and primary muscle;
- candidate pools, including the existing variants catalogue and taxonomy.

Given a candidate assignment, the evaluator computes the projected end-of-week pattern totals
including the current session and the planned remaining sessions. The score rewards reducing the
largest under-target gap without creating an over-target or MRV breach. "Projected" means the
post-budget outcome, not the raw blueprint sets.

Weak-point targeting is not implemented. The app has no validated weakness metric; automatic
weakness/injury-targeted selection remains a later gated feature. This is movement-pattern
coverage, not weakness correction. Muscle-group balance uses the taxonomy's primary muscles as a
diversity heuristic; volume minima/maxima remain movement-pattern based.

### 5.4 Power

Power is a hard structural constant:

- **all four blueprints already carry one power slot**: `box_jump` on squat, `broad_jump` on
  hinge, and `medicine_ball_chest_pass` on both bench sessions (`DEC-POWER-01/02/04/05`);
- first in the session, before strength work;
- 3 sets of 3–5 reps (the blueprint controls the dose), full recovery (about 120 s);
- maximal intent and a quality stop, no RIR;
- no load progression and no double progression;
- no Olympic lifts;
- power pattern sets stay outside MEV/MAV/MRV; `power_throw` shares the fixed `power_jump`
  volume bucket.

The resolver treats the power slot as fixed: it does not choose a different power exercise, add
a second power slot, or remove it. The taxonomy already carries `power_jump` and `power_throw`
patterns; no separate upper-body power pool is needed. If frequency is one or two sessions per
week, the available session keeps its own power slot and the resolver records a warning that
twice-weekly power exposure is not feasible; it never adds sessions.

### 5.5 Volume, duration and joint optimisation

The generator and the volume budget are one joint decision, not two independent passes:

- candidate exercise assignments are scored by the **post-budget** week projection;
- the evaluator runs the existing readiness set cuts, deload, spinal trim, volume budget,
  time estimate and validation in read-only mode;
- the winning proposal is built once by the same pipeline; the budget is not applied twice and
  is not reimplemented;
- the existing volume budget remains the only volume engine and the runtime authority;
- top-set time and spinal cost are part of the evaluation; back-off sets are trimmable, the top
  set is protected.

Weekly pattern volume is checked against the existing configurable landmarks. The existing
session-time estimate checks that the generated session fits max_session_minutes. If it cannot
fit, generation fails or warns according to the validator; it never silently exceeds the limit.

### 5.6 Determinism

Same blueprint digest + policy digest + athlete state/history snapshot + config + date + session
type + rotation state = same generated session.

- No randomness; stable candidate order and deterministic tie-break.
- No LLM.
- Store the input hash, blueprint/policy digests, generated-session snapshot and top-set
  structure.
- A new date or a materially changed readiness/history state may produce a different session by
  design; that is not a violation of determinism.
- kg is not resolved here; the runtime engine computes it from current e1RM/readiness.
- The generated session is frozen at workout start; no mid-session change.

### 5.7 Exercise Rotation

Exercise Rotation is a deterministic dwell rule, not a random score weight.

- rotation 0: keep the slot's last exercise unless a hard constraint, required pattern or volume
  objective cannot be met.
- rotation 1: choose a different eligible exercise every session; if no alternative exists, keep
  the only eligible one and warn.
- 0 < rotation < 1: dwell = 1 + round((1 - rotation) * (D - 1)), with D a configured maximum
  dwell (default 8 sessions). Rotate when the slot has gone that many sessions without a change.
- Recommended defaults: 0.2 main/secondary, 0.5 accessories; the setting can be global with
  per-class overrides.
- Constraints, injury, required patterns and coverage may force a change before the dwell; pure
  variety does not.
- Tie-break inside a rotation: least recently used, then canonical id.

### 5.8 Top set / back-off (optional main-lift structure)

The generator can offer a top set + back-off structure for the session's primary main lift. It is
a set-configuration feature, not a second periodisation engine. Eligibility is validated against
the taxonomy's main-lift markers (`main_lift` or `primary_compound`); `conventional_deadlift` is
not in the list because the taxonomy does not classify it as a main lift today.

**Structure**

- one top set plus back-off sets, preserving the blueprint's total working sets;
- top set at the blueprint's rep range and the resolved top-set RIR;
- back-off sets at 85% of the top-set load (configurable) with the normal RIR window;
- no AMRAP, no failure set and no RIR 0;
- warm-up derives from the top-set load; the top set counts as a working set and one spinal
  exposure;
- top set protected from volume trim; back-off sets are trimmed first; deload reduces back-off
  sets and may reduce the top-set load; no top set on a deload week;
- first-class set-group model on the item, not two same-exercise item rows.

**Top-set RIR**

Use the DUP main scheme actually applied to the item:

- maximal -> 1;
- strength -> 2;
- DUP off/no anchor -> 2;
- competition override: inside the configured peak window (default 4 weeks) the base is 1,
  even on a strength week;
- then apply readiness/deload once; if the resolved RIR would exceed 2, use straight sets;
- no top set inside the configured taper (recommended 7 days) before competition;
- never RIR 0; clamp the resolved value to 1 as the lowest.

**Hinge on a maximal week**

Hinge is allowed on a maximal week. Remove the maximal exclusion for the prescribed hinge
exercises (trap bar, sumo and conventional deadlift) and remove the separate top-set RIR-2 cap for
hinge. Keep the accessory/risk hinge exclusions (good morning, rack pull, Jefferson curl) unless
separately approved. This is a programme change with a spinal/fatigue cost: record it as a
decision, update goldens and show a warning. The ordinal spinal cap is load-blind, so a maximal
hinge exposure is not fully represented by the cap.

**Ordering**

1. build the base item and set structure;
2. apply the DUP scheme (reps/load; preserve the structure);
3. resolve the top-set RIR from the applied scheme and competition override;
4. apply readiness/deload once;
5. fall back to straight sets if the resolved RIR is above 2;
6. run the volume budget (trim back-offs first).

**Evidence**

The top-set/back-off evidence review recommends no default programme change. The generator
option is therefore opt-in; the default mode is ask (visible in generation, not applied), and
it is recorded as a decision/assumption with a warning. It is not automatically selected from
readiness.

### 5.9 Joint evaluator

The evaluator is the existing pipeline in read-only mode, not a copy:

1. outer loop: candidate assignments per slot (greedy or bounded beam; deterministic order);
2. inner evaluator: readiness set cuts, deload, spinal trim, volume budget, time estimate and
   validation;
3. score: projected pattern-band distance, required-pattern coverage, readiness/fatigue fit,
   spinal cost, injury penalty, rotation, preference and time;
4. choose the best complete proposal; build it once; freeze it at workout start.

Performance is bounded by fixed candidate limits and a deterministic beam width (recommended
3-5), not by a wall-clock cut-off. A cheap prefilter selects candidates for full evaluation. If
the exact evaluator is too slow, extract a lightweight projection that calls the same budget
functions; do not write a second volume engine.

---

## 6. Resolution versus runtime

| Concern | Generator | Existing runtime |
|---|---|---|
| Session type | no (scheduler) | scheduler |
| Exercise choice | yes (rotation, readiness, fatigue, spinal, injury, coverage) | no second selection |
| Top-set structure | yes (optional, main lift) | set-group load solver and logging |
| Sets/reps/RIR target | blueprint + DUP + top-set RIR base | readiness, deload, volume, DUP application |
| kg load | no | e1RM solver/load history |
| Power placement | blueprint/policy | quality-stop enforcement |
| Weekly volume | joint post-budget score | volume budget/MRV cap (only engine) |
| Duration | fit check | estimate and warnings |
| History | no writes | append-only prescription/workout; generated session frozen at start |

---

## 7. Persistence and provenance

### 7.1 Provenance

No template_version, resolver_policy_version or template_state tables are added in the MVP. The
blueprint is the shipped YAML; the policy is a tracked file; the dynamic flag is a settings
profile value.

Minimum provenance:

| object | purpose |
|---|---|
| prescription.template_digest | SHA-256 of the blueprint file used |
| prescription.policy_digest | SHA-256 of the resolver policy file used; null on the fixed path |
| prescription.input_hash | canonical hash of the state/config inputs used for generation |
| prescription.generated_session_json | generated exercise list, slot patterns and top-set structure; null on the fixed path |
| settings_profile resolver flag | dynamic generation on/off, effective-dated |

Reuse the existing run/prescription provenance path and settings-profile snapshot. Do not add a
third overlapping provenance surface without a stated reason. The canonical input hash must be
defined (tables/rows, date, history window, blueprint/policy digests, config digests, rotation
state) and stored, not recomputed from the current database.

### 7.2 Default, policy save and rollback

- If the settings-profile resolver flag is off, the fixed templates run exactly as today.
- Turning the flag on uses the current policy file; there is no database seed or active-version
  record.
- Policy save takes effect for the next generation, with a diff and backup. A generation or a
  workout start never changes the policy.
- Rollback is flipping the flag off, restoring the policy file from backup, or checking out the
  previous git revision.
- A policy edit cannot change a generated session that is already in progress.

### 7.3 Editors and source of truth

- The template YAML editor stays on Exercises and edits the shipped blueprint file with the
  existing backups.
- Settings -> Resolver owns the policy editor: structured controls for common values plus an
  advanced validated YAML view. Saving writes the policy file with a backup and digest.
- The advanced policy editor must validate the whole document before writing; a rejected save
  leaves the current file untouched.
- No editor mutates an active database version in place, because there is no database version.

### 7.4 Historical integrity

- New prescriptions store blueprint/policy digests, input hash, generated-session snapshot and
  top-set structure.
- Old prescriptions keep nulls; their stored items remain readable.
- Critique for new sessions uses the frozen generated session's rep ranges and top-set roles.
- Critique for old unlinked sessions continues on the current fallback; do not invent history.
- Switching the resolver flag or policy never rewrites old prescriptions or workouts.

### 7.5 What "frozen" means

The generated_session_json is the **effective** session used to build the prescription, after
readiness set cuts, deload, spinal trim and the volume budget. It includes the final exercise
list, slot patterns and top-set structure. It is not the raw pre-runtime proposal.

- The prescription items remain the final truth for what was prescribed.
- The snapshot exists so critique, volume_budget.record_exemptions and historical display can
  recover slot rep ranges, base sets and top/back-off roles without reading the current policy.
- The live workout copies the plan JSON, so it must copy the generated-session identity and
  top-set structure with it; it must never re-read the active policy.
- A generated session is frozen when the workout starts; a later generation is a new session,
  not a rewrite.

Do not rewrite old prescriptions. Null means "not recorded", not "use current".

---

## 8. UI and API

### 8.1 Navigation

- **Settings -> Resolver** is the configuration home for dynamic generation and all policy
  values.
- The template YAML editor stays on **Exercises**.
- The existing forecast stays on **Programme** and shows the blueprint/expected pattern (option
  c); it does not claim a future exercise list.
- No separate pathway selector, no template-version management page.

### 8.2 Settings -> Resolver

The section contains, in order:

1. **Generation:** enable, Exercise Rotation, dwell, eligibility, coverage priority,
   readiness/fatigue/spinal/injury weights or modes, tie-break.
2. **Top set / back-off:** mode (off / ask / on), eligible main lift, back-off percentage,
   DUP/competition RIR mapping, peak window, taper, fallback-to-straight rule.
3. **Pools and patterns:** required patterns per session, allowed patterns per slot, candidate
   pools, redundancy limits, structural policy.
4. **Preview:** "Preview next session" and "Regenerate"; shows choices, reasons, alternatives,
   top-set structure and warnings.
5. **Policy:** validation, digest, diff, save/backup; advanced YAML view.

High-level controls use the existing settings-profile form (append-only, effective date,
reason, guarded confirmation). Structural policy uses the advanced validated YAML editor.
No volume targets are duplicated here; link to Settings -> Volume.

**Step 1 note:** the scalar keys are already registered, so the generic Settings profile shows a
**Resolver** group. The dedicated Settings -> Resolver panel, preview and policy editor are
Step 5; Step 1 does not wire the values into any prescription.

**Resolver settings inventory**

Scalar keys (settings registry / settings profile):

- resolver.enabled
- resolver.rotation.default, resolver.rotation.main, resolver.rotation.accessory,
  resolver.rotation.max_dwell
- resolver.eligibility.auto_requires_can_do, resolver.eligibility.unrated_mode,
  resolver.eligibility.will_do_blocks, resolver.eligibility.feels_bad_blocks
- resolver.coverage.priority, resolver.coverage.under_target_weight,
  resolver.coverage.over_target_weight
- resolver.weights.readiness, resolver.weights.fatigue, resolver.weights.spinal,
  resolver.weights.injury
  (the rotation and preference weights were retired in the Step 2 final remediation because
  the dwell mechanism and binary suitability made them constant across automatic candidates)
- resolver.tie_break
- resolver.top_set.mode, resolver.top_set.eligible, resolver.top_set.backoff_percent,
  resolver.top_set.preserve_total_sets, resolver.top_set.protect_top_set,
  resolver.top_set.fallback_above_rir
- resolver.top_set.rir_by_main_scheme.maximal, resolver.top_set.rir_by_main_scheme.strength,
  resolver.top_set.rir_by_main_scheme.off
- resolver.competition.peak_weeks, resolver.competition.taper_days,
  resolver.competition.override_enabled
- resolver.forecast.mode = blueprint

Structural policy (config/template-resolver.v1.yaml, advanced editor):

- required patterns per session;
- allowed patterns per slot and the main/secondary boundary;
- candidate pools and redundancy limits;
- per-class rotation overrides and tie-break detail;
- top-set eligible lifts and any lift-specific exceptions;
- policy schema version and digest.

Guarded keys (confirmation and reason required): top-set load/RIR, competition override,
spinal/injury weights, and any setting that can increase a near-maximal exposure. The hinge
maximal change lives in the DUP schemes config, not in the resolver panel; the panel links to it
and shows the warning.

### 8.3 Generation workflow

1. readiness and state;
2. scheduler/session type;
3. generator chooses exercises and optional top set;
4. preview shows the generated session, top-set structure, warnings and alternatives;
5. start workout freezes the generated session; a later generation is a new session.

If readiness or settings change before start, offer "Regenerate" and show a diff. The started
workout never changes.

### 8.4 API (proposed)

- GET /api/settings/resolver
- POST /api/settings/resolver (scalar settings save; settings-profile semantics)
- GET /api/settings/resolver/policy
- POST /api/settings/resolver/policy (validated YAML save with backup/digest)
- POST /api/resolver/preview (date/session type; returns proposal, reasons, top-set structure,
  projected week, warnings)
- POST /api/resolver/generate (freeze the proposal as the prescription when starting)
- Existing /api/programme remains the blueprint forecast (option c).

### 8.5 CLI

UI-first for MVP; read-only status/show later. Document the temporary gap in
[UI-CLI-PARITY.md](UI-CLI-PARITY.md). Do not rename the existing `programme` command.

### 8.6 Mobile

One section per step; generated session cards with expandable slot details; warnings first;
explicit save/regenerate; sticky save. No wide table.

---

## 9. Validation and testing

### 9.1 Resolver validation

- Fixed blueprint parses through validate_text.
- Generated session has all required slots, at least one essential slot and valid patterns.
- Main/secondary lifts match the session pattern family.
- Exercise ids exist, are eligible (explicit can_do or confirmed rating) and not vetoed.
- No duplicate/overlapping slot content beyond policy allowances.
- Power slot is first, no RIR, has quality stop.
- Top-set structure is valid: one top set, preserved total sets, back-off percentage, no AMRAP,
  RIR not 0, top-set RIR mapping and fallback-to-straight rule.
- Hinge maximal-week decision is reflected in the scheme and tests; a warning is emitted.
- Competition override is inside the configured window; deload/taper and readiness rules win.
- Weekly pattern volume, spinal cap, MRV and session time are inside configured limits after the
  joint evaluator.
- No unresolved slot; fail with a field-level error.
- The generated session is consumable by build_prescription; the preview and final build agree.
- Settings values validate; the policy file rejects unknown keys and invalid combinations.

### 9.2 Test layers

| layer | coverage |
|---|---|
| unit | rotation endpoints/dwell; eligibility and unrated confirmation; coverage scoring; pattern flexibility; top-set RIR mapping; competition override; hinge maximal; power; failure cases; scheduler availability |
| integration | generator -> SessionTemplate/top-set -> build_prescription -> scheduler/volume/selection; joint evaluator and final build agree; plan_drop/report/record_exemptions use the generated session; proposal path uses the same policy or is disabled |
| regression | fixed path unchanged when the flag is off; golden prescriptions; forecast; rules; workout/history; PRG-DP-001; hinge maximal golden update |
| historical | generated-session snapshot and top-set structure; frozen at start; policy/digest changes do not rewrite old rows |
| migration | additive provenance columns/table; no template-version seed; no backfill |
| UI/API | Settings -> Resolver save/validation; preview/regenerate; top-set toggle; rating/confirmation; option-c forecast |
| determinism | same inputs and rotation state produce the same generated session; no random order; bounded beam |
| safety | top set never RIR 0; no top set on deload/taper; hinge maximal warning; missing readiness neutral; no silent fallback |

### 9.3 Existing invariants

- Four canonical identities and default scheduler behavior.
- build_prescription output for fixed templates when the resolver flag is off.
- Readiness/RIR/e1RM/volume/spinal/deload semantics.
- Append-only history; generated session frozen at start.
- Forecast /api/programme option (c): blueprint/expected pattern, no future exercise claim.
- Template schema; top set is opt-in and defaults to ask.
- No top set at RIR 0; hinge maximal is an explicit approved change.

---

## 10. Implementation steps

Work on `feature/template-resolver` off `development`; merge at gates.

### Step 0 — Contracts and decision records

**Status:** confirmed and complete 2026-11-01. Documentation and decisions only; no code
starts in this step.

**Confirmed decisions to record:**

- fixed YAML = blueprint + fallback; the shipped file is the source of truth;
- session generator per session, no block-level exercise pin; generated session frozen at
  workout start;
- main lift within its pattern family; secondary within its support pattern; accessories
  pattern-flexible;
- Exercise Rotation 0-1 as a deterministic dwell rule; defaults 0.2 main/secondary, 0.5
  accessories, D=8;
- eligibility: explicit can_do=1 when require_can_do is on; when it is off unrated candidates
  are admissible; while it is on, unrated_mode selects confirm (suggestion) or exclude (hidden);
  will_do/feels_bad suggestion-only; no default/fallback bypass;
- joint bilevel optimisation: readiness/deload/spinal/volume inside the evaluator; final build
  once; no second volume engine;
- top set/back-off: opt-in main-lift structure, preserve total sets, 85% configurable, top set
  protected, back-offs trimmable, set-group model;
- top-set RIR: DUP maximal=1, strength=2, DUP off=2; competition peak override=1; readiness/
  deload once; >2 means straight sets; no top set on deload or taper;
- hinge is allowed on a maximal week: remove the maximal exclusion for the prescribed hinge main
  lifts and the separate top-set RIR cap; keep the accessory/risk exclusions;
- competition-date override: peak window default 4 weeks, taper default 7 days;
- Settings -> Resolver owns all configuration; high-level UI plus advanced YAML; scalar keys in
  the settings profile;
- forecast option (c): blueprint/expected pattern, generated at start;
- failure is a hard field-level error with an explicit disable action; no silent fallback.

**Completion (2026-11-01):** plan confirmed; DEC-RESOLVER-01 to DEC-RESOLVER-06 recorded;
feature/template-resolver created; docs consistency green; no code, schema, config or API
change. The methodology version bump and hinge golden updates happen at implementation, not in
Step 0.

**Change control:** a change from fixed to dynamic session composition, and the hinge maximal
change, are methodology/programme changes. At implementation, bump docs/METHODOLOGY.md §9 and
update the detailed docs per its §8 change-control table. The hinge maximal change needs its own
decision and golden updates.

**Sequencing:** ROADMAP.md currently places this work after v1.2. Starting earlier needs explicit
owner approval; do not silently move the gate.

**Tests:** docs consistency.

**Acceptance:** decisions recorded; no code starts before approval.

**Merge gate:** documentation can merge to development first.

### Step 1 — Settings, policy file and provenance  (complete 2026-11-01)

**Status:** complete. Storage and validation only; the resolver flag is off and no generator or
prescription path consumes the new values.

**Objective:** store the resolver flag, policy file and prescription provenance without changing
behaviour.

**Delivered:**

- config/template-resolver.v1.yaml: structural policy for the candidate catalogue reference,
  required/allowed patterns, optional slot pools, redundancy and top-set eligible lifts;
- strength_coach/prescribe/resolver_policy.py: strict loader/validator with schema version;
  duplicate-key, YAML merge-key and recursive-alias rejection at every level; string-only mapping
  keys; ordinary anchors/shared aliases allowed; candidate-catalogue structure, slot-pool
  movement-pattern and top-set main-lift checks; file-read errors normalised with the underlying
  cause preserved; SHA-256 digest;
- 30 scalar resolver keys in settings_registry/settings_profile after the Step 2 final
  remediation retired the redundant rotation and preference weights (Step 1 originally
  registered 32; DEC-RESOLVER-10); the existing generic Settings profile now shows a Resolver
  group, while the dedicated panel remains Step 5;
- migration 0048 adds nullable template_digest, policy_digest, input_hash and
  generated_session_json to prescription; append_prescription accepts them and preserves null
  for the fixed path;
- SessionTemplate.digest exposes the shipped blueprint SHA-256 for provenance;
- no database template-version or template-state table;
- DEC-RESOLVER-07/08 record the Step 1 implementation boundary and the top-set eligibility correction.

**Data:** additive nullable provenance columns; no seed, no backfill.

**UI/API/CLI:** the generic Settings-profile group and the existing /api/settings/profile
payload gain the Resolver keys; there is no generator preview, no new endpoint and no new CLI
command. The dedicated Settings -> Resolver panel is Step 5.

**Tests:** tests/test_resolver_policy.py, tests/test_resolver_settings.py and
tests/test_resolver_provenance.py cover duplicate/merge/recursive YAML keys, anchor sharing,
string-key enforcement, catalogue structure, slot-pool patterns, main-lift eligibility, file-read
errors, digest stability, profile save/guarded values, the snapshot, nullable provenance and the
blueprint digest.

**Acceptance:** the app behaves exactly as today with the flag off; a policy file loads,
validates and hashes; fixed-path prescriptions leave the provenance columns null.

**Merge gate:** merged to the feature branch behind the disabled flag; Step 2 not started.

### Step 2 — Generator core  (complete 2026-11-01)

**Status:** complete and remediated 2026-11-01. Internal generator only; no prescription wiring,
persistence, UI or top set.

**Objective:** produce a valid generated SessionTemplate from blueprint + policy + state.

**Delivered:**

- strength_coach/prescribe/generator.py: deterministic candidate pools, shared eligibility,
  rotation dwell, main/secondary pattern families, pattern-flexible accessory slots,
  required-pattern repair, redundancy and provisional coverage scoring, injury exclusion and the
  existing weekly spinal-cap check;
- strength_coach/prescribe/resolver_settings.py: reads the Step 1 scalar settings from the
  effective-dated profile, including require_can_do, unrated_mode and rotation_default;
- config/template-resolver.v1.yaml: the accepted accessory pattern-flexibility mapping,
  the explicit hinge main pool (trap bar and sumo), and the hinge main pool comment;
- generated session output records the chosen exercise, pattern, score, reasons, alternatives,
  pending ratings, suggestion-only candidates, the policy digest and the catalogue digest; the
  generated template has concrete exercises and the chosen main lift as primary_exercise;
- available_session_types() checks the power/main/secondary structural slots, required patterns,
  hard constraints and concrete or pattern-level injury exclusions; schedule.next_session_type
  is unchanged;
- no top set, joint volume-budget evaluator, persistence, API, CLI or UI; no prescription path
  consumes the generator, and resolver.enabled remains off.

**Remediation semantics (2026-11-01):**

- **Hard exclusions.** A candidate is excluded when a constraint vetoes it, when its concrete id
  is in an active injury region, or when its taxonomy pattern matches an active
  pattern:<family> injury identifier. The same helper is used by generation, repair, power-slot
  safety and availability.
- **Fixed power slots.** The configured power exercise is never substituted or omitted. If it is
  vetoed, injured, not permitted, can_do=0, or merely suggestion-only, generation fails with a
  field-level error naming the power slot and the reason.
- **Eligibility.** With require_can_do=true, automatic selection requires an explicit can_do=1.
  Unrated candidates are suggestion-only under unrated_mode=confirm and hidden under exclude; a
  default or fallback never bypasses this. With require_can_do=false, unrated candidates are
  admissibly automatic (unrated_mode is the requirement-on policy). will_do=0 and feels_bad=1 are
  never automatic; the Step 1 flags decide whether they remain suggestion-only or are hidden.
- **Rotation default and scoring.** Rotation is the deterministic dwell rule, not a ranking
  weight. rotation_default is the fallback for secondary and unclassified slots; the shipped
  default is 0.2 so main/secondary rotation matches the confirmed 0.2 default. The redundant
  resolver.weights.rotation setting was retired (DEC-RESOLVER-10) because every ranked candidate
  had the same rotation value.
- **Required-pattern repair.** Automatic candidates are filtered by the missing pattern first;
  only then is the blueprint fallback considered. A fallback must pass the same hard, injury and
  can_do rules; a suggestion-only fallback is not selected. This avoids failing because an
  unrelated automatic candidate exists.
- **Availability.** A session is available only when power, main and secondary slots each have a
  hard-eligible candidate and every required pattern can be covered by at least one hard-eligible
  candidate. Soft preference, confirmation and scoring are not part of availability.
- **Spinal scoring.** The provisional candidate cost is the difference produced by the
  authoritative spinal rule for the whole proposed session: existing weekly exposures, every
  already-selected slot, the candidate slot and the blueprint default for not-yet-selected
  slots. It uses configured overrides, excluded patterns, set-count factors and the same neutral
  intensity assumption as final validation. Duplicate exercise ids are aggregated into one
  exposure with their total sets, so a later slot cannot overwrite an earlier one. Final
  validation remains authoritative and applies the same aggregation.
- **History.** Completed workouts and prescriptions are merged by date, with the workout taking
  precedence on a date that has both. A completed date blocks prescription fallback even when
  its plan mapping is empty, malformed or unusable; absence of exercise information is preserved.
  Multiple prescriptions on one date use the deterministic created-at/id order. The most recent
  row that actually contains a slot drives rotation; newer rows missing that slot do not erase an
  older choice.
- **Rotation warning.** When a rotation change is due and the only eligible candidate is the
  current exercise, it is retained and a warning names the configured rotation and states that
  no eligible alternative existed. This wording is not specific to rotation 1.
- **Pending ratings and transparency.** One shared helper decides pending_rating for normal
  selection and required-pattern repair, and pending_ratings is derived from the final slots.
  A dwell-retained choice keeps its dwell explanation and appends the score reasons. Reasons show
  only components actually used by the weighted score, including the injury value and its
  normalized weight.
- **Provenance.** GeneratedSession exposes policy_digest and catalogue_digest. Catalogue load,
  validation, immutable mapping construction and digest use one file snapshot, so a concurrent
  edit cannot be consumed without validation; the digest is SHA-256 over the canonical validated
  content (session, slot and candidate order), independent of file timestamps.
- **Retired preference weight.** The binary suitability fields made preference constant across
  the normal automatic pool, so resolver.weights.preference was retired rather than inventing
  graded values (DEC-RESOLVER-10). The remaining four weights are normalized over their own
  total. will_do=0, feels_bad=1 and can_do=0 remain hard/suggestion-only rules, never score
  loopholes.
- **Deferred.** The configurable injury weight is implemented only for low-back
  review/monitoring risk, because the readiness ceiling already owns the other regions and
  DEC-INJURY-04 deliberately excludes the low back there. Broader candidate-specific injury
  scoring and the joint post-budget evaluator remain Step 4/deferred; they are not simulated.

**Data:** no new tables.

**UI/API/CLI:** no visual change; internal function and tests only.

**Tests:** tests/test_generator.py covers generated defaults after explicit ratings, eligibility,
require_can_do, unrated confirm/exclude, will_do/feels_bad suggestions, pattern-level injury
exclusion, power-slot safety, rotation 0/1 and its no-alternative warning, whole-session spinal
scoring, duplicate exposure aggregation, completed-workout precedence including empty/malformed
mappings, deterministic prescription order, pending-rating consistency, dwell/injury reasons,
required-pattern fallback repair, main/secondary availability, the rotation default and
catalogue digest. tests/test_resolver_policy.py covers the pattern-flexibility policy and the
single-snapshot catalogue read.

**Acceptance:** generator returns valid generated templates and field-level errors; not wired
into the main path; the fixed-template prescription path is unchanged.

**Merge gate:** merged to the feature branch after generator unit tests; Step 3 not started.

### Step 3 — Top set / back-off structure

**Objective:** implement the optional main-lift set structure and its DUP/competition RIR
mapping, independently of exercise generation.

**Scope:** set-group model on Slot/PrescriptionItem; load solver relative to the top-set load;
DUP main scheme mapping; competition peak/taper; hinge maximal decision; warm-up, volume, spinal,
deload and readiness interaction; top-set role in critique and e1RM; UI display.

**Data:** item/set-group persistence; migration additive; no backfill.

**UI/API/CLI:** preview and workout show top/back-off sets; no automatic top set.

**Tests:** preserve total sets; 85% configurable; RIR 0 impossible; DUP maximal/strength; hinge
maximal; competition peak/taper; deload; readiness >2 fallback; volume trim removes back-offs
first; critique/volume/e1RM; golden updates.

**Acceptance:** a generated session can include a valid top-set structure with a transparent
reason; default ask leaves the fixed programme unchanged.

**Merge gate:** merge after the top-set decision and golden updates; keep the feature off by
default.

### Step 4 — Joint evaluator and pipeline integration

**Objective:** score candidate assignments by the post-budget outcome and wire the generator into
the real prescription path.

**Scope:** read-only evaluator around readiness/deload/spinal/volume/time/validation; bounded
beam search; extend volume/selection/scheduler/critique to accept the generated session; store
digests, input hash and generated-session snapshot; forecast option (c).

**Architecture:** explicit passing; no global active read inside SessionTemplate.load; preview
and final build use the same pipeline once.

**Tests:** evaluator/final build parity; no double budget; full pipeline; flag-off golden
regression; scheduler availability; PRG-DP-001; historical/critique; forecast option (c).

**Acceptance:** with the flag off, byte-identical fixed output; with it on, the generated session
uses the chosen exercises and top-set structure; old rows unchanged.

**Merge gate:** merge after default-path golden regression and joint integration tests.

**Risk:** highest-risk step; a missed template load site or a double budget pass is a silent mix.

### Step 5 — Settings -> Resolver and generation preview

**Objective:** make every resolver configuration editable and the generated session reviewable.

**Scope:** Settings -> Resolver panel; scalar settings profile; advanced validated policy YAML
with backup/digest; generation preview with choices, reasons, alternatives, top-set structure,
projected week and warnings; regenerate/diff; rating/confirmation flow; mobile layout; docs links.

**Tests:** API/UI save/validation; policy diff/backup; preview; top-set toggle; regenerate;
failure UX; mobile; no volume-target duplication.

**Acceptance:** the user can configure the generator, preview a session, choose top set/back-off,
rate an unrated suggestion, regenerate before start, and start the frozen session.

**Merge gate:** merge after UI/API and policy-validation tests.

### Step 6 — Historical hardening, rollout and documentation

**Objective:** guarantee old sessions remain stable and finish without changing the default.

**Scope:** generated-session snapshot and top-set roles used by critique/exemptions; legacy null
path; forecast option (c); policy/flag rollback; power/volume duration edge cases; performance;
docs (METHODOLOGY version, DECISIONS, ROADMAP, USER-GUIDE, UI-MAP, UI-CLI-PARITY); real-DB copy
smoke test; default flag off.

**Tests:** old/new prescriptions; policy/flag switch; critique rep ranges and top-set roles;
forecast; full suite; golden fixtures; migration/provenance copy; UI smoke.

**Acceptance:** old rows untouched; new sessions explain themselves from their snapshot; the
generator and top set work end-to-end; the feature can be disabled without data loss.

**Merge gate:** final merge to development after review; no release from the feature branch.

---

## 11. Branch strategy

- Cut `feature/template-resolver` from `development`.
- Rebase/merge development regularly.
- Merge at the gates above, not as one large drop.
- Never release/tag from the feature branch.
- Additive schema and disabled flag preserve the fallback during rollout.

---

## 12. Confirmed risks and mitigations

1. **Resolver leakage and double budget:** a missed load site, or an evaluator that applies the
   budget and then the final build applies it again, silently changes the session. Step 4 must be
   exhaustive and test evaluator/final parity.
2. **Top-set evidence:** the review recommends no default programme change. Top set is opt-in;
   the default mode is ask, recorded as a decision/assumption with a warning.
3. **Hinge maximal-week change:** removing the hinge exclusion changes the existing DUP, not just
   the generator. It is a high spinal/fatigue exposure and the ordinal cap is load-blind. Needs
   its own decision, golden updates and a user-visible warning.
4. **Competition override:** a near-competition RIR-1 top set on a hinge is high risk. Peak window
   and taper are configurable; deload/readiness/taper must win.
5. **Joint evaluator performance:** exact full-pipeline evaluation per candidate may be slow. Use
   a cheap prefilter and a bounded deterministic beam; no wall-clock cut-off that breaks
   determinism.
6. **Rotation fragmentation:** high rotation can fragment per-lift e1RM/double progression.
   Defaults are low for main lifts; the preview shows the choice and alternatives. This is
   accepted by the owner, not a bug.
7. **Eligibility/equipment:** unrated exercises are not auto-selectable; will_do/feels_bad are
   suggestion-only; no equipment model.
8. **Scheduler availability:** must be pool-aware; otherwise a valid session is hidden.
9. **all_rep_ranges / PRG-DP-001:** dynamic exercises outside the four-file pool make the rule
   unassessable unless its scope is defined.
10. **Other load sites:** volume_budget.plan_drop/report/record_exemptions reload by type;
    agents/proposal.py is live; critique receives only session_type. All must use the generated
    session or be explicitly disabled.
11. **Forecast mismatch:** option (c) is honest but will not match the eventual exercise list; do
    not present it as generated.
12. **Top-set roles in critique/e1RM:** a top set at RIR 1 must be graded against its own role, not
    the RIR 2-3 accessory target.
13. **Settings scope:** expose high-level controls plus advanced validated YAML; guard top-set
    load/RIR and spinal/injury weights.
14. **Main-lift boundary:** same pattern family only; cross-pattern would invalidate session
    identity and scheduler.
15. **No silent fallback:** an unresolved slot is a hard field-level error with an explicit
    disable action.
16. **Methodology change:** fixed -> dynamic and hinge maximal need METHODOLOGY/DECISIONS updates
    and golden fixtures.
17. **No second engine:** the generator must not become a second periodisation/volume engine.

## 13. Confirmed decisions

Recorded as `DEC-RESOLVER-01`–`10` in [DECISIONS.md](DECISIONS.md).

- Session generator per session; no block-level exercise pin; generated session frozen at workout
  start.
- Fixed YAML is the blueprint and fallback; the shipped file is the source of truth.
- Main lift rotates within its pattern family; secondary within its support pattern; accessories
  are pattern-flexible.
- Exercise Rotation 0-1 is a deterministic dwell; 0 never voluntarily rotates, 1 changes every
  session; defaults 0.2 main/secondary, 0.5 accessories, D=8.
- Eligibility: explicit can_do=1 auto when require_can_do is on; when it is off unrated
  candidates are admissible. While it is on, unrated_mode selects confirm (suggestion) or exclude
  (hidden). will_do/feels_bad are suggestion-only; no default/fallback bypass.
- Joint bilevel optimisation: readiness/deload/spinal/volume inside the evaluator; final build
  once; back-off sets trimmable; top set protected.
- Top set/back-off: opt-in main-lift structure, one top set, preserve total sets, 85%
  configurable, set-group model, no AMRAP, no RIR 0.
- Top-set RIR: DUP maximal=1, strength=2, DUP off=2; competition peak override=1; readiness/
  deload once; >2 means straight sets; no top set on deload or taper.
- Hinge is allowed on a maximal week; remove the maximal exclusion for the prescribed hinge main
  lifts and the separate top-set RIR cap; keep accessory/risk exclusions.
- Competition override: peak window default 4 weeks; taper default 7 days.
- Settings -> Resolver owns all configuration; high-level UI plus advanced validated YAML; scalar
  keys in the settings profile.
- Forecast option (c): blueprint/expected pattern, generated at start.
- No second scheduler, prescription engine, volume engine, lifecycle or LLM.

## 14. Related

- **Methodology:** [METHODOLOGY.md](METHODOLOGY.md)
- **Templates:** [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md)
- **Workout generation:** [WORKOUT-GENERATION.md](WORKOUT-GENERATION.md)
- **Volume:** [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md)
- **LLM workstream:** [LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
