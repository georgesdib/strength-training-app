# Per-rep velocity — evidence and analysis decision

**Date:** 2026-10-24  
**Question:** Once optional per-rep velocity is captured, what can it validly tell us beyond
RIR, RPE, sRPE, readiness, load and reps?

**Decision:** Keep it descriptive. Do not infer RIR, readiness, injury risk, a universal
velocity-loss threshold or a next-session performance prediction from it. Report stratified
associations with sample sizes and explicit “insufficient data” states.

---

## 1. What velocity loss is

Within-set velocity loss is the decline from the fastest early rep to the last rep:

    VL = (first velocity - last velocity) / first velocity * 100

It is a **mechanical fatigue signal inside that set**, not a measure of systemic readiness or
tissue injury.

---

## 2. Evidence

### 2.1 Velocity loss tracks acute neuromuscular/metabolic fatigue

Sánchez-Medina and González-Badillo had strength-trained men perform bench press and squat
protocols with different rep counts relative to failure. Velocity loss after three sets was
highly correlated with loss of velocity against the 1 m/s load and countermovement-jump loss
(r = 0.91–0.97), and strongly correlated with post-exercise lactate (r = 0.93–0.97). This
supports velocity loss as an acute fatigue indicator, not as a predictor of injury or readiness.

[Sánchez-Medina & González-Badillo 2011](https://doi.org/10.1249/MSS.0b013e318213f880)

### 2.2 The size of velocity loss changes the training stimulus

Pareja-Blanco et al. compared 20% vs 40% velocity loss in the squat over 8 weeks. Strength gains
were similar, but the 20% group improved countermovement jump more (9.5% vs 3.5%) while doing
40% fewer reps; the 40% group had greater vastus lateralis/intermedius hypertrophy. A later
study compared 10%, 30% and 45% velocity loss and found similar strength gains, with 10% giving
the best jump/sprint changes.

[Pareja-Blanco et al. 2016](https://doi.org/10.1111/sms.12678)  
[Pareja-Blanco et al. 2021](https://doi.org/10.1111/sms.13967)

**Implication:** velocity loss is a real programming variable. It does not follow that a
post-hoc measurement should change a prescription automatically.

### 2.3 Velocity loss is strongly related to repetitions performed, not to a fixed RIR

Rodríguez-Rosell et al. found strong relationships between relative velocity loss and the
percentage of performed repetitions in bench press (R = 0.97) and squat (R = 0.93), with
equations to predict repetitions left in reserve. But the same velocity loss corresponded to
different percentages of performed reps in the two lifts, and individuals varied.

[Rodríguez-Rosell et al. 2019](https://doi.org/10.1519/JSC.0000000000002881)

A 2024 study modelled the RIR–velocity relationship directly. **Individual** RIR–velocity
relationships predicted RIR acceptably (mean error <2 reps) in a later session; **general**
relationships did not. This is the key limitation: the app does not have an individual
RIR–velocity model, and a single group equation would be a fabricated precision.

[Modeling the RIR–velocity relationship 2024](https://doi.org/10.14814/phy2.15955)

### 2.4 A universal velocity-loss threshold is not supported

A 46-person study tested whether the work completed after reaching different velocity-loss
thresholds was stable across two sessions. Agreement was not acceptable; sex, load, strength
level, training history and personality traits moderated the response. The authors question
using velocity loss to prescribe volume.

[One velocity loss threshold does not fit all 2023](https://doi.org/10.1186/s40798-023-00626-z)

**Implication:** no app-wide 10/20/30% threshold. Report the observed loss; do not turn it into
a rule.

### 2.5 RPE and velocity loss overlap but are not interchangeable

In bench press, RPE and velocity loss both predicted the percentage of reps performed, and
together improved the fit (R² = 0.94). In explosive back squat, however, velocity loss and a
spectral fatigue index were only weakly correlated (r = 0.224), and velocity did not decrease
significantly across the tasks. The relationship is lift- and context-dependent.

[RPE and velocity loss 2019](https://doi.org/10.1080/14763141.2019.1640278)  
[Explosive back squat 2024](https://doi.org/10.3390/jfmk9040238)

### 2.6 Higher velocity loss can increase delayed internal load

A crossover study compared sessions with 10%, 20% and 40% velocity loss. At 24 h, DOMS and HRV
markers differed most after 40% velocity loss, consistent with greater internal load. This is a
group acute response, not evidence that a given set caused injury or that tomorrow's readiness
is predictable.

[Delayed effects of velocity loss 2024](https://doi.org/10.5114/jhk/189703)

### 2.7 Barbell and device matter

A 2026 crossover study found the safety squat bar produced higher mean propulsive velocity and
different velocity loss than a traditional barbell at 65% and 85% 1RM. Device comparison work
also shows meaningful between-device error; mean velocity is more reliable than some derived
metrics, but the device and lift must be held constant.

[Safety squat bar vs traditional 2026](https://doi.org/10.3390/sports14040146)  
[Device reliability 2020](https://doi.org/10.1371/journal.pone.0232465)

**Implication:** stratify by exercise and barbell. Never pool safety-squat, straight-bar and
trap-bar velocity loss as if they were the same measurement.

### 2.8 No evidence for back symptoms or injury prediction

The search found no study linking within-set velocity loss to low-back symptoms, injury or a
back-flare prodrome. This is an evidence gap, not a null result. The app may display a
descriptive association when symptom data exist, but must not claim prediction or causation.

---

## 3. What the evidence supports

| claim | support |
|---|---|
| velocity loss measures acute within-set fatigue | supported |
| velocity loss relates to repetitions performed | supported, lift-specific |
| individual RIR–velocity models can predict RIR | supported with individual data; **not available** |
| general RIR–velocity equation is accurate enough | **not supported** |
| a universal velocity-loss threshold is stable | **not supported** |
| higher velocity loss can increase acute internal load | supported, group-level |
| velocity loss predicts next-session performance | **not established** |
| velocity loss predicts back pain/injury | **no evidence** |

---

## 4. Analysis decision

Build a **descriptive** report only:

### Per set
- first, last, mean, min/max;
- absolute and percentage loss;
- rep count and missing reps;
- RIR and RPE;
- load and estimated %e1RM where available;
- exercise and barbell identity.

### Per session
- mean loss by exercise;
- sRPE and readiness (mean of the seven self-report fields, or unknown);
- pre-session symptom level;
- next same-exercise session performance within 14 days, as an e1RM change.

### Across sessions
- correlations only when n >= 10 **within the same exercise**;
- otherwise show “insufficient data” and the n;
- no p-values presented as proof; no causal language;
- show missing-data counts.

### Explicitly excluded
- inferring RIR from velocity;
- a universal loss threshold;
- adjusting load, sets or RIR;
- predicting injury or back pain;
- pooling different barbells/lifts;
- using the report as a prescription input.

---

## 5. Limitations

- No real per-rep data exists yet in the local database.
- The analysis cannot be prospectively validated from one athlete quickly.
- RIR is self-reported and has known error; velocity loss does not replace it.
- Device and barbell changes can dominate the signal.
- Symptom data are currently absent, so symptom associations will show no data.
- Next-session e1RM is an estimate, not a measured 1RM.

---

## 6. References

See [REFERENCES.md](REFERENCES.md) entries 143–153.
