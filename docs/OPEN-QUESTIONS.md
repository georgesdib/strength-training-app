# OPEN QUESTIONS — ranked by how much they change the design

These are genuine ambiguities in the programme brief, the data, or both. Each states the
default this project will implement if nobody answers, so a missing answer is survivable and
produces an `unknown` verdict rather than a silent guess.

> Quantitative evidence for each question is kept out of this public repository. The
> questions themselves are methodology questions and apply to any athlete using the system.

---

## Q1. Sessions have no timestamps — **accepted: date-only, manual duration only**

The date column is calendar-date only. So "same date + time gap" is impossible, two sessions
on one day are indistinguishable, and a squat-plus-bench day is ambiguous between the squat
day and the bench-plus-squat day unless erector or power work is present.

**Blocks:** session/day identity, scheduling rules, duration scoring.
**Default:** one session per date; day inferred from the main lift present, with the
ambiguous pair separated by erector/power content; ambiguous -> `unknown`, and no
day-specific rule is scored when the day is unknown.

---

## Q2. What is a "high-fatigue spinal exposure"? **Default implemented: weighted cost**

The brief caps "more than ~3 per week" without defining an exposure. Measured on **distinct
exercise types** the cap almost never fires, which makes it decorative; measured **per set**
it fires almost every week, which makes it meaningless.

The likely intent is distinct high-fatigue exercise types per week — but then three heavy
rack-pull sets count the same as three light back-extension sets, which is probably not the
intent either.

**Blocks:** the spinal-cap rule and the redundancy rubric line.
**Default:** distinct high-fatigue exercise types per ISO week, cap 3, with an ordinal
weighted cost reported alongside as context (ASSUMPTION-02).

---

## Q3. The erector ramp needs an anchor — **default implemented: optional anchor**

The 8-12 week dose ramp (bodyweight -> add load -> add a set -> consolidate) requires knowing
which week of the block today is. Nothing in the source export marks a block boundary, and
the historical erector rows deliberately do **not** count toward the dose.

**Blocks:** the erector ramp rule, squat/bench session prescription, the "weekly erector dose vs plan"
rubric line.
**Default:** block starts on the first Monday after approval; until then, bodyweight only,
phase labelled `unanchored`.

---

## Q4. ~~There is no symptom field.~~ **Answered: symptom_log exists**

The most safety-relevant rules — "if back symptoms rise and do not settle in 24-48 h",
"progress only if no symptom flare" — depend on data that does not exist in either export.
The form-quality column is the only candidate and its direction is unknown, so it is not used
as a proxy.

**Blocks:** the back-flare modifier, the erector stability gate, the "symptoms reported"
rubric line.
**Applied:** manual pre-session 0-3 entries in `symptom_log`; `MOD-BACK-001` and the stability
gate read it. Missing entries still return `unknown`.

---

## Q5. ~~Session duration is unmeasurable.~~ **Answered: manual/optional only**

The rubric wants "session duration vs 80 min planned / 90 min hard cap". There are no timestamps in imported logs. The options
are a set-count proxy or dropping the metric — and a proxy presented as minutes would be a
fabricated score.

**Applied partially:** `session_feedback.duration_min` records optional session length at
review, and live workouts store `duration_basis=measured`. Imported sessions still have no
timestamps and remain unmeasured. Rubric 1.1.0 now scores measured live-workout duration
against 80 planned / 90 hard; the earlier “unmeasured for both” text is superseded.

---

## Q6. Readiness conflicts and new metrics — **merge + score implemented**

Two sub-questions:
1. **Merge** — multiple readiness rows per date exist, and most are *conflicting* rather than
   identical. Proposed rule: most-complete row, tie-break on latest. That assumes
   completeness equals authority.
2. **New metrics** — a composite readiness score, HRV and RHR are planned. Each needs a
   declared scale, direction (does higher mean better?) and aggregation before it can enter
   the composite. Grip strength is a periodic measurement, not a readiness input
   (`DEC-GRIP-01`).

**Blocks:** the readiness composite. The merge half no longer blocks anything.
**Default:** most-complete-row merge with conflicts logged. `metric_definition` rows carry
`scale_min`, `scale_max`, `higher_is_better` and `aggregation` for measurements, but they do
not currently drive the readiness composite. Adding a readiness metric still needs code/config
work; see `docs/DATA-MODEL.md` §11.4.
**Status:** the merge default is implemented (`ingest/readiness.py`, `DEC-READINESS-01`);
every date carries its `merge_note`. The global/category score, HRV/RHR baseline and wearable
blend are implemented separately (`features/readiness_score.py`); `readiness_day.composite`
still stays null by design. `ASSUMPTION-04`: completeness is treated as authority. The
"new metric needs no code" claim is **not true for readiness**; it is true only for the
measurement path.

---

## Q7. Does "main lifts at RIR 2-3" forbid sets *easier*? **Default implemented**

The constitution states a window, but `PRG-RIR-001`'s `on_fail` code is `RIR_FLOOR`, and the
danger it names is "no RIR 0-1 sets, no max singles". A set at RIR 4-5 is easier than
prescribed, not more dangerous, so treating it as a veto would make the rule fire on almost
every session and bury the real violations.

**Blocks:** nothing — the rule runs today with the default below.
**Default:** the floor is a veto (RIR below the window, plus max singles at >= 90% of a
multi-rep e1RM); a set *above* the window is counted and reported in the verdict details but
does not fail the rule. Making easy sets violations is then a config change
(`on_fail.action`) plus a predicate branch, not a rewrite.

---

## Q8. What counts as one "high-fatigue spinal exposure"? **Default implemented**

ASSUMPTION-02 fixes the *weighting* (ordinal `spinal_cost`) but not the *unit*:

* per **set** — one 12-set trap-bar session is twelve exposures, so the cap fires every week;
* per **exercise type per week** — the cap almost never fires, which makes it decorative;
* per **exercise per session** — two hinge sessions in a week cost 2+2 = 4 against a cap of 3.

**Blocks:** how strict `PRG-SPINE-001` is. It does not block the build.
**Default:** one exposure = one exercise in one session, weighted by `spinal_cost`
(`rules/registry.py` `weekly_spinal_cap`). Sets do not multiply an exposure.

---

## Q9. ~~Can the RIR window itself be widened?~~

**Closed** by `DEC-RIR-02`: the window is now RIR 1-4 with a 2-3 target, based on the
evidence collected in `docs/RIR-EVIDENCE.md`. Changing it again is still a constitution change.

## Q10. ~~Can the sumo deadlift be an accessory?~~ **Closed**

**Replacement only** (`DEC-TRAPBAR-03`). Sumo may replace the trap bar as the Day B hinge, but it
is not added alongside it or as an accessory: a second hinge violates the no-stacking rule
(`PRG-RED-001`), and on A/C it would sit next to direct erector work. No hinge-variant slot and
no rotation are planned. The path is main-lift substitution (`DEC-LLM-06`), once sumo is rated.

## Q11. Sumo replacement and the 2.5 cost — **Closed**

**Closed 2026-10-20.** Sumo is a replacement for the trap-bar hinge
(`DEC-TRAPBAR-03`), not a rotation or accessory. The 2.5 spinal cost is accepted as the
owner's ordinal design choice (`DEC-SPINE-01`); it is not a measured value and will not be
recalibrated.

There is **no formal trial and no open question**. If you want to use sumo, run it as the hinge
for a normal 4–6 week block, using ordinary training judgement:

- normal working-set/RIR rules, conservative progression;
- log a symptom reading only when the back actually feels different;
- continue at 0–1, or level 2 that settles within about 48 hours;
- reduce or stop at level 3, persistent level 2, or new neurological symptoms;
- one video or coach check in the first 1–2 sessions; not every session.

Evidence: no RCT ranks sumo against trap bar for injury; they differ in muscle activity and joint
moments, and trap-bar/squat selection matters less than heavy loading and target muscles. See
references 132–135 and `docs/SPINAL-COST.md`.

## Q12. ~~How should re-entry be calibrated from real returns?~~ **Implemented; calibrated factor rejected**

**Now rejected for use; the fixed arithmetic stays.** 14/28/56 days, +1 RIR and −5%/−10% remain
the defaults. They are evidence-informed assumptions, not measured cut-points; the calibrated
factor was tested and lost.

The plan is to calibrate them on the athlete's own returns (ROADMAP §4.12):

- record each gap and the first sessions back, with load, reps, RIR, completion, symptoms,
  readiness and **post-session fatigue**;
- estimate how strength (load at a fixed RIR) and capacity (work tolerated without a flare)
  taper with time away;
- replace a fixed band only when there are enough returns to support it, and only as a
  configurable, cited change.

**Applied then rejected:** the calibration exists, but the 2026-10-20 retrospective walk-forward
had ratio MAE 0.150 vs 0.128 for the fixed rule. The calibrated factor is not adopted; fixed
bands remain. See [RETROSPECTIVE-VALIDATION.md](RETROSPECTIVE-VALIDATION.md).

## Q13. ~~Is four weeks the right back-signal window?~~ **Answered (2026-10-19)**

The owner answered all three parts, and the signal is now per region
(`DEC-INJURY-01/02/03`; [`docs/INJURY-SIGNAL.md`](INJURY-SIGNAL.md)):

1. **The window scales** with prior flares: 28 days + 14 per prior flare (cap 84), with
   4 + 2 tolerated sessions per flare (cap 12). More than two previous episodes predict
   recurrence (da Silva 2019), so a fixed certificate over-states recovery for someone who
   flares repeatedly.
2. **"Tolerated" means loaded and followed by a clean reading**, not merely loaded. A session
   with no post-session reading is counted but `unverified`, and never satisfies the review
   requirement — missing input is `unknown`, not `pass`.
3. **The signal names lifts.** A general signal plus one per region (low back, biceps, knee),
   with the exercise links in `config/injuries.v1.yaml`; adding an injury is a config change.

Residual uncertainty is calibration, not design: the step sizes and the 7-day verification
window are assumptions (`ASSUMPTION-08`, `ASSUMPTION-09`), and the injury-to-lift link is
exposure, not causation (`ASSUMPTION-10`).

## Q14. What cardio load and fatigue model should the app use?

Planned in ROADMAP §4.13. Open: which modalities, whether TRIMP or sRPE is the impulse,
two vs three fatigue systems, whether cardio modifies load or only readiness context, and how
many weeks of individual data are needed before showing a time constant. No implementation.

## Q15. ~~Should the programme prescribe dedicated core work, and at what dose?~~ **Answered (2026-10-20)**

Before the answer, the prescribed days contained **no dedicated core work**: four slots per day
(main lifts, back extension, lateral raise, split squat), with six sets of spinal-extension work
per week. The taxonomy and rules already knew the movements — `PRG-DP-001` even carried an
`ab_wheel` increment — but no template or collection referenced them, so the config was dead.

The evidence supports a **small** block, not a large one: core exercise is not superior to
other exercise for low back pain at six months (Wang 2012; Saragiotto 2016), exercise did not
reduce recurrence in a randomised trial (Ferreira 2021), core training modestly improves
speed/jump in athletes (Kayantaş 2026), and trunk endurance is associated with lower overuse
injury (Lopes 2021, observational).

**Applied (`DEC-CORE-01`, constitution 1.2.0):** two reps-based slots — Day A `ab_wheel`
3×6-10, Day C `hanging_leg_raise` 3×8-12 — added to `accessories_and_back_extension` so
`PRG-DP-001` progresses them. No new hard rule; planks and carries stay self-directed because
they are time-based. Full reasoning: [`docs/CORE-TRAINING.md`](CORE-TRAINING.md).

## Q16. ~~Why is `PRG-DP-001` never assessable?~~ **Answered (2026-10-20)**

The rule scoped the whole `$accessories_and_back_extension` collection, but `rep_ranges` was
built from the current day's template (`DayTemplate.rep_ranges`). Every day lacked at least one
scoped exercise (A: `split_squat`, B: `back_extension`, C: `lateral_raise`), so the rule
returned `unknown` every day and "add increment" could never fire.

**Applied:** `templates.all_rep_ranges()` pools the map across all three day templates, and the
engine passes it to the rule context. On the current store the decision is still "hold load",
so no prescribed load changed on the day of the fix. See `docs/CORE-TRAINING.md` §5.4.

## Q17. ~~Should the programme add pulling and/or power slots?~~ **Answered (2026-10-20)**

- **Pulling — applied (`DEC-PULL-01/02`, constitution 1.4.0).** The prescribed upper body was
  entirely pressing (bench ×2-3, lateral raise) with no pull in any template, while the log
  contained rows, pull-ups and lat pulldowns. Day B now has a **vertical-pull variant slot**:
  `pull_up` **or** `lat_pulldown` 3×6-10, whichever was trained most recently; both are in
  `accessories_and_back_extension` so `PRG-DP-001` progresses each on its own history. They
  are substitutable for the stimulus but not identical (chin-ups load the biceps/erectors
  more, pulldowns the rectus abdominis more; 1RM correlation ~0.78), and their loads are never
  compared.
- **Power — applied (`DEC-POWER-01`).** Day A opens with `box_jump` 3×3-5, RIR 4-5, full
  recovery, before the main lift. `box_jump` is now a real taxonomy entity; the slot is
  excluded from weekly undulation and carries no double-progression citation because power
  cannot be scored from per-set average velocity.

Full reasoning and evidence: [`docs/LONGEVITY-REVIEW.md`](LONGEVITY-REVIEW.md).

## Q18. ~~Which longevity assessment metrics should the app record?~~ **Answered (2026-10-20)**

**Applied (`DEC-MEASURE-01`).** A generic append-only `measurement` table with a config
catalogue (`config/measurements.v1.yaml`): `vo2max`, `grip_strength_kg`,
`sit_to_stand_5_s`, `steps_per_day`, `sitting_hours_per_day`. Each metric is declared in
`metric_definition` with a direction and aggregation; a later direction change is refused. The
CLI is `strength-coach measure` and the web UI has a Measures page.

Grip strength was previously a readiness field; it has since been removed from readiness
(`DEC-GRIP-01`) and is measurement-only. None of these metrics changes a load.

## Q19. ~~Should a fatigue-fitness model drive strength loads?~~ **Answered: no load effect**

**Answered 2026-10-20.** The model is shadow-only; the retrospective check lost to persistence
(0.158 vs 0.074), so it does not drive loads. A future candidate must pass §4.20's gate.

**Research note:** [`docs/FATIGUE-FITNESS.md`](FATIGUE-FITNESS.md).

At the time of the question, the app had no post-session fatigue state: readiness was the
athlete's integrated signal, and gap rules handled long breaks. The model now exists in shadow
but does not change a prescription.

Options:

- **A (default, recommended):** readiness only. No modelled fatigue.
- **B:** a fixed-decay "recent stress" indicator, advisory only, no load effect.
  **Applied 2026-10-20 (`DEC-STRESS-01`):** shown on Prescribe/Programme; still no load change.
- **C:** a per-lift fitness-fatigue model fitted to the athlete's e1RM series, then validated
  prospectively before it may change a load.
- **D:** collect session RPE for strength (and optional per-lift soreness) first; revisit C.
  **Partially applied 2026-10-20 (`DEC-SRPE-01`):** optional session RPE and length are captured
  at review; no model reads them yet.

**Why not C now:** the strength-specific evidence is one small weight-lifter study; parameter
identifiability is poor; the fatigue component did not improve out-of-sample prediction in a
2025 re-analysis; and the log still lacks frequent performance tests. The current RIR
window and 48–72 h spacing already manage acute fatigue.

**Default if unanswered: no modelled fatigue (A).** Recommendation: B or D, then revisit.

## Q20. ~~Should e1RM estimates be calibrated against test results?~~ **Answered: bounded correction applied**

**Answered 2026-10-20.** Epley+RIR estimates were used as `best_usable` in an 84-day window,
and a measured `test` became an override. The report and bounded correction now exist; a
correction is applied only when the CI excludes 1.0 and the bias is within ±10%.

**Applied 2026-10-20 (`DEC-E1RM-CAL-01/02`):** report plus a bounded correction when the CI
excludes 1.0; `e1rm calibrate` and the Athlete page. Measured overrides remain the control.

## Q21. How should exercise selection decide what is comparable?

The selector can swap configured variants but has no explicit comparability class. Open:
where the A/B boundary sits (pause/narrow bench, SSB/high-bar), whether the class is per
exercise or per pair, what confirmation means, and whether parent-variant e1RM ratios can ever
be used.

Proposed in [SELECTION-COMPARABILITY.md](SELECTION-COMPARABILITY.md): class A load-comparable,
class B near-comparable (confirmation required), class C different lift (never automatic).
**Implemented 2026-10-20**; the exact A/B boundary remains open.

## Q22. Should selection target weakness or injury?

**Deferred 2026-10-20; earliest review after v0.5 (~April 2027).** No positive
weakness/injury targeting. Injury remains a constraint/ceiling/penalty; it must never boost a
candidate. A relative-weakness display, if added, is display-only. Revisit only with 12
sessions per target lift over 12 weeks, a pre-registered weakness definition, a retrospective
baseline win, and an opt-in N-of-1/alternating test. See
[WEAKNESS-INJURY-SELECTION.md](WEAKNESS-INJURY-SELECTION.md).

## Closed

- ~~What do the extreme `RIR` values mean?~~ **Closed** — `RIR 6` marks a **warm-up set**
  (`DEC-RIR-01`), so it is excluded from effort, e1RM and working volume while staying
  visible. `RIR 0-1` remain in scope but flagged (`DQ-RIR-02`).
- ~~Bodyweight movements: total mass or added load?~~ **Closed** — progression acts on
  **added load** (`DEC-LOAD-02`); total mass is used only for an e1RM.
- ~~Is there a trap-bar deadlift in the data?~~ **Closed, then corrected** — the log name
  "Competition Deadlift" meant a **sumo** pull until a recorded switch date and the trap bar after that
  (`DEC-TRAPBAR-02`); the history is resolved by date, not relabelled.
- ~~Which exercise is "back extension"?~~ **Closed** — synonymous with the older
  hyperextension name, **including historical rows**: they keep their own identity but
  count as back-extension history (`DEC-BACKEXT-02`, amending `DEC-BACKEXT-01`).

## Decisions taken as defaults unless told otherwise

- Training rows are **never** deduplicated — repeated identical rows are real sets.
- ACWR is advisory only and may never veto a prescription (the "sweet spot" reading is
  contested).
- Within-set velocity loss is reported as *not measurable*, with a labelled set-to-set decay
  proxy instead.
- Exercise-rotation scoring is split by session provenance, because in a real export the
  logging app deliberately rotates variations while self-directed sessions are stable.
