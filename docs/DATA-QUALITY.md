# DATA-QUALITY DECISIONS

The decision ledger. Every `DQ-*` id is referenced from code and rules, so a decision can
be changed in one place.

Status values: `CONFIRMED` (settled), `NEEDS CONFIRMATION` (a rule is proposed and must be
approved by the athlete), `ASSUMPTION` (no source can settle it; recorded so it is visible).

> **Note on evidence.** This repository is public, so the measured profile of a real
> training export is not included. Every claim below was derived from a multi-year Sheiko
> Gold export and is stated in structural terms — the *shape* of the problem, not anyone's
> numbers. Reproduce your own with `python tools/profile_data.py`.

---

## 1. Sentinels — the core trap

`0` means a different thing in almost every column. **There is no global rule.** Applying
one is the single most likely way to corrupt every downstream metric.

### DQ-SENT-01 — telemetry zeros  `CONFIRMED`
`Avg_velocity`, `Avg_power`, `Avg_rom` and `TUT` are all zero on exactly the same rows, and
`velocity == 0` never coexists with `TUT > 0`. So the whole telemetry block is present or
absent together, and one flag `telemetry_present = Avg_velocity > 0` describes it.

**Action:** coerce to null. Exclude from VBT, ROM and TUT features. Never treat as a slow
rep — that would make an unmeasured set look like a fatigued one.

### DQ-SENT-02 — readiness zeros  `CONFIRMED`
`HRV`, `RHR`, `Weight`, `Fat_Percent` and the per-lift `*_Readiness` fields use 0 for
missing. This is provable rather than assumed: a bodyweight of 0 kg, an HRV of 0 ms, a
resting heart rate of 0 bpm and 0% body fat are all physiologically impossible, and the
recorded non-zero bodyweight range is a narrow band consistent with one person.

**Action:** coerce to null. The 1–5 wellness fields have no zero bucket, so a 0 there is a
hard data error, not a sentinel.

### DQ-RIR-01 — `RIR 6` marks a warm-up  `CONFIRMED`
The athlete confirmed that `RIR = 6` labels a **warm-up set**. That is a much stronger
statement than "unknown", and it changes what the value may influence:

- a warm-up is not evidence of effort, so it must not enter compliance scoring;
- it must not contribute an RIR adjustment to an e1RM (extrapolating a ramp-up set to a
  maximum is meaningless);
- it must not count toward working-set volume, spinal dose or progression decisions;
- but it **must remain visible**: the warm-up share of a session is itself a coaching signal
  (how much of the logged work was ramp-up).

In the reference export this relabels roughly a quarter of all rows, so the practical working
volume is materially smaller than the raw row count suggests. That is exactly the kind of
error that is invisible in aggregate and biases every prescription, which is why it was the
highest-ranked open question.

**Action:** `domain.rir.classify` maps 6 to class `warmup`, sets `is_working_set = False`, and
records `rir_source = logged_warmup`. The value itself is preserved.

### DQ-RIR-02 — `RIR 0–1` remain suspect but in scope  `NEEDS CONFIRMATION`
These are genuine effort ratings (unlike the warm-up marker), so they are **not** excluded —
the hard "no RIR 0–1 on main lifts" rule must be able to see them. They are flagged
`SUSPECT_RIR` and reported separately from clean effort.

What remains open is whether an RIR 0 on an isolation accessory is a real failure set (which
the constitution does not forbid) or an unset field. The default treats it as real.

### DQ-RIR-03 — `RIR 5` is treated as a genuine easy working set  `ASSUMPTION`
Nothing indicates it is a sentinel, and it is used far less than the warm-up marker. This is
the least consequential assumption in this file.

## 2. Bodyweight load convention  `NEEDS CONFIRMATION`

One weight column carries **three different meanings**, sometimes for the same exercise:

| meaning | what it looks like |
|---|---|
| unweighted bodyweight movement | `0` |
| bodyweight captured by the device | a value within a few percent of the athlete's mass |
| added external load | a small number, well below body mass |

Disambiguation key: the readiness file records bodyweight, so a logged value near body mass
is total mass, while a value far below it is a plate.

### DQ-BW-01 — proposed rule

Resolve `load_basis` per row, in this order:

1. `exercise.time_based` (plank, carry) → tonnage undefined; score on seconds.
2. `Weight_Used == 0` → `bodyweight_total`, `external_load_kg = 0`.
3. `exercise.bodyweight_type` **and** `0.5 × BW < weight ≤ 1.15 × BW` → `bodyweight_total`.
4. `exercise.bodyweight_type` **and** `0 < weight ≤ 0.5 × BW` → `added`.
5. otherwise → `external`.

`BW` is bodyweight on the nearest date within a configurable tolerance (±7 days by
default), because weighing is sporadic but body mass is stable across a week. If no
bodyweight is on record, `load_basis = unknown` and the row is excluded from e1RM but still
counted for sets, reps and rotation.

Why those thresholds: real values cluster either far below body mass (added plates) or
within a few percent of it (captured total), so the cut sits in empty space and is not
sensitive. They are config, not code.

**Open sub-question:** for a bodyweight movement logged at total mass, is progression
tracked on **total mass** or on **added load**? This changes the double-progression
increment for every pull-up prescription. Proposed default: total mass for e1RM, added load
for increments.

### DQ-LOAD-02 — progression acts on ADDED load  `CONFIRMED`
The athlete chose **added load** as the progression axis for bodyweight movements. So a
pull-up is programmed as "bodyweight + 2.5 kg", never as a total mass, and the
double-progression increment applies to the plate.

This is why `ResolvedLoad` carries both `total_load_kg` and `external_load_kg`:
`progression_load()` returns the added load for a bodyweight movement — with a
device-captured total-mass reading resolving to **0 kg added**, because the bar is the
athlete — while total mass remains the correct input for an e1RM.

### DQ-BW-02 — `0` vs "not recorded"  `ASSUMPTION`
`Weight_Used = 0` on a bodyweight exercise is read as "unweighted", not "unknown". The
alternative discards a large number of real repetitions.

## 3. Units and types

### DQ-UNIT-01 — mixed-case units  `CONFIRMED`
Only `kg` and `KG` appear. No unit-less rows were observed, contrary to the brief, but the
reader normalises case-insensitively and defaults to kg with a `LOAD_AMBIGUOUS` flag rather
than guessing if a blank ever appears.

### DQ-REPS-01 — `Reps_Done` is not always repetitions  `CONFIRMED`
Plank and carry families store **seconds**: values in the tens-to-hundreds range are
isometric hold durations, not repetitions. There are also genuine typos (a four-digit rep
count on a push-up variant).

**Action:** `reps_unit` follows the taxonomy (`rep_semantics`); tonnage is null for
`seconds`; a typo threshold flags implausible rep counts. Flagged rows are retained and
excluded from features — never deleted.

## 4. Duplicates

### DQ-DUP-01 — training rows are **not** duplicates  `CONFIRMED`
This contradicts a natural assumption, so it matters.

If you group fully identical rows, the group sizes trace a textbook set structure: mostly
pairs, then threes, then fours and fives, with a thin tail. That is what a session with
straight sets looks like — e.g. a squat at the same load and RIR three times, then two
bench doubles at one load and two singles at another.

**Action: never deduplicate the cleaned set table.** Blanket deduplication deletes real
volume. A row is only collapsed when it is identical **and** carries identical non-zero
telemetry, which is effectively impossible for genuinely distinct sets.

### DQ-RD-01 — readiness conflicts  `NEEDS CONFIRMATION`
Multiple readiness rows per date occur. Only a minority are exact duplicates; the rest are
**mutually contradictory** measurements for the same day (different HRV, different
hydration). This is not duplication, it is multiple or edited entries.

Proposed merge, in order:
1. drop rows where every field is a sentinel;
2. prefer the row with the most non-null fields;
3. tie-break on latest source row;
4. record the discarded rows in `merge_note`.

Step 2 assumes "more complete = more authoritative", which is why it needs confirmation.

## 5. Sessions

### DQ-SESSION-01 — no timestamps exist  `CONFIRMED`
The date column is calendar-date only, with a null placeholder. There is no time column, so
"same date + **time gap** + exercise sequence" cannot be implemented. The logging app's own
documentation says a generated workout is valid for a bounded window, i.e. one workout is
one session, so date is the best available boundary.

**Action:** one session per calendar date; a `POSSIBLE_DOUBLE_SESSION` flag when the set
count is implausible for one session or when two main-lift families appear that no day
template contains; `duration_min` is null with `duration_basis = unavailable`.

### DQ-SESSION-02 — day classification is retrofitted  `NEEDS CONFIRMATION`
Day A/B/C must be inferred from which main lift is present. A and C are both squat + bench,
so they are distinguishable only by the presence of erector or power work. Ambiguous
sessions get `unknown`, and no day-specific rule is scored when the day is unknown.

### DQ-NULLDATE-01 — rows with a null date  `CONFIRMED`
A contiguous block of rows with a null date forms a plausible session fragment, all carrying
the same suspicious RIR value and no telemetry — most likely an orphaned early import.

**Action:** quarantine, exclude from sessions, report the count in every run. Do not delete:
quarantined rows otherwise leak into violation counts and fabricate failures.

### DQ-IMPORT-01 — overlap across exports is not deduplication

A cumulative re-export contains rows already stored. The importer matches each new row to
a stored payload and reuses the existing `raw_id`; that is **overlap detection across files**,
not content deduplication. Two identical rows *inside the same new file* still create two raw
rows and two clean sets, preserving DQ-DUP-01. A correction with a changed load/reps/date is a
new row, not a silent merge.

## 6. Flags that must not be resolved silently

| issue | handling |
|---|---|
| implausible rep counts (e.g. four digits) | `REPS_TYPO` flag, excluded from features, reported |
| implausible load × rep combinations | `REPS_TYPO` flag |
| dates with an implausible number of sets | `POSSIBLE_DOUBLE_SESSION` |
| `Form` 1–4 with unknown direction | stored, **not** used in scoring until the scale is confirmed |
| `ExertionLoad` semantics unclear | unused; not trusted as a fatigue proxy |

## 7. The general principle

Every row either becomes a feature, gets an explicit flag, or is quarantined with a reason.
Nothing is dropped silently, and nothing is "cleaned up" by inference. A missing value stays
missing and propagates as `unknown` — because a plausible-looking substitute is worse than a
visible gap in a system whose whole purpose is to justify each number it prints.
