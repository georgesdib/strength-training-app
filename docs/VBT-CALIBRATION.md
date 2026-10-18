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
| 6 | `exercise.vbt_family` not null | non-VBT movements (back extension, planks) are excluded structurally |
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
| **L1** | pool by `vbt_family` at the same rep count (bench: bench/narrow/pause; squat: SSB/comp; hinge: trap bar/conventional/RDL), if `n_family ≥ 24` | `scope: family` |
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

Nothing is updated in place. Recalibrating after new data produces a new row; a past
prescription still points at the old one and still explains itself. `params_hash` covers
`k`, the relative floor, the warm-up threshold, the RIR band and the rep cap, so a change
to any of those is visible as a different calibration even if the numbers coincide.

## 6. What cannot be computed — velocity loss

Within-set velocity loss requires a **per-rep velocity series**. The export has one
`Avg_velocity` per set, so within-set loss is arithmetically unavailable
(`docs/SANITY-CHECKS.md` §C). It remains deferred (`DEC-VBT-02`), and the prescription does
not pretend otherwise.

Two options, and the choice is Q4:

1. **Report it as not measurable** and score no rubric line for it. Honest.
2. **Set-to-set decay proxy**: within one session, at the same load and rep count, the
   drop from the first working set's velocity to the last, expressed as a percentage. This
   captures *some* of the same fatigue signal and is cheap. It must be labelled
   `velocity_decay_proxy`, never "velocity loss".

Recommendation: implement both, with `velocity_loss_measurable: false` carried in the
feature record so the critique cannot accidentally print a real-looking velocity-loss score.

## 7. Test strategy for this module

- Golden test: the clean-set counts in §1 are asserted against the real CSV, so a change in
  exclusion logic cannot silently change the calibration base.
- Unit tests with synthetic frames for each exclusion criterion (one row each) and for
  each fallback level boundary (`n = 11` vs `12`, `23` vs `24`).
- Determinism test: same inputs + same `params_hash` ⇒ byte-identical output.
- Immutability test: recomputation inserts a new row and leaves the old one untouched.


## 8. What is wired now (v0.1)

`build_prescription` calibrates from the stored clean sets on every run and attaches a target
only where the ladder produces one:

- the target is the calibrated **median mean velocity** for that lift, rep count and RIR band;
- the item records `velocity_target` and `vbt_basis` (scope + sample size);
- the prescription cites the stored calibration rows in `calibration_ids`;
- **no target** is attached when the session was already modified by a safety rule (the load no
  longer matches the calibration), or when no lift has 12 clean sets across 3 sessions;
- **hex-bar deadlift targets are withheld** regardless of sample size, because the RIR-velocity
  relationship for that lift failed accuracy criteria (`docs/VBT-EVIDENCE.md`).

The prescription notes say which case applied, and the CLI prints a `vel` column when any item
has a target. A missing target is visible, not silent.

## 9. Upgrade path (placeholder)

The current input is one mean velocity per set. A real velocity-loss controller needs:

- per-rep velocity samples (or first/last rep), for within-set loss and stop rules;
- a progressive loading test per lift, for an individual load-velocity line and a minimal
  velocity threshold;
- device/belt/setup metadata, so curves are compared like-for-like;
- a method-version bump, with old calibration rows kept and superseded, never edited.

The calibration already carries `METHOD_VERSION` and a typed `CalibrationParams`, so the
upgrade is additive: a v2 method can be written beside the current one and selected by config.
Until then, the app uses what the export provides and says when that is not enough.
