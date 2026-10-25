# Parent-variant e1RM ratios and weakness — evidence review

**Status:** research note, 2026-10-25. No code, no selection rule, no prescription change.

## Question

Could a parent-variant e1RM ratio (for example, front squat ÷ back squat) be used as a
measure of muscle weakness, or is there a better way to estimate weakness?

## Bottom line

**No — a parent-variant ratio is not a measure of muscle weakness.** It is a *relative
performance ratio* between two specific tasks. It can be useful as a descriptive profile, or
as a prior when one variant has too little history, but it cannot identify a weak muscle or an
injured region on its own.

If the goal is weakness assessment, the defensible options are repeated task-specific strength
tests, and — where equipment exists — isometric or isokinetic force testing. None of those is
currently part of this app. Parent-variant ratios should stay **display-only** and must not
drive targeting.

---

## 1. What the ratio actually measures

For variants A and B:

```text
ratio = e1RM(A) / e1RM(B)
```

That number is jointly determined by:

- the external load basis and range of motion;
- bar/implement, stance, grip and technique;
- familiarity and practice with each variant;
- fatigue and readiness on the test day;
- the e1RM formula, rep cap and RIR error;
- the athlete’s leverage and anthropometry.

It is therefore a **task-relative performance profile**. Calling a low ratio “weakness” assumes
all those other causes are equal, which the ratio cannot establish.

## 2. Evidence

### 2.1 Specificity is strong; cross-variant transfer is not automatic

Resistance-training adaptations are specific to the mode and exercise used
([Morrissey 1995](https://pubmed.ncbi.nlm.nih.gov/7674868/)). Variants change mechanics,
load–velocity relationships and the load basis, so a ratio between them is not a clean
measurement of one muscle group:

- front squat versus back squat: different load–velocity relationships and mechanics
  ([Spitz 2019](https://doi.org/10.1519/JSC.0000000000002962);
  [Krzyszkowski 2020](https://doi.org/10.1080/02640414.2020.1766738));
- safety squat bar versus straight bar: different kinematics, kinetics and performance
  ([Johansson 2024](https://doi.org/10.1519/JSC.0000000000004719);
  [Vantrease 2021](https://doi.org/10.1519/JSC.0000000000003541);
  [Hecker 2019](https://doi.org/10.1519/JSC.0000000000002912));
- bench grip width changes the load–velocity relationship and 1RM
  ([Herrera-Bermudo 2024](https://doi.org/10.1519/JSC.0000000000004920);
  [Pérez-Castilla 2020](https://doi.org/10.1123/ijspp.2019-0549)).

This is why the app keeps variants distinct and re-solves loads from each lift’s own history.

### 2.2 Strength ratios and asymmetry are poor stand-alone diagnostics

Inter-limb strength asymmetry has inconsistent calculation methods, thresholds and reporting
([Parkinson 2021](https://doi.org/10.52082/jssm.2021.594)). The commonly used 10–15% threshold
is often not supported by appropriate evidence.

In sub-elite rugby players, no unilateral leg-strength measure was related to injury relative
risk; relative strength had only a weak association with time lost
([Helme 2023](https://doi.org/10.1016/j.ptsp.2023.05.003)).

A five-season study of 271 elite female footballers found preseason isokinetic testing had
**limited independent predictive utility** for noncontact lower-extremity injury; a lower
hamstring:quadriceps ratio had a modest association with higher risk, but the authors say it
should not be a stand-alone screen
([Seiler 2026](https://doi.org/10.1002/ksa.70623)).

The general screening critique is stronger still: to justify a screening test one needs a
prospective marker–injury relationship, adequate test properties and evidence that treating
the “high-risk” group is better than treating everyone. No sports-injury screening test has
adequate test properties for prediction
([Bahr 2016](https://doi.org/10.1136/bjsports-2016-096256)).

### 2.3 e1RM is itself noisy

e1RM is an estimate from a working set, adjusted by RIR. RIR error, rep-range extrapolation,
fatigue, technique and formula choice all contribute. A ratio between two noisy estimates is
noisier than either estimate, especially with sparse variant history.

This is not a reason to never display a ratio. It is a reason not to treat a ratio difference
as a diagnosis without uncertainty and repeated observations.

### 2.4 Individual response matters, but does not make the ratio diagnostic

Individual response variation is real and requires repeated within-person designs
([Robinson 2024](https://doi.org/10.1007/s40279-024-02050-z)). Auto-regulated exercise selection
produced small lean-mass and bench-press advantages in one small study, with no squat advantage
([Rauch 2020](https://doi.org/10.1519/JSC.0000000000002272)) — not evidence that the lowest
e1RM variant identifies a weak muscle.

### 2.5 No direct validation of parent-variant ratios as weakness

No study was found that validates cross-exercise e1RM ratios as a diagnostic of muscle
weakness, injury risk or the need to target a muscle. The literature supports *performance
profiling* and *specificity*, not a “weakness” interpretation.

## 3. What a low ratio could mean

Before calling it weakness, rule out:

1. **Specificity/familiarity** — the variant is less practiced; the ratio rises with exposure.
2. **Technique/leverage/ROM** — different bar, stance, grip or depth.
3. **Fatigue/readiness** — one test was on a bad day.
4. **Measurement error** — sparse sets, RIR error, formula/rep-cap differences.
5. **A real force deficit** — possible, but not identifiable from the ratio alone.

A ratio can be a prompt to review those five, not proof of number 5.

## 4. Better ways to assess strength/weakness

| method | what it measures | strengths | limits |
|---|---|---|---|
| Repeated 1RM/3RM/5RM or e1RM on the *same* lift | task-specific maximal strength | accessible; directly relevant; can track change | technique/effort dependent; e1RM noise; not muscle-specific |
| Isometric mid-thigh pull or isometric squat | force production in a fixed task | reliable when standardised; sensitive to change | equipment; task-specific; not a muscle diagnosis |
| Isokinetic dynamometry | joint torque at set angular velocities | precise joint-specific torque; good for H:Q ratios | laboratory cost; joint/task-specific; poor stand-alone injury prediction |
| Handheld dynamometry | isometric force in a clinical position | practical; useful for rehab monitoring | rater/position dependent; weak for whole-lift performance |
| Rate of force development / force–velocity profiling | force expression over time or load–velocity profile | identifies force vs velocity limitation | equipment and protocol expertise; not muscle-specific |
| EMG | muscle activation | research/technique context | activation is not strength; cannot diagnose weakness |
| Ultrasound/MRI | muscle size/quality | structural context | not function; not routine |
| Functional tests (hop, sit-to-stand) | task performance | practical | not a muscle-strength measure |
| Symptoms/pain | tolerance and context | relevant to injury constraints | subjective; not objective weakness |

### The most practical hierarchy for this app

1. **Own-lift repeated performance** — already available; use trend and uncertainty.
2. **Same-lift test** — a planned 3RM/5RM or repeatable submaximal set.
3. **Isometric test** — only if equipment and a standard protocol exist.
4. **Parent-variant ratio** — descriptive context only.
5. **Population ratios/norms** — not appropriate for an individual programme.

## 5. Recommendation

### What I would allow later

A **display-only relative performance profile**:

- formal `variant_of` relation, no silent conversion;
- paired observations under comparable rep/RIR/equipment conditions;
- minimum data per variant (not one set);
- ratio with a bootstrap/credible interval;
- label **“relative performance”**, never “weak muscle”;
- no ranking effect, no automatic selection, no injury inference.

### What I would not do

- infer a weak muscle from one ratio;
- use a low ratio to auto-select the variant;
- use ratios to predict or “fix” injury risk;
- compare variants with different load bases as if the ratio were a 1RM conversion;
- treat a 10–15% difference as a universal threshold.

### If weakness targeting is ever revisited

It still needs the gates already recorded in
[WEAKNESS-INJURY-SELECTION.md](WEAKNESS-INJURY-SELECTION.md): a pre-registered own-trend
definition, enough paired data, a retrospective baseline win and an opt-in N-of-1/alternating
test. Parent-variant ratios alone do not meet those gates.

## 6. Decision

1. Parent-variant ratios are **not** a weakness or injury measure.
2. They may be implemented later as a **descriptive prior/profile**, with uncertainty, and
   never as a load conversion or targeting rule.
3. The app’s first weakness assessment remains **own-lift repeated performance**; the next
   credible upgrade is a standardised same-lift test, not a cross-variant ratio.
4. No implementation now. Parent-variant ratios remain unscheduled in ROADMAP §4.20.2.

## Related

- **Weakness targeting:** [WEAKNESS-INJURY-SELECTION.md](WEAKNESS-INJURY-SELECTION.md)
- **Variant load basis:** [SELECTION-COMPARABILITY.md](SELECTION-COMPARABILITY.md)
- **Variant configuration:** [EXERCISE-VARIANTS.md](EXERCISE-VARIANTS.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)