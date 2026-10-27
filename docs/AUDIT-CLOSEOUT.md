# ENGINE AUDIT — CLOSEOUT

**Status:** CLOSED 2026-10-23.
**Scope:** W0–W12 of [`ENGINE-AUDIT-PLAN.md`](ENGINE-AUDIT-PLAN.md).
**Later amendment:** `DEC-SPINE-05` (2026-10-25) raised the spinal cap from 3 to 6 and
counted the competition squat; the cap statements below describe the audited state at close.

**Meaning:** the planned audit work is complete. It does **not** mean every limitation is
closed; remaining limitations are tracked in
[`LIMITATIONS-REGISTER.md`](LIMITATIONS-REGISTER.md).

---

## 1. Workstream outcome

| workstream | outcome |
|---|---|
| W0 execution map | complete; execution map, owner order and test-coverage map |
| W1 attendance / rolling schedule | complete; forecast deload is build-time, session cap wired; family fallback remains a limitation |
| W2 load lineage | complete; bodyweight-basis and incomplete-workout defects fixed; e1RM source width added |
| W3 modifier interactions | complete; six confirmed deload/order/floor/RIR defects fixed and tested |
| W4 programme evidence | complete; every controlling rule classified; evidence labels added |
| W5 prospective evaluation | complete; protocol and read-only Outcomes review implemented |
| W6 readiness | complete; no-readiness counterfactual not identifiable; main-lift set reduction remains opt-in |
| W7 attendance metrics | complete; shared target-based attendance in Today/Outcomes |
| W8 volume balance | complete; 57-set split reconciled, four options documented, no change |
| W9 spinal cap | complete; explicit costs and at-cap display; cap remains 3 |
| W10 age | complete; optional `birth_year` proposed for wording/priority only; no age rule |
| W11 documentation | complete; one cap/count source, duration rubric 1.1.0, architecture contract |
| W12 public data | complete; exact sample counts generalised; Git history accepted, not rewritten |

## 2. Implemented during the audit

Only fixes with separate approval were applied:

- W1/W7: forecast-deload ordering and session-cap consumption; shared attendance.
- W2: shared load-basis resolver in workout materialisation, actual-only main lifts,
  incomplete flag, external-load tonnage, e1RM coverage field.
- W3: deload inside build, one-way floors, single load factor, RIR cap, MRV one-way,
  recomputed minimum note.
- W4: user-facing evidence labels.
- W5: `prospective` CLI/API and Outcomes panel.
- W9: explicit high-fatigue costs, cap/headroom display.
- W11: rubric 1.1.0 scores measured live duration.

## 3. Deliberately not changed

- readiness gate and weights;
- MRV/MEV/MAV values;
- spinal cap 3 at close and template volume (the cap was later raised to 6 by `DEC-SPINE-05`
  — see the header);
- main-lift readiness set reduction default (still opt-in);
- age-based load rules (none);
- stored planned calendar;
- Git history (no rewrite);
- cardio prescription (v0.5).

## 4. Remaining limitations

The register had **42 entries on 2026-10-25**, when that count was last updated (36 when the
closeout was written on 2026-10-24); it is a living list, and the current rows are in
[`LIMITATIONS-REGISTER.md`](LIMITATIONS-REGISTER.md). The important open ones are:

- readiness has no validated no-readiness counterfactual;
- no stored plan calendar;
- imported-session duration remains unmeasurable;
- last-working-load fallback is undecayed;
- spinal cap is ordinal and load-blind, with no headroom;
- the volume split is a bench-heavy strength-priority choice;
- age is not recorded;
- public Git history still contains earlier personal details;
- the prospective protocol has not yet been run for a full new block.

These are limitation records, not incomplete audit workstreams.

## 5. Exit criteria

- W0–W12 complete: **yes**.
- Confirmed defects either fixed or explicitly accepted: **yes**.
- Policy changes separated from evidence: **yes**.
- No new model adopted: **yes**.
- Open limitations visible and revisitable: **yes** — 36 entries when the closeout was written
  (2026-10-24), 42 on 2026-10-25; neither is a live count. The single current list is
  [`LIMITATIONS-REGISTER.md`](LIMITATIONS-REGISTER.md).

The next planned product work is **v0.5 — cardio depth and comparable calibration**, not
another audit slice.
