# Next-phase fatigue-management plan

**Status:** planning only. No implementation has been approved or performed.
**Date:** 2026-10-20
**Scope:** the non-cardio fatigue-management items. Cardio–strength interaction is explicitly
out of scope.

This document records the decisions reached interactively, the evidence behind them, the data
gaps, and the proposed next phase.

---

## 1. Decisions locked

| decision | choice |
|---|---|
| Historical session RPE backfill | all sessions with a plausible memory |
| Backfill fields | session RPE and session duration |
| Backfill method | editable table in the Review/Import UI, planned |
| Missing values | leave blank and record as missing |
| Retrospective provenance flag | none |
| Separate post-session fatigue rating | none — session RPE is the only post-session signal |
| Scheduled deload | **suggestion**, not automatic |
| Prompt frequency | every workout in the due week |
| Declining a scheduled deload | skips only that workout; the next workout in the week asks again |
| End of due week | the opportunity is skipped until the next six-week cycle |
| Reactive deload triggers | remain automatic |
| Non-interactive default | no scheduled deload unless explicitly confirmed |
| Randomised scheduled-deload trial | **not doing one** |
| Evaluation design | observational plus shadow triggers |
| Primary outcomes | session performance and back symptoms/flares |
| 3RM/5RM testing | every 10–12 weeks, alternating |
| Warm-up | 3 ramp sets at approximately 50%, 70%, 85% of working load |
| Under-MEV volume work | accessory titration after backfill; no main-lift volume changes initially |
| Individualised MRV / main-lift volume | deferred until observational data exist |
| Prospective phase start | after the bulk backfill is complete |

### Deload behaviour in detail

The scheduled deload remains a configurable opportunity, not a command:

- computed from the declared `block_start_date` every six weeks;
- when a workout is requested in the due week, the athlete is asked whether to deload;
- default is **no**;
- declining affects only that workout;
- the next workout in the same week asks again;
- once the week ends, the opportunity is skipped until the next cycle;
- accepting applies the low-volume deload;
- reactive triggers — two weeks over the spinal cap, or two consecutive back flares — still
  apply automatically.

No randomised trial of the scheduled deload will be run. The evidence for a fixed deload
calendar is weak; the policy remains optional.

---

## 2. Direct answers

### Can session RPE be backfilled in the Review tab?

Yes. Session RPE and duration are stored independently of rubric marks. A feedback row can be
saved without any rubric scores; blank values remain missing. Corrections append a new row and
the latest row wins.

### Will session RPE be used if the rest of the review is blank?

Yes for future analysis; no model currently reads it. The planned bulk backfill and analysis
will use it independently.

### Can existing data plus evidence be calibrated now?

Partially, and only descriptively. Existing data can support some association analyses, but not
the decision calibrations in this plan. The concrete gaps are documented in §4.

---

## 3. Evidence summary

| topic | evidence | planning consequence |
|---|---|---|
| Session RPE | Valid global session-load measure ([Foster 2001](https://pubmed.ncbi.nlm.nih.gov/11708692/)), but not a validated recovery or deload trigger | Use as a load/trend signal, not an automatic trigger |
| Autoregulation | Load/volume autoregulation does not consistently outperform standardised training ([meta-analysis](https://doi.org/10.1186/s40798-021-00404-9)); definitions vary ([review](https://doi.org/10.1007/s40279-020-01330-8)) | Keep candidate triggers in shadow mode |
| Volume | Dose-response exists with diminishing returns ([2025 meta-regression](https://link.springer.com/article/10.1007/s40279-025-02344-w); [Schoenfeld 2017](https://www.tandfonline.com/doi/abs/10.1080/02640414.2016.1210197)) | Under-MEV accessory titration is plausible; main-lift cuts need caution |
| MRV/MEV | Coaching constructs, not measured individual thresholds ([RP](https://rpstrength.com/blogs/articles/training-volume-landmarks-muscle-growth)) | Report estimated tolerance, not “MRV” |
| Deload | Evidence for a fixed schedule is weak; the 2026 trial is narrow ([trial](https://link.springer.com/article/10.1038/s41598-026-40612-5)) | Keep scheduled deload optional and untested as a formal trial |
| Performance decline | A useful contextual fatigue signal, but no validated universal threshold | Shadow rule only |
| Warm-up | Standardising the ramp improves comparability more than it proves an optimal warm-up | Use 50/70/85; do not count ramp sets as working volume |
| Strength testing | 3RM/5RM is a practical, submaximal strength outcome | Alternate every 10–12 weeks |

**Core conclusion:** the next phase should improve measurement and compare signals without
adding automatic fatigue rules.

---

## 4. What calibration needs, and what is missing

“Calibration” here covers three different things:

1. **Scale calibration** — mapping a self-report or derived signal to a measured quantity.
2. **Model calibration** — estimating parameters from variation in inputs and outcomes.
3. **Decision calibration/validation** — testing whether a rule improves an outcome versus an
   alternative.

The planned decisions need the third kind. That is why descriptive analysis of the existing
data is possible while decision calibration is not.

### 4.1 Session-RPE calibration

**What it needs**

- session RPE for many sessions;
- duration for the same sessions;
- working sets, tonnage and exercise mix;
- enough variation in session demand to estimate a relationship;
- a clear distinction between retrospective and prospective entries.

**Current gap**

- session RPE is essentially absent from the historical record;
- duration is likewise absent;
- without RPE there is no signal to calibrate;
- without duration, sRPE × duration cannot be computed.

**What is possible now**

At most a descriptive audit of how session demand relates to performance. No sRPE calibration
until backfill exists.

**After backfill**

- distribution and scale-use check;
- sRPE versus hard sets, tonnage and duration;
- expected-sRPE model with uncertainty;
- descriptive report only, not an automatic fatigue model.

### 4.2 Readiness calibration

**What it needs**

- repeated readiness scores;
- a performance outcome not derived from the same readiness inputs;
- enough sessions with both good and poor readiness;
- a model that accounts for exercise, load and training phase.

**Current gap**

Readiness coverage is good, but:

- session RPE is missing, so perceived effort cannot be used as an independent criterion;
- back-symptom records are absent;
- measured strength tests are absent;
- performance at a fixed load is confounded by exercise selection, readiness-driven load
  changes and missing effort data;
- the readiness score itself is a constructed index, not a measured quantity.

**What is possible now**

A descriptive readiness–performance association can be estimated. It cannot establish a
readiness threshold or validate a readiness-triggered deload.

### 4.3 Performance-decline calibration

**What it needs**

- actual reps at the prescribed load;
- expected reps from a stable e1RM/RIR model;
- enough sessions per lift;
- a definition of a “bad session” independent of the trigger being tested;
- prospective recording, so the threshold is not chosen after seeing the outcome.

**Current gap**

- actual reps and loads exist;
- session RPE is missing;
- measured e1RM tests are absent, so expected performance rests on formula-derived estimates;
- there is no recorded deload decision/outcome to compare against.

**What is possible now**

A retrospective performance-ratio analysis. It can generate candidate thresholds, not validate
them.

### 4.4 Scheduled-deload calibration

**What it needs**

- deload events and non-deload comparison periods;
- a counterfactual: what would have happened without the deload;
- outcomes measured before and after;
- enough deload opportunities;
- a decision record for accepted/declined suggestions.

**Current gap**

- no block anchor, so no scheduled deload due dates;
- no recorded deload events or decisions;
- no symptom records for the back-safety outcome;
- no randomised or otherwise credible counterfactual.

**Planning decision**

No randomised trial. The scheduled deload remains an optional suggestion. Any comparison will
be observational and cannot establish efficacy.

### 4.5 Individualised MRV / under-MEV calibration

**What it needs**

- deliberate variation in weekly volume, independent of outcome;
- per-pattern volume and per-pattern performance;
- enough repeated blocks to estimate a dose-response;
- a stable outcome;
- ideally some randomised volume variation.

**Current gap**

- the programme has been largely fixed, so volume variation is limited;
- no measured strength tests;
- no symptom outcomes;
- MRV is not directly measurable;
- a single athlete’s observational data cannot identify an individual maximum.

**What is possible**

Under-MEV accessory titration can be evaluated as a small prospective series. Individualised
MRV should be reported only as an estimated tolerance band after substantial data.

### 4.6 Back-symptom calibration

**What it needs**

- repeated pre-session symptom levels;
- flare/settling outcomes;
- enough exposed and unexposed sessions;
- a defined temporal window.

**Current gap**

No symptom records are available, so back symptoms cannot currently be modelled or calibrated.

---

## 5. Proposed next-phase plan

### Phase 0 — Bulk backfill and baseline

**Goal:** create usable retrospective data without changing prescriptions.

**Deliverable:** editable backfill table in the Review/Import UI.

Columns:

- session date / session id;
- sRPE, 1–10;
- duration, minutes;
- optional note;
- missing cells left blank.

Rules:

- all sessions with a plausible memory;
- corrections append, never overwrite;
- no provenance field; the phase-start date is the retrospective/prospective cutoff;
- report coverage and missingness;
- do not use retrospective data as if it were prospective.

Also:

- record a 3RM or 5RM baseline;
- introduce the standardised warm-up ramp;
- freeze the data dictionary before prospective collection.

**Gate:** acceptable coverage, no unresolved schema changes.

### Phase 1 — Optional deload prompt

**Goal:** make the scheduled deload a suggestion at the point of use.

Planned behaviour:

- due week computed from the block anchor;
- prompt on each workout request;
- default no;
- decline skips only that workout;
- skip after the due week ends;
- reactive triggers automatic;
- non-interactive default no.

The Programme forecast shows a suggested deload but does not apply it.

### Phase 2 — Observational phase, 16 weeks

Collect:

- sRPE and duration;
- actual reps at prescribed load versus expected reps;
- back symptoms and flares;
- readiness;
- deload choices;
- adherence.

Shadow signals:

- two sessions below expected reps;
- readiness trend;
- sRPE trend;
- optional deload uptake.

These are reported, not applied.

**Primary outcomes:** session performance (actual vs expected reps) and back symptoms/flares.
**Secondary outcomes:** sRPE/duration trend, adherence, deload uptake, readiness.

**Gate:** at least 80% completeness over 16 weeks before drawing conclusions.

Because deload acceptance is self-selected, any comparison is observational and confounded.

### Phase 3 — Under-MEV accessory titration

After backfill, and separate from the deload question:

- accessory patterns only;
- one set added to one accessory when a pattern is below MEV for at least three weeks;
- hold for two weeks;
- evaluate performance, sRPE and back symptoms;
- one change at a time;
- no main-lift volume changes.

### Phase 4 — Revisit volume individualisation

After at least 12–16 weeks of prospective data:

- estimate per-pattern volume-response;
- report an estimated tolerance band, not MRV;
- consider main-lift readiness volume reduction only as a separate test;
- default remains load/RIR adjustment.

### Phase 5 — Strength and warm-up enabling work

- 3RM/5RM every 10–12 weeks, alternating;
- baseline test in Phase 0;
- 3 ramp sets at approximately 50%, 70%, 85% of working load;
- ramp sets are not working volume;
- same ramp structure per main lift for comparability.

---

## 6. What this plan deliberately does not do

- No randomised scheduled-deload trial.
- No automatic scheduled deload.
- No automatic performance/readiness deload trigger.
- No main-lift volume reduction by default.
- No individualised MRV claim.
- No separate post-session fatigue score.
- No LLM-driven fatigue decisions.
- No cardio work.

---

## 7. Limitations to record

- Retrospective sRPE is recall-biased and has no provenance flag.
- The phase-start cutoff must be recorded in analysis, not inferred from the schema.
- Session RPE conflates effort with fatigue; it is not a recovery measure.
- Deload decisions are observational and self-selected.
- Back symptoms are currently absent, so the primary safety outcome has no historical baseline.
- Formula-derived e1RM is not a measured strength outcome.
- A single athlete cannot support a precise individual MRV estimate.

---

## 8. Open decisions before implementation

1. Bulk backfill table in the **Review** tab or a separate **Import** panel.
2. Prospective phase start date.
3. Whether the optional deload prompt offers a one-click “decline for this week” shortcut.
4. Exact reporting format for the 16-week observational phase.

No code or configuration has been changed for this plan.
