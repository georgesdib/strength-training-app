# Readiness- and symptom-driven exercise selection — implementation plan

**Status:** closed 2026-10-20. Tax metadata, candidate catalogue, review panel and explicit
suggestions are implemented. Automatic symptom withholding is deliberately deferred to the
follow-up review.
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
- a symptom-linked exercise that is not a hard constraint is **safety-blocked** in the
  suggestion and flagged in the UI; automatic withholding is **not enabled** in this slice;
- a same-pattern candidate is suggested when it has:
  - no link to the active region;
  - lower axial/erector cost;
  - class A or B only;
  - an executable load from its own history;
- if no safe candidate exists, **do not invent one**; show “no safe substitution” and leave the
  decision to the athlete/clinician.

The hard-constraint exclusion is automatic; the symptom **suggestion and replacement remain
explicit**. Automatic symptom withholding is the next gate, not a current behaviour.

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
| Symptom | hard veto automatic; symptom-linked exercise safety-blocked, suggested replacement explicit; automatic withholding deferred |
| Mandatory tax dimensions | main: axial + systemic + skill; accessories: axial + skill; ROM optional |
| Rule ID | no new rule; applied substitutions cite `MOD-SELECT-001`; exclusions cite existing injury/constraint rules; trigger recorded in notes |

These values are policy assumptions, not validated cut-points. Changes require updating this
document, the config, tests and the decision log.

The review panel (§12), tax metadata, candidate catalogue and explicit substitution
suggestions are implemented. Automatic symptom withholding remains deferred to the follow-up
review; see §14.

---

## 11. App-wide readiness threshold policy

The exercise-substitution plan is one consumer of a broader rule:

> **Personal baseline for context and high-cost, reversible choices; fixed absolute thresholds
> for safety and load.**

### 11.1 What stays absolute

| threshold | treatment |
|---|---|
| sleep/energy ≤ 2 | fixed safety floor |
| load factor bands (`0.80 / 0.60 / 0.40`) | fixed intervention dose |
| set-reduction score `< 0.50` | fixed volume valve |
| injury/symptom rules | fixed safety rules |
| deload triggers | separate policy; never readiness-relative |

A rolling baseline must never normalise a poor absolute state.

### 11.2 What may use a rolling baseline

| decision | use |
|---|---|
| HRV/RHR components | existing 28-day baseline, minimum 7 readings |
| readiness warnings | absolute score **and** deviation from 28-day median |
| exercise substitution Tier 2 | absolute `< 0.70` **and** at least `0.10` below the median |
| “falling readiness” display | relative trend only |
| per-lift readiness | show own-history context; keep action thresholds fixed |

Per-lift readiness is already relative (global base, e1RM trend, RIR, VBT). Do not add a second
rolling baseline to its action thresholds; that would make it difficult to interpret.

### 11.3 Periodic review, not daily tuning

Thresholds are reviewed at a pre-specified cadence:

- every **12–16 weeks**, or
- after roughly **40–50 new sessions**, whichever comes first;
- plus after a material programme change or a new back pattern.

The review may:

1. re-run readiness–performance and readiness–sRPE associations;
2. compare the current absolute threshold with the absolute + relative gate;
3. use held-out sessions;
4. change a threshold only if it beats the current one out of sample and does not increase
   symptoms or missed sessions;
5. otherwise keep the fixed value and record why.

The review must not:

- refit weekly;
- change thresholds automatically;
- use the same data to choose and validate a cutoff;
- turn a weak association into a rule.

### 11.4 Baseline rules

- window: previous **28 days**, excluding today;
- minimum: **10** readiness readings;
- insufficient baseline → use the fixed fallback and mark it;
- slow update; no re-centring on the last few days.

---

## 12. Website: periodic review reminders

The app should not rely on the athlete remembering reviews. Add a small **Periodic reviews**
section to Today (or a “Maintenance” panel) that is local-only and non-intrusive.

### 12.1 Purpose

Tell the athlete:

- what is due;
- why it is due;
- what to do;
- what **not** to do;
- how to mark it reviewed.

No automatic threshold changes. The panel is a prompt, not a controller.

### 12.2 Suggested task cards

| task | due calculation | suggested action |
|---|---|---|
| **Readiness threshold review** | 12 weeks or 40 new sessions since last completion | Re-run readiness associations, compare absolute vs relative gates, keep unless held-out improvement |
| **Rubric labels** | show count; target 10 high-confidence marks per measurable item | Review recent sessions; current coverage 9–10 per measurable item (2026-10-25) |
| **3RM/5RM test** | 10 weeks from last measured test | Run `strength-coach test --status`; schedule a test if due |
| **sRPE/duration coverage** | monthly check; target 80% of recent sessions | Review recent sessions with missing sRPE/duration |
| **Back-pattern review** | after a new low-back episode or a pattern that does not fit the existing case series | Review the episode against the private case series; do not auto-change rules |
| **Readiness baseline sufficiency** | fewer than 10 readings in the 28-day window | Keep the fixed fallback; record the gap |

### 12.3 Card content

Each card should show:

- **status:** due / due soon / not yet / insufficient data;
- **last completed** (or “never”);
- **why:** one sentence;
- **what to do:** 2–4 concrete steps;
- **what not to do:** e.g. “do not change the threshold without held-out evidence”;
- **links:** the relevant doc/section;
- **actions:** `Mark reviewed` and optionally `Snooze 2 weeks`.

No card should apply a programme change itself.

### 12.4 Data model

No implementation yet. The minimal design is an append-only table:

```text
maintenance_review
  review_id
  task_key          -- readiness_thresholds | rubric_labels | strength_test | srpe_coverage | back_case
  completed_on
  decision          -- kept | changed | insufficient | not_applicable
  note
  created_at
```

Rules:

- latest row per `task_key` is the completion record;
- corrections append;
- due dates are computed from the latest completion plus the interval;
- task definitions and intervals live in config, not code;
- no external notifications; the local UI is the reminder.

### 12.5 Behaviour

- The panel is visible on Today, collapsed when nothing is due.
- Due items are not modal; they do not block a workout.
- “Mark reviewed” records a decision and note; it does not silently change a threshold.
- “Snooze 2 weeks” records a snooze, not a completion.
- If data are insufficient, the card says so and does not manufacture a due date.
- The panel must not turn into a dashboard of unstable rolling correlations.

### 12.6 Review checklist content

When a readiness threshold review is opened, show:

1. current absolute threshold and fallback;
2. current 28-day baseline and reading count;
3. readiness–performance association on held-out sessions;
4. readiness–sRPE association;
5. how many sessions would have triggered the current vs proposed rule;
6. decision:
   - keep;
   - change with a pre-specified rationale;
   - insufficient data.
7. record the decision in `maintenance_review`.

This makes the reminder useful and auditable, rather than a generic “review due” badge.

---

## 13. Implementation gates

Before the review panel is built:

1. decide whether `maintenance_review` is the right persistence;
2. define intervals and snooze behaviour in config;
3. decide where the panel lives (Today vs a separate Maintenance page);
4. keep all actions non-prescriptive.

No code has been written for this section.


---

## 14. Closure and follow-up

### 14.1 Implemented

- ordinal tax metadata for main lifts and accessories (`config/selection-tax.v1.yaml`);
- accessory candidate lists in `config/variants.v1.yaml`;
- symptom and stress/readiness **suggestions** in `/api/selection` and the Prescribe panel;
- current vs candidate tax, trigger, safety-blocked flag and reasoning;
- explicit apply only; load re-solved from the selected lift's history;
- no automatic substitution;
- no automatic symptom withholding.

### 14.2 Evidence boundary

The evidence supports:

- load/volume autoregulation better than daily exercise selection;
- pain-guided modification as injury management, not a general readiness rule;
- same-pattern variants over unrelated exercises;
- comparability classes because load bases differ.

The evidence does **not** establish:

- a validated per-lift readiness threshold;
- that daily exercise substitution improves outcomes;
- that an ordinal tax map is a measured fatigue model;
- that automatic withholding is safer than a visible suggestion.

The one small autoregulated-selection study found a small lean-mass/bench advantage and no
squat advantage ([Rauch 2020](https://doi.org/10.1519/JSC.0000000000002272)); that is not enough
for automatic removal.

### 14.3 What is needed before automatic withholding

1. **8–12 weeks or ~30 sessions** of suggestion use.
2. Record:
   - trigger frequency;
   - accepted vs ignored suggestions;
   - back symptoms/flares;
   - session completion;
   - main-lift performance.
3. No increase in symptoms or abandoned sessions.
4. The tax table remains accepted after real use.
5. A decision that automatic withholding is preferable to the current safety-blocked
   suggestion.

The **Exercise substitution review** task is now in the periodic reviews dashboard with an
8-week/30-session interval. It records a decision and note; it does not change behaviour.

### 14.4 Plan status

**Closed for the suggestion slice.** Automatic withholding is a separate, evidence-gated
follow-up, not unfinished implementation.
