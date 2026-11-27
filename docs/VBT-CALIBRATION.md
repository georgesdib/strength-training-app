# VBT CALIBRATION

Goal: turn historical velocity data into **per-lift, per-rep-count velocity targets** the
prescription engine can use, without inventing numbers when the data is thin.

This is a deterministic, versioned code function. It is never an LLM decision.

---

## 1. What counts as a clean calibration set

A set may enter calibration only if **all** of these hold. Every exclusion is counted and
reported per lift, so a target with `n = 4` is visibly weak rather than silently weak.

| # | Criterion | Reason |
|---|---|---|
| 1 | `Avg_velocity > 0` | `0.000000` is "device not used" (DQ-SENT-01), not slow |
| 2 | `RIR` inside the **0-4 fit band** | RIR is a covariate, not a filter (`DEC-RIR-06`): the line fits across the legal range while the issued target keeps the per-lift 2-3 band. RIR 6 stays excluded as a warm-up (DQ-SENT-03) |
| 3 | `1 ≤ reps ≤ 8` | velocity is rep-count dependent; long sets are not VBT sets |
| 4 | `load_basis ≠ unknown` | DQ-BW-01 could not classify the load |
| 5 | not quarantined, no `REPS_TYPO` flag | corrupt rows cannot set a target |
| 6 | `exercise.vbt_family` not null | non-VBT movements (e.g. back extension, planks, jumps, carries and bodyweight work) are excluded structurally. No lift is currently withheld by an evidence rule: the trap-bar exclusion was reversed (`DEC-VBT-06`) |
| 7 | `load ≥ 0.60 × e1RM` | a 40%-e1RM warm-up has no informative velocity target; configurable |
| 8 | velocity within `median ± 4·MAD` of its (lift, rep) group | single-session device glitches; iterative, max 2 passes |

Expected magnitudes in a real export (reproduce with `tools/profile_data.py`):

- only about a third of all sets carry any velocity at all, and
- after the filters above, a high-volume main lift typically retains on the order of
  100–200 clean sets, a moderately-used one a few dozen, and a rarely-logged variant fewer
  than 30 — which is precisely why the fallback ladder below is mandatory rather than a
  nicety.

## 2. What a target is

A target is **conditional on rep count**, and a fitted target is also conditional on load and
RIR — it is not a single number per lift:

```
target(lift, reps, rir_band)       = (median_velocity, low, high)              # flat fallback
target(lift, reps, rir_band, load) = slope·load + intercept + rir_coef·rir      # per-rep line
target(lift, reps, rir_band, load) = slope·load + rep_coef·reps + rir_coef·rir  # pooled fallback
```

The per-rep line is primary where the rep count has enough load variation; the pooled model
covers a rep count with no line; the median band is the flat fallback. In every case
`low/high` comes from the fit's residual spread (the median fallback uses
`median ∓ k·MAD`, with `k = 2.0` and a **relative floor** so a zero-dispersion sample cannot
collapse the band onto the median; see `utils.stats.robust_band`). Storing the band instead of
a point is what makes the check "did velocity fall outside the expected range" honest at small
*n*.

Why not a single "target velocity" per lift: velocity at 3 reps and at 6 reps are different
quantities, and a target that ignores rep count will systematically flag one of them.

A prescription that allows a **rep range** therefore freezes one target per allowed rep count
(`vbt.per_rep`), each resolved through the same L0–L2 ladder and carrying its own calibration
id and band (`DEC-VBT-11`). A 3–5 prescription is judged at 5 reps against the rep-5 target, not
against the rep-3 one. Nothing is interpolated across rep counts: a rep count with no target of
its own has no entry, and the comparison says `rep_mismatch` rather than presenting a
neighbouring rep count's number. A pooled target already carries a rep term, so when its fitted
rep range covers the prescription that single target is evaluated at the reps used and no vector
is frozen.

## 3. Sparse data: a strict fallback ladder

Never interpolate silently. Resolve in order and record which level was used:

| level | rule | recorded as |
|---|---|---|
| **L0** | lift + rep count directly, if `n ≥ 12` and `≥ 3` distinct sessions | `scope: lift` |
| **L1** | pool by `vbt_family` at the same rep count, if `n_family ≥ 24`. Only genuine variants pool: bench grips, squat types. Named hinges (trap bar, sumo, RDL, conventional), good mornings, rack pulls, and the rear-foot-down and rear-foot-elevated split squats each have their own family, because their load-velocity curves differ | `scope: family` |
| **L2** | **pooled rep-count fallback** when no L0/L1 target exists at the prescribed rep count: a two-stage pooled model across the lift's rep counts (shared load/RIR slope, per-rep intercepts, weighted rep trend). Gates: 12 sets, 3 sessions, 3 loads, and at least two rep counts with three sets each. The target is evaluated at the prescribed load, reps and RIR and labelled `pooled`; an unobserved rep count or a load outside the fitted range is `pooled_extrapolated` | `scope: lift`, `fit_method: pooled` |
| **L3** | *not implemented* — no further pooling; a rep count with no L0/L1/L2 target gets no target | — |
| **L4** | no target | `scope: none`, `vbt_status: uncalibrated` |

Consequence at L4: **the prescription omits a velocity target entirely** and says so. It
does not guess. A lift with a few dozen clean sets will frequently land on L1 (its family) or
L2 (the pooled rep-count fallback), and the prescription must label the target as family- or
pool-derived rather than lift-derived.

## 4. Manual override (per lift)

`config/calibration/overrides.v1.yaml`:

```yaml
overrides:
  - exercise_id: ssb_squat
    rep_count: 3
    rir_band: [2, 3]
    velocity_low: 0.42
    velocity_high: 0.52
    reason: "SSB sets feel slower than comp squat at the same RIR; coach call."
    author: user
    recorded_on: <date>
    expires_on: null      # or a date, after which the computed target resumes
```

Rules:
- an override **always wins** over a computed target and is tagged `source: override`;
- a prescription records the `calibration_id` it used, so overriding later does not rewrite
  history;
- an expired override is ignored and the computed target resumes — no silent rot.

## 5. Versioning and immutability

Every computation creates a new `vbt_calibration` row:

`calibration_id`, `exercise_id`, `scope`, `rep_count`, `rir_band`, `velocity_median`,
`velocity_mad`, `velocity_low`, `velocity_high`, `fit_method`, `velocity_slope`,
`velocity_intercept`, `velocity_rir_coef`, `velocity_residual_mad`, `load_min`, `load_max`,
`velocity_rep_coef`, `reps_min`, `reps_max`, `n_sets`, `n_sessions`, `window_start`,
`window_end`, `method_version`, `params_hash`, `computed_at`, `supersedes_id`.

Nothing is updated in place. Recalibrating after new data produces a new row. The
deterministic `calibration_id` covers the exercise, scope, rep count, RIR band, median,
band, sample size, method version, family, parameter values and issue date, so a lift target
and a family target with coincidentally equal numbers are different rows. A past
prescription cites the exact row it used. `vbt_family` and `velocity_mad` are persisted when
available; older rows without them remain valid historical records.

## 6. What cannot be computed — velocity loss

See [`VBT-REP-LEVEL.md`](VBT-REP-LEVEL.md) for the post-hoc cost/benefit and the decision not
to add manual rep-level entry.

Within-set velocity loss requires a **per-rep velocity series**. The standard export has one
`Avg_velocity` per set, so the target is still calibrated on a set mean. An optional per-rep
CSV supplies the series (`DEC-VBT-04`); since `DEC-VBT-09` it also supplies the **mean** when the
stored set mean is missing, so a per-rep-only set is no longer dropped from calibration. The
velocity-loss series itself remains descriptive: it does not set a target, a stop rule or a
load. Set-level capture is complete for the workout path.

Two options were considered; `DEC-VELOCITY-01` records the position (report within-set loss as
not measurable, with a labelled decay proxy where a proxy is shown):

1. **Report it as not measurable** and score no rubric line for it. Honest.
2. **Set-to-set decay proxy**: within one session, at the same load and rep count, the
   drop from the first working set's velocity to the last, expressed as a percentage. This
   captures *some* of the same fatigue signal and is cheap. It must be labelled
   `velocity_decay_proxy`, never "velocity loss".

Recommendation: implement both, with `velocity_loss_measurable: false` carried in the
feature record so the critique cannot accidentally print a real-looking velocity-loss score.

## 7. Test strategy for this module

- Private integration test (git-ignored): the clean-set counts in §1 are asserted against the
  real CSV, so a change in exclusion logic cannot silently change the calibration base. The
  expected numbers are personal data and are not committed.
- Unit tests with synthetic frames for each exclusion criterion (one row each) and for
  each fallback level boundary (`n = 11` vs `12`, `23` vs `24`).
- Determinism test: same inputs + same `params_hash` ⇒ byte-identical output.
- Immutability test: recomputation inserts a new row and leaves the old one untouched.


## 8. What is wired now (v0.1)

`build_prescription` calibrates from the stored clean sets on every run and attaches a target
only where the ladder produces one:

- the target is the calibrated **median mean velocity** for that lift, rep count and RIR band,
  or — when the group has at least 12 sets across 3 sessions, 3 distinct loads and a 10 % load
  span — the **fitted line evaluated at the item's prescribed load and RIR**, or, when no line or
  median exists at that rep count, the **pooled rep-count fallback** evaluated at the prescribed
  load, reps and RIR (§3 L2). Outside a line's fitted load range the median band is used and the
  provenance says `median`; a pooled prediction outside the observed rep or load range is issued
  but labelled `pooled_extrapolated`. The plan records `fit_method` plus the coefficients, so a
  target is never extrapolated silently. The per-set comparison evaluates the line or pooled model
  at the load **actually used** and reports the expected velocity and its residual; an actual load
  or rep count outside the fitted range is reported as an extrapolation and excluded from
  comparability;
- the item records the legacy `velocity_target` and `vbt_basis` fields and a structured
  `vbt` object with target/lower/upper, rep count, RIR band, scope/family, sample size,
  method version, calibration id and source;
- a rep-range prescription freezes one target per allowed rep count in `vbt.per_rep`, each
  with its own calibration id and band; the per-set comparison uses the entry for the reps the
  set used, and `rep_outside_prescription` (left the prescribed range) or `rep_mismatch` (no
  target at that rep count) is reported when there is none (`DEC-VBT-11`);
- the structured object is frozen into the workout plan JSON, so it is reproducible after a
  later recalibration; old plans without it are `legacy_partial` and are never reconstructed
  from today's calibration;
- the prescription cites the stored calibration rows in `calibration_ids` (deduplicated);
- a swap clears the old target because the replacement lift has a different velocity profile;
  added exercises have no target; changing set counts preserves a still-applicable target;
- **no target** is attached when no lift has 12 clean sets across 3 sessions at the prescribed
  rep count. A session modified by a safety rule keeps its targets (`DEC-VBT-07`): a line or
  pooled target is evaluated at the prescribed load, RIR and reps, and the comparison uses the
  load actually used, so a lighter set is still comparable; the per-set rules exclude a set whose
  effort left the band or whose load/rep count left the fitted range;
- **hex-bar deadlift targets are no longer withheld** (`DEC-VBT-06`): the failed accuracy
  criterion in `docs/VBT-EVIDENCE.md` concerns RIR-from-velocity, not the mean-velocity target,
  and the ladder above still refuses a target when the sample is thin. `VBT_UNRELIABLE` stays in
  the engine as an empty hook for a future evidence-based exclusion.

The prescription notes say which case applied, and the CLI prints a `vel` column when any item
has a target. A missing target is visible, not silent.

No schema migration is required for the structured metadata: `vbt_calibration` already has the
needed columns, and `workout_session.plan_json` is the frozen historical authority.
`prescription_item` retains the legacy `velocity_target`/`vbt_basis` projection for existing
readers. The new `vbt` fields are additive to the plan JSON returned by the API, including the
additive iOS plan payload; no iOS code or model changes are involved.

The active logger checks exercise identity, set group, rep count, actual RIR and load basis before
treating the frozen target as applicable. Completed workouts are analysed from corrected
`clean_set` leaf rows: exercise/identity, exact target rep count, valid positive mean velocity,
working-set status, known/compatible load basis, target RIR band and data-quality flags are
required for `comparable: true`. A removed item falls back to its original-plan target; a swapped
item never borrows the old target. The latest set-mean `vbt_override` wins. Per-set signed and
relative deltas, absolute error, band status and reasons are exposed, together with per-exercise
counts, mean/median signed delta, mean/median absolute error, mean/median relative error,
within-band and above/below-target fractions, actual/prescribed RIR and calibration provenance.
Metrics are never pooled across exercises into a composite score, and within-set velocity loss is
kept separate.

The Performance view adds a read-only longitudinal layer over the same per-set rules. Cohorts are
split by exercise, scope/family, rep count and target RIR band; lift and family targets are never
pooled. It reports weekly residual series, within/above/below-band evidence, actual vs prescribed
RIR, deterministic 95% bootstrap intervals for sufficiently sized cohorts, and per-set drill-down.
The reused gates are 5 comparable observations for a descriptive signal and 20 observations over
8 weeks (on at least two cohorts) before anything is called evaluation-ready; these gates do not
authorize a change. Per-rep within-set loss has a separate 5-set/3-consecutive-week descriptive
gate and no fitted trend. Set-level band counts are evidence, not success thresholds.

## 9. What is captured now, and what a live controller would still need

Set-mean velocity is the calibration input. Optional per-rep detail is already captured in
`clean_rep` and, where the stored mean is missing, contributes that mean (`DEC-VBT-09`); the
loss series stays descriptive. Supplying the per-rep CSV is an action available today, not a
missing upgrade.

A real live velocity-loss controller would still need:

- a live/streamed per-rep feed, not an archived file, for within-set stop rules;
- near-maximal sets (or a progressive loading test) per lift, for a minimal velocity
  threshold — the load-velocity line itself now comes from historical sets;
- device/belt/setup metadata, so curves are compared like-for-like;
- a validated control rule and a method-version bump, with old calibration rows kept and
  superseded, never edited.

The calibration already carries `METHOD_VERSION` and a typed `CalibrationParams`, so a future
v2 method could be written beside the current one and selected by config.
Until then, the app uses what the export provides and says when that is not enough.

## 10. Load–velocity profile (display only)

The full methodology — the per-rep-count lines, the pooled rep-count fallback, target
issuance, the comparison and the display-only e1RM — is in
[VBT-LOAD-VELOCITY.md](VBT-LOAD-VELOCITY.md). This section is the short version.

The Exercises dialog shows a fitted load–velocity profile and a display-only implied 1RM.

- **Input:** the stored set mean concentric velocity (`clean_set.velocity_mps`), not a per-rep
  best. It exists for the whole history and is the quantity the prescription compares.
- **Form:** `mean velocity ~ load + RIR`, fitted per (exercise, rep count). RIR is a covariate
  because load and RIR move together; the fit band is RIR 0–4, wider than the prescription
  target band. Warm-up loads below 60 % e1RM, `REPS_TYPO` rows, non-working sets and sets
  without a mean are excluded, matching the calibration filters.
- **Gates:** at least 12 sets, 3 sessions, 3 distinct loads and a load span of at least 10 % of
  the heaviest load. Below any gate the panel says why and draws no line.
- **Implied 1RM:** the load at a minimal-velocity anchor, with the anchor taken from a
  per-family table (`ASSUMPTION-58`). It is shown even when it is inconsistent with the data: an
  implied load below the heaviest fitted load, or beyond 2.5× it, is kept and flagged in the
  payload and the panel rather than hidden. The panel labels it display only.
- **Effect:** none. No load, RIR, set, target or rule reads this module; the prescription
  calibration in §1–§8 remains the authority and is unchanged.

The implied 1RM is also returned as a **point-in-time series**: a fixed weekly grid from the
first observation, each point fitted only on the trailing 84 days, capped at the most recent
52 points. A later heavy block can append points but never moves an earlier one.

Endpoint: `GET /api/exercises/<id>/vbt-profile?rep=N`. The response carries the points, the
coefficients, the residual spread, the gates' outcome, the display-only e1RM with its anchor
and the e1RM series. Missing data stays missing; nothing is interpolated.

## Related

- **UI surface:** [WEB-UI.md](WEB-UI.md), [UI-MAP.md](UI-MAP.md)
- **API and data model:** [API.md](API.md), [DATA-MODEL.md](DATA-MODEL.md)
- **Evidence:** [VBT-EVIDENCE.md](VBT-EVIDENCE.md), [REFERENCES.md](REFERENCES.md)
- **Rep-velocity detail:** [REP-VELOCITY.md](REP-VELOCITY.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
