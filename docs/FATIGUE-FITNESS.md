# Fatigue, fitness, and strength: evidence and options

**Status: research note (2026-10-20). No model is implemented.** The current programme changes
loads from readiness and history; it does not carry a session-level fatigue state forward. This
note asks whether it should, what the evidence supports, and what the alternatives are.

Short answer: **a workout does contribute to fatigue, but the evidence for a strength-specific
fitness-fatigue model is not strong enough to let one change prescriptions.** A shadow model now
fits per-lift fitness/fatigue state for display; it does not read into a load. The app also
captures the practical consequence through self-reported readiness.

---

## 1. What the app does today

| mechanism | what it does | what it does **not** do |
|---|---|---|
| readiness score | global 0–1 from sleep/energy/mood/stress/soreness (plus HRV/RHR baseline and optional wearable blend); category overrides | no per-lift readiness; no post-session fatigue |
| `MOD-FAT-001` | reduces load up to 5% and raises RIR when readiness is low | does not know what you lifted yesterday |
| e1RM | best usable Epley+RIR estimate in the **84-day** window, or a measured override | does not decay the estimate after a hard session |
| gap rules | 14/28/56-day bands reduce load and step back the erector ramp | a 48-hour turnaround is "no gap" |
| deload | readiness/block rules can reduce the week | no accumulated-load or fitness-fatigue state |

So a very hard Monday does not directly change Wednesday's prescription. Only the readiness you
report on Wednesday does. That is conservative and defensible, but it means the app treats a
workout as a **history record**, not as a stress that decays.

---

## 2. The classic model and the strength evidence

The fitness-fatigue (Banister) model represents performance as a slow positive adaptation minus a
fast negative response:

```
P(t) = P0 + k1 * Σ w_i * exp(-(t - t_i)/τ1) - k2 * Σ w_i * exp(-(t - t_i)/τ2)
```

- `w_i` — training load for session `i` (TRIMP, volume load, sRPE, …)
- `τ1` — fitness decay (slow), `τ2` — fatigue decay (fast)
- `k1`, `k2` — fitness and fatigue multipliers
- `P0` — baseline performance

**The strength-specific evidence is thin.** The most direct study is small: six elite
weight-lifters over one year, with individually fitted parameters; predicted and actual
performance correlated in each subject, but the fatigue index "remains to be clarified"
([Busso 1990](https://doi.org/10.1007/BF00236693), ref 94). Applications and validations are
overwhelmingly endurance-based. We found no trial showing that changing strength loads *because of* a
fitted fitness-fatigue model improves strength outcomes.

The model is also statistically fragile:

- Parameters are ill-conditioned and sensitive to starting values, fitting method and the load
  metric ([Hellard 2006](https://doi.org/10.1080/02640410500244697), ref 64;
  [Vermeire 2022](https://doi.org/10.1123/ijspp.2021-0494), ref 97).
- In a Bayesian re-analysis of two independent datasets, the model was non-identifiable and the
  fatigue component **did not improve out-of-sample prediction** over a fitness-only model
  ([Marchal 2025](https://doi.org/10.1038/s41598-025-88153-7), ref 98).
- The choice of load metric changes when training is estimated to have its peak positive effect
  by up to ~20 days ([Vermeire 2021](https://doi.org/10.1123/ijspp.2020-0662), ref 96).
- The app has an additional problem: its training log has **no session-RPE for strength** and no
  frequent maximal performance test, so the two inputs a fit would rely on are sparse or noisy.

This does not make the physiology wrong. It means the model is a **descriptive, data-hungry
approximation**, not a validated individual controller.

---

## 3. What strength recovery actually looks like

The acute evidence is more useful than the model:

- Training to failure slowed recovery of jump height and bar velocity at **24–48 h**
  (measurements extended to 72 h), compared with the same volume split into sets of 5
  ([Morán-Navarro 2017](https://doi.org/10.1007/s00421-017-3725-7), ref 99).
- A review of 24 recovery studies concludes that failure, higher volume, lower-body/multi-joint
  work, eccentric emphasis and long-muscle-length positions increase recovery demands, with wide
  individual variation ([Sousa 2024](https://doi.org/10.5114/jhk/186659), ref 100).
- Three full-body sessions per week already leave ~48–72 h between similar work. That spacing is
  a practical fatigue-management rule, not a modelled state.

The app's programme is deliberately nowhere near failure (RIR 1–4, target 2–3), which is the
single most effective recovery lever in that literature. A fatigue model would mostly be
re-deriving what the RIR window and the 48–72 h spacing already enforce.

---

## 4. Why a fitted strength model would be hard here

A per-lift model needs:

| input | what the app has | problem |
|---|---|---|
| session load | sets × reps × load × RIR | no consensus metric; volume load ignores proximity to failure, RIR is ordinal |
| performance observation | e1RM from working sets; measured test every ~8–12 weeks | e1RM is itself an estimate with RIR error; tests are sparse |
| training dates | yes | 3 sessions/week, little within-week variation |
| fatigue observation | self-reported readiness | global, not per lift; not a performance measure |

RIR estimates are systematically imperfect: predicted RIR differed from actual by ~2 reps at
1 RIR, ~3.7 at 3 RIR and ~5 at 5 RIR in one squat study
([Zourdos 2021](https://doi.org/10.1519/JSC.0000000000002995), ref 101); errors were similar
across single- and multi-joint exercises and training experience
([Remmert 2023](https://doi.org/10.1177/00315125231169868), ref 102). That error propagates
directly into any e1RM series used to fit a curve.

With ~3 sessions/week and a performance observation every few weeks, a four-parameter model has
more parameters than the data can identify. Fitting it would produce confident-looking curves
whose fatigue half-life is an artefact of the priors.

---

## 4a. Shadow prototype (2026-10-20)

`features/fatigue_fitness.py` implements the first phase:

- per lift, session load = hard working sets (RIR ≤ 4);
- fixed half-lives: fitness 42 days, fatigue 4 days;
- a linear performance model `e1RM ≈ P0 + k1·fitness − k2·fatigue` is fitted to the athlete's
  own e1RM observations;
- it refuses (status `insufficient` or `unstable`) when there are fewer than 8 observations,
  less than 28 days of span, rank < 3, or a condition number above 1e8;
- only canonical lift ids are modelled (synthetic pattern ids would average unrelated movements);
  an accessory with too few observations is hidden, while a primary lift is shown as
  `insufficient`;
- an **overall** row pools lifts by relative e1RM (each lift divided by its median) against
  total hard-set load; its state is a ratio, not kg;
- a **family** slope is fitted on relative e1RM across lifts with the same movement pattern, and
  each lift's slopes are shrunk toward it (weight `n / (n + pooling_k)`);
- a chronological **80/20 holdout** reports backtest MAE against the training-mean baseline;
  a model that cannot beat the naive baseline is still displayed, but not trusted;
- `R²`, condition number, and approximate 95% intervals from the fit covariance are shown;
  intervals are linear-propagation approximations, not Bayesian posteriors;
- `strength-coach fatigue` and the Programme page display it;
- **no prescription reads it.**

Why fixed half-lives: fitting four parameters (two half-lives + two coefficients) at once is the
identifiability trap described in §2–4. Intervals, family shrinkage and a chronological backtest are now present; the remaining
statistical work is a fully prospective, frozen-parameter test — still not a load effect.

## 5. Options

### A. Status quo — readiness only (**recommended**)

Keep the current design: readiness is the athlete's integrated fatigue signal, and the gap rules
handle long breaks. No modelled fatigue, no new failure mode. The cost is that a hard session is
not automatically reflected in the next prescription unless the athlete reports it.

### B. Advisory recent-stress indicator (applied 2026-10-20)

A fixed, transparent decay of recent hard sets per lift (48 h half-life, high ≥ 6 decayed
sets, normal ≥ 3), shown on Prescribe/Programme as "recent stress: high/normal/low", with a
warning when a lift is scheduled within 48 h of high stress. No fitting, no load change. The
constants are `ASSUMPTION-24` (`DEC-STRESS-01`). It is a prompt to check readiness, not a
controller.

### C. Fitted per-lift fitness-fatigue model

Fit on the athlete's own e1RM series with hierarchical priors, validate prospectively, freeze
parameters, and only then consider load changes. This is a research project, not a config edit.
The evidence above says it is premature now.

### D. Collect the data first (partially applied)

**Applied 2026-10-20 (`DEC-SRPE-01`):** optional session RPE (1–10) and session length are
captured at review in `session_feedback`, stored append-only, and never change a load. The
remaining part — optional per-lift soreness/readiness after the session — is still open. After ~6 months and enough measured tests, revisit B/C.
This is the lowest-risk way to make a future model identifiable.

---

## 6. e1RM calibration — a separate, smaller question

**Applied 2026-10-20:** a report comparing measured tests with the pre-test formula estimate,
per lift (median ratio, mean bias, MAE), and a **bounded correction** when ≥3 tests and the
95% bootstrap CI excludes 1.0 (`DEC-E1RM-CAL-01/02`, `MOD-E1RM-001`). `e1rm calibrate` and the
Athlete page show both. Measured overrides still win. The value remains an estimate:

- Epley with RIR folded in (`epley_plus_rir`), marked as an approximation (`ASSUMPTION-03`);
- the **best usable** estimate in the 84-day window is used for loads, not the latest;
- a measured `test` writes an `e1rm_override` and outranks the formula;
- `--e1rm` can override a test if the athlete knows better.

A calibration report would compare measured tests with the estimate the app would have used
before the test: per-lift bias (measured − predicted), MAE, and the spread. That is useful and
cheap; a **bounded median-ratio correction** is justified only when the confidence interval
excludes 1.0 and the bias is within ±10% (implemented, `DEC-E1RM-CAL-02`). A curve fit to a
handful of tests would overfit; the single robust ratio is the limit.

Recommended order: report first (now implemented), manual override remains the control. If
the report shows a consistent per-lift bias over several tests, add a config-level correction
with an assumption, not a learned model.

---

## 7. Exercise selection and per-lift readiness

**Exercise selection is template-driven, not fatigue-driven.** Each day has fixed slots and a
main lift; variant slots (e.g. `bench_press_narrow` / `bench_press_pause`, `pull_up` /
`lat_pulldown`) resolve to the variant trained most recently. Constraints and suitability can
veto or warn. Readiness changes the **load and RIR** of the selected lift, not which lift is
selected.

**Readiness is global plus categories, with an advisory per-lift score.** The global score and
**category** overrides (`squat`, `hinge`, `horizontal_push`, …) remain the base. A per-lift
score (`docs/LIFT-READINESS.md`, `DEC-LIFT-READY-01`) adds e1RM trend, RIR and VBT deviations;
it can only lower a load. There is still no validated per-lift readiness questionnaire, so this
is an assumption, not a measurement. The old `squat_readiness` / `bench_readiness` /
`deadlift_readiness` fields are legacy labels and are excluded.

If per-lift readiness is wanted later, the honest version is a lift-specific **soreness/readiness
rating** logged before the session, used as a bounded modifier and validated against the session
outcome — not inferred from the global score.

---

## 8. Recommendation

1. **Do not let a fitted fatigue-fitness model change loads now.** A shadow, fixed-half-life
   prototype is implemented and displays per-lift state; the strength-specific evidence is small,
   the model is non-identifiable in this data regime, and the current RIR window + 48–72 h
   spacing already manages acute fatigue.
2. **Option B is applied** (2026-10-20): fixed decay, advisory only, no load change
   (`DEC-STRESS-01`, `ASSUMPTION-24`).
3. **Add session RPE for strength** as a low-burden input; it is the missing load variable for
   any future model and is useful on its own.
4. **e1RM calibration report** (predicted vs measured, bias/MAE), with the bounded correction
   applied only when the CI excludes 1.0 — implemented.
5. Revisit a fitted model only after ~6 months of the richer data and a prospective backtest.

See `OPEN-QUESTIONS.md` Q19 for the decision record and the default.
