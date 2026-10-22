# SELECTION COMPARABILITY — evidence and proposed guard

**Status: implemented 2026-10-20.** This note documents the evidence and the guard that is now
[STRENGTH-PROGRAM-REVIEW.md](STRENGTH-PROGRAM-REVIEW.md) and proposes a comparability model.
The implemented classification is in `config/selection-comparability.v1.yaml`; the selector,
engine, CLI and web UI enforce it.

---

## 1. The problem

The selector can substitute one configured variant for another: SSB squat -> front squat,
competition bench -> dumbbell bench, pull-up -> lat pulldown, and so on. It re-solves the load
from the selected lift's own history, which is mechanically correct.

That still leaves two separate questions:

1. **Can the load be transferred?** Usually no; the lifts have different load bases.
2. **Is the stimulus still the intended one?** Not necessarily, even when the pattern matches.

The current safeguards are real but incomplete: pattern match, constraints, suitability,
injury ceiling, one substitution per slot, and explicit opt-in. None of them classifies
comparability.

## 2. What comparability means here

Three different claims are often conflated:

| claim | meaning | evidence needed |
|---|---|---|
| **same movement family** | both are squats/benches/hinges | taxonomy pattern |
| **same load basis** | the same e1RM/history can be used without a conversion | direct load/1RM comparison |
| **same stimulus** | adaptation and fatigue cost are close enough to be interchangeable | longitudinal equivalence, not EMG alone |

The selector currently checks only the first. The proposed guard is about the second and third.

## 3. Evidence

### 3.1 Specificity: a different mode is a different adaptation

The classic review of resistance-training modes concludes that adaptations are specific to the
mode and exercise used ([Morrissey, Harman & Johnson 1995](https://pubmed.ncbi.nlm.nih.gov/7674868/)).
A recent meta-analysis reaches the same conclusion for dynamic versus isometric strength:
dynamic resistance training transfers less well to isometric tests than to dynamic tests
([Saeterbakken 2025](https://doi.org/10.1007/s40279-025-02225-2)).

Free-weight versus machine training shows the same pattern: direct pooled differences are
small, but strength changes are **specific to the tested modality**
([Haugen 2023](https://doi.org/10.1186/s13102-023-00713-4)).

**Strength:** strong for specificity; not evidence that every variant is useless, and not a
claim that any particular substitution is harmful.

### 3.2 Bench grip width

Grip width changes the load-velocity relationship and the 1RM value:

- [Herrera-Bermudo 2024](https://doi.org/10.1519/JSC.0000000000004920): grip width influenced
  the bench-press load-velocity relationship and 1RM.
- [Pérez-Castilla 2020](https://doi.org/10.1123/ijspp.2019-0549): the load-velocity relationship
  differed across four grip widths.

A counterpoint matters:

- [Pérez-Castilla 2021](https://doi.org/10.3390/ijerph18031057): grip width did **not** change
  the number of repetitions at fixed velocity-loss thresholds.

So the fatigue response can be similar while the load basis is not. A narrow-grip bench is not
a neutral relabelling of a competition bench.

### 3.3 Front squat versus back squat

Front and back squats have different load-velocity relationships
([Spitz 2019](https://doi.org/10.1519/JSC.0000000000002962)) and load-dependent lower-body
mechanics ([Krzyszkowski & Kipp 2020](https://doi.org/10.1080/02640414.2020.1766738)).

They share a pattern and a broad stimulus, but not a load basis. A front-squat e1RM cannot be
used as a back-squat e1RM.

### 3.4 Safety squat bar versus straight bar

The SSB changes mechanics and performance:

- [Johansson 2024](https://doi.org/10.1519/JSC.0000000000004719): kinematic and kinetic
  differences; the traditional bar lifted more weight and produced greater hip extensor demand.
- [Vantrease 2021](https://doi.org/10.1519/JSC.0000000000003541): differences in maximal
  strength, muscle activation and bar velocity.
- [Hecker 2019](https://doi.org/10.1519/JSC.0000000000002912): altered trunk and lower-body
  mechanics.

SSB -> front squat is therefore not a like-for-like swap. Each can be a valid training choice;
they are not one load basis.

### 3.5 Barbell versus dumbbell bench

Barbell and dumbbell bench do not share a clean rep/1RM relationship
([Heinecke 2021](https://doi.org/10.1519/JSC.0000000000003539)). A direct comparison of
barbell, dumbbell and Smith-machine bench also found differences in maximal performance,
repetitions and muscle activation ([Farias 2017](https://doi.org/10.1519/JSC.0000000000001651)).

The dumbbell version adds independent-arm stability and a different range/stability demand.
The load must come from the selected implement's history.

### 3.6 Pull-up versus lat pulldown

The latissimus activation is broadly similar across pull-up variations
([Di Fonza 2026](https://doi.org/10.3390/jfmk11030315)), and lat-pulldown training improves
pull-up endurance ([Li 2025](https://doi.org/10.1002/ejsc.12243)).

That is evidence of **carryover**, not evidence of a common load basis. One is bodyweight plus
added load; the other is an external stack. They can substitute as a stimulus without sharing an
e1RM.

### 3.7 Exercise variation is not automatically better

Random session-to-session exercise variation produced similar strength and hypertrophy to a
fixed programme, with better motivation ([Baz-Valle 2019](https://doi.org/10.1371/journal.pone.0226989)).

This is useful: variation is not harmful by default. It does **not** show that an algorithmic
selector improves outcomes, or that any two variants are load-comparable.

### 3.8 The selector itself has no outcome evidence

There is no trial of:

- readiness/stress/rotation-driven selection versus a fixed programme;
- automatic substitution versus human choice;
- a same-pattern filter preserving the intended stimulus;
- a parent-variant e1RM ratio improving prescriptions.

The strength-programme review therefore rates **specificity strong, algorithmic selection
weak**. The guard is a safety and coherence measure, not a proven performance intervention.

## 4. What the evidence supports

1. **Do not transfer loads across different implements.** Barbell, dumbbell, machine, SSB,
   front squat and safety-bar variants have different load bases.
2. **Do not treat a shared pattern as proof of equivalence.** Bench, squat and hinge each
   contain variants with different mechanics.
3. **Do use the selected lift's own history.** Re-solving from the selected lift is necessary;
   it is not sufficient to make the substitution neutral.
4. **Similar EMG does not establish load equivalence.** Pull-up/lat-pulldown is the clearest
   example.
5. **Variation itself is defensible.** The guard should not ban variation; it should make the
   load and stimulus change visible.
6. **No parent-variant ratio is validated.** A ratio can be a future prior, not a conversion.

## 5. Implemented solution

### 5.1 Classify each variant, not just its pattern

Add explicit comparability metadata to each exercise or to each slot-variant pair:

| field | examples | why |
|---|---|---|
| load_basis | barbell, dumbbell, machine, bodyweight, added-load, implement | decides whether a load can transfer |
| movement_family | squat, hinge, horizontal push, vertical pull | broad pattern only |
| rom_profile | full, partial, box, pause, deficit | changes load and velocity |
| stability | bilateral, unilateral, machine-supported | changes load and skill |
| bodyweight | yes/no | bodyweight vs external load |
| variant_class | exact, near, different | the guard's decision |

The class must be configuration, not inferred from the display name.

### 5.2 Three classes

| class | meaning | apply policy |
|---|---|---|
| **A — load-comparable** | same implement and load basis, same broad ROM/stability; e.g. a true duplicate/alias | auto-eligible, but still uses selected lift history |
| **B — near-comparable** | same pattern but different grip, bar, pause, box or stability; e.g. competition <-> pause bench, SSB <-> high-bar | **confirmation required**; show the load-basis difference and selected lift history |
| **C — different lift** | different implement or load basis; e.g. barbell <-> dumbbell bench, pull-up <-> lat pulldown, trap bar <-> straight bar, SSB <-> front squat | **never automatic**; human must choose it as a programme change |

The exact A/B boundary is a decision, not an evidence claim. Bench pause/narrow and
SSB/high-bar are the hard cases; the evidence shows they are not identical, so the conservative
default is **B**, not A.

### 5.3 Load handling

- Always re-solve from the **selected** lift's own e1RM/history.
- Never copy the old item's load or citation.
- If the selected lift has no usable history, show unknown; do not borrow a parent ratio.
- Show the selected lift, its e1RM source/age, the old load and the new load.
- Record the comparability class and confirmation in the selection note.
- A parent-variant ratio is allowed only after prospective validation, and even then as a
  display/prior, not a silent conversion.

### 5.4 Selection and UI

- The selector's default candidate set is class A/B; class C is hidden behind "show all" or an
  explicit programme-change action.
- Automatic apply is limited to class A. Class B requires a confirmation that states:
  "This changes the load basis; the load will be re-solved from the selected lift."
- Class C requires the same confirmation plus a visible "different lift" warning and a reason.
- The LLM sees only the filtered list and can never select class C.
- The shadow ranking can still show class C as information; it must not apply it.
- The existing one-substitution-per-slot and explicit opt-in remain.

### 5.5 Rollout

1. **Shadow audit** — classify the current candidate list and report pair classes/load deltas;
   change no prescriptions.
2. **Config** — add the comparability fields and a default class per configured pair.
3. **Opt-in confirmation** — enable class B confirmation in Prescribe/CLI.
4. **Only then** consider any automatic class A apply.

### 5.6 Acceptance criteria

- class C can never be applied automatically;
- class B requires a confirmation and records it;
- every applied substitution resolves load from the selected lift's id;
- no load, e1RM, or PRG-DP-001 citation is inherited from the old lift;
- no parent-ratio conversion without a validated, dated calibration;
- an unknown selected-lift history is shown as unknown, never filled from the old lift;
- tests use synthetic pairs for each class and an explicit different-implement case.

## 6. Open questions

1. Is bench pause/narrow a B (near) or can any pair ever be A? The load-velocity evidence says
   B is the safe default.
2. Is SSB <-> high-bar B, while SSB <-> front squat C? Both change mechanics; front squat also
   changes the load basis more substantially.
3. Should class be per exercise, per slot pair, or both? Pair-level is more precise but more
   configuration.
4. What counts as sufficient confirmation: one click, a typed reason, or both?
5. Are parent-variant e1RM ratios ever acceptable as a prior? If so, only after prospective
   validation and with a visible uncertainty interval.
6. Does the selector need a same-stimulus score, or is a hard class enough? A hard class is
   simpler and auditable.

## 7. Recommendation

Adopt the **three-class guard**, default all non-identical variants to **B**, and reserve **C**
for different implements/load bases. Keep variation available, but make the load-basis change
explicit and require confirmation before a prescription changes.

## 8. Implementation status

Implemented 2026-10-20:

- `config/selection-comparability.v1.yaml` defines load-basis groups, default B and explicit
  B/C pairs;
- `prescribe/selection.py` classifies candidates against the current lift and hides C unless
  `include_different` is requested;
- `prescribe/engine.py` applies only A automatically; B requires `selection_confirmed`; C is
  never applied by the selector;
- CLI `select` shows the class and `--include-different`; `run --selection-confirm` confirms B;
- the web Prescribe form has a near-comparable confirmation and a “show different lifts”
  checkbox; the selection panel shows class badges;
- tests cover default filtering, B confirmation, C blocking and selected-lift load resolution.

Still open: the exact A/B boundary for pause/narrow bench and SSB/high-bar, pair-vs-exercise
metadata, and any future parent-ratio prior.
