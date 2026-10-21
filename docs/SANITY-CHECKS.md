# SANITY CHECKS — external verification of classification and formulas

The exercise taxonomy and the arithmetic in `strength_coach/domain/` were written from
training-domain reasoning, then checked against published material. This file records what
was checked, what the check changed, and what remains unverifiable.

Status legend: `CONFIRMED` (source agrees), `CORRECTED` (source contradicted the choice,
config changed), `UNVERIFIABLE` (no source can settle it), `CONTESTED` (credible
disagreement in the literature).

---

## A. Exercise taxonomy

| Claim | Verdict | Basis |
|---|---|---|
| A trap-bar pull is a **hinge** pattern | CONFIRMED | Universally classed as a hip-hinge/deadlift variant; handle position changes torso angle, not the movement pattern. |
| A trap bar has **lower lumbar demand** than a straight bar | CONFIRMED (direction) | The neutral-grip, higher-handle position reduces the trunk flexor moment. Exact ratio is not measurable from a log, hence an ordinal `spinal_cost` with an explicit ASSUMPTION tag. |
| Trap bar still counts as a high-fatigue spinal exposure | CONFIRMED by the programme | It stays in the high-fatigue set even though it is the mildest member. |
| "Hyperextension" and "back extension" name the same movement family | CONFIRMED | The 45-degree back-extension bench is commonly called a hyperextension; Starting Strength's own forum uses the terms interchangeably ([startingstrength.com](https://startingstrength.com/resources/forum/mark-rippetoe-q-and-a/27855-extensions.html)). This validates a *forward-only* synonym — it says nothing about whether historical rows used the same bench, so backward mapping stays disabled. |
| Reverse hyperextension is **not** direct erector work | CONTESTED | Usually described as glute/hamstring dominant with high erector involvement, not isolated spinal-erector loading. Kept `direct_erector: false` **and** added `substitutable_for_back_extension: false`, so it can never satisfy the erector dose even if the label is debated. |
| Good morning is high spinal cost | CONFIRMED | Long lever arm, barbell on the back, high lumbar moment. |
| Jefferson curl is direct erector work | CONFIRMED | Loaded spinal flexion/extension is its purpose. |
| Kettlebell swing is **not** high-fatigue spinal | CONFIRMED (spirit) | Ballistic hip hinge: high velocity, short spinal loading duration. Split into its own `hinge_ballistic` pattern so it never consumes a spinal-cap slot. |
| Ab wheel is core, not erector dose | CONFIRMED | Anti-extension isometric; erectors stabilise but are not the trained target. |
| Planks log **seconds** in a reps column | CONFIRMED by the data | Values in the tens-to-hundreds for a hold are durations, not repetitions. Modelled as `rep_semantics: seconds`. |
| Pause-bench variants are programme lifts | CORRECTED | They had been left as generic accessories; the brief's hinge day allows "close-grip **or pause** bench", so `bench_press_pause` is a first-class main lift with `vbt_family: bench`. |
| A non-main-lift squat may still be a primary compound | CORRECTED | Kept `main_lift: false` for programme role, but added `primary_compound: true` and `programme_slot_of`. Rationale: an effort rule scoped only to `main_lift` would leave most heavy squatting unregulated. |

### Ordering bugs these checks surfaced
Regex order is the fragile part of a taxonomy, and two real misclassifications were caught by
running the profiler against a real export rather than by reading the config:

* `Lying Leg Curls` matched the biceps `curl` pattern → knee-flexion patterns now run first.
* Pause-bench variants fell through to the generic horizontal-push accessory bucket.

Both have regression tests in `tests/test_exercises.py`.

---

## B. What the logging app itself is doing

The app's product page confirms three things that matter for design
([sheikogold.com](https://sheikogold.com/home/)):

1. **Readiness capture matches the export** — "typical readiness questions... optional inputs
   like HRV, RHR, & BF%". The readiness columns are app-native, not user-invented.
2. **Workouts are generated on demand and valid for a bounded window** — so one workout is
   one session, but the export carries no session id. This independently confirms that
   session reconstruction is required and that a date is the only boundary available.
3. **The app deliberately rotates exercises**: it "will sometimes assign you new exercise
   variations to test out... It'll treat each exercise variation it assigns as a stress test."

Point 3 has a direct design consequence: **high exercise rotation may be prescribed, not
chosen.** In a representative export the carry-over of exercise choice within three sessions
is markedly higher for self-directed sessions than for app-assigned ones.

**Consequence:** the session-provenance label is the only signal available for this
distinction, and the rotation rubric must be split by it. A critique that penalises rotation
without conditioning on provenance penalises the athlete for following the prescription.

---

## C. Formulas and feature logic

| Choice | Verdict | Basis and consequence |
|---|---|---|
| Within-set **velocity loss** can be computed | **CORRECTED — impossible** | Velocity loss is defined from the series of individual rep velocities inside a set; the literature reports per-repetition mean propulsive velocity across a set ([Wiley/Physiological Reports](https://physoc.onlinelibrary.wiley.com/doi/pdfdirect/10.1113/EP093514)). A per-set average has no within-set variance, so the rubric must use a clearly labelled **set-to-set decay proxy** or report the metric as not measurable. |
| Epley e1RM | CONFIRMED with a caveat | Epley and Brzycki are accurate at low rep counts and degrade as reps rise ([sportRxiv](https://sportrxiv.org/index.php/server/preprint/download/971/2090/1978)). e1RM is therefore computed only for `reps <= 10` (configurable) and tagged `e1rm_quality: ok|degraded`; above a hard cap it is refused outright. |
| RIR-adjusted e1RM via `w * (1 + (reps + RIR)/30)` | **ASSUMPTION** | "Add RIR to reps" is a common practical convention (e.g. consumer RIR-aware calculators such as [TrainerStudio](https://www.trainerstudio.com/en/tools/1rm-calculator)) but it is an approximation, not a validated equation. Stored with `rir_adjustment: epley_plus_rir` so a series can be recomputed under another convention. Never presented as measured. |
| e1RM is meaningful for every exercise | **CORRECTED — no** | It is suppressed for bodyweight/erector work and for partial-ROM variants (rack pull, RDL, good morning), where the extrapolation produces an inflated index rather than a maximal estimate. A variant "e1RM" exceeding the competition lift's is the tell. |
| ACWR as a hard rule | **CONTESTED — demoted** | The "sweet spot" reading is actively disputed ([Europe PMC critique](https://europepmc.org/article/pmc/7485291); [Gabbett](https://www.taylorfrancis.com/chapters/edit/10.4324/9781315542348-9/workload-monitoring-athlete-management-tim-gabbett)). Advisory feature only; may never veto. |
| Session duration can be measured | **CORRECTED — impossible** | No timestamps anywhere in the export. The time cap cannot be scored; only a set-count proxy, which must be labelled as such. |
| Symptoms / flare tracking | UNVERIFIABLE | No such field exists in either export. Symptom-dependent rules cannot run without a new manual input. |

---

## D. Assumptions this file creates or confirms

- **ASSUMPTION-05** — the switch date 2026-08-17 is the athlete's "about two months ago". The
  identity of "Competition Deadlift" is date-scoped (`DEC-TRAPBAR-02`), and the exact date may
  need correcting.
  Inferred from the log name; not verifiable from data.
- **ASSUMPTION-02** — `spinal_cost` values are an ordinal design choice, not a measurement.
  Sumo at 2.5 is a half-step the athlete chose: each of sumo and the trap bar has evidence of
  lower sagittal demand than a conventional pull (Swinton 2011 for the trap bar; Hanen 2025 for
  sumo), but no study ranks them against each other (`docs/SPINAL-COST.md`).
  Must be calibrated against symptom history.
- **ASSUMPTION-06** — a 4-week symptom-free streak with loaded sessions is treated as weak
  positive evidence for a suitability review. Relapse is common, so this is a prompt to look,
  not a clearance (`DEC-BACKSIGNAL-01`). Since `DEC-INJURY-02`, four weeks is the **base** of a
  scaled window, not the whole rule.
- **ASSUMPTION-08** — the injury window scales by 14 days and 2 tolerated sessions per prior
  flare, capped at 84 days and 12 sessions. The predictor (more than two previous episodes) is
  from da Silva 2019; the step sizes are a design choice (`DEC-INJURY-02`).
- **ASSUMPTION-09** — a loaded session is verified as tolerated by a symptom reading within
  7 days and no flare in that window. The direction (pain-guided progression) is supported in
  tendinopathy; the 7-day window is not measured (`DEC-INJURY-03`).
- **ASSUMPTION-11** — the readiness composite uses equal weights over present subjective
  fields as a transparent starting point; the weights are not validated.
- **ASSUMPTION-12** — per-lift readiness is constructed from global readiness, an optional
  self-rating and an injury ceiling; no validated per-lift instrument exists.
- **ASSUMPTION-13** — the injury ceilings (active 0.50/0.60, monitoring 0.80/0.85) are design
  choices, not measurements.
- **ASSUMPTION-14** — readiness cut-points, load factors and the combined-reduction cap are
  design choices, not findings; the cut-points and injury caps are approved for the plan.
- **ASSUMPTION-15** — three core subjective fields are the minimum for a numeric score; a
  design choice, not a finding.
- **ASSUMPTION-16** — the injury attention tiers are descriptive, not probabilistic, and do not
  predict a new injury.
- **ASSUMPTION-17** — the attention indicator is grouped by movement/muscle category; regions
  remain the evidence unit, and the category list/links are config.
- **ASSUMPTION-18** — the old per-lift readiness values are a black-box reference, not ground
  truth; calibration measures mimicry, not validity.
- **ASSUMPTION-19** — overrides are bounded by constraints and injury ceilings; "override wins"
  applies to the computed score only.
- **ASSUMPTION-20** — calibration features and the date split are design choices until tested.
- **ASSUMPTION-21** — a 20% cap on combined readiness + continuity reduction is a guardrail,
  not an evidence-based threshold.
- **ASSUMPTION-22** — main-lift load features are used only in calibration and only from data
  available before the session.
- **ASSUMPTION-23** — the proposed core dose (2 sessions/week, 2-3 sets, 30-60 s holds,
  anti-extension + anti-rotation/lateral, progressed by load/leverage) is a synthesis of the
  evidence, not a validated minimum. The evidence gives no dose-response for this population
  (`docs/CORE-TRAINING.md`).
- **ASSUMPTION-30** — the continuity calibration minimums (5 returns/band, 12 total), 0.15
  bootstrap-width ceiling, 0.85 lower bound and 365-day cap are transparent defaults, not
  validated (`DEC-CONTINUITY-03`).
- **ASSUMPTION-29** — the exercise-selection weights (readiness 0.35, stress 0.25,
  rotation 0.20, preference 0.10, fatigue 0.10), 28-day rotation window and 0.15 injury
  penalty are transparent defaults, not validated (`DEC-SELECT-01`).
- **ASSUMPTION-28** — the fixed 42-day/4-day half-lives and the 8-observation/28-day minimums
  for the strength shadow model are assumptions, not fitted findings; the model never changes a
  load (`DEC-FFM-01`).
- **ASSUMPTION-27** — the 21-day grace, 1%/week decay and 10% cap for an old e1RM are
  transparent defaults, not a validated detraining rate (`DEC-E1RM-DECAY-01`).
- **ASSUMPTION-26** — the e1RM correction minimum (3 tests), 95% bootstrap CI, ±10%
  bound and median-ratio estimator are assumptions, not validated; the correction is disabled
  in config if the evidence is ambiguous (`DEC-E1RM-CAL-02`).
- **ASSUMPTION-25** — the per-lift readiness weights (e1RM 0.20, RIR 0.15, velocity 0.15)
  and bands are transparent defaults, not validated; the score can only lower a load
  (`DEC-LIFT-READY-01`, `docs/LIFT-READINESS.md`).
- **ASSUMPTION-24** — the recent-stress decay constants (48 h half-life, 6/3 decayed
  hard-set thresholds, 48 h warning window) are transparent defaults, not validated
  parameters. The indicator is advisory and never changes a load (`DEC-STRESS-01`).
- **ASSUMPTION-10** — the injury-to-exercise link is an **exposure** map (direct weight 2,
  indirect 1), not a causal claim. It says which lifts load a region, not which lift caused an
  injury or which one prevents recurrence.
- **ASSUMPTION-07** — the continuity thresholds (14/28/56 days and their load/RIR changes) are
  adapted from detraining studies but are not measured cut-points (`DEC-CONTINUITY-01`).
- **ASSUMPTION-03** — RIR-adjusted e1RM is an approximation.
- **ASSUMPTION-04** — plank/carry values in the reps column are seconds. Strongly implied by
  the magnitudes; no schema states it.
- **ASSUMPTION-05** — a session is one calendar date. Unverifiable without timestamps.

## E. What these checks deliberately did not do

- They did not invent targets. No velocity range, RIR band or load increment here is sourced
  from the literature as "correct for this athlete"; all of it is calibrated from data or left
  as config awaiting the user.
- They did not use any source to override the programme. Where the literature and the
  programme disagree (e.g. ACWR), the programme's intent is kept as product behaviour and the
  metric is demoted to advisory.
