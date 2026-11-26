# VBT load–velocity methodology

**Status:** implemented (2026-11-26). Display in Exercises and the calibration that issues
velocity targets. The two read the same fits but have different authority: the Exercises
graphs are display-only, while the calibration's targets are frozen into a prescription and
compared per set.

Related: [VBT-CALIBRATION.md](VBT-CALIBRATION.md) (clean-set filters, ladder, versioning),
[VBT-EVIDENCE.md](VBT-EVIDENCE.md) (what velocity can and cannot support),
[REP-VELOCITY.md](REP-VELOCITY.md) (per-rep capture).

---

## 1. What is fitted

One row per set after the same clean-set filters the calibration uses:

- a working set (warm-ups excluded, `DEC-RIR-01`);
- a usable mean velocity: the stored `clean_set.velocity_mps`, else the latest set-mean
  `vbt_override`, else the mean of the per-rep rows (`DEC-VBT-09`);
- `1 ≤ reps ≤ 8`, known load basis, no `REPS_TYPO`, load at least 60 % of the set's e1RM;
- `RIR 0–4` (`DEC-RIR-06`). RIR is a covariate, not a filter.

The response variable is the **set mean concentric velocity**, not the fastest rep. It is the
quantity the device exports, the quantity the prescription compares, and the quantity that
exists for the whole history.

## 2. The per-rep-count line (primary)

For each pair `(exercise_id, reps)`:

```
mean_velocity = intercept + slope · load + rir_coef · RIR
```

- `slope` must be negative; a flat or rising fit is refused.
- Gates: at least 12 sets, 3 sessions, 3 distinct loads and a load span of at least 10 % of the
  heaviest load. A group that fails keeps the robust median band (or no target).
- RIR is a covariate because load and RIR move together: heavier sets sit closer to failure.
  Holding RIR out would let the load coefficient absorb the effort mix.
- Rep counts are fitted **separately**. Velocity at a given load depends on how many reps the
  set contains and how close to failure it is, so a 3-rep line is not used to judge a 5-rep
  set. A rep count without its own line gets the pooled fallback (§3), never another rep
  count's slope.

**Target issuance.** At plan time the line is evaluated at the item's prescribed load and
target RIR: `value ± 2 · residual MAD` (a relative floor when the MAD is missing). A load
outside the fitted load range is refused and the median band is used instead; the provenance
says `median`.

## 3. The pooled rep-count fallback

When no line (and no family line) exists at the prescribed rep count, one model per lift is
fitted across its rep counts:

```
mean_velocity = intercept + slope · load + rep_coef · reps + rir_coef · RIR
```

It is estimated in **two stages**. First a shared load/RIR slope is fitted with a categorical
intercept per rep count; that keeps the load slope identified *within* rep counts. Then a
weighted straight line is fitted through those per-rep intercepts against rep number, and that
line's slope is the rep term. A single raw regression of velocity on load + reps was rejected:
load and reps are negatively correlated by programme design, and on the reference data that
regression returned a *positive* rep coefficient (heavier sets have fewer reps, so the raw
model can attribute their lower velocity to the rep term). The two-stage form reads the rep
effect from where the rep counts actually differ instead.

- Gates: 12 sets, 3 sessions, 3 distinct loads, at least 2 distinct rep counts and a 10 %
  load span; `slope < 0` and `rep_coef < 0`.
- The rep term is the fitted version of "use the available rep counts to extrapolate". There
  is no hand multiplier; the coefficient is estimated from the athlete's data.
- `rep_coef < 0` is a sanity guard: at a fixed load, more reps must mean lower mean velocity.
  A model that violates it is refused rather than issued.
- It is a **fallback only**. A line at the exact rep count always wins; a family line at the
  same rep count also wins. The pooled model is used only for rep counts that would otherwise
  have no target.

**Extrapolation is allowed and labelled.** The model can be evaluated at any rep count
1–8 and any load, including a rep count with no sets of its own (the 1-rep prescription with
only 2- and 3-rep data). There is no bound, because a bound would be an arbitrary choice; the
target is instead labelled `pooled` when the rep count is inside the fitted range and
`pooled_extrapolated` (or a load outside the fitted range) when it is not. The set comparison
marks the same cases `rep_outside_fitted_range` / `load_outside_fitted_range` and excludes
them from comparability. The number is visible; it is not counted as a hit.

**Caveat.** Load and reps are negatively correlated in a programme, so the rep coefficient is
identified by where rep counts overlap at similar loads. With sparse 1-rep data the 1-rep
prediction is a fitted trend, not a measured point. That is why the per-rep line is primary
and the pooled model is the fallback.

## 4. Fallback order

1. A lift line at the prescribed rep count.
2. A family line at the same rep count (genuine variants only; see the ladder in
   [VBT-CALIBRATION.md](VBT-CALIBRATION.md) §3).
3. The lift's or family's robust median band at that rep count, where the group has enough
   sets and sessions for one. It is measured at the exact rep count, so it outranks the pooled
   model even though it is not load-conditioned.
4. The pooled rep-count model (this document) — only for a rep count with no line and no
   median target of its own.
5. No target, stated as unavailable.

## 5. Per-set comparison

The plan freezes the target and its coefficients. At analysis time the expected velocity is
recomputed at the load, RIR and rep count **actually used**:

```
expected = intercept + slope · actual_load + rep_coef · actual_reps + rir_coef · actual_RIR
residual = actual_velocity − expected
```

The band is `expected ± 2 · residual MAD`. The planned target remains visible alongside it.
A substitution, a load outside the fitted range or a rep count outside the pooled range is
reported but not comparable. Legacy plans without coefficients keep the old flat-target
comparison.

## 6. Display-only implied 1RM

The per-rep line is evaluated at a minimal-velocity anchor for the lift's family
(`ASSUMPTION-58`): the load where the line reaches that velocity. The value is **always
shown**, including when it looks inconsistent with the data: if the implied load is below the
heaviest fitted load, or beyond 2.5× it, the panel keeps the number and adds a flag
(`below_heaviest_load` / `beyond_extrapolation_limit`). A 1RM estimate below a weight the
athlete actually lifted means the line and the anchor disagree with the heavy sets; hiding
the number was less useful than showing it with that caveat. The value is display-only; no
load, target or rule reads it, and the anchor is a literature value, not an estimate from this
athlete.

The **pooled model also implies an e1RM**: the same anchor, evaluated at **1 rep and RIR 0**,
`(mvt − intercept − rep_coef) / slope`. It carries the same guards, and is labelled
*extrapolated* when 1 rep is outside the rep range the pooled model was fitted on. Both values
are shown, so the per-rep and pooled views can be compared directly.

The e1RM is also shown as a point-in-time weekly series. The per-rep point is fitted on the
trailing 84 days only; the pooled point refits on all history up to that date (an expanding
window), because the rep term needs several rep counts and a trailing window is too thin on
most lifts. A later block can append points but never rewrites an earlier one. The series
chart **overlays the computed e1RM** already used elsewhere in the app — the Epley+RIR estimate
from the enriched set history, best usable set per day, forward-filled to the weekly dates — so
the velocity-implied and load/RIR-implied trajectories can be read against each other.

## 7. Where it is shown

Exercises → Open → **VBT load–velocity profile**:

- **Per-rep chart**: the stored sets at the selected rep count, the per-rep line, the pooled
  line at the same rep count as a dashed overlay, and the display-only e1RM marker.
- **Pooled panel**: one line per observed rep count from the pooled model. The selected rep
  count is highlighted; if it has no sets, it is drawn dashed and labelled *extrapolated*.
- **e1RM series**: the weekly display-only series described in §6, with the computed
  Epley+RIR e1RM overlaid.

**Performance** renders the same weekly chart, using that view's lift selector, so the
velocity-implied and computed trajectories can be inspected without opening the exercise
dialog. The table below the chart still lists the Epley observations inside the selected range.

The profile is computed on read and cached in process, keyed on a cheap history revision
(max set id, row count, latest override, latest rep row, session edits and voids). A repeat
open is immediate; any append-only history edit changes the key and the profile is rebuilt on
the next open. Nothing is written to the database for this view.

Selecting a rep count with no sets is allowed when the pooled model exists, so the
extrapolation can be inspected rather than hidden.

## 8. Provenance and versioning

Every issued target cites an append-only `vbt_calibration` row. The row records `fit_method`
(`line`, `pooled` or `median`), the coefficients, the residual spread, the load range, the
observed rep range for a pooled fit and the calibration parameters hash. The plan JSON freezes
the same fields, so a later recalibration cannot rewrite the target a workout was issued with.
`METHOD_VERSION` is bumped when the fitting method changes; old rows stay valid and are never
edited.

## 9. Limits

- **Self-selected loads.** The fit describes the loads the athlete actually trained, not a
  controlled loading test; a narrow block yields a narrow line.
- **Collinearity.** In the pooled model load and reps are correlated by programme design. The
  rep term is a trend, and the 1-rep case is its weakest extrapolation.
- **No validated MVT.** The display 1RM uses a family anchor, not an athlete-specific minimal
  velocity threshold, which would need near-maximal sets.
- **No causal claim.** A residual is descriptive. It is not a fatigue score, a readiness
  input or an instruction to change a load.
- **No live control.** Nothing here stops a set or adjusts load in real time.

## Related

- **Docs:** [VBT-CALIBRATION.md](VBT-CALIBRATION.md) (filters, ladder, versioning),
  [VBT-EVIDENCE.md](VBT-EVIDENCE.md) (what velocity can and cannot support),
  [REP-VELOCITY.md](REP-VELOCITY.md) (per-rep capture), [API.md](API.md) (endpoint and payload).
- **Decisions:** [DECISIONS.md](DECISIONS.md) — the decisions behind the method.
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) — what is still unproven.
- **Roadmap:** [ROADMAP.md](../ROADMAP.md) — implementation status.
