# Rep-level VBT — post-hoc value, cost and decision

**Status:** not adopted. Rep-level velocity logging is not implemented, and manual per-rep
entry after every workout is not justified. If a device already exports per-rep samples, keep
the raw data for a possible retrospective analysis.

This note records why the feature is not being built now.

---

## 1. The distinction that matters

| form | when available | what it can do |
|---|---|---|
| set-level mean velocity | after the set/workout | calibrate load–velocity bands; provide readiness context; existing use |
| **rep-level velocity** | after the set/workout, unless streamed live | compute within-set velocity loss; describe fatigue/technique retrospectively |
| **live rep-level velocity** | during the set | stop the set at a velocity-loss target; adjust load/volume in real time |

The programme does not have a live VBT feed. Adding rep-level data after the workout therefore
does **not** enable live autoregulation.

---

## 2. What post-hoc rep-level data can still do

1. **Retrospective fatigue monitoring**
   - compute within-set velocity loss for each set;
   - compare the same lift and load across sessions;
   - flag unusually grindy sessions.

2. **Consistency check on RIR**
   - a set logged at RIR 2 with a very large velocity loss may have been closer to failure;
   - this is a check, not a replacement for RIR.

3. **Calibrate future load–velocity relationships**
   - with enough per-rep data, estimate how velocity loss relates to load, reps and performance;
   - could improve future readiness or set-termination rules.

4. **Associate with other outcomes**
   - velocity loss versus sRPE, next-session performance, readiness and back symptoms;
   - descriptive covariate only.

5. **Data-quality audit**
   - implausible velocity curves, device-placement issues, rep-count errors.

## 3. What it cannot do

- stop a set at a velocity-loss threshold;
- adjust load or volume during the session;
- provide live autoregulation;
- reliably infer RIR from velocity, especially for the trap bar;
- establish an individual velocity-loss threshold from one athlete’s retrospective data;
- justify an automatic programme change.

The main evidence-supported use of velocity loss is **live set termination** — roughly 10–20%
for strength/power and 20–30% for hypertrophy. Captured after the workout, the same number is
descriptive, not actionable.

---

## 4. Cost versus benefit

For **manual per-rep entry after every workout**:

- high logging burden;
- transcription and device-placement error;
- no in-session action;
- marginal information beyond sRPE, actual-vs-expected reps, readiness and back symptoms;
- one athlete cannot support a validated individual threshold.

**Not worth building.**

For **automatic device export that already contains per-rep samples**:

- low marginal cost;
- worth archiving raw files;
- useful for a focused retrospective analysis later.

The difference is whether the data arrives automatically or has to be typed.

---

## 5. Decision

1. **No rep-level VBT logging UI, schema or import path now.**
2. **Keep set-level VBT** as the usable input; existing calibration and targets remain.
3. **Do not add manual per-rep entry.**
4. If a device already exports per-rep velocity, **preserve the raw export** outside the normal
   ingestion path. Do not contort the current schema for data with no current use.
5. Revisit only if:
   - per-rep data can be captured automatically;
   - there is a specific question it can answer better than sRPE/performance/readiness;
   - a retrospective baseline shows velocity loss adds information;
   - any future use is descriptive first, not a live stop rule.

This is consistent with:

- `DEC-VELOCITY-01` — within-set velocity loss is not measurable from one mean per set;
- `DEC-VBT-02` — per-rep loss and MVT wait for richer input;
- `docs/VBT-EVIDENCE.md` — velocity loss evidence and its live-use context;
- `docs/VBT-CALIBRATION.md` — what the current calibration can and cannot compute.

---

## 6. What would change the decision

A future phase could revisit rep-level VBT if:

- a device provides per-rep samples automatically;
- the data include load, reps and RIR;
- the athlete wants a specific question answered, for example:
  - does velocity loss predict next-session performance better than sRPE?
  - does velocity loss flag a back-flare prodrome?
- the analysis is pre-specified and descriptive, with no automatic programme change.

Until then, the honest position is: **no rep-level VBT feature.**
