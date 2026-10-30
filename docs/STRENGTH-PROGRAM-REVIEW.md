# Strength programme review — 2026-10-20

**Scope:** the strength programme only. Cardio, video, the LLM narrative and the web UI are out
of scope. This is the evidence snapshot; implementation status is recorded in the note and table below.

**Review status: CLOSED 2026-10-20.** No open programme-design items remain here. Future
validation, parent-ratio and targeting work is tracked in [ROADMAP.md](../ROADMAP.md) §4.20.

**Implementation note (2026-10-20):** the P0/P1 fixes for power loading, hinge balance, rolling session types, upper-body row/press, readiness set reduction, volume management v1 and **selection comparability** were subsequently implemented; Plan A restored squat volume and raised trap-bar hinge volume while keeping the spinal cap. A scheduled deload is now implemented as an optional suggestion with automatic reactive triggers; a standardised warm-up, a 3RM/5RM cadence and accessory under-MEV progression are implemented. Individualized MRV is closed as not estimable from the available data; main-lift volume experimentation is deliberately not done. The retrospective walk-forward check is done; continuity and fatigue lost to their baselines, so neither is adopted; prospective validation is a future gate only for a candidate that first beats the retrospective baseline. Weakness/injury targeting is deliberately deferred (`DEC-SELECT-04/05`). There are no open programme-design items left in this review. On 2026-10-28 a knee-flexion accessory (`lying_leg_curls`, 3×8-12) was added to the squat and hinge sessions and `knee_flexion` became a managed ledger key (`DEC-KNEEFLEX-01`, weekly total 57→63); the groups that remain unprescribed are recorded as accepted gaps in `LIM-54`.

**Method:** read the templates, constitution, prescription engine, evidence notes and references;
generated A/B/C prescriptions from the local database; checked the planned weekly dose and the
main evidence claims against the cited literature. The local 12-week audit is in
`private/docs/STRENGTH-PROGRAM-AUDIT.md` (git-ignored, personal data).

---

## 1. The programme as implemented

### Current weekly shape (generated from config)

The tables below are generated from `config/templates/session-types.v1.yaml`, the taxonomy,
`config/volume.v1.yaml` and `PRG-SPINE-001`; run `python tools/programme_summary.py --write`
after a template change. A stale block fails `tests/test_programme_summary.py`.

**Reconciled 2026-10-27** with `DEC-SPINE-05`: the bench+hinge support is the sumo deadlift,
not the single-leg RDL.

<!-- BEGIN GENERATED PROGRAMME SUMMARY -->
<!-- source:sha256:72b82400ff7cdfc4 -->

| session type | work | sets | spinal cost |
|---|---|---|---:|
| **squat** | Box Jump 3×3–5 @ quality stop; SSB Squat 5×3–5 @ RIR 2–3; Bench Press 4×3–5 @ RIR 2–3; Back Extension 3×10–12 @ RIR 2–3; Dumbbell Row 3×8–12 @ RIR 2–3; Lying Leg Curls / Nordic Curl 3×8–12 @ RIR 2–3; Ab Wheel 3×6–10 @ RIR 2–3 | 24 | 1 |
| **hinge** | Trap-Bar Deadlift 5×3–5 @ RIR 2–3; Bench Press (narrow grip) / Bench Press (pause) 4×3–5 @ RIR 2–3; Pull-up / Lat Pulldown 3×6–10 @ RIR 2–3; Dumbbell Row 3×8–12 @ RIR 2–3; Split Squat 3×8–10 @ RIR 2–3; Lying Leg Curls / Nordic Curl 3×8–12 @ RIR 2–3 | 21 | 2 |
| **bench_squat** | Bench Press 4×3–5 @ RIR 2–3; Competition Squat 4×3–5 @ RIR 2–3; Dumbbell Row 3×8–12 @ RIR 2–3; Overhead Press (seated) 3×6–10 @ RIR 2–3; Ab Wheel 3×6–10 @ RIR 2–3 | 17 | 1 |
| **bench_hinge** | Bench Press 4×3–5 @ RIR 2–3; Sumo Deadlift 3×3–5 @ RIR 2–3; Pull-up / Lat Pulldown 3×6–10 @ RIR 2–3; Dumbbell Row 3×8–12 @ RIR 2–3; Overhead Press (seated) 3×6–10 @ RIR 2–3; Hanging Leg Raise 3×8–12 @ RIR 2–3 | 19 | 2.5 |

Over six sessions (two weeks): squat, hinge, bench+squat, squat, hinge, bench+hinge.
Planned average is **63 working sets/week** across three sessions.

| lift group | sets/week |
|---|---:|
| squat (SSB main + competition support) | 7 |
| bench (main + support) | 12 |
| trap-bar deadlift | 5 |
| sumo deadlift | 1.5 |
| back extension | 3 |
| horizontal row | 9 |
| vertical pull | 4.5 |
| overhead press | 3 |
| split squat | 3 |
| knee-flexion hamstrings | 6 |
| core | 6 |
| power | 3 |
| **total** | **63** |

Counted spinal cost: **4** for the first week (squat, hinge, bench+squat) and **5.5** for the second (squat, hinge, bench+hinge), against a cap of **6**.
<!-- END GENERATED PROGRAMME SUMMARY -->

### Effort and progression

- Main lifts: **RIR 2** target, allowed window **RIR 1–4**; RIR 0, max singles and 1RM testing
  inside a block are forbidden.
- Accessories: double progression, hold load until the top of the range on all sets at RIR ≥ 2,
  then add one increment. The prescription rule (`PRG-DP-001`) considers the last four sessions
  containing the lift; the rubric item `PROGRESSION_ADHERENCE` is a **one-session review** using
  the immediately previous session. That difference is intentional and documented in `rubric.py`.
- Main-lift load: solved from the lift's own e1RM (Epley + RIR) with a bounded measured-test
  calibration and age decay.
- Undulation: 4-week cycle (strength / strength / maximal / strength; accessory / volume /
  accessory / volume), only when a block anchor is declared. A scheduled deload week is configured every 6 weeks; reactive triggers still override it.
- Readiness and continuity can reduce load and add RIR; poor readiness can also remove one
  accessory set. The combined readiness + continuity load reduction is capped at 20%. The
  fitness-fatigue model does **not** change loads.
- Exercise selection can apply at most one substitution per slot when explicitly enabled; the
  load is re-solved from the selected lift's history. A/B/C comparability classes gate
  automatic application, and the LLM may only choose from the Python-filtered list.

---

## 2. Evidence check

Legend: **Strong** = consistent meta-analytic evidence; **Moderate** = a reasonable body of
evidence with caveats; **Weak/Methodology** = plausible practice or product decision, not
settled by trials.

| # | Claim in the programme | Evidence status | What the evidence says | Verdict |
|---|---|---|---|---|
| 1 | 3×/week full-body is a good strength frequency | Moderate | When weekly volume is equated, higher frequency appears to help strength somewhat; 3× full-body is within the supported range. Frequency is not a free extra dose. ([frequency meta-analysis](https://pubmed.ncbi.nlm.nih.gov/30076500/); [2025 dose-response](https://link.springer.com/article/10.1007/s40279-025-02344-w)) | Supported |
| 2 | Weekly volume around the current plan is enough | Moderate | Hypertrophy rises with weekly volume to roughly 10+ sets per muscle with diminishing returns; strength is less volume-dependent. The current plan has ~7 squat, 12 bench and ~6.5 hinge sets/week (5 trap-bar + 1.5 sumo), plus accessory volume. ([Schoenfeld 2017](https://www.tandfonline.com/doi/abs/10.1080/02640414.2016.1210197); [2025 dose-response](https://link.springer.com/article/10.1007/s40279-025-02344-w)) | Supported after Plan A; hinge still below bench volume |
| 3 | Main lifts at 3–5 reps | Strong for strength | Heavy, lower-rep training is more specific for 1RM strength when effort is matched. ([Hammert 2026](https://doi.org/10.1007/s40279-025-02370-8)) | Supported |
| 4 | RIR 2 target, RIR 1–4 allowed, RIR 0 forbidden | Moderate | Strength gains are similar across a wide RIR range; non-failure is at least as good for dynamic strength; hypertrophy improves closer to failure; RIR self-estimation carries meaningful error. ([Robinson 2024](https://doi.org/10.1007/s40279-024-02069-2); [Wu 2026](https://doi.org/10.1186/s13102-026-01861-z); [RIR-EVIDENCE](RIR-EVIDENCE.md)) | Supported and conservative |
| 5 | Accessories at RIR 2 with double progression | Moderate | The effort is defensible for a back-sensitive athlete, but hypertrophy-oriented accessory work may progress more slowly than a failure-inclusive programme. This is a deliberate trade-off, not an evidence claim that RIR 2 is optimal. | Coherent trade-off |
| 6 | Power work: box jumps 3×3–5, quality stop | Moderate for function, weak for this exact dose | Power training improves physical function in older adults, with low certainty; the exact 3–5 set prescription is practice, not a validated protocol. ([power meta-analysis](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9096601/)) | Keep, label as practice |
| 7 | 4-week undulating cycle | Moderate | Linear and undulating periodization produce comparable strength and body-composition outcomes. DUP is variety/fatigue management, not a superiority claim. ([Zhang 2026](https://doi.org/10.3389/fpubh.2026.1707627)) | Supported as structure, not advantage |
| 8 | Scheduled and reactive deload policy | Weak/Methodology | Practical deload recommendations exist, but the comparative evidence for a fixed deload schedule is thin. The implemented policy is a low-volume week every six weeks plus reactive triggers, explicitly framed as fatigue management rather than a proven strength intervention. ([practical deload review](https://shura.shu.ac.uk/35313/3/Bell-APracticalApproach%28AM%29.pdf)) | Implemented as a policy; evidence remains weak |
| 9 | Readiness reduces load, not volume | Moderate/Weak | Autoregulated load has not clearly beaten standard percentage prescription; readiness is a fatigue-management tool, not a proven strength optimiser. ([Hickmott 2022](https://doi.org/10.1186/s40798-021-00404-9)) | Reasonable safety choice |
| 10 | Trap-bar hinge is the main hinge; direct erector work is not stacked with it | Moderate for trap-bar biomechanics; methodology for the stacking rule | Trap-bar deadlift has lower peak lumbar moments than a straight bar. The no-stacking rule is plausible fatigue management but not established by trials. ([Swinton 2011](https://doi.org/10.1519/JSC.0b013e3181e73f87); [TRAINING-GUIDELINES](TRAINING-GUIDELINES.md)) | Trap-bar supported; stacking is methodology |
| 11 | Fixed continuity bands, now calibrated from returns | Weak for fixed cut-points; improving with calibration | Detraining occurs within weeks, but exact −5%/−10% cut-points are assumptions. The calibration model estimates observed e1RM retention per band and falls back to fixed values when a band is sparse. ([CONTINUITY](CONTINUITY.md); [Yamashita 2023](https://doi.org/10.1371/journal.pone.0288344)) | Honest and improving |
| 12 | Exercise selection can substitute variants | Weak for algorithmic selection; strong for specificity | Specificity matters; variation is not automatically beneficial. There is no trial showing algorithmic selection beats a fixed programme. Substituting a different load basis is a programme change, not a neutral swap. ([specificity review](https://pubmed.ncbi.nlm.nih.gov/7674868/); [exercise variation review](https://recyt.fecyt.es/index.php/retos/article/download/106279/80441)) | Useful shadow tool; needs guardrails |
| 13 | Strength is worth measuring for longevity | Moderate observational | Higher strength is associated with lower all-cause mortality; this is association, not proof that a particular programme causes longevity. ([Jochem 2019](https://doi.org/10.1016/j.jamda.2019.05.015)) | Supports the goal, not the exact dose |

### Evidence limitations

- Most sources are short-term resistance-training trials in varied populations; this athlete's
  back history and adherence pattern are not represented.
- Several programme rules are explicitly methodology, not evidence: direct-erector scheduling,
  the spinal-exposure cap, the exact accessory RIR floor, and the 3×/week structure.
- The e1RM and load solver introduce measurement error; the programme's apparent precision is
  greater than the underlying RIR/e1RM data.
- No evidence supports the current exercise-selection algorithm as a strength intervention.

---

## 3. Critique

### What is good

1. **The core strength dose is evidence-aligned.** Three full-body sessions, 3–5 reps on the
   main lifts, RIR 2 with a 1–4 window, and no failure is a coherent strength programme.
2. **It is safety-conscious without being fear-driven.** RIR 0 and max singles are excluded;
   direct erector work is separated from the hinge; trap bar is used; readiness can only reduce
   load. This fits a lifter with a back history.
3. **The deterministic layer is strong.** Loads are solved from lift-specific e1RM, every item
   cites a rule, constraints and injury signals are applied, and the LLM cannot compute or veto.
4. **Progression is explicit.** Double progression for accessories, e1RM-based loading for main
   lifts, and a configurable undulating cycle are all auditable.
5. **The system is honest about uncertainty.** The fatigue model is shadow-only, continuity now
   has a calibrated/fixed fallback, and the evidence notes distinguish assumptions from findings.
6. **The power and pulling additions are directionally right.** Power work and a vertical pull
   are better than a pure squat/bench/deadlift programme for a longevity-first athlete.

### What is weak or risky

#### A. Main-lift volume — applied

**Applied 2026-10-20 (Plan A + session types).** The original plan gave bench 12 sets/week,
squat 7 sets/week and hinge 4 sets/week once. The rolling programme initially restored squat but
left heavy hinge at 4 and squat at ~5.5; Plan A corrected that to squat **~7** and trap-bar
**~5** sets/week. The added hinge is a sumo deadlift support, a second heavy hinge exposure;
weekly hinge volume is now ~6.5 sets (5 trap-bar + 1.5 sumo), still below bench volume.

This is a **volume-first** resolution: the evidence favours added volume over added frequency
when weekly volume is matched, and a second heavy hinge would exceed the spinal cap. The spinal
cap remains the hard ceiling.

#### B. Power work loading — applied

**Applied 2026-10-20.** The power slot now uses `load_source: bodyweight`; it ignores stored
external load and e1RM history, carries no double-progression citation, and stops on quality
loss. `box_jump` remains bodyweight-only in the taxonomy. Loaded power work, if wanted,
must be a separate variation with its own prescription, not this slot.



#### C. Exercise selection comparability — applied

**Applied 2026-10-20.** The selector now classifies every candidate against the current lift:

- **A** — load-comparable; auto-eligible;
- **B** — near-comparable (same pattern, changed grip/bar/ROM/stability); explicit
  confirmation required;
- **C** — different lift/load basis; hidden by default and never applied automatically.

The load is always re-solved from the selected lift's own history; the old load/citation is not
transferred. The implementation is in `config/selection-comparability.v1.yaml`,
`prescribe/selection.py`, `prescribe/engine.py`, the CLI and the Prescribe panel. Evidence and
the class boundary are in [SELECTION-COMPARABILITY.md](SELECTION-COMPARABILITY.md)
(`DEC-SELECT-03`, Q21).

#### D. Scheduled deload — applied

**Applied 2026-10-20 (`DEC-PROGRAMME-05`).** A configurable low-volume week runs every six weeks
from the declared block anchor. It removes one set from each item (minimum two), reduces load
by 10% and adds one RIR under `MOD-DELOAD-001`; reactive triggers (two weeks over the spinal cap
or two flares) still apply. The evidence for a fixed deload is weak, so this is described as
fatigue management, not a proven strength intervention. The readiness set valve remains a
separate, within-week response.

#### E. Upper-body balance — applied

**Applied 2026-10-20.** The session types now include a horizontal row on every session and a
vertical press on the bench-heavy sessions; the vertical pull remains. This closes the original
gap without changing the bench main-lift volume.

#### F. Rolling next-session policy — applied

**Applied 2026-10-20.** New prescriptions use session types and a rolling next-session rule;
Canonical session types now replace the old labels. The forecast shows a
calendar, but the day's session is selected from the rolling balance rather than a strict
session-type sequence.

**Applied above:** the rolling rule preserves the main-lift balance without a strict weekly
A/B/C calendar. This is a scheduling policy, not a new training principle.

#### G. Readiness set reduction — applied

**Applied 2026-10-20.** Poor readiness can now reduce accessory sets by a configured amount as
well as reducing load and raising RIR. Main lifts keep their volume unless the config explicitly
includes essential work. Exercise selection remains restricted by the A/B/C comparability guard;
it is not a readiness-driven free swap.

#### H. Main-lift progression depends on e1RM estimates

The solver uses e1RM from recent sets, with calibration and decay. This is sensible, but it
inherits RIR estimation error and formula error. There is no top set/AMRAP or regular
submaximal test in the template; e1RM can drift without a deliberate calibration point.

**Suggestion:** keep the existing `test` command but schedule a 3RM/5RM check every 8–12 weeks,
or use a repeatable top-set standard. Do not add routine 1RM testing.

### Is it good?

**Yes as a safe, evidence-aware and now reasonably balanced strength programme. No as a
finished, validated or fully fatigue-managed programme.**

The core — 3×/week full body, 3–5 reps, RIR 2, no failure, autoregulated load, conservative
back rules — is defensible and better than most generic templates. The original weaknesses were
programme-design imbalances and one concrete power-load bug, not a bad philosophy.

The current template includes the fixes that mattered:

1. rebalanced hinge and squat volumes — **done** (Plan A + session types);
2. bodyweight-only power slot — **done**;
3. horizontal pulling and a vertical press — **done**;
4. comparability-guarded selection — **done**;
5. fatigue-management valve — **done**: readiness set reduction, volume cap, reactive and scheduled deload.

The remaining gaps are the calibration/validation items in §4, not a missing deload policy.

---

## 4. Suggested changes, prioritised

Status reflects the implementation, not only the original recommendation.

### Implementation checklist

- [x] Power work bodyweight/implement-only.
- [x] Rolling session types instead of rigid A/B/C.
- [x] Upper-body row in every session.
- [x] Overhead press on bench-emphasis sessions.
- [x] Readiness set reduction (accessories + main lifts) and editable valve.
- [x] Continuity calibration from observed returns, with fixed-band fallback.
- [x] Dorsiflexion readiness category for the tib-bar lift.
- [x] Volume v1: ledger, MEV/MAV/MRV, conservative MRV cap.
- [x] Selection comparability A/B/C guard.
- [x] Plan A: squat ~7 sets/week, trap-bar ~5 sets/week and sumo ~1.5 sets/week.
- [x] Scheduled deload / broader fatigue-management policy (`DEC-PROGRAMME-05`).
- [x] Under-MEV accessory progression (`MOD-VOL-002`).
- [x] MRV question closed — not estimable without independent volume variation; no experiment.
- [x] 3RM/5RM calibration cadence (`test --status`).
- [x] Explicit warm-up prescription (50/70/85 ramp).
- [x] Review closed: prospective validation is moved to ROADMAP §4.20 as a gate for a future candidate. The retrospective check rejected the current continuity/fatigue models; no prospective period is active.
- [x] Parent-variant e1RM ratios moved to ROADMAP §4.20. Weakness/injury targeting is deferred there (`DEC-SELECT-04/05`); only the display-only own-history context is implemented.

| priority | change | reason | effort | status |
|---|---|---|---|---|
| P0 | Fix power items: bodyweight/implement only, no e1RM/double progression | A loaded box jump is not the intended stimulus | Small | **Done** |
| P0 | Rebalance main-lift volume: restore squat and raise hinge volume without breaking the spinal cap | Current 4 hinge vs 12 bench and reduced squat was not a balanced strength dose | Medium | **Done** — Plan A, volume-first; hinge is ~6.5 sets/week (trap-bar + sumo) |
| P0 | Restrict automatic selection to load-comparable variants; require confirmation for different implements | Prevents a valid load solve from silently changing the stimulus | Medium | **Done** (A/B/C guard) |
| P1 | Add a horizontal row and a vertical press (3 sets each), or explicitly trade bench accessory volume | Upper-body balance and shoulder health | Small | **Done** |
| P1 | Add a scheduled low-volume week or a readiness set-reduction option | Set valve and scheduled/reactive deload policy exist; evidence is weak but the gap is now addressed | Medium | **Done** — set valve + scheduled deload (`MOD-DELOAD-001`) |
| P1 | Define a rolling next-session policy that preserves A/B/C balance across missed weeks | Current fixed sequence is brittle | Medium | **Done** (session types) |
| P2 | Schedule a 3RM/5RM calibration every 8–12 weeks; no routine 1RM | Keeps e1RM honest without adding maximal testing | Small | **Done** — 10-week reminder |
| P2 | Add warm-up/ramp sets to the prescription or document the assumption explicitly | The template only describes working sets | Small | **Done** — 50/70/85 ramp |
| P2 | Validate the calibrated continuity and selection models prospectively before letting them drive loads automatically | Avoid overfitting to a small, noisy log | Large | **Moved** to ROADMAP §4.20 — no candidate; current models failed the retrospective baseline |
| P3 | Parent-variant e1RM ratios and weakness/injury selection | Useful later, but not needed to fix the current programme | Large | **Moved** to ROADMAP §4.20; targeting deferred (`DEC-SELECT-04/05`) |

## 5. Bottom line

- **Evidence-aligned:** frequency, heavy main-lift reps, RIR buffer, no-failure, autoregulated
  load, trap-bar choice, measurable strength.
- **Methodology, not evidence:** erector scheduling, spinal cap, exact accessory RIR, 3×/week
  calendar.
- **Weakest links now:** data depth and future model validation; neither is a programme-design
  defect in the current template.
- **Verdict:** a good, safer and more balanced default for a back-sensitive lifter. The review
  is **closed**; future model/ratio/targeting work is in ROADMAP §4.20.

---

## 6. Sources

Primary sources used in this review:

- [Robinson et al. 2024, proximity to failure](https://doi.org/10.1007/s40279-024-02069-2)
- [Wu et al. 2026, non-failure vs failure](https://doi.org/10.1186/s13102-026-01861-z)
- [Refalo et al. 2023, failure and hypertrophy](https://doi.org/10.1007/s40279-022-01784-y)
- [Hammert et al. 2026, load specificity](https://doi.org/10.1007/s40279-025-02370-8)
- [2025 resistance-training dose response](https://link.springer.com/article/10.1007/s40279-025-02344-w)
- [Schoenfeld et al. 2017, weekly volume](https://www.tandfonline.com/doi/abs/10.1080/02640414.2016.1210197)
- [Frequency meta-analysis](https://pubmed.ncbi.nlm.nih.gov/30076500/)
- [Zhang et al. 2026, linear vs undulating](https://doi.org/10.3389/fpubh.2026.1707627)
- [Hickmott et al. 2022, autoregulation](https://doi.org/10.1186/s40798-021-00404-9)
- [Power training in older adults](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9096601/)
- [Practical deload review](https://shura.shu.ac.uk/35313/3/Bell-APracticalApproach%28AM%29.pdf)
- [Swinton et al. 2011, trap-bar biomechanics](https://doi.org/10.1519/JSC.0b013e3181e73f87)
- [Yamashita et al. 2023, detraining](https://doi.org/10.1371/journal.pone.0288344)
- [Jochem et al. 2019, strength and mortality](https://doi.org/10.1016/j.jamda.2019.05.015)
- [Specificity review](https://pubmed.ncbi.nlm.nih.gov/7674868/)
- [Exercise variation review](https://recyt.fecyt.es/index.php/retos/article/download/106279/80441)

Internal evidence notes: [`TRAINING-GUIDELINES.md`](TRAINING-GUIDELINES.md),
[`RIR-EVIDENCE.md`](RIR-EVIDENCE.md), [`TRAINING-DYNAMICS.md`](TRAINING-DYNAMICS.md),
[`CONTINUITY.md`](CONTINUITY.md), [`REFERENCES.md`](REFERENCES.md).

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
