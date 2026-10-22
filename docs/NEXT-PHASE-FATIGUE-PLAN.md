# Next-phase fatigue-management plan — final lean version

**Status:** Phase 0 backfill done; descriptive sRPE and readiness–performance reports done;
optional-deload suggestion implemented. No training-programme changes.
**Date:** 2026-10-20
**Scope:** non-cardio fatigue-management work. This supersedes the earlier experimental draft;
the feedback was that the programme must not become an experiment.

---

## 1. Feedback incorporated

The plan now follows these constraints:

- use the data already available plus a one-time sRPE/duration backfill;
- do not require measured 3RM/5RM tests — use the computed e1RM as the outcome, with its
  limitations;
- treat the three known low-back tweaks as the current back-history evidence; revisit only if
  a future episode does not fit the pattern;
- do not invent a “bad session” label;
- do not experiment with or manipulate the training programme;
- do not run a scheduled-deload trial;
- do not build individualised MRV or automatic volume control;
- keep the scheduled deload as an optional suggestion;
- use evidence-informed defaults where data cannot calibrate a decision;
- if a small programme-specific measurement check is needed, limit it to one month and do not
  change training.

The repeated principle: **measure and document; do not experiment on the athlete.**

---

## 2. Direct answers

### 1. What extra information will be available later?

Assuming sRPE and duration are backfilled, the usable dataset will contain:

- session RPE, 1–10;
- session duration;
- actual reps and load;
- computed e1RM from the existing sets;
- daily readiness;
- the three known low-back tweaks;
- future sessions logged normally, if the athlete chooses.

It will **not** contain:

- measured 3RM/5RM tests unless performed for another reason;
- a manual “bad session” label;
- a randomized deload comparison;
- enough volume variation to identify an individual MRV;
- a counterfactual for causal claims.

That is enough for **descriptive calibration**, not for automatic decision rules.

### 2. The three low-back tweaks

Use them as a **qualitative case series**:

- all three occurred in the historical record;
- three events are too few for statistical calibration;
- they justify keeping the existing reactive back rules;
- if a future episode does not fit the expected pattern, revisit the model then.

No new symptom schema or daily symptom logging is required for this plan. Future episodes can be
recorded through the existing mechanism when they happen.

### 3. Will there be a “bad session” label?

No. A label is not necessary and would be another subjective input.

Instead, derive an observational measure:

```text
performance_ratio = actual reps at the prescribed load / expected reps from the current e1RM
```

Use it descriptively. Do not convert it into an automatic trigger in this phase.

sRPE and back episodes provide independent context, but they do not create a validated “bad
session” definition.

### 4. Scheduled-deload calibration

Ignore it for now, as requested.

The scheduled deload remains an **optional suggestion**, not a trial and not an automatic
action. Its effects will not be estimated experimentally.

### 5. Experimenting with the programme

No. The plan does **not**:

- randomise training;
- alter volume to estimate MRV;
- test under-MEV titration;
- test main-lift volume reduction;
- run deload versus no-deload periods;
- use the athlete as a guinea pig.

The programme stays as written unless the athlete independently chooses the optional deload.
Observations are recorded around the existing programme.

---

## 3. Evidence used

| topic | evidence | conclusion for this plan |
|---|---|---|
| Session RPE | Valid global session-load measure ([Foster 2001](https://pubmed.ncbi.nlm.nih.gov/11708692/)), not a validated fatigue/deload trigger | Calibrate descriptively; do not automate |
| Autoregulation | Mixed evidence, no consistent advantage over standardised training ([meta-analysis](https://doi.org/10.1186/s40798-021-00404-9); [review](https://doi.org/10.1007/s40279-020-01330-8)) | Keep decisions with the athlete; no automatic triggers |
| Volume | Dose-response with diminishing returns ([2025 meta-regression](https://link.springer.com/article/10.1007/s40279-025-02344-w); [Schoenfeld 2017](https://www.tandfonline.com/doi/abs/10.1080/02640414.2016.1210197)) | No individual MRV from fixed-programme data |
| MRV/MEV | Coaching constructs, not measured thresholds ([RP](https://rpstrength.com/blogs/articles/training-volume-landmarks-muscle-growth)) | Document the heuristic; no individualisation |
| Deload | Evidence for a fixed schedule is weak; the 2026 trial is narrow ([trial](https://link.springer.com/article/10.1038/s41598-026-40612-5)) | Optional suggestion only; no trial |
| Computed e1RM | Epley + RIR estimate, not a measured test | Accept as an observational outcome with caveats |

Additional evidence note: a single athlete’s observational data cannot identify a causal deload
or MRV effect without deliberate variation or randomisation. Since neither is acceptable here,
the correct output is a descriptive report, not a calibrated controller.

---

## 4. What can and cannot be calibrated

### Can be calibrated descriptively

1. **sRPE scale use**
   - distribution and central tendency;
   - relationship with hard sets, tonnage and duration;
   - expected sRPE with uncertainty.

2. **Readiness–performance association**
   - readiness versus performance ratio;
   - exercise- and load-adjusted if the data allow;
   - clearly labelled associational, not causal.

3. **Back-episode case review**
   - what preceded each episode;
   - what the programme was doing;
   - whether the existing reactive rule would have fired.

4. **Data quality**
   - coverage, missingness, recall bias, scale outliers.

### Cannot be calibrated

- individual MRV;
- optimal weekly volume;
- causal effect of a deload;
- a validated “bad session” threshold;
- a readiness threshold for main-lift volume reduction;
- a performance-decline trigger that is proven to improve outcomes.

These are documented as **not estimable** from the available data, rather than approximated with
false precision.

---

## 5. Data requirements

### Backfill

A single editable table, planned for the Review/Import UI:

| field | rule |
|---|---|
| session date / id | existing session |
| sRPE | 1–10, optional |
| duration | minutes, optional |
| note | optional |
| missing | leave blank; never invent |

- all sessions with a plausible memory;
- append-only corrections;
- no provenance flag;
- phase-start cutoff recorded in the analysis plan, not the schema;
- report coverage.

### Existing data

- actual reps and loads;
- computed e1RM;
- readiness;
- three known low-back tweaks.

### Not required

- measured 3RM/5RM tests;
- daily symptom logging;
- a bad-session label;
- new readiness metrics;
- a block anchor for this descriptive analysis.

---

## 6. Final lean plan

### Phase 0 — Backfill and audit  (done)

**Goal:** make the existing record usable.

1. Build the editable sRPE/duration backfill table (later implementation).
2. Backfill all sessions with plausible recall.
3. Audit:
   - number of sessions with sRPE;
   - number with duration;
   - distribution;
   - missingness;
   - recall-bias caveat.
4. Freeze a phase-start date for retrospective/prospective separation.

**No programme change.**

### Phase 1 — Optional one-month measurement check  (not triggered; decision open)

Only if the backfill leaves a specific, concrete gap.

Examples:

- sRPE is present but duration is too sparse to compute session load;
- the scale is being used inconsistently;
- one lift’s performance ratio cannot be computed.

For at most **one month**:

- log sRPE/duration normally;
- do not change sets, load, exercises or deload policy;
- no experimental conditions.

If no specific gap exists, **skip this phase**.

### Phase 2 — Descriptive calibration report  (sRPE + readiness descriptive done)

Produce, with uncertainty and limitations:

1. sRPE coverage and distribution.
2. sRPE versus hard sets, tonnage and duration.
3. Readiness versus performance ratio.
4. Three low-back case reviews.
5. A statement of what cannot be estimated.

Do not produce:

- an automatic fatigue score;
- an MRV estimate;
- a deload effect estimate;
- a new trigger.

### Phase 3 — Optional deload suggestion  (implemented)

The scheduled deload remains an optional suggestion, not a calibration:

- due every six weeks from a declared anchor;
- ask at workout time;
- default no;
- skip only that workout;
- reactive triggers remain automatic;
- no trial, no randomisation.

The optional-deload suggestion is implemented; the reactive triggers remain automatic.

### Phase 4 — Stop and document  (stop point reached; final closure open)

After the descriptive report:

- keep the evidence-based defaults;
- keep the reactive rules;
- keep the optional deload;
- do not add individualised MRV or main-lift volume control;
- revisit only if a specific observed problem appears.

---

## 7. What the report will say if the data are insufficient

It will say so directly:

- “sRPE coverage is too low to estimate a scale relationship.”
- “Readiness–performance association is descriptive only.”
- “Two back episodes are a case series, not a model.”
- “Deload effect and individual MRV are not estimable.”
- “No programme change is justified.”

That is a valid outcome. It is better than overfitting a model to a single athlete’s fixed
programme.

---

## 8. Decisions

| decision | choice |
|---|---|
| Backfill fields | sRPE + duration |
| Backfill scope | all sessions with plausible memory |
| Missing values | blank |
| Provenance flag | none; use phase-start cutoff |
| Post-session signal | sRPE only |
| Bad-session label | not needed; derive performance ratio |
| Measured strength tests | not required; computed e1RM is the observational outcome |
| Back episodes | three known low-back tweaks as a case series; revisit only if pattern changes |
| Scheduled deload | optional suggestion; no trial |
| Reactive deload | automatic |
| Volume/MRV work | not in this phase |
| Programme experiments | none |
| One-month check | only if a specific data gap exists; no programme change |

---

## 9. Open decisions

1. Edit the bulk backfill table in Review or Import.
2. Define the phase-start cutoff date.
3. Decide the exact descriptive-report format.
4. Decide whether the current reports are sufficient or whether a one-month measurement check is needed.

Phase 0 backfill and Phase 2 descriptive reports are complete; the optional-deload policy is
implemented. No training-programme changes or experiments were made. The Phase 1 measurement
decision and formal Phase 4 closure remain open.
