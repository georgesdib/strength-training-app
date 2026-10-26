# INJURY SIGNAL — from a symptom number to a decision the athlete can inspect

The app records a 0-3 symptom level per region. That number alone is not a recovery status:
it says how today feels, not whether a tissue has tolerated training. This document explains
what the injury signal does with the number, what evidence stands behind each choice, and
where the model is coarse on purpose.

It replaces the single back-progression summary described in the earlier version of
[CONTINUITY.md](CONTINUITY.md) §2. Decisions: `DEC-INJURY-01`, `DEC-INJURY-02`,
`DEC-INJURY-03`, `DEC-SYMPTOM-03`. Config: [`config/injuries.v1.yaml`](../config/injuries.v1.yaml).
Code: [`strength_coach/features/injury_signal.py`](../strength_coach/features/injury_signal.py).

> **This is not medical clearance.** A symptom-free streak is weak positive evidence. The
> signal may suggest reviewing a suitability rating; it never sets one, never clears a
> constraint, and never substitutes a lift.

---

## 1. One general signal, one per region

The athlete asked for a general signal plus a per-injury signal, starting with **low back**,
**biceps** and **knee**, with more injuries addable later. The shape is therefore:

- a **general** status, the worst of the regions (a live flare outranks a review suggestion,
  which outranks monitoring, which outranks "no data");
- one **region signal** each, with its own streak, its own window and its own tolerance count.

Regions are configuration, not code. Adding an injury means appending a block to
`config/injuries.v1.yaml` and logging against it with `strength-coach symptom --region`.
The region name is the same string written to `symptom_log.region`.

The per-region summary is what the athlete reads. It deliberately carries the numbers it used
(window, required sessions, tolerated vs loaded) so it can be argued with.

The signal is **history**, not permission. The veto mechanism is still `athlete_constraint`
(`severity = hard_exclude`) plus `exercise_suitability`; a `review` here never edits either.
An injury can therefore exist in three places without contradiction: a constraint (what is
forbidden), a suitability rating (what the athlete will do), and a signal (what the loading
history shows).

---

## 2. What "tolerated loading" means

This was the open question. There are three candidate definitions, and only the third is
honest.

**(a) Any loading counts.** This is the weakest option. It credits a month of training at any
intensity and cannot distinguish a hard hinge session from a warm-up. It also rewards the
behaviour the signal is meant to check, not the response to it.

**(b) Loading above a minimum dose counts.** Necessary but not sufficient. A region is
"loaded" when the session's work sets on linked exercises reach a threshold: direct loading
weighs 2, indirect 1, and the default threshold is 2. So one direct set, or two indirect
sets, makes a session count. This stops a single unloaded set from being evidence, but it
still says nothing about whether the loading was *tolerated*.

**(c) Loading followed by evidence of no flare counts.** This is the definition used. A
loaded session is **tolerated** only when:

1. the session loaded the region at or above the minimum dose, and
2. a symptom reading for that region exists in the **7 days after** the session, and
3. **no reading in that window is a flare**.

A session with no follow-up reading is **unverified**. It is counted and displayed, but it
never satisfies the review requirement. Missing input is `unknown`, not `pass`
(AGENTS.md invariant 12) — the same rule that makes an empty symptom log `unknown` rather
than "no flare".

Two consequences are deliberate:

- **A pre-session log on the next training day is enough.** It is the natural logging
  cadence, and it reflects the state after the previous session. The window is 7 days so a
  normal week of training self-verifies.
- **A flare in the window disqualifies the session even if a later reading is clean.** A
  flare that appears the next day is evidence the load was too much; waiting it out does not
  make the session tolerated.

### What this definition cannot tell you

- **It is not adaptation.** Symptoms can stay quiet while tissue adapts, and can flare while
  tissue is adapting normally. The signal measures *symptom response to load*, not healing.
- **The readings are self-reported and unblinded.** There is no sham control and no clinician
  in the loop.
- **A late flare is invisible.** A reaction that appears after the 7-day window is attributed
  to something else.
- **It inherits the scale's coarseness.** A 0-3 scale cannot reproduce the pain-monitoring
  rules used in tendinopathy rehabilitation (which work on a 0-10 scale and a 24-hour
  response). The app therefore uses the direction of the response, not a pain ceiling.

The evidence for pain-guided rather than rest-based progression comes from tendinopathy, not
from the low back: in a randomised trial of 38 patients with Achilles tendinopathy, continuing
tendon-loading activity under a pain-monitoring model produced no worse outcomes than six
weeks of active rest ([Silbernagel 2007](https://doi.org/10.1177/0363546506298279)). For
patellofemoral pain, a 12-week programme built on activity modification, load management and
pain monitoring produced 86% treatment success at 12 weeks and 81% at 12 months in 151
adolescents ([Rathleff 2019](https://doi.org/10.1177/0363546519843915)). Neither trial is
about back pain, and neither validates a 7-day verification window; the window is a
design choice (`ASSUMPTION-09`).

---

## 3. Why the window scales with prior flares

Four weeks was never a finding. It is now the **base**, and it grows with the number of
previous flares for that region:

```
window_days      = min(28 + 14 × prior_flares, 84)
tolerated_needed = min( 4 +  2 × prior_flares, 12)
```

`prior_flares` counts flares **before** the one that started the current streak. The flare
that ended the streak is the event being recovered from, not evidence of a recurring problem.

The evidence for scaling is reasonably direct. In a prospective inception cohort of 250 people
who had recovered from an episode of low back pain, 69% (95% CI 62-74) had a recurrence within
12 months, median time to recurrence 139 days, and **more than two previous episodes predicted
recurrence** (p < 0.01), along with awkward postures and more than five hours of daily sitting
([da Silva 2019](https://doi.org/10.1016/j.jphys.2019.04.010)). A 2025 cohort found 38%
recurrence ([Huang 2025](https://doi.org/10.1002/ejp.4793)).

So a prior-episode count is a real risk marker, and a fixed certificate for everyone
over-states recovery for the person who flares repeatedly. The **size** of the step (14 days,
2 sessions) is not measured (`ASSUMPTION-08`): the literature gives a direction and a
predictor, not a dose-response curve for required symptom-free time.

There is also no evidence that *any* fixed symptom-free period means tissue clearance. The
window is a prompt to look, not a threshold of healing.

---

## 4. Linking an injury to the lifts that load it

The athlete asked to cross-check the injury against exercise selection: link the injury to the
lift. Every region therefore declares which exercises load it, by canonical taxonomy property
rather than by log name:

```yaml
low_back:
  links:
    direct:   {patterns: [erector_extension, hinge, hinge_unilateral], flags: [direct_erector]}
    indirect: {patterns: [squat, ...], muscles: [erectors], flags: [high_fatigue_spinal]}
```

Direct loading weighs 2, indirect 1. The mapping is **exposure, not causation**
(`ASSUMPTION-10`): "this lift loads that region" is a mechanical statement, and it does not
claim the lift caused the injury or that avoiding it prevents recurrence.

### 4.1 Low back

Linked: erector work, all hinges (trap bar, sumo, conventional, RDL, good morning, rack pull),
squats and carries as indirect. This reuses the existing taxonomy properties, so the
`SPINAL-COST` work and this signal cannot drift apart.

The evidence does not support banning loading. Exercise treatment is probably effective for
chronic low back pain compared with no treatment (moderate certainty, mean difference −15.2 on
a 0-100 pain scale) ([Hayden 2021](https://doi.org/10.1002/14651858.CD009790.pub2)). What
matters for this signal is the *response* to loading, which is exactly what the tolerated
count measures. The one caveat is that the cohort evidence is about episodes of pain, not
about heavily loaded barbell work; the app cannot say a heavy hinge is safe, only that it was
loaded and followed by a quiet reading.

### 4.2 Biceps / elbow flexors

Linked: elbow flexion, vertical pulls (pull-ups, chin-ups) and horizontal pulls (rows).

This is the weakest evidence of the three. A scoping review of physical-therapy interventions
for long-head biceps tendinopathy found 14 eligible articles, mostly of modalities, and
concluded there is "a dearth of evidence detailing the conservative management"
([McDevitt 2024](https://doi.org/10.1016/j.bjpt.2023.100586)). Exercise and eccentric training
appear among the interventions used, but no loading protocol is established.

The model also cannot see grip: a supinated curl and a neutral-grip row are not distinguished,
and grip and shoulder position change biceps demand. That makes the linkage coarse rather than
precise, which is stated rather than hidden.

Distal biceps **repair** is a different case and is not modelled: return to sport after repair
averages 6.3 months in a review of 42 studies and 1093 patients
([Boufadel 2025](https://doi.org/10.1177/03635465241295618)). A repaired tendon is a surgical
timeline, not a load-tolerance signal, and the app should not pretend otherwise.

### 4.3 Knee

Linked directly: squats, split squats, knee extension, knee flexion, Nordic hamstring work and
jump/landing. Indirectly: hinges and carries.

Exercise is the standard treatment for patellar tendinopathy, but the evidence is weak: a
Cochrane review of seven trials and 211 athletes found very-low-certainty evidence for pain
versus no treatment, and **no trial measured adverse events**
([Lopes 2025](https://doi.org/10.1002/14651858.CD013078.pub2)). That absence is a reason to
keep the signal advisory and to keep recording symptoms, not a reason to assume exercise is
risk-free.

For patellofemoral pain the load-management approach has better support
([Rathleff 2019](https://doi.org/10.1177/0363546519843915)), and it is the model this signal
follows: reduce or modify loading when symptoms rise, progress when they settle.

Knee loading is the least specific of the three: patellofemoral pain, patellar tendinopathy
and meniscal symptoms are different tissues with different aggravating movements, and the app
records one "knee" region. The signal is therefore a general knee-load history, not a
diagnosis-specific one.

---

## 5. Statuses

| status | meaning |
|---|---|
| `unknown` | no reading for the region; nothing can be said |
| `insufficient` | the last reading is older than 14 days; a stale reading cannot speak for today |
| `active` | the latest reading is a flare (level ≥ 2, or level 1 that did not settle in 48 h — an unrecorded settlement counts as not settled) |
| `monitoring` | readings exist, no active flare, and the review bar is not met |
| `review` | streak ≥ window **and** tolerated sessions ≥ requirement, with no active flare |

`review` produces a recommendation to consider re-rating the lifts that load the region. It
does not change any rating. A flaring region adds an advisory warning to a prescription that
loads it; the low back is excluded from that warning because `MOD-BACK-001` already reports it
and a duplicate would bury the modifier.

---

## 6. Adding an injury

1. Append a region to `config/injuries.v1.yaml` with its `links` and, if it needs different
   numbers, any of the window keys.
2. Log against it: `strength-coach symptom --region <name> --level <0-3>`. What to
   write in `settled`, and which reading ends a flare, is in
   [SYMPTOM-LOGGING.md](SYMPTOM-LOGGING.md).
3. If the region needs a movement the taxonomy cannot express, add the property to the
   taxonomy (and document it in [DATA-MODEL.md](DATA-MODEL.md)), not a special case in code.

An unknown `--region` is rejected with the list of configured regions: a typo must not create
a silent region that never loads.

---

## 7. What would change this design

- Enough returns to estimate **per-region tolerance curves** from the athlete's own data,
  instead of fixed steps (the same logic as ROADMAP §4.12 for gap arithmetic).
- A symptom input that records **which movement** provoked the symptoms, which would replace
  the exposure map with a direct attribution.
- A validated per-region scale (the current 0-3 is the athlete's, and the 24-48 h settlement
  question is the only timing information).
- Evidence that a specific loading pattern is protective or harmful for a region; today the
  link is mechanical, and the app should not be read as claiming more.

---

The proposed readiness score uses this signal as a **ceiling**, never an average: a high
readiness score cannot raise a lift above its region's injury status. See
[`READINESS-SCORE.md`](READINESS-SCORE.md) §2.2 and §2.6.
