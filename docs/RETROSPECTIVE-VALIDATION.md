# RETROSPECTIVE WALK-FORWARD — method and result

**Status:** implemented 2026-10-20. This is retrospective, not prospective.
**Command:** `strength-coach validate --max-dates 12` (also on the Prescribe page).

It changes no prescription, load or model parameter.

---

## 1. Method

For each evaluation date:

1. fit/model on data strictly before that date;
2. predict the next observed session outcome;
3. compare with a simple baseline;
4. move forward and repeat.

- **Continuity:** at each observed return, fit the continuity calibration on the prefix and
  compare its factor with the fixed rule and the actual e1RM ratio.
- **Fatigue:** at each cutoff, fit the strength fitness-fatigue model on the prefix and predict
  the next observed e1RM for a lift; baseline is persistence (last observed e1RM).
- **Volume:** no predictive volume model exists; only descriptive/causal limits are reported.
- **Selection:** no counterfactual exists (one exercise per slot), so it is excluded.

The report uses only earlier data per date, but the candidate models and features were chosen
with knowledge of the full dataset. That is why it is retrospective. Exact counts and dates are
kept in the private audit record.

## 2. Result (small retrospective sample)

| model | predictions | relative MAE | baseline MAE | skill |
|---|---:|---:|---:|---:|
| Strength fatigue | a small number of lift-sessions | worse | persistence baseline | **−112%** |
| Continuity calibration | one per observed return | worse | fixed rule | **−17%** |

Both models are **worse than the simple baseline** in this retrospective check.

Volume has no predictive model; selection has no counterfactual.

## 3. Interpretation

- The fatigue model should **not** be adopted, and should not drive a load.
- The calibrated continuity factor should **not** replace the fixed fallback.
- No prospective shadow period is started for these candidates: they failed the retrospective
  screen first.
- This is a small, single-athlete, non-stationary record. The result is enough to reject
  adoption, not enough to prove the models can never work.
- If a future model beats these baselines retrospectively, the next step is a frozen
  prospective test, not immediate use.

## 4. What would count as a positive result

- a pre-declared improvement over the persistence/fixed baseline;
- a confidence interval excluding no difference;
- no safety or calibration failure;
- then a frozen prospective period with no retuning.

Until then: keep fixed continuity, keep the fatigue model shadow-only, and keep volume/selection
decision rules conservative.
