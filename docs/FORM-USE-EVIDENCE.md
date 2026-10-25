# FORM RATINGS — WHAT THEY CAN AND CANNOT BE USED FOR

**Status:** evidence review and retrospective association complete 2026-10-25.
**Decision:** form remains a monitoring/rubric input. It does not change loads, sets or
exercise selection.

---

## 1. What the rating is

A post-lift, per-exercise self-rating:

```text
1 = worst form
5 = best form
```

It is not per set, not a biomechanical measurement, and not a substitute for a coach or video.
The rubric weight is 0.05; it cannot move a prescription.

## 2. External evidence

| question | evidence | what it supports |
|---|---|---|
| Can lifting technique be assessed reliably? | A structured powerlifting squat/deadlift protocol had good content validity and inter/intra-rater reliability for 17 squat and 10 deadlift aspects ([Sjöberg 2020](https://pubmed.ncbi.nlm.nih.gov/30199449/)) | Structured assessment is possible; reliability depends on the protocol and assessor |
| Does better movement quality prevent injury or improve performance? | A 2025 meta-analysis found exercise improves Functional Movement Screen scores, but explicitly cautions against linking FMS improvements directly to performance or injury outcomes ([Maleki 2025](https://www.nature.com/articles/s41598-025-12371-2)) | Movement quality can improve; the injury/performance link is not established |
| Is a single self-rating a validated technique measure? | No validated 1–5 self-rating scale identified for this purpose | The app's rating is a coaching prompt, not a measurement |
| Is there an objective within-set fatigue signal? | Velocity loss tracks acute neuromuscular/metabolic fatigue ([Sánchez-Medina 2011](https://doi.org/10.1249/MSS.0b013e318213f880)); velocity-loss thresholds change the stimulus ([Pareja-Blanco 2016](https://doi.org/10.1111/sms.12678)) | Objective monitoring exists, but it is not the same as self-rated form |
| Is RIR a precise effort measure? | RIR estimation error is meaningful and improves with practice ([Wiedenmann 2026](https://doi.org/10.1186/s13102-026-01997-y); [Robinson 2024](https://doi.org/10.1007/s40279-024-02069-2)) | Self-report is noisy; a form rating is likely noisier |

The evidence supports **structured observation**, not an automatic form score.

## 3. Internal association

The retrospective check asked whether a lift's form rating predicts:

- its e1RM relative to the prior 84-day best;
- the next observed e1RM for the same lift;
- session RPE.

Result, qualitatively:

- correlations were near zero;
- confidence intervals included zero;
- high-rated lifts were not followed by better performance;
- sRPE showed no meaningful association;
- the sample is small, sparse and non-independent.

Exact counts and coefficients are kept in the private analysis record. This is not a
prospective test and cannot establish prediction or causation.

## 4. What it can be used for

### Monitoring

- **Form trend** in Outcomes: latest rating, current vs previous window, coverage.
- **Review context**: this session's rating beside prior ratings for the same lift.
- **Coaching prompt**: a low rating is a question (“what changed?”), not a verdict.
- **Correlation study**: compare form with sRPE, symptoms, velocity loss, e1RM residuals.

### Programming

- **No automatic change.** A low form rating alone must not reduce load, add RIR, remove sets,
  substitute an exercise or trigger a deload.
- **Technique work** can be a coaching response after the athlete reviews the pattern.
- **Exercise selection** may show form as context, but must not rank or exclude a lift on it.
- **A user-declared throttle is not a rating-driven change.** `MOD-TECH-001` lets the athlete
  ask for a lighter session after reviewing a pattern; it reads no `form_rating`, stores no
  flag and carries nothing forward (`docs/TECHNIQUE-THROTTLE.md`).

## 5. What it must not be used for

- injury prediction or “clearance”;
- validating RIR or replacing velocity loss;
- deciding that an e1RM is invalid;
- automatic progression/regression;
- a universal “good form” threshold;
- comparing different lifts as if 3/5 meant the same thing.

## 6. e1RM quality metadata

The proposed next use was to tag or downweight e1RMs from low-form sessions.

**Not recommended yet.** The retrospective association does not show that low form predicts a
worse e1RM or next-session performance. Tagging would add a second, unvalidated quality model to
the load lineage.

A future version would need:

1. a pre-specified outcome and window;
2. enough repeated low-form observations per lift;
3. reliability checks on the rating anchors;
4. a prospective test against a simple baseline;
5. a bounded display-only phase before any load use.

## 7. Decision

Keep form as:

- rubric input (0.05);
- descriptive trend;
- review context;
- coaching prompt.

No load, set, selection or e1RM filtering change.

## 8. References

Full bibliography: [`REFERENCES.md`](REFERENCES.md). This note uses references 163–164 plus
the existing RIR/velocity references 143–149.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
