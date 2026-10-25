# FORM RATING — PROSPECTIVE EVALUATION

**Status:** documentation and implementation complete 2026-10-25; prospective data collection open. No result yet. Descriptive only.
**Purpose:** test whether repeated low post-lift form ratings predict a worse next performance,
higher sRPE or a symptom flare — without changing training.

---

## 1. Anchors

Rate one exercise after its last set, 1–5:

| rating | anchor |
|---:|---|
| 5 | Intended technique on every rep; no compromise. |
| 4 | Minor deviation; no rep lost or materially altered. |
| 3 | Clear deviation in at least one rep; set completed as planned. |
| 2 | Multiple compromised reps, or a rep noticeably altered/partial; set completed only with modification. |
| 1 | Technique broke down; set stopped/aborted or unsafe to continue. |

Compare only within the same lift. A 3/5 on a squat is not the same as 3/5 on a curl.

## 2. Sampling

- Window: **12 weeks** from the start date. Historical backfilled ratings before the start date do not count as prospective events.
- Minimum before analysis: **10 low-form events (≤2)** across at least **4 lifts**.
- If fewer, extend to 24 weeks; do not analyse a handful of events.
- One rating per exercise/session; latest correction wins.
- Missing rating = unknown; no zero, no imputation.

## 3. Outcomes

Primary:

- **next-session e1RM** for the same lift / current-session best;
- **e1RM / prior 84-day best** for the rated session.

Secondary:

- session sRPE;
- any symptom flare in the 7 days after the session;
- per-rep velocity loss where captured.

## 4. Analysis

- descriptive medians for low (≤2) vs higher (≥3) ratings;
- within-lift comparison, not pooled across lifts;
- report n, missingness and confidence intervals where enough data;
- no fitted model, no p-value-driven policy;
- no causal language.

## 5. Decision rule

This evaluation **cannot** change a load, set, RIR, exercise selection or deload by itself.

A future change would require:

1. a stable signal across the window;
2. enough low-form events;
3. no increase in symptoms or missed work;
4. a separate decision with user approval.

## 6. What would count as a signal

A consistent direction with a confidence interval excluding no difference, plus a plausible
mechanism and no safety cost. A near-zero or inconsistent result means **keep it descriptive**;
do not add a form-based load rule.

## 7. Files

- `features/form_assessment.py` (`low_form_events`, trend)
- `docs/FORM-ASSESSMENT.md`
- `docs/FORM-USE-EVIDENCE.md`
- Outcomes **Form trend** and Review **Form context**
