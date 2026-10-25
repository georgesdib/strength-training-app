# W3 — MODIFIER INTERACTION MATRIX

**Status:** audit completed and all six confirmed defects fixed 2026-10-23. Regression tests
in `tests/test_w3_interactions.py`.
**Scope:** readiness, continuity, deload, MRV/volume, constraints, back flare, selection and
minimum session.
**Method:** synthetic fixtures; no personal training data.

---

## 1. Approved intended precedence

The audit used the approved defaults:

1. hard constraints and injury ceilings;
2. **deload** as the planned/reactive reduction;
3. **one load factor**: the most restrictive of deload, readiness and continuity — no
   multiplicative stack;
4. **minimum session as the final volume ceiling**;
5. floors: accessory 1 set, main lift 2 sets;
6. essential/main-lift exercises are never removed; only sets can be reduced;
7. revalidate after every reduction path; the most restrictive safety rule wins.

The implementation now follows this order; the findings below record what the audit found
before the fix.

## 2. Confirmed findings

### W3-01 — RESOLVED — Deload is applied after minimum session and after validation

**Classification:** confirmed defect.

Current path:

```text
build_prescription:
  readiness
  continuity
  volume / MRV
  constraints
  minimum session
  warmup
  validate

caller (CLI/Web):
  deload.apply
```

`deload.apply` reduces sets/load/RIR after `validate_prescription` has already produced the
`issues` tuple. `Prescription.executable` only checks the stored issues and loads; it does not
recompute the rubric/RIR/spinal validation. A deload can therefore leave a prescription that
was never validated in its shown form.

### W3-02 — RESOLVED — Deload can add sets to a 1-set accessory

**Classification:** confirmed defect.

`deload.apply` uses:

```text
new_sets = max(minimum_sets, item.sets - set_reduction)
```

with `minimum_sets = 2`. If minimum session has reduced an accessory to 1 set, a later deload
**increases** it to 2:

```text
minimum session:  accessory 1 set
deload:           accessory 2 sets
```

That violates the approved floors and the rule that a modifier never adds work. The same
mechanism can undo an MRV cap.

### W3-03 — RESOLVED — Deload multiplies an already reduced load and exceeds the 20% guardrail

**Classification:** confirmed defect under the approved policy.

Synthetic fixture:

```text
normal main load:                 158.5 kg
low readiness main load:          134.5 kg   (~15% cut)
low readiness + deload:           121.0 kg   (~24% cut from normal)
```

The readiness/continuity cap is 20%, but the deload multiplier is applied afterwards. The
result is a second independent load reduction, not “the most restrictive single factor”.

### W3-03 residual — e1RM decay sits outside the 20% readiness cap  (accepted 2026-10-25)

The deload is no longer multiplicative: `apply_items` uses the most restrictive single factor.
A separate correction can still stack with readiness:

```text
e1RM decay 0.91 × readiness 0.85 = 0.7735   (~23% total)
```

`MOD-FAT-001`'s 20% cap applies to **readiness + continuity**, not to e1RM decay. That is
intentional: decay says the load basis itself is stale. A total 20% cap would leave the load
too high when both signals agree.

Displayed context: `PrescriptionItem.load_factor` and `Prescription.notes["load_stack"]` record
the cumulative factor; a warning is emitted when it falls below 0.80. The deload still does not
add a second cut when readiness is already stricter. No total cap is applied. See `LIM-42`.

### W3-04 — RESOLVED — Deload can push a main-lift RIR outside 1–4

**Classification:** confirmed defect.

Low readiness produced RIR 4 on the main lifts. Deload adds 1 RIR after validation:

```text
deload: main-lift RIR target = 5
```

`PRG-RIR-001` allows 1–4. No revalidation occurs, and the stored `issues` remain empty.

### W3-05 — RESOLVED — Deload can undo the MRV cap

**Classification:** confirmed defect.

With a high pull-up history, the MRV cap reduced `pull_up` to 1 set. A later deload raised it
back to 2. The final session exceeded the cap that had already been enforced.

### W3-06 — RESOLVED — Minimum-session note is stale after deload

**Classification:** confirmed defect.

For a 30-minute minimum:

```text
minimum note: estimated 34.5 minutes, status partial
after deload: estimated 27.5 minutes
```

The note still says 34.5 minutes and `MOD-MIN-001` says “load and RIR unchanged”, while the
deload later changed both. The warning sequence is internally inconsistent.

## 3. Cases that behaved as intended

| case | result |
|---|---|
| readiness alone | load/RIR/set reduction as configured |
| continuity alone | one RIR amendment; no duplicate load cut observed |
| MRV alone | non-essential accessory trimmed; no essential cut |
| minimum alone | main lifts preserved; accessory sets reduced or removed |
| minimum + hard constraint | refused; `status=unavailable`; no changes |
| back flare + minimum | main-lift RIR set to 3; no essential removal |
| scheduled + reactive deload | caller chooses reactive; no double deload |
| recent stress | advisory warning only; no load change |
| unknown readiness | no readiness cut; deload path unchanged |

## 4. Not fully exercised

- selection applied + deload + minimum;
- all MRV patterns;
- multiple simultaneous injury regions;
- exact warning consistency for every `MOD-*` combination.

These remain open for a fuller matrix, but the deload defects above already fail the W3 exit
criteria.

## 5. Priority

| priority | finding | why |
|---|---|---|
| P0 | W3-01 order/revalidation | a shown prescription can be invalid |
| P0 | W3-04 RIR 5 | violates a hard rule after validation |
| P0 | W3-02/W3-05 set increase | a reducer adds work / undoes MRV |
| P1 | W3-03 double load / cap | exceeds the intended single-factor/cap policy |
| P1 | W3-06 stale note | contradicts what is displayed |

## 6. Fixes implemented

1. Apply the deload **before** minimum session and final validation, or move both into one
   ordered pipeline.
2. Change deload set reduction to a one-way floor:

   ```text
   new_sets = min(item.sets, max(floor, item.sets - reduction))
   ```

   Never raise a set count.
3. Cap or reject deload RIR changes that leave the 1–4 window; revalidate.
4. Apply one load factor: the most restrictive of deload/readiness/continuity, not a product.
5. Recompute `issues` and `executable` after every post-build modifier.
6. Mark the minimum note superseded or recompute it after deload.
7. Add regression tests for all six confirmed findings.

Implemented in `prescribe/deload.py`, `prescribe/engine.py`, `prescribe/minimum_session.py`,
the CLI/server prescription callers and `tests/test_w3_interactions.py`.

Verification:

- `test_deload_never_increases_a_one_set_item`
- `test_deload_uses_one_load_factor_not_a_product`
- `test_deload_rir_cap_keeps_primary_compounds_in_window`
- `test_deload_does_not_undo_mrv_cap`
- `test_minimum_note_is_after_deload_not_before_it`
- `test_stacked_decay_readiness_and_deload_do_not_multiply`

Full suite at W3 audit time: 662 tests passed. Current counts live in `ROADMAP.md`.
