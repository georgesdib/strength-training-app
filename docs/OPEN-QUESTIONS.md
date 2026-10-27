# OPEN QUESTIONS — ranked by how much they change the design

These are genuine ambiguities in the programme brief, the data, or both. Each states the
default this project will implement if nobody answers, so a missing answer is survivable and
produces an `unknown` verdict rather than a silent guess.

> Quantitative evidence for each question is kept out of this public repository. The
> questions themselves are methodology questions and apply to any athlete using the system.

**Live register (2026-10-27):** one open question (Q14) and one deferred decision (Q22).
The 22 questions decided since the register was created were removed from the live text on
2026-10-25; each outcome and decision record is indexed under
[Closed](#closed--index-only). Reopening a closed question is a new decision, not an edit.

---

## Q14. What cardio load and fatigue model should the app use?

Planned in ROADMAP §4.13. Open: which modalities, whether TRIMP or sRPE is the impulse,
two vs three fatigue systems, whether cardio modifies load or only readiness context, and how
many weeks of individual data are needed before showing a time constant. No implementation.

---

## Q22. Should selection target weakness or injury?

**Deferred 2026-10-20; earliest review after v0.5 (~April 2027).** No positive
weakness/injury targeting. Injury remains a constraint/ceiling/penalty; it must never boost a
candidate. A relative-weakness display, if added, is display-only. Revisit only with 12
sessions per target lift over 12 weeks, a pre-registered weakness definition, a retrospective
baseline win, and an opt-in N-of-1/alternating test. See
[WEAKNESS-INJURY-SELECTION.md](WEAKNESS-INJURY-SELECTION.md) and the gated
[WEAKNESS-TARGETING-PLAN.md](WEAKNESS-TARGETING-PLAN.md).

---

---

## Closed — index only

Removed from the live register on 2026-10-25. Each row names the outcome and where it is
enforced; the reasoning lives in the decision record and the linked document.

| Q | question | outcome | decision / evidence |
|---|---|---|---|
| Q1 | Do sessions have timestamps? | date-only accepted; one session per calendar date; ambiguous composition stays `unknown`; imported duration unmeasured | owner acceptance 2026-10-25; `docs/DATA-QUALITY.md` |
| Q2, Q8 | What is one "high-fatigue spinal exposure"? | one high-fatigue exercise per session, weighted by `spinal_cost`; cap was 3, raised to 6 on 2026-10-25; kettlebell swings excluded | `DEC-SPINE-01`, `DEC-SPINE-05`, `ASSUMPTION-02`, `docs/SPINAL-COST.md` |
| Q3 | How is the erector ramp anchored? | explicit `athlete_profile.block_start_date`; `--force` restarts at week 1; a missing symptom reading stays `unknown` | `DEC-RAMP-02`, `docs/DECISIONS.md` |
| Q4 | Is there a symptom input? | manual pre-session 0-3 back level in `symptom_log`; missing stays `unknown` | `DEC-SYMPTOM-01/02` |
| Q5 | Is session duration measurable? | imported sessions unmeasurable; live workouts store measured duration; optional review length | rubric 1.1.0, `session_feedback.duration_min` |
| Q6 | How do readiness rows merge, and is the composite authoritative? | most-complete row, latest tie-break, manual wins; `composite` stays null and the score is separate and non-authoritative | `DEC-READINESS-01`, `ASSUMPTION-04` |
| Q7 | Does "RIR 2-3" forbid easier sets? | floor-only veto: RIR 0, below window and near-max singles fail; above-window sets are reported only | `DEC-RIR-03`, `docs/RIR-EVIDENCE.md` |
| Q9 | Can the RIR window widen? | window is RIR 1-4 with a 2-3 target; changing it is a constitution change | `DEC-RIR-02`, `docs/RIR-EVIDENCE.md` |
| Q10, Q11 | Is the sumo deadlift an accessory? | replacement for the trap-bar hinge only; its 2.5 spinal cost is an accepted ordinal choice, not recalibrated | `DEC-TRAPBAR-03`, `DEC-SPINE-01` |
| Q12 | Can re-entry be calibrated from returns? | calibrated factor rejected (MAE 0.150 vs 0.128); fixed 14/28/56-day bands, +1 RIR, −5%/−10% remain | `DEC-CONTINUITY-02/03`, `docs/RETROSPECTIVE-VALIDATION.md` |
| Q13 | Is four weeks the right back-signal window? | window scales with prior flares (28 d + 14/flare, cap 84); "tolerated" needs a clean reading; region-specific lift links | `DEC-INJURY-01/02/03`, `docs/INJURY-SIGNAL.md` |
| Q15 | Dedicated core work, and at what dose? | two reps-based slots; both in `accessories_and_back_extension` so `PRG-DP-001` progresses them | `DEC-CORE-01`, `docs/CORE-TRAINING.md` |
| Q16 | Why was `PRG-DP-001` never assessable? | rep ranges pool across all templates (`all_rep_ranges`), so every scoped accessory is assessable | answered 2026-10-20; `docs/CORE-TRAINING.md` §5.4 |
| Q17 | Pulling and power slots? | vertical-pull variant slot and `box_jump` power slot added | `DEC-PULL-01/02`, `DEC-POWER-01` |
| Q18 | Which longevity metrics? | append-only `measurement` table with a config catalogue; none changes a load | `DEC-MEASURE-01` |
| Q19 | Should a fatigue-fitness model drive loads? | no; shadow-only and no load effect; the predictive model is closed | `DEC-FFM-04`, `DEC-STRESS-01`, `DEC-SRPE-01`, `docs/FATIGUE-FITNESS.md` |
| Q20 | Calibrate e1RM against test results? | bounded correction only when the CI excludes 1.0 and the bias is within ±10%; measured overrides win | `DEC-E1RM-CAL-01/02` |
| Q21 | What counts as comparable for selection? | three-class A/B/C guard; A is automatic aliases only, B needs confirmation, C is never automatic | `DEC-SELECT-03`, `docs/SELECTION-COMPARABILITY.md` |
| Q23 | Does a first-set RIR drop trigger a load cut? | no; never implemented, inside RIR reporting error, removed from `MOD-FAT-001` in constitution 1.13.0; the mean-RIR per-lift component remains | `DEC-RIR-04` |
| Q24 | Should the low-bar competition squat count toward the weekly spinal cap? | yes, at cost 1; the cap rises 3 to 6, and bench+hinge uses sumo at 2.5 | `DEC-SPINE-05`, `docs/SPINAL-COST.md` |
| Q25 | Does a level-1 reading with no settle answer count as a flare? | yes: only a recorded 48 h settlement clears a level 1, so an unrecorded answer fails safe | `DEC-SYMPTOM-04`, `docs/SYMPTOM-LOGGING.md` |
| Q26 | Does volume respond to programme frequency or an incomplete session? | **Closed 2026-10-27.** Frequency remains dates-only (1–3 scheduled sessions keep the normal template; no per-session scaling or extra sessions). Incomplete/low-volume sessions are handled by the live volume budget through policy-specific accessory top-up/under-MEV; `preserve` is the mode where ordinary accessory make-up applies. No automatic heavy-session cut. | `DEC-VOLUME-06`, live budget, [FREQUENCY-AND-VOLUME.md](FREQUENCY-AND-VOLUME.md) |
| Q27 | Should filled groups reallocate volume across groups? | strength-preserving default; main lifts stay; accessory-only compensation under `preserve`; volume-first `drop` deferred; compensation slot pool and weights agreed | `DEC-VOLUME-08/09`, VOLUME-MODULATION-PLAN §4.2 |
| Q28 | Should a personalised volume-response model drive volume? | not now: future shadow-only model with interval/confidence and a pre-registered prospective gate; fixed budget and safety guards remain authoritative until then | `DEC-VOLUME-29`, VOLUME-MODULATION-PLAN §13 |
| Q29 | How should the volume ledger treat a week with no working sets? | implemented 2026-10-27: calendar-window denominator; `volume.ledger.coverage=complete` zero-fills; breaks/deloads reset the under-MEV clock; under-MEV requires all eligible weeks to be training weeks. The live profile is complete | VOLUME-MODULATION-PLAN §14 |

---

## Decisions taken as defaults unless told otherwise

- Training rows are **never** deduplicated — repeated identical rows are real sets.
- ACWR is advisory only and may never veto a prescription (the "sweet spot" reading is
  contested).
- Within-set velocity loss is reported as *not measurable*, with a labelled set-to-set decay
  proxy instead.
- Exercise-rotation scoring is split by session provenance, because in a real export the
  logging app deliberately rotates variations while self-directed sessions are stable.
