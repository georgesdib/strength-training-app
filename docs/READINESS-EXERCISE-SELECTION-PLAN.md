# Readiness- and symptom-driven exercise selection — implementation plan

**Status:** locked 2026-10-20. No code or configuration has been changed; this is the approved
implementation plan.
**Scope:** exercise substitution inside an already-prescribed session. Load/RIR/set adjustment
stays the first response to fatigue.

---

## 1. Question

Should readiness, recent stress and symptoms change the **exercise**, not only the load?

Example: the back is not well, or the same lift is heavily loaded — should the prescription
offer a less taxing variant?

## 2. Position

**Yes, but conservatively:**

1. **Symptom/injury** may trigger a protective substitution or removal.
2. **Recent stress + low readiness** may trigger a *suggestion* of a lower-tax, same-pattern
   variant.
3. **Readiness alone** does not change the exercise; it changes load/RIR/sets.
4. Every substitution is **explicit** and comparability-guarded.
5. No class C substitution is ever automatic.
6. No LLM chooses an exercise outside the Python-filtered candidates.

The hierarchy is:

```text
constraints / injury veto
  > symptom-specific protective substitution
  > recent-stress + readiness suggestion
  > load/RIR/set reduction
  > no change
```

---

## 3. Why not simply swap exercises on readiness

- Per-lift readiness is not a validated instrument.
- The evidence for autoregulated **load/volume** is mixed; evidence for daily **exercise
  selection** is much weaker.
- One small study found a small autoregulated-selection benefit in lean mass and bench, but no
  squat benefit; it was not a weakness/injury algorithm
  ([Rauch 2020](https://doi.org/10.1519/JSC.0000000000002272)).
- Exercise specificity matters: frequent arbitrary variation can dilute practice.
- A change of exercise changes the load basis, skill demand and comparison; it is a larger
  intervention than a load cut.
- Pain-guided modification is defensible, but it is **injury management**, not generic
  readiness selection.

This is consistent with [`WEAKNESS-INJURY-SELECTION.md`](WEAKNESS-INJURY-SELECTION.md) and
[`SELECTION-COMPARABILITY.md`](SELECTION-COMPARABILITY.md).

---

## 4. Current building blocks

Already present:

- `prescribe/selection.py` ranks configured variants by readiness, recent stress, rotation,
  preference and the shadow fatigue model.
- A/B/C comparability classes:
  - A: load-comparable;
  - B: near-comparable, confirmation required;
  - C: different lift/load basis, never automatic.
- Explicit apply only (`Apply selection`, `run --apply-selection`); load is re-solved from the
  selected lift's own history (`MOD-SELECT-001`).
- Injury signal, constraints and suitability already exclude/penalise candidates.
- Back-flare rule currently reduces erector work and main-lift RIR; it does **not** select a
  substitute.

Missing:

- an explicit **tax/risk metadata** for candidates;
- a clear symptom-specific substitution rule;
- a readiness/stress trigger that is separate from general readiness;
- reasons and audit fields for “why this variant was suggested”;
- tests for “should not substitute” cases.

---

## 5. Proposed design

### 5.1 Candidate tax metadata

Add a config map, not taxonomy code:

`config/selection-tax.v1.yaml`

```yaml
schema_version: "1.0.0"
# Ordinal, per exercise: 1 = low, 3 = high.
# Missing means unknown, not low.
exercises:
  ssb_squat: {axial: 2, systemic: 2, skill: 2, rom: 2}
  front_squat: {axial: 2, systemic: 3, skill: 3, rom: 2}
  hack_squat: {axial: 1, systemic: 2, skill: 1, rom: 2}
  trap_bar_deadlift: {axial: 2, systemic: 3, skill: 2, rom: 2}
  back_extension: {axial: 1, systemic: 1, skill: 1, rom: 1}
```

Rules:

- values are ordinal, not measured;
- unknown metadata blocks a “less taxing” claim;
- `spinal_cost` remains the safety input, not replaced by this map;
- the map is reviewed when exercises are added.

Mandatory dimensions for a lower-tax claim:

- **main lifts:** axial, systemic, skill;
- **accessories:** axial, skill;
- **ROM:** record and flag material changes, but do not require it. It is a stimulus
  dimension, not a simple fatigue score.

A candidate is lower-tax only if it is **not higher on any mandatory dimension** and is lower on
at least one.

### 5.2 Trigger tiers

#### Tier 1 — symptom/injury (strongest)

Trigger when:

- pre-session symptom flare is true, or the injury signal marks the region active; and
- the current exercise is linked to that region or has high axial/erector cost.

Behaviour:

- a hard constraint veto is **automatic** — the exercise is not prescribed;
- a symptom-linked exercise that is not a hard constraint is marked **safety-blocked** by
  default and requires an explicit override to keep it;
- a same-pattern candidate is suggested when it has:
  - no link to the active region;
  - lower axial/erector cost;
  - class A or B only;
  - an executable load from its own history;
- if no safe candidate exists, **do not invent one**; show “no safe substitution” and leave the
  decision to the athlete/clinician.

The exclusion is automatic; the **replacement is explicit**. The suggestion is prominent
because the safety case is stronger.

#### Tier 2 — recent stress + a meaningful readiness drop

Trigger when **all**:

- the current lift has high recent stress (`recent_stress.status == "high"`); and
- readiness is below **0.70** in absolute terms; and
- readiness is at least **0.10 below the rolling 28-day median**; and
- the current lift is high tax (axial/systemic/skill); and
- a same-pattern candidate is lower-tax on at least one mandatory dimension and not higher on
  the others.

Baseline rules:

- use the previous 28 days, excluding today;
- require at least **10 prior readings**;
- if the baseline is insufficient, fall back to a fixed **0.65** and mark the fallback in the
  notes;
- update slowly; never re-centre on the last few days.

The absolute guard prevents a chronically low baseline from normalising poor readiness; the
relative drop prevents reacting to a normal day that is merely below 0.70.

Behaviour:

- show a suggestion, not an automatic change;
- require confirmation (class B always; class A also explicit in this phase);
- keep the main lift slot; do not change session type.

#### Tier 3 — readiness alone

No exercise substitution.

Use existing:

- load/RIR reduction;
- readiness set reduction;
- optional deload.

This avoids turning a noisy readiness score into a different programme.

### 5.3 Candidate constraints

A candidate is excluded if:

- class C (unless explicitly shown, never applied);
- hard constraint veto;
- not `can_do` / suitability fails;
- linked to an active injury region;
- no executable load from its own history;
- not in the configured slot catalogue;
- tax metadata unknown for a “lower-tax” claim.

### 5.4 Reasons and audit

The selection result should include:

- `trigger`: `symptom` | `stress_readiness` | `none`;
- `current_tax`, `candidate_tax`;
- `reason` in plain language;
- `comparison_class` and `requires_confirmation`;
- `applied` and `confirmed_by`;
- `no_safe_substitution` when applicable.

The prescription cites `MOD-SELECT-001`; a future rule ID for the protective trigger can be
added only if the user approves a new hard rule.

---

## 6. UX and API plan

### Prescribe panel

Add a **Substitution** section:

```text
Back symptoms active.
Current: SSB squat (axial 2, skill 2)
Suggested: hack squat (axial 1, skill 1)
[Apply substitution] [Keep current]
```

Rules:

- explicit button;
- B always requires confirmation;
- C never shown as applicable;
- if no safe candidate: “no safe same-pattern substitution”;
- show that load will be re-solved from the candidate’s history.

### CLI

- `select` already previews; add the tax/trigger columns.
- `run --apply-selection --selection-confirm` remains the explicit path.
- Do not add an automatic flag for symptom substitutions.
- Add a `--no-selection` explicit opt-out if needed (already implicit default).

### API

- `GET /api/selection` returns trigger/tax/reason fields.
- `POST /api/prescribe` applies selection only with existing explicit flags.
- No new automatic mutation path.

---

## 7. Tests

1. **Symptom trigger**
   - active back flare + SSB: suggests a lower-axial same-pattern candidate or reports none;
   - no class C applied;
   - no automatic application.

2. **Stress + readiness trigger**
   - high recent stress + low readiness: suggestion appears;
   - normal stress + low readiness: no exercise suggestion; load/set reduction only;
   - high stress + normal readiness: no suggestion.

3. **Comparability**
   - A applies only when explicit;
   - B requires confirmation;
   - C never applies automatically and is hidden by default.

4. **Load**
   - suggested lift is rebuilt through `build_item`, not copied;
   - unknown load is reported, not guessed.

5. **No candidate**
   - no same-pattern lower-tax candidate: no invented substitution;
   - message says so.

6. **Audit**
   - trigger, tax, class, reason and confirmation are visible.

7. **Safety**
   - constraints/injury veto wins over the selector;
   - no change to main-lift volume beyond existing readiness rules.

---

## 8. Rollout

### Phase 0 — Config and shadow

- add tax config;
- compute trigger/tax/reason in selection;
- no UI apply;
- tests prove “no suggestion” cases.

### Phase 1 — Symptom-specific suggestions

- show protective suggestions in Prescribe/select;
- explicit apply only;
- log trigger and outcome.

### Phase 2 — Stress/readiness suggestions

- add the dual-trigger suggestion;
- keep readiness-alone as no substitution;
- no automatic application.

### Phase 3 — Review

After 12–16 weeks, review:

- substitution uptake;
- back symptoms/flares;
- session completion;
- main-lift e1RM;
- whether suggestions were accepted or ignored.

No automatic promotion to a rule.

---

## 9. Non-goals

- No free exercise generation.
- No LLM-only selection.
- No class C automatic substitution.
- No injury prediction.
- No “target the weak muscle” selection.
- No readiness-only exercise swap.
- No change to the programme template or session type.
- No substitution without re-solving the load.

---

## 10. Locked decisions

| decision | locked choice |
|---|---|
| Tier 2 readiness | `< 0.70` absolute **and** at least `0.10` below the 28-day median |
| Baseline | previous 28 days, excluding today, minimum 10 readings; fallback to `0.65` |
| High stress | existing `recent_stress.status == "high"` for the current lift |
| Symptom | automatic exclusion of unsafe/vetoed exercise; replacement explicit |
| Mandatory tax dimensions | main: axial + systemic + skill; accessories: axial + skill; ROM optional |
| Rule ID | no new rule; applied substitutions cite `MOD-SELECT-001`; exclusions cite existing injury/constraint rules; trigger recorded in notes |

These values are policy assumptions, not validated cut-points. Changes require updating this
document, the config, tests and the decision log.

No implementation until the user starts the implementation phase.
