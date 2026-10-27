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
| low-bar competition squat | **1** | counted by `DEC-SPINE-05`; most forward lean/erector activity of the squat variants (Glassbrook 2017), but no direct lumbar-load measurement |
| back extension | 1 | direct erector work but low absolute load; ordinal judgement |
| RDL / rack pull / good morning | 2-3 | hinge variants; ordinal judgement, not measured |

The **sumo rating of 2.5 is an assumption** (`ASSUMPTION-02`), not a finding. The evidence
shows sumo has lower sagittal demand than a conventional pull, but it does not rank sumo
against the trap bar. The half-step is the programme owner's decision: it records "between the trap bar
and conventional" without pretending to a measured value. Whether a half-step is meaningful on
an ordinal scale was accepted in Q11 and is no longer open.


## Squats: one counted exception

`PRG-SPINE-001` now counts the **low-bar competition squat** as one high-fatigue exposure
(`DEC-SPINE-05`). The safety-squat bar and high-bar squat remain outside the cap; the
taxonomy has no bar-position field, so this is an explicit per-exercise classification, not a
general squat rule.

The evidence still ranks the variants rather than measuring lumbar load:

- **Back squat vs hexagonal-bar deadlift** (Stahl 2024, n=16). The hex bar allowed a greater
  1RM and produced **greater maximum forward trunk lean** than the back squat; the back squat
  produced higher hip extension moments, with no difference at the knee. Lumbar-spine moments
  were not reported.
- **Low-bar vs high-bar** (Glassbrook 2017 review). The low-bar squat has greater hip flexion,
  **greater forward lean** and **greater erector spinae activity**; the high-bar squat is more
  upright, with greater knee flexion and quadriceps activity.
- **Safety-squat bar vs standard bar** (Hecker 2019, n=12 powerlifters). The SSB produced a
  **more upright trunk** (trunk flexion −7.3°, hip flexion −5.7°) at an 11.3% lower 3RM, and
  the authors describe it as placing *less* stress on the lower back.

| variant | forward lean / erector demand | in the cap? |
|---|---|---|
| safety-squat bar | lowest of the three (more upright) | no |
| high-bar | intermediate (upright, knee-dominant) | no |
| **low-bar competition squat** | **highest of the three** | **yes — cost 1** |

The cap was raised from **3 to 6** at the same time. With the current templates:

- squat (back extension 1) + hinge (trap bar 2) + bench+squat (competition squat 1) = **4/6**
- squat (back extension 1) + hinge (trap bar 2) + bench+hinge (sumo 2.5) = **5.5/6**

The old 3/3 budget could not absorb a counted competition squat or a sumo support lift. The
new cap is a programme-owner decision, not a measured safety threshold; it still treats the
ordinal costs as cardinal values and remains load-blind.

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

**Conclusion (2026-10-23):** load clearly changes tissue loading, but there is no validated
mapping from kg/%1RM/RIR/sets to a weekly spinal-risk unit. The ordinal variant ranking stays;
a precise load/RIR/set model was not added. The best-supported load principle is progressive
loading and avoiding abrupt spikes, not a precise per-session cost.

A separate observational advisory is now implemented: working sets on high-fatigue spinal
exercises at RIR ≤ 1 are counted over the volume window and shown as context.

## Effective-cost policy bands (2026-10-27)

The cap now applies bounded **policy** factors to the ordinal base cost. This is deliberately
not a calibrated equation; the evidence supports direction, not a coefficient.

| working sets | factor |
|---|---:|
| 1–3 | 0.85 |
| 4–5 | 1.00 |
| 6+ | 1.15 |

| mean working %e1RM | factor |
|---|---:|
| < 75% | 0.85 |
| 75–85% | 1.00 |
| > 85% | 1.15 |

`effective cost = base spinal_cost × set factor × intensity factor`

- Warm-ups / RIR 6 are excluded.
- Unknown e1RM uses the neutral 1.00 intensity factor, not a low guess.
- The existing 4–5 set / 75–85% baseline stays at the old cost, so the current normal week is
  not silently re-priced.
- A 12-set trap-bar session costs 15% more, not twelve exposures.
- The cap remains **6** effective points and is configurable in Settings → Spinal (guarded
  table) and in `config/rules/programme.v1.yaml` (`PRG-SPINE-001.params.cap`).
- This is a policy choice recorded by `LIM-14`; it is not a measured threshold or a validated
  load–risk model.
