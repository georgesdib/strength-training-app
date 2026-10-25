# Weakness targeting and testing — plan

**Status:** plan only, 2026-10-25. No targeting is implemented. Weakness targeting remains
unscheduled and gated by `DEC-SELECT-04/05`; injury targeting remains unscheduled.

## 1. What this plan is — and is not

This plan defines how a **weakness-targeted selection rule** could be tested later. It is not
permission to add one now.

- **Weakness** here means a target lift’s own performance is below its recent own trend by a
  pre-declared, uncertainty-aware amount. It does **not** mean a parent-variant e1RM ratio, a
  population ratio, a muscle-activation deficit or an injury.
- **Targeting** means explicitly choosing or adding a lift for a slot because of that deficit.
  It does not mean automatic substitution, and it never overrides constraints, readiness or
  the injury signal.
- **Injury targeting** is out of scope. Injury remains exclusion/penalty/ceiling only.

Parent-variant ratios are not a weakness measure; see
[PARENT-VARIANT-WEAKNESS-EVIDENCE.md](PARENT-VARIANT-WEAKNESS-EVIDENCE.md).

## 2. Preconditions (all required)

1. **Stable programme and logging:** at least 12 weeks under the current programme with
   reliable live-workout/import quality.
2. **Data volume:** at least 12 sessions for the target lift across those 12 weeks, plus
   comparable sessions for the guardrail lifts.
3. **Prescription snapshots:** live Workout mode, so planned versus actual is known.
4. **Effort data:** RIR coverage adequate for e1RM; otherwise the weakness metric is `unknown`.
5. **Symptoms:** explicit region/level entries; no missing symptom data treated as “no flare.”
6. **A pre-registered target:** one lift, one variant definition and one outcome before looking
   at the comparison.

If any precondition fails, the answer is `unknown`, not a targeting trial.

## 3. Weakness metric (pre-register before analysis)

Use **own-lift repeated performance**, not a cross-variant ratio:

```text
deficit = target_lift_recent_baseline - target_lift_current_trend
```

Rules to freeze:

- target lift and canonical variant;
- e1RM formula/version and rep cap;
- baseline window (for example 6–8 weeks) and current window (for example 3–4 weeks);
- minimum observations per window;
- robust estimator (median/trend with uncertainty), not a single session;
- minimum meaningful deficit, justified by the e1RM noise floor — not an arbitrary percentage;
- missing-data rule: `unknown` if the windows cannot be estimated;
- no use of parent-variant ratios, bodyweight norms or population percentiles.

The exact thresholds are deliberately **not chosen here**; they must be set before the
retrospective screen and must not move after it.

## 4. Phase 0 — evidence and rule definition (mostly complete)

| deliverable | status |
|---|---|
| Evidence review for weakness/asymmetry/screening | done in [WEAKNESS-INJURY-SELECTION.md](WEAKNESS-INJURY-SELECTION.md) |
| Parent-variant ratio review | done in [PARENT-VARIANT-WEAKNESS-EVIDENCE.md](PARENT-VARIANT-WEAKNESS-EVIDENCE.md) |
| Pre-registered metric and target | not started; needs Phase 1 data first |

## 5. Phase 1 — data collection and audit

Collect, without changing selection:

- per-session target-lift sets, load, reps, RIR and e1RM method;
- session type and whether the target lift was prescribed, substituted or extra;
- readiness, recent stress and symptom entries;
- guardrail outcomes for the other main lifts;
- attendance, completion and any missed sessions;
- all selection applications and their reasons.

Deliverable: a data-quality report stating comparable observation counts and any confounders.
No rule is evaluated until this report is accepted.

## 6. Phase 2 — retrospective screen (not causal proof)

Compare, chronologically:

1. **Fixed selection** — current template/rotation.
2. **Weakness-targeted selection** — the pre-registered rule, evaluated on the same dates.

Because historical selection was not randomised, this can only screen for a promising rule. It
cannot prove that targeting caused an improvement.

Metrics:

- primary: target-lift e1RM change, measured under comparable conditions;
- guardrails: other main-lift e1RM, attendance/completion, symptom flares, back tolerance;
- process: how often the rule would have changed a slot, and how often it was blocked.

Screen passes only if the targeted rule beats fixed selection on the primary outcome with an
uncertainty interval excluding no meaningful difference, and does not worsen guardrails.

## 7. Phase 3 — opt-in N-of-1 / alternating blocks

Only if Phase 2 passes and the athlete explicitly opts in:

- alternate **fixed** and **targeted** blocks (for example 4-week blocks) with a pre-declared
  order such as A-B-B-A to reduce drift;
- keep all other programme rules, constraints, readiness and injury handling identical;
- define the target-lift test at the end of each block under the same conditions;
- primary outcome: target-lift e1RM;
- secondary: other main lifts, symptoms, attendance, session completion;
- analysis: paired within-athlete differences with bootstrap/interval estimates; no optional
  stopping and no changing the rule after seeing a block;
- minimum: at least three paired blocks or 24 weeks if feasible; otherwise report `unknown`.

This is a single-athlete experiment, not a population trial. It can support a personal
decision; it cannot establish a general rule.

**Stop rules:** new/worsening symptom pattern, target-lift decline beyond the pre-declared
guardrail, or decline in another main lift. Stop and review; do not push through.

## 8. Phase 4 — decision

Choose one:

- **keep fixed** — no targeting;
- **display-only** — show the deficit as context, no ranking effect;
- **bounded opt-in targeting** — only after Phase 3, only with explicit apply, only within
  constraints, and never automatic.

No decision may be made from the retrospective screen alone.

## 9. What would be implemented only after approval

- a config-driven target and metric version;
- selection provenance showing why a slot changed;
- UI/CLI display of the deficit with n and uncertainty;
- tests for leakage, missing data, guardrails and refusal;
- an audit trail of every applied rule and outcome.

## 10. Explicit non-goals

- No parent-variant ratio as a weakness diagnosis.
- No injury-targeted positive selection.
- No automatic substitution or load change.
- No population-norm “weak muscle” label.
- No optimiser, ML or LLM-generated targeting.

## 11. Gates and sequence

| phase | gate |
|---|---|
| 0 | evidence and metric review |
| 1 | 12 sessions / 12 weeks and data-quality report |
| 2 | retrospective screen beats fixed selection; guardrails safe |
| 3 | opt-in N-of-1/alternating blocks; at least three pairs or report unknown |
| 4 | keep fixed, display-only, or bounded opt-in targeting |

Earliest review remains after v0.4/~April 2027 (`DEC-SELECT-05`). The date is a gate, not a
commitment.

## Related

- **Weakness evidence:** [WEAKNESS-INJURY-SELECTION.md](WEAKNESS-INJURY-SELECTION.md)
- **Parent ratios:** [PARENT-VARIANT-WEAKNESS-EVIDENCE.md](PARENT-VARIANT-WEAKNESS-EVIDENCE.md)
- **Selection comparability:** [SELECTION-COMPARABILITY.md](SELECTION-COMPARABILITY.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)