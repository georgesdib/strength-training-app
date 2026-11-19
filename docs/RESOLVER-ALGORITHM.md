# Resolver algorithm — step by step

**Status:** canonical implementation reference for resolver exercise selection.
**Code:** strength_coach/prescribe/generator.py (entry point: generate).
**Model:** [DWELL-AND-ROTATION.md](DWELL-AND-ROTATION.md) explains the exposure-based preference and probabilistic exploration.
**Settings:** Settings -> Resolver and Settings profile (group Resolver).
**Production path:** [RESOLVER-MAIN-LIFTS-VS-ACCESSORIES.md](RESOLVER-MAIN-LIFTS-VS-ACCESSORIES.md)
documents the joint resolver used in production. This page documents the standalone generator
(`generate()`) whose individual score and rotation draw are diagnostic; production uses
`candidate_pools()` with the bounded beam and full prescription evaluator instead.

The selector is best described as **exposure-based preference with probabilistic exploration**:
the score carries a preference built from completed exposures, and a seeded draw occasionally
explores an alternative. The dwell target is a cap, not a rotation schedule.

This document walks the whole selection algorithm in the order the code runs it, with the
formulas it uses. It selects exercises only: loads, reps, RIR, top sets and volume modifiers
are the existing prescription engine's job and are not re-derived here.

## 1. Scope and contract

The resolver answers one question: **which eligible exercise fills each slot of one session
type on one date?** It never invents an exercise, never changes the session type, and never
writes to the store. It reads the policy, the template, the athlete's history and state, and
returns a complete assignment plus the reasons, the runners-up and the provenance digests.

Inputs:

| Input | Source |
|---|---|
| for_date | caller |
| session_type | caller (one of squat, hinge, bench_squat, bench_hinge) |
| structural policy | config/template-resolver.v1.yaml, config/variants.v1.yaml |
| session template | config/templates/session-types.v1.yaml |
| scalar settings | effective-dated settings profile + registry defaults |
| readiness, injury signal, recent stress | features |
| suitability ratings | exercise_suitability (latest row per exercise) |
| dwell counters | exercise_dwell_state (mutable cycle state) |
| training history | rules context: clean_set up to the day before for_date |

Outputs: a GeneratedSession with, per slot, the chosen exercise, its score, a human-readable
reason list, up to five ranked alternatives and whether a rating is still pending; plus the
template, warnings, suggestions and the policy/catalogue digests.

## 2. The pipeline at a glance

    1. load policy, template, catalogue, settings, context
    2. compute readiness, injury, recent stress, suitability, dwell counters
    3. build each slot's raw candidate pool (template + catalogue)
    4. apply hard eligibility (patterns, vetoes, injury, suitability)
    5. apply the dwell cap (count >= target is excluded, unless all are)
    6. per slot: fixed power slot, or an exploration draw
    7. per slot: score every remaining candidate
    8. per slot: pick the highest score, break ties deterministically
    9. repair any required movement pattern that the greedy pass missed
    10. validate the projected weekly spinal cost
    11. emit the assignment, reasons, alternatives and digests

Steps 6-8 run slot by slot in template order, so a later slot sees the earlier slots'
choices through the redundancy and coverage terms.

## 3. Step 0 — load the world

    policy   = ResolverPolicy.load()                       # structural YAML
    settings = ResolverSettings.load(conn, for_date)       # profile + registry
    template = SessionTemplate.load(session_type)
    catalogue = load_candidate_catalogue(policy)           # variants.v1.yaml
    taxonomy = exercises.taxonomy().entities

The policy digest and the catalogue digest are computed now and returned with the session, so
the exact inputs can be reconstructed later (DEC-RESOLVER-12).

## 4. Step 1 — context, history and state

    context    = RuleContext.from_store(conn, end=for_date, ...)
    accounting = context.prior_to(for_date)                # strictly before the day
    assessment = readiness_score.compute(conn, for_date)
    injury     = injury_signal.compute(conn, for_date, ...)
    stress     = recent_stress.compute(context.sets, for_date, ...)
    suitability = queries.exercise_suitability(conn)       # latest rating per exercise
    dwell_counts = dwell.counts(conn)                      # {exercise_id: count}

Only work strictly before for_date is used for coverage; the day's own sets cannot influence
the plan that produced them.

## 5. Step 2 — candidate pools

A slot has either one fixed exercise or a list of variants. The pool is the template's own
list followed by the catalogue's additions, de-duplicated in order. A policy slot_pool
replaces the catalogue for that slot (used by the hinge main lift).

    def _candidate_ids(session_type, slot, policy, catalogue):
        if slot.power:
            return slot.exercises                  # fixed, never substituted
        explicit = policy.slot_pools.get(session_type, {}).get(slot.id)
        if explicit:
            return tuple(explicit)
        ids = list(slot.exercises)
        ids.extend(catalogue.get(session_type, {}).get(slot.id, ()))
        return tuple(dict.fromkeys(ids))

The pool is the search space. Nothing outside it can ever be prescribed by the resolver.

## 6. Step 3 — hard eligibility

Two filters run before any scoring:

    vetoes = constraints.evaluate(conn, all_candidates)     # constraints + injury links
    auto, suggestions = classify(pool, permitted, vetoes, ...)

classify returns one of three states per candidate:

    excluded   : not in the slot's permitted patterns, or vetoed, or an active injury link,
                 or can_do = 0, or (will_do = 0 / feels_bad = 1 with their block flags on)
    suggestion : unrated under require_can_do, or will_do = 0 / feels_bad = 1 while blocking
                 is on; shown for a rating but never auto-selected
    auto       : everything else

The suitability rules (DEC-RESOLVER-02 / DEC-RESOLVER-09) are:

    rating is None          -> require_can_do ? (unrated_mode == "confirm" ? suggestion
                                                                  : excluded) : auto
    rating.can_do  == False -> excluded
    rating.will_do == False -> will_do_blocks  ? suggestion : excluded
    rating.feels_bad == True-> feels_bad_blocks? suggestion : excluded
    otherwise               -> auto

If a slot has no auto candidate but has unrated suggestions, those suggestions are carried
into the preview as provisional candidates so the athlete can rate one (pending_rating stays
true and Start remains gated). If a slot has no candidate at all, generation fails with a
field-level error; there is no blueprint fallback that bypasses these rules.

## 7. Step 4 — the dwell cap

The per-exercise counter c (completed exposures in the current cycle) caps automatic
selection:

    if not slot.power:
        kept = [x for x in auto if counts.get(x, 0) < target]
        auto = kept if kept else auto          # all-over fallback keeps the pool
        warn if the fallback fired

Normal completions wrap the counter to 0 at the target, so a candidate is rarely at the cap
when a session is generated. The cap exists for a lowered target or an edited counter. If
every candidate is over, the generator still has to produce a session, so it keeps the pool
and warns.

## 8. Step 5 — the fixed power slot

A power slot is prescribed by intent and quality, not chosen by score. Its fixed exercise must
still pass eligibility; if it does not, generation fails rather than substituting:

    if slot.power:
        if default_state is not auto (or a suggestion for an unrated default):
            raise GenerationError(...)
        chosen = default_id
        score  = 1.0
        reasons = ("fixed power slot",)

## 9. Step 6 — the exploration draw

Rotation is probabilistic and reproducible. The draw is a pure function of the date, session
type and slot id:

    key  = "\x1f".join((for_date, session_type, slot_id))
    draw = int(sha256(key).hexdigest()[:16], 16) / 2**64       # in [0, 1)

    rotate = last_id is not None and draw < settings.dwell_probability

last_id is the exercise this slot used in the most recent earlier session of the same type,
read from workout history (completed workouts first, prescription fallback, merged by date).
If rotate fires and last_id is still auto-eligible, it is removed from the ranking for this
session only, and the best alternative wins. If removing it leaves nothing, the full pool is
ranked and a warning is recorded.

Because the draw depends only on stable inputs, a preview and the prescription saved from it
make the same decision; changing the probability can change the outcome, changing the date
almost certainly will.

## 10. Step 7 — the score

Every remaining candidate is scored independently, then the slot takes the best. The score has
five weighted components, a coverage bonus/penalty and a redundancy penalty:

    weights = {readiness, fatigue, spinal, injury, dwell}      # from the profile
    total   = sum(weights)

    weighted = sum(weights[k] * value[k] for k in weights) / total
    score    = clamp(weighted + coverage_factor * (coverage - 0.5) - redundancy)

with clamp(x) = max(0, min(1, x)). Defaults: readiness 0.30, fatigue 0.10, spinal 0.15,
injury 0.15, dwell 0.10; the weights normalise over their own total, so adding the dwell
weight redistributes the others rather than changing the scale.

> **2026-11-19 target amendment (not yet implemented).** The score described in this section is
> the fixed-path `generate()` score. The production resolver evaluator is replaced by the
> role-aware hierarchy in the [resolver prescription structure
> plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/RESOLVER-PRESCRIPTION-STRUCTURE.md):
> feasibility, programme consistency with the volume band as a gate, role-specific quality for
> main, secondary and accessory, volume distribution, recovery and tie-break. It is not a
> composite and does not change the fixed path.

### 10.1 Readiness R

The per-exercise readiness value in [0, 1] from the readiness score, capped by any
exercise-specific ceiling. Unknown overall readiness is acknowledged explicitly by the caller;
the selection value is then READINESS_MISSING = 1.0 (no readiness penalty) for every
candidate, and a per-exercise ceiling still caps it. Readiness never raises a load here; it
only ranks candidates.

### 10.2 Fatigue F

Recent hard work for the candidate, from the decayed-set stress model:

    F = 1 - decayed_sets / high_decayed_sets        # 48 h half-life, 10-day window
    F = 1.0                                          if there is no entry

STRESS_MISSING = 1.0 means "no record in the window" is treated as no recent fatigue, not as
a neutral-worse 0.5. That choice is deliberate: scoring unknown below a small real exposure
made a recently trained lift outrank an idle one.

### 10.3 Spinal S

Projected whole-week spinal cost with this candidate in this slot, versus the cap:

    S = clamp(1 - (current_week_cost + candidate_delta) / spinal_cap)

current_week_cost is the authoritative rule's cost for completed work before the day; the
delta includes the already-selected slots, this candidate and the blueprint defaults for
slots not yet chosen, aggregated per exercise so duplicate slots do not overwrite each other.

### 10.4 Injury I

    I = 1.00   no active low-back review/monitoring link for the candidate
    I = 0.85   low back in monitoring and the candidate is linked
    I = 0.65   low back in review and the candidate is linked

Active injury links are hard exclusions (step 3), not scores; the other regions are covered by
the readiness ceiling, so this term does not double-count them (DEC-INJURY-04).

### 10.5 Dwell D

    D = 1 - exp(-c / tau)          # c = counter, tau = resolver.dwell.tau

D(0) = 0 (a lift that has never been done in this cycle is unattractive) and D approaches 1
quickly (tau = 0.5 gives D(1) = 0.86, D(2) = 0.98). The term makes the current lift sticky
without turning the counter into a hard pin.

### 10.6 Coverage C

For every weekly volume target (low, high):

    total = completed_sets + assigned_sets
    under += max(0, low - total)
    over  += max(0, total - high)
    C = clamp(1 - (w_under * under + w_over * over)
                  / max(1, sum(max(1, low) for each target)))

coverage_factor comes from resolver.coverage.priority: balanced 0.15, under_target 0.25,
strict 0.35. The (C - 0.5) centring means a target-neutral session is not rewarded, and the
factor decides how much pattern coverage can outweigh the other components.

### 10.7 Redundancy P

    P = min(0.5, 0.1 * excess)
    excess = sum(max(0, count(pattern) - max_per_pattern))
           + sum(max(0, count(primary_muscle) - max_per_primary_muscle))

This stops a session becoming five variations of one pattern or one primary muscle. The
defaults (2 and 2) are policy, not evidence-derived optima.

## 11. Step 8 — pick and tie-break

    candidates.sort(key=rank_key)
    chosen = candidates[0]

    rank_key(least_recent) = (-score, last_date, exercise_id)
    rank_key(canonical)    = (-score, exercise_id)
    rank_key(blueprint)    = (-score, candidates.index(exercise_id))

least_recent prefers the lift that has not been trained for longest (a missing entry sorts
oldest), then the alphabetical id. canonical is purely alphabetical. blueprint uses the pool
order. The tie-break is a setting (resolver.tie_break) so the same data always produces the
same session.

## 12. Step 9 — required-pattern repair

Every session type declares required movement patterns. After the greedy pass, the assigned
patterns are checked with a small bipartite matching: each required pattern needs a distinct
slot that can provide it.

    def patterns_assignable(required, patterns_by_slot):
        # augmenting-path match, deterministic slot order
        return all(assign(key, set()) for key in required)

If a pattern is missing, the repair pass tries accessory slots (never main or secondary) whose
permitted patterns include the missing key, re-scores their candidates and swaps the best one
in. It repeats up to 2 * slots + 1 times. If it cannot settle, generation fails; it does not
silently ship an incomplete session.

## 13. Step 10 — spinal validation

The final assignment is projected into the weekly spinal cost again, this time with the
authoritative rule:

    total = weekly_spinal_cost(rule, accounting, extras)
    if total > cap + 1e-9:
        raise GenerationError(...)

The provisional score in step 7 uses the same rule to rank; this is the final safety check, so
a ranking approximation cannot let an unsafe session through.

## 14. Step 11 — output and provenance

    GeneratedSession(
        for_date, session_type, template, slots, pending_ratings, suggestions, warnings,
        policy_digest, catalogue_digest,
    )

Each slot carries its exercise, pattern, score, reasons (including the dwell counter/target
and any exploration draw), up to five alternatives and pending_rating. The reasons are the audit
trail: a session can be explained without re-running the resolver.

## 15. Availability and preview

Two read-only friends of the generator use the same eligibility and dwell rules:

* available_session_types(conn, for_date) returns which of the four types have an eligible
  candidate in every slot and can assign all required patterns to distinct slots. It never
  scores; a suggestion-only slot does not count as available.
* candidate_pools(conn, for_date, session_type) returns each slot's auto pool in template +
  catalogue order, with the dwell cap applied and the suggestions listed separately. The
  preview shows these pools; the joint evaluator may use their order as a deterministic
  tie-break cost, but the pool itself is not a preference ordering.

## 16. Worked example

Session squat, date 2026-11-19. Assume bench_press_narrow counter = 3, bench_press = 0,
tau = 0.5, T = 7, dwell weight 0.10, and the other components equal except fatigue:
narrow 0.88, bench_press 1.00 (no entry in the stress window). Weights normalise over 0.80:

    narrow:      0.375*0.50 + 0.125*0.88 + 0.1875*0.86 + 0.1875*1.00
                 + 0.125*0.998 + 0.15*(1.00-0.50)
               = 0.846
    bench_press: 0.375*0.50 + 0.125*1.00 + 0.1875*0.86 + 0.1875*1.00
                 + 0.125*0.000 + 0.15*(1.00-0.50)
               = 0.736

narrow wins because it is in its cycle. After its 7th exposure the counter wraps to 0, narrow
scores 0.721 and bench_press wins. An exploration draw below 0.10 would remove narrow for one
session even while it is incumbent; if the replacement is not performed, its counter stays 0
and the next session can return to narrow.

## 17. Failure modes

| Failure | Cause | Behaviour |
|---|---|---|
| slot has no automatically eligible candidate | all vetoed, unrated with exclude, or all suggestions | GenerationError with the slot id; no fallback |
| fixed power exercise is not eligible | injury/constraint/suitability on a fixed lift | GenerationError; power is never substituted |
| required pattern cannot be assigned | pools cannot cover the patterns with distinct slots | GenerationError before scoring |
| projected weekly spinal cost over the cap | final validation | GenerationError; the session is not emitted |
| unknown session type | bad caller input | GenerationError |

## 18. Tuning map

| Setting | Default | Effect |
|---|---|---|
| resolver.dwell.target | 7 | Exposures per cycle before the counter wraps |
| resolver.dwell.tau | 0.5 | Scale of the dwell factor; larger keeps the counter relevant longer |
| resolver.dwell.probability | 0.10 | Chance a slot explores its best alternative instead of keeping its last choice |
| resolver.weights.dwell | 0.10 | Weight of the dwell factor in the score |
| resolver.weights.readiness / fatigue / spinal / injury | 0.30 / 0.10 / 0.15 / 0.15 | The other score weights |
| resolver.coverage.priority | balanced | Coverage factor 0.15 / 0.25 / 0.35 |
| resolver.tie_break | least_recent | Final ordering after the score |

See [DWELL-AND-ROTATION.md](DWELL-AND-ROTATION.md) for the exposure-based preference and
exploration model, and the shapes it rejected.

## Related

- **Production joint resolver:** [RESOLVER-MAIN-LIFTS-VS-ACCESSORIES.md](RESOLVER-MAIN-LIFTS-VS-ACCESSORIES.md) — candidate pools, beam, evaluator and the main/accessory distinction.
- **Dwell model:** [DWELL-AND-ROTATION.md](DWELL-AND-ROTATION.md) — counters, factor, probability, cap and reset.
- **Generation pipeline:** [WORKOUT-GENERATION.md](WORKOUT-GENERATION.md) — how selection fits the wider prescription.
- **Session templates:** [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md) — slots, variants and candidate pools.
- **Decisions:** [DECISIONS.md](DECISIONS.md) — DEC-RESOLVER-15 and the resolver decisions it amends.
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) — resolver selection and exploration questions.
- **Roadmap:** [ROADMAP.md](../ROADMAP.md) — implementation status.
