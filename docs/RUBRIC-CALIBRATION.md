# Rubric calibration — B1 review

**Status:** B1 closed 2026-11-07. Rubric 1.2.0 is unchanged; no weight or definition was
retuned. **2026-11-13: the rubric is retired from the runtime (`DEC-EVAL-09`).** The loop went
dormant first (`DEC-EVAL-08`), then the scoring engine, eval harness, mark ingestion, CLI
commands and web endpoints were removed. No marks are requested, no B3 decision is pending, and
the historical rows stay read-only. B2/B3 remain gated to the 2027-01-22 Phase 5A review if a
decision is ever scheduled.

**Scope:** the calibration loop around the deterministic critique rubric. It does not change a
load, a prescription, a rule or a programme decision.

---

## 1. Why the loop exists

The rubric is deterministic: it will always produce a score. A human mark is the only external
signal that can say that score is wrong. Without marks the rubric is unfalsifiable, and
"agreement" has nothing on the other side of it.

The loop is therefore a check, not a validation. It answers "does the engine agree with a
judgement made while the session is still fresh?" It cannot answer "is the rubric correct?",
"are the weights right?" or "does the score improve training?" Those need independent markers,
more than one athlete, or prospective outcomes.

Marks are append-only (`rubric_mark`), carry a confidence, and are tied to the rubric version
that was judged. Only `high`-confidence marks count toward agreement. A reconstructed mark is
kept but excluded. A session whose latest marks were made under another rubric version is
excluded whole (`DEC-EVAL-03` to `DEC-EVAL-06`).

## 2. Current state (2026-11-07)

Twelve high-confidence sessions under rubric 1.2.0, 61 comparable items, 84% agreement,
mean absolute error 0.12.

| item | n | agreement | reading |
|---|---:|---:|---|
| RIR_ADHERENCE | 9 | 89% | at gate; no action |
| PROGRESSION_ADHERENCE | 0 | — | insufficient observations |
| WEEKLY_SPINAL_COST | 12 | 92% | at gate; no action |
| ESSENTIAL_WORK | 4 | 25% | coverage-limited; review finding |
| REDUNDANCY | 12 | 92% | at gate; no action |
| ROTATION | 11 | 64% | definitional split; review finding |
| SESSION_DURATION | 2 | 100% | insufficient observations |
| FORM_ASSESSMENT | 11 | 100% | at gate; no action |
| VELOCITY_LOSS | 0 | — | insufficient observations |

The headline is agreement with one marker, not proof that the rubric is right. The residual is
concentrated in two items; every other measurable item is at or near the gate.

## 3. B1 findings

### 3.1 Rotation

The item asks whether exercise selection stayed stable against the previous session of the same
type. It is a programme-drift check, not a session-quality check.

The label split confirms a definitional disagreement rather than noise. All ten app-assigned
(`Sheiko`) sessions score 1.0 because the engine treats planned rotation as neutral; the human
marks for those same sessions range from 0.5 to 1.0, with three outside tolerance. The one
self-directed session scores 0.0 against a human 0.5. In other words: where the app chose the
rotation, the engine stops measuring churn, while the human still grades it.

**Recommendation (not a code change):** keep app-assigned rotation neutral in 1.2.0, and state
the item's claim as *programme drift*, not *session quality*. Whether the item should grade
actual churn even when the app chose it is a B3 decision; it would be a different measure and
would need a version bump.

### 3.2 Essential work

The item asks whether the session contained its essential main-lift slots. Eight of the twelve
high-confidence marks sit beside an engine score of `measurable = 0` because the imported
session has no prescription snapshot or template. The four comparable cases are split: three
disagree, one agrees.

One live workout is 0.00 against a human 1.00. That is not a scale problem: the engine saw no
essential slot covered while the marker saw a complete session. The case needs inspection — a
snapshot whose items are not flagged essential, a substitution, or a different working
definition — before any definition is changed.

**Recommendation (not a code change):** treat the item as coverage-limited. Prefer live
workouts with a prescription snapshot; do not backfill imports just to create this label.
Whether a substituted lift that fills the same slot counts as coverage is an open B3 question;
implementing it would change the definition and need a version bump.

### 3.3 Other items

RIR, weekly spinal cost, redundancy and form are at the gate; no action. Progression, duration
and velocity loss have too few comparable observations to conclude anything.

## 4. What to do now

**Nothing routine: the loop is dormant.** The `rubric_labels` review prompt is retired and the
monthly marking habit described in earlier revisions of this page no longer applies.

- Existing marks, sessions and reports stay readable; nothing is deleted, edited or recomputed
  differently.
- The 2026-11-07 sample is the closed B1 evidence, not a live target.
- AFC is the canonical post-workout adherence evaluation ([the AFC plan](https://github.com/georgesdib/strength-app/blob/main/docs/plans/AFC.md)); the rubric is a
  display diagnostic with no training consumer.
- If a B3 decision is ever scheduled, collect a fresh version-matched sample *before* the review,
  as B2 requires, and pre-declare the acceptance criteria. Do not re-open routine marking.
- Historical marks stay readable through `GET /api/review/<session>`. The `calibrate` command
  and the on-page report were removed with the engine (`DEC-EVAL-09`); re-reporting the old
  evidence would be a new tool, not a re-enable.

## 5. What this cannot conclude

- Not "the rubric is valid": one marker, one athlete.
- Not "the weights are right": the sample is too small and has no independent labels.
- Not "the score improves training": there is no prospective outcome.
- The honest claim: on this athlete's fresh marks the engine agrees on most items; the residual
  is concentrated in two items and is explained by provenance and coverage, not by a general
  failure.

## 6. Gate

- **B2:** build comparable observations for progression, essential work, duration and velocity
  loss.
- **B3:** change a definition or weight only after B2 and a pre-declared review; record the
  decision in [DECISIONS.md](DECISIONS.md).
- **2027-01-22 Phase 5A review:** no rubric retune before it. Any change after it is a separate
  decision, not an automatic consequence of this report.

## 7. References

- `DEC-EVAL-03`, `DEC-EVAL-04`, `DEC-EVAL-05`, `DEC-EVAL-06`, `DEC-EVAL-07`; `LIM-64`
- [ROADMAP.md](../ROADMAP.md) §4.13a and §4.14
- `strength_coach/critique/rubric.py`, `strength_coach/eval/harness.py`, `strength_coach/eval/store.py`
- [STRENGTH-PROGRAM-REVIEW.md](STRENGTH-PROGRAM-REVIEW.md) for the programme evidence, not the
  calibration loop

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md), [WEB-UI.md](WEB-UI.md)
- **Programme evidence:** [STRENGTH-PROGRAM-REVIEW.md](STRENGTH-PROGRAM-REVIEW.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
