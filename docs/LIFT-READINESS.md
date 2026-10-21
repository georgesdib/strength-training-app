# Per-lift readiness — evidence and implementation

**Status: implemented 2026-10-20 (`DEC-LIFT-READY-01`), advisory and downward-only.**
The score is a bounded extension of the global readiness score, not a validated instrument.

---

## 1. Why a per-lift score at all

The global score answers "how ready is the athlete today". A session is not uniform: the
squat may feel fine while the hinge is still fatigued from two days ago. The app already has
**category** overrides (squat, hinge, horizontal push, …), but no per-exercise estimate.

This implementation exists to make the available signals explicit. It does **not** claim that
the composite is valid; the evidence for per-lift readiness is weak.

## 2. What the evidence supports

| input | evidence | what it can and cannot say |
|---|---|---|
| **Subjective wellness** (global score) | Subjective measures track training load better than most objective markers (Saw 2016, ref 47); Hooper 1995, Govus 2018 | Best-supported *general* readiness signal; not lift-specific |
| **RIR / RPE-based autoregulation** | A systematic review of 14 studies found RIR/RPE-based autoregulation increased 1RM, but the methods and comparisons were heterogeneous (Larsen 2021, ref 106) | Effort is a legitimate adjustment input; RIR is not a validated per-lift readiness measure |
| **Bar velocity** | Mean propulsive velocity in the squat is sensitive to acute fatigue, especially at 40% and 80% 1RM (Moura 2024, ref 107) | A performance/fatigue marker at a *standardised* load; the app's VBT data are sparse and not always at a fixed load |
| **e1RM trend** | The load itself is derived from e1RM; a falling e1RM at similar RIR indicates impaired performance | Noisy because e1RM is an Epley+RIR estimate |
| **Meta-session autoregulation** | A scoping review found subjective readiness measures often lacked validity evidence and fidelity was rarely reported (Ibrahim 2024, ref 108) | Strong caution: do not treat a per-lift readiness score as established |

**Conclusion:** there is no validated per-lift readiness questionnaire or composite. Combining
global readiness with recent RIR, velocity and e1RM is a **transparent assumption**, not a
finding. That is why the score can only *lower* a load.

## 3. The score

```
base   = global readiness score (or category override), capped by the injury ceiling
score  = base
       + 0.20 * (e1rm_score   - 0.5)
       + 0.15 * (rir_score    - 0.5)
       + 0.15 * (vbt_score    - 0.5)
```

- Neutral components are **0.5**, so a normal session leaves the base unchanged.
- Missing components are omitted (no renormalisation needed: they contribute zero).
- `score` is clamped to 0–1.

| component | source | neutral | low / high |
|---|---|---|---|
| `e1rm` | latest session's best e1RM vs the median of the previous 28 days | ratio 1.0 | ±10% maps to 0 / 1 |
| `rir` | mean RIR of the last session's working sets | RIR 2 (target 2–3) | RIR 0 → 0.1; RIR 5 → 1.0 |
| `vbt` | mean actual velocity vs the VBT calibration median at the same rep count | ratio 1.0 | ±10% maps to 0 / 1 |

Status bands: `ready ≥ 0.75`, `monitor ≥ 0.50`, `low < 0.50`.

## 4. How the engine uses it

- The per-lift score is computed for the exercises actually prescribed, from history **up to**
  the prescription date.
- If the per-lift score is **lower** than the global/category score, the readiness factor is
  recomputed from the lower score (load −5%, RIR +1 at the same bands). The injury ceiling still
  applies.
- If it is **higher**, it is ignored: the engine never uses an unvalidated composite to make a
  session harder.
- The scores and components are attached to `notes.per_lift_readiness` and shown on the
  Prescribe page and in `run` output. They are **not** a new rule and do not appear in the
  constitution.

## 5. Limitations

- **It is retrospective.** Today's RIR/velocity do not exist before the session; the score uses
  the last session. It is a prior, not a measurement.
- **RIR is imprecise.** Predictions can be off by ~2–5 reps depending on proximity to failure
  (Zourdos 2021, ref 101; Remmert 2023, ref 102), which feeds directly into the `rir` component.
- **VBT is sparse and load-dependent.** A velocity target only exists for lifts with enough
  clean sets; the app does not prescribe velocity targets for the trap bar (`DEC-VBT-01`), and
  mixed loads make the comparison approximate.
- **No per-lift soreness/pain input.** The global soreness field and the injury signal stand in
  for it. A true per-lift readiness score would need a lift-specific pre-session rating.
- **Weights are arbitrary.** 0.20/0.15/0.15 were chosen to let the subjective base dominate;
  they are `ASSUMPTION-25`, not fitted values.
- **No prospective validation.** There is no trial showing that reducing a lift's load on this
  score improves outcomes. Downward-only is the safety compromise.

## 6. What would make it stronger

1. A lift-specific pre-session soreness/readiness rating (1–5), logged before the session.
2. A standardised velocity check at a fixed load, so VBT is comparable across sessions.
3. More measured e1RM tests, enabling an e1RM calibration report and a better trend baseline.
4. Prospective validation: does a low per-lift score predict a missed rep or a worse session?

Until then, the global readiness score remains the primary signal and this score is a
transparent second opinion.

## References

Refs 47, 101–103, 106–108 in [`REFERENCES.md`](REFERENCES.md).
