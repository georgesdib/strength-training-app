# PERFORMANCE PERSISTENCE — CONTINUOUS FOLLOW-UP PRE-REGISTRATION

**Status:** **closed 2026-11-24 — label `carry-over`.** Gates were approved before the single
run and recorded as `ASSUMPTION-59` in [SANITY-CHECKS.md](../SANITY-CHECKS.md); no gate was changed
afterwards. The result authorises a descriptive sentence only. No rule, prescription or client
behaviour was built.
**Relationship to Phase 0:** this is a **new question on the same record**, not a re-analysis.
Phase 0 closed with verdict \`stop\` and that verdict stands
([archive/PERFORMANCE-CARRYOVER-PHASE0.md](PERFORMANCE-CARRYOVER-PHASE0.md)).
Nothing here reopens the current-session controller.
**Precedent:** [RETROSPECTIVE-VALIDATION.md](../RETROSPECTIVE-VALIDATION.md) — pre-declared
comparison, confidence interval, one look.

---

## 1. Why this exists

Phase 0's only positive was H2, next-exposure persistence: session-lifts containing a set below
the calibration band were followed by a next comparable session that was worse, and the
difference ran against simple regression to the mean. That result rested on a single-digit
number of trigger pairs, because the test dichotomised a continuous quantity — "any set below
−2 MAD" is a rare event.

This document pre-registers the continuous version of the same question, on the data that
already exists. It uses every usable pair rather than the handful that crossed a line.

**What it can establish:** whether a session's deviation from expectation predicts the next
session's deviation on the same lift, and whether that is carry-over of the latest deviation or
merely a stable level.

**What it cannot establish:** why. A shared hard week, poor sleep or a deliberate deload produce
the same persistence as genuine fatigue. No observational adjustment separates them. Nothing
here tests whether reducing volume improves the next session, and nothing here authorises a
volume change.

Phase 0's empirical context still applies: a prior descriptive report found no overall
association between preceding volume and performance, and the readiness audit showed a
retrospective counterfactual is not identifiable.

---

## 2. Hypotheses

| id | hypothesis | null |
|---|---|---|
| **P1** (primary) | A session-lift's mean residual \`u_t\` predicts the next session-lift's mean residual \`u_{t+1}\` on the same exercise, after adjusting for days between, set count, lift and a linear time term. Positive slope = persistence. | β ≤ 0, or the interval includes 0. |
| **P2** (secondary) | The association survives controlling for the *previous* session's residual \`u_{t-1}\`: the latest deviation adds information beyond a stable level. | β₁ ≈ 0 once \`u_{t-1}\` is in the model. |
| **P3** (descriptive) | Where session context exists (sRPE, readiness), it does not account for the association. | Coverage-limited; never a gate. |

P1 decides. P2 changes the **label**, not the decision (§5). P3 is reported and cannot promote a
failed P1.

---

## 3. Data

### 3.1 Eligible set and expectation

Identical to Phase 0 §3: working set; velocity present and positive; effort-classified RIR;
reps 1–8; known load basis; load at least 60 % of the lift's estimated maximum; no
\`REPS_TYPO\`; not voided or superseded. The expected velocity is the **leave-one-session-out**
lift-scoped median at the same rep count inside the lift's target RIR window, with the existing
12-set / 3-session ladder, and \`u = (observed − expected) / spread\` in scaled-MAD units.

The stored-target stratum was empty in Phase 0 and is not part of this plan. This analysis uses
reconstructed expectations only, and says so in the report.

### 3.2 Unit and pairs

- **Session-lift:** one \`(session_id, exercise_id)\` with at least one eligible set. Its value is
  the mean \`u\` across those sets.
- **Pair:** a session-lift and the **earliest later** session-lift on the same exercise, strictly
  after it and no more than **14 days** later, which has at least one eligible set. One next per
  current; no re-use of a next across two currents is required or forbidden — the estimator
  clusters by current session.
- **Triplet (P2 only):** three consecutive session-lifts, each pair ≤ 14 days.

No new exclusions. Sessions whose plan was modified are treated as in Phase 0: known-modified
pairs are excluded, unknown-modification history is included and the limitation is reported. In
Phase 0 that exclusion removed nothing, which is itself reported.

### 3.3 Variables

- \`u_t\`, \`u_{t+1}\`, \`u_{t-1}\` — mean residuals in MAD units.
- \`days\` — calendar days between the two exposures.
- \`n_sets\` — eligible sets in the current session-lift.
- \`time\` — years since the first eligible session in the record, centred.
- \`lift\` — fixed effect; see §4.

---

## 4. Model

**Primary (P1):**

    u_{t+1} = α + β·u_t + γ·days + δ·log1p(n_sets) + τ·time + λ_lift + ε

- \`β\` is the primary estimand.
- \`λ_lift\` is a fixed effect for \`exercise_id\` when that exercise contributes at least 3 pairs;
  exercises below that are collapsed into their \`vbt_family\`, and a family below 3 pairs is
  collapsed into \`other\`. The number of levels is reported.
- Estimator: OLS. Interval: **cluster bootstrap by current session** (2 000 resamples, fixed
  seed), because one session can contribute several exercise-lifts. The plan reports the
  ordinary OLS interval alongside for transparency.
- \`β\` is in MAD units: β = 0.5 means a session one MAD worse predicts the next session half a
  MAD worse.

**Secondary (P2):**

    u_{t+1} = α + β₁·u_t + β₂·u_{t-1} + γ·days + δ·log1p(n_sets) + τ·time + λ_lift + ε

Estimated only when at least 20 triplets exist; otherwise P2 is "not estimable".

**Sensitivities (reported, never used to promote a failed P1):** \`log1p(days)\` instead of
\`days\`; drop the time term; restrict to pairs ≤ 7 days; estimate on the first and second half of
the record separately; ordinary (non-cluster) interval.

**No dichotomisation.** The Phase 0 trigger design is not repeated. No band-crossing subgroup is
used as a rescue.

---

## 5. Pre-registered gates and labels

Gate values are judgement calls, fixed before the run. On approval they are recorded as a single
\`ASSUMPTION\` row in [SANITY-CHECKS.md](../SANITY-CHECKS.md).

**Yield gate (all required):**

- at least **50 pairs**;
- at least **20 distinct current sessions**;
- at least **4 exercises** with 3 or more pairs.

**P1 gate:** β ≥ **0.3** and the 95 % interval's lower bound > 0.

**Labels:**

| label | condition |
|---|---|
| \`carry-over\` | yield met, P1 met, and either P2 is not estimable or P2's β₁ ≥ 0.1 with the same sign |
| \`stable-level\` | yield met, P1 met, P2 estimable, P2's β₁ < 0.1, and P2's β₂ ≥ 0.3 |
| \`not-confirmed\` | yield met and P1 not met |
| \`inconclusive\` | yield not met |

\`stable-level\` is not a failure: it says performance sits at a persistent level but the latest
deviation does not itself carry forward. It is a different product statement from \`carry-over\`.

---

## 6. Rules of the analysis

1. **One look.** No re-runs with a different model, exclusion or gate to obtain a pass.
2. **Thresholds are echoed** into the JSON so the label is reproducible.
3. **CIs are mandatory**; a p-value alone never decides.
4. **Cells and levels below 10 pairs are reported but not interpreted.**
5. **Deviations are logged** in the report with their reason and cannot change the label rule.
6. **The Phase 0 verdict is untouched.** This plan cannot be cited as evidence for a controller.

---

## 7. Deliverables

| item | path | committed? |
|---|---|---|
| Tool | \`tools/performance_persistence.py\` (reuses Phase 0 preparation) | yes, after approval |
| Tests | \`tests/test_performance_persistence.py\` | yes, after approval |
| Report | \`private/docs/PERFORMANCE-PERSISTENCE.md\` + \`.json\` | **no** |
| Public result | this document, §8 | yes |

The tool is read-only (\`mode=ro\`, \`PRAGMA query_only=ON\`), writes nothing outside \`private/\`
without \`--force\`, and adds no CLI command, API route, web panel or client change.

---

## 8. After the result

- **\`carry-over\`** → the honest use is a **descriptive sentence**, at most: "the last session on
  this lift ran below expectation; the next one tends to run harder". No set is removed, no load
  changes, no client policy. A prospective shadow study would be a separate decision with its
  own pre-registration.
- **\`stable-level\`** → record that performance persists as a level but the latest deviation does
  not carry forward. The Phase 0 H2 flag is downgraded to "slow periods are slow"; nothing
  actionable.
- **\`not-confirmed\`** → the H2 flag was a composition artifact. Close the thread with this
  result and do not re-open without new data.
- **\`inconclusive\`** → state which yield condition failed and the revisit trigger. Do not
  loosen a gate.

**In every case: no controller, no volume rule, no client-side policy.**

---

## 9. Explicit non-goals

No current-session decision, no set reduction, no load or RIR change, no calibration change, no
rep-level eligibility, no MRV estimate, no new dashboard, no Swift decision engine, no second
volume ledger.

---

## 10. Approval checklist

1. **Gate values** — β ≥ 0.3, ≥ 50 pairs, ≥ 20 sessions, ≥ 4 exercises. Accept or change.
2. **Lift fixed-effect collapse** — exercise_id at ≥ 3 pairs, else \`vbt_family\`, else \`other\`.
3. **P2 downgrade rule** — the \`stable-level\` definition in §5.
4. **One look**, including no re-run after a null.
5. **What a positive authorises** — a descriptive sentence only.

Until 1–5 are answered, this document is a proposal, not an authorisation.

---

## 8. Result — 2026-11-24

**Label: `carry-over`.** One look at the approved gates; no gate was changed afterwards. Exact
counts and the full model output are in the private report
(`private/docs/PERFORMANCE-PERSISTENCE.md` and `.json`).

- **Yield: met.** On the order of seventy pairs across sixty-odd sessions and six lift levels,
  with four exercises contributing at least three pairs each.
- **P1: met.** The slope on the current session's deviation was about 0.44 MAD, cluster interval
  roughly 0.16 to 0.63 (iid interval close to it). A session one MAD worse predicted the next
  session a little under half a MAD worse, after days, set count, time and lift.
- **P2: the latest deviation survived** controlling for the previous session's level (slope about
  0.42), so the association is not merely a stable per-lift level.
- **Sensitivities: stable in specification, less stable in time.** Log-days and dropping the time
  term left the slope near 0.44. The second half of the record and pairs within seven days were
  weaker, with intervals that included zero. The label stands because the primary was
  pre-registered; the instability is a caveat, not a reason to refit.

**What this means.** Performance persists across exposures on this record. It remains
observational: a shared hard week, poor sleep or a deload produces the same pattern, and no
adjustment here separates them. It does not show that reducing volume improves anything.

**Authorised use.** A descriptive sentence at most: "the last session on this lift ran below
expectation; the next one tends to run harder." No set removed, no load changed, no client
policy, no controller. A prospective shadow study would be a separate decision with its own
pre-registration.

**Evidence:** `tools/performance_persistence.py`, `tests/test_performance_persistence.py`,
private report (not committed).

---

## Related

- [archive/PERFORMANCE-CARRYOVER-PHASE0.md](PERFORMANCE-CARRYOVER-PHASE0.md) — the closed Phase 0 record
- [RETROSPECTIVE-VALIDATION.md](../RETROSPECTIVE-VALIDATION.md) — pre-declared comparison precedent
- [VBT-CALIBRATION.md](../VBT-CALIBRATION.md) — targets, ladder, band
- [SANITY-CHECKS.md](../SANITY-CHECKS.md) — where the approved gates become an assumption
- [DECISIONS.md](../DECISIONS.md) — \`DEC-VBT-04\`, \`DEC-VBT-05\`, \`DEC-RESIDUAL-01\`
- [ROADMAP.md](../../ROADMAP.md) — status authority
