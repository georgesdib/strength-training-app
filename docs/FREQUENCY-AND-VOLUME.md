# FREQUENCY AND VOLUME — what `--sessions-per-week` actually changes

**Status: Q26 closed 2026-10-27; LIM-51 mitigated.** Frequency remains dates-only:
`--sessions-per-week` selects weekdays and keeps the normal per-session template; it does not
scale main-lift sets or create extra sessions. Incomplete/low-volume weeks are handled by the
live volume budget through policy-specific accessory top-up and under-MEV; `preserve` is where
ordinary accessory make-up applies. The reproduced gap and the residual 1/week main-lift
shortfall remain under `LIM-51`.

---

## 1. Reported behaviour, reproduced

On the local database, one-week forecast from 2026-10-26:

```bash
strength-coach programme --weeks 1 --sessions-per-week 1
strength-coach programme --weeks 1 --sessions-per-week 3
```

| frequency | sessions | hard sets in the week | first session |
|---|---:|---:|---|
| 1/week | 1 | **19** | `bench_squat`, 19 sets |
| 3/week | 3 | **61** | `bench_squat`, 19 sets — identical |

The first projected session is identical in exercise identity, sets, reps, loads and warning
count. The only difference is that two dates are absent. So `1/week` delivers about one third
of the weekly hard sets with the same per-session dose; it is not a volume-equivalent plan.

The one-week pattern split makes the size of the gap concrete:

| pattern | 1/week | 3/week | configured MEV |
|---|---:|---:|---:|
| squat (incl. `squat_unilateral`) | 4 | 13 | 6 |
| horizontal push | 4 | 12 | 8 |
| hinge | 0 | 5 | 6 |
| horizontal pull | 4 | 12 | 4 |
| core | 3 | 6 | 3 |

At 1/week, squat and horizontal push are below MEV every week, and the hinge is not trained at
all in the example week.

## 2. Why it behaves that way

`features/programme.py` chooses dates with `WEEKDAYS[:per_week]` and then runs the same
deterministic engine per date. Nothing reads `per_week` afterwards. The module docstring says
this is deliberate: *"The programme is the existing three-session full-body rotation; a
different frequency would need a scheduling decision, not a silent guess."*

That is a defensible engineering default, but the flag is exposed in the CLI and the web API and
is not explained in `USER-GUIDE.md`, so the natural reading — "1 day a week will pack the week
into one session" — is wrong. This is a documentation/UX gap first and a programming question
second.

## 3. What volume logic exists, and what it reacts to

| mechanism | input | effect | reacts to chosen frequency? | reacts to one short/heavy session? |
|---|---|---|---|---|
| weekly ledger (`features/volume.py`) | stored hard sets, 4-week window | report only (under/within/high/over) | no | no |
| MRV cap (`MOD-VOL-001`) | stored 7-day pattern sets + proposed session | trims non-essential sets when the total exceeds MRV | only indirectly (fewer sessions → fewer stored sets) | only if the 7-day pattern total crosses MRV |
| under-MEV (`MOD-VOL-002`) | stored sets over 3 weeks | +1 accessory set to the first non-essential item, max 8 | only after 3 stored weeks | no |
| readiness (`MOD-FAT-001`) | today's sleep/energy/score | load/RIR, optional set cut | no | no — it is next-day state, not prior volume |
| deload | schedule or two-week spinal/flare triggers | −1 set, −10% load, +1 RIR | no | no — "heavy" is not a trigger |
| continuity (`MOD-GAP-001`) | gap since the last session | load/RIR ramp | no | no |
| attendance | profile target | report only | no | no |

Three consequences matter:

1. **The forecast cannot see itself.** `build_programme` loads stored history once and passes it
   to every projected date; projected sessions are never added to the ledger. A six-week
   1/week forecast therefore never "notices" its own low volume, and under-MEV cannot react to
   it.
2. **No rule consumes "the last session was short or heavy".** `session.flags` marks an
   incomplete workout, but `prescribe/` never reads it. There is no volume-debt or
   make-up concept anywhere in the codebase.
3. **The automatic path cannot restore main-lift volume.** Under-MEV is accessory-only by
   design (`_apply_under_mev`), so the squat deficit in a 1/week week cannot be fixed by it
   even after three weeks; the only main-lift set change is the opt-in readiness valve.

## 4. The expectations, against the evidence

### 4.1 "Fewer sessions should redistribute weekly volume"

Weekly volume is the currency. The 2025 dose-response meta-regression (67 studies, 2058
participants) found a 100% posterior probability that both hypertrophy and strength increase
with weekly volume, with diminishing returns (strength's returns diminish considerably sooner):

> https://doi.org/10.1007/s40279-025-02344-w

Frequency looks mostly like a *distribution* variable:

- **Hypertrophy, volume-equated:** Schoenfeld 2016 found twice-weekly per muscle superior to
  once-weekly, with 3× vs 2× unresolved
  (https://doi.org/10.1007/s40279-016-0543-8). The 2025 model could not distinguish a frequency
  effect on hypertrophy from zero.
- **Strength, volume-equated:** Grgic 2018 found no significant frequency effect in
  volume-equated studies, with the overall frequency effect driven by volume
  (https://doi.org/10.1007/s40279-018-0872-x). The 2025 model still found a positive frequency
  slope for strength after fractional volume adjustment.

These two are not fully consistent: the 2025 analysis is much larger and adjusts for fractional
volume, while Schoenfeld compared 1 vs 2 vs 3 directly. Neither supports treating a 1/week plan
as equivalent once weekly volume drops.

So the honest reading is: **volume first, frequency second, and training a muscle once a week is
the weak end of the range.** A 1/week full-body programme at the normal per-session dose is not
a defensible compression of the 3/week programme — but the fix is a *weekly dose decision*, not
a per-session feedback rule.

Can the 61 sets simply be packed into one session? The acute-fatigue review of 51 studies found
total volume, proximity to failure and set duration to be the main determinants of
performance impairment and perceived fatigue after resistance training
(https://doi.org/10.1519/JSC.0000000000005194). That does not forbid a high per-session dose; it
does mean a 3× compression carries a fatigue cost that no study shows is equivalent.

### 4.2 "A short session should make the next one bigger"

No trial was found that tests compensating a missed or truncated session by adding volume to the
next one; the search returned coaching articles and detraining studies, not interventions. The
volume dose-response is expressed **per week**, and the app's own weekly ledger already reports
the shortfall. Short cessation evidence (two weeks in trained sprinters: eccentric knee strength
−15%, concentric 60°/s −0.7%, 300°/s −5.9% — https://doi.org/10.1371/journal.pone.0288344) says
a short gap matters, but it is a continuity problem, not a make-up-volume protocol.

Automatic compensation would also need a rule nobody has validated: how much, on which lift,
after how short a session, and with what cap. The W6 readiness audit already found that
readiness-driven volume changes are not identifiable retrospectively
([READINESS-AUDIT.md](READINESS-AUDIT.md)), and main-lift set reduction was made opt-in for the
same reason (`DEC-READINESS-12`).

### 4.3 "A heavy session should make the next one smaller"

A narrow version already exists: the MRV cap adds the stored 7-day pattern sets to the proposed
session and trims non-essential sets if the total exceeds the configured MRV. It never cuts an
essential item. It counts **hard sets**, not load, tonnage, RIR or session RPE, so a "heavy" low-rep
session only matters through the sets it contained.

Beyond that, recovery is handled by readiness (next-day state), reactive deload (two
consecutive weeks over the spinal cap, or two consecutive flares) and continuity. There is no
evidence that session-to-session volume autoregulation improves outcomes; the autoregulation
trials are load-based and have not clearly beaten a fixed programme
([Hickmott 2022](https://doi.org/10.1186/s40798-021-00404-9); the mixed-periodisation trial in
[VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md) §1). A general "cut after heavy" rule would be an
unvalidated new policy.

## 5. Options (none implemented)

**A. Dates-only, made honest (recommended now).** Document that the flag selects days, add the
weekly-volume consequence to the user guide, and keep the register entry. No prescription change,
no new evidence claim. This is the only option that is purely documentation.

**B. Frequency-aware weekly dose.** When `per_week < 3`, scale per-session sets toward a
weekly target (bounded by a session cap and MRV), so a 1/week plan is a genuinely different
prescription rather than a truncated one. This is now specified in
[VOLUME-MODULATION-PLAN.md](VOLUME-MODULATION-PLAN.md), including the settings/modality layer it
must sit behind. It is still a programme change: it alters sessions at 1–2/week, needs its own
`DEC`, and should start with accessories rather than main lifts.

**C. Completion-based nudge.** Add one accessory set next session when the last session completed
less than a configured fraction of planned working sets (capped, opt-in, new modifier id). The
evidence does not support it; it would be an experiment, and the app has already declined the
analogous automatic main-lift volume change.

**D. Remove or rename the flag.** If frequency-aware dosing is not wanted, `--sessions-per-week`
could become `--project-days` or disappear, so it cannot be read as a volume promise.

Recommendation: **A now; B only if the athlete actually intends to train 1–2×/week and wants the
weekly dose preserved; C only as a pre-registered, opt-in experiment; D if B is rejected.**

## 6. What would change this

- A prospective record of completed versus planned working sets per session, so the "short
  session" condition is measurable at all (today the flag exists but the rule does not).
- Prospective evidence that a volume nudge after a short session changes an outcome, not just
  the next session's set count.
- A frequency-aware template decision from the athlete, which is programming, not inference.

## 7. Sources

- 2025 volume/frequency meta-regression — https://doi.org/10.1007/s40279-025-02344-w
- Schoenfeld 2016, frequency and hypertrophy — https://doi.org/10.1007/s40279-016-0543-8
- Grgic 2018, frequency and strength — https://doi.org/10.1007/s40279-018-0872-x
- 2025 acute-fatigue review (proximity to failure, intensity, volume) —
  https://doi.org/10.1519/JSC.0000000000005194
- Yamashita 2023, two weeks of training cessation — https://doi.org/10.1371/journal.pone.0288344
- Hickmott 2022, autoregulation — https://doi.org/10.1186/s40798-021-00404-9

## Related

- [VOLUME-MANAGEMENT.md](VOLUME-MANAGEMENT.md) — ledger, landmarks, MRV cap, under-MEV
- [TRAINING-GUIDELINES.md](TRAINING-GUIDELINES.md) §2 — frequency summary
- [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) Q26
- [LIMITATIONS-REGISTER.md](LIMITATIONS-REGISTER.md) LIM-51
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
