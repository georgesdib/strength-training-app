# Rep-level VBT — post-hoc value, cost and decision

**Status:** optional post-workout **capture + descriptive analysis** implemented (2026-10-24);
the evidence review supports descriptive use only. A device's per-rep CSV can be supplied as a
second, optional table in Workout mode; the set-level path is unchanged. No live termination,
no load/volume adjustment and no prescription input. See [REP-VELOCITY.md](REP-VELOCITY.md) and
[REP-VELOCITY-EVIDENCE.md](REP-VELOCITY-EVIDENCE.md).

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

**Accepted only as an optional device CSV**, because the device already exports it and the
import costs no extra typing. Manual per-rep entry is still not a required workflow.

For **automatic device export that already contains per-rep samples**:

- low marginal cost;
- worth archiving raw files;
- useful for a focused retrospective analysis later.

The difference is whether the data arrives automatically or has to be typed.

---

## 5. Decision

1. **Optional per-rep import** exists as a second CSV in Workout mode; it is not required.
2. **Keep set-level VBT** as the primary input; existing calibration and targets remain.
3. **Do not add mandatory manual per-rep entry.**
4. Device exports are stored as optional `clean_rep` detail; no rule reads them.
5. Revisit only if there is a specific question it can answer better than sRPE/performance/
   readiness, a retrospective baseline shows velocity loss adds information, and any future use
   is descriptive first, not a live stop rule.

This is consistent with:

- `DEC-VELOCITY-01` — within-set velocity loss is not measurable from one mean per set;
- `DEC-VBT-02` — per-rep loss and MVT wait for richer input;
- `docs/VBT-EVIDENCE.md` — velocity loss evidence and its live-use context;
- `docs/VBT-CALIBRATION.md` — what the current calibration can and cannot compute.

---

## 6. What would make it more than descriptive

A future phase could use rep-level VBT for a decision only if:

- the optional import has produced enough complete sessions;
- the athlete wants a specific question answered, for example:
  - does velocity loss predict next-session performance better than sRPE?
  - does velocity loss flag a back-flare prodrome?
- the analysis is pre-specified, held out where possible, and descriptive first;
- any rule change remains policy-controlled, never a live stop rule derived from one athlete.

The current position is: **capture is optional and descriptive; no rep-level rule.**
