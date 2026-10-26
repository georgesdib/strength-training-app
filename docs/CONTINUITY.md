# CONTINUITY AND BACK SIGNAL

Two related rules that keep the programme honest about time: what to do after a gap, and what
the app may say about back recovery. Both were decided with the athlete and are implemented in
the engine; the open questions are at the end.

---

## 1. Continuity after a gap

### What the evidence says

- **Two weeks of cessation** already reduced fast-concentric and eccentric knee strength in
  trained sprinters ([Yamashita et al. 2023](https://doi.org/10.1371/journal.pone.0288344)).
- **Eight weeks of cessation** reduced strength and power adaptations in cyclists
  ([Rønnestad et al. 2016](https://doi.org/10.1123/ijspp.2015-0372)).
- **Muscle size is retained longer** than strength in older adults: no significant loss at
  12-24 weeks, significant loss at 31-52 weeks ([Grgic 2022](https://doi.org/10.3390/ijerph192114048)).
- There is **no clean meta-analysis of cut-points**. The thresholds below are adapted from
  these findings, not measured (`ASSUMPTION-07`).

### The rules (implemented)

| gap | adjustment |
|---|---|
| < 14 days | none |
| 14-27 days | keep load; +1 RIR for the first week back |
| 28-55 days | load −5%; +1 RIR |
| ≥ 56 days | load −10%; +1 RIR; erector ramp steps back one stage |

- The gap is measured from the **last stored session** to the prescribed date; no declaration
  is required.
- Every amended item cites `MOD-GAP-001`, and the prescription warns e.g.
  *"MOD-GAP-001: 31-day gap; prescription amended"*.
- **Bodyweight work** cannot shed load, so it loses one set instead.
- **DUP**: only weeks with a session (or a measured test) count. A missed week does not advance
  the cycle.
- **Erector ramp**: pauses during the gap; after the long break it steps back one stage. Rest
  settles symptoms but does not build load tolerance.

### Declared breaks (implemented 2026-10-26)

A break is a date range the athlete declares — holiday, deload, test week, other — recorded
append-only (`strength-coach break`, or the Athlete page). It exists for the week that **was
trained but must not count**: an untrained week is already skipped by the trained-week index,
so declaring a holiday changes the record and the display, not the arithmetic.

- **Freeze.** Every ISO week that contains at least one break day is removed from the
  trained-week count, so neither the DUP cycle nor the erector ramp advances inside it. One
  declared day freezes its whole week — that is the assumption, not a measurement.
- **Cancellation.** A mistake is cancelled by appending a row that names the row it cancels;
  nothing is edited or deleted, and the cancelled break stays visible in history.
- **No effect on load.** The gap rules above still apply when training resumes: a declared
  break does not replace `MOD-GAP-001`, and it never changes a load, RIR or set.
- **Not shifted:** the **scheduled-deload clock** still counts calendar weeks from the block
  start, so a long break does not move it (`LIM-50`).

Decision record: `DEC-CONTINUITY-04`.

### Retrospective walk-forward (2026-10-20)

On 12 observed returns, the calibrated factor had ratio MAE 0.150 versus 0.128 for the fixed
rule; the calibrated version lost. The fixed fallback therefore remains in use. This is
retrospective, not prospective; see [RETROSPECTIVE-VALIDATION.md](RETROSPECTIVE-VALIDATION.md).

### Open questions — parked for calibration

The arithmetic is frozen (`DEC-CONTINUITY-02`) and these are inputs to the calibration in
ROADMAP §4.12, not things to change by opinion:

1. Is −5%/−10% right, and should the reduction apply to sets as well as load?
2. Does bodyweight work need a different rule from barbell work beyond losing a set?
3. Should a measured test count for the **erector ramp**? It already counts in the trained-week
   index, so the ramp advances today; a test is high load but low volume, so this is unresolved.

---

## 2. Back-progression signal (now one region of the injury signal)

The single back summary was replaced on 2026-10-19 by a general signal plus one per region
(low back, biceps, knee, extensible in config). The back rules are unchanged and still read
**low back only**. The full design, evidence and definitions are in
[INJURY-SIGNAL.md](INJURY-SIGNAL.md); this section keeps only what continuity needs.

### What the evidence says

- Relapse after an episode of low back pain is **common**: 69% within 12 months in a
  prospective inception cohort, median 139 days
  ([da Silva et al. 2019](https://doi.org/10.1016/j.jphys.2019.04.010)); 38% in another cohort
  ([Huang et al. 2025](https://doi.org/10.1002/ejp.4793)).
- **More than two previous episodes predict recurrence** (da Silva 2019), which is why the
  window scales with prior flares rather than being fixed (`DEC-INJURY-02`).
- There is **no evidence that four symptom-free weeks means clearance**. Four weeks is the
  base of a configurable window (`ASSUMPTION-06`, `ASSUMPTION-08`).
- Rest helps symptoms but does not preserve strength; the signal therefore counts **loaded
  sessions**, not calendar.

### The rules (implemented)

- Status is one of `unknown` (no entries), `insufficient` (last entry older than 14 days),
  `active` (latest reading is a flare), `monitoring`, or `review`.
- `review` requires the **scaled** symptom-free window and the **scaled** number of
  **tolerated** loaded sessions since the last flare, with a current level of 0.
  Base: 28 days and 4 tolerated sessions; +14 days and +2 sessions per prior flare, capped at
  84 days and 12 sessions.
- A loaded session is **tolerated** only when a reading exists in the 7 days after it and no
  reading in that window is a flare. An unlogged session is `unverified` and never counts.
- Readiness is **excluded**: it already drives `MOD-FAT-001` and is the wrong signal for a
  structural judgement.
- The signal may **recommend** reviewing a suitability rating; it never sets one, never clears
  a constraint, and never substitutes a lift.
- Every display carries: *"Not medical clearance. A symptom-free streak is weak evidence; the
  athlete decides..."*
- It is shown by `state` and in the prescription notes.

### Open questions

The former three (window length, tolerated-loading definition, per-lift detail) were answered
on 2026-10-19: the window scales, tolerance means "loaded and followed by a clean reading", and
the signal names the lifts that load the region. What remains is calibration, not design: the
step sizes and the 7-day verification window are assumptions, and
[INJURY-SIGNAL.md](INJURY-SIGNAL.md) §7 lists what would replace them.

---

Full bibliography: [`docs/REFERENCES.md`](REFERENCES.md) §6 and §7. Decisions:
`DEC-CONTINUITY-01`, `DEC-CONTINUITY-02`, `DEC-BACKSIGNAL-01`, `DEC-INJURY-01/02/03`.
Implementations: `prescribe/engine.py` (`_apply_continuity`, `_injury_warnings`),
`features/injury_signal.py`.


---

## 3. Calibration from real returns (implemented 2026-10-20)

`features/continuity_calibration.py` estimates, per fixed band (short/medium/long), the ratio
of the first return session's best working e1RM to the last pre-gap session's best working e1RM
for the same lift. A return pair is excluded if the gap is outside the configured range or the
ratio is implausible.

Each band reports:

- number of returns;
- median retention and a deterministic bootstrap 95% interval;
- the fixed factor and the applied factor;
- `ok`, `insufficient`, `uncertain`, `disabled` or `report_only`.

A calibrated factor is applied only when the band has at least `min_returns_per_band` and the
whole dataset has `min_total_returns`, the interval is no wider than `max_ci_width`, and
calibration is enabled. Otherwise the fixed 14/28/56 rule is used. The factor is bounded to
`[factor_floor, 1.0]`; `allow_relax_fixed` decides whether the model may remove part of a fixed
reduction. The config is `config/continuity-calibration.v1.yaml`; `MOD-GAP-001` remains the cited
rule and the warning names the calibrated factor and its return count. `allow_relax_fixed` can
be changed from the Prescribe continuity panel or with `continuity --allow-relax-fixed on|off`.

This is **strength retention**, not capacity retention, and not the e1RM age decay. A future
capacity curve needs post-session fatigue/completion data; the current model only uses e1RM
observations already in `clean_set`. `strength-coach continuity` and the Prescribe continuity
panel show the report; `GET /api/continuity` is the same data.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
