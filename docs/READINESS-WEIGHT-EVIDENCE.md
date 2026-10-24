# Readiness weights — evidence and sensitivity check

**Status:** closed. Fixed, transparent weights are retained; learned individual weights are not
adopted.
**Date:** 2026-10-20

This note records the evidence for readiness weighting, the constrained comparison requested
before any learned model, and the decision not to learn weights from the existing data.

---

## 1. Evidence

| claim | evidence | strength / limit |
|---|---|---|
| Subjective self-reports are more sensitive to acute/chronic training load than most objective measures | Saw et al. 2016 systematic review, 56 studies | Moderate; heterogeneous measures, no universal questionnaire |
| A multi-item wellness index can track recovery/staleness | Hooper et al. 1995; Bell et al. 2025 (squat overreaching) | Moderate for trend; **no validated weighting of items** |
| Pretraining wellness is associated with subsequent training load | Govus et al. 2018 | Observational; not a prescription rule |
| Sleep restriction impairs maximal strength in compound movements | Knowles et al. 2018 systematic review | Moderate/weak quality; single-joint less affected |
| HRV-guided training improves vagal indices; performance benefit is small/not clearly significant | Manresa-Rocamora et al. 2021 meta-analysis | HRV is context/trend, not a hard daily gate |
| Perceived readiness can relate to performance | Munteanu et al. 2026, 28 trained females, two mesocycles | Emerging, small; not a validated per-lift scale |
| No validated composite weights or cut-points | Readiness-score review | The current equal weights and thresholds are policy, not measurement |
| No validated learned individual readiness weights | No trial or validation study identified | A learned model would require prospective, held-out validation |

Sources and DOIs are recorded in [`READINESS-SCORE.md`](READINESS-SCORE.md) §1.

### What the evidence supports

- tracking wellness as a **trend**;
- using sleep/energy as a safety floor;
- using HRV/RHR as low-weight context;
- keeping the score transparent.

### What it does not support

- specific weights for sleep, energy, mood, soreness or HRV;
- a learned individual weight vector from one athlete’s fixed programme;
- using readiness to justify automatic main-lift volume changes.

---

## 2. Constrained sensitivity check

Rather than fit free weights, three transparent schemes were compared:

| scheme | subjective core | HRV/RHR |
|---|---|---|
| current | each weight 1.0 | 0.5 |
| sleep-heavy | sleep/energy 2.0, rest 1.0 | 0.5 |
| HRV-low | each weight 1.0 | 0.25 |

Outcomes:

- performance ratio: session best e1RM / prior 84-day best for the same lift;
- sRPE where available.

The late period (from 2025-07-01) is the held-out evaluation window; it was not used to choose
the schemes.

### Results

**All sessions with readiness + performance (full sample):**

| scheme | performance ρ | sRPE ρ |
|---|---:|---:|
| current | 0.118 | -0.054 |
| sleep-heavy | 0.107 | -0.040 |
| HRV-low | 0.118 | -0.054 |

**Held-out late period (late subset):**

| scheme | performance ρ | sRPE ρ |
|---|---:|---:|
| current | -0.004 | -0.075 |
| sleep-heavy | -0.057 | -0.052 |
| HRV-low | -0.017 | -0.061 |

Readiness below vs at/above 0.75 in the late period:

| scheme | low median ratio | high median ratio |
|---|---:|---:|
| current | 0.968 | 0.981 |
| sleep-heavy | 0.980 | 0.961 |
| HRV-low | 0.955 | 0.980 |

### Interpretation

- No alternative scheme improves the association out of sample.
- The current equal-weight score performs as well as the alternatives in the held-out period.
- All associations are weak; this is consistent with readiness being context, not a precise
  predictor.
- The late-period performance association is essentially zero, so there is no justification
  for a more complex weighting.

---

## 3. Decision

**Keep the fixed score:** equal subjective weights, HRV/RHR at 0.5, sleep/energy safety floor.

Do not learn individual weights from this dataset. The dataset is large in sessions but small
in independent variation, and readiness already influences the prescription.

Revisit learned weights only if:

- prospective data include an independent outcome;
- enough poor-readiness days exist;
- a held-out comparison beats the fixed score;
- the result does not increase symptoms or missed sessions.

---

## 4. Limitations

- Retrospective and observational.
- Performance ratio is model-derived from e1RM, not a measured test.
- Readiness is used to change load/sets, creating circularity.
- HRV/RHR coverage and wearable blending vary by date.
- sRPE is available for a subset of sessions, not all.
- The late window is a small subset.

This is enough to reject a more complex weighting scheme; it is not enough to validate a
different one.

---

## 5. What stays

- Fixed transparent readiness score.
- Sleep/energy floor.
- Per-lift readiness as a downward-only advisory.
- Descriptive readiness–performance monitoring on the progress dashboard.
- No learned weights. Main-lift set reduction is opt-in (`DEC-READINESS-12`); it is not automatic.
