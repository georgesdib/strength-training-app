# W10 — AGE IN ATHLETE STATE

**Status:** audit complete 2026-10-23. No schema migration or prescription change.
**Question:** should age be stored, and what may it change?

---

## 1. Confirmed gap

`athlete_profile` has no age or birth-year field. `LONGEVITY-REVIEW.md` therefore says the
athlete's age is not recorded, while its power/balance advice is age-conditional.

This is a **state gap**, not a load defect. The engine currently has no age input and no
age-based rule, which is correct until a purpose is defined.

## 2. What the evidence supports

| area | evidence | what age changes |
|---|---|---|
| Strength / hypertrophy | adults respond across the lifespan; the 3–5 rep, RIR 2–3, progressive-overload principles do not change | **nothing automatic** |
| Power | power training modestly improves function vs strength training in older adults (SMD 0.30, low certainty); power declines with age | **priority/optional slot**, not a load multiplier |
| Balance / falls | balance and functional exercise reduces falls ~22%, strongest evidence in **60+** | **priority/optional work**, not a load multiplier |
| Recovery / load tolerance | individual and injury-dependent; age alone is a poor proxy | **no age-based load cut** |

The evidence is **age-conditional**, not a reason to prescribe a different strength programme
to an older lifter. A calendar age is not a recovery or 1RM model.

## 3. Options

### Option A — no age field; keep generic wording

- remove “age-dependent” claims from public guidance where no age is known;
- describe power/balance as **conditional** priorities, not personalized advice;
- no schema, no UI, no prescription change.

**Case:** minimal state and privacy; sufficient while age is not needed.
**Cost:** cannot tailor the rationale or prioritize the optional balance work.

### Option B — optional `birth_year` in `athlete_profile` (recommended if age is used)

Store `birth_year`, not current age, so age is derived on the prescription date.

Proposed schema (not migrated):

```sql
birth_year INTEGER
  CHECK (birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100)
```

- nullable; missing is `unknown`;
- profile stays append-only; a correction is a new row;
- derive `age_on(date)` in Python, never store a stale age;
- CLI/state/UI may accept it; it is local-only and never appears in public docs;
- **no load, RIR, set or session-type effect**.

Allowed uses:

- wording: “power/balance benefit is age-conditional; not established as necessary at this
  age”;
- prioritising an **optional** balance/power slot in narrative or suggestions;
- showing age context in the athlete state.

Forbidden uses:

- an age-based load multiplier;
- an age-based RIR or set cap;
- an age-based deload trigger;
- an automatic exercise exclusion;
- presenting population evidence as a personal prescription.

### Option C — store `age_years`

Rejected: age changes every year, so an append-only profile would need a new row annually and
old prescriptions would see a stale age. Birth year is stable; derive age.

### Option D — age-based load adjustment

Rejected. Age is not a validated individual load parameter; the current strength principles and
readiness/injury signals are the controlling inputs.

## 4. Recommended wording

Until an age is recorded:

> “Power and balance work have age-conditional evidence, strongest in older adults. They are
> low-cost optional priorities, not a personalized prescription.”

For an older athlete once age is recorded:

> “Plausible, cheap and low-fatigue at this age; not established as a necessary age-specific
> intervention.”

Do not write “at this age” when age is `unknown`.

`LONGEVITY-REVIEW.md` currently says the balance row is “age-dependent — priority 3”. That is
acceptable as an evidence label; it must not become a personal claim in the prescription.

## 5. Recommended decision

**Add nothing yet.** The programme has no age-based rule and does not need one.

If the athlete wants the optional power/balance rationale to be age-aware, choose **Option B**:
optional `birth_year`, derived age, wording/priority only, never a load multiplier.

## 6. Exit criteria

- The age gap is confirmed: **yes**, §1.
- The purpose is explicit and limited: **yes**, §2–3.
- No automatic age-based load reduction: **yes**, §3/§5.
- Schema and wording options are documented: **yes**.
- No migration or prescription change: **yes**.

No code, config, migration or prescription changed by W10.
