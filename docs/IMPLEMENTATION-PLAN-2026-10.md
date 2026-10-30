# IMPLEMENTATION PLAN — outcomes, longevity, readiness and minimum sessions

**Status:** approved direction. A0, A and B are implemented. W6 readiness audit is complete, Option B is implemented (main-lift set reduction opt-in), and
A0–F are implemented, including the canonical methodology/privacy docs. The full W3 modifier-interaction audit is complete; six confirmed deload-order defects are fixed and regression-tested.
**Date:** 2026-10-23
**Scope:** A–F from the final review, constrained by the existing deterministic architecture.
**Related:** [`ENGINE-AUDIT-PLAN.md`](ENGINE-AUDIT-PLAN.md),
[`HIGH-INTENSITY-EXPOSURE-PLAN.md`](HIGH-INTENSITY-EXPOSURE-PLAN.md),
[`READINESS-WEIGHT-EVIDENCE.md`](READINESS-WEIGHT-EVIDENCE.md).

---

## 1. Decisions already settled

| decision | choice |
|---|---|
| priority hierarchy | **longevity is the outcome; strength is the primary training modality** |
| first implementation slice | **read-only outcome review** |
| readiness gate | keep mandatory until the readiness audit is complete |
| outcome storage | compute on demand; no snapshot table in v1 |
| session target | **80 minutes default; athlete may raise or lower it** |
| minimum effective session | user-selected; offered when readiness is poor; never automatic |
| public-doc privacy | generalise current docs and move details to `private/`; do not rewrite Git history |
| readiness weights | unchanged; no automatic tuning |
| cardio | capture and context only; no prescription or fatigue model |

These choices do not authorize changes to prescribed loads. Any later change that does needs a
separate decision and sign-off.

---

## 2. Backlog and order

| order | item | user value | risk | dependency |
|---:|---|---|---|---|
| 0 | Documentation/privacy cleanup | high | low | none |
| 1 | **A. Outcome review** | high | low | W0 map; basic definitions |
| 2 | **B. Longevity section** in Outcomes | high | low | A |
| 3 | Readiness audit W6 | critical evidence | low code risk | W0 |
| 4 | **C. Quick readiness** | high daily value | medium | W6 gate decision |
| 5 | **E. Readiness feedback report** | high evidence value | medium | A + W6 |
| 6 | **D. Minimum effective session** | high adherence value | high | W3, C, cap decision |
| 7 | F. Remaining docs/methodology | medium | low | ongoing |

Do not implement D before the modifier-interaction audit and the readiness decision.

---

## 3. Cross-cutting rules

1. Every number is computed by Python.
2. The LLM may narrate an outcome report or choose among validated options; it may not
   calculate, change a load/RIR, or make a medical decision.
3. Outcome and readiness reports are descriptive. “Changed” and “trended” are allowed;
   “improved because” is not.
4. Missing data is `unknown`, never zero.
5. No automatic rubric retuning, injury clearance or readiness-weight update.
6. No new fatigue model.
7. Any change that alters a prescription needs a `DEC-` entry, config knob, tests and docs.
8. Every new metric has a definition: direction, aggregation, missing-data rule and whether
   it can affect a prescription.

---

## 4. A0 — Modifier provenance prerequisite

The outcome report needs to say when a session was reduced by readiness, continuity, a
deload, the MRV cap or a future minimum-session mode. That information is not consistently
stored today:

- prescription items are stored;
- prescription **notes** are not stored as a queryable record;
- CLI deload reasons are printed but not durable;
- the web prescription path does not create a replayable modifier event.

### Smallest safe design

Add an append-only `prescription_modifier` table:

```text
modifier_id
prescription_id
modifier_key       -- MOD-FAT-001, MOD-GAP-001, MOD-DELOAD-001, MOD-VOL-001/002, MOD-MIN-001
applied_on
detail_json        -- before/after, factor, reason refs
created_at
```

No behavior change. This is provenance only. It is a small migration and is required before
the outcome report can report deload/frequency reliably.

If this prerequisite is rejected for v1, the outcome report must show deload frequency and
reason as `unknown`, not infer them from changed sets/loads.

---

## 5. Slice A — outcome review

### Goal

Answer “is training doing what I intend over 4, 8 or 12 weeks?” without claiming causation.

### User story

As the athlete, I can run one read-only review and see the strength picture, the health
context and the data gaps, with links to the underlying sessions and measurements.

### Data

Use existing data:

- `session`, `clean_set`;
- `session_feedback` (sRPE, duration);
- `readiness_day` / `readiness_entry`;
- `symptom_log`;
- `cardio_log`;
- metric definitions and measurement entries;
- prescription/rule evaluation for spinal weeks;
- `prescription_modifier` from A0.

No new outcome snapshot table in v1.

### Sections

#### Strength

- stable main-lift e1RM first/last/change and number of observations;
- per-lift trend, not a single composite score;
- weekly hard-set volume by movement pattern;
- planned/target vs completed sessions;
- average sRPE and duration where present;
- readiness trend;
- low-back and other-region flare count;
- weeks at or above the spinal cap;
- deload count/reason from A0, or unknown;
- citations: session IDs, measurement IDs, rule IDs.

#### Longevity / health context

- cardio minutes by week and rolling four-week average;
- modality counts;
- steps, sitting, bodyweight, body fat, grip, VO2max estimate, sit-to-stand where measured;
- sleep/stress/soreness/readiness trends;
- symptom history by region.

#### Data coverage

- each metric: present / sparse / missing;
- no silent zero;
- no “injury-free” claim when symptom logging is absent.

### Attendance definition

Use the athlete profile’s `sessions_per_week_target` as the target, not a fabricated plan:

```text
target_sessions = weeks × sessions_per_week_target
completed_sessions = distinct session dates in the window
attendance = completed / target, or unknown if target is absent
```

Label it “target-based attendance”, not “planned adherence”, unless a stored forecast exists.

### CLI/API/UI

```bash
strength-coach outcomes --weeks 8
strength-coach outcomes --weeks 12 --date 2026-10-23
```

- `GET /api/outcomes?weeks=8&date=...`
- Web **Outcomes** page with Strength, Longevity and Data coverage sections.
- One core function shared by CLI and UI.

### Non-goals

- no prescription effect;
- no causal language;
- no new fatigue model;
- no snapshot table;
- no automatic decisions.

### Tests

- 4/8/12-week windows;
- sparse readiness, sRPE and measurements;
- no readiness at all → unknown;
- no symptom entries → unknown, not “no flare”;
- main-lift e1RM with a variant change;
- attendance target absent;
- cap week at exactly 3 vs above 3;
- deload provenance present and absent;
- report does not write to prescription/session tables;
- API/CLI parity.

### Acceptance

- every number traces to a row or is `unknown`;
- no causal wording;
- the report is readable in under a minute;
- no database write occurs.

---

## 6. Slice B — longevity section

### Goal

Make the longevity context visible without implying a cardio prescription.

### Design

This is a **section of Outcomes**, not a separate dashboard.

- Weekly aerobic minutes and rolling four-week average.
- Modality counts.
- WHO 150–300 minutes/week shown as a general reference only, with the source and a
  plain-language caveat.
- Steps/day, sitting hours/day, bodyweight, body fat, grip, VO2max estimate, sit-to-stand.
- Sleep/stress/soreness/readiness trends.
- Symptom history.
- Explicit label: **captured, not prescribed**.

### Non-goals

- no cardio prescription;
- no cardio fatigue model;
- no personalised WHO target;
- no new intervention recommendation.

### Tests

- WHO range renders as context, not a target;
- missing metrics are unknown;
- no cardio prescription is emitted;
- cardio modalities aggregate correctly;
- the strength report is unchanged.

---

## 7. Slice C — quick readiness

**Dependency:** W6 readiness audit and the gate decision.

### Goal

Reduce friction without changing the meaning of readiness or weakening the gate.

### Quick path

Require four ordinary fields:

```text
sleep, energy, soreness, stress
```

This satisfies the existing minimum (3 core fields plus sleep or energy). Presets write
ordinary `readiness_entry` rows with:

- explicit field values;
- `source = preset`;
- a preset key/note;
- no hidden defaults.

Proposed preset values are config, not code. Example presets:

```text
good_to_train
slightly_tired
poor_sleep
high_stress
sore_cautious
unwell_do_not_train
```

The exact values need a short config table and user review. “Unwell” must not be treated as
medical clearance to train; it should be a caution/context flag.

### Schema

- extend `readiness_entry.source` with `preset` (migration and repository validation);
- add append-only `readiness_context`:

```text
context_id
on_date
flag          -- travel, timezone_change, illness, alcohol, poor_sleep_environment, high_work_stress
note
created_at
```

- context flags display beside readiness and do **not** change the score by default.

### Device suppression

If a context flag makes HRV/RHR hard to interpret:

- default: annotate, keep the score;
- optional config: suppress HRV/RHR from the headline score;
- if suppression changes the score, it needs a decision record because it can change a load.

### UI/CLI

- quick preset buttons on Readiness;
- context flag chips/checkbox list;
- manual per-field entry remains;
- `strength-coach readiness preset --name ...`;
- `strength-coach readiness context --flag ...`;
- `/api/readiness/preset`, `/api/readiness/context`.

### Non-goals

- no skippable gate before W6;
- no automatic scoring from presets;
- no context flag hidden in a score;
- no change to the minimum-data rule.

### Tests

- preset writes four fields and `source=preset`;
- gate passes with a valid preset;
- gate still fails with insufficient fields;
- context flags do not change score by default;
- suppression config is explicit and cited;
- append-only history and correction;
- preset names/values are config-driven;
- UI and CLI use the same service.

---

## 8. Slice E — readiness feedback report

**Dependency:** A outcome review + W6 readiness audit.

### Goal

Test association, not causation: do readiness-driven reductions precede better or worse
subsequent training?

### Method

For each prescription with readiness-related reductions:

- use `prescription_modifier` to identify the applied reduction;
- compare the next session or week with the athlete’s own recent baseline;
- outcomes:
  - completion;
  - sRPE;
  - RIR adherence;
  - symptom flare within the configured follow-up window;
  - next-session performance/e1RM trend.

### Rules

- report associations only;
- always state observational, confounded, small-sample limits;
- no readiness weight changes;
- no “validated” claim;
- no recommendation to tighten/loosen from a handful of sessions.

### Tests

- reduction records are identified correctly;
- missing follow-up is unknown;
- no causal wording;
- no weight or config write;
- expected sample-size warnings.

---

## 9. Slice D — minimum effective session

**Dependency:** W3 modifier-interaction audit, readiness gate decision, session-cap decision.

### Goal

A user-selected fallback for busy, travelling, poor-sleep or reduced-capacity days that
preserves the primary pattern and essential work.

### Precedence

One modifier, not a stack:

```text
hard constraints / injury ceiling
→ preserve primary pattern and essential lifts
→ remove non-essential accessory volume first
→ reduce main-lift sets to a configured floor
→ existing readiness/load/RIR rules
→ validate
```

No second independent reduction. If readiness or deload already reduced work, the minimum
mode must cap the total, not duplicate it.

### Requirements

- explicit user action;
- may be offered when readiness is poor;
- never selected only because the calendar is busy;
- label as reduced; cite `MOD-MIN-001` (new modifier, not a hard rule);
- no violation of constraints, injury ceiling, spinal cap, RIR window or gate;
- config floors for accessory/main sets;
- no automatic change to session type.

### Evidence

The evidence supports that low-volume training can maintain strength better than it builds
it, but it does not define a universal minimum for this athlete. Treat the mode as a
coaching heuristic, not a validated dose. A short evidence review is required before coding.

### Tests

- user must opt in;
- accessory volume is reduced before main lifts;
- essential work is preserved;
- no double reduction with readiness/deload/MRV;
- cap/RIR/constraint validators still pass;
- rule citation and label;
- poor readiness can offer but not apply it;
- explicit “no minimum mode” path unchanged.

---

## 10. Slice F — documentation

Do not create a second documentation universe. Add:

1. one-page decision flow;
2. known limitations;
3. “what this app will never do”;
4. versioned methodology summary.

### Decision flow

```text
readiness
→ constraints / injury ceiling
→ session type
→ exercise selection
→ e1RM / load
→ RIR
→ volume / spinal / deload modifiers
→ validation
→ prescription
```

### Known limitations

- historical lack of timestamps;
- load-blind spinal cost;
- unvalidated readiness weights;
- e1RM estimation error;
- no prospective validation;
- cardio capture without prescription;
- injury signal is not medical clearance;
- single-athlete observational data.

### Never do

- diagnose injury;
- provide medical clearance;
- predict injury;
- automatically retune safety rules;
- replace clinical advice;
- prescribe rehabilitation.

### Methodology version

A human-readable summary versioned separately from code. It must describe current behaviour,
not future intentions.

---

## 11. Data model and config summary

| item | change |
|---|---|
| A outcome | no snapshot table; read-only queries |
| A0 provenance | `prescription_modifier` append-only table |
| B longevity | no new table; use `cardio_log`, measurements, readiness |
| C presets | `readiness_entry.source` adds `preset`; `readiness_context` table |
| C device suppression | config option; decision required before enabling |
| D minimum mode | config `minimum-session.v1.yaml`; no new hard rule; `MOD-MIN-001` |
| F docs | no schema |

Potential migrations:

```text
0025 readiness source/context
0026 prescription_modifier
```

No migration for outcome v1 unless A0 is not approved.

---

## 12. Existing files likely to change

- `docs/`: DECISIONS, DATA-MODEL, READINESS, WEB-UI, USER-GUIDE, ROADMAP, ARCHITECTURE,
  ENGINE-AUDIT-PLAN, this plan.
- `config/`: new `readiness-presets.v1.yaml`, `minimum-session.v1.yaml`; updates to
  readiness/volume/thresholds only if approved.
- `strength_coach/features/`: new `outcomes.py`, `readiness` preset/context support,
  `prescription_modifier` repository, readiness feedback report.
- `strength_coach/prescribe/`: minimum-session modifier, modifier provenance.
- `strength_coach/store/`: migrations, repositories, queries.
- `strength_coach/cli.py`, `web/server.py`, `web/static/app.js`, `index.html`.
- Tests: `test_outcomes.py`, `test_readiness_presets.py`, `test_minimum_session.py`,
  `test_readiness_feedback.py`, web/CLI parity, golden prescription regression.
- Rules: `MOD-FAT-001`, `MOD-GAP-001`, `MOD-DELOAD-001`, `MOD-VOL-001/002`, `PRG-SPINE-001`,
  `PRG-RIR-001`; `MOD-MIN-001` only with a decision.

---

## 13. Risks and mitigations

| risk | mitigation |
|---|---|
| outcome report implies causation | fixed descriptive wording; no “because” |
| sparse data looks like failure | explicit coverage/unknown section |
| longevity report becomes a prescription | “captured, not prescribed” label; no cardio logic |
| presets entrench an unvalidated gate | keep gate until W6; presets are explicit entries |
| context flags leak into score | separate data; default no score effect |
| device suppression changes loads unexpectedly | config off by default; decision + tests |
| minimum mode double-reduces | one modifier, explicit precedence, total cap |
| minimum mode removes essential work | preserve primary pattern/essential; validators |
| readiness feedback becomes tuning | report only; no writes to weights |
| docs conflict/privacy | docs cleanup before new reports; no Git history rewrite |

---

## 14. Rollout and approval gates

### Gate 0 — documentation/privacy

- generalise public docs;
- confirm no new personal data;
- known limitations/methodology draft.

### Gate 1 — A outcome review

- read-only report;
- A0 provenance decision;
- no prescription effect;
- tests pass.

### Gate 2 — B longevity section

- same Outcomes page;
- context only.

### Gate 3 — W6 readiness audit

- no implementation;
- decide gate and main-lift reduction policy.

### Gate 4 — C quick readiness

- gate decision required;
- preset values reviewed;
- context flags default no score effect.

### Gate 5 — E feedback

- outcome data available;
- no weight tuning.

### Gate 6 — D minimum session

- W3 complete;
- explicit user choice;
- decision record and sign-off.

---

## 15. First implementation slice acceptance

A was the first slice after Gate 0; all A0–F slices are now implemented.

Acceptance criteria:

- 4/8/12-week windows;
- strength and longevity sections distinct;
- every metric defined, with unknown for missing data;
- citations to sessions/measurements/rules;
- no causal wording;
- CLI and web share one core function;
- no prescription or session mutation;
- tests pass end to end;
- no new snapshot table.

---

## 16. Status of earlier open items

1. A0 modifier provenance — implemented (`prescription_modifier`).
2. Readiness preset values — implemented in `config/readiness-presets.v1.yaml`.
3. HRV/RHR suppression — config present, empty by default; enabling remains a decision.
4. Minimum-session floors — accessory floor 1, main floor 2; deeper tier explicit.
5. “Unwell” — preset plus `illness` context, not a hidden no-training mode.
6. Age/balance/carry — remain separate from this plan.
7. Test-count source — `ROADMAP` header is authoritative.

A0–F are implemented. The full W3 modifier-interaction audit is complete; confirmed defects
are documented in `W3-MODIFIER-MATRIX.md` and fixed with regression tests.
