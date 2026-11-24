# PERFORMANCE CARRY-OVER — PHASE 0 PRE-REGISTERED ANALYSIS

**Status:** **closed 2026-11-24 — verdict `stop`.** Thresholds were approved before the
single run; no threshold was changed afterwards. The analysis tool is implemented and tested
(`tools/performance_carryover.py`). No rule, calibration, prescription or client behaviour
was implemented.
**Prerequisite to any work:** the owner approves the thresholds in §5 in writing. After that,
the analysis is run **once**, and no threshold is changed in response to the result.
**Precedent:** [RETROSPECTIVE-VALIDATION.md](../RETROSPECTIVE-VALIDATION.md) — pre-declared
comparison, confidence interval, then a frozen prospective period if anything survives.

---

## 1. What this analysis is for

A proposal is on the table to use actual performance — RIR and mean velocity — to decide whether
the remaining sets of a session are still worth doing, and whether the next exposure should have
fewer sets. Its first release would be downward-only: it may recommend fewer sets, never more,
and never change a load.

Before that rule is specified, let alone built, one question has to be answered from data the
server already holds:

> **Does an under-performing set carry information about the next set, and does an
> under-performing session carry information about the next comparable session?**

That is the mechanism the rule depends on. If a slow or over-effortful set is an event about
that set only, then cutting the remaining work because of it is unjustified regardless of how
well engineered the controller is.

**What this analysis cannot establish.** It cannot show that reducing volume improves anything.
The log contains one observed training path and no counterfactual: the same limitation that
closed the readiness audit ([archive/READINESS-AUDIT.md](READINESS-AUDIT.md) §F1).
Historical replay can test the classifier and the mechanism; it cannot test the intervention.
Effectiveness would need the shadow-then-prospective path in §8.

**Consequence of a pass:** authorisation to write a *shadow* rule specification. Nothing else.
No prescription changes, no client work, no new modifier.

---

## 2. Hypotheses

| id | question | null |
|---|---|---|
| **H0** | Is there enough analysable data for the question to be answerable at all? | — (yield gate) |
| **H1** | A set materially below its expected velocity predicts a further below-expectation next set on the same lift, after controlling for set position and load. | No association beyond position. |
| **H2** | A session-lift with poor performance predicts worse performance at the next comparable exposure. | No association; poor sessions are isolated events. |
| **H3** | RIR deviation and velocity deviation agree often enough for a "corroboration" requirement to be usable. | The channels disagree too often; a corroborated rule would abstain nearly always. |

H1 is the current-session premise. H2 is the next-exposure premise. H3 is a design-feasibility
check: the proposal requires both channels to agree before acting, so if they rarely agree, the
rule as written cannot fire.

---

## 3. Data and definitions

### 3.1 Source and access

Read-only SQLite (`PRAGMA query_only=ON`), following the pattern of
`tools/monitoring_historical_audit.py`. Primary sources: `workout_set`, `clean_set`,
`prescription_item` (`velocity_target`, `vbt_basis`, `load_basis`), `workout_session`
(date, status, `plan_json`, `plan_modified_json`), `clean_rep` (reported only; never an
independent observation, per [VBT-REP-LEVEL.md](../VBT-REP-LEVEL.md)).

No writes, no migration, no new table, no API route, no web panel, no client change.

### 3.2 Eligible set

All of the following, mirroring the existing calibration and comparability rules rather than
inventing new ones:

- working set; not voided; session not voided; not superseded by a later row;
- velocity present and `> 0`; no `REPS_TYPO` or other data-quality flag;
- `rir` present and effort-classified (0-5, i.e. not the RIR-6 warm-up marker). Only sets
  **inside** the lift's target RIR window (`rir.target_for`) enter the expected-velocity sample;
  sets outside it keep a residual for H3 and the H1 sensitivity, because that deviation is the
  RIR channel the proposed rule would act on;
- reps in 1–8; `load_basis` known; load at least 60% of the lift's estimated maximum;
- a usable expected velocity (§3.3).

### 3.3 Expected velocity

**Primary (all history): leave-one-session-out lift-scoped target.** For a set in session S, the
expected velocity is the median velocity of eligible sets at the same `exercise_id` and rep
count, in the same RIR window, **from other sessions only**, requiring the existing ladder
(≥ 12 sets, ≥ 3 sessions). This avoids two errors: a set defining its own expectation
(circularity), and borrowing a family target, which [residual.py](../../strength_coach/features/residual.py)
already refuses because it is not independent evidence for one lift.

**Secondary (policy-relevant): the stored `velocity_target`** for app-generated workouts, which
is exactly what the rule would compare against in production. Reported as a separate stratum.

If a set has no expected velocity under either rule, it is excluded and counted.

### 3.4 Residual and standardisation

`r = observed_mean_velocity − expected_velocity` (m/s).

`u = r / MAD_expected`, where `MAD_expected` is the robust spread of the leave-one-session-out
sample. `u` is in band units: the calibration band is median ± 2·MAD, so a set is **below the
band** when `u < −2`, **above** when `u > +2`, and **expected** otherwise. Reporting in MAD
units makes one threshold usable across lifts of different absolute speed. Sets whose
`MAD_expected` is zero or undefined are excluded.

### 3.5 Position and load

**Position** is the ordinal of the working set within (session, exercise), counting *all* working
sets including those without velocity, so a gap does not compress the sequence. First set = 1.
H1 strata: position 2–3 and position ≥ 4.

**Load is a confound, not a detail.** The target is conditional on reps and RIR only
(`DEC-VBT-07`), so a back-off set at lower load reads as a large positive residual. Two
consequences:

- **H1 primary** uses only **constant-load groups**: (session, exercise) where the working-set
  loads vary by no more than the rounding increment (or 1%). Within such a group, load cannot
  explain a residual difference, and position is the only structural variation.
- **H1 sensitivity** uses all groups with `load / e1RM` as a covariate, so the direction and
  size of the bias are visible.

### 3.6 Modified sessions

A session modified by a safety rule (`fallback_level != "full"`, symptom flare) or a scheduled
deload is flagged. H2's primary estimate **excludes pairs with such a session between the two
exposures**, because the intervention changed and persistence would be diluted. The excluded set
is reported separately, not silently dropped.

### 3.7 Privacy

Row-level output, the generated report and the JSON stay under `private/`; the report may
contain personal training data and must never be committed. The public record carries method,
thresholds, aggregate results and the verdict — no exact single-athlete counts (see
[PRIVACY.md](../PRIVACY.md)).

---

## 4. Analysis

### 4.1 H0 — yield (descriptive, reported first)

Per lift: eligible sets, session-lifts, consecutive pairs, below-band sets. Plus coverage:
velocity present, RIR present, both, and a usable target. Cells with `n < 10` are reported but
not interpreted.

**Gate:** at least 20 session-lifts with ≥ 2 eligible sets in a constant-load group, and at least
15 below-band sets. Below that, the report returns `inconclusive` and no hypothesis is tested.

### 4.2 H1 — within-session carry-over

Unit: consecutive eligible pairs `(t, t+1)` in a constant-load group, both with a target.

- **Primary estimand:** risk difference
  `P(u(t+1) < −2 | u(t) < −2) − P(u(t+1) < −2 | u(t) ≥ −2)`, pooled over position strata by
  stratum size, with a 95% cluster bootstrap by session. Also report a position-stratified
  Mantel-Haenszel odds ratio (Robins-Breslow-Greenland interval): the same estimand as a
  position-adjusted model, without adding a modelling dependency. A zero-cell stratum is
  continuity-corrected; when the OR is still not estimable, criterion 3 is carried by the risk
  difference and the report says so.
- **Secondary:** an unadjusted linear slope of `u(t+1)` on `u(t)`, reported as a
  descriptive companion and not a decision criterion; the 3×3 cross-tab of
  below/expected/above verdicts for consecutive sets, position-stratified.
- **Sensitivity:** trigger at `u < −1.5` and `u < −1`; all groups with the load covariate;
  stored-target stratum only.

One primary test. The sensitivity results are labelled and cannot promote a failed primary.

### 4.3 H2 — cross-session persistence

Unit: session-lift with at least one eligible set. Predictor: mean `u` and a below-band count.
Outcome: mean `u` at the next session on the **same exercise** within 14 days, which must have
at least one eligible set.

- **Primary:** difference in mean next-session `u` between trigger session-lifts (≥ 1 below-band
  set) and non-trigger session-lifts (trigger minus control; a negative difference means the
  next session was worse), with a 95% bootstrap CI by session. Paired means are
  reported so the reader can see the raw shape, not only the adjusted number.
- **Secondary:** linear model with days between, set count and lift fixed effects; and the
  best-e1RM ratio outcome used by the existing volume–performance report, as a second channel.
- **Sensitivity:** include modified/deload pairs; require the same rep count.

### 4.4 H3 — channel agreement

Cross-tabulate the RIR verdict (below window / inside / above window) against the velocity
verdict (below / expected / above) for sets with both channels. Report raw agreement, Cohen's
`kappa`, and the share of eligible sets that carry both channels.

**Gate:** raw agreement ≥ 40% **and** `kappa ≥ 0.1`. Below that, a rule requiring corroboration
is not usable as specified and must be redesigned (for example RIR-only) before any further
work.

---

## 5. Pre-registered decision rule

All thresholds below are **judgement calls**, not measurements. They are chosen so that a
"pass" implies an effect large enough that acting on it could plausibly beat continuing, not
merely an effect distinguishable from zero. On approval they are recorded as a single
`ASSUMPTION` row in [SANITY-CHECKS.md](../SANITY-CHECKS.md), with the next free identifier.

| # | Metric | Pass | Otherwise |
|---|---|---|---|
| 1 | Yield | ≥ 20 session-lifts with ≥ 2 constant-load eligible sets; ≥ 15 below-band sets | `inconclusive` — do not loosen thresholds to rescue it |
| 2 | H1 risk difference | ≥ 10 percentage points; 95% CI excludes 0 | H1 fails |
| 3 | H1 adjusted OR | > 1; 95% CI excludes 1 | H1 fails |
| 4 | H2 difference in next mean `u` (trigger minus control) | ≤ −0.5 MAD — trigger sessions followed by worse performance — with the 95% CI entirely below 0 | H2 fails |
| 5 | H3 agreement | ≥ 40% raw and `kappa ≥ 0.1` | design not usable |
| 6 | Trigger rate | 5–40% of eligible sessions | outside the band: re-scope, do not retune |

**Verdict:**

- `pass` — 1, 2, 3, 4, 5 and 6 are all met → write the shadow-rule specification (§8).
- `narrow` — 1, 2, 3, 5 and 6 met but 4 not → current-session advisory only; H2 is closed and
  the next-exposure controller is not pursued on this evidence.
- `stop` — 1 fails, or 2/3 fail, or 5 fails → write the close-out and build nothing.
- `inconclusive` — 1 fails only for sample size → record what would be needed and when to
  revisit; do not build in the meantime.

The 0.5-MAD figure for H2 is half the distance a set must move to cross its own band, so a
session-level shift of that size is the smallest one plausibly worth acting on. It is a
threshold of usefulness, not of statistical detectability. The sign is fixed: a poorer
performance is a lower `u`, so persistence is a negative difference and its interval must lie
below zero. Criteria 2-3 are met together; if
the OR is not estimable because of a zero cell, criterion 3 is carried by criterion 2 rather
than failing a rule the data cannot compute. The 8-pair H2 floor is an implementation guard so a
handful of pairs cannot pass on a wide-but-positive interval.

---

## 6. Rules of the analysis

1. **One look.** The analysis is run once at the approved thresholds. No re-runs with a different
   exclusion, threshold or sample to obtain a pass. Repeated looks at a small record turn noise
   into findings, as the volume–performance report already warns.
2. **Uncertainty is mandatory.** Every estimate carries a 95% CI. A p-value alone never decides.
3. **Small cells are not interpreted.** `n < 10` is reported for completeness and excluded from
   conclusions.
4. **No subgroup fishing.** Per-lift results are descriptive. The pooled estimate is primary.
5. **Deviations are recorded.** Any departure from this document is logged in the report with
   its reason and the date, and cannot change the verdict rule.
6. **The thresholds are echoed.** The JSON output records the exact threshold values used, so the
   verdict is reproducible and cannot be re-read against a different rule.

---

## 7. Deliverables

| item | path | committed? |
|---|---|---|
| Analysis tool (read-only) | `tools/performance_carryover.py` | yes |
| Tool tests | `tests/test_performance_carryover.py` | yes |
| Generated report | `private/docs/PERFORMANCE-CARRYOVER-PHASE0.md` | **no** |
| Machine-readable result | `private/docs/PERFORMANCE-CARRYOVER-PHASE0.json` | **no** |
| Public method/result summary | this document, §4–§5 updated with aggregates and the verdict | yes |

The tool takes an explicit `--db` path, refuses a write-capable connection, and writes nothing
unless an output path under `private/` is given. It is an analysis tool, not a CLI command and
not a web panel, so it adds no UI/CLI parity obligation. Its output is not a prescription input,
is not stored as a decision, and does not create a `shadow_decision` row: this analysis is about
whether a rule is worth specifying, not a rule being evaluated.

---

## 8. After the result

- **pass** → write the shadow-rule specification: server-side only; a pre-issued, per-set stop
  condition frozen into the plan; downward-only; accessory/core work first; protected top sets;
  reuse `shadow_decision` and the existing evidence envelope; explicit precedence against
  readiness (`MOD-FAT-001`), MRV (`MOD-VOL-001`), exposure trim (`MOD-EXP-001`) and under-MEV
  addition (`MOD-VOL-002`); no client-side policy. That specification needs its own approval.
- **narrow** → specify only the half that survived, and say in the document which half was
  dropped and why.
- **stop** → a one-page close-out in `docs/archive/`, naming the result and the reason, so the
  proposal is not re-opened without new data.
- **inconclusive** → state the missing sample and the revisit trigger (for example "after N
  further app-generated sessions with a stored target"). Do not build.

---

## 9. Explicit non-goals

This analysis does not change, and does not authorise changing: the VBT calibration; rep-level
eligibility for any rule (`DEC-VBT-04`, `DEC-VBT-05`); any load, RIR or set count; the weekly
volume ledger; readiness; the constitution; any API route or schema; the iOS or watch client;
the UI. It introduces no fatigue score, no MRV estimate, no trend dashboard and no second ledger.

---

## 10. Approval checklist

**Approved 2026-11-24:** the thresholds in §5, with recommendations 2-6 accepted (all-history
leave-one-session-out primary, constant-load restriction for H1, the stated yield bar, the
modified-session exclusion, and a pass authorises a specification only). The remaining step is
the first run, on the server database. The checklist below is kept as the record of what was
decided:

1. **Thresholds in §5** — accept, or change and record the change.
2. **Primary expected-velocity rule** — leave-one-session-out lift scope (recommended) versus
   stored app targets only (smaller, but exactly the production comparison).
3. **Constant-load restriction for H1 primary** — accept, or move it to sensitivity only.
4. **Minimum yield** — 20 session-lifts / 15 triggers, or a different bar.
5. **Modified-session exclusion in H2** — exclude from primary (recommended) or include.
6. **What a pass authorises** — specification only (recommended), not implementation.

Until 1–6 are answered, this document is a proposal, not an authorisation.

---

## 11. Result — 2026-11-24

**Verdict: `stop`.** The analysis was run once at the approved thresholds. Exact counts, the
machine-readable result and the per-stratum tables are in the private report
(`private/docs/PERFORMANCE-CARRYOVER-PHASE0.md` and `.json`); this section records the shape
and the decision.

- **Yield: met.** A minority of the stored sets carried both a usable velocity and an effort
  rating; the trigger rate sat inside the pre-registered 5-40 % band.
- **H1 (current-session carry-over): not testable on this record.** The constant-load
  restriction left a double-digit handful of consecutive pairs and a single trigger pair. The
  risk difference is therefore uninformative, the continuity-corrected odds ratio is very wide,
  and the report states that this is underpowered rather than evidence of absence.
- **H2 (next-exposure persistence): met the pre-registered criterion.** Session-lifts that
  contained a below-band set were followed by a next comparable session about half a MAD worse,
  with the interval entirely below zero. A single-digit number of trigger pairs carried the
  estimate. It is observational, confounded by hard weeks and life stress, and is not a licence
  to act.
- **H3 (channel agreement): met the pre-registered gate.** RIR and velocity agreed in the large
  majority of dual-channel sets, with a fair rather than strong kappa: most sets were
  unremarkable on both channels, and disagreement clustered at the edges.
- **Production-target stratum: empty.** No app workout contributed a stored velocity target, so
  the comparison the proposed rule would actually make could not be evaluated at all.

**What this closes.** The current-session controller is closed: the mechanism it depends on could
not be demonstrated, and building it would act on an untested premise. The H2 persistence signal
is a flag, not a finding; it would need a separate pre-registration with a pair-count gate and a
design that accounts for hard weeks before it could justify anything. The constant-load
restriction is what removed H1's power, so a future attempt would need a load-adjusted design
rather than a constant-load subgroup.

**Evidence:** `tools/performance_carryover.py`, `tests/test_performance_carryover.py`,
private report (not committed).

---

## Related

- [RETROSPECTIVE-VALIDATION.md](../RETROSPECTIVE-VALIDATION.md) — the pre-declared-comparison precedent
- [VBT-CALIBRATION.md](../VBT-CALIBRATION.md) — targets, ladder, what the band means
- [REP-VELOCITY.md](../REP-VELOCITY.md), [VBT-REP-LEVEL.md](../VBT-REP-LEVEL.md) — why rep-level is not an input
- [VOLUME-MANAGEMENT.md](../VOLUME-MANAGEMENT.md), [FREQUENCY-AND-VOLUME.md](../FREQUENCY-AND-VOLUME.md) — existing volume valves and their evidence
- [FATIGUE-SIGNALS.md](../FATIGUE-SIGNALS.md) — shadow-only precedent and gate report
- [SANITY-CHECKS.md](../SANITY-CHECKS.md) — where the approved thresholds become an assumption
- [DECISIONS.md](../DECISIONS.md) — `DEC-VBT-04`, `DEC-VBT-05`, `DEC-VBT-07`, `DEC-RESIDUAL-01`
- [ROADMAP.md](../../ROADMAP.md) — status authority
