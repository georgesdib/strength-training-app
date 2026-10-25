# SPINAL COST — what the ordinal actually rests on

`spinal_cost` is an **ordinal 1-3 weight** used to add up a week's high-fatigue spinal work
against the cap, and to spot stacking. It is not a measurement in newtons, a moment, or an
injury probability. This note records the evidence behind each rating and where the rating is
an assumption.

---

## What is measured in the literature

**Straight bar vs hexagonal (trap) bar.** A biomechanical comparison at submaximal loads found
the hexagonal bar produced **lower peak moments at the lumbar spine, hip and ankle** and a
higher peak knee moment, while allowing a heavier 1RM (Swinton et al., *J Strength Cond Res*
2011, doi:10.1519/jsc.0b013e3181e73f87). That supports a lower spinal cost for the trap bar
than a straight-bar deadlift.

**Conventional vs sumo.** At 85% 1RM, sumo showed greater frontal- and transverse-plane joint
moments and range of motion, while conventional showed greater hip flexion, ankle dorsiflexion
and **greater erector spinae thoracis activation** (Hanen et al., *Front Bioeng Biotechnol*
2025, doi:10.3389/fbioe.2025.1597209). That supports a lower sagittal extensor demand for sumo
than conventional.

**No head-to-head sumo vs trap bar study.** There is no direct comparison of lumbar moments or
erector demand between those two lifts, so their relative rating is not measured.

## The ratings

| lift | cost | basis |
|---|---|---|
| conventional deadlift (straight bar) | **3** | highest peak lumbar moment of the compared barbells (Swinton 2011); most trunk flexion |
| sumo deadlift | **2.5** | lower erector activation and more upright than conventional (Hanen 2025); no sumo-vs-trap measurement, so placed between the trap bar (2) and conventional (3) |
| trap-bar deadlift | **2** | lower peak lumbar moment than a straight bar (Swinton 2011); no sumo-vs-trap measurement |
| back extension | 1 | direct erector work but low absolute load; ordinal judgement |
| RDL / rack pull / good morning | 2-3 | hinge variants; ordinal judgement, not measured |

The **sumo rating of 2.5 is an assumption** (`ASSUMPTION-02`), not a finding. The evidence
shows sumo has lower sagittal demand than a conventional pull, but it does not rank sumo
against the trap bar. The half-step is the programme owner's decision: it records "between the trap bar
and conventional" without pretending to a measured value. Whether a half-step is meaningful on
an ordinal scale is an open question (`OPEN-QUESTIONS.md` Q11).


## Squats are outside the cap — and the variants are not equal

`PRG-SPINE-001` counts hip-hinge and erector-extension work. **No squat variant carries
`high_fatigue_spinal`**, so a squat never consumes one of the three weekly exposures. That is a
**scope decision**, not a finding that a squat loads the spine lightly — and the evidence
available does not rank squat against hinge on lumbar load directly:

- **Back squat vs hexagonal-bar deadlift** (Stahl 2024, n=16). The hex bar allowed a greater
  1RM and produced **greater maximum forward trunk lean** than the back squat; the back squat
  produced higher hip extension moments, with no difference at the knee. Lumbar-spine moments
  were not reported. The finding supports the hinge as the more flexion-loaded pattern — which
  is what the cap targets — but it compares trunk lean and hip/knee moments, not lumbar load.
- **Low-bar vs high-bar** (Glassbrook 2017 review). The low-bar squat has greater hip flexion,
  **greater forward lean** and **greater erector spinae activity**; the high-bar squat is more
  upright, with greater knee flexion and quadriceps activity.
- **Safety-squat bar vs standard bar** (Hecker 2019, n=12 powerlifters). The SSB produced a
  **more upright trunk** (trunk flexion −7.3°, hip flexion −5.7°) at an 11.3% lower 3RM, and
  the authors describe it as placing *less* stress on the lower back.

So the variants sort the opposite way from what a single "squat" flag implies:

| variant | forward lean / erector demand | in the cap? |
|---|---|---|
| safety-squat bar | lowest of the three (more upright) | no — the exclusion is well supported |
| high-bar | intermediate (upright, knee-dominant) | no |
| **low-bar competition squat** | **highest of the three** | **no — this is the questionable one** |

The athlete's competition squat is a **low-bar** squat (athlete statement; the taxonomy has no
bar-position field, so the rating cannot read it). Counting it at cost 1 would put a standard
week — back extension (1) + trap bar (2) + a bench+squat session (1) — at 4 against a cap of 3,
so `MOD-SPINE-001` would drop the erector slot in every week that holds both a hinge and a
bench+squat, or the cap would have to move to 4. That is a programme decision, not a code fix:
see `OPEN-QUESTIONS.md` Q24 and `LIM-44`.

## What would change a rating

- A direct biomechanical comparison of sumo and trap bar at matched relative loads (lumbar
  moment, erector activation, trunk inclination).
- Athlete-specific symptom data: a lift that repeatedly precedes a flare deserves a higher
  effective cost even if the group average says otherwise.
- A change to the cap or the exposure definition, which would require rethinking the bins.

Until then, the ratings are a **conservative ordinal prior**, and the corpus records that
(`docs/SANITY-CHECKS.md`, ASSUMPTION-02).

---

Full bibliography with DOIs: [`docs/REFERENCES.md`](REFERENCES.md).

---

## Focused review: can load be weighted? (2026-10-23)

A focused, non-systematic review of load-dependent spinal kinematics, disc loading, variant
biomechanics and injury/load-management evidence is in
[SPINAL-LOAD-EVIDENCE.md](SPINAL-LOAD-EVIDENCE.md).

**Conclusion:** load clearly changes tissue loading, but there is no validated mapping from
kg/%1RM/RIR/sets to a weekly spinal-risk unit. The ordinal variant ranking stays; load/RIR/set
weighting is **not** added. The best-supported load principle is progressive loading and
avoiding abrupt spikes, not a precise per-session cost.

A separate observational advisory is now implemented: working sets on high-fatigue spinal
exercises at RIR ≤ 1 are counted over the volume window and shown as context. It is not
load-weighted and does not change the cap or prescription.
