# ATHLETE FEEDBACK AND COACHING (AFC) — PLAN

**Status:** proposed 2026-11-13. Documentation only: no runtime behaviour, prompt, API, schema,
dependency or training-rule change is included in this plan.
**Roadmap workstream:** ROADMAP section 4.33.
**Owner:** the athlete. AFC-2, AFC-3 and AFC-4 require explicit approval before implementation.
**Scope:** backend and web UI only, for the local server and its own browser UI.

This is a plan, not a claim that any described interface or capability exists. The current
implementation remains the source of truth until a phase is implemented and tested.

## 1. Purpose

AFC turns training, adherence, VBT, readiness and performance data that the server already
computes into reliable, evidence-linked and actionable feedback.

The principles are fixed:

- deterministic calculations remain authoritative;
- feedback is traceable to the actual underlying rows;
- missing data is reported as unknown, never as poor performance or poor adherence;
- observations are distinguished from hypotheses;
- nudges are supportive and non-punitive;
- initial functionality never changes a prescription;
- existing services are reused rather than reimplemented;
- the web UI consumes backend-generated metrics and observations;
- the same architecture can later supply an LLM without letting it calculate authoritative
  metrics.

## 2. What already exists

AFC is a composition layer. Every one of these is implemented and tested today:

| Capability | Owner |
|---|---|
| Per-set reps/load/RIR attainment, set completion, plan-change inventory, attribution loss | `strength_coach/adherence.py` |
| Multi-week adherence aggregation with coverage and exclusion reasons | `strength_coach/features/adherence_analytics.py` |
| Target-based attendance (`completed / (target × weeks)`) | `strength_coach/features/attendance.py` |
| Weekly set-volume targets per movement pattern with a tolerance band and exemptions | `strength_coach/prescribe/volume_budget.py`, `config/volume.v1.yaml` |
| Declared breaks (append-only range, cancellable) | `strength_coach/features/breaks.py` |
| Per-set VBT residual, band membership and comparability | `strength_coach/features/vbt_analysis.py` |
| Longitudinal VBT cohorts, weekly residuals, bootstrap CI, within-set drift, evidence gates | `strength_coach/features/vbt_performance.py` |
| Evidence gate vocabulary (`insufficient`, `signal`, `evaluation`) | `strength_coach/features/residual.py` |
| Readiness-reduction follow-up with explicit warnings and a small-sample guard | `strength_coach/features/readiness_feedback.py` |
| Session RPE, duration, productivity and notes | `strength_coach/features/session_feedback.py` |
| Descriptive monitoring analysis with a version and a database fingerprint | `strength_coach/features/monitoring_analysis.py` |
| Multi-source completed-workout payload | `strength_coach/workout.py` `summary()` |

The completed-workout payload already composes completion, strength, dose, special exposure,
feedback, ratios, comparison, adherence, VBT, quality and basis. AFC-2 does not need a new
calculation; it needs an evidence contract and a presentation surface.

Attendance is already rendered in Progress with the correct framing ("not a calendar",
"No planned-session calendar is stored", `web/static/progress.js`). AFC must not restate or
re-derive it.

## 3. What AFC does not do

Out of scope, permanently or until a separate approved decision:

- **Planned-session compliance.** `DEC-W7-01` stands: attendance is target-based and no
  planned-session calendar is stored. There is no eligible-session denominator, no "missed"
  session and no planned-vs-completed rate. `LIM-05` records this and is unchanged.
- **Prescription adaptation.** AFC-5 is a separate, gated initiative and does not block
  AFC-1 to AFC-4.
- **Prescription nudges.** A "nudge" in AFC is informative only. The completion-based volume nudge
  discussed in [`FREQUENCY-AND-VOLUME.md`](FREQUENCY-AND-VOLUME.md) would change a prescription
  and remains training-engine scope, not AFC.
- **Native iOS or watchOS work.** AFC is backend and web UI only.
- **Cardio, VBT calibration and training-engine scope.** They generate metrics but keep their
  own ownership, acceptance criteria and roadmap sections.
- **Changing any Phase 5A instrument** (see section 5).
- **Reimplementing any metric** owned by a module in section 2.

## 4. Decisions taken

| Ref | Decision |
|---|---|
| AFC scope | AFC composes existing services and adds no second calculation of a metric another module owns |
| Naming | Target-based attendance is never labelled "adherence"; it is "training frequency vs target" |
| Q1 | Nudge state reuses the append-only `maintenance_review` pattern; observation lifecycle justifies its own small table |
| Q2 | Per-workout observations render on the end screen, longitudinal observations in Progress, and at most one nudge on Today expressed as a review category |
| Q3 | `summary.completion` is removed; `adherence` becomes the single metric source; `comparison` is retained only as the pre-materialisation display contract and is never a metric source |
| Q4 | The "stagnation" observation is deferred; it is re-asked when AFC-3's second cut is scoped, and its definition must be written before any number is generated |
| Q5 | AFC-3 first cut: repeated RIR deviation, repeated incomplete work, VBT residual deviation. "Improving performance at stable effort" and stagnation are deferred |
| Q6 | No global observation gate; each family inherits its existing owner (VBT uses the residual gates; adherence uses the analytics display guard) |
| Q7 | CLI parity for the read-only observation report; no CLI for nudge rendering |
| Q8 | Snooze 14 days, permanent dismissal per `nudge_key` and window, at most one nudge per surface per day |
| Q9 | A declared break may be annotated beside attendance as a footnote; the percentage and denominator are unchanged |

## 5. Phase 5A protection

Phase 5A (2026-10-30 to 2027-01-22) is active. AFC is read-only composition and must not change
any value the validation reads, or any behaviour that produces those values.

Frozen until the 2027-01-22 gate:

- `attendance.summary` output: `target` and `pct` are unchanged. A declared break affects the
  DUP cycle and the deload clock only (`DEC-CONTINUITY-04`, `DEC-CONTINUITY-05`); it does not
  alter the attendance denominator.
- `features/prospective.py` thresholds, including the `ATTENDANCE_LOW` cut at 60 per cent.
- Monitoring, exposure, calibration and relationship configuration, and the hardcoded
  `features/residual.py` gates.
- The end-screen capture controls for session RPE, duration, productivity and "not recorded".
  This is a data-capture surface: `session_feedback` feeds `prospective.py` and
  `monitoring_analysis.py`, so changing where or how prominently those controls appear would
  change what the validation collects. No test can detect that.
- `workout.get` payload shape, because `prospective.py` consumes it.

Required before any AFC code merges:

1. a golden fixture of `prospective.report` captured from the last pre-AFC commit, committed
   and asserted equal;
2. an assertion that the locked configuration groups' `config_inventory.revision()` is
   unchanged;
3. a test that `features/prospective.py` does not consume `workout.summary`.

AFC-2 may extend `workout.summary()` and `summary.js`; `summary()` has exactly two consumers
(`web/server.py`, `cli.py`) and no feature module reads it.

## 6. Evidence contract

One module, `strength_coach/features/evidence.py`, owned jointly with the LLM workstream. It
is a serialiser, not a calculator. It generalises the shape `vbt_performance` already emits
per cohort (`set_ids`, `method_versions`, `calibration_ids`, `target_sources`, `reasons`,
`gate`, `reason`).

Each evidence item carries:

- a deterministic `evidence_id` derived from source, source rows and window;
- `source` and `source_ids` (the rows actually used);
- the analysis `window`;
- `value` and `unit`;
- `n` and the comparability verdict;
- `gate`, using the existing `insufficient` / `signal` / `evaluation` vocabulary;
- quality flags copied from the owning service;
- `method_versions` and `calibration_ids`;
- explicit `limitations`;
- `rule_ids` and `assumption_ids`.

Rules:

- a changed window or a changed input row changes the id;
- an observation without evidence is allowed only when labelled as interpretation;
- the UI can expand a claim to its evidence;
- no consumer computes a metric to build an evidence item.

`docs/LLM-INTEGRATION-PLAN.md` section 4 defines the same schema for the future
`AthleteContextBuilder`. There is one schema. The builder consumes AFC evidence; it does not
recalculate adherence, VBT, readiness or volume.

## 7. Phases

### AFC-0.5 — documentation consolidation (this commit)

Documentation only. Collapses the old ROADMAP section 4.23 into AFC-1 and AFC-4, creates this
document, records the decisions, and cross-references the LLM workstream. No code, no schema.

### AFC-1 — programme KPIs (dissolved)

AFC-1 does not survive as a phase. Attendance is already computed, rendered and correctly
labelled; weekly set-volume attainment already exists in the volume budget. The planned-session
part is out of scope by `DEC-W7-01`. The remaining items move:

- the programme-level KPI panel becomes part of AFC-4;
- an abandoned-attempt coverage counter belongs in AFC-2's data-quality block. An abandoned
  workout is not a missed planned session; the athlete demonstrably started it, no `session`
  row is written, and it currently vanishes from every denominator without a reason.

### AFC-2 — post-workout feedback report

Scope: compose `workout.summary()` into observations with evidence, render them on the end
screen, fix the quality block, and remove the duplicate set-count source.

Work:

- remove `summary.completion`;
- mark `workout._comparison` as the pre-materialisation display contract only;
- repoint `features/readiness_feedback.py` `_adherence` from `original_comparison` to
  `adherence.analyse`, because it is a completed-workout metric and currently uses the weaker
  engine;
- populate `summary.quality.flags` from `adherence.quality` and `vbt.quality` (it is
  currently a hardcoded empty list);
- add the abandoned-attempt coverage counter;
- render adherence and quality on the end screen, from `final_plan` for the primary table and
  `original` when the plan was modified.

No schema change.

### AFC-3 — longitudinal observations

Scope: a read-only observation service over AFC-2's evidence contract.

First cut only: repeated RIR deviation, repeated incomplete work, VBT residual deviation.
Deferred: "improving performance with stable effort" (no joint model exists) and stagnation
(no agreed definition).

Rules:

- no observation below its family's existing minimum;
- `insufficient` produces an abstention with a reason, never a value;
- a non-comparable input suppresses the observation and is listed in `abstain`;
- no causal language and no diagnosis;
- observations are descriptive and never change a prescription.

Persistence: a small append-only observation table recording identity, window, gate, `n` and
the evidence id, so a displayed observation is reproducible.

### AFC-4 — web UI coaching and nudges

Scope: extend existing hosts only. No new tab.

- Progress carries the programme-level panel and longitudinal observations;
- the end screen carries the per-workout report;
- Today carries at most one nudge, expressed as a review category rather than a competing list;
- one shared nudge component with expandable trigger and evidence;
- suppression uses the `maintenance_review` pattern: snooze 14 days, permanent dismissal per
  key and window, at most one nudge per surface per day.

### AFC-5 — evidence-gated prescription adaptation (separate)

Not part of AFC-1 to AFC-4 and not a dependency of them.

- AFC-5a historical evaluation of adaptation candidates;
- AFC-5b prospective shadow proposals;
- AFC-5c narrow, user-approved prescription changes.

AFC-5a may begin only after AFC-2 and AFC-3 produce a trustworthy evidence contract. AFC-5b and
AFC-5c require an independent evidence and safety gate; automatic adaptation is never
recommended without one.

## 8. Sequence

Documentation consolidation (AFC-0.5) → AFC-2 → AFC-3 → AFC-4 → AFC-5 (separate and gated).

AFC-1 is dissolved and is not a step. AFC-2 comes first because it needs no schema, no decision
change and no new calculation, and because it produces the evidence contract AFC-3, AFC-4 and
LLM Iteration 1 phase 2 all consume.

## 9. Open items

- **Stagnation definition (deferred).** Re-ask when AFC-3's second cut is scoped. The definition
  must be written before any stagnation number is generated or inspected; a threshold chosen
  after seeing the output is post-hoc. Do not reuse a percentage band invented during Phase 5A.
- **Interpretation caveat for the gate.** A declared break depresses `attendance.pct` and can
  raise `ATTENDANCE_LOW` in the Phase 5A read-out. This is expected behaviour under
  `DEC-W7-01`, not a defect. Note it when reading the 2027-01-22 review.

## 10. Related

- [ROADMAP](../ROADMAP.md) section 4.33 — roadmap summary of this plan.
- [LLM-INTEGRATION-PLAN.md](LLM-INTEGRATION-PLAN.md) — the shared context and evidence layer.
- [DECISIONS.md](DECISIONS.md) — `DEC-W7-01`, `DEC-AFC-01`, `DEC-AFC-02`.
- [LIMITATIONS-REGISTER.md](LIMITATIONS-REGISTER.md) — `LIM-05`, unchanged.
