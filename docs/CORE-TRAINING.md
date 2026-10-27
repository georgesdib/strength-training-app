# CORE TRAINING — is the programme doing enough?

Short answer: **before 2026-10-20 the prescribed programme contained no dedicated core work at
all.** The performed log did (planks, carries, ab wheel, hanging leg raise), so the omission
was in the templates, not in the athlete's practice or equipment. The evidence supported
adding a *small, progressive* block — but it does **not** support claiming that core work
prevents back pain, and it does not justify a large isolation circuit.

The amendment was **approved and applied on 2026-10-20** (`DEC-CORE-01`). In the current
four-session-type programme, the squat-led and bench+squat types carry `ab_wheel`; the
bench+hinge type carries `hanging_leg_raise`. Both progress through `PRG-DP-001`, and the
constitution is at **1.2.0**. This note keeps the evidence and the reasoning; the sections that
describe the gap are written in the past tense where the change has landed.

Decisions/assumptions: `DEC-CORE-01`, `ASSUMPTION-23`. Config:
[`config/templates/session-types.v1.yaml`](../config/templates/session-types.v1.yaml),
[`config/rules/programme.v1.yaml`](../config/rules/programme.v1.yaml). Private detail:
`private/docs/CORE-AUDIT.md` (git-ignored).

---

## 1. What the programme prescribes

| session type | main work | trunk-adjacent work | dedicated core (since 2026-10-20) |
|---|---|---|---|
| squat | SSB squat 5×3-5, bench 4×3-5 | back extension 3×10-12 | **ab wheel 3×6-10** |
| hinge | trap-bar deadlift 5×3-5, narrow/pause bench 4×3-5 | none direct | — |
| bench+squat | bench 4×3-5, competition-squat support 4×3-5 | none direct | **ab wheel 3×6-10** |
| bench+hinge | bench 4×3-5, sumo deadlift 3×3-5 | none direct | **hanging leg raise 3×8-12** |

Before the change, the prescribed week contained **6 sets of back extension** (spinal
extension) and heavy squat/hinge bracing, and **zero anti-extension, anti-rotation, lateral or
carry work**. The taxonomy already carried the movements — `plank` (seconds), `ab_wheel`
(reps), `hanging_leg_raise` (reps), `carry` (seconds), plus synthetic `pattern:core_*` buckets —
but no day template named one and the constitution's accessory collection excluded them. It was
an omission, not a recorded decision: there was no `DEC-*` or open question that said "no core
work".

## 2. What "core work" means here

Five distinct demands, not one:

1. **Anti-extension** — resisting lumbar extension under load (plank, ab wheel, rollout).
2. **Anti-rotation / anti-lateral flexion** — resisting twist and side bend (Pallof, suitcase
   carry, side plank).
3. **Flexion** — actively shortening the trunk (hanging leg raise, sit-up).
4. **Loaded carry** — walking under load with a braced trunk (farmer's, suitcase).
5. **Bracing during compounds** — the squats, hinges and back extensions already train this.

The programme covers (5) and some spinal extension. It does not cover (1)-(4). "Enough" has to
be judged against that coverage, not against a set count alone.

## 3. What the evidence says

### 3.1 Core exercise is not superior to other exercise for low back pain

- A meta-analysis of five trials (414 participants) found core stability exercise better than
  general exercise for pain and disability in the **short term**, but **no significant
  difference at six months** ([Wang 2012](https://doi.org/10.1371/journal.pone.0052082)).
- The Cochrane review of motor control exercise concluded it is better than minimal
  intervention, but **not superior to other forms of exercise**, and that the choice should
  depend on preference, cost and safety ([Saragiotto 2016](https://doi.org/10.1002/14651858.CD012004)).

Implication: there is no evidence-based reason to prescribe *this particular* core programme
to treat or prevent back pain. Any block is justified by capacity and performance, not by a
medical claim.

### 3.2 Exercise does not clearly prevent recurrence of low back pain

A randomised trial in people recently recovered from an episode found a 12-week exercise and
education programme did **not** reduce recurrence compared with an education booklet (63% vs
57%; HR 1.09, 95% CI 0.7-1.8) ([Ferreira 2021](https://doi.org/10.2519/jospt.2021.10187)).

Implication: the injury signal's "tolerated loading" framing stays; core work must not be sold
as back insurance.

### 3.3 Core training does improve athletic performance — modestly

A 2026 meta-analysis of 49 studies reported positive effects of core training on speed
(effect size 0.60) and jumping (0.49) across sports
([Kayantaş 2026](https://doi.org/10.3389/fphys.2026.1946447)). The populations are mostly
athletes and the outcomes are speed/jump, not barbell strength, so this supports *some* core
work for a lifter, not a large one and not a claim about the squat or deadlift.

### 3.4 Trunk endurance is associated with lower overuse-injury risk (observational)

In 545 naval cadets, failing a 60-second prone plank was associated with greater odds of an
overuse injury (OR 3.3, 95% CI 1.2-8.8) ([Lopes 2021](https://doi.org/10.1016/j.jsams.2020.11.020)).
This is a prospective association in a young military cohort, not proof that plank training
prevents injury, and it does not set a target.

### 3.5 Loaded carries load the trunk hard (mechanistic)

Surface EMG during farmer's and suitcase carries showed high bilateral activation of
longissimus, multifidus, rectus abdominis and external oblique, with suitcase carries adding
ipsilateral activation ([Ellestad 2024](https://doi.org/10.70252/nwue9985)). Mechanistic only:
it shows the exercise does what it looks like it does.

### 3.6 Longer planks are more fatiguing, not more productive

In a randomised acute study, only a 3-minute plank produced increases in muscle thickness,
echo intensity and a drop in peak force; 1- and 2-minute holds did not, and perceived effort
rose with duration ([Aleais 2022](https://doi.org/10.70252/rdkt2873)). Mechanistic and acute,
but it argues for **30-60 s holds with added load or leverage**, not for chasing 2-3 minute
planks.

### 3.7 What the evidence does not say

- There is no trial of core training in **this** population (a strength trainee with a history
  of resolved low-back tweaks) measuring lift performance or flare rate.
- There is no validated minimum dose. The dose below is a synthesis and is marked
  `ASSUMPTION-23`.
- No study shows that a specific core exercise is protective, or that omitting core work is
  harmful.

## 4. A defensible dose

For a longevity-first athlete training three days a week, with no current symptoms:

| element | recommendation | basis |
|---|---|---|
| frequency | 2 of 3 sessions (the hinge day stays as it is) | cheap, recoverable, avoids adding fatigue before the heaviest pull |
| volume | 2-3 sets per slot, 4-6 sets/week total | enough for a stimulus; the evidence gives no validated dose |
| coverage | one anti-extension + one anti-rotation/lateral per week | the two demands the compounds do not train |
| holds | 30-60 s; progress by load or leverage | longer holds only add fatigue (§3.6) |
| progression | reps to top of range, then load (ab wheel, leg raise) | existing `PRG-DP-001` logic |
| timing | end of session | never before the main lift; it is accessory work |
| claim | capacity and performance, **not** injury prevention | §3.1-3.2 |

A reasonable instance: **squat-led/bench+squat: ab wheel 3×6-10; bench+hinge: hanging leg
raise 3×8-12.** Both are reps-based, both already exist in the taxonomy, and both can progress
by load or lever.
Planks and carries stay optional/self-directed until a time-based progression rule exists
(see §5.3).

## 5. What changed

### 5.1 Session templates

Core slots were added to the current session types (applied 2026-10-20; the legacy A/C labels
are kept only in the decision history):

```yaml
# squat-led / bench+squat, after the erector slot
- id: core_anti_extension
  exercise: ab_wheel
  sets: 3
  reps: {low: 6, high: 10}
  rir: {low: 2, high: 3}
  rest_s: 90
  essential: false
  load_source: double_progression

# bench+hinge, after the erector slot
- id: core_flexion
  exercise: hanging_leg_raise
  sets: 3
  reps: {low: 8, high: 12}
  rir: {low: 2, high: 3}
  rest_s: 90
  essential: false
  load_source: double_progression
```

### 5.2 Constitution collection

`PRG-DP-001` scopes `$accessories_and_back_extension` and already carried
`increment_kg.per_exercise.ab_wheel: 2.5` — but `ab_wheel` was not in the collection and not in
any template, so that config was dead. Both exercises are now in the collection and the
constitution is at **1.2.0**. Time-based core (plank, carry) is deliberately still excluded.

### 5.3 No new hard rule

A rule like "every session must contain core work" has no evidence base and would be a veto
with nothing to veto — the template either includes the slot or it does not. The guarantee is a
test over the templates, not a constitutional rule. Time-based core (plank, carry) stays out of
`PRG-DP-001` until a progression rule for seconds exists; otherwise "hold until top of range"
would mean "hold longer", which §3.6 argues against.

### 5.4 Adjacent defect: `PRG-DP-001` was never assessable

**Fixed 2026-10-20.** The rule asked for a rep range for every scoped exercise, but `rep_ranges`
was built from the **current day's** template. Each day was missing at least one scoped
accessory (A: `split_squat`, B: `back_extension`, C: `lateral_raise`), so the rule returned
`unknown` on every day and double-progression decisions fell back to "hold load".

- **Cause:** `DayTemplate.rep_ranges()` (`prescribe/templates.py`) was per-day, while the rule
  scope is the whole collection.
- **Fix:** `templates.all_rep_ranges()` pools the map across all four session types; the engine
  passes it to the rule context.

## 6. Recommendation (applied)

1. **Added core work** — two reps-based slots (squat-led/bench+squat anti-extension,
   bench+hinge flexion), 6 sets/week, framed as capacity/performance.
2. **Amended the constitution collection** (`accessories_and_back_extension` gains `ab_wheel`
   and `hanging_leg_raise`; version 1.2.0) so progression is governed by the existing rule.
3. **Fixed the per-day rep-range defect** so `PRG-DP-001` can evaluate.
4. **No new hard rule**, no rubric item, no claim about back-pain prevention.

What would change this: a trial in strength trainees linking core work to lift performance or
flare rate; a validated minimum dose; or a time-based progression rule that makes planks and
carries first-class prescribed work.

## 7. Open questions (resolved)

- Q15: should the programme prescribe core work, and at what dose? **Yes — two slots, as above.**
- Q16: should `PRG-DP-001` build rep ranges from all day templates? **Yes — fixed.**

Both are marked answered in [`OPEN-QUESTIONS.md`](OPEN-QUESTIONS.md).
