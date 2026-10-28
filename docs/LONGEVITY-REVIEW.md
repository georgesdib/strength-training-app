# LONGEVITY REVIEW — do the training modalities match the goal?

The athlete's primary goal is **longevity**, with **strength** as the tie-breaker, a
configured weekly session count and session ceiling, and a recorded injury history. This
review asks a different question from the programme audit: not "are the lifts correct?" but
"are the *modalities* that matter for a long, capable life present at all?"

Short answer: **the resistance-training half is strong and already above the dose associated
with lower mortality; the aerobic half was absent, and power and assessment are still missing.**
Adding more lifting is not the answer — cardio and a small amount of power/upper-back work are.

Status (2026-10-20): **cardio capture**, the **pulling slot** and the **power slot** have been
applied (`DEC-CARDIO-01`, `DEC-PULL-01/02`, `DEC-POWER-01`); the cardio prescription and the
assessment metrics remain proposals. This document keeps the evidence and the reasoning; the sections below say
what has landed.

---

## 1. What the evidence says matters

| modality | key evidence | size of effect |
|---|---|---|
| **Resistance training** | Muscle-strengthening activity is associated with **10-17% lower all-cause mortality**, with the largest reduction around **30-60 min/week** (J-shaped) ([Momma 2022](https://doi.org/10.1136/bjsports-2021-105061)) | moderate; plateau above ~60 min/week |
| **Cardiorespiratory fitness** | Each **1-MET** higher fitness = **13% lower** all-cause mortality ([Kodama 2009](https://doi.org/10.1001/jama.2009.681)); elite vs low fitness HR **0.20**, no upper limit of benefit ([Mandsager 2018](https://doi.org/10.1001/jamanetworkopen.2018.3605)) | **largest single modifiable signal** |
| **Aerobic + strength combined** | Combined activity is associated with lower mortality than either alone ([Momma 2022](https://doi.org/10.1136/bjsports-2021-105061)); guidelines: 150-300 min moderate or 75-150 min vigorous + 2+ strengthening days ([WHO 2020](https://doi.org/10.1136/bjsports-2020-102955)) | large, dose-dependent |
| **Power / explosive work** | Power training modestly improves physical function vs traditional strength training in older adults (SMD 0.30, low certainty) ([Balachandran 2022](https://doi.org/10.1001/jamanetworkopen.2022.11623)); larger gains in muscle power and activity tests ([El Hadouchi 2022](https://doi.org/10.1186/s11556-022-00297-x)) | small-moderate; cheap to add |
| **Balance / falls** | Balance and functional exercise reduces the number of people who fall by about **22%** (RR 0.78) ([Sherrington 2019](https://doi.org/10.1002/14651858.CD012424.pub2)) | large, but evidence is in **60+** |
| **Grip strength** | Higher grip strength is associated with lower all-cause and cause-specific mortality ([Celis-Morales 2018](https://doi.org/10.1136/bmj.k1651)) | prognostic **marker**, not a proven training target |
| **Intervals for fitness** | 4×4 min at 90-95% HRmax improved VO2max more than the same work at moderate intensity ([Helgerud 2007](https://doi.org/10.1249/mss.0b013e3180304570)); sprint intervals added to lifting did **not** blunt strength and raised VO2max (SMD 0.78) ([Ferraro-Farro 2026](https://doi.org/10.1055/a-2820-4527)) | large for fitness; interference minimal at this dose |
| **Protein** | ~**1.6 g/kg/day** maximises resistance-training gains; more adds nothing ([Morton 2018](https://doi.org/10.1136/bjsports-2017-097608)) | nutrition, outside the app |

Two conclusions follow immediately:

1. **The programme's lifting dose is not the problem.** Three sessions at the 80-minute planned
   ceiling is far above the 30-60 min/week associated with the mortality benefit. The J-shape means
   adding lifting volume for longevity is not supported; the existing volume is for strength
   and is reasonable for that.
2. **Cardiorespiratory fitness is the biggest missing lever.** It is the strongest modifiable
   predictor in the evidence, and before 2026-10-20 the app captured **no cardio at all**. Capture now exists
   (`cardio_log`, CLI, Cardio page); a prescription and fitness estimate do not.

## 2. What the programme actually contains

| quality | prescribed? | evidence that it matters | verdict |
|---|---|---|---|
| Maximal/strength | yes: squat, bench, hinge 1-2×/week, RIR 1-4 | strong for strength; mortality benefit already exceeded | **covered** |
| Hypertrophy/accessory | modest: 6-9 sets/week | supports strength and lean mass | **adequate, not a priority** |
| Aerobic base / VO2max | **captured, not prescribed** | strongest longevity signal | **capture done; prescription missing — priority 1** |
| High-intensity intervals | **no** | efficient VO2max gain, minimal interference | **missing — priority 1** |
| Power / explosiveness | **yes: `box_jump` on Day A** | modest function benefit; declines with age | **covered (2026-10-20)** |
| Pulling (vertical/horizontal) | **yes: `pull_up`/`lat_pulldown` on Day B** | structural balance, shoulder/upper-back; no mortality claim | **covered (2026-10-20)** |
| Grip / loaded carry | **no** | grip is prognostic; carries load the trunk | **optional — priority 3** |
| Balance | **no** | falls prevention in 60+ | **age-dependent — priority 3** |
| Mobility / stretching | no | no injury-prevention evidence as a standalone | **not needed** |
| Assessment (VO2max, grip, sit-to-stand, steps) | **no** | you cannot track what you do not measure | **missing — priority 2** |

The programme is also **narrower than the athlete's actual practice**. The log shows rows,
pull-ups, vertical pressing, jumps, calf work and carries that no template prescribes; the
engine therefore cannot progress, critique or protect what is already being done. That is a
product gap as much as a training one.

## 3. Ranked recommendations

### 3.1 Cardio — the highest-value addition

**Target:** accumulate **150-300 min/week of moderate activity or 75-150 min of vigorous**,
plus the existing two-to-three lifting sessions (WHO 2020). A practical structure for three
lifting days:

- **2 × 30-40 min zone 2** (conversational pace; bike, rower, incline walk, easy run) on
  non-lifting days or after lifting;
- **1 × 4 × 4 min at 90-95% HRmax** (3 min easy between), once a week, **not** immediately
  before a heavy lower-body session;
- start at the current fitness level and add 10% per week; walking counts.

**Why not more:** the mortality benefit is dose-dependent but flattens; the goal is a high
fitness floor, not endurance sport. The interference literature supports this dose alongside
lifting ([Ferraro-Farro 2026](https://doi.org/10.1055/a-2820-4527)).

**What the app needs first:** cardio capture (modality, duration, HR, sRPE), then a
prescription and a fatigue model. That is ROADMAP §4.13. **Capture is done** (2026-10-20):
`cardio_log`, `strength-coach cardio`, the Cardio page and `GET/POST /api/cardio`. The
prescription and fatigue model are still open, and the injury signal still cannot see
running/cycling load.

### 3.2 Power — one small slot (applied)

**Applied 2026-10-20:** Day A opens with `box_jump` 3×3-5, RIR 4-5, full recovery
(`DEC-POWER-01`). It is excluded from undulation and carries no double-progression citation.

**Later amendment 2026-10-27 (`DEC-POWER-02/03`):** the power item is quality-limited. It has
no RIR target; the stop rule is stored as `quality_stop` and shown in the prescription, API and
UI. The lift, dose and placement are unchanged.

**Target:** 1-2×/week, **2-3 sets of 3-5 reps**, maximal intent, full recovery, stop when
velocity drops. Put it **before** the main lift on a non-hinge day (e.g. Day A or C), or as
its own short block.

**Options with the available equipment:** trap-bar jump (light), box jump, broad jump,
medicine-ball throw if available. The log already contains jump work, so the movement is
familiar.

**Caveat:** the strongest evidence is in adults 60+; for a younger lifter the benefit is
plausible but not established. It is cheap, low-fatigue, and does not replace strength work.

**Why it needed a taxonomy entity:** a synthetic `pattern:power_jump` cannot be prescribed
safely because synthetic ids carry no taxonomy entity, so the engine cannot tell it is
bodyweight. `box_jump` is now a real entity; it is the only canonicalised jump, while other
jump variants stay synthetic.

### 3.3 Pulling — balance the pressing (applied)

**Applied 2026-10-20:** Day B prescribes a vertical-pull slot, `pull_up` **or**
`lat_pulldown` 3×6-10 (`DEC-PULL-01`, `DEC-PULL-02`); the engine picks whichever was trained
most recently. A horizontal row remains self-directed; the athlete already trains both.

**Target:** 2-3 sets of 8-12, twice a week: pull-up / chin-up (bodyweight or added load) and
a row (barbell, dumbbell, cable or inverted).

**What it fixes:** the programme currently has **no pull at all** — three pressing slots
(bench ×2-3, lateral raise) against zero pulling, which is an unbalanced upper-body
prescription regardless of mortality evidence. It also gives the grip and upper back the
longevity argument cannot supply on its own.

### 3.3a Knee-flexion hamstrings — applied 2026-10-28

**Applied 2026-10-28 (`DEC-KNEEFLEX-01`):** the squat and hinge sessions now carry
`lying_leg_curls` 3×8-12 at RIR 2-3 (with `nordic_curl` as an opt-in selection candidate),
and `knee_flexion` is a managed ledger key with a 6-set weekly target.

**What it fixes:** the hinge is hip-dominant, so the hamstrings' knee-flexion function was not
trained by any template. For a strength-and-longevity goal that is the one accessory-side gap
worth closing: hamstrings are the most commonly strained muscle in strength sport, the Nordic
curl roughly halves injury rates, and knee-flexion strength supports walking, stairs and
stumble recovery. It is accessorised, not a new emphasis: 6 sets/week, no spinal cost.

**Still not prescribed:** calves, grip/loaded carry, rear delt/external rotators, direct arm
work and balance. Those remain accepted coverage gaps (`LIM-54`), not oversights to close
silently.

### 3.4 Assessment — make the goal measurable (applied)

**Applied 2026-10-20 (`DEC-MEASURE-01`):** the `measure` command and Measures page record
periodic outcomes in an append-only table, with direction declared once. The default
catalogue is:

Add optional, low-burden measures so the programme can be judged against its own objective:

- **VO2max estimate** (submaximal step test or 1.5-mile/2-km test) every 8-12 weeks;
- **grip strength** (dynamometer) — prognostic marker;
- **5× sit-to-stand** and **30-s chair stand** — function/power;
- **steps/day** and **sitting time** — context, not a prescription.

None of these changes a load. They answer "is the longevity programme working?" in a way an
e1RM cannot.

### 3.5 Balance and loaded carries — optional, age-dependent

Balance training has good falls evidence in adults 60+, and almost none in younger lifters.
Include it if the athlete is over ~60 or reports unsteadiness; otherwise treat it as optional.
Carries are already performed and load the trunk; one carry slot (3×30-40 s) is a reasonable
optional addition, but grip strength is a **marker**, not a proven target — do not sell it as
mortality reduction.

### 3.6 What not to add

- **More lifting volume** for longevity: the mortality association plateaus around 30-60
  min/week; the current programme is far above it.
- **More core work**: just added, and the evidence does not support a larger block.
- **Stretching as injury prevention**: no standalone evidence; keep mobility specific to the
  lifts if needed.
- **A single "fatigue score"** for cardio plus lifting: the two exposures have different
  fatigue signatures (ROADMAP §4.13).

## 4. What is outside the app's scope

Nutrition (protein ~1.6 g/kg/day, [Morton 2018](https://doi.org/10.1136/bjsports-2017-097608)),
sleep, alcohol and smoking are large longevity levers but are **not training prescriptions**.
The app should say so once and not pretend to coach them; a food or sleep log would be a
different product with its own data-quality problems.

## 5. Sequence (1 and 3 applied)

1. **Cardio capture** (ROADMAP §4.13): table, CLI/web entry, display; no prescription change.
   **Done 2026-10-20.**
2. **Cardio prescription** after capture exists: a weekly target and one interval session,
   config-driven, with injury links for running/cycling.
3. **Pull slot**: `pull_up` (or a row entity) on Day B or C — small, no new taxonomy needed.
   **Done 2026-10-20:** vertical-pull variant slot (`pull_up` / `lat_pulldown`) on Day B.
4. **Power slot**: needs a real taxonomy entity (e.g. `box_jump`) and a placement decision.
   **Done 2026-10-20:** `box_jump` 3×3-5 first on Day A.
5. **Assessment metrics**: optional, no load effect. **Done 2026-10-20:** `measure` + Measures page.
6. **Balance/carry**: only with an age/needs trigger.

## 6. Open questions

- Q17: should the programme add a pulling slot, a power slot, or both, and where?
  **Applied:** pulling variants and power.
- Q18: which longevity assessment metrics should the app record, and how often?

Cardio scope is Q14 and ROADMAP §4.13. This review only ranks the priorities.

## 7. Limitations

- Most mortality evidence is observational; effect sizes are associations, not proof that
  adding the modality causes the benefit.
- The power and balance trials are in older adults; the athlete's age is not recorded, so the
  recommendation is age-conditional.
- The cardio dose is a guideline synthesis, not an individual prescription; it needs the
  athlete's current fitness and preferences, neither of which is in the app yet.
- Nothing here changes the constitution. The strength methodology remains the source of truth.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
