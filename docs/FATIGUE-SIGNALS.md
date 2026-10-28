# FATIGUE SIGNALS — exposure, residuals, substitution and advisories

**Status:** Phase 0 design and Phase 2 (Part A read-only) implemented, 2026-10-28.
`features/exposure.py` computes the ratio with windows, coverage, dedup and abstention;
`exposure ratio` (CLI), `GET /api/exposure` and the Prescribe **Exposure ratio** panel expose it.
Part D's low-exposure advisory is included. **Phase 3 done 2026-10-28**: the §1 trim is
implemented as `MOD-EXP-001` (constitution 1.20.0), switched by
`athlete_profile.exposure_trim_enabled`, default **off**; `shadow_decision` exists and is
append-only, but the engine does not yet write shadow rows (they land with the Phase 6 review,
so forecast builds never pollute the table). With the flag off nothing changes. Parts B/C
remain design-only.

Governing rule: these are **descriptive signals**, not physiological models. The app does not
estimate fatigue, recovery time or injury probability. Everything is downward-only or
advisory, and every component starts in **shadow** (records what it would do, changes
nothing).

## 1. Part A — rolling hard-set exposure

**Hard set:** a working set with a recorded RIR ≤ 4 (`stress.effort_max_rir`, already the
ledger's definition). RIR 6 is a warm-up and is excluded. A working set with no RIR counts as
**unknown**, not hard and not easy: it enters the denominator of the coverage check, never the
numerator.

**Exposures count.** High-intensity exposure rows (tests, max attempts, competition,
unplanned near-max work) are added to the same ledger, because they are real hard work. To
avoid double counting, an exposure row that references a `set_id` is dropped when that set is
already counted; only free-standing exposures add.

**Windows** (evaluation date `d`, ISO dates, inclusive):

- acute = `[d-6, d]`
- chronic = `[d-34, d-7]` — the 28 days **before** the acute window, so the comparison is not
  self-referential
- `weekly_baseline = chronic_hard_sets / 4`
- `ratio = acute_hard_sets / weekly_baseline`

A ratio near 1 means recent weekly exposure is similar to the preceding month. It is **not** a
fatigue score and not an injury-risk metric.

**Abstain** (no signal, and the reason is reported) when any of:

- fewer than 8 sessions in the chronic window;
- RIR coverage of chronic working sets < 80%;
- `weekly_baseline == 0`;
- the chronic window contains a gap ≥ 10 days (the baseline is depressed and a return week
  would look like a spike for arithmetic reasons);
- the window contains a scheduled deload (same artefact; detected from stored prescription
  notes; if that cannot be established, abstain);
- the evaluation date is inside an active declared break.

**Deloads and missed weeks are not discarded** from the ledger. They are counted as the low
exposure they are; the two abstention rules above only prevent the *trim* from acting on a
depressed baseline.

**Effect.** None by default. `exposure_trim_enabled` on the athlete profile (default **false**)
enables one downward action: trim non-essential accessory sets in the session whose group
ratio is high (≥ 1.3, `ASSUMPTION-51`), at most 1 set per item, 2 sets per session, never
below 1 working set, never essential work, never a main lift, and never an item already
reduced by readiness or already topped up by under-MEV in the same session. Main lifts are
outside this mechanism entirely.

A deload week is a plan, not a fatigue event; the trim never turns a planned deload into a
double reduction (deload runs later and stays the single planned reduction).

## 2. Part B — performance residual (VBT only)

**Definition.** For a prescribed main-lift set that has a velocity target and a stored mean
velocity: `residual = observed_mean_velocity − target_mean_velocity`. Negative means the bar
moved slower than the calibration expected — worse than predicted. This is the only residual
implemented now.

**Why not an e1RM residual.** The engine *solves* the load from e1RM at the target RIR and rep
count. Recomputing an e1RM from the resulting set mostly re-derives the input, so the residual
would measure RIR judgement and rounding, not fatigue. The execution residual (reps×RIR
achieved vs prescribed) is reported as **compliance**, never as fatigue, and the trend-based
e1RM predictor is explicitly out of scope (it is a fitted model).

**Comparability.** Same lift, same rep count, same load basis; use the lift-scoped calibration
target only (not pooled/family). Require at least 5 comparable observations in the window, a
calibration target that is available today, and no change of equipment in the window.
Overlapping rolling windows are not independent evidence: the report shows the window, not a
significance claim.

**Effect.** Shadow only. No modifier, no flag to enable one in this release. A future
downward-only modifier requires a prospective evaluation and an explicit decision.

**When there is enough data to evaluate it.** Two different gates, so "enough" is never
vague:

- *signal available* — at least 5 comparable observations in the window, with a lift-scoped
  calibration target (not pooled/family), for the same lift, rep count and load basis. This
  only lets the report print a residual; it does not justify a modifier.
- *evaluation-ready* — at least 20 comparable observations per lift across at least 8 weeks,
  two lifts with sufficient volume, and an estimated residual spread (so "worse than usual"
  can be separated from measurement noise). `ASSUMPTION-56`.

A read-only *residual readiness* report will print, per lift: comparable observations, rep
bands, calibration scope (lift vs family vs pooled), weeks covered, and which gate is unmet.
That is how you will know it is enough; until both gates are met on at least one lift, Part B
stays off.

## 3. Part C — fatigue-informed substitution (suggest-only)

A suggestion may be produced only when Part A has an active signal (or a future Part B signal
explicitly approved for substitution) **and** every candidate requirement holds:

1. accessory slot only — main lifts are never substituted automatically;
2. the candidate passes existing constraints, suitability, equipment and injury rules, and is
   in the slot's configured candidates;
3. comparability class A or B (class C never, and B only with the existing confirmation);
4. the candidate covers the original's `primary_muscles` (stimulus preservation) and shares
   the family/slot intent;
5. the targeted demand dimension is rated (not `unknown`) for **both** exercises and is
   strictly lower for the candidate;
6. at most one suggestion per slot, at most one substitution per session;
7. no substitution in a group where Part A already trimmed that session (same signal, one
   action).

Abstain and record why when no candidate qualifies. Suggestions display in the existing
Exercise-selection panel with the dimension comparison and the reason; applying one stays the
existing explicit action, which rebuilds the item from the candidate's own history. No load is
ever transferred.

Priority when several signals qualify: injury/constraint > readiness > exposure > substitution.
Hard exclusions and safety rules always win.

## 4. Part D — advisories (never modify)

- **Low exposure:** ratio below 0.7 for two consecutive weeks, with adequate coverage. Text says
  it may reflect missed sessions, a deload or intentional rest, and that low exposure alone is
  not evidence of under-stimulation.
- **Positive residual:** mean VBT residual positive and larger than the calibration's own
  residual spread, with ≥5 comparable sets. Text says it may be prediction bias or normal
  variability.
- If planned progression looks unresponsive to performance, report it as a separate finding;
  never change progression.

## 5. Where these sit in the engine

Actual stages, in order (`prescribe/engine.py`): constraints → readiness (`_apply_readiness_score`)
→ back flare → continuity → automatic-stack cap → volume budget (`volume_budget.apply`) →
compensation → VBT targets → under-MEV → MRV cap (`_apply_volume_cap`) → spinal trim →
deload → minimum session → validation.

- Signals are computed read-only **before** the item loop (Part A from stored sets/exposures,
  Part B from stored sets and calibration).
- Part C produces *suggestions* at the selection stage; applying one is still the existing
  explicit path (`apply_selection`) and rebuilds through `build_item`.
- Part A's trim, when enabled, is applied **after under-MEV and before the MRV cap**, with the
  skip set (readiness-reduced + under-MEV-added ids) so no set is trimmed twice, and so
  under-MEV cannot re-add what the trim removed. It is a registered modifier
  (`MOD-EXP-001`) with a `prescription_modifier` row; it counts inside the existing 20%
  automatic-stack bookkeeping only if it changes load — it changes sets, so it is recorded with
  the set-change fields and does not enter the load stack.
- Part D is generated after validation and never touches the items.

## 6. `shadow_decision` (append-only)

Proposed migration `003x_shadow_decision.sql` for Phase 2:

| column | meaning |
|---|---|
| `decision_id` | uuid |
| `evaluated_on` | date the signal was evaluated |
| `component` | `exposure` \| `residual` \| `substitution` |
| `rule_id` | `MOD-EXP-001`, `MOD-SUB-001`, or `ADVISORY` |
| `signal_json` | window bounds, counts, ratio, coverage, threshold, deload/gap flags |
| `catalogue_digest` | demand-catalogue digest used, or null |
| `config_digest` | thresholds/config digest |
| `proposed_json` | the sets/substitution/advisory it would produce |
| `reason` | human-readable, plus the abstention reason when nothing was proposed |
| `action` | `none`, `trim_sets`, `suggest_substitution`, `advisory` |
| `applied` | 0 in this release; 1 only after an explicit activation decision |
| `prescription_id` | nullable link when a prescription existed |

Update/delete triggers, like `prescription_modifier`. One row per component per evaluation, so
the Phase 6 review can count triggers, abstentions and declines without recomputing history.

## 7. Configuration and flags

- `config/exposure.v1.yaml`: windows, thresholds, coverage minimums, trim caps, flag default.
- `config/residuals.v1.yaml`: minimum observations, calibration scope, advisory thresholds.
- Profile flags: `exposure_trim_enabled` (default false), `exposure_report_enabled` (default
  true; reporting only). No residual or substitution application flag exists in this release.
- Every threshold is an `ASSUMPTION-n` and is printed with the signal so a reader can see the
  rule that fired: `ASSUMPTION-51` (windows, coverage, 1.3 threshold), `ASSUMPTION-52` (trim
  caps), `ASSUMPTION-53` (substitution caps and priority), `ASSUMPTION-54` (residual minimum),
  `ASSUMPTION-55` (Part D thresholds), `ASSUMPTION-56` (Part B sufficiency gates).

## 8. What this explicitly is not

- Not a Banister impulse-response model, not a fitted fatigue-decay model.
- Not ACWR as an injury-risk rule; the ratio is descriptive, and even the opt-in trim is an
  owner decision recorded as contested (`DEC-EXPOSURE-01`, `LIM-56`).
- Not a per-exercise "fatigue score"; the demand catalogue is qualitative and never aggregated.
- Not a reason to raise volume, load, frequency or planned progression.
- Not validated by tests passing; validation is the shadow review plus prospective use.

## 9. Tests to write with each phase

- Windows and boundaries (inclusive dates, leap/week edges), non-overlapping chronic,
  consistency between the ledger and the signal.
- Dedup of exposure rows that reference a counted set.
- Abstention matrix: thin history, low RIR coverage, zero baseline, gap, deload, break.
- Flag off ⇒ byte-identical prescription to the current engine (goldens unchanged).
- Trim: accessory only, floors, caps, skip set, no double trim with MRV/readiness/under-MEV.
- Substitution: class A/B only, main lift never, unknown dimension abstains, stimulus
  preservation, own load/history, one per slot, deterministic priority, decline reason.
- Residual: sign convention, leakage (no look-ahead), comparability, sparsity abstains.
- Advisories never change items.
- Determinism and back-compat (old prescriptions, old taxonomy entries).

## 10. Activation gates

Shadow → report → explicit decision. A flag may only be enabled with the Phase 6 report
attached: trigger frequency, abstention reasons, coverage, proposals declined, and whether any
two components fought over the same family. The trim flag stays off until then; Part B and
auto-substitution have no flag at all.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md), [WEB-UI.md](WEB-UI.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md) (`DEC-EXPOSURE-01`, `DEC-DEMAND-01`, `DEC-RESIDUAL-01`, `DEC-SELECT-08`, `DEC-SHADOW-01`)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Catalogue:** [EXERCISE-DEMANDS.md](EXERCISE-DEMANDS.md)
- **Existing load logic:** [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md), [CONTINUITY.md](CONTINUITY.md), [READINESS.md](READINESS.md)
- **Limitations:** [LIMITATIONS-REGISTER.md](LIMITATIONS-REGISTER.md) (`LIM-56`)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md) §4.19
