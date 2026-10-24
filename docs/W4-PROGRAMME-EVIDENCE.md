# W4 — PROGRAMME QUALITY AND EVIDENCE

**Status:** audit complete 2026-10-23. No programme change.
**Scope:** the controlling strength rules, their evidence class and their weakest claims.
**Related:** [`STRENGTH-PROGRAM-REVIEW.md`](STRENGTH-PROGRAM-REVIEW.md),
[`RIR-EVIDENCE.md`](RIR-EVIDENCE.md), [`VOLUME-MANAGEMENT.md`](VOLUME-MANAGEMENT.md),
[`W6`](READINESS-AUDIT.md), [`W9`](W9-SPINAL-CAP.md).

---

## 1. Classification key

- **Direct evidence** — a relevant trial/meta-analysis supports the rule as stated.
- **Reasonable heuristic** — plausible coaching practice, not settled by trials.
- **Athlete-specific hypothesis** — a judgement about this athlete/history.
- **Engineering/safety constraint** — product or safety guardrail, not a biological claim.
- **Unvalidated model** — a computed model that has not beaten a simple baseline.

“Confidence” is about the **rule**, not the athlete's response.

## 2. Rule classification

| rule / claim | class | confidence | implementation | qualification |
|---|---|---|---|---|
| Main lifts at 3–5 reps | direct evidence | moderate–high | `build_item`, `PRG-RIR-001` | Specific to 1RM strength; not a hypertrophy claim |
| RIR 2–3 target, allowed 1–4, RIR 0 forbidden | direct/moderate evidence | moderate | `PRG-RIR-001`, `domain/rir.py` | Self-reported RIR has meaningful error; 1–4 is deliberately wide |
| Main-lift load from e1RM | engineering estimator | low–moderate | `_latest_e1rm`, `loads.solve_load` | Epley + RIR is an estimate, not a measured 1RM |
| Measured-test calibration | reasonable heuristic | low–moderate | `e1rm_calibration`, `MOD-E1RM-001` | Bounded correction; sparse-test caveat |
| Age decay of e1RM | reasonable heuristic | low | `e1rm_decay`, `MOD-E1RM-DECAY-001` | Suppressed when continuity handles a long gap |
| Double progression for accessories | reasonable heuristic | low | `PRG-DP-001`, `build_item` | Not a validated progression algorithm |
| Readiness load/RIR/set modifiers | unvalidated model / heuristic | low | `readiness_score`, `_apply_readiness_score`, `MOD-FAT-001` | No no-readiness counterfactual; W6 could not validate |
| Readiness gate | engineering/safety constraint | low as evidence | `run`, web prescribe | Consistency/safety policy, not an outcome claim |
| Continuity fixed/calibrated reductions | reasonable heuristic | low | `_apply_continuity`, `MOD-GAP-001` | Fixed bands are assumptions; calibrated bands are non-controlling |
| Combined readiness + continuity 20% cap | engineering guardrail | low as evidence | `_apply_readiness_score`, `_apply_continuity` | No trial defines a safe stack |
| Scheduled deload every six weeks | reasonable heuristic / policy | low | `features/deload.py`, `MOD-DELOAD-001` | Comparative evidence is thin; optional suggestion |
| Reactive deload on two over-cap weeks or two flares | engineering/safety heuristic | low | `deload.reactive_decision` | Conservative trigger, not a validated threshold |
| MEV/MAV/MRV landmarks | reasonable heuristic | moderate for dose-response; low for individual values | `features/volume.py`, `MOD-VOL-001` | Individual MRV is not measurable from this log |
| Under-MEV accessory +1 set | reasonable heuristic | low | `_apply_under_mev`, `MOD-VOL-002` | Deterministic programme adjustment, not an experiment |
| Power: box jump 3×3–5, quality stop | moderate function evidence; exact dose practice | low–moderate | `session-types.v1.yaml`, `DEC-POWER-01` | Function benefit, not a validated 3–5 protocol |
| Session-type balance / rolling families | engineering heuristic | low | `schedule.py` | A product design choice; W1 shows balance |
| Exercise substitution / comparability | engineering + specificity evidence | low for algorithm | `selection.py`, `MOD-SELECT-001` | No trial shows algorithmic selection beats a fixed programme |
| Warm-up ramp 50/70/85% | reasonable heuristic | low | `warmup.py` | Preparation/comparability, not an optimal ramp |
| 3RM/5RM test cadence | reasonable heuristic | low | `test_cadence.py` | Practical testing policy, not an evidence-based interval |
| VBT targets | unvalidated/weak evidence | low | `vbt_calibration`, `_attach_vbt_targets` | Attached only when calibration is trustworthy |
| Spinal cap 3 | engineering/safety constraint + ordinal assumption | low as measurement | `PRG-SPINE-001`, `registry.weekly_spinal_costs` | Ordinal, load-blind; normal week at cap (W9) |
| High-intensity exposure guard | engineering/safety constraint | low | `high_intensity_exposure` | Prospective review pending |
| Cardio capture (no prescription) | direct evidence for aerobic health, not a dose | high for direction | `features/cardio.py` | Captured context only; no individual prescription |
| Minimum effective session | reasonable heuristic | low | `minimum_session.py`, `MOD-MIN-001` | No validated universal minimum dose |
| 80 planned / 90 hard session cap | engineering/product constraint | n/a | `prescribe/engine.py`, profile | No biological claim |
| Readiness feedback report | descriptive only | low | `readiness_feedback.py` | Association, not causal effect |

## 3. Claims that need qualification

1. **“The e1RM is precise.”**  
   It is an estimate from a formula + RIR, with calibration/decay. Do not present it as a
   measured max or a precise individual capacity.

2. **“Readiness improves training outcomes.”**  
   Not validated. W6 found no identifiable no-readiness counterfactual; the descriptive
   association is weak. Readiness remains a bounded safety heuristic.

3. **“MRV is known.”**  
   The configured landmark is a guardrail. Individual MRV is not estimated from this log.

4. **“A deload every six weeks is evidence-based.”**  
   It is a fatigue-management policy with weak comparative evidence; scheduled deload is a
   suggestion, not an automatic law.

5. **“The spinal cap is a measured injury threshold.”**  
   It is an ordinal, load-blind exposure guard. W9 found a normal week already at cap.

6. **“Algorithmic exercise selection improves strength.”**  
   Specificity matters; the selection algorithm is a shadow tool with guardrails, not a
   validated intervention.

7. **“3×3–5 box jumps is the optimal power dose.”**  
   Power training has function evidence; this exact dose is practice.

8. **“Attendance shortfall means missed planned sessions.”**  
   There is no stored plan. Attendance is target-based (W7).

9. **“A single set establishes an e1RM.”**  
   It is a real performance but low-coverage; W2 now warns.

10. **“The minimum session is a validated minimum dose.”**  
    It is an explicit volume heuristic with floors, not a trial-defined minimum.

## 4. Rules to simplify or leave alone

**Leave alone (with qualification):**

- RIR 1–4 window and RIR 0 veto;
- e1RM solver and bounded calibration;
- volume landmarks/MRV as configurable guardrails;
- power placement;
- comparability guard for substitutions;
- high-intensity exposure guard;
- 80/90 session policy.

**Simplify only if a later decision requires it:**

- do not add another load model;
- do not turn readiness into a learned weight;
- do not make MRV an individual measurement;
- do not add more session types;
- do not replace the simple baselines with the fitness-fatigue model.

**No new model is proposed.** A new model would need to beat a simple baseline on held-out data,
which the current retrospective work has not shown.

## 5. Findings

**W4-01 — The programme's core strength dose is evidence-aligned; the precision around it is
not.**  
The 3×/week full-body structure, heavy 3–5 rep main lifts, RIR 2–3 target, and non-failure
approach are supported. The exact loads, MRV landmarks and readiness cut-points are heuristics.

**W4-02 — Several safety rules are engineering constraints, not evidence.**  
The spinal cap, exposure guard, combined-reduction cap and session ceiling are sensible
guardrails. They should not be presented as measured biological thresholds.

**W4-03 — Readiness is the weakest controlling input.**  
W6 could not validate it against no readiness; symptom outcomes are absent. The current
opt-in main-lift set reduction is the right mitigation; the gate remains a policy choice.

**W4-04 — Volume landmarks are useful but not individual measurements.**  
The dose-response direction is supported; the configured MEV/MAV/MRV values are coaching
landmarks. The MRV cap should remain conservative and configurable.

**W4-05 — Deload evidence is weak.**  
Scheduled deloads are a policy suggestion; reactive triggers are safety heuristics. This is
already labelled.

**W4-06 — Selection and VBT remain shadow tools.**  
Neither has beaten a simple fixed alternative in the available data. Keep them non-controlling.

## 6. Exit criteria

- Every controlling rule has a classification: **yes**, §2.
- No assumption is presented as established evidence: **yes**, qualifications in §2–3.
- No new model is proposed unless it beats a simple baseline: **yes**, no new model.

## 7. Recommended follow-up

1. Keep the evidence table and qualifications visible in the user-facing methodology.
2. Do not change the strength dose on the basis of this audit.
3. The next high-value work is **W5 — prospective evaluation design**, not another model.
4. Keep W8 (volume split) and W10 (age) as explicit policy decisions rather than implicit
   evidence.

No code, config or prescription was changed by W4.
