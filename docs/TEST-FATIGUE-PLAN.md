# TEST FATIGUE — evidence and proposed recovery guard

**Status:** proposal only. No implementation, no decision, no change to the current test
workflow.
**Question:** a strength test is excluded from working volume, but it is still a high-intensity
exposure. How should the app represent its fatigue and protect the next session?

---

## 1. Current state

A test is recorded as a measured e1RM override (`DEC-TEST-01`):

- it is not written into `clean_set`;
- it does not count as working volume or tonnage;
- it does not enter the volume ledger, double progression or the RIR rule;
- it currently does **not** create a fatigue/recovery flag for the next session;
- the test still counts for the trained-week index used by continuity/ramp logic.

That split is correct for **volume** but incomplete for **fatigue**.

## 2. Evidence

### A single test is not automatically a large fatigue dose

García Valverde et al. (2024) had trained participants perform a bench-press 1RM test on four
consecutive days:

- 1RM and submaximal velocity did not change significantly across days;
- perceived recovery was affected only in the stronger group from day 3, and remained
  “moderately” to “well recovered”;
- DOMS rose on days 3–4 but stayed low (< 3.3/10);
- RPE was high but stable.

This is useful counter-evidence to the assumption that one test necessarily produces a large
systemic fatigue debt. It does not show that a test is free of cost, and it is bench press, not a
heavy hinge or a lower-body 1RM.

### Reliability does not imply zero fatigue

1RM test–retest reliability is generally good to excellent (Grgic et al. 2020), but reliability
is about consistency, not recovery. A test can be reliable while still being a high-intensity
exposure.

### Lower-body and axial tests are different

The current programme already treats near-maximal hinge work as the highest spinal-risk
exposure. A lower-body 1RM or 3RM test has a different risk and recovery profile from a bench
test. The evidence is too sparse to assign one recovery time to every test.

### What the evidence does not give us

There is no validated conversion from:

```text
one 1RM test
```

to:

```text
equivalent working sets
or a precise next-day fatigue percentage
```

A numeric fatigue model would be a fabricated precision. The defensible approach is a
conservative exposure guard, not a load multiplier derived from an invented equivalence.

## 3. Interpretation

- A test is low **volume** but high **intensity**.
- “Not volume” does not mean “no fatigue.”
- The fatigue is probably smaller and shorter than the volume ledger would imply for a normal
  session, especially for an upper-body 3RM/5RM.
- The app should not count it as working volume.
- The app should not silently ignore it either.
- The right first model is a **time-window guard**, not a fatigue score.

## 4. Proposed model — Test Exposure Guard

### 4.1 Record

Add a small `test_exposure` record, separate from `clean_set`:

```text
test_id
performed_on
exercise_id
test_type          -- 1RM | 3RM | 5RM
attempts           -- optional
estimated_intensity -- %1RM or RIR context, optional
region_load        -- upper | lower | axial
readiness_json     -- optional snapshot
symptoms_json      -- optional
note
```

This is deliberately not a working set. It is a high-intensity event.

### 4.2 Guard windows

Initial conservative defaults, to be reviewed:

| window | guard |
|---|---|
| same day | do not schedule a second test or a normal heavy session after the test |
| 0–24 h | no maximal attempt; no heavy hinge or high-axial loading |
| 24–48 h | no second maximal lower-body/axial test; upper-body 3RM/5RM may resume if readiness and warm-up are normal |
| 48–72 h | no specific restriction unless symptoms or readiness are poor |

“No maximal attempt” is a scheduling guard, not an automatic load cut.

### 4.3 What the guard does

- shows a warning on the next prescription:
  “Recent 1RM test on 2026-10-23; avoid a second maximal exposure”;
- blocks a **test** action inside the guard window;
- suggests avoiding heavy hinge/axial work within 24h of a lower-body/axial test;
- leaves the normal readiness, injury and load rules in charge;
- never adds test sets to the volume ledger;
- never silently lowers the next load.

### 4.4 What it does not do

- it does not estimate “fatigue = X%”;
- it does not convert the test into working sets;
- it does not automatically make the next session lighter;
- it does not override readiness, symptoms or constraints.

## 5. Phases

### Phase 1 — record and display

- add the exposure record;
- show the last test and the guard window on Today/Test;
- no change to prescriptions.

### Phase 2 — deterministic guard

- block a second test within the window;
- add a prescription warning for recent lower-body/axial tests;
- add a “recent test” context flag to the session notes;
- no automatic load/RIR change.

### Phase 3 — learn from outcomes

After ~8–12 tests, compare:

- next-session e1RM/performance;
- readiness on the next day;
- soreness/symptoms;
- session completion;
- whether the guard was too strict or too loose.

Only then consider a calibrated recovery factor. Do not fit one from a handful of tests.

## 6. Why not simply count the test as volume?

It would make the volume ledger wrong:

- a 1RM test is not a working set at RIR 2–3;
- it would inflate pattern volume and under-MEV/over-MEV status;
- it would corrupt double-progression and weekly dose comparisons;
- it would treat a high-intensity, low-volume event as ordinary training volume.

The correct representation is a **separate high-intensity exposure**, not a fake working set.

## 7. Open questions

1. Is the guard 24h, 48h or 72h for lower-body 1RM?
2. Does a 3RM/5RM test need a shorter window than a 1RM?
3. Should an upper-body test affect lower-body training at all?
4. Should the guard apply to a test performed after a normal session?
5. Does the athlete’s back history require a longer axial window?
6. Can the guard be evaluated prospectively without becoming an experiment?

## 8. Recommendation

Adopt the **record + guard** approach, not a numeric fatigue model.

- Keep tests out of volume.
- Record them as high-intensity exposures.
- Use a conservative time window for the next maximal/axial exposure.
- Let readiness and symptoms handle the next normal session.
- Collect prospective outcomes before adding any automatic load adjustment.

No implementation has been done.
