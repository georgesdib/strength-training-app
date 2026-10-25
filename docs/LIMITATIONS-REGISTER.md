# LIMITATIONS REGISTER

**Status:** living register, 2026-10-23.
**Purpose:** keep every known limitation from the audits in one place so later work can revisit
it deliberately instead of rediscovering it.

This register does not override the detailed audit reports. It indexes them.

| ID | limitation | status | source | revisit when |
|---|---|---|---|---|
| LIM-01 | The no-readiness counterfactual is not identifiable retrospectively; the mandatory readiness policy is not validated against no readiness | open | W6 / READINESS-AUDIT | prospective data or a different evaluation design |
| LIM-02 | Readiness weights and cut-points are fixed design choices; no symptom outcome data supported them | open | W6, READINESS-WEIGHT-EVIDENCE | prospective outcomes and symptom coverage |
| LIM-03 | Main-lift readiness set reduction is opt-in because it was the least validated part of the policy | mitigated | W6 / DEC-READINESS-12 | evidence for/against main-lift volume reduction |
| LIM-04 | A permanently unavailable session family can stall the rolling selector; one-off misses do not | open | W1 | a family-level fallback is designed |
| LIM-05 | There is no stored planned-session calendar; attendance is target-based | open | W7 / DEC-W7-01 | a persisted plan is introduced |
| LIM-06 | Injury-free weeks are only reported when every week has symptom coverage | open | W7 | symptom logging coverage improves |
| LIM-07 | `SESSION_DURATION` remains unmeasurable for imported sessions | mitigated | W0-C2, W11/B7 | imported timestamps become available |
| LIM-08 | Session duration outside live workouts is an estimate, not measured | open | W0-C4, W1 | measured duration is available |
| LIM-09 | UI prescription preview and committed workout artifact are different states | documented | W0-C5, UI-CLI-PARITY | never; it is intentional |
| LIM-10 | Imported logs lack reliable timestamps and include late/backfilled rows | open | W0-C7 | source data gains timestamps |
| LIM-11 | Minimum-session deep-tier main floor of 2 is a heuristic, not trial evidence | open | W0-C8, DEC-MIN-01 | evidence for a different minimum dose |
| LIM-12 | Last-working-load fallback is not decayed; continuity handles the gap separately | open | W2 | evidence for decaying the fallback |
| LIM-13 | e1RM coverage is visible as a source-set count; a single-set source still has low confidence | closed | W2 / DEC-E1RM-COVERAGE-01 | reopened if coverage needs a confidence model |
| LIM-14 | The spinal cap is ordinal and load-blind; normal week sits exactly at cap 3 | open | W9 | cap/ordinality/template decision |
| LIM-15 | Exact-cap weeks do not trigger the reactive deload; only two consecutive over-cap weeks do | open | W9 | reactive-policy change is approved |
| LIM-16 | `single_leg_db_rdl` is classified as non-counting by engineering judgement; no direct lumbar-load comparison exists | open | W9 / DEC-W9-01 | direct unilateral spinal-load evidence or a template decision |
| LIM-17 | High-fatigue deadlift variants use a conservative default cost of 3, not a measured cost | open | W9 | variant-specific evidence/config |
| LIM-18 | Readiness and continuity load reductions are capped at 20%, but that cap is an assumption | open | READINESS-SCORE, DEC-READINESS-07 | evidence or a different cap decision |
| LIM-19 | the deload schedule/evidence is weak; scheduled deload is a policy suggestion, not proven superiority | open | W4, STRENGTH-PROGRAM-REVIEW | prospective deload comparison |
| LIM-20 | MEV/MAV/MRV are configurable coaching landmarks, not measured individual thresholds | open | W4, VOLUME-MANAGEMENT | individual MRV can be estimated |
| LIM-21 | Power dose (3×3–5 box jumps) is practice; function evidence is moderate/low certainty | open | W4, STRENGTH-PROGRAM-REVIEW | dose-specific power evidence |
| LIM-22 | Exercise-selection algorithm is a shadow tool, not a validated strength intervention | open | W4, SELECTION-COMPARABILITY | prospective selection comparison |
| LIM-23 | High-intensity exposure guard is safety engineering; prospective review is pending | open | W4, HIGH-INTENSITY-EXPOSURE-PLAN | prospective exposure review |
| LIM-24 | e1RM/formula precision overstates the underlying RIR/measurement precision | open | W4, STRENGTH-PROGRAM-REVIEW | calibration/measurement study |
| LIM-25 | Public Git history still contains earlier personal details; current docs were generalised, not rewritten | accepted | F, PRIVACY | a history-rewrite decision |
| LIM-26 | Single-athlete observational data cannot support causal claims | open | W4/W5, METHODOLOGY | prospective design |
| LIM-27 | The UI still lacks first-class surfaces for `review --pending`, bulk state YAML, some report date controls and LLM proposals | open | UI-CLI-PARITY | parity work |
| LIM-28 | The engine does not enforce measured session duration; it only warns against the planned cap | open | W1, DEC-W1-01 | duration becomes a hard input |
| LIM-29 | Forecast deload is now build-time, but a forecast is still not a persisted plan | documented | W1 | a persisted plan is introduced |
| LIM-30 | W3 interaction fixes are regression-tested for the audited cases, not every imaginable combination | open | W3 | a broader property matrix is run |
| LIM-31 | The prospective evaluation protocol has not yet been run for a new block | open | W5 | 8–12 weeks of prospective data |
| LIM-32 | A stable-lift ±2.5% change threshold is a practical noise guard, not a validated minimal important difference | open | W5 | a defensible individual change threshold exists |
| LIM-33 | Prospective review remains observational; it cannot establish causation | open | W5, W6 | a controlled or natural-experiment design |
| LIM-34 | The weekly split is bench-heavy (12 bench vs 7 squat and 5 hinge sets); the exact ratio is a strength-priority choice, not an evidence-derived optimum | open | W8 | a user volume-balance decision |
| LIM-35 | Age is not recorded in athlete state, so age-conditional power/balance evidence cannot be personalized | open | W10 | `birth_year` is added and used only for wording/priority |
| LIM-36 | Public guidance says “age-dependent” without a recorded age; this must not read as a personal prescription | open | W10 | age is recorded or wording is generalised |
| LIM-37 | `metric_definition` is not a live readiness-composite driver; adding readiness metrics still needs code/config work | open | W11 follow-up / DATA-MODEL §11.4 | dynamic composite design with weights/baselines and shadow validation |
| LIM-38 | Regime-change thresholds (4 baseline sets, ≤25% current, ≥2 substitute rise) are descriptive heuristics, not validated cut-points | open | DEC-REGIME-01 | prospective evidence or a different review policy |
| LIM-39 | Post-lift form is a subjective 1–5 self-rating; its rubric weight (0.05) and aggregation are policy choices, not validated. Imported Form backfill uses 1=best, 5=worst, 0=missing and half-up rounding; retrospective associations with e1RM/next performance/sRPE were near zero | open | DEC-FORM-01/02/04 | prospective evidence or a coach comparison |
| LIM-40 | Form-trend status uses a ±0.5 descriptive threshold; it is not a validated minimal important difference | open | DEC-FORM-04 | evidence for a change threshold |

## Rules

- An item moves to **closed** only when a later change removes the limitation and tests it.
- An item marked **mitigated** still exists; the mitigation must be named.
- Do not silently delete an item. Add a superseding row if the scope changes.
