# Strength programme review — 2026-10-20

**Scope:** the strength programme only. Cardio, video, the LLM narrative and the web UI are out
of scope. This is a review document; no code or configuration was changed.

**Implementation note (2026-10-20):** the P0/P1 fixes for power loading, hinge balance, rolling session types, upper-body row/press and readiness set reduction were subsequently implemented; selection comparability and a scheduled deload remain open. This document is the evidence snapshot, not a claim that every suggestion is still pending.

**Method:** read the templates, constitution, prescription engine, evidence notes and references;
generated A/B/C prescriptions from the local database; checked the planned weekly dose and the
main evidence claims against the cited literature. The local 12-week audit is in
`private/docs/STRENGTH-PROGRAM-AUDIT.md` (git-ignored, personal data).

---

## 1. The programme as implemented

### Weekly shape

| day | emphasis | main work | accessory work | sets |
|---|---|---|---|---:|
| A | squat | box jump, SSB squat 4×3–5, bench 4×3–5 | back extension 3×10–12, ab wheel 3×6–10, lateral raise 3×10–12 | 20 |
| B | hinge | trap-bar deadlift 4×3–5, narrow/pause bench 4×3–5 | pull-up/lat pulldown 3×6–10, lateral raise 3×10–12, split squat 3×8–10 | 17 |
| C | bench | bench 4×3–5, SSB squat 3×3–5 | back extension 3×10–12, hanging leg raise 3×8–12, split squat 3×8–10 | 16 |

Planned total: **53 working sets/week**, three sessions.

Main-lift frequency and volume:

| lift | sessions/week | sets/week |
|---|---:|---:|
| squat (SSB) | 2 | 7 |
| bench (competition/narrow/pause) | 3 | 12 |
| trap-bar deadlift | 1 | 4 |
| vertical pull | 1 | 3 |
| horizontal pull | 0 | 0 |
| vertical press | 0 | 0 |

### Effort and progression

- Main lifts: **RIR 2** target, allowed window **RIR 1–4**; RIR 0, max singles and 1RM testing
  inside a block are forbidden.
- Accessories: double progression, hold load until the top of the range on all sets at RIR ≥ 2,
  then add the smallest increment.
- Main-lift load: solved from the lift's own e1RM (Epley + RIR) with a bounded measured-test
  calibration and age decay.
- Undulation: 4-week cycle (strength / strength / maximal / strength; accessory / volume /
  accessory / volume), only when a block anchor is declared. No scheduled deload week.
- Readiness and continuity can reduce load and add RIR; the combined readiness + continuity
  reduction is capped at 20%. The fitness-fatigue model does **not** change loads.
- Exercise selection can apply at most one substitution per slot when explicitly enabled; the
  load is re-solved from the selected lift's history. The selector is Python-first; the LLM may
  only choose from the filtered list.

---

## 2. Evidence check

Legend: **Strong** = consistent meta-analytic evidence; **Moderate** = a reasonable body of
evidence with caveats; **Weak/Methodology** = plausible practice or product decision, not
settled by trials.

| # | Claim in the programme | Evidence status | What the evidence says | Verdict |
|---|---|---|---|---|
| 1 | 3×/week full-body is a good strength frequency | Moderate | When weekly volume is equated, higher frequency appears to help strength somewhat; 3× full-body is within the supported range. Frequency is not a free extra dose. ([frequency meta-analysis](https://pubmed.ncbi.nlm.nih.gov/30076500/); [2025 dose-response](https://link.springer.com/article/10.1007/s40279-025-02344-w)) | Supported |
| 2 | Weekly volume around the current plan is enough | Moderate, but uneven | Hypertrophy rises with weekly volume to roughly 10+ sets per muscle with diminishing returns; strength is less volume-dependent. The plan has 12 bench sets, 7 squat sets and 4 hinge sets per week, which is not a balanced strength dose. ([Schoenfeld 2017](https://www.tandfonline.com/doi/abs/10.1080/02640414.2016.1210197); [2025 dose-response](https://link.springer.com/article/10.1007/s40279-025-02344-w)) | Bench/squat supported; hinge under-dosed |
| 3 | Main lifts at 3–5 reps | Strong for strength | Heavy, lower-rep training is more specific for 1RM strength when effort is matched. ([Hammert 2026](https://doi.org/10.1007/s40279-025-02370-8)) | Supported |
| 4 | RIR 2 target, RIR 1–4 allowed, RIR 0 forbidden | Moderate | Strength gains are similar across a wide RIR range; non-failure is at least as good for dynamic strength; hypertrophy improves closer to failure; RIR self-estimation carries meaningful error. ([Robinson 2024](https://doi.org/10.1007/s40279-024-02069-2); [Wu 2026](https://doi.org/10.1186/s13102-026-01861-z); [RIR-EVIDENCE](RIR-EVIDENCE.md)) | Supported and conservative |
| 5 | Accessories at RIR 2 with double progression | Moderate | The effort is defensible for a back-sensitive athlete, but hypertrophy-oriented accessory work may progress more slowly than a failure-inclusive programme. This is a deliberate trade-off, not an evidence claim that RIR 2 is optimal. | Coherent trade-off |
| 6 | Power work: box jumps 3×3–5, quality stop | Moderate for function, weak for this exact dose | Power training improves physical function in older adults, with low certainty; the exact 3–5 set prescription is practice, not a validated protocol. ([power meta-analysis](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9096601/)) | Keep, label as practice |
| 7 | 4-week undulating cycle | Moderate | Linear and undulating periodization produce comparable strength and body-composition outcomes. DUP is variety/fatigue management, not a superiority claim. ([Zhang 2026](https://doi.org/10.3389/fpubh.2026.1707627)) | Supported as structure, not advantage |
| 8 | No scheduled deload; reactive deload only | Weak/Methodology | Practical deload recommendations exist, but the comparative evidence for a fixed deload schedule is thin. A reactive trigger is defensible; the absence of any planned fatigue management is a design choice with a cost. ([practical deload review](https://shura.shu.ac.uk/35313/3/Bell-APracticalApproach%28AM%29.pdf)) | Plausible, but a gap |
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

#### A. Main-lift volume is unbalanced — highest priority

The plan gives bench **12 sets/week across three sessions**, squat **7 sets/week across two**,
and hinge **4 sets/week once**. For a strength programme that is not a balanced stimulus. The
hinge is the lowest-volume main lift and the one with the most technical/spinal risk; one
exposure per week gives little practice and little strength-specific volume. The bench, by
contrast, gets three exposures and three times the sets.

This may be intentional because of the back history, but then it should be an explicit
trade-off, not an accident of the A/B/C template. The evidence supports 2–3 exposures for
strength and does not support treating the hinge as a once-weekly afterthought.

**Suggestion:** either add a second, lower-fatigue hinge exposure (e.g. a submaximal trap-bar or
RDL slot on Day A/C, respecting the erector rules) or reduce bench volume and explain the
priority. Target roughly 6–8 hinge sets/week if the back tolerates it; keep the spinal cap as
the hard ceiling.

#### B. Power work can be prescribed as a loaded lift

**Applied 2026-10-20.** The power slot now uses `load_source: bodyweight`; it ignores stored
external load and e1RM history, carries no double-progression citation, and stops on quality
loss. `box_jump` remains bodyweight-only in the taxonomy. Loaded power work, if wanted,
must be a separate variation with its own prescription, not this slot.

See [SELECTION-COMPARABILITY.md](SELECTION-COMPARABILITY.md) for the evidence and the proposed
three-class guard. No implementation yet.

#### C. Exercise selection has no comparability guard

The selector can substitute across variants with different load bases: SSB squat to front squat,
competition bench to dumbbell bench, trap-bar hinge to a very different variant. It re-solves the
load from the selected lift, which is mechanically correct, but the resulting session may no
longer be the intended stimulus. The LLM can only choose from the filtered list, which is good,
but the list itself is broad. This undermines the "one programme" idea.

**Suggestion:** distinguish **same-stimulus variants** (pause/narrow/competition bench; SSB/
high-bar/front squat with appropriate expectations) from **different lifts**. Keep the latter
out of automatic apply, or require explicit confirmation and show the load-basis difference.
The parent-variant e1RM ratio idea is relevant but not a substitute for a comparability flag.

#### D. No planned deload or volume autoregulation

The 4-week cycle varies reps but has no deload week; reactive deload only fires after two weeks
over the spinal cap or two flares. Readiness reduces load, not sets. The evidence for a fixed
deload is weak, but the programme has no general fatigue-management valve. A lifter who is
sleep-deprived, traveling or accumulating joint irritation can keep the same 53-set week with
only a load cut.

**Suggestion:** add one configurable low-volume week per 4–6 week cycle, or an optional
"reduce one set per slot" readiness response, kept in shadow until validated. Do not claim a
strength benefit; call it fatigue management.

#### E. Upper-body balance is incomplete

There are 12 bench sets/week but **no horizontal row and no vertical press**. The only pull is
three sets of vertical pull. For shoulder health and general strength, a horizontal pull and an
overhead press are conspicuous gaps. The actual log contains rows and overhead presses, so the
programme is narrower than the athlete's practice.

**Suggestion:** add 3 sets of a horizontal row and 3 sets of a vertical press, or explicitly
replace some bench accessory volume. This is a balance/longevity change, not a claim that it
increases bench strength.

#### F. The 3×/week assumption is not robust to missed sessions

The programme is a fixed A/B/C sequence. When sessions are missed, the day sequence does not
automatically rebalance; the forecast uses a calendar and the log's day inference is often
`unknown`. A strength programme should survive a two-session week without silently skipping the
hinge or doubling bench.

**Suggestion:** define a rolling "next session" rule that preserves the main-lift balance over
2–3 weeks, rather than a strict weekly A/B/C calendar. This is a scheduling policy, not a new
training principle.

#### G. Readiness changes load but not the rest of the dose

If readiness is low, load drops and RIR rises, but set count and exercise selection stay. That is
a reasonable safety-first response, but it can leave a fatigued athlete doing the same volume at
lighter loads. The evidence does not say this is wrong; it is a design gap worth measuring.

#### H. Main-lift progression depends on e1RM estimates

The solver uses e1RM from recent sets, with calibration and decay. This is sensible, but it
inherits RIR estimation error and formula error. There is no top set/AMRAP or regular
submaximal test in the template; e1RM can drift without a deliberate calibration point.

**Suggestion:** keep the existing `test` command but schedule a 3RM/5RM check every 8–12 weeks,
or use a repeatable top-set standard. Do not add routine 1RM testing.

### Is it good?

**Yes as a safe, evidence-aware strength skeleton. No as a finished, balanced strength
programme.**

The core — 3×/week full body, 3–5 reps, RIR 2, no failure, autoregulated load, conservative
back rules — is defensible and better than most generic templates. The weaknesses are mostly
programme-design imbalances and one concrete power-load bug, not a bad philosophy.

I would not run the current template unchanged for a lifter whose primary goal is strength. I
would run it after:

1. rebalancing the hinge and bench volumes;
2. fixing the power slot;
3. adding horizontal pulling and a vertical press;
4. restricting automatic selection to comparable variants;
5. adding a fatigue-management valve (deload or set reduction).

---

## 4. Suggested changes, prioritised

No implementation here; this is the recommendation list.

| priority | change | reason | effort |
|---|---|---|---|
| P0 | Fix power items: bodyweight/implement only, no e1RM/double progression | A loaded box jump is not the intended stimulus | Small |
| P0 | Rebalance main-lift volume: second hinge exposure or lower bench volume; target ~6–8 hinge sets/week | Current 4 vs 12 is not a balanced strength dose | Medium |
| P0 | Restrict automatic selection to load-comparable variants; require confirmation for different implements | Prevents a valid load solve from silently changing the stimulus | Medium |
| P1 | Add a horizontal row and a vertical press (3 sets each), or explicitly trade bench accessory volume | Upper-body balance and shoulder health | Small |
| P1 | Add a scheduled low-volume week or a readiness set-reduction option | No general fatigue valve today; evidence is weak but the gap is real | Medium |
| P1 | Define a rolling next-session policy that preserves A/B/C balance across missed weeks | Current fixed sequence is brittle | Medium |
| P2 | Schedule a 3RM/5RM calibration every 8–12 weeks; no routine 1RM | Keeps e1RM honest without adding maximal testing | Small |
| P2 | Add warm-up/ramp sets to the prescription or document the assumption explicitly | The template only describes working sets | Small |
| P2 | Validate the calibrated continuity and selection models prospectively before letting them drive loads automatically | Avoid overfitting to a small, noisy log | Large |
| P3 | Parent-variant e1RM ratios and weakness/injury selection | Useful later, but not needed to fix the current programme | Large |

## 5. Bottom line

- **Evidence-aligned:** frequency, heavy main-lift reps, RIR buffer, no-failure, autoregulated
  load, trap-bar choice, measurable strength.
- **Methodology, not evidence:** erector scheduling, spinal cap, exact accessory RIR, 3×/week
  calendar.
- **Weakest links:** hinge volume/frequency, power-load handling, selection comparability,
  absence of a general deload/volume valve, and upper-body balance.
- **Verdict:** a good foundation and a safe default for a back-sensitive lifter; not yet a
  well-balanced strength programme.

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
