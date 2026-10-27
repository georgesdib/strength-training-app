# W9 — SPINAL-CAP HEADROOM

**Status:** audit complete 2026-10-23; W9 recommendations implemented. No cap change was made by
that audit.
**Superseded in part 2026-10-25:** `DEC-SPINE-05` raised the cap from **3 to 6**, counted the
low-bar competition squat at cost 1, and replaced the bench+hinge support with a 3x3-5 sumo
deadlift at 2.5. Everything in §§1–7 is the audit state at close (cap 3) and is kept as
historical evidence; see §8 for the current state.
**Follow-up 2026-10-25:** the engine has a one-directional remedy for the at-cap week this
report documents. `MOD-SPINE-001` removes a non-essential high-fatigue spinal item (in practice
the erector slot) when that alone brings the week to the cap; when the overage is carried by
essential lifts the veto stands and the issue names the exposures (`DEC-SPINE-03`).
**Method:** template arithmetic plus stored weekly spinal costs. Exact personal counts are in
`private/docs/PRIVATE-CONTEXT.md`; this public report gives the shape only.
**Scope:** `PRG-SPINE-001`, normal weekly programming and the reactive deload trigger.

---

## 1. What the rule currently does

`PRG-SPINE-001`:

- groups a week by ISO week;
- counts each distinct **(session, exercise)** once;
- uses the configured ordinal `spinal_cost` for high-fatigue spinal exercises;
- sums those costs;
- vetoes a proposed session if the week exceeds `cap: 3`.

It does **not** count sets, load, RIR or tonnage. A 12-set trap-bar session and a 3-set
trap-bar session have the same spinal exposure. That is deliberate (`ASSUMPTION-02`) but is
load-blind.

The reactive deload trigger requires **two consecutive weeks strictly greater than 3**. An
exact-cap week (3.0) does not trigger it.

## 2. Normal template week

The three-session normal cycle is:

```text
squat (back_extension 1)
hinge (trap_bar_deadlift 2)
bench_squat (no counted spinal work)
= 3
```

or:

```text
squat (back_extension 1)
hinge (trap_bar_deadlift 2)
bench_hinge (single_leg_db_rdl — currently uncounted)
= 3
```

**The normal week is designed to land exactly on the cap.**

That is the structural finding: there is no headroom in the standard cycle. Any additional
counted spinal exposure in the same week either:

- reaches 3.0 exactly (still no reactive trigger), or
- exceeds 3 and is vetoed if proposed in a prescription.

## 3. Frequency in stored history

The historical log contains:

- weeks below the cap;
- a meaningful group exactly at the cap;
- a substantial group above the cap;
- a small number of high-cost historical weeks.

Exact counts and the full distribution are intentionally kept in the private appendix. The
public shape is enough to answer the audit question: **exact-cap weeks are common, and
over-cap weeks occur in the stored record.** Historical over-cap weeks do not retroactively
invalidate current prescriptions.

The important distinction:

```text
exact cap:        no reactive trigger
above cap:        prescription veto if proposed
two consecutive > cap: reactive deload trigger
```

## 4. Confirmed findings

### W9-01 — The normal cycle has zero headroom

**Classification:** confirmed structural design.

The standard squat + hinge + bench-support week sums to 3 against a cap of 3. This is not a
calculation error; it is the current template design. It means the cap is both:

- a normal-week ceiling, and
- a limit that any extra spinal work immediately tests.

### W9-02 — Exact-cap weeks do not trigger the reactive guard

**Classification:** confirmed behaviour.

The guard requires `> cap`, not `>= cap`. A week at exactly 3.0 is treated as safe. That is
consistent with a cap as a maximum, but it leaves no signal that the normal week is already at
the ceiling.

### W9-03 — RESOLVED — Several `high_fatigue_spinal` entities had no `spinal_cost`

**Classification:** confirmed config/code inconsistency; resolved.

`spinal_exposures` uses:

```text
cost = explicit rule cost, else entity spinal_cost
```

If both are absent, the entity is silently skipped even when
`high_fatigue_spinal: true`. This affects:

- many deadlift variants/block pulls;
- `single_leg_db_rdl`, which appears in the bench+hinge template;
- `kettlebell_swing`, which is excluded by pattern but still lacks a cost.

The omission of `single_leg_db_rdl` is material: it is currently the reason a bench+hinge week
still sums to 3 rather than 5. If a cost were assigned without changing the template or cap,
the normal bench+hinge week would exceed the cap.

Resolution:

- all deadlift/deficit variants received explicit conservative `spinal_cost: 3`;
- `kettlebell_swing` received an explicit cost even though its pattern is excluded;
- `single_leg_db_rdl` is explicitly non-counting (`high_fatigue_spinal: false`,
  `spinal_cost: 0`) with a reason.

The single-leg decision is an engineering classification, not a measured zero. Unilateral
loading changes trunk/hip activation versus bilateral work, but there is no direct lumbar-load
comparison. See [Frontiers 2023](https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2023.1264604/full).
It stays in the bench+hinge template as a hamstring/hip accessory and does not consume a
spinal slot. If future evidence says otherwise, that is a separate template/cap decision.

### W9-04 — The 2.5 sumo half-step can change a borderline week

**Classification:** assumption-dependent.

The half-step is a programme-owner choice, not a measurement. If sumo is used, a week at 2.5
plus one back-extension exposure becomes 3.5, above the cap. This is transparent in config but
not evidence-based.

### W9-05 — The current guard is ordinal, not a dose model

**Classification:** confirmed limitation.

The cap cannot distinguish:

- 3 heavy trap-bar sets from 12;
- 3 RIR 0 sets from 3 RIR 3 sets;
- a 2.5 sumo exposure from a 3 conventional exposure.

It is a conservative exposure ledger, not a load/RIR model. Do not present it as a measured
injury threshold.

## 5. Options

### A. Leave the cap and template unchanged

- Document the zero-headroom normal week.
- Keep the reactive trigger at two consecutive `> 3` weeks.
- Accept that ordinary programming sits at the ceiling.

**Benefit:** no new unvalidated policy. **Risk:** no early warning before the veto.

### B. Add explicit headroom (e.g. cap 4)

- Lower the chance that a normal variation hits the veto.
- Weakens the safety ceiling without evidence.

**Not recommended without a separate decision.**

### C. Treat the cap as ordinal exposure count

- Count distinct exercises rather than weighted costs.
- Removes the fractional sumo issue.
- Almost never fires, making it decorative.

**Not recommended.**

### D. Fix the missing costs and adjust the template

- Give every `high_fatigue_spinal` entity an explicit cost or explicit zero.
- If `single_leg_db_rdl` counts, change the bench+hinge template or accept that week is over.
- Requires W8 volume/template decision.

**Recommended prerequisite** before any cap change.

### E. Leave the cap, improve the warning

- Keep cap 3.
- Surface “at cap” and “one exposure of headroom” in the prescription/UI.
- No load change.

**Implemented.** `notes.spinal_cap` now reports cost, cap, headroom and at/over-cap state;
Prescribe shows it.

## 6. Implemented recommendation

1. **Cap unchanged at 3; no headroom added.**
2. Every `high_fatigue_spinal` entity now has an explicit `spinal_cost`.
3. `single_leg_db_rdl` is explicitly non-counting, with a reason; the template stays unchanged.
4. `notes.spinal_cap` and the Prescribe UI show cost/cap/headroom and at/over-cap state.
5. The reactive trigger remains two consecutive strictly over-cap weeks.

## 7. Exit criteria

- exact-cap and over-cap frequency measured: **yes**, aggregate shape and private counts;
- cause of excess identified: **yes**, template arithmetic and missing costs;
- ordinality/headroom options presented: **yes**;
- no silent cap change: **yes**.

No cap or template change. Config, notes and UI were changed as above; tests cover the
cost completeness and the cap note.

---

## 8. Current state (2026-10-27)

The cap is **6**, not 3. The historical analysis above explains why 3 was the audited state;
this section is the live summary and takes precedence where they differ.

- `PRG-SPINE-001.params.cap: 6` in `config/rules/programme.v1.yaml`.
  The default is 6; the cap and per-exercise costs are editable in Settings (`DEC-SPINE-06`),
  guarded by a warning, typed confirmation and a required reason.
- The **low-bar competition squat counts at cost 1** (`DEC-SPINE-05`); the safety-squat bar and
  high-bar squat stay outside the cap by explicit exercise identity (`ASSUMPTION-39`).
- The **bench+hinge support is a 3x3-5 sumo deadlift at cost 2.5**, replacing the non-counting
  `single_leg_db_rdl` (`DEC-SPINE-05`).
- With the current templates a normal week is **4/6** (squat + hinge + bench+squat) or
  **5.5/6** (squat + hinge + bench+hinge), not the 3/3 documented above. `MOD-SPINE-001` still
  trims a non-essential erector slot when that alone resolves an overage (`DEC-SPINE-03`).
- The reactive deload still requires **two consecutive weeks strictly greater than the cap**;
  an exact-cap week does not trigger it. That behaviour did not change when the cap moved.
- The limits in §4 (W9-05) still hold: the sum is ordinal, load-blind and counts one exposure
  per (session, exercise), not sets or RIR. A cap of 6 is a programme-owner number, not a
  measured safety threshold ([SPINAL-COST.md](SPINAL-COST.md), `ASSUMPTION-02`).

The original cap-3 analysis is retained above because it documents the zero-headroom finding
that motivated `DEC-SPINE-03`, and because the frequency data in §3 is still the evidence base
for the ordinal model.

## Related

- **Evidence:** [SPINAL-COST.md](SPINAL-COST.md), [SPINAL-LOAD-EVIDENCE.md](SPINAL-LOAD-EVIDENCE.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md) (`DEC-SPINE-03/04/05/06`)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) (Q2, Q24)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
