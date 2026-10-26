# TRAINING GUIDELINES — external evidence check on the programme

Purpose: check a fixed-methodology strength programme against published resistance-training
evidence, and record where they agree, where they differ, and where the literature is too
weak to settle anything.

This file is about the strength programme. The wider question — whether the programme covers
the *modalities* that matter for a longevity-first goal (cardio, power, pulling, assessment) —
is reviewed in [`LONGEVITY-REVIEW.md`](LONGEVITY-REVIEW.md).

**The programme's constitution wins every conflict** — it is the product's methodology. This
file only says where a rule is well supported, over-constrained, or unsupported.

**Honesty note:** several full texts were paywalled or blocked when checked. Where that
happened the finding is cited at the level reported in the abstract or title and marked
`[title/abstract only]`. No effect sizes are quoted that were not verified.

---

## 1. Volume: sets per muscle per week

The best-known dose-response review finds hypertrophy increasing with weekly volume up to
roughly 10+ sets per muscle group per week, with diminishing returns beyond (Schoenfeld,
Ogborn & Krieger, *J Sports Sci* 2017 —
[tandfonline](https://www.tandfonline.com/doi/abs/10.1080/02640414.2016.1210197)). A 2024
meta-analysis models dose-response across strength, hypertrophy and other outcomes and finds
the shape differs by outcome
([Sports Medicine 2024](https://link.springer.com/content/pdf/10.1007/s40279-024-02006-3)),
so a single "sets per week" target cannot serve both goals.

**Implication for a 3x/week full-body programme:** it is fully compatible with this, *because*
every session touches every muscle group. The meaningful audit is therefore not sessions per
week but **sets per muscle group per week**, which most logging apps never compute.
Recommendation: add `sets_per_muscle_group_per_week` to the feature store, keyed off the
exercise taxonomy rather than the raw muscle label.

## 2. Frequency

The meta-analyses disagree in emphasis, so the honest summary is narrow. When weekly volume is
equated, the hypertrophy advantage of training a muscle more often is small but not always
zero: Schoenfeld 2016 found twice-weekly per muscle superior to once-weekly, while the 2025
dose-response meta-regression could not distinguish a frequency effect on hypertrophy from zero
([Schoenfeld 2016](https://doi.org/10.1007/s40279-016-0543-8);
[2025 meta-regression](https://link.springer.com/article/10.1007/s40279-025-02344-w)). For
strength, Grgic 2018 found the frequency effect disappeared when volume was equated, whereas
the 2025 model still found a positive frequency slope
([Grgic 2018](https://doi.org/10.1007/s40279-018-0872-x)). The consistent reading is that
**frequency mostly distributes volume, and training a muscle once a week is the weak end of the
range**; whether 3x beats 2x is unresolved.

**Implication:** 3x/week full-body is a defensible distribution, not a free extra dose. A rule
like "missed sessions must not leave any muscle group without stimulus for a week" is a
*practical robustness* rule, not a frequency-science claim. Fewer sessions at the same
per-session dose means less weekly volume; see
[FREQUENCY-AND-VOLUME.md](FREQUENCY-AND-VOLUME.md).

## 3. Proximity to failure

A 2024 series of meta-regressions on estimated proximity to failure finds hypertrophy benefits
from training closer to failure, while strength effects are less clear-cut
([Sports Medicine 2024](https://link.springer.com/article/10.1007/s40279-024-02069-2)).

**Implication:** the window is now RIR 1-4 with a 2-3 target (`DEC-RIR-02`,
[evidence](RIR-EVIDENCE.md)). It remains a conservative choice — failure is not required, and
RIR estimation is imprecise — but RIR 1 is a legitimate strength exposure, so the rule no longer
forbids it. The consequence worth stating plainly:

> Main lifts are still never taken to failure, and accessories only progress at RIR >= 2. That
> is a legitimate choice for a lifter managing symptoms — but it means **hypertrophy-oriented
> accessory work may progress more slowly than a failure-inclusive programme.** A critique must
> not score "too easy" as a failure when the constitution forbids the alternative.

It also couples to Q1: if the modal RIR value is a default rather than a real rating, apparent
average effort is understated and the prescription is systematically too light.

## 4. VBT and velocity loss

Velocity loss is defined from the series of per-rep velocities inside a set; the literature
reports mean propulsive velocity per repetition across a set
([Physiological Reports](https://physoc.onlinelibrary.wiley.com/doi/pdfdirect/10.1113/EP093514)).
Many exports store only one **average** velocity per set, in which case within-set velocity
loss is **not computable** — a single mean has no within-set variance.

**Implication:** any rubric line about "adherence to the velocity-loss cutoff" must either be
dropped or explicitly relabelled as a set-to-set decay proxy. This is an arithmetic
limitation, not a data-quality complaint.

## 5. Load monitoring (ACWR)

Acute:chronic workload ratio is **contested** — the "sweet spot" interpretation has been
directly challenged ([Europe PMC 7485291](https://europepmc.org/article/pmc/7485291)), and
workload monitoring is broader than a single ratio
([Gabbett, 2017](https://www.taylorfrancis.com/chapters/edit/10.4324/9781315542348-9/workload-monitoring-athlete-management-tim-gabbett)).
**Decision:** ACWR is computed as an advisory feature only and may never veto a prescription.

## 6. Where the literature is too weak to settle the programme

These are domain judgements in the constitution, not literature deficits. Do not over-claim
support for them:

| Rule | Evidence status |
|---|---|
| Direct erector work is its own progression, dose-ramped over 8-12 weeks | **No comparable prospectively-validated protocol found.** A clinical caution is a perfectly good reason; it is not an evidence-based protocol. |
| Never stack a hinge plus direct erector work in the same session | **Plausible fatigue-management logic, not established by trials.** Keep it; label it a methodology choice. |
| Use high handles on a trap bar if low handles irritate the back | Sound practical reasoning; not a trial result. |
| Power work: 3-5 reps, full recovery, stop on decline | Consistent with general power-training practice, but **cannot be scored** when the export has no per-rep power data. |

## 7. How weakness-targeted exercise selection should work

"We add exercises for your weaknesses" is where a fixed-methodology coach most easily drifts
into a chatbot inventing programmes. Two guardrails:

1. **A weakness must be evidenced** — a measured ratio outside a configured band, a stalled
   e1RM over N sessions, a movement pattern with insufficient weekly sets, or a reported
   symptom. "The model thinks the posterior chain is weak" is not evidence.
2. **A weakness may only select from a pre-approved exercise pool.** Adding a *new* exercise
   to the pool is a user decision, recorded in the taxonomy config, after which it appears in
   the baseline automatically.

A useful corollary: the **most-logged** lift is not automatically the weakest, and a programme
that allocates time by logging frequency will over-serve whatever the athlete enjoys or tracks
most. Allocation must follow evidence, not volume.

## 8. Anomaly detection that is evidence-based, not aesthetic

Programme audits should look for *regime changes* rather than judging individual sessions:

- a main lift's monthly volume collapsing to zero while a substitute rises (a common signature
  of an irritation being worked around),
- grinding counts rising alongside a volume peak,
- a lift's velocity or e1RM trending down while its volume trends up,
- near-empty months that are breaks rather than missed sessions.

These are questions to ask the athlete, not verdicts. A substitution pattern that looks like
avoidance may be a correct clinical decision. The main-lift/substitute check is implemented as
the read-only [`regime` command and Prescribe panel](REGIME-CHANGE.md).
