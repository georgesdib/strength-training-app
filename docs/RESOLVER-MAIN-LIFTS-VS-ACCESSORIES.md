# Resolver — main lifts vs accessories

**Status:** canonical implementation reference for the production resolver's joint search and
for the distinction between main lifts, support lifts and accessories.
**Code:** `strength_coach/prescribe/resolver.py` (orchestration),
`strength_coach/prescribe/generator.py` (eligibility and candidate pools),
`strength_coach/prescribe/beam.py` (bounded search),
`strength_coach/prescribe/evaluator.py` (prescription evaluation).
**Policy:** `config/template-resolver.v1.yaml`, `config/variants.v1.yaml`,
`config/templates/session-types.v1.yaml`.
**Settings:** Settings → Resolver and Settings profile (group Resolver).
**Companion:** [RESOLVER-ALGORITHM.md](RESOLVER-ALGORITHM.md) documents the standalone generator's
step-by-step ranking. This document explains the production joint resolver and what changes when
a slot is a main lift, a support lift or an accessory.

The resolver is a deterministic, policy-driven exercise selector. It does not choose the
highest-scoring exercise independently for every slot. It builds eligible candidate pools,
searches combinations across the whole session, runs the real prescription pipeline on each
finalist, and returns the best feasible complete session.

That is a joint optimisation problem, not a collection of independent recommendations. The
implementation separates three responsibilities:

| Responsibility | Owner | Question answered |
|---|---|---|
| Blueprint | session template and resolver policy | What is this session supposed to accomplish? |
| Candidate eligibility | generator | Which exercises may fill each slot? |
| Joint selection | beam and evaluator | Which complete combination makes the best executable prescription? |

The resolver is optional and off by default. When it is disabled, the fixed-template
prescription path is unchanged. The resolver selects exercises only; loads, reps, RIR, top sets
and volume modifiers remain the prescription engine's job.

## 1. Scope and contract

The production resolver answers one question: **which eligible exercise fills each slot of one
session type on one date?** It never invents an exercise, changes the session type or writes to
the store. It reads the policy, templates, athlete history and current state, and returns a
complete assignment plus provenance and diagnostics.

| Input | Source |
|---|---|
| `for_date` | caller |
| `session_type` | caller; one of `squat`, `hinge`, `bench_squat`, `bench_hinge` |
| Session blueprint and slot requirements | `config/templates/session-types.v1.yaml` |
| Structural policy and candidate pools | `config/template-resolver.v1.yaml`, `config/variants.v1.yaml` |
| Scalar settings | effective-dated settings profile plus registry defaults |
| Readiness, injury signal and recent stress | features layer |
| Exercise suitability | `exercise_suitability`, latest row per exercise |
| Dwell counters | `exercise_dwell_state` |
| Training history | clean sets strictly before `for_date` |

The output is a real `Prescription`, not just an exercise list. The resolver also records the
winning assignment, candidate pools, beam diagnostics, evaluator components, template/policy/
catalogue digests and an input fingerprint.

## 2. Session types and slot roles

Each session type is loaded as a `SessionTemplate`. A template contains ordered slots. Each
slot supplies its exercise or variants, sets, rep range, RIR range, rest, essential/power flags
and load source. The resolver chooses *which* exercise fills a slot; it does not re-derive the
slot's set or rep prescription.

The template does not store a movement pattern. The pattern is looked up in the exercise
taxonomy for the slot's default exercise or candidate exercises. The resolver derives three
working roles from the template and taxonomy:

| Role | Identification | Movement-pattern freedom |
|---|---|---|
| Primary main lift | The slot containing `template.primary_exercise` | Restricted to the main slot's pattern family |
| Secondary/support lift | Any other essential, non-power slot | Restricted to its blueprint pattern family |
| Accessory | Non-essential, non-power slot | Policy-authorised alternatives; otherwise its blueprint patterns |
| Power | `power: true` | Fixed exercise; never substituted |

This distinction is functional, not a statement about how many sets a slot has. An accessory is
not merely a less important main lift: it has a different, explicitly bounded degree of
movement-pattern freedom.

`_permitted_patterns()` implements the rule:

- **Main:** the patterns of the template's primary-lift slot.
- **Secondary/support:** the patterns of that slot's blueprint exercise or variants.
- **Accessory:** `allowed_patterns[slot.id]` when the policy defines them; otherwise the slot's
  blueprint patterns.
- **Power:** fixed identity plus the same hard eligibility checks as every other slot.

The four canonical session types and their primary lifts are:

| Session type | Primary lift | Role of the other strength work |
|---|---|---|
| `squat` | SSB squat | Bench support |
| `hinge` | Trap-bar deadlift | Bench support |
| `bench_squat` | Bench press | Competition-squat support |
| `bench_hinge` | Bench press | Sumo or trap-bar hinge support |

A main lift cannot become a leg press or a shoulder press merely because that alternative scores
better. The resolver may rotate within the lift family and may choose a configured variant, but
it cannot change the session's structural identity.

Accessories have the useful flexibility. The current policy allows:

| Accessory slot | Permitted patterns |
|---|---|
| Accessory row | Horizontal pull, vertical pull, rear-delt pull |
| Accessory pull-up | Vertical pull, horizontal pull, lat isolation |
| Accessory vertical press | Vertical push, horizontal push |
| Accessory knee flexion | Knee flexion, hamstring eccentric |
| Erector | Erector extension |
| Core anti-extension | Core anti-extension, core stability |
| Core flexion | Core flexion, core stability |
| Accessory split squat | Unilateral squat |

For example, an accessory-row slot can supply horizontal or vertical pulling depending on what
the rest of the session and the week need. The main lift cannot make that trade. Accessories are
still limited to the patterns authorised for their slot; the freedom is explicit, not arbitrary.

## 3. Candidate pools

A slot's raw pool comes from one of three sources, in precedence order:

1. **Fixed power slot:** the slot's blueprint exercise, never substituted.
2. **Explicit policy pool:** `slot_pools[session_type][slot.id]` replaces the ordinary pool.
3. **Template plus catalogue:** the template's exercise or variants, followed by catalogue
   additions for that session/slot, de-duplicated in order.

The policy uses an explicit hinge-main pool because the catalogue has no hinge-main entry that
covers the accepted main-lift variants:

```yaml
slot_pools:
  hinge:
    hinge_main:
      - trap_bar_deadlift
      - sumo_deadlift
      - deadlift_w_bands
      - deadlift_w_chains
      - deadlift_w_chains_off_blocks
      - deficit_deadlift_w_chains
```

`bench_hinge/hinge_support` similarly has an explicit pool: sumo first, then trap bar. The pool
is the entire search space. Nothing outside it can be prescribed by the resolver.

Candidate-pool order is deterministic. It is the template-plus-catalogue order, with any policy
pool order taking precedence. In the production path that order is **not** an exercise-quality
ranking; it is used only as a deterministic computational ordering and tie-break cost by the
beam.

## 4. Hard eligibility and suitability

Before any combination search, every candidate is classified as **auto**, **suggestion** or
**excluded**. The filters run in this order:

1. **Movement pattern.** The exercise's taxonomy pattern must be in the slot's permitted set.
2. **Stored constraints.** `constraints.evaluate()` vetoes exercises with hard stored
   contraindications. These are vetoes, not preferences.
3. **Active injury links.** Exercises linked to an actively affected region are excluded.
4. **Suitability.** The athlete's latest rating for the exercise determines whether it may be
   selected automatically.

The suitability rules are:

| State | Classification |
|---|---|
| No rating, `require_can_do=true`, `unrated_mode=confirm` | Suggestion only |
| No rating, `require_can_do=true`, `unrated_mode=exclude` | Excluded |
| No rating, `require_can_do=false` | Auto |
| `can_do=false` | Excluded |
| `will_do=false` | Suggestion if `will_do_blocks`; otherwise excluded |
| `feels_bad=true` | Suggestion if `feels_bad_blocks`; otherwise excluded |
| Otherwise | Auto |

`will_do=false` and `feels_bad=true` are never automatic, even when they remain visible as
suggestions. If a slot has no automatic candidate but has unrated suggestions, those suggestions
are carried into the preview so the athlete can rate one; the selection remains pending and
Start is gated. Rated preference blocks stay suggestion-only and are not promoted into the
automatic pool. If a slot has no eligible candidate at all, generation fails field-level rather
than falling back to the blueprint.

A power slot is special only in being fixed. It is still checked against the same eligibility
rules. If its fixed exercise is vetoed, injured or unsuitable, generation fails; power work is
never silently substituted.

## 5. Dwell filtering

The resolver reads one completed-exposure counter per exercise. A candidate at or above the
configured **dwell target** is removed from automatic selection:

```text
candidate_count < resolver.dwell.target
```

The dwell target is a cap, not a rotation schedule. Normal completion wraps the counter to zero
at the target, so a candidate is rarely at the cap. If every candidate is at or above the
target, the pool is retained and a warning is recorded rather than making the slot impossible.

The production path applies dwell eligibility as a pool filter. It does **not** apply the
standalone generator's dwell score or exploration draw when ordering pools. The full exposure
model, including `f(c) = 1 - exp(-c / tau)` and the seeded exploration draw, is in
[DWELL-AND-ROTATION.md](DWELL-AND-ROTATION.md).

## 6. Required patterns and structural feasibility

Each session type declares required movement patterns in the policy:

| Session | Required patterns |
|---|---|
| `squat` | Squat, horizontal push, horizontal pull, erector extension, knee flexion, core anti-extension |
| `hinge` | Hinge, horizontal push, vertical pull, horizontal pull, unilateral squat, knee flexion |
| `bench_squat` | Horizontal push, squat, horizontal pull, vertical push, core anti-extension |
| `bench_hinge` | Horizontal push, hinge, vertical pull, horizontal pull, vertical push, core flexion |

Required patterns are constraints on the final assignment, not recommendations. Distinct slots
must cover them: one slot cannot satisfy both horizontal pull and vertical pull merely because
its candidate pool contains both patterns. The generator uses a deterministic bipartite match
to check that the pools can cover every requirement with distinct slots.

For matching, taxonomy patterns are mapped to volume-ledger keys. In particular,
`squat_unilateral` joins `squat`, and `hamstring_eccentric` joins `knee_flexion`. The mapping is
defined once in `features/volume.py::volume_target_key()`.

The policy also defines redundancy limits:

```yaml
redundancy:
  max_per_pattern: 2
  max_per_primary_muscle: 2
```

These limits belong to the standalone generator's individual score. The production beam does
not apply a separate redundancy penalty. Its protection against over-concentration comes from
the structural requirements and from evaluating the actual post-pipeline volume, spinal and
session outcome.

## 7. Two generator modes

The generator has two distinct operating modes. Confusing them is the easiest way to misread
the resolver.

| Concern | `generate()` — standalone | `candidate_pools()` + beam + evaluator — production |
|---|---|---|
| Builds eligible pools | Yes | Yes |
| Applies hard eligibility, suitability and dwell cap | Yes | Yes |
| Uses the individual readiness/fatigue/spinal/injury/dwell score | Yes | No |
| Applies the rotation/exploration draw to candidate order | Yes | No |
| Searches complete slot combinations | No | Yes |
| Runs the real prescription pipeline on finalists | No | Yes |
| Chooses by post-pipeline feasibility and score | No | Yes |

The production resolver calls `candidate_pools()`. It does not call `generate()` and take its
greedy choices. The individual scoring function still exists as the standalone diagnostic
model, but applying it again in production would double-count an exercise-level objective before
the complete prescription is evaluated.

The standalone score is:

```text
weighted = sum(w_k * v_k) / sum(w_k)     over readiness, fatigue, spinal, injury, dwell
score    = clamp(weighted + coverage_factor * (coverage - 0.5) - redundancy)
```

That formula is documented in [RESOLVER-ALGORITHM.md](RESOLVER-ALGORITHM.md). It is not the
production assignment objective.

## 8. Bounded beam search

`resolver.build_resolved()` passes the candidate pools to `beam.search()`. The search is
deterministic and bounded.

| Parameter | Default | Configurable |
|---|---:|---|
| Beam width | 4 | No in production |
| Maximum candidates per slot | 6 | No in production |
| Full-evaluation budget | 4 | Yes: `resolver.full_evaluations`, 1–4 |

### 8.1 Candidate truncation

Each slot is reduced to its first six eligible candidates. The beam preserves candidates needed
to cover required movement patterns even when they appear beyond the first six. It then checks
that the capped pools can still satisfy all required patterns; if they cannot, the search fails
loudly rather than dropping a requirement.

### 8.2 Expansion and structural pruning

The search starts from one empty partial assignment and processes slots in template order. Every
partial assignment is expanded with each candidate in that slot's capped pool. After each
expansion, branches that can no longer cover the outstanding required patterns with the
remaining slots are discarded immediately.

This is a cheap structural filter; it is not a prescription evaluation. No load, volume, spinal
or duration outcome is scored at this stage.

### 8.3 Beam-width pruning

Surviving partial assignments are sorted by a deterministic ordering cost:

```text
C(A) = sum(rank_j)
```

where `rank_j` is the candidate's position in its capped slot pool, starting at zero. Ties are
broken by:

1. lowest total candidate rank;
2. lexicographically lowest rank tuple;
3. assignment tuple.

Only the best four partial assignments survive at each step. This ordering is a computational
heuristic, not an exercise-quality score, and it does not yet know the final prescription's
loads, volume, spinal exposure or duration.

### 8.4 Full evaluation

Once every slot has been assigned, at most four finalists remain. Up to the configured
full-evaluation budget (default four, configurable 1–4) are passed to the evaluator. The beam
records:

- assignments evaluated;
- partial assignments pruned by beam width;
- structural dead ends;
- candidates removed by the per-slot cap;
- finalists removed by the evaluation budget;
- whether the search was exhaustive.

The beam is approximate. A combination can be pruned before the full evaluator sees it, so the
winner is the best feasible prescription found within the bounded search, not a proof of global
optimality.

## 9. Full prescription evaluation

Every finalist is passed to `evaluator.evaluate_assignment()`. The evaluator builds a concrete
template from the selected exercises and invokes the existing `build_prescription()` pipeline
with `use_resolver=False`. It does not create a second prescription engine.

The assignment is protected:

- every slot must have exactly one selected exercise;
- every selected exercise must belong to that slot's eligible pool;
- no missing or unknown slots are permitted;
- resolver substitution and selection overrides are disabled;
- the normal engine runs once, read-only, with the shared history snapshot.

The engine therefore applies the real downstream rules to each finalist:

| Stage | What the evaluator sees |
|---|---|
| Readiness | Load/RIR reductions and any configured set reductions |
| Continuity and progression | Existing progression, e1RM selection and gap handling |
| Deload | The established deload decision, not a resolver invention |
| Top set/back-off | Eligible primary main lift only; total working sets preserved |
| Spinal exposure | Weekly cost and the authoritative cap |
| Volume budget | Actual post-budget group distribution |
| Session duration | Estimated minutes against the planned target |
| Validation and constraints | The normal issue list and constraint report |

The evaluator returns components, warnings, unknown-load count and a score. Hard feasibility is
separate from that score.

### 9.1 Hard feasibility

An assignment is feasible only when all of these are true:

- the prescription is executable;
- it has no validation or constraint issues;
- the weekly spinal cap is not exceeded;
- the exact assigned exercise list is preserved;
- the session type is not replaced;
- the required movement patterns are satisfied.

Time overruns, volume-target deviation and warnings are soft objectives. They rank otherwise
feasible finalists but do not independently make an assignment infeasible.

### 9.2 Heuristic score

Lower is better. The current penalties are:

| Component | Penalty |
|---|---:|
| Validation/constraint issue | 10 per issue |
| Non-executable prescription | 2 |
| Unknown load | 2 per unknown load |
| Spinal cap exceeded | 3 |
| Session over planned duration | 1 + minutes over / 30 |
| Volume target error | 2 × normalised error |
| Prescription warning | 0.05 per warning |
| Session/template replaced | 5 |
| Structural violation | 10 |

The volume error is normalised over groups with positive targets:

```text
E_V = sum_g |after_g - target_g| / sum_g target_g
```

The weights order candidates; they are not calibrated physiological utilities.

### 9.3 Winner selection

Only feasible finalists compete:

```text
A* = arg min score(A) over feasible evaluated assignments A
```

Ties fall back to the beam rank tuple and then the assignment tuple. If no feasible finalist
exists, the resolver fails with diagnostic information about the best evaluated alternative. It
does not quietly use the original blueprint.

## 10. Final integrity and provenance

After the beam chooses a winner, `resolver.py` re-checks the production contract:

- required movement patterns are still satisfied;
- the prescription preserved the exact assigned exercises;
- the session type still matches the request;
- the generated-session snapshot validates;
- the deterministic input fingerprint can be built.

Failures raise a structured `ResolverBuildError` with one of these stages:

| Stage | Meaning |
|---|---|
| `dispatch` | resolver disabled, bad request or invalid minimum-session shape |
| `pool_generation` | candidate pools, eligibility or structural feasibility failed |
| `assignment_search` | the beam found no feasible assignment or could not complete |
| `prescription_evaluation` | the real engine failed while evaluating a finalist |
| `final_integrity` | the selected result failed the final production contract |

The winning result is stored with a generated-session snapshot containing:

- the chosen exercise per slot and original slot specifications;
- sets, rep range, RIR range, rest, essential/power flags and load source;
- quality-stop requirements;
- template, policy and catalogue digests;
- the input fingerprint and its version;
- candidate pools, beam configuration and beam diagnostics;
- evaluator components and the top-set note.

The fingerprint covers the material build/evaluation inputs, candidate pools and beam
configuration. It is an audit fingerprint, not a guarantee that the prescription can be
reconstructed from the fingerprint alone or that every unrelated historical database row was
captured.

## 11. Minimum sessions

A minimum session is not a normal session with exercises deleted afterwards. The resolver first
builds a reduced session shape from the requested duration and whether the main lift is retained.
It then generates candidate pools for that reduced template and runs the same beam and evaluator.

For a normal minimum session, a required pattern is retained when the retained slots can still
cover it. Patterns that belonged only to removed slots are recorded as omitted. Accessories-only
mode has no main-lift coverage contract, but its remaining slots still pass through the normal
eligibility, structural and evaluation rules.

## 12. Top sets

Top-set selection is separate from exercise selection. The resolver chooses the assignment
first, then the normal prescription engine decides whether a top-set/back-off structure is
appropriate.

Only explicitly eligible primary main lifts can receive it. The current policy lists selected
squat, deadlift and bench variants; accessories never receive a top set. The structure is also
conditional on the request and training context:

- deload and competition taper suppress it;
- the DUP main scheme determines the target RIR;
- the competition peak window can override the normal RIR;
- one top set plus back-off sets preserves the original total working-set count;
- a later set trim removes back-off sets before the protected top set.

The evidence is in [TOP-SET-BACKOFF-EVIDENCE.md](TOP-SET-BACKOFF-EVIDENCE.md). The set
arithmetic and fallbacks are implemented in `strength_coach/prescribe/top_set.py`; the resolver
records the resulting `top_set` note in its snapshot.

## 13. Main lift vs accessory — complete comparison

| Dimension | Primary main lift | Secondary/support lift | Accessory |
|---|---|---|---|
| Candidate source | Template/catalogue or explicit policy pool | Template/catalogue or explicit policy pool | Template/catalogue or explicit policy pool |
| Pattern flexibility | Restricted to the primary pattern family | Restricted to its support pattern family | Explicitly configurable by slot |
| Suitability filters | Yes | Yes | Yes |
| Injury exclusions | Yes | Yes | Yes |
| `can_do` requirement | Yes | Yes | Yes |
| `will_do` / `feels_bad` handling | Yes | Yes | Yes |
| Dwell filtering | Yes | Yes | Yes |
| Required-pattern coverage | Usually provides core coverage | Contributes coverage | Can fill missing patterns |
| Joint beam search | Yes | Yes | Yes |
| Full prescription evaluation | Yes | Yes | Yes |
| Progression continuity | Existing lift-specific mechanisms | Existing mechanisms | Existing mechanisms |
| Top set/back-off | Potentially eligible | No | No |

The important difference is structural freedom, not a different prescription engine. Every
exercise is subject to the same final pipeline.

## 14. Design rationale and limits

Three design decisions follow from the model:

1. **Main lifts preserve programme identity.** The main lift is not freely interchangeable with
   another exercise that trains similar muscles. Rotating within a lift family is allowed;
   replacing a squat with a leg press would change the training objective and invalidate
   progression history.
2. **Accessories distribute the training stimulus.** Their explicit pattern flexibility lets
   the resolver cover required patterns and respond to the week's volume distribution without
   changing the session identity.
3. **The actual prescription decides the winner.** An exercise is not selected because an
   individual heuristic calls it optimal. It is selected because its complete combination
   produces the best feasible result after readiness, progression, deload, spinal, volume and
   duration rules have run.

Known limits:

- The beam is approximate; a good combination can be pruned before full evaluation.
- The evaluator and beam weights are heuristic ordering weights, not calibrated utility
  estimates.
- Candidate-pool order and the dwell cap affect which combinations reach the evaluator.
- The resolver is disabled by default; enabling it changes exercise selection but not the
  authority of the prescription engine.

## Related

- **Algorithm:** [RESOLVER-ALGORITHM.md](RESOLVER-ALGORITHM.md) — the standalone generator's
  full scoring and failure modes.
- **Dwell model:** [DWELL-AND-ROTATION.md](DWELL-AND-ROTATION.md) — counters, factor,
  exploration probability and cap.
- **Session templates:** [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md) — slot fields and blueprint
  rules.
- **Variants:** [EXERCISE-VARIANTS.md](EXERCISE-VARIANTS.md) — how the candidate catalogue is
  configured.
- **Workout generation:** [WORKOUT-GENERATION.md](WORKOUT-GENERATION.md) — where resolver
  selection sits in the prescription pipeline.
- **Minimum sessions:** [MINIMUM-SESSION.md](MINIMUM-SESSION.md) — shape-before-search behaviour.
- **Top sets:** [TOP-SET-BACKOFF-EVIDENCE.md](TOP-SET-BACKOFF-EVIDENCE.md) — evidence and set
  arithmetic.
- **Decisions:** [DECISIONS.md](DECISIONS.md) — DEC-RESOLVER-01, -03, -06, -12, -14 and -15.
- **Roadmap:** [ROADMAP.md](../ROADMAP.md) — implementation status.
