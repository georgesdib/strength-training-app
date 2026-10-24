# W5 — PROSPECTIVE EVALUATION PROTOCOL

**Status:** protocol complete 2026-10-23. No dashboard, model or policy change.
**Purpose:** define, before looking at the next block, what “is this working?” means.
**Scope:** one athlete, observational, descriptive. No causal claim.

---

## 1. The question

> Over the next 8–12 weeks, is the strength programme producing a coherent strength signal,
> and is training being completed without a new symptom pattern?

This protocol does **not** ask whether readiness, deloads, MRV or selection “cause” better
outcomes. Those need a different design.

## 2. When it runs

| point | window | purpose |
|---|---|---|
| baseline | the 4 weeks before the evaluation block | comparison |
| interim | every 4 weeks | early check, no policy change |
| primary | 8 weeks | main review |
| confirmation | 12 weeks | avoid reacting to one block |

A review needs at least:

- 16 completed sessions in the 8-week window;
- 4 usable e1RM observations for a lift before claiming a trend on that lift.

Below that: `unknown`, not “no progress”.

## 3. Outcomes and definitions

### 3.1 Stable-lift e1RM

For each main lift:

- use one canonical lift identity;
- do **not** combine variants or sides of a date-scoped implement change;
- use the session-best usable e1RM;
- baseline = median of the previous 4 weeks;
- current = median of the last 4 weeks;
- change = `(current − baseline) / baseline`.

| status | rule |
|---|---|
| `up` | ≥ +2.5% and ≥2 observations in each window |
| `down` | ≤ −2.5% and ≥2 observations in each window |
| `stable` | change inside ±2.5% |
| `unclear` | enough data but mixed/insufficient per-window coverage |
| `unknown` | fewer than 2 observations in either window |

The 2.5% threshold is a practical noise guard, **not** a validated minimal important
difference. It is fixed before the block and may not be moved after seeing the result.

### 3.2 Attendance

- `completed_sessions` = distinct session dates;
- `target_sessions` = weeks × `sessions_per_week_target`;
- `attendance_pct`;
- target absent → `unknown`;
- no stored plan → never call the shortfall “missed planned sessions”.

### 3.3 Planned vs completed work

Only live workouts with a frozen plan provide this:

- planned working sets from the modified plan;
- completed working sets from actual sets;
- ratio and status `complete` / `under` / `over`;
- imported sessions have no plan → `unknown`.

### 3.4 RIR adherence

Proportion of working sets with a logged RIR inside **1–4**:

```text
in_window / logged_working_sets
```

Missing RIR is excluded from the denominator and reported as coverage, not treated as
compliance.

### 3.5 Duration

- measured live-workout duration only;
- imported/manual duration is labelled `manual` or `unavailable`;
- compare with the 80-minute planned cap, not a fabricated target.

### 3.6 Symptoms

- any region with a level ≥2 reading is a **reported flare**;
- no symptom entry → `unknown`, never “no flare”;
- do not combine regions into one score.

### 3.7 sRPE

Median and count where recorded. No threshold; descriptive context only.

## 4. Review output

One page, no new dashboard:

| section | output |
|---|---|
| Strength | per-lift status (`up/down/stable/unclear/unknown`), median change, n |
| Attendance | completed / target, percentage, coverage |
| Work completed | planned vs actual, only where a plan exists |
| Effort | RIR adherence, coverage |
| Duration | measured mean/median vs planned cap |
| Symptoms | region, flare count, coverage |
| Context | sRPE median, readiness coverage |
| Data quality | which sources were missing |

Every number links to its source rows. No composite “readiness score” or “programme score”.

## 5. What counts as a regression flag

These are review triggers, not automatic prescription changes:

- stable-lift e1RM `down` by ≥5% across the 8-week comparison;
- two consecutive sessions below 90% of the recent best e1RM;
- a new or worsening symptom flare;
- attendance below 60% of target;
- RIR adherence below 70% with adequate coverage;
- a large unexplained duration drift.

A flag triggers a **review**, not a deload, load cut or rule change.

## 6. Missing data and exercise changes

- Missing is `unknown`; never zero.
- No imputation, no carry-forward, no “normal” default.
- A lift variant change starts a new series; do not splice.
- A date-scoped implement change splits the series at the configured boundary.
- Imported late/backfilled rows are flagged; do not silently treat them as prospective.
- Partial workouts remain incomplete; W2 flags them.

## 7. What would justify a policy change

**Not this protocol alone.**

A policy change would need:

1. a pre-specified outcome and comparison window;
2. enough observations to avoid a handful of sessions;
3. a consistent direction across at least two review points;
4. no increase in symptoms or missed sessions;
5. an explicit `DEC-` entry and user approval.

For readiness specifically, the no-readiness counterfactual remains unavailable (W6). A
prospective association would still be observational. A future candidate model must beat a
simple baseline on held-out data before it can control prescriptions.

## 8. Non-negotiable reporting language

Allowed:

- “the median e1RM was higher/lower”;
- “attendance was 18/24”;
- “the signal is unclear”.

Not allowed:

- “the programme caused the gain”;
- “readiness improved recovery”;
- “the deload worked”;
- “the athlete is injury-free” (when symptom coverage is absent);
- “progress” when the comparison is unknown.

## 9. Implementation mapping

The protocol uses existing data and functions; no new table or model:

| measurement | source |
|---|---|
| e1RM | `clean_set.e1rm_kg`, `features/outcomes.py` |
| attendance | `features/attendance.py` |
| planned vs actual | `workout.comparison` |
| RIR adherence | `clean_set.rir`, rubric logic |
| duration | `session_feedback.duration_min` / `session.duration_basis` |
| symptoms | `symptom_log` |
| sRPE | `session_feedback.srpe` |
| readiness coverage | `readiness_entry` / `readiness_day` |

## 10. Exit criteria

- The athlete can answer “is this working?” with a one-page descriptive review: **yes**.
- Missing data is visibly unknown: **yes**.
- No threshold is changed from a handful of observations: **yes**.
- No new model or dashboard is introduced: **yes**.

This is a protocol, not an evaluation result. No training policy changed.
