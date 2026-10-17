# RULES DOCUMENT FORMAT

The constitution is the source of truth. It is stored as **versioned YAML** so that every
claim the system makes can cite a stable, immutable rule ID.

## 1. Why a document rather than prose in a prompt

Three requirements force this:

1. **Citable.** The output must say "load reduced because `PRG-FAT-001` fired", and that
   ID must still mean the same thing in six months.
2. **Machine-checkable.** The policy engine must be able to *veto* an LLM suggestion. A
   rule that only exists as prompt text cannot veto anything.
3. **Versioned.** When the constitution changes, old prescriptions must still explain
   themselves against the version that was in force.

So each rule has a human `statement`, machine `params`, and a `check` that names a
registered Python predicate. The rule text is never parsed as an expression — there is no
little DSL to get wrong. YAML declares *which* predicate and *with what arguments*; Python
implements the predicate once and tests it.

## 2. Anatomy of a rule

```yaml
- id: PRG-RIR-001                 # stable forever; never reused, never renumbered
  title: short human label
  severity: veto | downgrade | warn | advisory
  scope:                          # what the rule applies to
    exercises: [ssb_squat, ...]   # canonical ids
    sessions: [A, B, C]
  statement: >                    # the constitution, in words
    ...
  params:                         # every number the predicate needs
    main_lift_rir: {min: 2, max: 3}
  inputs: [set.rir, exercise.primary_compound]   # what must exist to evaluate
  check:
    fn: primary_compound_rir_window   # registry key
    args: {allow_rir_zero_when_unset: true}
  citations: ["constitution §2 effort bullet"]
  depends_on_data_decisions: [DQ-SENT-03]
  on_fail: {action: veto, code: RIR_FLOOR}
  notes: why this is worded the way it is
```

### Severity semantics

| severity | policy engine effect |
|---|---|
| `veto` | the proposed prescription is rejected; deterministic fallback used |
| `downgrade` | the offending item is reduced/modified; prescription survives |
| `warn` | recorded, surfaced in the report, no change |
| `advisory` | informational only (e.g. ACWR, which is contested) |

### The `inputs` field and the `unknown` verdict

A rule whose `inputs` are absent returns **`unknown`**, never `pass`. This is how the
system stays honest about things it cannot measure: symptoms (no field exists), session
duration (no timestamps), within-set velocity loss (no per-rep data). An `unknown`
verdict is reported as "not assessable — <missing input>" and never scored as compliant.

### Modifiers are not rules

Fatigue handling is a **modifier**, not a pass/fail rule: it transforms a prescription
rather than judging one. Modifiers live in the same document under `modifiers:` and are
applied in order by the prescription engine before the policy engine evaluates the result.

## 3. Citation scheme

Every rationale sentence carries one or both of:

- a **rule citation**: `PRG-RIR-001` — resolved through `rule_document.version`;
- a **data citation**: a stable fact id such as `set:<session>/<index>` or
  `feature:rolling_readiness/<date>`.

The critique and prescription store these as `rationale_refs`, so a citation cannot be
hallucinated: the validator rejects any reference that does not resolve.

## 4. Five encoded rules

These are the constitution's own words, encoded. The full set lives in
`config/rules/programme.v1.yaml`. Nothing here is invented — where the constitution is
ambiguous, the ambiguity is recorded in `notes` and raised in `docs/OPEN-QUESTIONS.md`.

### PRG-RIR-001 — Effort window on primary compounds  (severity: `veto`)

> "Main lifts at RIR 2–3 (trap-bar RIR 3–4). No RIR 0–1 sets, no max singles, no 1RM
> testing inside a block. This is a hard rule, not a preference."

```yaml
scope: {exercises: "$primary_compounds"}
params:
  default_rir: {min: 2, max: 3}
  per_exercise: {trap_bar_deadlift: {min: 3, max: 4}}
  forbid_max_single: true          # reps == 1 at >= 90% e1RM
check: {fn: primary_compound_rir_window}
on_fail: {action: veto, code: RIR_FLOOR}
notes: >
  Scoped to `primary_compound`, not `main_lift`, because the most-performed squat in
  an export may not be one of the constitution's named lifts. Scoping to main_lift
  would leave most heavy squatting unregulated. Depends on DQ-SENT-03: if the modal
  RIR value is a default bucket it must not be read as an easy set.
```

### PRG-DP-001 — Double progression  (severity: `downgrade`)

> "Hold load until top of rep range on all sets at RIR ≥2, then add the smallest
> increment."

```yaml
scope: {exercises: "$accessories_and_back_extension"}
params:
  top_of_range_all_sets: true
  min_rir_at_top: 2
  increment_kg: {default: 2.5, per_exercise: {Lateral Raise: 2.5, Ab Wheel: 2.5}}
check: {fn: double_progression_decision}
on_fail: {action: downgrade, code: HOLD_LOAD}
notes: >
  "Smallest increment" is per-exercise config: this log contains 0.5, 1.0 and 2.5 kg
  steps, so a global 2.5 kg constant would be wrong for small lifts. Also requires
  sets to be comparable: a set interrupted by a typo or a missing RIR does not count
  toward "all sets".
```

### PRG-SCHED-001 — Erector work is exclusive to Days A and C  (severity: `veto`)

> "Back extensions (Days A, C only — never on the hinge day)… do not stack a hinge plus
> direct erector work in the same session."

```yaml
scope: {sessions: [A, B, C]}
params:
  allowed_days: [A, C]
  forbid_with_patterns: [hinge]
  direct_erector_flag: true
check: {fn: direct_erector_scheduling}
on_fail: {action: veto, code: ERECTOR_STACKING}
notes: >
  Implemented as a property check (`direct_erector` and `pattern == hinge`) rather
  than a name list, so a new erector exercise is covered automatically. This is what
  `substitutable_for_back_extension: false` protects: an RDL can never be counted as
  the erector dose, so it can never satisfy this rule by proxy.
```

### PRG-EREC-001 — Erector dose ramp with a stability gate  (severity: `warn`)

> "Dose-ramped over 8–12 weeks (weeks 1–3 bodyweight, 4–6 add 5–10 kg, 7–9 add a set,
> 10–12 consolidate). Progress only if two consecutive sessions are stable with no
> symptom flare."

```yaml
scope: {exercises: [back_extension]}
params:
  weeks: [{weeks: [1,3], dose: bodyweight, added_kg: 0},
          {weeks: [4,6], dose: load, added_kg: [5,10]},
          {weeks: [7,9], dose: add_set, added_kg: [5,10]},
          {weeks: [10,12], dose: consolidate}]
  stability_sessions: 2
  symptom_gate: required
check: {fn: erector_dose_ramp}
inputs: [block.week_index, session.sets, symptom.flare]
on_fail: {action: warn, code: ERECTOR_RAMP_HOLD}
notes: >
  Two blockers, both surfaced rather than guessed: (1) there is no symptom field in
  either CSV, so `inputs: symptom.flare` is unavailable and the rule returns
  `unknown` rather than assuming no flare; (2) DEC-BACKEXT-01 means historical
  `Hyperextensions` rows do NOT count toward this dose, so there is effectively no
  history to ramp from and week 1 needs an explicit anchor date from the user.
```

### PRG-SPINE-001 — Weekly high-fatigue spinal exposure cap  (severity: `veto`)

> "Flag any week containing more than ~3 high-fatigue spinal-loading exposures (e.g.
> trap-bar + rack pull + RDL + good morning + hyperextension)."

```yaml
scope: {unit: iso_week}
params:
  cap: 3
  counting: weighted            # sum of spinal_cost, not a raw count
  costs: {back_extension: 1, trap_bar_deadlift: 2, rdl: 2, jefferson_curl: 2,
          rack_pull: 3, good_morning: 3, conventional_deadlift: 3}
check: {fn: weekly_spinal_cap}
on_fail: {action: veto, code: SPINAL_CAP}
notes: >
  Ambiguous in the constitution: "exposures" could mean distinct exercises, sessions,
  or sets. Measured on distinct exercises the cap almost never fires, which would make
  it decorative; measured per set it fires every week. A weighted sum is the middle
  reading and is explicitly ASSUMPTION-02 — the cost values are an ordinal design
  choice, not a measurement.
```

## 5. What is deliberately **not** a rule

- `Trap-bar RIR 3–4` — encoded as a per-exercise override inside `PRG-RIR-001` rather
  than a second rule, so there is exactly one place that answers "what RIR is allowed?".
- Power work (3–5 reps, full recovery, stop on decline) — v1, needs rep-level power data
  that the log does not contain (Q4).
- Session time cap 60–80 min — cannot be measured (no timestamps). Encoded as an
  `advisory` placeholder that always returns `unknown` today, so the gap is visible
  instead of forgotten.
