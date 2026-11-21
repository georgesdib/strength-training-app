# Resolver algorithm — canonical reference

**Status:** canonical production reference for exercise selection, prescription structure and
the resolver's supporting analysis. WP9 closeout, 2026-11-21.
**Code:** strength_coach/prescribe/resolver.py (production entry), generator.py (pools),
beam.py (search), evaluator.py and role_quality.py (finalist hierarchy).

This document describes what the production resolver actually runs. It replaces the earlier
step-by-step description of the standalone generator, which remains only as a diagnostic test
path. Where a specialist document has deeper evidence, it is linked rather than copied.

## 1. Scope and invariants

The resolver answers one question: **which eligible exercise fills each slot of one session on
one date, and does the built prescription survive the evaluator's hierarchy?** It never invents
an exercise, changes the session type, or writes to the store.

Invariants:

- Python is authoritative. No LLM computes selection, load, RIR, volume or fatigue.
- Candidate pools are finite and explicit. Nothing outside the pool can be prescribed.
- Hard feasibility precedes every soft comparison. There is no composite score.
- The pre-build dwell layer owns repetition/variation; role quality does not re-score dwell.
- The evaluator owns specificity, exposure, suitability, complementarity, coverage and
  stimulus-to-fatigue. Each signal has one owner.
- Missing data is neutral or unknown, never an optimistic guess.
- Append-only history is read, never rewritten. Corrections become new records.

Inputs: for_date, session_type, policy, template/catalogue, settings profile, readiness, injury
signal, recent stress, suitability, dwell counters, history, and optional minimum-session /
deload / top-set / VBT inputs.

Outputs: a ResolvedPrescription with the chosen assignment, exact final prescription, candidate
pools, beam diagnostics, evaluator snapshot, top-set block and input fingerprint.

## 2. Production pipeline

1. build_prescription dispatches to the resolver when Settings -> Resolver is enabled.
2. resolver.build_resolved loads policy, template, catalogue, settings, context, History.
3. generator.candidate_pools builds each slot's raw pool and applies hard eligibility.
4. The dwell cap removes candidates at or above the target; if all are at the cap, the pool is
   kept with a warning.
5. The dwell order applies the bounded factor and the deterministic draw within each structural
   pattern; catalogue order is the remaining tie-break.
6. beam.search explores complete assignments. It keeps at most width = 4 partials, at most 6
   candidates per slot, and fully evaluates at most 4 finalists.
7. evaluator.evaluate_assignment builds each finalist through the normal prescription pipeline
   with use_resolver=False and returns hard feasibility, components and the role-quality snapshot.
8. The beam compares finalists by the lexicographic quality_key, then rank cost, then assignment.
9. The winning prescription is final; it is not rebuilt. Structural violations and ownership are
   checked again.
10. The input fingerprint and generated-session snapshot are attached to the plan notes.

## 3. Candidate pools and hard eligibility

A slot pool is the template's own list, followed by catalogue additions, de-duplicated in order.
A policy slot_pool replaces the catalogue for that slot. Power slots use their fixed exercise.

Hard exclusions happen before ranking:

- pattern not permitted for the slot;
- constraint veto or active injury link;
- can_do = 0;
- will_do = 0 or feels_bad = 1 when their block flags are on;
- unavailable/unrated exercise when the unrated mode excludes it.

Suggestion-only candidates may appear in a preview but do not enter an automatic assignment.

## 4. Dwell ordering (WP7a)

The cap is unchanged: a candidate with done_count >= resolver.dwell.target is excluded. When
every candidate is at the cap the pool is returned unchanged with a warning.

The bounded factor is:

    f(c) = 1 - exp(-c / tau)

with c = done_count, tau = resolver.dwell.tau (default 0.5). f(0) = 0 and f saturates below 1.
The factor orders candidates only inside the same structural pattern. It never crosses a pattern,
never overrides eligibility or the cap, and never becomes a final score.

The exploration draw is deterministic:

    u = first 64 bits of SHA-256(date + separator + session_type + separator + slot_id)
        divided by 2^64

If u < resolver.dwell.probability, the slot's last choice is demoted to the end of its pattern
class. It is retained as a fallback, not removed. The last choice is the most recent working date
for an exercise in clean_set, so a shaped template that renumbers slots keeps the same key.

Precedence in the pool is: structural pattern, factor within pattern, draw demotion within the
class, catalogue order. Required-pattern coverage is not a pool sort key; it is enforced by the
beam's structural reserve before truncation.

## 5. Beam search

The beam is a bounded best-first search over complete assignments.

- width = 4 partial assignments;
- max_candidates_per_slot = 6;
- max_full_evaluations = 4.

Partial order cost is the sum of candidate ranks in the pool. Required-pattern candidates are
reserved before truncation, so a pattern that only one candidate covers is not lost to position.
An evaluated finalist records whether the search was exhaustive, pruned, candidate-capped or
evaluation-budget-capped.

## 6. Evaluator hierarchy (WP6)

Hard feasibility is separate from the hierarchy:

- executable;
- no validation/constraint issues;
- weekly spinal cap not exceeded;
- exact assignment preserved;
- session/template not replaced;
- no structural required-pattern violation.

Finalist comparison is lexicographic:

1. Band gate: outside the adjusted weekly volume band ranks below every inside-band finalist.
2. Non-negotiable intent: an unsatisfied required top-set intent ranks below an applied one.
3. Role-quality classes, main then secondary then accessory. Each role's criteria are compared
   in the configured order. Missing data is neutral.
4. Volume closeness inside the band: the symmetric volume error is the sum of per-group absolute
   deviations divided by the sum of targets.
5. Recovery/practicality: time over the planned target, then warnings.
6. The old additive score is retained only as a transparent fallback in the key.
7. Rank cost, then stable assignment order.

The role-quality snapshot is response-only. It records each role's slots, exercise and class
values, plus the flattened vector and limitations. It is not a training target.

### 6.1 Role classes

Every class is ordinal and higher is better. Missing data returns the configured neutral value;
it is never treated as evidence of a deficit, a surplus or a complement. The configured class
values and criterion order are in `config/resolver-role-quality.v1.yaml`; the snapshot version is
`role-quality-v2`.

**Main**

- specificity: same lift 3, same `summary.LIFT_GROUPS` family 2, same taxonomy pattern 1,
  another permitted pattern 0; unknown previous choice 2.
- exposure: intensity at or above 0.80 with full e1RM quality/age 2, partial 1, missing 1,
  below the heavy band 0. This is a band check, not a point estimate.
- suitability: explicit positive 3, unrated 2, eligible with caution 1. Injury, `can_do`,
  `will_do`, `feels_bad` and pattern remain pass/fail filters, never points.

**Secondary**

- complementarity is relative to the main lift actually selected, not "is any family known".
  A candidate that shares the main lift's pattern, materialised volume key
  (`features.volume.volume_target_key`) or `LIFT_GROUPS` family is redundant
  (same pattern 1, same family 1). A different permitted pattern is complementary 3. Missing
  candidate or main pattern is neutral 2.
- volume usefulness uses the candidate's own movement-pattern ledger group. The candidate's
  prescribed sets are removed from the post-session group volume, so a genuine deficit
  (group below target before this candidate, result within the 15% tolerance) is 3; a pattern
  already at target before the candidate is redundant 1; a deficit filled past the tolerance is
  2. Missing or unusable volume information is neutral 2. The weekly volume band remains a
  separate gate and is not re-scored here.
- redundancy is relative to the main lift and the other selected non-power exercises, excluding
  the candidate's own slot. A duplicate pattern, materialised pattern key or lift family is 1;
  a shared primary muscle without a duplicate pattern is a partial overlap 2; a different
  pattern and no shared primary muscle is complementary 3. Prescribed set count and
  "compound" status are not signals. Missing classification data is neutral 2.

**Accessory**

- coverage excludes the candidate's own slot. A pattern or family already supplied by the main
  lift or another selected exercise is covered 1; an otherwise uncovered pattern is 3. Missing
  candidate taxonomy is neutral 2, and missing taxonomy on every other exercise cannot establish
  a new uncovered pattern. Multiple accessories each see the other selected accessories, so the
  rule is symmetric and slot-order independent.
- productive volume uses the same deficit/target/tolerance rule as volume usefulness. It is not
  a positive-set-count check and does not reward volume materially beyond target.
- stimulus-to-fatigue compares the mandatory tax axes from `config/selection-tax.v1.yaml`
  (accessory: axial and skill; essential: axial, systemic and skill). Low cost 3, moderate 2,
  high 1; missing tax is neutral 2. The existing tax data measures ordinal fatigue cost, not an
  independent stimulus magnitude, so the slot's fixed dose is treated as the stimulus. The
  snapshot records the limitation `stimulus_to_fatigue_compares_cost_at_fixed_slot_dose`.
  This criterion never outranks feasibility, intent, the volume band or the main/secondary
  hierarchy.


## 7. Loads and Epley inversion

The engine does not invent a load. For a working set:

    e1RM = load * (1 + (reps + RIR) / 30)

The inverse is:

    load = e1RM / (1 + (reps + RIR) / 30)

The result is rounded down to the item's rounding increment:

    round_down(x, inc) = floor(x / inc) * inc

This inverse is used by the top-set solver. A normal load is computed from the e1RM target and
the prescribed reps/RIR; readiness, continuity, deload and back-flare modifiers act before this
step.

## 8. Prescription structure

### 8.1 Straight sets

No set_groups. The item carries sets, reps range, load, RIR target and rest. The client renders
one planned row.

### 8.2 Top set plus back-offs

Eligibility requires a main lift, a usable load/e1RM, at least two sets, and no blocker
(deload, taper, two-step readiness drop, flare, outside policy).

The top-set RIR is selected by the main scheme and competition window, raised by one readiness
step at most, and capped at resolver.top_set.fallback_above_rir.

    top_load = round_down(e1RM / (1 + (reps_low + top_rir) / 30), increment)
    backoff_load = round_down(top_load * backoff_percent, increment)

The back-off count is item.sets - 1 and must be at least one. The groups are:

    [top_set: 1 set at top_load, top_rir]
    [back_off: sets-1 at backoff_load, item.rir_target]

This is a set configuration, not extra volume. The groups are ordered and carry no stored role
on the wire; group_index is the identity.

Status is applied, not_applicable, fallback or unsatisfied. blocked_by_design is not a failure;
unexpected blockers are fallback under preferred and unsatisfied under required.

### 8.3 Warm-up ramps

Warm-ups use the heaviest planned group load, not the item summary load:

    50% x 5, 70% x 3, 85% x 1 (config defaults), rounded down
    plus an empty-bar set when it is below the first rung and below the working load.

Warm-ups are attached after the load-changing modifiers and are not part of working volume.

### 8.4 RIR 6

RIR 6 is the warm-up sentinel unconditionally. It is never working volume, never matched to a
planned working group and never part of derived working structure. A stored working flag that
disagrees is only a data-quality note. Imports are never rejected for RIR 6.

## 9. Volume ledger and band

The weekly ledger uses hard working sets (or configured effective sets). For each managed
pattern, after is completed plus this session's pattern sets. The target is the effective target
for the date.

The total band is:

    total_band = tolerance * total_target
    low = total_target - total_band
    high = total_target + total_band

The per-pattern band is:

    pattern_band = max(band_min, tolerance * pattern_target)
    under  if value < target - pattern_band
    within if target - band <= value <= target + band
    over   if value > target + band

Default tolerance is 0.10 and band_min is 1 set. The engine prunes or tops up only within the
configured allocation rules; the resolver never widens the band or the beam to manufacture a
winner.

## 10. Minimum session and accessory-only

The minimum-session shape runs before the resolver:

- retain the most important slots for the target minutes;
- clamp main-lift sets to main_lift_floor_sets (default 2);
- clamp accessories to accessory_floor_sets (default 1);
- remove non-essential work before touching essentials;
- never add a slot the resolver would then have to remove.

The time estimate is:

    sum(sets * (set_seconds + rest_s)) + warmup_sets * warmup_set_seconds, divided by 60

Defaults: 30 seconds per execution, 30 seconds per warm-up set. The result is a planning estimate,
not a measured duration. Accessory-only has no main lift, no required main pattern, and top set
is not_applicable by design.

## 11. Fingerprint and generated snapshot

prescription-input-v4 fingerprints the material inputs: date, session type, assignment, template
and policy digests, catalogue digest, resolved settings, resolver settings, candidate pools,
beam config, evaluator version and role-quality config digest.

The generated_session snapshot carries:
- assignment and slot specs;
- template/policy/catalogue digests;
- candidate pools and beam result;
- evaluator snapshot (including quality);
- top-set block;
- pending ratings.

The snapshot is response/audit data. It never changes a prescription.

## 12. Actual data and derived structure (WP5)

Adherence, VBT and derived structure share one order matcher. Planned groups are matched to
performed sets by cumulative working order, not a stored role. A substitution is attributed by
substitutes_plan_item_index and recorded as a changed slot; its quality uses the saved prefill
when present and is unavailable otherwise. An addition is extra work.

Derived structure is post-workout description only:

    preparatory progression
    heavy working exposure
    top_set_like_plus_back_off
    back_off_sequence
    straight_working_sets
    multiple_heavy_exposures
    ambiguous / insufficient

Thresholds are config/derived-structure.v1.yaml: load equality within one rounding increment, a
top-set gap of at least two increments, at least two back-off sets, RIR tolerance one. Confidence
is high with load/RIR/reps, medium with one missing, low with load only, unknown when evidence is
insufficient. It never changes a raw set, working volume, e1RM, fatigue or policy.

## 13. Execution layer (WP8)

The resolver is not the execution layer. A plan is frozen at start. Substitutions and additions
are append-only execution events. The phone is the only author of a substitution; the watch
renders and logs it. A replacement is rejected once a set is attributed to the slot.

The watch talks to the server directly. When that transport fails and the phone is reachable, the
phone relays the same operation with the watch token and original operation id; the server still
sees the watch as the execution device. This is a transport fallback, not a second writer. True
dual logging is not supported: one owner_device_id per session.

## 14. Code map

| Stage | File | Functions |
|---|---|---|
| Dispatch | prescribe/engine.py | build_prescription |
| Resolver entry | prescribe/resolver.py | build_resolved, _build_resolved, prescription_input_fingerprint |
| Pools | prescribe/generator.py | candidate_pools, _dwell_ordered_pool, _last_used, _apply_dwell_exclusion |
| Dwell | features/dwell.py | factor, rotation_value, counts, record_completion |
| Beam | prescribe/beam.py | search, BeamConfig, BeamResult |
| Evaluator | prescribe/evaluator.py | evaluate_assignment, score_components, _components |
| Role quality | prescribe/role_quality.py | snapshot, RoleQualityConfig, ClassScale |
| Tax input | prescribe/selection_tax.py | TaxConfig, Tax, lower_tax |
| Fixed-history A/B | prescribe/evaluator_ab.py | _run_case, CASES, _markdown |
| Resolver benchmark | tools/resolver_benchmark.py | _synthetic_measure, _timed, _percentile |
| Top set | prescribe/top_set.py | plan_for_item, resolved_top_set_rir |
| Loads | prescribe/loads.py, domain/e1rm.py | solve_load, round_down, epley_rir_adjusted, load_for_reps |
| Warm-up | prescribe/warmup.py | for_item |
| Volume | prescribe/volume_budget.py, features/volume.py | week_panel, band, per_pattern_band |
| Minimum session | prescribe/minimum_session.py | build_resolver_shape, estimate_minutes |
| Adherence | adherence.py | analyse, _set_metrics |
| Matching | features/set_matching.py | classify_set, group_for_ordinal |
| Derived structure | features/derived_structure.py | derive, StructureConfig |
| Gateway | StrengthCore/Execution/WatchRelayModels.swift, StrengthApp/Core/WatchPairing.swift | WatchRelayRequest, relay |
| Watch transport | StrengthWatch/WatchSessionController.swift | send(_:) |

## 15. Worked examples

### 15.1 Straight sets

Plan: SSB squat 4 x 5 @ RIR 2, e1RM 140 kg, increment 2.5.
Load = 140 / (1 + (5 + 2)/30) = 140 / 1.2333 = 113.5 -> 112.5 kg after round-down.
No groups. The client shows one row. The evaluator checks executable load, no issues, spinal cap,
volume band and recovery; role classes compare the main candidate's specificity/exposure/
suitability.

### 15.2 Top set plus back-offs

Performed history: 180 x 4 @ RIR 1, then 160 x 5 @ RIR 3 three times.
Forward e1RM from the top set = 180 * (1 + (4+1)/30) = 210 kg.
Top set target: 4 reps @ RIR 1 -> 210 / (1 + 5/30) = 180 kg.
Back-off at 85%, 2.5 kg increment: 180 * 0.85 = 153 -> 152.5 kg.
Groups: top_set 1 x 4 @ 180 / RIR 1; back_off 3 x 5 @ 152.5 / RIR 2.
The same sequence read back through WP5 is top_set_like_plus_back_off with high confidence.

### 15.3 Deload

The deload provider reduces the main-lift load and sets, adjusts the weekly band for the
intentional reduction, and blocks top-set structure by design. The result is not a failed
top set or a failed volume gate; it is not_applicable/inside the adjusted band.

### 15.4 Competition taper

Taper is a competition window, not a deload. Top-set structure is blocked by design, the load
and set dose follow the taper policy, and the adjusted band is used. The report says
blocked_by_design, not unsatisfied.

### 15.5 Minimum session

Target 30 minutes, accessory-only. The shape keeps only the accessory slots needed to cover the
retained patterns, clamps each to at least one set, and passes those slots to the resolver. The
time estimate uses 30 s execution plus rest per set, plus warm-up allowance. Top set is
not_applicable. The volume gate is neutral because the shape deliberately undershoots the normal
weekly target.

### 15.6 Substitution

The phone writes one execution event for a plan slot with the replacement exercise and a
server-solved prefill. The performed set carries substitutes_plan_item_index. Adherence marks the
slot as substituted, counts it as filled, and compares quality with the substitute prefill when
present. The original lift's target is never used for the substitute. A late substitution is
rejected once a set is attributed to the slot.

### 15.7 Derived structure

Rows: 180 x 4 @ RIR 1, 160 x 5 @ RIR 3, 160 x 5 @ RIR 3, 160 x 5 @ RIR 3.
Working loads: 180, 160, 160, 160. Gap = 20 kg = 8 increments of 2.5. First RIR 1 < rest RIR 3;
first reps 4 <= rest reps 5. Result: top_set_like_plus_back_off, high confidence, segments
top_set_like_effort + back_off_sequence. No raw set or training metric changes.

### 15.8 Secondary comparison: complementarity and redundancy

Main `ssb_squat` (pattern `squat`, volume key `squat`). Support candidates:

- `bench_press` (`horizontal_push`): different pattern -> complementarity 3.
- `split_squat` (`squat_unilateral`, volume key `squat`): same materialised pattern ->
  complementarity 1.

Complementarity is evaluated before volume and redundancy, so `bench_press` wins. This is the
unchanged `secondary_complementarity` A/B row.

For redundancy, use a main `ssb_squat`, a selected accessory `bench_press_narrow`
(`horizontal_push`), and support candidates `bench_press` and `dumbbell_row`:

- `bench_press` duplicates the accessory's pattern -> redundancy 1.
- `dumbbell_row` (`horizontal_pull`) adds a different pattern and shares no primary muscle with
  the main or accessory -> redundancy 3.

Both have complementarity 3, so redundancy decides. This is the `secondary_redundancy` A/B row.
Tests: `tests/test_role_quality.py::test_complementarity_is_relative_to_the_selected_main_lift`,
`::test_redundancy_compares_selected_work_not_set_count` and
`::test_redundancy_can_decide_between_equally_complementary_supports`.

### 15.9 Accessory comparison: coverage and stimulus-to-fatigue

Main `ssb_squat`, support `bench_press`. Accessory candidates:

- `dumbbell_row` (`horizontal_pull`): no other selected exercise has that pattern -> coverage 3.
- `bench_press_narrow` (`horizontal_push`): the support already covers the pattern -> coverage 1.

Coverage is the first accessory criterion, so `dumbbell_row` wins even though the weekly
horizontal-pull volume is already at target and its productive-volume class is lower. This is
the `accessory_coverage` A/B row.

For stimulus-to-fatigue, when coverage and productive volume tie, compare the mandatory tax
axes. Accessory candidates `front_squat` (axial 2, skill 3 -> high cost 1) and
`hanging_leg_raise` (axial 1, skill 1 -> low cost 3) have different patterns and neither is
covered, so coverage ties at 3. The low-cost candidate wins. Missing tax (for example
`lying_leg_curls`) stays neutral 2 and is never assumed to be cheaper. This is the
`accessory_stimulus` A/B row. Tests:
`tests/test_role_quality.py::test_coverage_excludes_the_candidate_itself`,
`::test_accessory_coverage_can_decide_the_winner` and
`::test_stimulus_to_fatigue_can_decide_between_equally_covering_accessories`.

## 16. Failure modes and diagnostics

| Symptom | Meaning | Where |
|---|---|---|
| no feasible assignment | hard feasibility failed, or beam pruned all | BeamResult / ResolverBuildError stage assignment_search |
| prescription_evaluation | a finalist build raised | evaluator stage |
| final_integrity | structural/ownership/fingerprint check failed | resolver final stage |
| candidate_cap_applied | a slot had more than 6 candidates | BeamResult |
| truncated | candidate or evaluation budget removed options | BeamResult |
| band outside | posted session is outside adjusted volume band | volume panel |
| top set fallback/unsatisfied | preferred/required structure could not be applied | top_set block |
| role snapshot missing | test double or non-resolver path | evaluator quality |

Every resolver failure is structured with stage, message, cause and beam details. Do not parse a
message; use the stage and fields.

## 17. Settings and config map

| Setting/config | Default | Owner |
|---|---|---|
| resolver.enabled | off | settings registry |
| resolver.dwell.target | 7 | dwell cap |
| resolver.dwell.tau | 0.5 | factor |
| resolver.dwell.probability | 0.10 | draw |
| resolver.top_set.mode | off | top-set intent |
| resolver.top_set.backoff_percent | 0.85 | back-off load |
| resolver.top_set.fallback_above_rir | 2 | top-set RIR ceiling |
| config/resolver-role-quality.v1.yaml | role criteria, class scales and neutral values | evaluator |
| config/derived-structure.v1.yaml | load/RIR tolerances, gap, back-off count | analysis only |
| config/volume.v1.yaml | targets, tolerance 0.10, band_min 1 | volume ledger |
| config/minimum-session.v1.yaml | floors 2/1, 30 s per set | shaped sessions |
| beam width / cap / budget | 4 / 6 / 4 | beam |

## 18. Verification

Run the narrowest relevant tests, then the full backend suite:

    cd strength-training-app
    .venv/bin/python -m pytest tests/test_resolver_wiring.py tests/test_beam.py       tests/test_role_quality.py tests/test_evaluator_ab.py       tests/test_evaluator_ab_report.py tests/test_resolver_role_quality_config.py       tests/test_generator.py tests/test_dwell_ab.py -q
    .venv/bin/python -m pytest -q
    .venv/bin/ruff check strength_coach/prescribe tests

The synthetic A/B and dwell reports are reproducible with:

    .venv/bin/python -m strength_coach.prescribe.evaluator_ab
    .venv/bin/python -m strength_coach.prescribe.dwell_ab

The resolver performance report is reproducible with:

    .venv/bin/python tools/resolver_benchmark.py --synthetic       --case secondary_complementarity --runs 10
    .venv/bin/python tools/resolver_benchmark.py --synthetic --case straight --runs 10

It reports cold start, steady-state p50/p95, finalist evaluations, prescription builds,
candidate count and beam truncation for the corrected path and for the same builds with the
role-quality snapshot disabled. Laptop numbers are not ODROID numbers; the ODROID-C4
measurement is pending until the command is run there.

## 19. Superseded and specialist documents

This page is the canonical production reference. The following remain for deeper derivation or
historical evidence:

- DWELL-AND-ROTATION.md — dwell model, parameters and counter audit.
- TOP-SET-BACKOFF-EVIDENCE.md — top-set rationale and evidence.
- RESOLVER-MAIN-LIFTS-VS-ACCESSORIES.md — role taxonomy and main/support/accessory background.
- docs/WATCH-GATEWAY.md — WP8 relay protocol and physical acceptance.
- docs/plans/RESOLVER-PRESCRIPTION-STRUCTURE.md — the cross-repository plan and decision log.

The earlier description of generate() as the production path is superseded. generate() remains a
deterministic diagnostic path; production uses candidate_pools -> beam -> evaluator.

## Related

- **Dwell:** [DWELL-AND-ROTATION.md](DWELL-AND-ROTATION.md) — model, parameters and counter audit.
- **Top set:** [TOP-SET-BACKOFF-EVIDENCE.md](TOP-SET-BACKOFF-EVIDENCE.md) — rationale and evidence.
- **Roles:** [RESOLVER-MAIN-LIFTS-VS-ACCESSORIES.md](RESOLVER-MAIN-LIFTS-VS-ACCESSORIES.md) — role taxonomy.
- **API:** [API.md](API.md) — resolver response and execution payloads.
- **Gateway:** [WATCH-GATEWAY.md](https://github.com/georgesdib/StrengthApp/blob/development/docs/WATCH-GATEWAY.md)
  — WP8 phone relay.
- **Decisions:** [DECISIONS.md](DECISIONS.md) — DEC-RESOLVER-18 through DEC-RESOLVER-30.
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) — resolver questions that remain.
- **Roadmap:** [ROADMAP.md](../ROADMAP.md) — implementation and release status.
