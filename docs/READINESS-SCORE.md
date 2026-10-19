# READINESS SCORE — global and per lift (proposal)

**Status: proposal, not implemented.** This replaces the single sleep/energy trigger with a
transparent two-level score, and makes it interact with the per-region injury signal. The
current behaviour remains: `MOD-FAT-001` reads sleep and energy, cuts every loaded item by 5%
when either is at or below 2, and says when readiness is unknown.

This document records the evidence, the proposed model, what is assumed rather than measured,
and the phased path. Decisions still belong in `docs/DECISIONS.md`.

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
`10.1371/journal.pone.0358036`. Grip and mortality context: LaMonte 2026
`10.1001/jamanetworkopen.2025.59367`. Injury evidence: refs 40-46 in REFERENCES.

### What is absent

- **No validated per-lift readiness questionnaire.** `squat_readiness`, `bench_readiness` and
  `deadlift_readiness` are self-ratings; treating them as measured lift readiness is a design
  assumption, not a finding.
- **No evidence for specific composite weights or cut-points.** Equal weights and the
  thresholds below are transparent starting points, not science.
- **No evidence that grip strength tracks day-to-day readiness.** It is slow capacity.
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
| grip strength | kg | higher better | **capacity trend only; excluded from the daily score** |

For a field present on the date:

- 1-5: `normalised = (value - 1) / 4`;
- HRV: `median(previous 28 days)` baseline; ratio clipped to 0.5-1.5, mapped to 0-1;
- RHR: same baseline, ratio **inverted** before mapping.

```
global = sum(weight_i * normalised_i) / sum(weight_i)   over present, eligible fields
```

Defaults (config, not code): equal weight 1 for the five subjective fields; weight 0.5 for HRV
and RHR when a baseline exists; no score with fewer than **two** subjective fields (report
"insufficient", not a number). Missing fields are excluded, never zero.

Every display shows the contributors and their weights, a confidence label based on how many
fields were present, and the baseline dates used for HRV/RHR.

### 2.2 Per-lift readiness

```
lift_readiness = min(global,
                     self_readiness_if_present,
                     injury_ceiling_if_linked)
```

- `self_readiness` maps the existing per-lift 1-5 fields to their patterns:
  squat readiness → squat patterns; bench readiness → horizontal-push/bench; deadlift
  readiness → hinge patterns. Lifts without a mapped field inherit the global score.
- `injury_ceiling` comes from the injury signal for the region linked to that exercise:
  direct loading uses the table below; indirect loading adds one step less severe.

| injury status | direct ceiling | indirect ceiling |
|---|---|---|
| active flare | 0.50 | 0.60 |
| monitoring | 0.80 | 0.85 |
| review | 1.00 (no cap) | 1.00 |
| insufficient / unknown | 1.00, with a warning | 1.00 |

These numbers are **assumptions** (`ASSUMPTION-13`). The important structural rule is that a
high readiness score can never lift an item above its injury ceiling, and an injury signal can
never *increase* readiness.

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

## 3. Why this shape

- It separates **subjective readiness** (what the athlete feels today) from **injury history**
  (what the tissue has tolerated) instead of averaging them into one number.
- It preserves the existing safety floors and the injury signal's "may recommend, never clear"
  rule.
- It is transparent: the score, its inputs, weights and ceilings are all visible.
- It starts in **shadow mode**, so the first phase changes no prescription.

---

## 4. Phased plan

1. **Score core + display (shadow).** Compute global and per-lift scores, show contributors,
   confidence and injury ceilings; store the assessment in the prescription notes. No load
   effect. Collect at least a few weeks of scores alongside RIR, completion and post-session
   fatigue.
2. **Per-lift caps in shadow.** Compare `min(global, self, injury)` with the current
   sleep/energy trigger; show where they disagree.
3. **Enable load effects behind config.** Keep the old trigger as a floor; cap combined
   reductions; add tests for direction, missing fields, injury precedence and no double count.
4. **Calibrate.** Use the recorded returns and session outcomes to adjust weights/cut-points
   per athlete; no automatic change.

## 5. Open questions

1. Should the global score use equal weights or explicit weights per field? Evidence does not
   settle it.
2. Is a 1-5 soreness scale direction "higher = less sore" intuitive enough, or should the UI
   invert the label?
3. Which per-lift fields map to which patterns, and what about lifts with no field?
4. Are the injury ceilings (0.50/0.60 active, 0.80/0.85 monitoring) too aggressive?
5. Should the combined reduction cap be 20%, or lower for a return after a gap?
6. Does grip strength ever belong in the daily score, or only in a capacity panel?
7. Minimum data before a score is shown: two subjective fields? Three?

## 6. Assumptions

- `ASSUMPTION-11` — equal weights over present subjective fields are a transparent starting
  point, not a validated composite.
- `ASSUMPTION-12` — per-lift readiness is constructed from global + self-rating + injury
  ceiling; no validated per-lift instrument exists.
- `ASSUMPTION-13` — the injury ceilings are design choices, not measurements.
- `ASSUMPTION-14` — readiness cut-points/factors and the combined-reduction cap are design
  choices.

Evidence references: [`docs/REFERENCES.md`](REFERENCES.md) §7. Injury evidence:
[`docs/INJURY-SIGNAL.md`](INJURY-SIGNAL.md).
