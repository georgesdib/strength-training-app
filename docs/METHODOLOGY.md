# METHODOLOGY

**Version:** 1.0.0  
**Status:** current method, 2026-10-23.  
This is the canonical one-page summary. Detailed schemas, evidence and decisions stay in their
existing documents; this file does not replace them.

---

## 1. Purpose

A local-first strength-coaching tool for one athlete. **Longevity is the outcome; strength is
the primary training modality.** Python computes; an optional LLM explains or chooses among
validated options. The system must still produce a safe prescription with no LLM available.

## 2. Decision flow

```text
athlete state / constraints / injury context
        ↓
readiness (date-scoped; global or category; per-lift downward only)
        ↓
session type (squat, hinge, bench_squat, bench_hinge)
        ↓
exercise selection (validated substitutions only)
        ↓
e1RM / load (formula, tests, overrides, calibration, decay)
        ↓
RIR target
        ↓
readiness / continuity / deload / volume / MRV modifiers
        ↓
optional user-selected minimum session (MOD-MIN-001)
        ↓
warm-up ramp
        ↓
validation: constraints, RIR window, spinal cap, executability
        ↓
prescription
```

The order matters. A later convenience cannot silently undo an earlier safety rule. The most
restrictive applicable rule wins.

## 3. Non-negotiables

1. Loads, RIR targets, velocity targets, tonnage and e1RM are computed by Python.
2. The LLM may narrate and choose among precomputed options. It may propose bounded structural
   edits, including a set-count change, but policy validates them; it cannot write a load,
   RIR, velocity or percentage.
3. The LLM may never veto a rule.
4. Missing data is `unknown`, never zero or normal.
5. Prescriptions, critiques, calibrations and provenance are append-only.
6. A hard constraint or injury ceiling cannot be overridden by readiness, selection, deload
   or minimum-session mode.
7. Config, not code, owns thresholds, templates, exercise taxonomy and rule documents.
8. A change that alters a prescribed load or set count needs a decision record, tests and docs.
9. No automatic rubric retuning or readiness-weight tuning.
10. No medical diagnosis, treatment, clearance or injury prediction.

## 4. Readiness policy

Readiness is date-scoped. The score can reduce load and add RIR; accessory set reduction is
automatic under poor readiness. **Main-lift set reduction is opt-in** (`DEC-READINESS-12`).
The current/future readiness gate remains mandatory. Readiness feedback is descriptive and
does not tune the policy.

The no-readiness counterfactual is not identifiable from the retrospective log; see
[`READINESS-AUDIT.md`](READINESS-AUDIT.md).

## 5. Volume and minimum sessions

Weekly volume is tracked by movement pattern against configured MEV/MAV/MRV landmarks. The
MRV cap trims non-essential sets. The optional minimum session is volume-only, user-selected,
and preserves load/RIR. Its default tier removes non-essential accessory work; the explicit
deeper tier reduces main-lift sets to a floor of two. See
[`MINIMUM-SESSION.md`](MINIMUM-SESSION.md).

## 6. What this app will never do

- diagnose, treat or clear an injury;
- predict injury or guarantee safety;
- prescribe rehabilitation or medical care;
- let the LLM compute, invent or veto a load/RIR/velocity number;
- silently turn missing data into zero or “normal”;
- automatically retune safety rules, readiness weights or the rubric;
- automatically clear an injury;
- prescribe cardio;
- run as a hosted, multi-user, cloud or authenticated service;
- make a causal claim from a single-athlete observational record.

## 7. Known limitations

- Historical imported logs lack reliable timestamps and include late/backfilled entries.
- Readiness weights are fixed and unvalidated; the no-readiness counterfactual is unavailable.
- The full W3 modifier-interaction matrix is still open.
- The minimum-session target is a planning estimate, not measured duration.
- e1RM is an estimate with individual and variant error.
- Spinal cost is ordinal and load-blind by design.
- No prospective validation; reports are descriptive.
- Symptom data may be absent; absence is `unknown`, not “no flare”.
- Cardio and measurements are captured context, not prescriptions.
- Session duration is only truly measured in live workout mode.
- The UI/CLI parity is not complete; see [`UI-CLI-PARITY.md`](UI-CLI-PARITY.md).
- The repository is public; exact personal data belongs in `private/`, not public docs.

## 8. Change control

| change | requirement |
|---|---|
| load/RIR/set policy | `DEC-` entry, config, tests, docs |
| new hard rule | user approval; constitution version |
| new metric | definition, direction, aggregation, missing-data rule, prescription effect |
| new LLM capability | validated option/proposal; no computed numbers |
| evidence claim | citation and evidence classification |
| methodology change | update this version and the relevant detailed doc |

## 9. Version history

| version | date | change |
|---|---|---|
| 1.0.0 | 2026-10-23 | First canonical summary after outcomes, readiness, feedback, minimum session and parity work |

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
