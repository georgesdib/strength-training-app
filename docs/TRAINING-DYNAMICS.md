# TRAINING DYNAMICS — testing, rep ranges, and undulation

This note collects the evidence behind three questions the athlete asked: whether occasional
1RM testing is worth it, whether rep counts should be adjustable, and whether daily undulating
periodization (DUP) and readiness-driven variation belong in the programme. It is a design note,
not a decision record; decisions live in `docs/DECISIONS.md`.

---

## 1. Occasional 1RM testing

**What the evidence supports**

- Maximal strength is a meaningful health marker. A meta-analysis of 39 studies (39,852
  participants) found the lowest strength category had a hazard ratio of 1.80 for all-cause
  mortality versus the highest, and each 5 kg of strength was associated with HR 0.72
  (Jochem et al., *JAMDA* 2019, doi:10.1016/j.jamda.2019.05.015). Association, not proof that
  testing causes longevity — but it supports keeping strength measurable.
- Actual 1RM testing is a standard assessment in trials and is generally considered safe in
  healthy, resistance-trained adults. Direct data on injury rates are thin.
- Risk is not zero. A vertebral fracture during 1RM leg-press testing has been reported in an
  older breast-cancer survivor with previously unknown osteoporosis (Rosenberger et al.,
  *Medicine* 2021, doi:10.1097/MD.0000000000025705). Reviews of testing in older adults describe
  1RM testing as time-consuming and carrying injury risk, and validate velocity-based
  alternatives instead (Deboutte et al., *Exp Gerontol* 2026, doi:10.1016/j.exger.2026.113174).
- Submaximal estimates are good enough for programming. A 3-5RM test plus the RIR-adjusted
  Epley formula gives an e1RM within the precision the load solver uses (it rounds down to
  0.5 kg anyway). Velocity-based estimation can be equivalent to measured 1RM when the
  load-velocity profile is individual (Deboutte 2026), but general profiles are less reliable.

**Recommendation for this athlete**

- Test **3RM or 5RM**, not a true single: same information for load prescription, far less
  spinal load, and it fits the existing e1RM override mechanism (`source = measured`).
- Cadence: every **8-12 weeks**, or when the solver's e1RM and the athlete's perceived effort
  diverge for several sessions — not on a fixed calendar week.
- Always with safeties, never on the trap bar (the hinge day already carries the highest spinal
  cost), and never during a back-flare window.
- A true 1RM stays possible but should be an explicit, declared exception, not a routine.

**Open issue:** `PRG-RIR-001` forbids "max singles and 1RM testing inside a block". With no fixed
block (DEC-PROGRAMME-01), "inside a block" is currently always true, which bans testing forever.
A test-session exception needs defining before a `test` command can exist.

---

## 2. Rep ranges — fixed, or adjustable?

Today reps are fixed per template slot (e.g. 3-5 on main lifts, 8-12 on accessories), and the
model may not change them. That is a design choice, not an evidence claim.

**What the evidence supports**

- **Strength** is specific to heavy loading: lower-rep, higher-load training produces larger 1RM
  gains than low-load training when effort is matched; high- and low-load training differ in
  non-specific strength too (Hammert et al., *Sports Med* 2026,
  doi:10.1007/s40279-025-02370-8).
- **Hypertrophy** is similar across a wide rep range when sets are taken close enough to failure
  and volume is matched; the practical band is roughly 5-30 reps, with low loads requiring more
  proximity to failure.
- **Longevity / health**: the benefit comes from being strong and trained, not from a specific
  rep bracket. Moderate loads (roughly 6-12) with RIR 1-3 capture most of the strength and mass
  benefit at lower joint and fatigue cost; some heavier work preserves the strength-specific
  stimulus.
- **Readiness** interacts with reps: at low readiness the same load is closer to failure, which
  is why the fatigue modifier cuts load rather than reps.

**Recommendation**

- Keep the current day character (A squat-led, B hinge, C bench-led) but make the rep range a
  **menu of validated schemes** rather than a single fixed pair, e.g. `strength` (3-5),
  `volume` (6-8), `accessory` (8-12), each with a solver-computed load.
- The model may **choose a scheme** (menu), never write a rep number; Python computes the
  matching load.
- Do not let a single session move reps arbitrarily: variation belongs at the day/week level,
  so the block still has a coherent stimulus.

---

## 3. DUP and readiness-driven variation

**What the evidence supports**

- Linear and undulating periodization produce **comparable** strength and body-composition
  outcomes in a 29-study meta-analysis (Zhang et al., *Front Public Health* 2026,
  doi:10.3389/fpubh.2026.1707627); undulating was better only for lean mass in obese
  participants in short-term subgroups. In older adults, traditional and undulating training
  also improved strength and fat-free mass similarly (Vargas-Molina et al., *IJERPH* 2022,
  doi:10.3390/ijerph19084522).
- Autoregulated load (RIR- or velocity-based) versus standardized percentage prescription showed
  **no significant difference** in 1RM strength (MD 2.07 kg, 95% CI -0.32 to 4.46, p = 0.09) in
  a 15-study meta-analysis (Hickmott et al., *Sports Med Open* 2022,
  doi:10.1186/s40798-021-00404-9); velocity-loss thresholds ≤25% were favourable for some
  outcomes.

**What that means, honestly**

- DUP is **not superior** to linear periodization in the literature. It is a legitimate way to
  organise variety and manage fatigue, and it may help adherence; it should not be sold as a
  strength advantage.
- Readiness-based adjustment is **not proven to beat** fixed prescription either. It is a
  sensible way to avoid bad-day grinding, and it fits the athlete's longevity goal, but its
  value is fatigue management rather than extra gains.
- Therefore: implement DUP and readiness variation as **configurable structure**, not as a
  claimed optimisation, and keep the deterministic rules (RIR window, spinal cap, deload
  triggers) above them.

---

## 4. Proposed shape (needs a decision before building)

1. **`test` session type — implemented (`DEC-TEST-01`).** `strength-coach test` records a
   3RM/5RM (or a `--max` 1RM with confirmation) as a `measured` e1RM override, with a 28-day
   warning for submaximal tests and a 56-day limit for 1RM tests unless `--force`. The test set
   is not logged as training volume, and `--e1rm` lets the athlete override the computed value.
2. **Rep scheme menu — implemented (`DEC-REPS-01`).** Named schemes: `maximal` (1-3),
   `strength` (3-5), `volume` (6-8), `accessory` (8-12). The model may name a scheme, never a
   number; Python re-solves the load for it. `maximal` is excluded on hinge lifts: a
   near-maximal trap-bar pull is the highest-risk exposure in this programme.
3. **Weekly undulation — implemented (`DEC-UNDUL-01`).** A 4-week config cycle keyed to the
   declared anchor: week 3 main lifts at `maximal`, weeks 2/4 accessories at `volume`. With no
   anchor there is no cycle. It is variety/fatigue management, not a claimed advantage.
4. **Readiness response.** Keep MOD-FAT-001 as the load cut; add an optional "reduce one set when
   readiness is poor" modifier, config-gated.

Each of these changes what is prescribed, so each needs a `DEC-` row and an acceptance test.

---

Test/high-intensity exposure: [`HIGH-INTENSITY-EXPOSURE-PLAN.md`](HIGH-INTENSITY-EXPOSURE-PLAN.md).

Readiness/injury and scheme selection: [`WORKOUT-TYPE-READINESS-EVIDENCE.md`](WORKOUT-TYPE-READINESS-EVIDENCE.md).

Full bibliography with DOIs: [`docs/REFERENCES.md`](REFERENCES.md).
