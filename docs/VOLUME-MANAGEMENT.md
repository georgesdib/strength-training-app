# Volume management — evidence and implementation

**Status: v1 done (2026-10-20).** “Done” means the evidence check, ledger, configured
landmarks, conservative MRV cap, readiness valve and UI/CLI/API are implemented. It does **not**
mean individualized MRV (closed as not estimable), per-muscle volume or prospective validation;
the under-MEV accessory progression is a separate deterministic rule (`MOD-VOL-002`). A separate scheduled/reactive deload policy is described
in `DEC-PROGRAMME-05`.

**Scope:** weekly hard-set volume for the strength programme. This note records the evidence
used for the volume ledger and the conservative MRV cap; it is not a claim that MEV/MRV are
measured individual constants.

---

## 1. What the evidence supports

### Volume dose-response

- Weekly volume is associated with more hypertrophy up to a point of diminishing returns; the
  shape differs for strength, hypertrophy and other outcomes. A 2025 meta-regression of weekly
  volume and frequency is the main current source
  ([Sports Medicine 2025](https://link.springer.com/article/10.1007/s40279-025-02344-w)).
- An earlier dose-response review found hypertrophy increasing to roughly 10+ sets per muscle
  per week with diminishing returns ([Schoenfeld et al. 2017](https://www.tandfonline.com/doi/abs/10.1080/02640414.2016.1210197)).
- Strength is generally less volume-dependent than hypertrophy; very high volumes are not
  required for strength and can add fatigue. Examine's summary of the strength-volume question:
  [Examine](https://examine.com/faq/how-much-volume-do-i-need-to-perform-to-increase-muscle-strength/).

### MRV, MEV and the "volume landmarks"

- **MEV** (minimum effective volume), **MAV** (maximum adaptive volume) and **MRV** (maximum
  recoverable volume) are coaching constructs popularised by RP/Israetel, not validated
  individual measurements:
  [RP volume landmarks](https://rpstrength.com/blogs/articles/training-volume-landmarks-muscle-growth).
- There is no validated test that measures an individual's MRV. The landmarks are useful as
  **configurable guardrails and vocabulary**, not as measured thresholds.
- The programme therefore uses broad pattern-level ranges, not a precise per-muscle MRV.

### Deloads and autoregulation

- A 2026 randomised within-subject deload trial in untrained young men examined hypertrophy and
  strength endurance after a deload; this is a narrow population and does not establish a
  general deload schedule
  ([Scientific Reports 2026](https://link.springer.com/article/10.1038/s41598-026-40612-5)).
- Autoregulation has not consistently beaten a well-designed fixed programme. A trial in
  trained men found no additional benefit from autoregulation within a mixed periodised plan
  ([autoregulation trial](https://cris.unibo.it/retrieve/handle/11585/1050402/6abdb23c-cb15-4062-95dd-bafaf9f659aa/autoregulation_does_not_provide_additional.2-1.pdf); [Examine summary](https://examine.com/research-feed/study/1agVB9/)).
- Therefore the implementation is **conservative**:
  - a ledger reports under/within/high/over;
  - a cap trims **non-essential** sets only when the recent week plus the proposed session is
    above the configured MRV;
  - under-MEV is reported; a separate accessory-only rule adds one set after three weeks below
    MEV (`MOD-VOL-002`);
  - the readiness set valve remains a separate recovery rule.

---

## 2. Landmarks in this programme

Configured in [`config/volume.v1.yaml`](../config/volume.v1.yaml). They are broad, pattern-level
defaults and are `ASSUMPTION-31`.

| pattern | MEV | MAV | MRV |
|---|---:|---:|---:|
| squat | 6 | 8–12 | 14 |
| hinge | 6 | 6–9 | 10 |
| hinge unilateral | 0 | 0–6 | 8 |
| knee flexion | 3 | 4–8 | 10 |
| horizontal push | 8 | 10–16 | 18 |
| vertical push | 3 | 4–8 | 10 |
| horizontal pull | 4 | 6–10 | 12 |
| vertical pull | 3 | 4–8 | 10 |
| core | 3 | 4–9 | 12 |

Why these values:

- they sit around the broad dose-response ranges, with a lower hinge MRV because the hinge is
  the highest spinal-cost pattern and the athlete has a back history;
- unilateral hinge and core have lower MEV because they are accessory patterns;
- knee flexion is the row added on 2026-10-28 (`DEC-KNEEFLEX-01`, `ASSUMPTION-50`): MEV 3
  is a maintenance floor, and the 6-set weekly target is what the two template exposures
  (squat + hinge, 3 sets each) supply, so no third lower-body day is needed;
- horizontal push has a higher MRV because it is the largest current strength emphasis;
- none of these is an individual measurement.

The ledger reports the **average per week over the window**, not one session's set count.

---

**Programme adjustment (2026-10-20):** the squat-emphasis SSB is 5×3–5, bench+squat squat
support is 4×3–5, and trap-bar hinge is 5×3–5. Planned weekly squat volume is ~7 sets and heavy
hinge ~5 sets; the back-extension and single-leg RDL doses are unchanged. This came from the
review decision `DEC-PROGRAMME-04`, not from a new MRV estimate.

**Later amendment (2026-10-25, `DEC-SPINE-05`):** the bench+hinge support is a 3×3–5 sumo
deadlift at spinal cost 2.5, replacing the single-leg RDL. The paragraph above is the 2026-10-20
snapshot; current weekly volume is in `docs/STRENGTH-PROGRAM-REVIEW.md`.

## 3. Implemented behaviour

### Ledger

`features/volume.py` counts working sets by pattern over the configured window and returns:

- weekly counts, total, average (for that raw pattern) and `group_average` (for its landmark);
- MEV, MAV, MRV;
- status: `under`, `within`, `high`, `over`, `untargeted`, judged on the **landmark group**.

The status belongs to the group, not the row (`DEC-VOLUME-05`). Several raw patterns share one
landmark — `core_anti_extension` and `core_flexion` both count as `core`, `squat_unilateral`
counts as `squat` — and judging a sub-pattern on its own against the merged landmark lets a
pattern that is low add volume to a sibling that is already trained. `erector_extension` has
no landmark at all: direct erector work is dosed by `PRG-EREC-001` and capped by
`PRG-SPINE-001`, never by MEV/MRV.

Exposed as:

```bash
strength-coach volume --weeks 4 --date 2026-10-20
```

and the **Weekly volume** panel on Prescribe / `GET /api/volume`.

### MRV cap

Before validation, the engine adds the prior seven days' working sets for each pattern to the
proposed session. If the total exceeds MRV:

- non-essential items in that pattern lose one set at a time until the total is at or below MRV;
- essential items are never cut automatically;
- if only essential work remains above MRV, the prescription warns and leaves the decision to
  the athlete;
- changed items cite `MOD-VOL-001`.

This is not a per-muscle measurement and not a deload. It is a guardrail against accidental
volume stacking.

### Under-MEV

When a pattern **group** is below MEV across the configured three-week window, the engine adds
**one accessory set** to the first non-essential item in that group (`MOD-VOL-002`), up to the
configured per-item maximum. Main lifts are never increased by this rule. The MRV cap runs
afterwards, so the result still cannot exceed the weekly ceiling.

"Group" matters: before `DEC-VOLUME-05` the rule read a raw pattern's status but matched items
by landmark key, so a low `core_flexion` added a set to a well-trained `ab_wheel` on every
squat day, and a low `squat_unilateral` added a set to `split_squat` on every hinge day. The
set never reached the pattern that was actually under, so the rule re-fired indefinitely.

This is a small deterministic progression, not an individual MRV or an experiment.

**Precedence (`DEC-VOLUME-33`):** an item that readiness reduced this session is skipped, so
an under-MEV week cannot undo the recovery valve by adding the set straight back. The pattern
simply stays under target for that week. Safety modifiers run after volume elsewhere too (the
spinal trim and the MRV cap), and this keeps that order consistent.

### Readiness valve

The readiness set valve is separate: poor readiness removes one set from accessories and main
lifts only when the athlete explicitly opts in (config `include_essential`, default false); it is editable on the
Readiness page and recorded in the `MOD-FAT-001` warning.

---

## 4. Limitations

- MEV/MAV/MRV are not measured for this athlete; the values are config assumptions.
- The ledger counts hard sets, not effective reps, proximity to failure, load or tonnage.
- The seven-day MRV window is a practical approximation of a week, not an individual recovery
  measurement.
- The cap is asymmetric: it never adds work below MEV and never cuts an essential item.
- The evidence does not support a fixed automatic deload schedule; the scheduled deload is a
  configurable fatigue-management policy (`DEC-PROGRAMME-05`), not a claim of proven superiority.
- Volume management does not itself trigger a deload; the deload policy is separate.
- Frequency is not used to redistribute weekly volume: `programme --sessions-per-week` changes
  which days are projected, not the per-session dose. See
  [FREQUENCY-AND-VOLUME.md](FREQUENCY-AND-VOLUME.md).

---

## 5. What would strengthen this

1. Record a per-pattern RPE/soreness/fatigue response and test whether MRV predicts next-session
   performance.
2. Compare the ledger's under/over states with actual e1RM changes prospectively.
3. Calibrate the landmarks from this athlete's returns before widening them.
4. If deloads are added, test them against a no-deload control rather than assuming benefit.

---

## 6. Sources

- [2025 volume/frequency meta-regression](https://link.springer.com/article/10.1007/s40279-025-02344-w)
- [Schoenfeld 2017 volume dose-response](https://www.tandfonline.com/doi/abs/10.1080/02640414.2016.1210197)
- [RP volume landmarks — coaching construct](https://rpstrength.com/blogs/articles/training-volume-landmarks-muscle-growth)
- [2026 deload RCT](https://link.springer.com/article/10.1038/s41598-026-40612-5)
- [Autoregulation trial](https://cris.unibo.it/retrieve/handle/11585/1050402/6abdb23c-cb15-4062-95dd-bafaf9f659aa/autoregulation_does_not_provide_additional.2-1.pdf)
- [Examine strength-volume summary](https://examine.com/faq/how-much-volume-do-i-need-to-perform-to-increase-muscle-strength/)

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- [VOLUME-MODULATION-PLAN.md](VOLUME-MODULATION-PLAN.md) — proposed weekly target + session cap budget
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
