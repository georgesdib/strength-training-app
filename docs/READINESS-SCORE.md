# READINESS SCORE — global, category and calibration

**Status: implemented (2026-10-19; HRV/RHR + wearable 2026-10-20)** for the global/category
score, overrides, the readiness-required gate, the 20% combined cap, the calibration report,
baseline-relative HRV/RHR, the optional device-computed wearable score, per-athlete baseline
settings and the shadow baseline report. Learned weight adoption was evaluated and closed
on 2026-10-20; see [`READINESS-WEIGHT-EVIDENCE.md`](READINESS-WEIGHT-EVIDENCE.md).

The score replaces the old sleep/energy-only trigger, but the old trigger remains as a safety
floor. The three legacy per-lift values are calibration labels, never inputs.

This document records the evidence, the model, what is assumed rather than measured, and the
remaining path. Decisions live in `docs/DECISIONS.md`.

---

## 1. What the evidence supports

| claim | evidence | strength / limit |
|---|---|---|
| Subjective self-reports are more sensitive to acute and chronic training load than most objective measures | Saw et al. 2016 systematic review (56 studies) | Moderate; heterogeneous measures, no universal questionnaire |
| A multi-item wellness index can track recovery and staleness | Hooper et al. 1995 (daily fatigue/stress/sleep/muscle soreness in swimmers); Bell et al. 2025 (Hooper index during a squat overreaching protocol) | Moderate for trend; no validated weighting of items |
| Pretraining wellness is associated with subsequent training load | Govus et al. 2018 (American football) | Observational; not a prescription rule |
| Sleep restriction impairs maximal strength in compound movements | Knowles et al. 2018 systematic review (17 studies) | Moderate/weak quality; single-joint movements less affected |
| HRV-guided training improves vagal HRV indices, but performance benefits are small and not clearly significant; resting HR was not improved | Manresa-Rocamora et al. 2021 meta-analysis | Supports HRV as context/trend, not a hard daily gate |
| HRV interpretation depends on the decision framework; no standard multimodal rule | Schaffarczyk & Sperlich 2026 SWOT review | Weak for a specific formula; supports transparency |
| Perceived readiness can relate to resistance-training performance | Munteanu et al. 2026 (28 resistance-trained females, two mesocycles) | Emerging, small; not a validated per-lift scale |
| Grip strength is a strength/health marker related to upper-body power | Silder et al. 2024 (military); LaMonte et al. 2026 (mortality) | Chronic capacity, **not** acute daily readiness |
| Injury history and symptom response matter more than a calendar | injury-signal evidence, refs 40-46 | Supports a ceiling, not an average |

DOIs: Saw 2016 `10.1136/bjsports-2015-094758`; Hooper 1995 `10.1249/00005768-199501000-00019`;
Govus 2018 `10.1123/ijspp.2016-0714`; Knowles 2018 `10.1016/j.jsams.2018.01.012`;
Manresa-Rocamora 2021 `10.3390/ijerph181910299`; Schaffarczyk 2026
`10.3389/fspor.2026.1858271`; Munteanu 2026 `10.1007/s40279-026-02459-8`; Bell 2025
`10.3390/jfmk10020227`; Silder 2024 `10.1093/milmed/usae227`; Long 2026
`10.1371/journal.pone.0358036`; Toohey 2017 `10.1136/bjsports-2017-097500`; Lou 2026
`10.1038/s41598-026-59571-y`; Yuan 2026 `10.52082/jssm.2026.172`; Impellizzeri 2020
`10.1123/ijspp.2019-0864`; Herr 2026 `10.4085/1062-6050-0619.25`. Grip and mortality context: LaMonte 2026
`10.1001/jamanetworkopen.2025.59367`. Injury evidence: refs 40-46 in REFERENCES.

### What is absent

- **No validated per-lift readiness questionnaire.** `squat_readiness`, `bench_readiness` and
  `deadlift_readiness` are self-ratings; treating them as measured lift readiness is a design
  assumption, not a finding.
- **No evidence for specific composite weights or cut-points.** Equal weights and the
  thresholds below are transparent starting points, not science.
- **No evidence that grip strength tracks day-to-day readiness.** It is slow capacity.
- **No validated per-lift readiness score.** A per-lift advisory score now combines the global
  base with e1RM trend, RIR and VBT and can only lower a load (`docs/LIFT-READINESS.md`); it is
  an assumption, not validation.
- **No trial of a readiness score overriding an injury signal.** The safe rule is that it
  cannot: injury is a ceiling/veto, readiness is a down-adjustment.

---

## 2. Proposed model

### 2.1 Global readiness, 0-1

Inputs and directions (higher score = more ready):

| input | scale | direction | role |
|---|---|---|---|
| sleep, energy, mood, stress | 1-5 | higher better | core subjective |
| soreness | 1-5 | higher = less sore | core subjective |
| HRV | ms | higher better, only relative to baseline | context, low weight |
| RHR | bpm | **lower** better, only relative to baseline | context, low weight |
| wearable score | 0-100 | higher better, device-defined | optional 10% blend; never a replacement |
| grip strength | kg | higher better | **moved out of readiness**: measured with `measure`, never a daily score input (`DEC-GRIP-01`) |

For a field present on the date:

- 1-5: `normalised = value / 5` (so a neutral 4/5 is 0.80 and a 5/5 is 1.00);
- HRV: `median(previous 28 days)` baseline; ratio clipped to 0.5-1.5, mapped to 0-1;
- RHR: same baseline, ratio **inverted** before mapping.

```
global = sum(weight_i * normalised_i) / sum(weight_i)   over present, eligible fields
```

`readiness.score` is independent of the legacy `readiness.composite.enabled` flag. The flag
only controls the imported `readiness_day.composite`; `MOD-FAT-001` reads the computed score
from `readiness_score.compute(...)` and can fire with the composite disabled.

Defaults (config, not code): weight 1 for the five subjective fields; weight 0.5 for HRV and
RHR when a baseline exists; no score with fewer than **three** subjective fields (report
"insufficient", not a number). Missing fields are excluded, never zero. If a wearable score is
present, the final score is `0.90 * subjective/device score + 0.10 * wearable/100`.

**Athlete settings.** A `readiness_setting` row effective on the date overrides the config
window, minimum readings, slopes and weights. Precedence is **athlete > config > code default**;
the score report says `athlete score setting` when one is active. Settings are append-only.

Every display shows the contributors and their weights, a confidence label based on how many
fields were present, and the baseline dates used for HRV/RHR.

### 2.1a Equal weights vs explicit weights

**Equal weights (recommended first).** Every present subjective field counts once; HRV/RHR
count half when a baseline exists. The score is the plain mean of the normalised values.

- why: no field's weight is validated, so equal weights are the least arbitrary choice;
- it is transparent and cannot overfit a short history;
- it is robust when a field is missing or noisy;
- weakness: it assumes a bad night's sleep and a slightly low mood matter equally, and it can
  dilute one severe field.

Example with sleep 2 (0.25), energy 4 (0.75), mood 4 (0.75), stress 4 (0.75), soreness 4
(0.75): equal score = **0.65**. With explicit weights sleep ×2, energy ×1.5 and the rest ×1,
the score falls to about **0.60**. Neither number is evidence; the first is the default.

**Explicit weights (later, per athlete).** Give each field a weight or a floor, e.g. sleep 2,
energy 1.5, HRV 0.5, because the evidence is strongest for sleep and weakest for HRV. This can
be more faithful to the athlete, but:

- the weights are not validated;
- with a handful of sessions they fit noise, not readiness;
- they make the score harder to explain and easier to game.

**Recommendation:** equal weights in shadow mode; explicit weights only as per-athlete config
after enough scored sessions, with the contributors still shown. Keep the **individual safety
floor** regardless of weights: sleep or energy at or below 2 still applies the old 5% cut even
if the composite is high. That prevents a single catastrophic field being averaged away.

### 2.1b HRV and RHR: implementation

HRV and RHR enter the score only when the athlete has a personal baseline:

- baseline = median of the previous **28 days**, at least **7** readings (imported or manual);
- HRV is higher-is-better, RHR lower-is-better; both are normalised around 0.5 at baseline;
- a 50% deviation from baseline maps to 0 or 1; the slope is a heuristic, not a clinical cutoff;
- each device field has weight **0.5**, against 1.0 for each subjective field;
- if the baseline is missing, the field is shown as present but **not scored**; it is never
  replaced by an arbitrary population value;
- a day with only device data is still insufficient: three subjective fields plus sleep or
  energy are required.

This is deliberately low-weight. HRV-guided training improves vagal indices, but performance
benefits are small and not clearly significant, and there is no standard decision framework
([Manresa-Rocamora 2021](https://doi.org/10.3390/ijerph181910299);
[Schaffarczyk 2026](https://doi.org/10.3389/fspor.2026.1858271)).

### 2.1b1 Per-athlete baseline settings

The rolling median is the default. An athlete can set the baseline window, minimum readings,
slopes and weights in `readiness_setting`; the latest row effective on the score date wins.
Nothing is auto-fitted. The CLI/UI show the effective values and their source.

The **shadow report** compares the shipped rolling median with a trend-projected baseline
(log-linear fit over the same prior readings), reporting the normalised difference. It is
diagnostic only: it does not change a score, a factor, or a load. The projection is capped to
0.5-1.5× the rolling median so an extrapolated trend cannot produce an absurd target.

### 2.1c Optional wearable readiness score

A device such as Bevel can supply its own readiness score (0-100). The app treats it as an
**optional context blend**, not as a second truth:

- absent: no effect;
- present: `score = 0.90 * computed_score + 0.10 * wearable/100`;
- 0 is valid (worst), blank is missing; the device threshold is not reinterpreted;
- global and category overrides still win; the injury ceiling still caps the result;
- the UI and score report label it `wearable_score` and show the 10% weight.

Why only 10%: the algorithm is proprietary and cannot be audited; it may double-count sleep,
HRV and soreness that are already in the subjective score; and different devices disagree.
Wearable data are useful context and can predict performance in groups, but they do not
replace the athlete's own report for an individual session
([Spetz 2025](https://doi.org/10.1186/s40798-025-00958-y);
[Khodr 2024](https://doi.org/10.1101/2024.01.04.24300784);
[Zhang 2026](https://doi.org/10.3389/fphys.2026.1912453)).

### 2.2 Per-lift readiness

```
lift_readiness = min(global_readiness,
                     category_override_if_present,
                     injury_ceiling_if_linked)
```

- The old `squat_readiness` / `bench_readiness` / `deadlift_readiness` fields are **labels, not
  inputs** (section 2.8). They are not read here.
- A **category override** is the manual per-lift input: the athlete may set `category:hinge`,
  `category:squat`, etc. for the day. This is how the score stays overridable without keeping
  the old fields in the form.
- `injury_ceiling` comes from the injury signal for the region linked to that exercise; direct
  loading uses the table below, indirect loading adds one step less severe.

| injury status | direct ceiling | indirect ceiling |
|---|---|---|
| active flare | 0.50 | 0.60 |
| monitoring | 0.80 | 0.85 |
| review | 1.00 (no cap) | 1.00 |
| insufficient / unknown | 1.00, with a warning | 1.00 |

These numbers are **assumptions** (`ASSUMPTION-13`). A high readiness score can never lift an
item above its injury ceiling, and an injury signal can never *increase* readiness.

### 2.2a Minimum data before a score is shown

Decision: require **at least three of the five core subjective fields** for a numeric global
score. With one or two, show the individual fields and `insufficient`, not a composite. For a
readiness-driven load change, require at least one of **sleep or energy** to be present;
otherwise the score can be displayed but does not move a load. The existing sleep/energy floor
still applies independently.

For a lift with no global score: use its **category override** if present, capped by the injury
ceiling; otherwise no readiness factor. The injury ceiling still applies either way.
This is `ASSUMPTION-15`; it prevents a two-field day from masquerading as a full score.

### 2.3 From score to load

| readiness | load factor | RIR |
|---|---|---|
| ≥ 0.80 | 1.00 | unchanged |
| 0.60-0.80 | 0.95 | +1 |
| 0.40-0.60 | 0.90 | +1 |
| < 0.40 | 0.85 | +2 |

Cut-points and factors are `ASSUMPTION-14`. The current sleep/energy rule stays as a **floor**:
if either is at or below 2, the old 5% reduction still applies even if the composite is high.
Final factor is the **strongest single reduction**, not a product of every rule; total
readiness + continuity reduction is capped (proposal: 20%) unless a flare or constraint says
otherwise. This prevents three rules silently compounding into a session that is too easy.

### 2.3a Combined reduction cap

Several rules can fire on the same day: the readiness score, the old sleep/energy floor, a
return-from-gap adjustment, a back flare and a per-lift injury ceiling. Without a cap, three
small reductions can silently become a deload that nobody intended.

Proposal:

- **Readiness vs the old sleep/energy floor:** take the **stronger single reduction**, not the
  product. They are two views of the same signal.
- **Readiness + continuity:** these are independent risks, so combine them, but cap the total
  load reduction at **20%**. The cap applies to the global load factor only.
- **Not capped:** hard constraints, back-flare RIR rules and per-lift injury ceilings. Those are
  safety layers; they are allowed to be more restrictive and must never be diluted by a cap.
- **Trace:** if the cap bites, say so and show the uncapped factors.

Why 20%, and what the evidence says: **there is no direct study of a numerical cap for stacked
readiness + return-to-training reductions.** Autoregulation research supports adjusting load to
readiness but shows only small advantages over standard prescription, and the reviews do not
define a safe stacking ceiling ([Hickmott 2022](https://doi.org/10.1186/s40798-021-00404-9);
[Hickmott 2025](https://doi.org/10.1007/s00421-025-05709-1)). The cap is therefore a guardrail,
not a finding. Twenty percent is deliberately modest: it honours two bad signals without turning
the session into a planned deload. Fifteen or twenty-five percent would be equally defensible;
the number is `ASSUMPTION-21`.

### 2.4 Interaction order

1. Hard constraints and suitability vetoes (unchanged; readiness cannot override).
2. Back-flare `MOD-BACK-001` (unchanged; wins over readiness).
3. Per-lift readiness: `min(global, self, injury ceiling)`.
4. Apply the factor to that item; items without a lift-specific value use the global factor.
5. Continuity (`MOD-GAP-001`) applies as today, but the combined reduction is capped.
6. Cite `readiness:<date>`, `readiness_score:<value>`, the contributors, and the injury region
   that set a ceiling.

A `review` injury status does **not** raise a score or clear a constraint. An `active` region
produces a warning and a ceiling; the hard-exclude constraint remains the only veto.

### 2.5 Grip strength

Stored as a capacity measurement, shown as a 28-day trend. It does not move a daily load in
this proposal. If later evidence supports it, it can enter the global score as a slow baseline
term; that would be a separate decision.

---

## 2.6 Injury attention by movement/muscle category

**Decision: the attention indicator is per movement/muscle category, not only per injury
region.** Regions remain the evidence unit (a flare is a low-back flare); the category is the
training unit the athlete actually chooses between.

A category is configuration, for example:

| category | matches | typically linked regions |
|---|---|---|
| hinge | patterns `hinge`, `hinge_unilateral`, `hinge_ballistic`; glutes/hamstrings/erectors | low back (direct), knee (indirect) |
| squat | `squat`, `squat_unilateral`; quads/glutes | knee (direct), low back (indirect) |
| horizontal push | `horizontal_push`, `horizontal_push_bw`; chest/triceps/front delts | none configured by default |
| vertical push | `vertical_push`; delts/triceps | none configured by default |
| horizontal pull | `horizontal_pull`; lats/rhomboids/biceps | biceps (direct) |
| vertical pull | `vertical_pull`; lats/biceps | biceps (direct) |
| elbow flexion | `elbow_flexion`; biceps/brachialis | biceps (direct) |
| knee extension | `knee_extension`; quads | knee (direct) |
| dorsiflexion | `dorsiflexion`; tibialis anterior | ankle/shin (if configured) |
| knee flexion | `knee_flexion`, `hamstring_eccentric`; hamstrings | knee (direct) |
| spinal extension | `erector_extension`; erectors | low back (direct) |
| core / carry | core patterns or `carry` | low back (indirect), knee (indirect) |

The exact list is config; patterns and muscles must exist in the taxonomy or the config is
rejected. An exercise can match a category by pattern **or** primary muscle; a category can also
list explicit exercise ids. A category may be **muscle-only** (for example elbow flexors:
biceps/brachialis) when no single movement pattern captures it.

For each category:

1. collect the configured regions linked to its patterns/muscles;
2. take the **worst** region status (active > review > monitoring > insufficient/unknown);
3. show the drivers: region, direct/indirect, latest level, prior flares, tolerated/unverified
   sessions;
4. if no region is linked, say *"no injury configured for this category"* — unknown, not fine.

No probability, no load effect, no second penalty. A category's attention is display and
education only; the injury signal and constraints remain the decision layer.

## 2.7 Injury risk indicator (why it is not a probability)

This is **not** a probability of injury and must not be called one. The evidence supports a
transparent **attention indicator**, not individual prediction.

### Evidence

- Previous injury is a risk factor for subsequent/recurrent injury; ACL history was associated
  with later hamstring injury (RR 2.25, 95% CI 1.34-3.76) ([Toohey 2017](https://doi.org/10.1136/bjsports-2017-097500)); prior low-back episodes predict recurrence ([da Silva 2019](https://doi.org/10.1016/j.jphys.2019.04.010)).
- Machine-learning models report pooled sensitivity 0.79 / specificity 0.71 across 10 small
  models, with substantial methodological heterogeneity and risk of bias
  ([Lou 2026](https://doi.org/10.1038/s41598-026-59571-y)). A 15-study review found AUCs up to
  0.91 but called for large prospective validation
  ([Yuan 2026](https://doi.org/10.52082/jssm.2026.172)).
- The acute:chronic workload ratio has **not** been shown to be causal for injury; treating it
  as one is an overinterpretation ([Impellizzeri 2020](https://doi.org/10.1123/ijspp.2019-0864)).
- Wellness/readiness as an injury predictor is case-level and observational, not validated
  ([Herr 2026](https://doi.org/10.4085/1062-6050-0619.25)).

### Proposed indicator

For each **movement/muscle category**, produce an attention tier with drivers, not a percentage:

| tier | drivers (examples) |
|---|---|
| high attention | active flare, or ≥3 prior flares with recent unverified/un tolerated loading |
| medium attention | monitoring, 1-2 prior flares, or a sudden load increase without follow-up readings |
| low attention | review status, no recent flare, tolerated loading |

It is **display and education only** in the first phase. It does not change a load, substitute a
lift, or clear a constraint. It must not feed back into the readiness score as a second penalty.
A future probability model is out of scope until prospective, calibrated validation exists.

### Current calibration report (2026-10-19)

`readiness calibrate` on the 306 labelled days, date split 70/30:

| label | n | MAE readiness-only | MAE + load | baseline | rank r |
|---|---|---|---|---|---|
| squat | 306 | 0.102 | 0.101 | 0.119 | 0.11 |
| bench | 306 | 0.069 | 0.068 | 0.071 | 0.00 |
| deadlift | 306 | 0.106 | 0.111 | 0.118 | 0.04 |

Read: the score is close in absolute error but barely ranks the old labels; main-lift load
features add almost nothing. That is evidence about **mimicry**, not readiness. The fitted
weights are not applied. If this remains weak, the old label may be mostly a different
construct, not a target worth chasing.

## 2.8 Legacy per-lift readiness labels (black box)

The three imported fields `squat_readiness`, `bench_readiness` and `deadlift_readiness` are
**not inputs** in the new model. They are outputs of an older external calculation — training
load plus other readiness data — whose formula is a black box. The athlete could override the
old value, which is why it is a useful reference but not ground truth.

What we know from the data:

- the overlapping window covers most of the available period, so those days carry all three values;
- all are 1-5, higher better;
- means: squat 3.53, bench 3.79, deadlift 3.56.

Plan:

1. **Remove them from new input surfaces**: readiness CLI, readiness web form and bulk state
   import. Stop asking the athlete for them.
2. **Keep the historical values read-only** in `readiness_day`/raw rows as calibration labels.
   They are not deleted and never become model inputs at prediction time.
3. **Calibrate against them in shadow mode.** They can tell us whether the new score *mimics*
   the old app, not whether it is physiologically correct. That distinction is stated wherever
   the calibration is reported.
4. If the old labels depend on training-load features, include those features in calibration
   (recent acute/chronic load, category-specific sets/tonnage, days since the category was
   trained). We cannot recover the black-box formula; we can only fit an approximation.

### Main-lift load features

Calibration must include the main-lift load history, because the old labels were derived from
training load as well as readiness. Features are built **only from data available before the
session** (no leakage from the session being predicted):

- readiness inputs for the day (sleep, energy, mood, stress, soreness; HRV/RHR relative to
  baseline);
- main lift: last load and e1RM estimate at a comparable RIR, and the change over the last two
  sessions;
- main-lift acute load (7 days) and chronic load (28 days): sets, tonnage and best set, relative
  to the athlete's 28-day baseline;
- days since that main lift was trained;
- last session's RIR and mean velocity for that lift, when present;
- missingness indicators, so "no data" is not silently zero.

Keep the feature set small and pre-specified; 306 labelled days will overfit quickly. Use a
date split and ridge/linear regression, not a black box. Report the global-only baseline next to
the load-feature model, and per-label MAE/rank correlation.

### Calibration shape

One shared global component plus three category adjustments, fitted against the three labels:

```
label_category ~ f(global readiness inputs,
                   recent training load,
                   category-specific load,
                   days since category trained)
                   + category adjustment
```

- fit on a **date split** (earlier dates train, later dates test), not a random split;
- report MAE and rank correlation for each label and for the pooled labels;
- compare against a baseline (global score alone) before adding load features;
- only 306 labelled days exist, so start simple (linear/ridge); no deep model, no black box;
- the fitted weights are proposals, never auto-applied; the athlete adopts them.

Only squat, bench and deadlift have labels. Other movement categories have no calibration
target until the athlete provides one.

## 2.9 Readiness overrides

Computed readiness is a model output, so the athlete must be able to correct it. Overrides are
append-only, dated and reasoned.

- **Scopes:** `global` and `category:<name>` (for example `category:hinge`).
- **Value:** 0.00-1.00, the same scale as the computed score (higher = more ready). No separate
  1-5 override scale.
- **Precedence:** a category override wins over the global override, which wins over the
  computed score.
- **Effect:** the winning score goes through the same load-factor table, so an override **does
  change the prescribed load**.
- **Safety ceiling:** an override may raise or lower readiness, but it **cannot** raise a lift
  above an injury ceiling or bypass a hard constraint/back-flare rule. Those remain the veto
  layer. This is the one place where "override wins" does not mean "override everything".
- **Trace:** the prescription cites `readiness_override:<id>` and the reason. A later override
  appends; the earlier one stays in history.

A manual override is a statement about today's readiness, not a new programme rule. It expires
with the date unless re-entered.

## 3. Why this shape

- It separates **subjective readiness** (what the athlete feels today) from **injury history**
  (what the tissue has tolerated) instead of averaging them into one number.
- It preserves the existing safety floors and the injury signal's "may recommend, never clear"
  rule.
- It is transparent: the score, its inputs, weights and ceilings are all visible.
- It starts in **shadow mode**, so the first phase changes no prescription.

---

## 4. What is implemented

Delivered on 2026-10-19:

- global score from sleep, energy, mood, stress, soreness; 3-field minimum and sleep/energy
  requirement;
- category scores and overrides at global/category scope, 0.00–1.00, reason required;
- injury ceiling per item, applied before the factor;
- load factor table and the old sleep/energy floor;
- 20% combined readiness + continuity cap, with a warning when it bites;
- readiness-required gate for current/future CLI and web workouts;
- calibration report (`readiness calibrate`) with main-lift load features, date split,
  ridge/linear fit and baseline comparison;
- HRV/RHR baseline-relative components (0.5 weight, 7 readings in 28 days);
- optional wearable score at a 10% blend.

Closed:

- learned weight adoption — the held-out comparison found no improvement; fixed transparent
  weights are retained (`DEC-READINESS-10`, [`READINESS-WEIGHT-EVIDENCE.md`](READINESS-WEIGHT-EVIDENCE.md)).

## 5. Decisions and open questions

Periodic review and the app-wide threshold policy are specified in
[`READINESS-EXERCISE-SELECTION-PLAN.md`](READINESS-EXERCISE-SELECTION-PLAN.md) §11–13.

Decided:

- **Equal weights retained**; explicit per-athlete weights and learned weights are not adopted;
  the sleep/energy floor stays.
- **Cut-points and injury caps accepted.**
- **Per-lift mapping accepted**: squat → `squat`/`squat_unilateral`, bench →
  `horizontal_push`/`horizontal_push_bw`, deadlift → `hinge`; unmapped lifts inherit global.
- **Minimum data**: three core subjective fields, with sleep or energy for a load effect.
- **Grip is capacity only**, never a daily score input.
- **Injury attention is per movement/muscle category**, not only per region; display only.
- **The three old per-lift fields are black-box labels**, kept read-only for calibration and
  removed from new input surfaces.
- **Overrides cover global and category scores**, win over computed readiness, change the load,
  but never bypass constraints or injury ceilings.

Still open:

1. Is a 1–5 soreness scale direction "higher = less sore" intuitive enough, or should the UI
   invert the label?
2. The exact category list and exercise-to-category mapping; the table above is a starting
   proposal, not final.
3. The exact regularisation/feature weighting in calibration; the feature set is specified, the
   fit is not.
5. Whether a category with no linked injury should say `unknown` or `not configured`; both
   avoid "fine", but they mean different things.

Decided: overrides use 0.00–1.00 like the score and require a reason; the combined readiness +
continuity cap is 20%, applying to loads only.

## 6. Assumptions

- `ASSUMPTION-11` — equal weights over present subjective fields are a transparent starting
  point, not a validated composite.
- `ASSUMPTION-12` — per-lift readiness is constructed from global + self-rating + injury
  ceiling; no validated per-lift instrument exists.
- `ASSUMPTION-13` — the injury ceilings are design choices, not measurements.
- `ASSUMPTION-14` — readiness cut-points/factors and the combined-reduction cap are design
  choices; the cut-points and injury caps are approved for the plan.
- `ASSUMPTION-15` — three core fields are the minimum for a numeric score; this is a design
  choice, not a finding.
- `ASSUMPTION-16` — the injury attention tiers are descriptive, not probabilistic; they do not
  predict a new injury.
- `ASSUMPTION-17` — the attention indicator is grouped by movement/muscle category, with the
  region as the underlying evidence unit; the category list and links are config, not science.
- `ASSUMPTION-18` — the old per-lift readiness values are a black-box reference, not ground
  truth; calibration measures mimicry, not validity.
- `ASSUMPTION-19` — readiness overrides are bounded by constraints and injury ceilings; "override
  wins" applies to the computed score only.
- `ASSUMPTION-20` — the calibration features and date split are design choices until tested.
- `ASSUMPTION-21` — a 20% cap on combined readiness + continuity reduction is a guardrail, not
  an evidence-based threshold.
- `ASSUMPTION-22` — main-lift load features are used only in calibration and only from data
  available before the session.

Evidence references: [`docs/REFERENCES.md`](REFERENCES.md) §8. Injury evidence:
[`docs/INJURY-SIGNAL.md`](INJURY-SIGNAL.md).

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [READINESS-WEIGHT-EVIDENCE.md](READINESS-WEIGHT-EVIDENCE.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
