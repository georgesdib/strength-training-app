# OPEN QUESTIONS — ranked by how much they change the design

These are genuine ambiguities in the programme brief, the data, or both. Each states the
default this project will implement if nobody answers, so a missing answer is survivable and
produces an `unknown` verdict rather than a silent guess.

> Quantitative evidence for each question is kept out of this public repository. The
> questions themselves are methodology questions and apply to any athlete using the system.

---

## Q1. What do the extreme `RIR` values mean?  <- highest impact

The RIR column does not behave like a real 0-6 scale. In a representative export, one
mid-scale value is **never used at all**, a high value is used far more often than any other
and clusters on the main lifts, and `RIR 0` clusters on isolation accessories — including
every row with a null date.

Two readings, opposite consequences:

- **All real** — the athlete genuinely reports easy ratings on heavy work and goes to
  failure on accessories. The hard "no RIR 0-1 on main lifts" rule then has many genuine
  violations to find.
- **Partly a default bucket** — the modal value means "not recorded" and some zeros are
  unset. Effort is then systematically *understated*, every RIR-adjusted e1RM is biased low,
  and any prescription built on RIR is systematically too light.

**Blocks:** the effort rule, RIR-adjusted e1RM, the fatigue modifier's "first-set RIR drop"
test, and the critique's main rubric line.
**Default:** modal high value -> `rir_source = assumed_default` (excluded from effort
statistics, still reported); `0/1` treated as logged but flagged suspect.

---

## Q2. Bodyweight movements: total mass or added load?

The weight column mixes three meanings (see DQ-BW-01). The unresolved part is what to *do*:

- For a pull-up logged at total body mass, is progression tracked on **total mass** or on
  **added load** (0 kg, then +2.5 kg)?
- Should e1RM for bodyweight movements use bodyweight + added, or added only?

This changes the double-progression increment for every bodyweight prescription.

**Default:** total mass for e1RM; added load for progression increments.

---

## Q3. Sessions have no timestamps — how should training days be assigned?

The date column is calendar-date only. So "same date + time gap" is impossible, two sessions
on one day are indistinguishable, and a squat-plus-bench day is ambiguous between the squat
day and the bench-plus-squat day unless erector or power work is present.

**Blocks:** session/day identity, scheduling rules, duration scoring.
**Default:** one session per date; day inferred from the main lift present, with the
ambiguous pair separated by erector/power content; ambiguous -> `unknown`, and no
day-specific rule is scored when the day is unknown.

---

## Q4. What is a "high-fatigue spinal exposure"?

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

## Q5. The erector ramp needs an anchor — when is week 1?

The 8-12 week dose ramp (bodyweight -> add load -> add a set -> consolidate) requires knowing
which week of the block today is. Nothing in the source export marks a block boundary, and
the historical erector rows deliberately do **not** count toward the dose.

**Blocks:** the erector ramp rule, day A/C prescription, the "weekly erector dose vs plan"
rubric line.
**Default:** block starts on the first Monday after approval; until then, bodyweight only,
phase labelled `unanchored`.

---

## Q6. There is no symptom field. How should back symptoms be recorded?

The most safety-relevant rules — "if back symptoms rise and do not settle in 24-48 h",
"progress only if no symptom flare" — depend on data that does not exist in either export.
The form-quality column is the only candidate and its direction is unknown, so it is not used
as a proxy.

**Blocks:** the back-flare modifier, the erector stability gate, the "symptoms reported"
rubric line.
**Default:** a manual per-session input (`--back 0-3`) into a `symptom_log` table; rules
return `unknown` until it exists.

---

## Q7. Session duration is unmeasurable. Proxy or drop?

The rubric wants "session duration vs 60-80 min cap". There are no timestamps. The options
are a set-count proxy or dropping the metric — and a proxy presented as minutes would be a
fabricated score.

**Default:** drop the line; report sets-per-session as context with `measurable: false`.

---

## Q8. Readiness conflicts, and how new metrics enter

Two sub-questions:
1. **Merge** — multiple readiness rows per date exist, and most are *conflicting* rather than
   identical. Proposed rule: most-complete row, tie-break on latest. That assumes
   completeness equals authority.
2. **New metrics** — a composite readiness score, HRV, RHR and left/right grip strength are
   planned. Each needs a declared scale, direction (does higher mean better?) and
   aggregation before it can enter the composite.

**Blocks:** the readiness composite and every fatigue modifier input.
**Default:** most-complete-row merge with conflicts logged; new metrics enter as
`metric_definition` rows with explicit `scale_min`, `scale_max`, `higher_is_better` and
`aggregation`, and stay dormant until populated.

---

## Closed

- ~~Is there a trap-bar deadlift in the data?~~ **Closed** — the logging app records it under
  a different name (`DEC-TRAPBAR-01`).
- ~~Which exercise is "back extension"?~~ **Closed** — synonymous with the older
  hyperextension name *going forward only*; historical rows keep their own identity
  (`DEC-BACKEXT-01`).

## Decisions taken as defaults unless told otherwise

- Training rows are **never** deduplicated — repeated identical rows are real sets.
- ACWR is advisory only and may never veto a prescription (the "sweet spot" reading is
  contested).
- Within-set velocity loss is reported as *not measurable*, with a labelled set-to-set decay
  proxy instead.
- Exercise-rotation scoring is split by session provenance, because in a real export the
  logging app deliberately rotates variations while self-directed sessions are stable.
