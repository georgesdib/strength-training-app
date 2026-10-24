# HIGH-INTENSITY EXPOSURE — evidence, model and implementation plan

**Status:** detailed proposal only. No schema change, no API, no UI, no prescription change.
**Supersedes:** the narrower [`TEST-FATIGUE-PLAN.md`](TEST-FATIGUE-PLAN.md) proposal.
**Question:** how should the app represent a very hard exposure that is not ordinary working
volume — a test, a max attempt, a competition lift, or unplanned heavy work — without inventing
a fatigue score?

---

## 1. Why this needs its own model

The programme has two different quantities:

```text
volume / dose       how much work was done
fatigue / recovery  how much capacity is temporarily reduced
```

A strength test exposes the gap:

- it is one high-intensity exposure;
- it is not a working set;
- it is deliberately excluded from volume;
- it is currently not represented as fatigue at all.

The same issue applies outside tests:

| exposure | currently in volume? | currently in fatigue/recovery? |
|---|---:|---:|
| normal working set at RIR 1–4 | yes | partly: sets, recent stress, readiness, deload rules |
| top single / PR inside a workout | yes, as one set | only as one set; intensity not weighted |
| 1RM or 3RM test | no | no |
| powerlifting/competition lift | maybe, if logged | only through the logged set |
| unplanned max effort outside the log | no | no |
| heavy sport/manual work | no | no |

The app should not solve this by counting a test as volume. It should separate **what was
lifted** from **what it may cost to recover**.

## 2. Evidence review

### 2.1 One test is not automatically a large systemic fatigue dose

García Valverde et al. (2024) had trained participants perform a bench-press 1RM test on four
consecutive days:

- 1RM and submaximal velocity did not change significantly across days;
- perceived recovery was affected only in the stronger group from the third day, and remained
  “moderately” to “well recovered”;
- DOMS was higher on days 3–4 but remained low (< 3.3/10);
- RPE was high and stable.

This is useful counter-evidence to “a test always produces a massive fatigue debt.” It is not
proof that a test is free of cost:

- it is bench press, not a lower-body or axial 1RM;
- performance stability does not rule out local fatigue or injury risk;
- four consecutive tests are not the same as a test followed by a heavy session.

[García Valverde et al. 2024](https://doi.org/10.47197/retos.v52.101433)

### 2.2 Repeated maximal singles can produce substantial acute fatigue

Häkkinen (1993) had athletes perform **20 × 1 squat at 100% 1RM**. Maximal force fell by about
24% in men and 21% in women immediately after the session; force–time and relaxation
characteristics also changed. Recovery was gradual over the following period.

This is not one test. It shows that a cluster of maximal attempts is a meaningful
neuromuscular exposure and that “low volume” is not the same as “low fatigue.”

[Häkkinen 1993](https://doi.org/10.1055/s-2007-1021146)

### 2.3 Consecutive full-body sessions do not necessarily compound recovery failure

Marshall et al. (2021) studied two consecutive days of full-body resistance exercise in trained
men. Fatigue and pain were elevated at the start of day 2, but maximal voluntary torque and rate
of torque development had recovered by day 2; the second session did not significantly worsen
neuromuscular function.

This supports a **conservative guard**, not an assumption that every hard exposure requires
several days off.

[Marshall et al. 2021](https://doi.org/10.1007/s00421-021-04777-3)

### 2.4 Test reliability is not recovery

1RM test–retest reliability is generally good to excellent, but reliability only means the test
is consistent. A reliable test can still be a high-intensity exposure.

[Grgic et al. 2020](https://doi.org/10.1186/s40798-020-00260-z)

### 2.5 What the evidence does not establish

There is no validated conversion from:

```text
one 1RM test
```

to:

```text
a number of equivalent working sets
or a precise next-day fatigue percentage
```

The evidence supports a **time-window guard** based on exposure type and region. It does not
support a numeric fatigue multiplier, a universal 48-hour rule, or a claim that every hard
exposure impairs the next session.

## 3. Design principles

1. **Do not double count.** If a hard set is already in `clean_set`, it stays in volume; the
   exposure record is only for recovery context.
2. **Do not fake volume.** A test is not a working set.
3. **Do not fake precision.** No “fatigue = 37%” score.
4. **Guard only near-maximal/unlogged exposures.** Normal RIR 1–4 training keeps the existing
   readiness, volume, recent-stress and deload rules.
5. **Conservative and reversible.** A warning/block on another maximal exposure is easier to
   reverse than an automatic load cut.
6. **Append-only.** Corrections append; the original event remains.
7. **No LLM arithmetic.** The guard uses timestamps and enums, not model-generated numbers.
8. **Explicit scope.** The first version protects the next test/near-max exposure; it does not
   attempt to model all fatigue.

## 4. Exposure taxonomy

### 4.1 Kind

```text
test           a declared 1RM/3RM/5RM assessment
max_attempt    a top single, PR attempt, or near-max set inside a workout
competition    a meet/competition lift or event
unplanned      heavy work/sport outside the planned session
other          explicit fallback; requires a note
```

### 4.2 Intensity class

```text
near_max       RIR 0–1, or ≥ 90% 1RM, or an explicit max/PR
high           RIR 2–3 at a heavy load, or 85–90% 1RM
moderate       ordinary working sets
unknown        insufficient evidence
```

Only `near_max` is eligible for the first guard. `high` can be displayed but does not block
anything initially.

### 4.3 Region load

```text
upper
lower
axial
mixed
```

Use the existing taxonomy `spinal_cost` to refine axial cost; do not invent a new scale.

### 4.4 Link to existing data

```text
session_id   nullable; present when the exposure occurred in a logged session
set_id       nullable; present when the exposure is already a logged set
```

Rules:

- `set_id` requires `session_id`;
- a set-linked exposure must not add volume;
- a test must not have a `set_id`;
- duplicates are rejected by `(kind, performed_on, exercise_id, set_id)` or an explicit
  `supersedes_id`.

## 5. Proposed data model

Append-only table:

```sql
high_intensity_exposure (
    exposure_id      TEXT PRIMARY KEY,
    performed_on     TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN
                     ('test', 'max_attempt', 'competition', 'unplanned', 'other')),
    exercise_id      TEXT,
    session_id       TEXT REFERENCES session(session_id),
    set_id           INTEGER,
    region_load      TEXT NOT NULL CHECK (region_load IN
                     ('upper', 'lower', 'axial', 'mixed', 'unknown')),
    intensity_class  TEXT NOT NULL CHECK (intensity_class IN
                     ('near_max', 'high', 'moderate', 'unknown')),
    axial_cost       INTEGER,
    novelty          TEXT CHECK (novelty IN ('familiar', 'novel', 'unknown')),
    test_type        TEXT CHECK (test_type IN ('1RM', '3RM', '5RM')),
    note             TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime(...))
)
```

No update/delete triggers; corrections append. `test_type` is only for `kind = 'test'`.

Why not reuse `clean_set`?

- a test is not a working set;
- a set-linked exposure already exists in `clean_set`;
- volume and fatigue must be independently auditable.

## 6. Guard logic

### 6.1 Scope

The guard looks back over a configurable window (default **72 hours**) for `near_max`
exposures.

It affects:

- another **test**;
- another **near-max attempt**;
- a planned **heavy axial** session after a lower-body/axial exposure.

It does **not**:

- block ordinary training;
- reduce load or sets automatically;
- replace readiness, injury or constraint rules;
- apply to `high`/`moderate` exposures in phase 2.

### 6.2 Initial windows

These are assumptions to validate, not evidence-based constants:

| exposure | suggested guard |
|---|---|
| upper-body 1RM/3RM/5RM test | no second maximal upper-body exposure for 24 h |
| lower-body 1RM test | no second maximal lower-body/axial exposure for 48 h |
| lower-body 3RM/5RM test | 24–48 h, configurable |
| axial max attempt/competition | 48–72 h |
| unplanned near-max lower/axial | 48–72 h |
| upper-body max attempt | 24 h |

The first implementation should expose these in config, not hard-code them.

### 6.3 Output

The guard returns a small deterministic result:

```json
{
  "status": "clear" | "caution" | "blocked",
  "reason": "recent lower-body 1RM test on 2026-10-23",
  "expires_on": "2026-10-25",
  "next_maximal_on": "2026-10-25",
  "linked_exposure_ids": ["..."]
}
```

- `blocked` applies to another test/near-max in the window.
- `caution` applies to a planned heavy axial session; it is a warning, not a veto.
- The prescription records the warning; it does not silently change.

### 6.4 No double-volume rule

If `set_id` is present:

- the set remains in volume;
- the exposure is used only for the guard;
- the volume ledger must not see a second item.

If `kind = 'test'`:

- no volume;
- exposure only.

## 7. UI and CLI surface

### 7.1 Logging

- **Test page**: after recording a test, also create the exposure with `kind=test`,
  `test_type`, region and axial cost.
- **Workout review**: optional “mark as near-max exposure” for a logged set.
- **Today/Test**: show recent exposure and the guard state.
- **Manual**: a small form for competition/unplanned exposure, with a note.

### 7.2 Prescription

- show a non-blocking warning:
  “Recent lower-body 1RM test on 2026-10-23; avoid a second maximal/axial exposure before
  2026-10-25.”
- no automatic load/RIR/set change.
- if the user tries to schedule a test in the window, block it with the reason.

### 7.3 CLI

```bash
strength-coach exposure log --date ... --kind test --exercise trap_bar_deadlift \
  --test-type 1RM --region lower --axial-cost 2
strength-coach exposure status --date ...
```

No LLM involvement in the guard.

## 8. Tests and acceptance criteria

### Phase 1 — recording

- a test creates a `high_intensity_exposure` with `kind=test`, no `set_id`;
- a normal set does not create one automatically;
- a set-linked exposure does not change volume;
- duplicate exposure is rejected;
- append-only correction works;
- `/api/exposures` returns recent exposures and guard state;
- **no prescription changes**.

### Phase 2 — guard

- `near_max` upper-body exposure blocks another test for 24h;
- lower/axial exposure blocks maximal test/attempt for 48h;
- a planned heavy hinge after a lower-body exposure gets `caution`, not a veto;
- a test outside the window is allowed;
- expired windows are clear;
- a normal RIR 2 session is unaffected;
- volume ledger is byte-for-byte unchanged;
- the prescription warning cites the exposure ID.

### Phase 3 — evaluation

- after 8–12 exposures, compare next-session e1RM/performance, readiness, soreness, symptoms
  and completion;
- no automatic threshold change from the first data;
- if the guard is too strict, adjust the window with a recorded decision.

## 9. Phases and deliverables

### Phase 1 — Record and display

- schema, repository, API, CLI/Web forms;
- display only;
- acceptance tests;
- no prescription effect.

### Phase 2 — Deterministic guard

- config windows;
- status endpoint;
- test blocking;
- prescription warning;
- acceptance tests;
- no automatic load change.

### Phase 3 — Prospective evaluation

- report of exposures, next-session outcomes and guard hits;
- no auto-fit;
- decision on whether windows need adjustment.

## 10. What this plan deliberately does not do

- does not count tests as volume;
- does not convert tests to working sets;
- does not estimate a fatigue percentage;
- does not automatically reduce load or RIR;
- does not model all sport/occupational fatigue;
- does not let the LLM decide the guard.

## 11. Risks and trade-offs

| risk | mitigation |
|---|---|
| overcaution after a single easy test | only `near_max`; config windows; no automatic load cut |
| undercaution after repeated near-max work | lookback across 72h; count all near-max exposures |
| double-counted volume | `set_id` link; volume ledger ignores exposure rows |
| recording burden | auto-create for tests; optional for logged PR sets; manual only for external events |
| false precision | enums and windows, no fatigue score |
| lower-body evidence is thinner | conservative window; prospective review |
| user ignores warning | warning is visible; test blocking is deterministic; no silent changes |

## 12. Open decisions needed before implementation

1. Is the upper-body window 24h or 48h?
2. Is lower-body 1RM 48h or 72h?
3. Should a 3RM/5RM test be treated differently from a 1RM?
4. Does a prior back symptom extend the axial window?
5. Should a set-linked PR be auto-marked, or only by user action?
6. Should the guard block a test only, or also a prescribed maximal scheme?
7. What is the minimum prospective sample before changing a window?

## 13. Recommendation

Implement **Phase 1 + Phase 2** only after these decisions are settled.

The evidence supports:

- keeping tests out of volume;
- treating them as high-intensity exposures;
- a conservative time-window guard;
- no automatic load adjustment.

The evidence does **not** support:

- a numeric fatigue model;
- a universal recovery time;
- counting tests as working sets;
- letting the LLM decide recovery.

No implementation has been done.
