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
| 2 | `RIR` inside the **2-3 target band** (`rir_mod.target_for`) | calibration deliberately uses the narrower target band, not the 1-4 allowed window (`DEC-RIR-02`); RIR 6 excluded as suspect (DQ-SENT-03) |
| 3 | `1 ≤ reps ≤ 8` | velocity is rep-count dependent; long sets are not VBT sets |
| 4 | `load_basis ≠ unknown` | DQ-BW-01 could not classify the load |
| 5 | not quarantined, no `REPS_TYPO` flag | corrupt rows cannot set a target |
| 6 | `exercise.vbt_family` not null | non-VBT movements (e.g. back extension, planks, jumps, carries and bodyweight work) are excluded structurally. A family is necessary but not sufficient: the trap bar has a family yet is withheld by the evidence-based `VBT_UNRELIABLE` rule |
| 7 | `load ≥ 0.60 × e1RM` | a 40%-e1RM warm-up has no informative velocity target; configurable |
| 8 | velocity within `median ± 4·MAD` of its (lift, rep) group | single-session device glitches; iterative, max 2 passes |

Expected magnitudes in a real export (reproduce with `tools/profile_data.py`):

- only about a third of all sets carry any velocity at all, and
- after the filters above, a high-volume main lift typically retains on the order of
  100–200 clean sets, a moderately-used one a few dozen, and a rarely-logged variant fewer
  than 30 — which is precisely why the fallback ladder below is mandatory rather than a
  nicety.

## 2. What a target is

A target is **conditional on rep count**, not a single number per lift:

```
target(lift, reps, rir_band) = (median_velocity, low, high)
```

where `low/high = median ∓ k·MAD`, with `k = 2.0` and a **relative floor** so a
zero-dispersion sample cannot collapse the band onto the median (see
`utils.stats.robust_band`). Storing the band instead of a point is what makes the check
"did velocity fall outside the expected range" honest at small *n*.

Why not a single "target velocity" per lift: velocity at 3 reps and at 6 reps are different
quantities, and a target that ignores rep count will systematically flag one of them.

## 3. Sparse data: a strict fallback ladder

Never interpolate silently. Resolve in order and record which level was used:

| level | rule | recorded as |
|---|---|---|
| **L0** | lift + rep count directly, if `n ≥ 12` and `≥ 3` distinct sessions | `scope: lift` |
| **L1** | pool by `vbt_family` at the same rep count, if `n_family ≥ 24`. Only genuine variants pool: bench grips, squat types. Named hinges (trap bar, sumo, RDL, conventional), good mornings, rack pulls and split squats each have their own family, because their load-velocity curves differ | `scope: family` |
| **L2** | *not implemented.* Pooled rep-count fits were designed but the shipped calibration uses lift and family only, because a pooled line can hide a lift-specific curve | — |
| **L3** | *not implemented* (same reason) | — |
| **L4** | no target | `scope: none`, `vbt_status: uncalibrated` |

Consequence at L4: **the prescription omits a velocity target entirely** and says so. It
does not guess. A lift with a few dozen clean sets will frequently land on L1 (its family),
and the prescription must label the target as family-derived rather than lift-derived.

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
`velocity_mad`, `velocity_low`, `velocity_high`, `n_sets`, `n_sessions`, `window_start`,
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
`Avg_velocity` per set, so set-level calibration still uses the mean only. An optional per-rep
CSV can now supply the series (`DEC-VBT-04`); it is stored as descriptive detail and does **not**
enter the VBT calibration, targets or prescription. Set-level capture is complete for the
workout path.

Two options, and the choice is Q4:

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

- the target is the calibrated **median mean velocity** for that lift, rep count and RIR band;
- the item records the legacy `velocity_target` and `vbt_basis` fields and a structured
  `vbt` object with target/lower/upper, rep count, RIR band, scope/family, sample size,
  method version, calibration id and source;
- the structured object is frozen into the workout plan JSON, so it is reproducible after a
  later recalibration; old plans without it are `legacy_partial` and are never reconstructed
  from today's calibration;
- the prescription cites the stored calibration rows in `calibration_ids` (deduplicated);
- a swap clears the old target because the replacement lift has a different velocity profile;
  added exercises have no target; changing set counts preserves a still-applicable target;
- **no target** is attached when the session was already modified by a safety rule (the load no
  longer matches the calibration), or when no lift has 12 clean sets across 3 sessions;
- **hex-bar deadlift targets are withheld** regardless of sample size, because the RIR-velocity
  relationship for that lift failed accuracy criteria (`docs/VBT-EVIDENCE.md`).

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
`clean_rep` and reported descriptively; it does **not** enter the calibration. Supplying the
per-rep CSV is an action available today, not a missing upgrade.

A real live velocity-loss controller would still need:

- a live/streamed per-rep feed, not an archived file, for within-set stop rules;
- a progressive loading test per lift, for an individual load-velocity line and a minimal
  velocity threshold;
- device/belt/setup metadata, so curves are compared like-for-like;
- a validated control rule and a method-version bump, with old calibration rows kept and
  superseded, never edited.

The calibration already carries `METHOD_VERSION` and a typed `CalibrationParams`, so a future
v2 method could be written beside the current one and selected by config.
Until then, the app uses what the export provides and says when that is not enough.

## Related

- **UI surface:** [WEB-UI.md](WEB-UI.md), [UI-MAP.md](UI-MAP.md)
- **API and data model:** [API.md](API.md), [DATA-MODEL.md](DATA-MODEL.md)
- **Evidence:** [VBT-EVIDENCE.md](VBT-EVIDENCE.md), [REFERENCES.md](REFERENCES.md)
- **Rep-velocity detail:** [REP-VELOCITY.md](REP-VELOCITY.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
