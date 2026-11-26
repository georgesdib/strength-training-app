# VBT EVIDENCE — what velocity can and cannot tell us

A knowledge base for the velocity-target wiring. It records the evidence, the best practices
that follow from it, and which parts of VBT this app does **not** do with the data currently
available. Decisions live in `docs/DECISIONS.md`; the mechanics live in
`docs/VBT-CALIBRATION.md`.

---

## 1. What the evidence supports

**Load-velocity profiles are reliable when measured with a valid device.** A 2026 systematic
review of 63 sensor studies and 38 1RM-prediction studies found good-to-excellent reliability
for commercial velocity sensors (pooled ICC 0.90-0.91), while 1RM prediction from a general
profile carries meaningful error (Claassen et al., *Sports Med Open* 2026,
doi:10.1186/s40798-026-01102-0). Individual profiles are better than group ones.

**The relationship is strong within a lift.** In the full squat, mean velocity explained about
96% of the variance in relative load (R² = 0.958) across age groups (Serrano-Cañadillas et al.,
*J Strength Cond Res* 2026, doi:10.1519/JSC.0000000000005624). A belt changes the relationship:
it raises 1RM and shifts velocities at high relative loads, so measurements must be compared
like-for-like (Huang et al. 2026, doi:10.1519/JSC.0000000000005523).

**Velocity loss is a dose variable, not a pass/fail.** A dose-response meta-analysis found a
reverse-U relationship with 1RM gain: **20-30% velocity loss** was associated with the best
strength outcomes, while lower loss was more efficient per repetition (Zhang et al.,
*Healthcare* 2023, doi:10.3390/healthcare11030337). A systematic review of acute and chronic
responses reached a compatible conclusion: higher velocity loss means more fatigue, and the
adaptation depends on the threshold chosen (Jukic et al., *Sports Medicine* 2023,
doi:10.1007/s40279-022-01754-4).

**Hypertrophy does not need a high velocity loss.** Pooling the velocity-loss trials found no
advantage for >25% over 20-25% loss for muscle growth (ES 0.08, 95% CI -0.16 to 0.32)
(Refalo et al., *Sports Medicine* 2023, doi:10.1007/s40279-022-01784-y).

**General velocity-to-RIR rules are weak.** A bench-press study found the RIR-velocity
relationship least biased of three general approaches, but errors were still about ±1.3 reps
(Qin et al. 2025, doi:10.1186/s13102-025-01098-2). For the **hexagonal-bar deadlift**, no
condition met the accuracy criteria for estimating RIR from mean velocity, and the authors
concluded the relationship is not fit for real-time monitoring (Chen et al.,
*J Strength Cond Res* 2026, doi:10.1519/JSC.0000000000005549).

**Intent matters as much as the number.** A narrative review of best practice stresses
explosive intent versus merely moving slowly; a set's velocity depends on how the athlete
intends to move, not only on the load (Behm et al., *Appl Physiol Nutr Metab* 2025,
doi:10.1139/apnm-2024-0136).

## 2. Best practices that follow

| practice | why |
|---|---|
| Build an **individual** load-velocity profile (3-5 loads) when precision matters | group profiles carry more 1RM error (Claassen 2026) |
| Compare **like-for-like**: same lift, setup, belt, device, rep count | belt and setup shift the curve (Huang 2026) |
| Use **mean velocity**, not peak, for set-to-set comparison | mean is the more stable construct |
| Stop sets at a **target velocity loss**: 20-25% for hypertrophy, 10-20% for strength/power | Zhang 2023; Jukic 2023 |
| Treat **RIR-from-velocity** as a weak prior, not a measurement | Qin 2025; Chen 2026 (hex bar fails) |
| Do not prescribe **RIR or velocity-loss thresholds** for the **hex-bar deadlift** | Chen 2026; the mean-velocity target is a separate quantity (`DEC-VBT-06`) |
| Track **trend within an athlete**, not against a population table | individual curves differ |

## 3. What our data can support today

The standard export gives **one mean velocity per set**, plus load, reps, RIR and date. That is
enough to:

- estimate a per-lift, per-rep-count median velocity inside an RIR band, and — where the
  loads vary — a per-rep-count load-velocity line with RIR as a covariate, plus a pooled
  rep-count fallback when a rep count has no line of its own;
- attach a target to a prescription where at least 12 clean sets across 3 sessions exist
  (or a family pool of 24, and only for genuine variants such as bench grips or squat types —
  named hinges, good mornings, rack pulls and split squats are never pooled with each other);
- state the absence of a target explicitly when no lift reaches the ladder. No lift is
  currently excluded by evidence: the hex-bar exclusion was reversed by the owner
  (`DEC-VBT-06`), so the trap bar is calibrated like every other lift.

An optional device CSV can add **per-rep detail**. The velocity-loss series stays descriptive,
but since `DEC-VBT-09` a per-rep series also supplies the **set mean** when the stored mean is
missing (set-mean override first), so those sets enter calibration instead of reading as
"no velocity". The loss itself never sets a target.

It is **not** enough to:

- compute within-set velocity loss from the standard export (that needs per-rep samples or
  start/end velocities); per-rep detail, when supplied, allows only a descriptive report;
- build a *validated* individual load-velocity profile from a controlled progressive loading
  test. The app now fits an **observational** line per rep count (and a pooled fallback) from
  the stored sets, which is useful but inherits the self-selected loads and narrow blocks; a
  controlled test is still what a precise, validated profile and MVT would need;
- estimate a minimal velocity threshold at 1RM (needs near-maximal sets);
- control for belt, device or technique changes.

## 4. Consequences in the app

- A target is `target(lift, reps, rir band)`, and a fitted target also takes the prescribed
  load and RIR — never a single number per lift.
- No target is better than a guessed one; the prescription says "unavailable" and why.
- The target is a **per-rep line**, a **pooled rep-count fallback**, or a **median with a robust
  band**, and the basis records which, plus scope, sample size and coefficients.
- A session already modified by a safety rule keeps its velocity targets: a line or pooled target
  is evaluated at the prescribed load, RIR and reps, so a lighter set is still comparable; the
  per-set rules exclude it when the amended effort left the band or the load/rep count left the
  fitted range (`DEC-VBT-07`).
- Hex-bar targets are no longer withheld (`DEC-VBT-06`). Chen 2026 is about estimating RIR from
  velocity; a mean-velocity target with a robust band at a fixed rep count is a different
  quantity, and the 12-set/3-session ladder still refuses one when the sample is thin. The
  `VBT_UNRELIABLE` hook remains in the engine, empty, for a future evidence-based exclusion.
- The structured `vbt` metadata is provenance only. It does not add evidence, change the
  calibration method, change how a target is selected, or make a target load-specific. The
  target remains a median velocity conditional on lift/family, rep count and RIR band.
- Target-versus-actual deltas, within-band counts and above/below-target fractions are
  descriptive summaries of observed sets. They are not measurement-error bounds, prediction
  intervals, evidence that a set was effective, or inputs to autoregulation. A comparison marked
  `comparable` means only that the predefined structural and effort conditions were met.
- The Performance dashboard's cohort residuals, bootstrap intervals, band counts and rep-loss
  drift are descriptive observations. A 20-observation/8-week gate makes a cohort
  evaluation-ready; it does not validate a load-velocity model, justify a load change or establish
  a causal effect. Cohorts are not pooled across lifts or target scopes.

## 5. What is already available, and what remains

Already available and usable now:

- optional per-rep CSV capture in Workout mode;
- per-set first/last/mean/min/max and within-set loss on the end screen;
- a descriptive cross-session report with `insufficient`, `no variance` and missing-data states;
- append-only `clean_rep` storage and import undo.

The immediate action is **data collection**, not a code upgrade: supply the per-rep CSV for
sessions and reopen **Progress → Per-rep velocity** until the report has at least 10 paired
observations. Until then, the honest result is `insufficient`.

Still missing for live velocity-based autoregulation:

- a live/streamed feed and a validated set-termination rule;
- a **progressive loading test** (or enough near-maximal sets) for a validated minimal
  velocity threshold; the load-velocity line itself is now fitted observationally from history;
- device and setup metadata (belt, machine, sensor position) so curves are comparable;
- a calibration method version bump, with the old targets kept as superseded rows.

None of that is faked now. Optional per-rep data supplies a missing set mean (`DEC-VBT-09`)
but its velocity-loss series remains descriptive and never sets a target or a stop rule.

---

Full bibliography with DOIs: [`docs/REFERENCES.md`](REFERENCES.md).
