# OPEN QUESTIONS — ranked by how much they change the design

These are genuine ambiguities in the programme brief, the data, or both. Each states the
default this project will implement if nobody answers, so a missing answer is survivable and
produces an `unknown` verdict rather than a silent guess.

> Quantitative evidence for each question is kept out of this public repository. The
> questions themselves are methodology questions and apply to any athlete using the system.

---

## Q1. Sessions have no timestamps — how should training days be assigned?

The date column is calendar-date only. So "same date + time gap" is impossible, two sessions
on one day are indistinguishable, and a squat-plus-bench day is ambiguous between the squat
day and the bench-plus-squat day unless erector or power work is present.

**Blocks:** session/day identity, scheduling rules, duration scoring.
**Default:** one session per date; day inferred from the main lift present, with the
ambiguous pair separated by erector/power content; ambiguous -> `unknown`, and no
day-specific rule is scored when the day is unknown.

---

## Q2. What is a "high-fatigue spinal exposure"?

The brief caps "more than ~3 per week" without defining an exposure. Measured on **distinct
exercise types** the cap almost never fires, which makes it decorative; measured **per set**
it fires almost every week, which makes it meaningless.

The likely intent is distinct high-fatigue exercise types per week — but then three heavy
rack-pull sets count the same as three light back-extension sets, which is probably not the
intent either.

**Blocks:** the spinal-cap rule and the redundancy rubric line.
**Default:** distinct high-fatigue exercise types per ISO week, cap 3, with an ordinal
weighted cost reported alongside as context (ASSUMPTION-02).

---

## Q3. The erector ramp needs an anchor — when is week 1?

The 8-12 week dose ramp (bodyweight -> add load -> add a set -> consolidate) requires knowing
which week of the block today is. Nothing in the source export marks a block boundary, and
the historical erector rows deliberately do **not** count toward the dose.

**Blocks:** the erector ramp rule, day A/C prescription, the "weekly erector dose vs plan"
rubric line.
**Default:** block starts on the first Monday after approval; until then, bodyweight only,
phase labelled `unanchored`.

---

## Q4. There is no symptom field. How should back symptoms be recorded?

The most safety-relevant rules — "if back symptoms rise and do not settle in 24-48 h",
"progress only if no symptom flare" — depend on data that does not exist in either export.
The form-quality column is the only candidate and its direction is unknown, so it is not used
as a proxy.

**Blocks:** the back-flare modifier, the erector stability gate, the "symptoms reported"
rubric line.
**Default:** a manual per-session input (`--back 0-3`) into a `symptom_log` table; rules
return `unknown` until it exists.

---

## Q5. Session duration is unmeasurable. Proxy or drop?

The rubric wants "session duration vs 60-80 min cap". There are no timestamps. The options
are a set-count proxy or dropping the metric — and a proxy presented as minutes would be a
fabricated score.

**Default:** drop the line; report sets-per-session as context with `measurable: false`.

---

## Q6. Readiness conflicts, and how new metrics enter

Two sub-questions:
1. **Merge** — multiple readiness rows per date exist, and most are *conflicting* rather than
   identical. Proposed rule: most-complete row, tie-break on latest. That assumes
   completeness equals authority.
2. **New metrics** — a composite readiness score, HRV, RHR and left/right grip strength are
   planned. Each needs a declared scale, direction (does higher mean better?) and
   aggregation before it can enter the composite.

**Blocks:** the readiness composite. The merge half no longer blocks anything.
**Default:** most-complete-row merge with conflicts logged; new metrics enter as
`metric_definition` rows with explicit `scale_min`, `scale_max`, `higher_is_better` and
`aggregation`, and stay dormant until populated.
**Status:** the merge default is **implemented** (`ingest/readiness.py`, `DEC-READINESS-01`);
every date carries its `merge_note`. The composite is still unbuilt and stays `null` until
part 2 is answered. `ASSUMPTION-04`: completeness is treated as authority.

---

## Q7. Does "main lifts at RIR 2-3" forbid sets *easier* than the window?

The constitution states a window, but `PRG-RIR-001`'s `on_fail` code is `RIR_FLOOR`, and the
danger it names is "no RIR 0-1 sets, no max singles". A set at RIR 4-5 is easier than
prescribed, not more dangerous, so treating it as a veto would make the rule fire on almost
every session and bury the real violations.

**Blocks:** nothing — the rule runs today with the default below.
**Default:** the floor is a veto (RIR below the window, plus max singles at >= 90% of a
multi-rep e1RM); a set *above* the window is counted and reported in the verdict details but
does not fail the rule. Making easy sets violations is then a config change
(`on_fail.action`) plus a predicate branch, not a rewrite.

---

## Q8. What counts as one "high-fatigue spinal exposure"?

ASSUMPTION-02 fixes the *weighting* (ordinal `spinal_cost`) but not the *unit*:

* per **set** — one 12-set trap-bar session is twelve exposures, so the cap fires every week;
* per **exercise type per week** — the cap almost never fires, which makes it decorative;
* per **exercise per session** — two hinge sessions in a week cost 2+2 = 4 against a cap of 3.

**Blocks:** how strict `PRG-SPINE-001` is. It does not block the build.
**Default:** one exposure = one exercise in one session, weighted by `spinal_cost`
(`rules/registry.py` `weekly_spinal_cap`). Sets do not multiply an exposure.

---

## Closed

- ~~What do the extreme `RIR` values mean?~~ **Closed** — `RIR 6` marks a **warm-up set**
  (`DEC-RIR-01`), so it is excluded from effort, e1RM and working volume while staying
  visible. `RIR 0-1` remain in scope but flagged (`DQ-RIR-02`).
- ~~Bodyweight movements: total mass or added load?~~ **Closed** — progression acts on
  **added load** (`DEC-LOAD-02`); total mass is used only for an e1RM.
- ~~Is there a trap-bar deadlift in the data?~~ **Closed** — the logging app records it under
  a different name (`DEC-TRAPBAR-01`).
- ~~Which exercise is "back extension"?~~ **Closed** — synonymous with the older
  hyperextension name, **including historical rows**: they keep their own identity but
  count as back-extension history (`DEC-BACKEXT-02`, amending `DEC-BACKEXT-01`).

## Decisions taken as defaults unless told otherwise

- Training rows are **never** deduplicated — repeated identical rows are real sets.
- ACWR is advisory only and may never veto a prescription (the "sweet spot" reading is
  contested).
- Within-set velocity loss is reported as *not measurable*, with a labelled set-to-set decay
  proxy instead.
- Exercise-rotation scoring is split by session provenance, because in a real export the
  logging app deliberately rotates variations while self-directed sessions are stable.
