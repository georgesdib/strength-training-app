# Dwell — exposure-based preference with probabilistic exploration

**Status:** canonical model for resolver exercise selection: exposure-based preference with
probabilistic exploration (DEC-RESOLVER-15).
**Code:** strength_coach/features/dwell.py, strength_coach/prescribe/generator.py.
**Settings:** Settings -> Resolver and Settings profile (group Resolver).
**Canonical pipeline:** [RESOLVER-ALGORITHM.md](RESOLVER-ALGORITHM.md).
**Supersedes:** the deterministic seven-session rotation schedule of DEC-RESOLVER-02.

**Resolver wiring status (2026-11-20, WP7a).** The cap, deterministic draw and bounded factor are
live in the resolver's `candidate_pools`. The production pool order is the pre-build dwell
layer's only output: it orders candidates for the beam but does not choose the winner, and the
evaluator remains authoritative. The factor orders only candidates sharing a structural pattern;
the draw demotes the slot's last choice to the end of that pattern class rather than removing it,
so coverage and the all-at-cap fallback survive. The last-choice lookup uses the most recent
working date per exercise from `clean_set`, which stays stable when a minimum-session shape
renumbers or omits slots. The older `generator._score` weighted-dwell path remains only for the
generator's own tests and is not production resolver behaviour.

## 1. The problem this solves

The first resolver kept a per-slot dwell: each slot remembered its last exercise and a
counter of how many sessions of that session type in a row had used it. The slot kept the
exercise without ranking until the counter reached 7, then changed. Three things went wrong
in practice:

1. The counter was per (session type, slot). The bench lift lives in four slots
   (squat bench_support, hinge bench_main, bench_squat bench_main, bench_hinge bench_main),
   so one lift could be pinned in three families at once with three independent 7s —
   up to roughly 21 exposures before every family had rotated.
2. A prescription counted even when the athlete skipped the exercise, so the counter did
   not measure work done.
3. The counter was "sessions since the slot changed", not exposure to the lift, so the same
   lift could be re-selected by another family while the first family's clock ran.

The owner's requirement was simple: count what was actually done, across the programme, and
express the result as a preference with a reproducible element of exploration — not as a fixed
seven-exposure rotation schedule.

## 2. The model in one page

The model is best described as **exposure-based preference with probabilistic exploration**.
The score carries a preference built from completed exposures, and a seeded draw occasionally
explores an alternative. The dwell target T is a cap, not a schedule: it says when a lift has
had enough exposure in the current cycle, not that the lift must change on a fixed cadence.

There is one mutable counter per exercise. It counts completed exposures of that exercise,
not sessions of a slot.

* **Increment.** When a workout is completed, every exercise with at least one working set
  in that workout, and no earlier working set on the same date, advances its counter by 1.
  Warm-up sets do not count; imported history does not count; accessory use of the same
  exercise does count.
* **Cap.** If the increment reaches the dwell target T, the counter resets to 0. The lift
  re-enters the pool at the least attractive end of the factor, not at the cap.
* **Factor.** Every candidate carries a dwell factor

      f(c) = 1 - exp(-c / tau)

  where c is the counter and tau is the exposure scale. f(0) = 0; f rises quickly and
  saturates below 1. With the shipped tau = 0.5: f(1) = 0.86, f(2) = 0.98, f(6) = 0.99999.
* **Pool ordering (production).** The factor orders candidates only within the slot's structural
  pattern class; it never moves a candidate across a pattern, never overrides eligibility or the
  cap, and is followed by the draw and catalogue order. It changes the beam's rank cost, not the
  evaluator's winner.

* **Legacy generator score (tests only).** The generator's independent score still contains a
  weighted dwell term:

      weighted = sum(w_k * v_k) / sum(w_k)          over readiness, fatigue, spinal,
                                                     injury and dwell
      score    = clamp(weighted + coverage_factor * (coverage - 0.5) - redundancy)

  This path is not the production resolver; do not use it to describe live selection.
* **Exclusion.** A candidate with c >= T is removed from automatic selection. This is a
  safety net for a lowered target or an edited counter; normal completions wrap to 0, so a
  candidate is not normally at the cap. If every candidate is at or above T, the pool is
  kept and the generator picks the best remainder, with a warning.
* **Exploration.** Each slot draws a deterministic pseudo-random value between 0 and 1, keyed
  on (date, session type, slot id), and with probability p = resolver.dwell.probability demotes
  its own last choice to the end of its structural pattern class; it is retained as a fallback.
  The replacement is the best-ranked alternative, not a random exercise. The draw is
  reproducible, so a preview and the prescription saved from it make the same decision;
  exploration is a decision, not noise.
* **No pin.** The old "keep the last choice and skip scoring" branch is gone. The dwell
  factor is a strong preference, not a lock: the current lift usually wins because its
  factor is near 1 while never-done lifts are at 0, but a lift with a much better base
  score can take over, and the exploration draw can force a change.

## 3. Worked example (the bench)

Counters: bench_press_narrow = 3, bench_press = 0, bench_press_pause = 0. T = 7, tau = 0.5,
w_dwell = 0.10, the other weights are readiness 0.30, fatigue 0.10, spinal 0.15, injury 0.15,
coverage factor 0.15.

Assume the other components are equal at readiness 0.50, spinal 0.86, injury 1.00 and
coverage 1.00. Narrow's fatigue is 0.88 (it has recent work); bench_press has no entry in the
stress window, and after the stress fix a missing entry scores 1.00. Weights normalize over
0.80, so readiness/fatigue/spinal/injury/dwell carry 0.375/0.125/0.1875/0.1875/0.125:

    narrow:       0.1875 + 0.125*0.88 + 0.1875*0.86 + 0.1875 + 0.125*0.998
                  + 0.15*(1.00-0.50) = 0.846
    bench_press:  0.1875 + 0.125*1.00 + 0.1875*0.86 + 0.1875 + 0.125*0.000
                  + 0.15*(1.00-0.50) = 0.736

Narrow wins because it is in its cycle; that is the intended stickiness. After the counter
reaches the cap (T = 7) it wraps to 0, narrow drops to 0.721 (same formula, dwell term 0) and
bench_press's higher fatigue component wins. The next completion sets bench_press to 1 and it
becomes the incumbent.

An exploration draw of 0.043 with p = 0.10 removes narrow from the ranking for that session only;
the highest-scoring alternative wins. If the alternative is not done, its counter stays 0 and
the next session can return to narrow — exploration only sticks when it is performed.

**Lowering the target.** If T is changed from 7 to 4 while narrow is at 5, the save path runs
a reconcile pass: every counter at or above 4 resets to 0. Without that pass a lowered target
would strand the lift outside automatic selection until its next completion.

**Everything at the cap.** If all candidates are at or above T (only possible after a target
change or a manual edit), the pool is kept and the best-scoring candidate is used; the
completion then resets that counter.

## 4. Parameters

| Profile key | Default | Range | Effect |
|---|---|---|---|
| resolver.dwell.target | 7 | 1-52 | Completed exposures in one cycle. The counter wraps to 0 at this value. |
| resolver.dwell.tau | 0.5 | 0.05-10 | Scale in f(c) = 1 - exp(-c / tau). Larger values make the counter matter for longer; 0.5 makes the factor nearly a step at c = 1. |
| resolver.dwell.probability | 0.10 | 0-1 | Chance that a slot explores its best alternative instead of keeping its last choice. 0 disables exploration; 1 explores every session. |
| resolver.weights.dwell | 0.10 | 0-1 | Legacy generator score only; production pool ordering uses the bounded factor and ignores this weight. |

The four retired keys (resolver.rotation.main, resolver.rotation.accessory,
resolver.rotation.default, resolver.rotation.max_dwell) no longer have any effect. Historical
profiles still load; the keys cannot be set again.

## 4.1 Fixed-history ordering comparison

`python -m strength_coach.prescribe.dwell_ab` runs one synthetic squat history through
cap-only, cap plus draw, cap plus draw plus bounded factor, and the rejected pure-factor
reference. It records the pool order and the resolver's selected exercise with the same
feasibility, band, volume and time gates. The production default remains the full layer; the
pure-factor reference is never selectable. The 2026-11-20 run moved the later
`competition_squat` ahead of `ssb_squat` in the draw/full orders while the evaluator still chose
`ssb_squat`, with no safety, band or time change.

## 5. Counter storage and audit

exercise_dwell_state is one mutable row per exercise (exercise_id, done_count, updated_at).
It is deliberately mutable, unlike the append-only prescription and workout tables: it is a
cycle state, not a record. updated_at is the audit marker for the last change. Migration 0072
creates it empty, so every exercise starts at 0 (a one-time reset; the dwell is a cycle
state, and historical done dates have no defined cycle anchor).

The two write paths are:

1. workout completion, inside the completion transaction, after clean_set is materialised.
   It runs once per completed workout; a retry returns early on the completed status.
2. settings_profile.save when resolver.dwell.target changes, and the Settings -> Resolver
   dwell counters panel (one explicit override per exercise; setting a value does not change
   suitability, so it is not the way to stop prescribing a lift).

The resolver only reads the table.

## 6. Why the earlier shapes were rejected

* **Anchored window ("exposures since the slot adopted the lift")** — has no single anchor
  when the same exercise is used in several slots, and hides the cross-role exposure the
  owner wanted counted.
* **Fixed lookback window ("done in the last 28 days")** — maximum count equals frequency x
  window. A weekly accessory can never reach 7 in 28 days, so it never rotates; and a lift
  returning from a break is immediately over the cap.
* **Per-slot counters** — the multiplication problem of section 1.
* **Naive factor (T - c) / T** — falls as the lift is used, so it pushes the incumbent out
  every session (round-robin) and makes a reset lift maximally attractive.
* **Flat factor (0 at 0, exactly 1 above 0)** — correct stickiness but the counter value
  between 1 and T-1 does nothing. The exponential keeps a small, explainable gradient.
* **Reset at the cap only** — with no decay or second state the reset lift bounces straight
  back. Wrapping to 0 at completion makes it unattractive instead.
* **Global "consecutive streak"** — families using different lifts reset each other every
  session, producing churn. The model counts occurrences, not runs.

## 7. Assumptions and limits

* tau = 0.5 and w_dwell = 0.10 are starting assumptions, not evidence-derived optima. They
  are profile settings precisely so they can be tuned after the model is evaluated
  (ASSUMPTION-31).
* With tau = 0.5 the factor is close to a step: the only large contrast is 0 versus >= 1.
  Increase tau only if the counter is meant to matter inside a cycle.
* A skipped exercise never advances its counter. That is intentional (the dwell measures done
  work), but it means a deliberate skip freezes that lift's cycle.
* Accessory use counts the same as a main-slot use. If that proves too strong, the next change
  is a per-role weight, not a return to per-slot counters.
* One exploration draw per slot per session date. The draw is deterministic but not secret; it
  is not a privacy mechanism.
* The cap excludes a lift from automatic selection, not from manual substitution. Suitability
  (will_do = 0) remains the way to say "never prescribe this".

## 8. How to configure and verify

Settings -> Resolver, or the Resolver group in Settings profile. A save appends a profile
version; a target change also reconciles the counters in the same transaction. Preview a
session and read the slot reasons: the dwell component prints the counter and the target, and
an exploration prints the draw and the previous choice.

Rollback: revert the resolver code and drop exercise_dwell_state. Historical profiles that
contain the retired keys keep loading (DEC-RESOLVER-11 precedent).

## Related

- **Algorithm:** [RESOLVER-ALGORITHM.md](RESOLVER-ALGORITHM.md) — every selection step, with the score formulas.
- **Session templates:** [SESSION-TEMPLATES.md](SESSION-TEMPLATES.md) — where slots and candidate pools live.
- **Workout generation:** [WORKOUT-GENERATION.md](WORKOUT-GENERATION.md) — the pipeline that calls the resolver.
- **Exercise variants:** [EXERCISE-VARIANTS.md](EXERCISE-VARIANTS.md) — how the catalogue feeds the pools.
- **Decisions:** [DECISIONS.md](DECISIONS.md) — DEC-RESOLVER-15 and the superseded DEC-RESOLVER-02.
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) — exposure preference and exploration questions.
- **Roadmap:** [ROADMAP.md](../ROADMAP.md) — resolver implementation status.
