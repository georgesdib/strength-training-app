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
| Do not prescribe velocity thresholds for the **hex-bar deadlift** | Chen 2026 |
| Track **trend within an athlete**, not against a population table | individual curves differ |

## 3. What our data can support today

The standard export gives **one mean velocity per set**, plus load, reps, RIR and date. That is
enough to:

- estimate a per-lift, per-rep-count median velocity inside an RIR band;
- attach a target to a prescription where at least 12 clean sets across 3 sessions exist
  (or a family pool of 24, and only for genuine variants such as bench grips or squat types —
  named hinges, good mornings, rack pulls and split squats are never pooled with each other);
- withhold a target where the evidence says velocity is not trustworthy (hex bar).

An optional device CSV can add **per-rep detail**, but it stays descriptive. It does not enter
the set-mean calibration, targets or prescription.

It is **not** enough to:

- compute within-set velocity loss from the standard export (that needs per-rep samples or
  start/end velocities); per-rep detail, when supplied, allows only a descriptive report;
- build an individual load-velocity profile (needs a progressive loading test);
- estimate a minimal velocity threshold at 1RM (needs near-maximal sets);
- control for belt, device or technique changes.

## 4. Consequences in the app

- A target is `target(lift, reps, rir band)`, never a single number per lift.
- No target is better than a guessed one; the prescription says "unavailable" and why.
- The target is a **median with a robust band**, and the basis records scope and sample size.
- A session already modified by a safety rule does not get a velocity target: the load it was
  calibrated against no longer holds.
- Hex-bar targets are withheld regardless of sample size. The trap bar has its own family, but
  that does not override the evidence-based `VBT_UNRELIABLE` exclusion; a family is necessary,
  not sufficient, for a target.
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
- a **progressive loading test** per lift to fit an individual load-velocity line and a minimal
  velocity threshold;
- device and setup metadata (belt, machine, sensor position) so curves are comparable;
- a calibration method version bump, with the old targets kept as superseded rows.

None of that is faked now. Optional per-rep data is descriptive and does not enter the set-mean
calibration, targets or prescription.

---

Full bibliography with DOIs: [`docs/REFERENCES.md`](REFERENCES.md).
