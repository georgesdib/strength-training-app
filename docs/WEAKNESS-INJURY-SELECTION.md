# WEAKNESS / INJURY-TARGETED SELECTION — evidence and decision

**Status: targeting deferred; display-only own-history context implemented.** No exercise is
selected because it targets an injury or a weak muscle. Injury remains a
constraint/ceiling/penalty. The selector shows an own-history e1RM ratio, which never enters the
score.

---

## 1. Why this is not obvious

Two different claims are often mixed:

1. **Weakness targeting:** choose exercises because a lift or muscle is lagging.
2. **Injury targeting:** choose exercises because a region is injured or at risk.

Both need a validated definition and a tested intervention. Neither currently exists for this
single-athlete programme.

## 2. Evidence

### Individual variation is real, but not predictable from one programme

True individual response variation requires repeated within-person designs; group averages can
hide different responses ([Robinson 2024](https://doi.org/10.1007/s40279-024-02050-z)).

Auto-regulated exercise selection produced small lean-mass and bench-press advantages over
fixed selection in one small study, but no squat advantage; it was not a weakness-targeting
algorithm ([Rauch 2020](https://doi.org/10.1519/JSC.0000000000002272)).

### A shared pattern is not a validated weakness measure

Exercise specificity means training a lift improves that lift. It does **not** establish that
choosing the lowest e1RM is the right programme adjustment. A low e1RM can reflect technique,
practice, fatigue or measurement error.

### Asymmetry and injury prediction are inconsistent

Inter-limb strength asymmetry has inconsistent calculation methods and thresholds
([Parkinson 2021](https://doi.org/10.52082/jssm.2021.594)).

In sub-elite rugby players, no unilateral leg-strength measure was related to injury relative
risk; relative strength had only a weak association with time lost
([Helme 2023](https://doi.org/10.1016/j.ptsp.2023.05.003)).

Some population-specific exceptions exist: preseason supraspinatus weakness was associated with
major shoulder/elbow injury in high-school pitchers
([Tyler 2014](https://doi.org/10.1177/0363546514535070)), and older preseason imbalance work is
mixed ([Knapik 1991](https://doi.org/10.1177/036354659101900113)). These do not support a general
automatic rule.

### Injury-targeted exercise is not the same as rehabilitation

Pain-guided activity modification is feasible in patellar tendinopathy
([Sprague 2021](https://doi.org/10.1186/s40814-021-00792-5)), but it is a rehabilitation strategy,
not evidence that a selector should choose exercises from an injury map.

Exercise therapy is effective for chronic low back pain ([Hayden 2021](https://doi.org/10.1002/14651858.CD009790.pub2))
and tendinopathy ([Lopes 2025](https://doi.org/10.1002/14651858.CD013078.pub2)), but these trials
test treatment programmes, not algorithm-selected substitutions.

Prior injury is a strong recurrence marker; that supports **caution and exposure management**,
not “train the weak area to prevent recurrence.”

### Parent-variant e1RM ratios are not a weakness measure

A ratio between two exercise variants (for example, front squat ÷ back squat) is a relative
performance ratio, not a muscle diagnosis. It mixes load basis, technique, familiarity, range
of motion and e1RM noise. A low ratio is a prompt to check specificity/technique before calling
it weakness. See
[PARENT-VARIANT-WEAKNESS-EVIDENCE.md](PARENT-VARIANT-WEAKNESS-EVIDENCE.md).


## 3. Decision

1. **No weakness-targeted selection now.**
2. **No injury-targeted positive selection now.**
3. Injury status may only:
   - exclude a candidate,
   - penalise a candidate,
   - cap readiness.
   It may never boost a candidate because it “targets” an injury.
4. If a relative-weakness display is added later, it is **display-only**, based on the
   athlete’s own trend, with uncertainty; it must not change the ranking.
5. Any future targeting must still obey the A/B/C comparability guard; C remains never automatic.
6. Revisit only after:
   - a validated weakness definition,
   - enough per-lift history,
   - a retrospective baseline result,
   - and a prospective or N-of-1 test showing benefit without harming the main lifts.

## 3a. What was implemented now

- Each selection candidate gets a **display-only** `history_context`:
  latest best e1RM versus the median of that lift's own earlier 84 days, with n and a plain
  label.
- It is **not** part of the score, ranking, class or prescription.
- It uses no parent-lift ratio and no population norm.
- No weakness target and no injury-positive selection were added.

## 4. Deferral gates — when this can be revisited

A concrete test plan is recorded in
[WEAKNESS-TARGETING-PLAN.md](WEAKNESS-TARGETING-PLAN.md): metric, retrospective screen,
opt-in N-of-1 blocks and decision gates. It is plan-only; no targeting is implemented.

**Recommended: not before v0.5 is complete, and not before six months of stable current-programme
data (~April 2027).** That is an earliest review point, not a commitment.

Weakness targeting may be reconsidered only when all of these exist:

1. **Data:** at least 12 sessions per targeted lift, across at least 12 weeks, under the current
   programme and with manual logging/import quality fixed.
2. **Definition:** a pre-registered weakness metric (own-trend e1RM, not a population ratio) and
   a declared target lift.
3. **Retrospective baseline:** the proposed targeting rule beats fixed selection on a
   walk-forward check, with uncertainty.
4. **Counterfactual design:** an opt-in N-of-1 or alternating-block test, not a single-path
   observational comparison.
5. **Safety:** the test shows no harm to the other main lifts or the back, and no increase in
   flare frequency.

Injury targeting is **not scheduled at all**. It may only be revisited if a clinician defines a
specific rehabilitation goal and the athlete wants it; it is not a general selection feature.
Until then, injury remains exclusion/penalty/ceiling only.

## 4a. Plan and earliest date

| phase | deliverable | status |
|---|---|---|
| 0 | evidence, guardrails, display-only own-history context | **done** |
| 1 | 12 sessions per target lift over 12 weeks; stable logging | waiting for data |
| 2 | pre-registered own-trend weakness metric + retrospective walk-forward baseline | not started |
| 3 | opt-in N-of-1 / alternating-block comparison, with safety outcomes | not started |
| 4 | decision: keep fixed, or add a bounded targeting rule | not reached |

**Earliest review:** after v0.5 and roughly **April 2027**. This is a gate, not a scheduled
feature. Injury targeting remains unscheduled at every phase.

## 5. What would be tested if this is revisited

- primary outcome: the targeted lift’s e1RM/performance, not “feels better”;
- guardrail outcomes: other main lifts, pain/injury, session completion;
- comparison: fixed programme vs targeted selection, with a pre-declared analysis;
- no automatic application until the comparison is positive.

No targeting implementation in this change.

## Related

- **Evidence review:** [PARENT-VARIANT-WEAKNESS-EVIDENCE.md](PARENT-VARIANT-WEAKNESS-EVIDENCE.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
