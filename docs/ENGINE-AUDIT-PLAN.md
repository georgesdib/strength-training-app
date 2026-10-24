# STRENGTH-FIRST ENGINE AUDIT — living plan

**Status:** living audit plan. No implementation. Refined as further audits are completed.
**Companion:** [`IMPLEMENTATION-PLAN-2026-10.md`](IMPLEMENTATION-PLAN-2026-10.md) records the approved product direction and implementation order.
**Date:** 2026-10-23
**Scope:** the deterministic coaching engine, its prescription behaviour and its evaluation.
**Not in scope:** rewriting the architecture, adding commercial infrastructure, Olympic
lifts, medical diagnosis, or new scoring/fatigue models.

---

## 1. Purpose

This plan turns the external audit brief into a sequence of **bounded, evidence-led audits**.

The goal is not to produce a large report. It is to answer specific questions about whether
the engine:

- produces a coherent strength stimulus over months;
- behaves safely across missed sessions, incomplete sessions and variable recovery;
- avoids contradictory or double-applied modifiers;
- keeps the deterministic/LLM boundary intact;
- distinguishes evidence from assumptions;
- collects enough prospective data to evaluate itself.

Each audit ends with **findings and recommendations**, not code changes. Implementation needs
separate approval.

---

## 2. Starting point — decisions not to reopen without new evidence

The audit must respect the existing decision log. The following are closed unless a new
finding contradicts them:

| decision | current position |
|---|---|
| readiness weights | fixed weights retained; learned weights closed after held-out comparison |
| MRV | not estimable from this observational log; descriptive only |
| continuity calibration | fixed reduction retained; calibrated model non-controlling |
| fatigue model | shadow only; lost to simpler baselines |
| exercise substitution | suggestions + explicit apply; automatic withholding deferred |
| test fatigue | high-intensity exposure guard implemented; prospective review pending |
| rolling session types | four canonical types; schedule tie-break fixed |
| readiness thresholds | fixed safety floors; rolling baseline only where documented |

An audit may challenge these only with **new evidence**, not by restating the original
argument.

---

## 3. Audit principles

1. **Verify before claiming.** A suspected defect needs a code path, a reproducible input and
   an observed wrong output.
2. **Separate defect from trade-off.** “I would design it differently” is not a defect.
3. **One question per audit slice.** Keep each slice small enough to finish and review.
4. **Evidence over complexity.** Compare complex logic with a simple baseline where possible.
5. **No silent policy changes.** Thresholds, constitution rules and user-owned programming
   choices require explicit approval.
6. **Tests follow questions.** Add a regression test only for a confirmed behaviour or an
   agreed acceptance criterion.
7. **Preserve the working system.** No broad refactor during an audit.
8. **No causal claims from a single-athlete record.** Trends are descriptive unless a
   prospective design supports more.

---

## 4. Audit workstreams

### W0 — Execution-path map and baseline

**Question:** what actually happens, in order, from import to the next prescription?

Trace and document:

```text
raw import
→ clean sets / sessions
→ athlete state
→ readiness / stress / injury
→ exercise selection
→ load / e1RM / calibration
→ volume / continuity / deload
→ validation
→ workout execution
→ review / critique
→ next prescription
```

Deliverable:

- a short execution map with the functions and data read at each step;
- a list of inputs that can be missing, stale or non-comparable;
- a current test-coverage map for each step;
- a list of candidate findings (not yet confirmed).

Exit criteria:

- every prescription modifier has a named owner function and call order;
- no undocumented branch remains on the main path.

---

### W1 — Attendance and rolling schedule

**Question:** does the rolling programme remain coherent when attendance is imperfect?

Cases:

- normal 3-session week;
- 2-session week;
- repeated 1–2 session weeks;
- 2–4 week gap;
- missed main-lift day;
- repeated session-type emphasis;
- back-to-back same-family sessions;
- a holiday/reset of the block anchor.

Check:

- 8–24 week exposure counts by lift family;
- whether missed work becomes a backlog;
- whether the schedule creates three-in-a-row emphasis again;
- whether main lifts disappear for long stretches;
- whether power or core work gets displaced;
- whether session duration is respected.

Candidate findings to verify:

- `athlete_profile.max_session_minutes` is stored/displayed but not consumed by the engine;
- template `time_cap_s` is fixed and may not reflect the athlete’s configured limit;
- the rolling target is a six-session window and may behave unevenly over short blocks.

Deliverable:

- a deterministic attendance simulation table over 12–24 weeks;
- confirmed schedule defects or an explicit “no defect found” conclusion;
- proposed regression tests for any confirmed defect.

Exit criteria:

- every attendance case has an expected exposure pattern and an observed one;
- no unexplained consecutive emphasis or lost main-lift block.

---

### W2 — Load lineage and incomplete sessions

**Question:** can a stale, missing or changed input produce a misleading load?

Trace:

- formula e1RM and measured overrides;
- calibration factor and decay;
- rounding and increments;
- last working load fallback;
- variant/history equivalence;
- missed sessions and continuity;
- incomplete workouts;
- changes of exercise.

Check:

- stale e1RM within and outside the decay window;
- manual override precedence;
- variant change with a different load basis;
- incomplete session followed by a normal session;
- repeated poor sessions;
- bodyweight/added-load cases;
- `NO_LOAD` and fallback paths.

Deliverable:

- a load-lineage table: input → function → output → validator;
- a list of cases where the load is defensible but the provenance is not visible;
- confirmed defects only where the output is wrong or contradictory.

Exit criteria:

- every prescribed load can be traced to an input and a cited decision;
- incomplete work does not create phantom progression;
- variant changes never silently reuse incompatible loads.

---

### W3 — Modifier interaction matrix

**Status:** audit complete 2026-10-23; six confirmed defects fixed and regression-tested. See
[`W3-MODIFIER-MATRIX.md`](W3-MODIFIER-MATRIX.md).

**Question:** do readiness, stress, continuity, deload, volume and injury rules stack
coherently?

Build a matrix of combinations:

| dimension | cases |
|---|---|
| readiness | ready / insufficient / unknown / low |
| recent stress | normal / high |
| continuity | normal / short gap / long gap |
| deload | none / scheduled / reactive / both |
| volume | under MEV / normal / over MRV |
| injury | clear / monitoring / active / hard constraint |
| selection | none / applied / skipped / blocked |

Check for:

- double load reduction;
- set reduction plus MRV cap plus deload;
- RIR bump stacking;
- injury ceiling overridden by a modifier;
- continuity reduction applied twice;
- a warning that contradicts the applied action;
- a modifier that silently removes essential work.

Deliverable:

- a combination matrix with expected vs observed effects;
- a priority list of contradictions;
- regression tests for each confirmed contradiction.

Exit criteria:

- no combination applies the same policy twice without an explicit cap;
- the most restrictive safety rule wins;
- essential work is removed only by an explicit rule.

---

### W4 — Programme quality and evidence

**Question:** is the programme a coherent strength stimulus, and which rules are evidence,
heuristic, hypothesis, constraint or unvalidated model?

For each important rule, classify:

```text
direct evidence
reasonable coaching heuristic
athlete-specific hypothesis
engineering/safety constraint
unvalidated model
```

Rules to classify:

- load selection and e1RM;
- progression/regression;
- readiness weights and cut-points;
- continuity reductions;
- deload triggers;
- volume landmarks and the MRV cap;
- under-MEV accessory progression;
- exercise comparability;
- power placement;
- session-type balance;
- high-intensity exposure guard.

Deliverable:

- an evidence table with confidence and the exact file/function;
- a list of claims that need qualification;
- a list of rules that should be simplified or left alone.

Exit criteria:

- every controlling rule has a classification;
- no assumption is presented as established evidence;
- no new model is proposed unless it beats a simple baseline on held-out data.

---

### W5 — Prospective evaluation design

**Question:** what is the smallest evaluation that can distinguish real progress from noise?

Measurements:

- stable-lift e1RM trend;
- planned vs completed sets;
- RIR/effort adherence;
- attendance;
- session duration;
- back symptoms;
- optional sRPE.

Define in advance:

- the comparison window;
- what counts as a meaningful change;
- how missing data and exercise changes are handled;
- what would count as a regression;
- what would justify changing a policy.

Deliverable:

- a one-page evaluation protocol;
- a small set of summary outputs, not a new dashboard;
- explicit non-causal language for the single-athlete record.

Exit criteria:

- the athlete can answer “is this working?” without a new model;
- no threshold is changed from a handful of observations.

---

## 5. Finding format

Every audit finding must use this structure:

```text
ID:
Severity: critical | high | medium | low
Status: confirmed defect | trade-off | hypothesis | documentation issue
Question:
Evidence:
  - code path / file / function
  - input and observed output
  - test or simulation
Expected:
Observed:
Impact:
Confidence:
Proposed action:
Regression test:
Approval needed:
```

“Critical” is reserved for issues that can produce an incorrect, contradictory or unsafe
prescription. A design preference is not critical.

---

## 6. Prioritisation

### Critical

- contradictory modifiers;
- wrong load from stale/incompatible lineage;
- injury/constraint override;
- a prescription that removes essential work unexpectedly;
- a schedule that creates a large, silent exposure gap.

### High

- attendance and session-duration behaviour;
- incomplete-session semantics;
- cumulative modifier effects;
- variant-change load comparability;
- missing regression coverage for a confirmed defect.

### Medium

- warning clarity;
- provenance display;
- evaluation summaries;
- test gaps without a known defect.

### Low / leave alone

- dashboard sophistication;
- new scores;
- model complexity without a baseline win;
- re-litigating closed readiness/MRV decisions without new data.

---

## 7. Sequence and review gates

Each workstream is a separate audit report. Do not run them all in one pass.

```text
W0 execution map
  ↓ review
W1 attendance and rolling schedule
  ↓ review
W2 load lineage and incomplete sessions
  ↓ review
W3 modifier interaction matrix
  ↓ review
W4 programme quality and evidence
  ↓ review
W5 evaluation design
```

After each workstream:

1. the report separates confirmed defects from hypotheses;
2. the user reviews priorities;
3. only then is an implementation plan written;
4. implementation is a separate approval, not part of the audit.

---

## 8. First slice — recommended

Start with **W0 + W1**.

Why:

- the rolling schedule was recently found to have a real consecutive-squat bug;
- attendance is the athlete’s main real-world constraint;
- schedule errors affect every downstream modifier;
- the session-duration field is a concrete potential inconsistency;
- the slice is small enough to finish before expanding.

Deliverable for the first slice:

- execution-path map;
- 12–24 week attendance simulation;
- confirmed schedule/duration findings;
- a small set of regression-test proposals;
- explicit “no defect found” statements where applicable.

---

## 9. What this plan does not do

- no implementation;
- no constitution change;
- no threshold change;
- no new model;
- no broad refactor;
- no claim that a design preference is a defect;
- no causal conclusion from one athlete’s history.

---

## 10. Open questions for refinement

These are intentionally left open for the next audit pass:

1. Should `max_session_minutes` constrain prescription generation, or is it informational?
2. What is the expected exposure pattern over a 12-week block with 2 sessions/week?
3. How should an incomplete workout feed the next load decision?
4. Which modifier combinations are currently untested?
5. Which evidence classifications need a citation, and which are admitted assumptions?
6. What is the minimum prospective sample before a policy review?

The plan will be refined after each audit report, not by adding more scope in advance.


---

## 11. Round 2 review intake

This section records a second review of the docs and proposed changes. It does not imply that
every item is a confirmed defect.

### 11.1 Substantive findings

| ID | item | finding | classification | action |
|---|---|---|---|---|
| A1 | Readiness never tested against no readiness | **Confirmed evidence gap.** The readiness-weight report compares only weight variants; it has no no-readiness baseline. The late held-out association is essentially zero (ρ ≈ 0.00). Readiness still changes load/RIR/sets and gates current/future prescriptions. | Confirmed audit gap + policy question | New **W6**; no change until the walk-forward and user decision |
| A2 | Attendance not measured | **Confirmed.** The progress dashboard reports sRPE coverage, performance ratio, volume and back symptom; it does not report sessions completed vs planned or injury-free weeks. “Adherence” in existing docs refers to RIR/progression compliance, not attendance. | Confirmed missing metric | New **W7**; descriptive only, no load effect |
| A3 | Volume split vs longevity | **Arithmetic confirmed.** The current templates produce squat ≈7, bench ≈12 and trap-bar ≈5 sets/week; total ≈57 reconciles. The imbalance is a programme decision, not a calculation bug. | Design trade-off requiring user choice | New **W8**; present options, no change |
| A4 | Spinal cap has no headroom | **Structural finding confirmed.** A normal week is designed to reach cost 3 against cap 3. The reactive trigger fires only when cost is **greater than** cap, so an exact-cap week does not trigger it; however the ordinal costs are summed as cardinal values and the sumo 2.5 is an assumption. Frequency of >3 weeks needs measurement. | Confirmed structural risk + open data question | New **W9**; measure, do not change cap |
| A5 | Age not recorded | **Confirmed.** `athlete_profile` has no age field. The longevity review's power/balance advice is age-conditional. | Confirmed state gap | New **W10**; requires schema/state decision |

#### A1 detail — readiness baseline

The existing report says:

- fixed weights are retained after the weight comparison;
- the late held-out association is effectively zero;
- readiness is used to change the prescription, creating circularity;
- no learned weights are justified.

What it does **not** answer:

```text
Does the readiness-modified prescription beat “repeat the last session plus simple rules”
when both are evaluated walk-forward?
```

The audit must compare:

- current readiness-modified prescription;
- no-readiness baseline (repeat last comparable session + normal progression/continuity);
- safety floor only (sleep/energy + symptoms), with other readiness effects advisory;
- the same held-out dates and outcome definition used for the fatigue/continuity audits.

Policy options after the result:

1. keep readiness as-is if it wins;
2. make main-lift set reduction opt-in and keep load/RIR advisory if it does not;
3. make the readiness gate skippable with an explicit neutral default;
4. keep the sleep/energy and symptom floor even if the score becomes advisory.

These are user-owned decisions. No change in this audit plan.

**Also confirmed:** `READINESS-WEIGHT-EVIDENCE.md` says “No automatic main-lift volume
change from readiness,” while `config/readiness.v1.yaml` has `include_essential: true` and
the engine reduces essential sets. That is a documentation/implementation conflict that must
be resolved whichever policy wins.

#### A2 detail — attendance metrics

Proposed descriptive metrics:

```text
sessions_completed / sessions_planned
attendance_pct
injury_free_weeks
```

Requirements:

- no load, RIR or set effect;
- declared direction and aggregation in `metric_definition`;
- planned sessions derived from the rolling forecast/calendar, with a documented definition;
- missing data reported as unknown, never zero.

#### A3 detail — volume options

Do not change sets yet. Present options within:

- the spinal cap;
- the session-duration cap;
- the existing upper-body coverage;
- the athlete's preference for strength first.

Candidate directions:

1. shift one bench/support set to a squat or single-leg exposure;
2. reduce redundant pressing volume without removing the main bench exposure;
3. add low-axial-cost lower-body work (e.g. single-leg/hip support);
4. leave the split unchanged and document it as a deliberate strength-first choice.

Each option needs expected weekly sets, spinal cost, session time and a rationale.

#### A4 detail — spinal-cap headroom

The audit must report:

- how often a normal prescription week has cost exactly 3;
- how often it exceeds 3;
- which exercise/set causes the excess;
- how often two consecutive weeks exceed 3 and trigger the reactive deload;
- whether the 2.5 sumo half-step makes a meaningful difference to those counts.

Do not silently convert the cap to a cardinal scale or add headroom. Options for later:

- treat the cap as an ordinal exposure count, not a fractional sum;
- keep the fractional sum but add explicit headroom;
- leave it and accept that a normal week is at the ceiling;
- change the template/exercise selection.

#### A5 detail — age

Age is not in the athlete state. Adding it requires:

- a profile/schema field and a migration;
- an explicit purpose (power/balance optional slots, not a load multiplier);
- a wording change from age-conditional evidence to an athlete-specific rationale;
- no automatic age-based load reduction.

Recommended wording for the box jump:

> “Plausible, cheap and low-fatigue at this age; not established as a necessary
> age-specific intervention.”

### 11.2 Documentation defects

| ID | item | finding | classification |
|---|---|---|---|
| B6 | Session-length cap inconsistent | **Resolved in current tree.** The policy is 80 minutes planned / 90 minutes hard; templates use 80; `LONGEVITY-REVIEW` and the rubric docs now match. `max_session_minutes` remains informational until duration is consumed by the engine. | Documentation fixed; engine consumption still open |
| B7 | Duration marked unmeasurable | **Confirmed for imported sessions; outdated for live workouts.** Live workout materialisation stores measured duration, but the rubric still marks `SESSION_DURATION` unmeasurable and does not score it. | Documentation + rubric gap |
| B8 | Test counts conflict | **Confirmed.** Historical counts appear in different docs; `CHANGELOG` still contains 604/589 while `ROADMAP` has a newer count. | Documentation maintenance |
| B9 | Architecture says no UI / no LLM numbers | **Confirmed contradictions.** `ARCHITECTURE.md` says “No UI (explicitly deferred)” while the local web UI exists. It also says the LLM never touches numbers, while proposals may change set counts and choose precomputed menu options. | Documentation contract drift |
| B10 | Public docs contained athlete-specific data | **Resolved in current tree.** Exact episode history, example performance values, the trap-bar switch date and single-athlete sample sizes were removed from public docs; exact details are in `private/docs/PRIVATE-CONTEXT.md`. Earlier Git history remains public. | Privacy issue; no history rewrite |

#### B6 detail — cap resolved

The policy is **80 minutes planned / 90 minutes hard ceiling**. Templates use 80. The docs
now match. `max_session_minutes` remains informational until the engine consumes measured
duration. No template change is needed for this documentation pass.

#### B7 detail — duration

The rubric should distinguish:

- imported/manual session with no measured duration → unmeasurable, as today;
- live workout with `duration_basis=measured` → score duration against the chosen cap;
- manual duration without timestamps → score or label as manual, with provenance.

This requires a rubric-version bump and tests. It does not change loads.

#### B8 detail — counts

Use one authoritative location, preferably the `ROADMAP` header, and remove test counts from
narrative docs. Historical changelog entries may keep their historical counts if clearly
labelled historical. Auto-generation is optional; a single source is sufficient.

#### B9 detail — architecture contract

Reconcile to the actual contract:

- the local web UI is part of the architecture, not a deferred omission;
- the LLM never performs arithmetic, writes a load/RIR/velocity, or vetoes a rule;
- the LLM may choose precomputed menu options and propose structural set-count changes
  within the bounds enforced by Python.

#### B10 detail — public data and Git history

Move or generalise:

- low-back episode count/case series;
- manual e1RM values;
- the date-scoped trap-bar switch if it identifies the athlete;
- single-athlete sample sizes and exact dates;
- personal dates, competition dates and unique history details.

Important: deleting text from current docs does **not** remove it from Git history. A public
repository requires an explicit decision about history rewriting, or accepting that the
history remains public. Do not rewrite history without separate approval.

### 11.3 New workstreams

| ID | workstream | depends on | deliverable |
|---|---|---|---|
| W6 | Readiness vs no readiness | W0 | audit complete; no-readiness counterfactual not identifiable; Option B (main-lift set reduction opt-in) accepted |
| W7 | Attendance metrics | W0 | metric definitions and descriptive dashboard proposal |
| W8 | Volume balance | W1/W4 | options with sets, spinal cost, time and rationale |
| W9 | Spinal cap headroom | W1/W3 | frequency table and cap/ordinality options |
| W10 | Age in athlete state | W0 | schema/state proposal and wording changes |
| W11 | Documentation consistency | W0 | one cap, duration policy, test-count source, architecture contract |
| W12 | Public-data audit | none | inventory, generalisation plan and Git-history decision |

### 11.4 Revised priority order

```text
0. W12 public-data audit (decision only; privacy is time-sensitive)
1. W0 execution map
2. W6 readiness vs no readiness
3. W1 attendance and rolling schedule
4. W9 spinal-cap headroom
5. W2 load lineage and incomplete sessions
6. W3 modifier interaction matrix
7. W8 volume balance
8. W10 age
9. W11 documentation consistency
10. W5 prospective evaluation design
```

W4 (programme quality/evidence) runs alongside W6/W8/W9 as the evidence classifier.

### 11.5 What would count as confirmed

For A1:

- a reproducible walk-forward where the no-readiness baseline beats or ties the current
  readiness-modified path on the same dates and outcome;
- a documented outcome definition and missing-data handling.

For A2:

- a metric that can be computed from stored sessions and the planned rolling calendar;
- no path from the metric into a prescription.

For A3/A4/A5:

- arithmetic and observed counts, not just a design opinion.

### 11.6 Items explicitly deferred

- No change to readiness weights, thresholds or gate in this plan.
- No change to MEV/MAV/MRV or the spinal cap.
- No change to session templates or volume split.
- No new age-based load rule.
- No new fatigue model.
- No Git-history rewrite.
- No cardio expansion.

No implementation has been done.
