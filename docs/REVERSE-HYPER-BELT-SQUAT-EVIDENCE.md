# Reverse hyperextension and belt squat — evidence review

**Status:** research note, 2026-10-25. No programme change. Both lifts already exist in the
taxonomy and selection catalogue; neither is a default.

## Question

Are reverse hyperextensions and belt squats beneficial for the athlete’s goals: strength-first
powerlifting, hypertrophy where useful, longevity, and back tolerance?

## Bottom line

**Both can be useful accessories, but neither has direct longitudinal evidence that it improves
1RM strength or prevents injury.**

- **Belt squat:** acute evidence supports a quadriceps demand similar to the back squat with
  substantially lower lumbar/trunk loading. That makes it a plausible lower-spine-load squat
  alternative, not a replacement for the competition squat or a proven injury-prevention tool.
- **Reverse hyperextension:** acute evidence shows strong posterior-chain activation and a high
  low-back moment with less lumbar flexion than a hyperextension. It is a posterior-chain
  accessory that costs spinal exposure; the “decompression” claim is not established by these
  studies.

## 1. Reverse hyperextension

### Direct acute evidence

- Lawrence et al. (2019) compared reverse hyperextension with hyperextension at equivalent load.
  The reverse hyper had greater **low-back moment** (peak +129%, integrated +63%, mean +78%) and
  greater hip ROM, with equivalent erector-spinae activity and less lumbar flexion. The authors
  called the movement profile preferable for hip ROM/angular stress, not “decompression.”
- Cuthbert et al. (2021) found greater peak and mean EMG in erector spinae, gluteus maximus and
  biceps femoris during reverse hyperextension than hyperextension; the authors suggest it may
  be a higher-intensity posterior-chain exercise.
- Lawrence et al. (2022) tested 50%, 100% and 150% bodyweight loads. Erector and gluteus maximus
  activity was greater at 100–150% than 50%, but increasing load did not linearly increase force
  or activation; heavier loads increased hip and trunk flexion.

### What this means

- Good candidate for gluteus/hamstring/erector work without axial bar loading.
- **Not** a free “back decompression” intervention; it produces a meaningful low-back moment.
- The 2019 study did not measure pain, injury, hypertrophy or strength outcomes.
- No longitudinal trial was found showing that reverse hyperextensions reduce back pain, prevent
  injury, or improve competition lifts.

### Current app treatment

- `reverse_hyperextension` is already a canonical entity and an `erector` slot candidate.
- It has `high_fatigue_spinal: true` and `spinal_cost: 1`; it counts toward the weekly spinal cap.
- It is **not** substitutable for back extension and is not a default.

## 2. Belt squat

### Direct acute evidence

- Evans et al. (2017/2019) compared back squat and machine belt squat. Quadriceps activation was
  broadly comparable, but gluteus maximus activation was lower in the belt squat. They also
  produced load-prediction equations; these are not evidence of 1RM transfer.
- Layer et al. (2018) compared isometric back and belt squats. Belt squat increased peak force,
  ankle and knee moments but **decreased low-back moments**; hip moments were unchanged. The
  authors suggest it for people with upper-body or spinal limitations or excessive back moments.
- Joseph et al. (2020) found belt squat reduced lumbar erector, gluteus maximus/medius and trunk
  activation versus back squat, while quadriceps, hamstrings and plantar flexors were broadly
  similar. The authors call it a suitable alternative when low-back/trunk stress should be
  reduced.
- Isometric belt-squat force is reliable/valid against force plates (2024) and has weak-to-moderate
  associations with jump performance (2026); neither establishes strength transfer.

### What this means

- Plausible **quadriceps accessory** or back-sparing squat variation when spinal load is the
  limiting factor.
- It is not equivalent to the back squat: glute/trunk demand is lower, and the load basis is
  different.
- No training study was found showing belt squat improves competition squat 1RM, hypertrophy or
  injury outcomes more than the current squat.

### Current app treatment

- `belt_squat` is already a canonical entity and a squat-slot candidate.
- It is not a default; selecting it requires the explicit selection path and re-solves load from
  its own history.
- It is a different implement/load basis from the SSB or competition squat; do not transfer load
  or treat it as a like-for-like e1RM.

## 3. Goal-by-goal assessment

| goal | reverse hyperextension | belt squat |
|---|---|---|
| 1RM strength | no direct transfer evidence; posterior-chain accessory at best | no longitudinal transfer evidence; quad accessory, not a competition-squat replacement |
| hypertrophy | plausible glute/hamstring/erector accessory; acute EMG only | plausible quadriceps accessory; glute demand lower; acute EMG only |
| longevity / back tolerance | loads the low back and counts toward the cap; “decompression” unproven | lower lumbar/trunk load than back squat in acute studies; useful when spinal load is limiting |
| injury prevention | no evidence | no evidence |
| time / equipment | machine/GHR setup | belt-squat machine setup |
| current programme | optional erector candidate; not default | optional squat candidate; not default |

## 4. Recommendation

1. **Do not add either as a default.** The current programme already has a coherent main-lift and
   accessory structure.
2. **Belt squat** is the more defensible substitution when the goal is quadriceps work with less
   spinal/trunk loading. Keep it explicit and preserve its own load history.
3. **Reverse hyperextension** is a valid posterior-chain accessory, but treat it as spinal
   exposure, not recovery. Keep it inside the weekly cap.
4. Do not use either to “fix” an injury or replace a competition lift without an explicit trial.
5. If either is tested, track the relevant lift, back symptoms and the other main lifts; acute EMG
   is not an outcome.

## 5. What would change the recommendation

- a longitudinal trial showing belt squat improves squat 1RM or hypertrophy versus an equivalent
  back-squat programme;
- a trial showing reverse hyperextension reduces pain/flares or improves posterior-chain strength
  beyond an equivalent accessory;
- individual N-of-1 data showing tolerance and performance benefit without increasing spinal cost.

Until then, both remain **optional accessories**, not evidence-based programme changes.

## Related

- **Injury/exposure:** [INJURY-SIGNAL.md](INJURY-SIGNAL.md)
- **Spinal cost:** [SPINAL-COST.md](SPINAL-COST.md)
- **Selection comparability:** [SELECTION-COMPARABILITY.md](SELECTION-COMPARABILITY.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)