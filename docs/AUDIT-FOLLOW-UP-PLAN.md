# AUDIT FOLLOW-UP — implementation plan

**Status:** implemented 2026-10-27. The audit report is
[`AUDIT-FOLLOW-UP-REPORT.md`](AUDIT-FOLLOW-UP-REPORT.md). The body below is the plan as
written, including the pre-implementation state it described. Part A is decided (`DEC-SPINE-07`); Part B is decided (`DEC-POWER-02`);
Part C is a documentation/tooling fix with no constitution change; Part D is decided
(`DEC-VOLUME-30`); Part E verifies the fixes behaviourally after they land. No code has been changed
for any part.

| part | finding | status | blocking input |
|---|---|---|---|
| A | back-flare scope misses a non-essential high-fatigue hinge; the sumo is not aligned with the competition squat; interaction tests are missing; the erector dose can be reset upward after a readiness cut | implemented 2026-10-27 (`DEC-SPINE-08`); dose ceiling and interaction matrix included | none |
| B | power work is displayed as RIR-limited but instructed as quality-limited | implemented 2026-10-27 (`DEC-POWER-03`) | none |
| C | the programme review and dependent summaries describe the old bench+hinge support | implemented 2026-10-27 | none |
| D | same-date recorded sets are counted as completed **and** added as proposed in the MRV cap, the spinal cap and the budget application | implemented 2026-10-27 (`DEC-VOLUME-31`) | none |
| E | independent adversarial audit of the fixed system, including the five previous fixes | completed 2026-10-27; report linked above | none |

The parts A–D are independent and can ship in any order. E is a gate over all of them, so it runs
last; the sequencing in §F is the safe one.

---

# Part A — Back-flare scope (`DEC-SPINE-07`)

## A.1 Goal

On a back-symptom flare, every strength-support lift that loads the back is held at **RIR 3 or
higher with its load re-solved from the same e1RM**, while direct-erector work returns to the
weeks 1–3 dose. The bench+hinge sumo becomes an essential support lift like the bench+squat
competition squat, and the rules stop using "main lift" for four different concepts.

**Non-goals:** no taxonomy change (`main_lift`, `direct_erector`, `high_fatigue_spinal` and the
2.5 spinal cost stay as they are); no change to the spinal cap, costs or trim order; no change to
DUP's cycle or to non-flare prescriptions; no readiness-policy change; no UI or API shape change;
no re-solve of readiness's own RIR bump (A.8).

## A.2 Behavioural contract

### A.2.1 The sumo and the competition squat

| property | sumo after the change | competition squat (precedent) |
|---|---|---|
| template `essential` | **true** (new) | true |
| taxonomy `main_lift` | false | false |
| `primary_compound` | true | true |
| `direct_erector` | false | false |
| `high_fatigue_spinal` | true | true |
| spinal cost | 2.5 | 1 |
| `maximal` scheme | **never** (new guard: it is a hinge) | allowed (safeties) |

Aligned in *role*, not in every property. The one deliberate difference is the hinge policy: the
competition squat can take the week-3 `maximal` scheme because it has safeties; the sumo cannot,
because a near-maximal hinge is the exposure the back-history exclusion exists for.

### A.2.2 How the flare policy is resolved

The slot may carry an optional policy: `auto` (default), `hold_effort`, `erector_dose`. Resolution
order, first match wins:

1. `erector_dose` on the slot, **or** taxonomy `direct_erector: true` → **dose** (sets **capped**
   at 3: `min(current sets, 3)`, never increased; load to 0 kg added; bodyweight basis). This
   branch keeps precedence. The ceiling is explained in A.2.6.
2. `hold_effort` on the slot → **hold**.
3. `essential: true` **or** `high_fatigue_spinal: true` → **hold**.
4. otherwise → **no change**.

`erector_dose` is honoured on a non-direct slot deliberately (a template author may want the dose
treatment on a new erector movement before the taxonomy catches up); it is not expected to be
used yet.

### A.2.3 RIR and load

- The held RIR is `max(slot.rir_low, 3)`; the flare only ever **raises** RIR. A slot already at
  RIR 4 keeps 4.
- When the RIR rises, the load is **re-solved at build time** from the same e1RM, the same rep
  count and the same increment — not relabelled on a load solved for the old RIR, and not a
  percentage cut.
- The re-solve applies to `load_source: e1rm` only. `double_progression` and bodyweight items get
  the RIR target with no load change; an e1RM item that fell back to a last working load keeps
  that load and warns as it does today.
- Readiness, continuity and deload run **after** the build, so they still stack on the re-solved
  load exactly once. The flare never makes the effective load heavier.
- The floor is 3 (the rule's 3–4 window); an item already at RIR 4 keeps 4, and readiness may
  later add another RIR as it does today.
- Direct-erector items keep the dose **ceiling**: at most 3 sets (the lower of the current count
  and 3), 0 kg added, bodyweight basis. A readiness cut is not restored (A.2.6).

### A.2.4 Provenance

- `MOD-BACK-001` is added to an item's rationale **only when that item changed** (RIR raised, or
  the dose pass lowered its sets or load). A dose branch that only confirms an item already at or
  below the ceiling is `reviewed_unchanged`, not cited. An item reviewed and already at RIR ≥ 3 is
  recorded in the modifier note, not in its rationale.
- `notes["back_flare"]` stays a bool for compatibility; a new `notes["back_flare_review"]` holds
  `held`, `reviewed_unchanged` and `dose` lists.
- The engine warning names the held items and the dose items, and says explicitly that the load
  was re-solved.

### A.2.5 Wording

Terms, to be added to `docs/RULES-FORMAT.md`:

| term | meaning |
|---|---|
| main lift | taxonomy `main_lift` / the constitution's named lift collection |
| primary compound | `primary_compound` (the RIR window scope) |
| essential item | the template slot's `essential` flag (session role) |
| direct erector work | `direct_erector` (a dose class, not an anatomy claim) |
| high-fatigue spinal lift | `high_fatigue_spinal` (the spinal-cap risk marker) |

Rule text changes (all in `config/rules/programme.v1.yaml`, constitution 1.19.0):

- `MOD-BACK-001`: "If back symptoms rise and do not settle in 24–48 h, cut direct-erector volume
  to **at most** the weeks 1–3 dose, **never restore a set removed by readiness or another earlier
  modifier**, and hold the session's **essential items and any high-fatigue spinal lift** at a
  target of **at least RIR 3** for a week; each held item's load is re-solved from the same e1RM
  at that RIR, never relabelled on a load solved for a lower RIR." Params gain
  `applies_to: [essential, high_fatigue_spinal]`; `main_lift_rir_override` is renamed `hold_rir`
  (nothing reads it; the code reads `thresholds.back_flare_main_rir`).
- `PRG-RIR-001`: "**Primary compounds** at RIR 1–4 …" — its scope already includes the sumo,
  dumbbell row and overhead press, which are not main lifts.
- `MOD-MIN-001`: "essential items" instead of "main-lift sets" (the param key
  `main_lift_floor_sets` keeps its name for config compatibility).
- `MOD-VOL-003`: "essential item" for the accessory actions, "taxonomy main lift" for reduce.

### A.2.6 The erector dose is a ceiling, not a reset

`MOD-BACK-001` says "cut erector volume to the weeks 1–3 dose". The earlier reading in this plan —
sets reset to 3 — can **increase** work when readiness has already cut the same accessory:
readiness 3 → 2, flare 2 → 3. That contradicts the rule's "cut" wording, violates the monotonicity
of simultaneous cautions, and leaves the readiness citation claiming a reduction the flare undid.

The chosen rule is a ceiling: `sets = min(item.sets, back_flare_erector_sets)`; load 0 kg added;
bodyweight basis. The flare removes added load and caps the dose; it never restores a set removed
by readiness or another earlier modifier. The symptom rule and the generic readiness score stay
distinct: the flare owns the load reset and the dose cap, readiness owns its volume cut, and both
compose downward.

The absolute difference is small — one bodyweight set versus two weighted sets is not
straightforwardly "more load" — so this is a semantic and provenance defect rather than a
demonstrated injury risk. It is still the correct default: a safety modifier should not raise
prescribed work.

This is a clarification of `DEC-SPINE-07`'s existing "cut to" wording, not a new programme
decision. If the owner wants it independently citable, add a short `DEC-SPINE-` row before
implementation; otherwise the Part A implementation row records it. The config key
`back_flare_erector_sets` keeps its name (value 3); it is a maximum, not a target.

## A.3 File-by-file

| file | change |
|---|---|
| `config/templates/session-types.v1.yaml` | `bench_hinge.hinge_support`: `essential: true`; comment says "strength support, essential like the competition squat on bench+squat". Sets, reps, rest and load source unchanged. |
| `config/templates/schemes.v1.yaml` | add `sumo_deadlift` to `maximal.exclude` with a one-line reason. The guard that keeps week 3 off the sumo once it is essential. |
| `config/rules/programme.v1.yaml` | version 1.19.0, one changelog entry, the four rule-text edits in A.2.5. No predicate or `implemented_by` change. |
| `strength_coach/prescribe/templates.py` | `Slot.flare: str \| None = None`; validate `auto/hold_effort/erector_dose`; parse from YAML; document why the default is `auto`. |
| `strength_coach/prescribe/models.py` | `PrescriptionItem.flare: str = "none"` carrying the **resolved** policy (`hold`, `reviewed`, `dose`, `none`). Generation-time only: not persisted, like `load_factor`. |
| `strength_coach/prescribe/engine.py` | resolve the policy and apply the hold inside `build_item`; carry the resolved hold forward in `_apply_undulation`; replace the effort branch of `_apply_back_flare` with the post-readiness dose pass; the dose pass uses `min(current, back_flare_erector_sets)` and 0 kg added, never a reset; add the warning and `notes["back_flare_review"]`. |
| `strength_coach/prescribe/persistence.py` | no change; `flare` is not stored. Confirm `as_rows()` stays as it is. |
| `docs/SYMPTOM-LOGGING.md` | what the flare holds, that the load is re-solved, which lifts are unaffected. |
| `docs/RULES-FORMAT.md` | the five-term table in A.2.5. |
| `docs/EXERCISE-VARIANTS.md` | document the optional slot `flare` field. |
| `docs/DECISIONS.md` | append one implementation row under the next free `DEC-SPINE-` number: constitution 1.19.0, final wording including the erector-dose ceiling (`min(current, 3)`) and the no-restore rule, where enforced. Do **not** edit `DEC-SPINE-07`. |
| `docs/LIMITATIONS-REGISTER.md` | `LIM-53` → `closed`, naming the new tests. |
| `CHANGELOG.md` | one entry under 0.5.0: sumo alignment, flare scope/load re-solve, provenance fix. |
| `ROADMAP.md` | the 2026-10-27 status row and the public test count; no phase change. |
| UI / API | none. Warning text changes; no new field. `notes["back_flare_review"]` is additive. |

### A.3.1 Why the hold runs at build time

The alternative — keep the post-readiness transform and rebuild the item there — would need the
e1RM again. The item stores the **solved load**, not the e1RM, so rebuilding from the item would
have to invert the rounded load, which is exactly the "second approximation" the load solver
forbids. Building at the source also means readiness/continuity/deload apply to the re-solved
load once, in their normal order, with no re-application logic.

The cost is one interaction: `_apply_undulation` rebuilds items after the first build, so it must
carry the resolved hold forward as an explicit `hold_effort` slot policy. Without it, a held item
rebuilt on a DUP week would lose its citation (and, if the scheme changed, its floor). A test
covers weeks 2/3/4.

The dose branch stays **after** readiness so it removes added load and caps the dose on the final
item. It does **not** protect the set count: a readiness cut survives (`min(current, 3)`), and the
readiness citation remains accurate. The earlier plan wording — "the erector dose must not be cut
by the readiness set valve" — described the old unconditional reset and is withdrawn (A.2.6).

## A.4 Tests

| file | case |
|---|---|
| `tests/test_symptom.py` | `bench_hinge` + a level-2 symptom: sumo RIR 3, load lower than the same day without a flare, cites `MOD-BACK-001`; the bench re-solves; a direct-erector item is capped at 3 sets / 0 kg (3 when readiness has not cut it); an accessory that is neither essential nor high-fatigue is unchanged and **not** cited; `notes["back_flare_review"]` lists it. |
| `tests/test_symptom.py` | a slot already at RIR ≥ 3 is `reviewed` with no citation and no load change. |
| `tests/test_symptom.py` | flare + poor readiness: both apply, the load is not higher than either alone, both citations present. |
| `tests/test_symptom.py` | poor readiness + flare on the `squat` session: back extension is 3 → 2 under readiness and **stays 2** under the flare; with added load it is reset to 0 kg and cites both `MOD-FAT-001` and `MOD-BACK-001`; with no added load the flare changes nothing, cites only readiness, and the note lists it as reviewed. The flare does not restore the third set. Flare-only is 3. |
| `tests/test_symptom.py` | flare + deload on `back_extension`: the final set count respects the deload floor, the load is 0 kg added, and the flare citation remains where the dose pass changed the item. |
| `tests/test_undulation.py` | with the sumo essential, week 3 still gives it the strength scheme (3–5), not `maximal`; only `maximal_hinge_allowed: true` changes that. |
| `tests/test_undulation.py` | a flare + a DUP week keeps the sumo at RIR 3 and keeps the citation. |
| `tests/test_prescribe.py` (or a focused test) | build-time hold: an e1rm item's load equals `solve_load(e1rm, reps, 3)`; a `double_progression` item keeps its load and changes only RIR; an unknown-load item is not solved. |
| `tests/test_volume_budget.py` | `bench_hinge` hinge top-up capacity is now 0; `preserve` changes no sumo sets; `reduce` ignores it (taxonomy `main_lift` false). |
| `tests/test_spinal_cap.py` | the sumo is no longer removable by the trim; the prescription reports the issue instead. Deliberate, asserted. |
| `tests/test_golden_prescription.py` + fixture | update `bench_hinge` deliberately: `essential: true`, warm-up ramp, changed loads. |
| `tests/test_minimum_session.py` | the sumo is now a main-tier item. |
| `tests/test_docs_consistency.py` | unchanged; every `DEC-`/`LIM-` token resolves. |

### A.4.1 Interaction matrix (the test-depth finding)

The current symptom suite asserts the squat/bench flare and the back-extension dose; it stops at
warnings and never touches the sumo. The sumo case is added in A.4. The matrix below is a separate
`tests/test_back_flare_interactions.py` and asserts the
**final prescription** — `items` (RIR, load, sets, refs), `issues` and `notes` — not merely that each
modifier added a warning. Every row has a no-flare control, so a failure shows whether the
interaction or the base modifier is wrong.

| combination | expected final state |
|---|---|
| flare + readiness reduction (sumo/bench) | hold at build, then the readiness factor on top; sumo RIR 3 (or the readiness-bumped 4), load = `solve(e1rm, reps, 3) × readiness`, both refs, no double reduction |
| flare + readiness on direct erector (`squat`) | back extension 3 → 2 under readiness, **stays 2** under the flare; added load is reset to 0 and both refs appear, while an already-bodyweight item gets no flare citation and is listed as reviewed; the flare never restores the third set |
| flare + deload on direct erector | deload runs after; the final set count respects the deload floor, load 0, and the flare citation remains where the dose pass changed the item; no upward reset |
| flare + a later set-adding modifier | under-MEV or budget top-up cannot push the erector above the flare ceiling; the final sets are asserted |
| flare + long gap (`MOD-GAP-001`) | continuity applies after the hold; load reduced once, RIR raised by the continuity bump, both refs; the 20% combined cap still covers readiness+continuity only |
| flare + deload (`MOD-DELOAD-001`) | deload runs after; the sumo (now essential) takes the deload set/load/RIR treatment; final RIR and load pinned; the flare citation remains; no double-counted load factor |
| flare + spinal cap at the boundary | at the cap: executable, sumo present, cost/cap in `notes["spinal_cap"]` |
| flare + spinal cap over the boundary | the sumo is essential and cannot be trimmed; `SPINAL_CAP` issue, prescription not executable, sumo still present — the A.7 consequence asserted, not wished away |
| flare + DUP week 3 | the sumo stays on the strength scheme (never `maximal`) and keeps the hold; the bench is re-solved on `maximal` 1–3 at RIR 3 |

These tests must be written against the **new** build-time hold, not the old post-readiness
transform. If a final value differs from this table, decide whether the documented precedence or
the expectation is wrong before changing code; do not relax the assertion to a warning.

## A.5 Commit sequence

Each commit leaves the suite green.

1. **Guard first.** Add `sumo_deadlift` to `maximal.exclude` and a test that an essential sumo
   still gets `strength` in week 3. No visible change yet.
2. **Engine: the hold at build time.** Add `Slot.flare`/`Item.flare`, resolve and apply the hold,
   split the dose pass, cap the erector dose at `min(current, 3)`, add the note and the citation
   rule. Tests for the bench, the erector ceiling and provenance.
3. **DUP carry-forward.** Carry the resolved hold through `_apply_undulation`; add week-2/3/4
   tests.
4. **Alignment.** Flip the sumo to `essential: true`; update golden, budget capacity, spinal
   trim, minimum-session and the `bench_hinge` flare test.
5. **Wording and records.** Constitution 1.19.0, four rule texts, terms table, user docs,
   `LIM-53` → closed, implementation row, CHANGELOG, ROADMAP.

If a smaller change is wanted, steps 1 and 4 are the safety-critical pair; steps 2–3 make the
number honest.

## A.6 Acceptance

- On a flare, `bench_hinge` shows the sumo at 3×3–5, **RIR 3**, load solved for RIR 3 (lower than
  the non-flare day) and `MOD-BACK-001` in its rationale.
- The bench is re-solved too — the old "RIR 3 on a RIR-2 load" is gone.
- No item carries `MOD-BACK-001` unless it changed; the note lists reviewed-but-unchanged items.
- On poor readiness + flare, the back-extension set count is the lower of the readiness-cut and
  the early-block dose; the flare never adds a set back, and the readiness citation stays accurate.
- The sumo remains `main_lift: false`, `direct_erector: false`, `high_fatigue_spinal: true`,
  cost 2.5, and still counts toward the spinal cap.
- Week 3 never puts the sumo on `maximal` with the default hinge policy.
- Full suite passes; golden fixture updated deliberately.

## A.7 Risks and known consequences

- **Spinal trim loses its only bench+hinge option.** The sumo is the one non-essential
  high-fatigue item on that day, so an over-cap week can no longer be fixed by removing it; the
  prescription becomes non-executable with an issue instead. Same trade the competition squat
  already makes; safer than silently deleting a strength lift. Accept it; do not re-add a silent
  trim.
- **Warm-up cost.** The sumo gains three ramp sets; `bench_hinge`'s estimated time rises and the
  session-time warning may fire more often. Honest; no threshold change.
- **Readiness no longer cuts the sumo by default.** That is the point of `essential`; the readiness
  valve still cuts accessories and, when enabled, essential items.
- **Erector dose below the early-block dose.** With the ceiling, a flare after a readiness cut
  leaves 2 sets rather than 3. That is intended: the flare removes load and caps the dose; it does
  not restore volume. The erector ramp resumes after the flare. Do not "fix" this back to 3
  without a decision.
- **Budget capacity.** Hinge top-up capacity on `bench_hinge` becomes 0; the budget may report
  "under, no non-essential capacity". Correct, not a bug.
- **Under-MEV top-up.** Because the sumo is essential, the under-MEV accessory rule no longer
  adds a set to it; the golden fixture drops from 4 to 3 sets on a persistent under-MEV week.
  Same exclusion as the competition squat; not a bug.
- **Drop is unaffected.** `plan_drop` removes the whole filled-group slot, not by `essential`, so
  the sumo is still removed when hinge is filled. Matches the competition squat.
- **The 20% combined load cap** still covers readiness+continuity only; a flare RIR hold is not a
  load factor, so it cannot breach the cap.

## A.8 Deliberately out of scope

- **Readiness's own RIR bump.** Initially out of scope; resolved 2026-10-27 by
  `DEC-READINESS-18`. The load is re-solved at the bumped RIR from the factor-scaled e1RM, so the
  printed RIR and the load describe the same set. This changes loads for readiness-reduced items.
- **Pattern-based hinge guard.** The plan uses the config exclusion list, the existing mechanism.
  A property-based guard is a separate improvement.
- **No per-lift load adjustment beyond the RIR re-solve.** The flare adds no percentage cut, no set
  change and no spinal-cost change.

---

# Part B — Power work is quality-limited

## B.1 Finding and agreement

The finding is correct, and it is worse than a display mismatch:

- `config/templates/session-types.v1.yaml` prescribes `box_jump` as 3×3–5 with `rir: {low: 4, high: 5}`.
- `build_item` detects power work and sets a **zero load**, `refs = ()`, and a warning: "power
  work — maximal intent, full recovery, stop when height or quality drops". It still sets
  `rir_target = slot.rir_low` (4). The operative instruction exists only in the warning.
- Warnings are **not persisted with a stored prescription** (`LIM-43`). Once the prescription is
  stored and shown in Workout/History, the item is just "RIR 4" with no quality instruction. That
  is the state the UI exports.
- `features/derived.add_effort_fields` computes `in_rir_window` for **every** set against
  `rir_mod.target_for(exercise_id)`, which defaults to RIR 2–3. Box-jump sets at RIR 4–5 are
  therefore marked non-compliant, and `features/baseline.rir_compliance_pct` averages them. RIR
  is already being interpreted numerically downstream, exactly as the finding warns.
- `DEC-POWER-01` records "RIR 4-5" as part of the original power prescription. `DEC-POWER-02`
  (recorded 2026-10-27) amends that clause; this is not a code-only bug.

**Agreement:** power work should be represented as quality-limited. Keep sets/reps, make the
quality stop rule the operative instruction, and give power items no RIR target at all — not a
number that every consumer has to remember to ignore.

## B.2 Contract

- A power item is **quality-limited**: no RIR target, no load progression, no RIR compliance, no
  RIR-based readiness/deload/continuity adjustment. Sets, reps and the stored stop rule are the
  prescription.
- The stop rule is stored **on the item**, not only in a generation-time warning, so the stored
  prescription and the UI remain self-contained.
- The template carries the stop rule for a power slot and carries **no** RIR for it. A non-power
  slot still carries an RIR.
- Non-power items are unchanged.
- Old stored prescriptions keep their recorded numbers (append-only); only new prescriptions get
  the new model. Historical box-jump rows keep `rir_target = 4` and display as RIR, with the
  snapshot's own truth. No backfill.
- The decision log is amended, not edited: `DEC-POWER-01` stays; `DEC-POWER-02` records the
  quality-limited model and the null RIR.

## B.3 Design

### B.3.1 Template and parser

- `box_jump` slot: keep `sets: 3`, `reps: 3–5`, `power: true`, bodyweight; **remove** the `rir`
  block; add `quality_stop: "Maximal intent; full recovery; stop when jump height or quality drops"`.
- `Slot` gains `quality_stop: str | None`; `rir_low`/`rir_high` become `int | None`.
- Parser rules, enforced with a clear `TemplateError`:
  - `power: true` → `rir` must be absent, `quality_stop` required;
  - `power: false` → `rir` required (as today), `quality_stop` ignored/rejected.
- This makes the dual model structurally impossible in config, not just hidden in code.

### B.3.2 Item, engine and modifiers

- `PrescriptionItem`: `rir_target: int | None`, `effort_model: str = "rir"` and
  `quality_stop: str | None = None`. `build_item` sets `effort_model="quality"`,
  `rir_target=None`, `quality_stop=slot.quality_stop` and keeps `refs=()` for power.
- Every RIR transform is guarded by `effort_model == "rir"`: readiness RIR bump, continuity RIR
  bump, deload `rir_add`, technique throttle, back-flare hold. Readiness/deload **set** reduction
  may still apply to power (a fatigue lever, not an RIR interpretation); decide that explicitly
  and test it.
- `validate_prescription`'s RIR-window check runs only for `effort_model == "rir"`.
- `_apply_undulation` already skips power (`DEC-POWER-01`); keep that.
- `agents/proposal` offers only `keep` for a quality item and never an RIR option; a `set_scheme`
  rebuild keeps `effort_model="quality"` and the stop rule. `schemes.applicable` is unchanged.

### B.3.3 Persistence

- Migration `0041` adds to `prescription_item`: `effort_model TEXT NOT NULL DEFAULT 'rir'` and
  `quality_stop TEXT`. `rir_target` is already nullable.
- Repository insert/read and `persistence.py` `as_rows` carry the two fields; old rows default to
  `rir`, so historical prescriptions remain readable.
- No backfill of old box-jump rows. Document the decision's boundary.

### B.3.4 Analytics

- `features/derived.add_effort_fields` marks power sets (`pattern: power_jump`, the existing
  taxonomy marker — no new property) with `rir_target_low = NA`, `rir_target_high = NA`,
  `in_rir_window = NA`.
- `features/baseline.rir_compliance_pct` computes over the non-NA rows, so box-jump RIR no longer
  lowers compliance.
- Add one test with a frame containing box-jump RIR 4–5 and a normal lift, asserting the normal
  lift's compliance is unchanged and the power set is excluded.

### B.3.5 API, UI, CLI, narrative

- `web/server.py` item payload adds `effort_model` and `quality_stop`; `rir_target` serialises as
  `null` for quality items.
- Prescribe table: the RIR cell shows "quality stop" and the stop rule (not `4`). Programme list:
  "quality stop" instead of `RIR 4`. Workout plan: the RIR cell shows "—" and the exercise row
  shows the stop rule. History/review show the same.
- CLI: the RIR column prints `quality` (or `Q`) for quality items and a footnote with the stop
  rule; header wording makes clear it is an effort column.
- `agents/narrative.py` includes `effort_model`/`quality_stop`; `agents/proposal.py` prompt says
  "quality stop: …" and omits `@ RIR` for power items.

## B.4 File-by-file

| file | change |
|---|---|
| `config/templates/session-types.v1.yaml` | `box_jump`: remove `rir`, add `quality_stop`, keep the rest. |
| `strength_coach/prescribe/templates.py` | `Slot.rir_low/high: int \| None`, `Slot.quality_stop`; parser validation above. |
| `strength_coach/prescribe/models.py` | `rir_target: int \| None`, `effort_model`, `quality_stop`; `as_rows` includes the new fields. |
| `strength_coach/prescribe/engine.py` | power branch sets the new fields; guards in readiness, continuity, deload, technique throttle, back flare, RIR validation. |
| `strength_coach/prescribe/persistence.py`, `store/repositories.py` | carry the fields; migration `0041`; no backfill. |
| `strength_coach/features/derived.py`, `features/baseline.py` | exclude power from RIR-window/compliance. |
| `strength_coach/web/server.py`, `web/static/app.js`, `web/static/workout.js` | payload and display. |
| `strength_coach/cli.py`, `agents/narrative.py`, `agents/proposal.py` | display/prompt; no RIR options for quality. |
| `tests/*` + golden fixture | see B.5. |
| `docs/DECISIONS.md` | `DEC-POWER-02` is recorded; do not edit `DEC-POWER-01`. |
| `docs/LONGEVITY-REVIEW.md`, `docs/W4-PROGRAMME-EVIDENCE.md`, `docs/RULES-FORMAT.md` | power wording already says "quality stop" in places; reconcile any remaining "RIR 4–5" text. |
| `CHANGELOG.md`, `ROADMAP.md` | entry and status row. |

## B.5 Tests

| file | case |
|---|---|
| `tests/test_prescribe.py` | box_jump item: `effort_model == "quality"`, `rir_target is None`, `quality_stop` non-empty, sets/reps unchanged; bench item still has an RIR. |
| `tests/test_templates.py` (or prescribe) | a power slot without `quality_stop` fails; a power slot with `rir` fails; a non-power slot without `rir` fails. |
| `tests/test_store.py` | insert/read round-trip for the new columns; a legacy row defaults to `effort_model="rir"`. |
| `tests/test_web.py` | `/api/prescribe` payload carries `effort_model`, `quality_stop` and a null RIR for box_jump. |
| `tests/test_power_work.py` | power sets are NA for the RIR window; the API/prompt/display paths carry the stop rule. |
| `tests/test_readiness.py` / `test_continuity.py` / `test_deload.py` | a quality item's `rir_target` stays `None`; no `+1` RIR. |
| `tests/test_proposal.py` | no RIR options for a quality item; a scheme rebuild keeps quality. |
| `tests/test_cli.py` (if output is asserted) | `quality` label, no `None`. |
| `tests/test_golden_prescription.py` + fixture | box_jump row updated deliberately. |

## B.6 Commit sequence

1. **Model and template.** Parser, `Slot`/`Item`, engine power branch, prescription tests,
   golden. Persistence still writes the old columns; the item fields are not exposed yet.
2. **Persistence and API.** Migration `0041`, repository/`as_rows`, `/api/prescribe` payload and
   round-trip tests.
3. **UI/CLI/narrative/proposal.** Display and prompt; tests.
4. **Analytics.** Derived/baseline exclusion; tests.
5. **Docs and decision.** Amendment row, CHANGELOG, ROADMAP, power wording sweep, and regenerate the programme-summary block with `tools/programme_summary.py --write` (Part C's test fails otherwise).

## B.7 Risks and out of scope

- **`None` ripples.** Every RIR arithmetic site is enumerated in B.4 and tested; a missed one
  fails with `TypeError` rather than silently mislabelling.
- **Old snapshots.** They keep numeric RIR; the UI shows a snapshot as recorded. Do not backfill.
- **Set reduction on power.** The plan keeps readiness/deload set cuts for power and only removes
  RIR arithmetic. If that is not wanted, it is a separate policy decision.
- **Proposal rebuilds.** A `set_scheme` on a quality item must preserve the stop rule and null
  RIR; tested.
- **Out of scope:** changing the box-jump rep range, adding a power progression rule, or
  interpreting jump height/video. The stop rule stays a text instruction.

---

# Part C — Programme documentation drift

## C.1 Finding and agreement

The finding is correct. `docs/STRENGTH-PROGRAM-REVIEW.md` still describes the bench+hinge support
as **single-leg RDL 3×8–10** and uses it in the weekly volume table; `DEC-SPINE-05` replaced it
with a **sumo deadlift 3×3–5** on 2026-10-25. `tests/test_spinal_cap.py` asserts the sumo, so the
code is intentional and the document is stale.

The drift is material, not cosmetic:

| dimension | old text | current template |
|---|---|---|
| movement | single-leg RDL | sumo deadlift |
| reps / load basis | 3×8–10, double progression | 3×3–5, e1RM-derived |
| spinal cost | 0 (non-counting) | 2.5 |
| weekly heavy-hinge sets | ~5 | ~6.5 (trap bar 5 + sumo 1.5) |
| bench+hinge week spinal total | 3 | 5.5 |

The same stale movement appears in `docs/CORE-TRAINING.md`, `ROADMAP.md` §4.17 (table and prose),
and the dated adjustment note in `docs/VOLUME-MANAGEMENT.md`. `docs/W8-VOLUME-BALANCE.md` is a
dated audit with an explicit later-amendment note; `docs/W9-SPINAL-CAP.md` §8 is current and
already correct; `docs/DECISIONS.md` rows are historical and must not be edited.

**Agreement:** update the current-state documents to the template, and make the factual tables
generated + test-checked so the next template change cannot leave them silently behind. Do not
regenerate the whole review: its evidence assessment and prose are human work. Generate the
**tables**, and test the specific movement names in the current-state docs.

## C.2 Contract and scope

- **Generated:** the session table and the weekly volume/spinal table in
  `docs/STRENGTH-PROGRAM-REVIEW.md`, between explicit markers, from
  `config/templates/session-types.v1.yaml`, the taxonomy and `config/volume.v1.yaml`.
- **Manual:** the review's evidence claims, prose and conclusions. They are not generated.
- **Historical:** `docs/W8-VOLUME-BALANCE.md` and `docs/W9-SPINAL-CAP.md` keep their dated
  analysis; W8 already carries the later-amendment note, W9 §8 is the live summary. The decision
  log is append-only and is never rewritten.
- **Current-state docs to correct:** `docs/STRENGTH-PROGRAM-REVIEW.md`,
  `docs/CORE-TRAINING.md`, `ROADMAP.md` §4.17, `docs/VOLUME-MANAGEMENT.md` (a later-amendment
  note, not a rewrite of the 2026-10-20 paragraph), and review of `LIM-16` (the lift is no longer
  in the template but is still a drop-fill candidate).
- **Enforcement:** a test regenerates the block and compares it; a second test fails if
  `single_leg_db_rdl` / "single-leg RDL" appears in the current-state docs' programme sections.
  The first catches any template change; the second catches the specific rename.

## C.3 Generator

- `strength_coach/prescribe/summary.py` renders:
  - the session table: type, work (exercise display × sets×reps, RIR or "quality stop"), set count;
  - the weekly table: sets/week per pattern/lift and counted spinal cost/week, for the
    six-session cycle.
- Reuse, do not re-implement: `templates.SessionTemplate`, `volume_budget.template_rows` and
  `pattern_key`, taxonomy `spinal_cost`, and `PRG-SPINE-001`'s cost/exclusion map. If the spinal
  cost lookup is currently private to the engine, extract one shared function and have both use
  it.
- The rendered block starts with a source digest (SHA-256 of the three config files) so the test
  is stable and a config change is visible.
- `tools/programme_summary.py` is a thin wrapper: `--check` (exit 1 with the diff when stale) and
  `--write` (update the block). The test calls the renderer directly; CI/handoff uses `--check`.

## C.4 File-by-file

| file | change |
|---|---|
| `strength_coach/prescribe/summary.py` | renderer + digest; no personal data. |
| `tools/programme_summary.py` | `--check` / `--write`; prints the stale diff. |
| `docs/STRENGTH-PROGRAM-REVIEW.md` | generated block with markers; bench_hinge row and weekly table corrected; prose lines about the "single-leg RDL support" and "~5 heavy hinge" corrected; amendment note dated 2026-10-27. |
| `docs/CORE-TRAINING.md` | bench+hinge main work → bench + sumo 3×3–5. |
| `ROADMAP.md` §4.17 | table row and "hinge gets a second exposure" paragraph; spinal figures. |
| `docs/VOLUME-MANAGEMENT.md` | one later-amendment sentence pointing at `DEC-SPINE-05`; do not rewrite the 2026-10-20 note. |
| `docs/LIMITATIONS-REGISTER.md` | review `LIM-16`: annotate that the lift is no longer in a template but remains a drop-fill/selection candidate, or close only if the classification no longer has a user. |
| `tests/test_programme_summary.py` | renderer, doc block, stale-name guard. |
| `AGENTS.md` | already lists the plan; no new doc. |

## C.5 Tests

| file | case |
|---|---|
| `tests/test_programme_summary.py` | the renderer's bench_hinge row names the sumo, 3×3–5, cost 2.5, and no single-leg RDL; weekly totals are 57 sets and a 5.5 spinal week for bench+hinge. |
| `tests/test_programme_summary.py` | the review's generated block equals the renderer output (stable digest); a config change without regeneration fails. |
| `tests/test_programme_summary.py` | "single-leg RDL" / `single_leg_db_rdl` is absent from the current-state programme sections of the review, ROADMAP and CORE-TRAINING. |
| `tests/test_spinal_cap.py` | unchanged: the template uses the sumo. It is the code contract the docs must follow. |
| `tests/test_docs_consistency.py` | links and ids still resolve. |

## C.6 Commit sequence

1. **Renderer + tests.** The doc test fails until step 2; run it deliberately.
2. **Review doc.** Insert the markers and generated block; correct the bench_hinge and weekly
   tables and the two prose claims; add the amendment note.
3. **Dependent current-state docs.** ROADMAP, CORE-TRAINING, VOLUME-MANAGEMENT note, LIM-16
   review; stale-name guard green.

## C.7 Risks

- **Rewriting history.** Do not edit W8's dated audit, W9's historical analysis or any `DEC-` row.
  Add amendment notes instead. The only current-state docs are corrected.
- **Prose drift.** The generated block covers tables; the stale-name test covers the specific
  rename. A future prose change that contradicts the table is still a review problem — the plan
  does not pretend to generate prose.
- **Arithmetic drift.** The generator must reuse the existing set/spinal functions; the 57-set and
  5.5-cost assertions catch a second implementation.
- **The review is marked CLOSED 2026-10-20.** This is an amendment/reconciliation, not a reopening
  of its evidence conclusions. Say so in the note.
- **`single_leg_db_rdl` remains in the taxonomy and drop-fill pool.** The docs must say "not in the
  current template", not "deleted".

---

# Part D — Same-date accounting

## D.1 Finding and agreement

The finding is correct, and the defect is broader than the MRV cap. In all three places the
"completed" baseline includes the prescription date, and the proposed items are added on top:

- `engine._apply_volume_cap`: `cutoff = for_date - 7 days`, `prior = context.sets` filtered
  `date > cutoff` and `date <= for_date`; `total = prior_counts + proposed`. A session recorded on
  `for_date` is in `prior`, and the new plan is added again.
- `_week_spinal`: `registry.weekly_spinal_costs(rule, context, proposed)` counts the performed
  exposures in `context.sets` (with their own session ids) **and** the proposed session under the
  `for_date` id. The same-date session and the plan both count.
- `volume_budget.apply`: `report` computes `completed_sets(include_today=today_done)`, which
  includes today's sets; `allocate_items` then receives the proposed rows and the same `completed`
  map. The `report` alone has a `today_done` branch that stops projecting a second today session,
  but `apply` bypasses it. Passing `projected_items` into `report` is a second path into the same
  double count.

There is no guard in `build_prescription`, the CLI `run` path or the API against a date that already
has a session, so this is reachable, not hypothetical. It is latent because it only appears when a
plan is rebuilt for a date with recorded work.

**Agreement, with a change of scope:** the finding names MRV. I would fix the whole same-date
accounting class — MRV, the spinal cap and the weekly budget application — with one baseline rule,
not patch MRV alone and leave the other two inconsistent. The recommendation's test is necessary
but not sufficient; the code needs the rule.

## D.2 Decision (recommended)

**One planned session per date.** A prescription is the plan for its date. If a session is already
recorded on that date, a newly built prescription is a **revision**:

- the date's recorded sets are **excluded** from the completed baseline for MRV, the spinal cap and
  the weekly budget;
- the proposed plan is counted **once**, as the date's plan;
- the prescription carries `notes["same_date_session"]` (session id(s) and type) and a warning that
  the date already has recorded work and the plan is being accounted as a replacement.

Refusal is the alternative: reject a new plan for a date with a recorded session and tell the user
to void or review it. I recommend against making that the default — rebuilding a plan after a
readiness or selection change is a legitimate action, and the stored session is already the record
of what happened. If strictness is preferred, a refusal guard is a one-line change and should be
recorded as the chosen semantic instead.

This assumes a date is one planned session. Two-a-days are out of scope; if two sessions share a
date, the plan treats them as that date's recorded work and a genuine second session would be
undercounted. `ASSUMPTION-38` already records that a session is one calendar date, so no new
assumption is added. `DEC-VOLUME-30` records the revision semantic. No constitution change:
`PRG-SPINE-001`'s treatment of performed work is unchanged; only the proposed-session projection
uses the prior view.

## D.3 Design

- Add `RuleContext.prior_to(for_date)`: a frozen copy with `sets` and `sessions` filtered to
  **strictly before** `for_date`. No mutation; the full context stays available for e1RM, recent
  stress, injury, readiness and the policy verdicts on performed work.
- Use the prior view in `_apply_volume_cap`, `_week_spinal`, `_apply_spinal_trim` and the spinal
  check in `validate_prescription` (including `notes["spinal_cap"]`). One helper, not four date
  filters.
- `volume_budget.report` gains an explicit revision mode: when a session exists on the plan date,
  `completed` is computed with `include_today=False`, the proposed items occupy the date's session
  slot, and the future projection starts from that. `apply` passes the same `completed` map to
  `allocate_items`, so `report` and `apply` cannot disagree.
- `build_prescription` queries the date's sessions once and adds the note/warning. The note is
  generation output; if the stored prescription has no notes column, it is a warning like the
  others and does not need a schema change. Do not silently drop it.
- Do **not** change `context.sets` itself: the same-date session is real data for e1RM, stress,
  injury and the performed-work policy. Only the proposed-plan projection is revised.
- No new arithmetic: the revision uses the same `completed_sets`, `projection`, `allocate_items` and
  `weekly_spinal_costs` functions with a different baseline.

## D.4 File-by-file

| file | change |
|---|---|
| `strength_coach/rules/context.py` | `RuleContext.prior_to(for_date)`. |
| `strength_coach/prescribe/engine.py` | MRV/spinal/validate use the prior view; add the same-date session note and warning. |
| `strength_coach/prescribe/volume_budget.py` | `report` revision mode; `apply` uses the same completed map; tests. |
| `tests/test_same_date_accounting.py` | new file, see D.5. |
| `docs/DECISIONS.md` | `DEC-VOLUME-30` is recorded; do not edit old rows. |
| `docs/LIMITATIONS-REGISTER.md` | no new row needed: `ASSUMPTION-38` covers one session per date, and two-a-days are out of scope. |
| `CHANGELOG.md`, `ROADMAP.md` | entry and status row. |

## D.5 Tests

| case | assertion |
|---|---|
| MRV, same-date session | build with a pattern close to MRV, record a session on the date, rebuild: no double-count trim; the final sets equal the plan, not the plan-plus-session |
| MRV, earlier-date session | a session on an earlier day still counts; the fix does not over-exclude |
| MRV, no session on the date | unchanged from today |
| spinal cap, same-date session | week cost excludes the date's recorded exposure and includes the proposed one once; at the boundary executable, over the boundary the expected issue |
| budget, same-date session | `report`'s completed/projection and `apply`'s allocation both exclude the date's completed sets; the two agree; no double trim/top-up |
| budget, no same-date session | unchanged |
| note/warning | present only when a session exists on the plan date; names the session(s) |
| forecast path | `projected_items` for earlier projected sessions is unaffected; the revision mode is only for a recorded same-date session |

## D.6 Commit sequence

1. **Context helper + MRV/spinal.** `prior_to`, the three consumers, tests; the budget path is still
   unchanged and its test is marked as the next step.
2. **Budget.** `report` revision mode and `apply`; `report`/`apply` agreement tests.
3. **Decision and records.** Decision row, assumption, docs, CHANGELOG, ROADMAP.

## D.7 Risks and out of scope

- **Two-a-days.** The one-session-per-date assumption is explicit; a genuine second session on the
  same date would be undercounted. If two-a-days become real, the date model needs a session
  identifier and a separate decision.
- **A recorded same-date session is not necessarily the planned one.** The revision semantic treats
  it as the date's work; refusal is the alternative. Do not silently pick per call site.
- **Performed-work policy is untouched.** The policy verdicts, e1RM, recent stress and injury still
  see the recorded session; only the proposed week accounting excludes it.
- **The budget is optional.** Its revision mode is still required for consistency; the normal
  no-session path is unchanged and tested.
- **Out of scope:** multiple plans per date, cross-date debt, and changing the MRV/spinal
  thresholds. This is an accounting fix, not a cap change.
- **Drop and under-MEV same-date paths.** Resolved 2026-10-27 by `DEC-VOLUME-32`:
  `_apply_under_mev` uses the prior view and `plan_drop` supplies the template as the revision
  plan when the date already has a session. Tests are in `tests/test_same_date_accounting.py`.

---

# Part E — Adversarial audit and verification

## E.1 What the brief gets right

The brief is a good audit contract: it asks for evidence rather than assertion, separates confirmed
defects from plausible risks, requires a reproduction and severity per finding, forbids personal data
in fixtures and reports, prefers narrow fixes and regression tests over refactors, and insists that
the final prescription — not a warning — is what gets asserted. Its closing honesty is right too: a
static review cannot establish training safety or medical validity.

I would adopt almost all of its discipline. I would not adopt it literally, for the reasons below.

## E.2 What I changed, and why

1. **The premise is false on the current branch.** The five previous issues are **not fixed**. The
   working tree contains decision rows (`DEC-SPINE-07`, `DEC-POWER-02`, `DEC-VOLUME-30`), a
   limitation row (`LIM-53`) and this plan;
   the sumo is still `essential: false`, power still carries `rir: 4-5`, the review still says
   single-leg RDL, the same-date double count is still in the code, and the interaction tests do not
   exist. An audit run today would "confirm" five open findings and add no information. **E is a
   post-implementation gate.** If a current-state audit is wanted first, it must exclude the five
   known-pending fixes and say so on its first page.
2. **The scope is a programme, not a pass.** Seven areas across the whole application plus
   remediation is weeks of work and would produce shallow coverage. E is risk-based: the changed
   surfaces and the invariants they can break are Tier 1; high-risk existing behaviour is Tier 2;
   the rest is a spot-check or explicitly unaudited. The report names what was not audited.
3. **"Do not stop after a report" versus the approval rule.** The audit may implement **non-behavioural**
   confirmed fixes (a wrong display, a missing test, a leaked traceback). Any change to a
   prescription, threshold, rule, template or programme policy still needs the owner's explicit
   approval, as the brief's own rule 10 says. The two rules are reconciled by making behaviour
   changes a **finding + proposal**, not an autonomous fix.
4. **"Avoid database migrations" is a default, not a veto.** Part B needs a migration to persist
   `effort_model` and `quality_stop`; without it the stored prescription loses the quality model,
   which is the defect. E should not add *unnecessary* migrations; it must not block a necessary one.
5. **No browser or property framework.** The repository has no browser test suite and no Hypothesis;
   adding one would be a new dependency and a new failure surface. E uses HTTP-level integration
   tests plus a manual browser check where the server is running, and states the limitation. The
   invariants use table-driven and seeded `random` tests in plain pytest, not a new library.
6. **The local checkout is the source, not "GitHub main".** Pin the audit to the commit that contains
   A–D, record the SHA, and audit a clean tree; the current uncommitted docs are not on `main`. Do not
   fetch or assume a remote state.
7. **"Reportedly fixed" is not evidence.** E verifies behaviour with tests and a reproducible path,
   not changed lines. That is the brief's own rule; it is the reason E exists after A–D rather than
   before.
8. **Keep the brief's honesty.** No manufactured findings, "pass" is an allowed result, and the
   report separates confirmed defects from plausible risks, design trade-offs and unverified areas.

## E.3 Preconditions and gate

Run E only when:

- A, B, C and D are implemented and merged, with their decisions (`DEC-SPINE-07`,
  `DEC-POWER-02`, `DEC-VOLUME-30`) in force;
- the five-fix regression tests exist and pass;
- the working tree is clean and the audit commit SHA is recorded;
- the full public suite is green as the baseline.

If any precondition is missing, stop and report which one; do not audit a half-applied change.

**Current baseline (2026-10-27, pre-implementation, working tree includes the plan and decision
docs):** `.venv/bin/python -m pytest -q` exited 0; **887 tests collected** (872 public plus the 15
private integration tests, per `ROADMAP.md`); `tests/test_docs_consistency.py` → 9 passed. This is
the starting point, not the audit baseline: E re-runs the same commands on the fixed commit and
records both, with the environment and exit codes.

## E.4 Risk-based scope

| tier | scope | why |
|---|---|---|
| **T1 — changed surfaces** | the five fixes: flare policy/load re-solve, quality-limited power (model, persistence, API, UI, analytics), generated docs, same-date accounting, the interaction matrix | these are the changes most likely to have introduced a defect, and the previous audit's claims must be verified behaviourally |
| **T2 — invariants around them** | final-prescription executability; load arithmetic and rounding; safety caps (spinal, MRV, MRV/budget); citation/provenance accuracy; no double counting; failed-write atomicity; read purity | the brief's highest-value invariants; a violation is material even if the changed code is small |
| **T3 — spot checks** | import idempotency and legitimate repeated sets; API→JS value path; malformed config/payload; SQLite lock/transaction; timezone-sensitive tests; LLM unavailable/malformed; stale e1RM and missing-load paths | broad areas where a cheap check can find a material defect, without auditing every branch |
| **not audited** | full architecture, commercial scalability, hosted UI, video, cardio depth, medical validation, performance tuning | out of scope for a personal local tool and not changed by this plan |

## E.5 Stages

### Stage A — Reconnaissance

- Re-read the five fixes against `DEC-SPINE-07`, the power decision, the docs generator and the
  same-date decision; map each to its code path and test.
- Produce a prioritised suspicion list with file/line evidence. No changes in this stage.
- Check the existing tests for the false-confidence patterns the brief names: order/date/timezone
  dependence, golden tests that assert only the fixture, missing regression tests, fixtures that
  hide missing-load or unknown-exercise paths.

### Stage B — Baseline and reproduction

- Run `.venv/bin/python -m pytest -q`, the fast lane, and `tests/test_docs_consistency.py`; record
  the command, Python/pytest versions, exit code and the count. Run the date-sensitive tests once
  with a non-local `TZ` (e.g. `TZ=America/New_York`) to expose machine-local assumptions.
- Ruff is configured (`pyproject.toml` `[tool.ruff]`, line length 110, `select = ["E", "F", "I",
  "UP", "B", "SIM"]`) but **not installed in `.venv`**; run `.venv/bin/ruff check .` if it becomes
  available, otherwise record "not run — not installed" and do not add the dependency. No mypy or
  other type check is configured.
- For each suspected defect, add the smallest failing test first. For the five fixes, add the
  behavioural assertions even if they pass — they are the regression contract.
- Record the baseline before fixing anything.

### Stage C — Remediation

- Fix only confirmed, material defects. Each fix is a separate small commit with its regression
  test. Preserve the architecture; no speculative refactor.
- Behaviour changes are **not** applied here: write the finding, the proposed correction, the
  behavioural difference and the approval request. Non-behavioural fixes may be applied.
- No new dependency, no unnecessary migration, no personal data in fixtures/logs/reports.

### Stage D — Verification

- Re-run the full suite, the fast lane, the docs consistency test and the `TZ` run; compare with the
  baseline and record the exit codes.
- Inspect the final diff for unintended behaviour changes; check that every "fixed" finding has a
  regression test that fails on the pre-fix commit.
- Produce the report and update the plan with what remains open.

## E.6 Five-fix verification matrix

| # | fix | behaviour to verify | test |
|---|---|---|---|
| 1 | back-flare scope | sumo essential; flare holds RIR and re-solves the load; direct-erector dose is a ceiling (`min(current, 3)`) and a readiness cut survives; citation only on change; DUP week 3; no false provenance | `tests/test_symptom.py`, `tests/test_back_flare_interactions.py` |
| 2 | power work | box jump has no RIR target; `effort_model=quality`, stored stop rule; API/UI/CLI show the stop rule; RIR analytics exclude it; legacy rows still read | `tests/test_prescribe.py`, `tests/test_web.py`, `tests/test_derived.py`, `tests/test_store.py` |
| 3 | programme docs | generated block matches config; sumo/3×3–5/2.5 in the review; no stale single-leg RDL in current-state docs | `tests/test_programme_summary.py`, `tests/test_docs_consistency.py` |
| 4 | same-date accounting | a session on the plan date is not counted as completed **and** proposed in MRV, spinal or the budget; revision note/warning; earlier dates still count | `tests/test_same_date_accounting.py` |
| 5 | interaction tests | the final prescription for flare+readiness, +gap, +deload, +spinal, +DUP; not warning-only | `tests/test_back_flare_interactions.py` |

## E.7 Invariants

Use table-driven or seeded tests; no new dependency. Adapt the brief's list to this app:

- no prescribed external load is negative; bodyweight `0` is valid and not a missing value;
- an external load is a multiple of its configured increment, and is rounded down;
- `load_kg is None` with an `unknown_load_reason` is never executable and is never shown as a number;
- a safety cap (spinal, MRV) is never exceeded silently: either the plan is within it or an issue
  names the exposure;
- a substitution preserves the slot's essential flag, RIR/quality model, pattern and load basis;
- a repeated read (prescription preview, budget report, history) does not mutate state;
- a failed write leaves no partial row (transaction boundary);
- a failed or incomplete API response is not rendered as a successful prescription;
- a quality item has no numeric RIR anywhere in the API/UI.

Do not impose these on valid exceptions: bodyweight work, a `None` load that is genuinely unknown,
and advisory-only warnings are not violations.

## E.8 Findings and report

Every confirmed finding gets: severity, file/line, workflow, reproduction (test or path), impact,
resolution status. Severity: **S1** wrong prescription/executability, safety-cap breach, data loss or
corruption; **S2** material user-visible wrong number/state; **S3** documentation or test gap.

The report is `docs/AUDIT-FOLLOW-UP-REPORT.md` (created at Stage D and added to the `AGENTS.md` map):

1. executive verdict and qualifications;
2. findings table (severity, evidence, reproduction, impact, status);
3. changes made, file by file;
4. tests: exact commands, environment, exit codes, results;
5. unverified areas and why;
6. residual risks;
7. recommended next actions, only with expected value.

A pass is a valid result; do not manufacture findings. The report must not use personal workout data.

## E.9 Exit criteria

- The five fixes are behaviourally verified, not merely present in the diff.
- No open S1 or S2 finding; every fixed finding has a regression test that fails on the pre-fix
  commit.
- The full suite, the fast lane and the docs consistency test pass; the `TZ` run passes or its
  failure is recorded as a finding.
- The report has an explicit unverified-areas section and a residual-risk list.
- The current-state limitations (no browser suite, ruff configured but not installed, no type check,
  single-user SQLite) are stated,
  not glossed.

## E.10 What I would not do

- Audit all seven areas exhaustively in one pass and call it complete.
- Add Playwright, Selenium, Hypothesis or a lint stack just to satisfy the brief.
- Rewrite the schema, the persistence layer or the engine architecture because an audit template
  suggests it.
- Change a training rule, threshold or template without the owner's explicit approval.
- Use the real database or workout exports in fixtures, logs, screenshots or the report.
- Claim medical validation or training safety from a static review.

---

# F. Sequencing across parts

1. **Part C** first: docs-only, no decision, and it removes the stale numbers before the code
   changes make more docs stale.
2. **Part A** next: decided, and its template change (sumo essential) sets the current spinal and
   volume numbers that D's tests should run against.
3. **Part D** next: the accounting defect is small and isolated, but it touches `engine.py` and
   `volume_budget.py`, which A also touches. Doing it after A means D's spinal test runs on the
   final template. Decided: `DEC-VOLUME-30` (revision).
4. **Part B** last: it is the largest change; decided `DEC-POWER-02`. It touches `models.py`,
   `engine.py`, `persistence.py`, `web/server.py`, `app.js` and `cli.py`, which A and D also touch.
   Sequence A → D → B; do not run them in parallel on the same files.
5. **Part E** only after A–D are merged and the tree is clean: pin the commit, run the baseline,
   reproduce, fix confirmed non-behavioural defects, verify the five fixes behaviourally, and
   produce `docs/AUDIT-FOLLOW-UP-REPORT.md`. If E runs earlier it will report the five fixes as
   open; that is not a useful result.

Each part ends with the full suite and a deliberate golden-fixture review. Part A also closes
`LIM-53`; Part B and D are decided (`DEC-POWER-02`, `DEC-VOLUME-30`); Part C adds the generator and
the docs guard; Part E adds the behavioural verification and the report. `ROADMAP.md` gets one
status row per part, and the public test count is updated once at the end.
