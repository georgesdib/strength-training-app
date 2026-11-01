# TECHNIQUE THROTTLE — MOD-TECH-001

**Status:** implemented 2026-10-25.
**Nature:** a user-declared, one-session reduction of load and effort. It reads no form
rating, stores no state, and cannot fire on its own.

---

## 1. Why this exists

The athlete sometimes finishes a lift knowing the technique was not what it should be. The
useful response is a deliberately lighter working session — not a rule that infers a problem
from a self-rating.

An earlier proposal (`MOD-FORM-001`) made the inference automatic: a `form_rating` below 3.0
would cap load and RIR, and the flag would persist at movement-pattern level until a better
rating arrived. It was **not** implemented, for the reasons in
[`FORM-USE-EVIDENCE.md`](FORM-USE-EVIDENCE.md) and `DEC-FORM-01`–`05`: the rating is optional
and not validated as a technique measure, the evidence does not link it to injury or
next-session performance, and a pattern-level latch would keep reducing loads after the
athlete stopped rating.

`MOD-TECH-001` keeps the useful part — a bounded throttle on the movements that felt off —
and moves the trigger to the athlete. It is a request, like the minimum session, not a
derived rule. No `form_rating` is read anywhere in the path.

## 2. User flow

UI:

```text
Prescribe → tick Technique throttle → select one or more movement patterns from the
multi-select → build. Keeping "All lifts (main work)" selected adds the main work to any
selected patterns; deselect it to throttle only the named patterns.
```

The API takes the same two fields (`technique_throttle`, `technique_throttle_pattern`)
from `POST /api/prescribe`; `technique_throttle_pattern` may be one pattern or a list.
The UI form above is a thin wrapper over it.

CLI:

```bash
strength-coach run --date 2026-10-23 --technique-throttle
strength-coach run --date 2026-10-23 --technique-throttle --throttle-pattern squat
strength-coach run --date 2026-10-23 --technique-throttle \
  --throttle-pattern squat --throttle-pattern horizontal_push
```

It is never selected automatically, and it is not offered from the calendar or the
programme forecast: it is a decision about one session.

## 3. What it changes

| setting | default | config |
|---|---|---|
| load | cap at **90%** of the current item load, rounded down to the increment; every top-set/back-off group load is scaled by the same factor | `load_multiplier` |
| RIR | **floor 3**, capped at 4 (`DEC-RIR-02`: RIR 0 forbidden, window 1–4), applied to the parent item and every structured group | `rir_floor`, `rir_cap` |
| scope | the session's essential/main-lift items | "All lifts" plus named patterns adds both; named patterns alone restrict the scope to those patterns |
| sets, reps, rest, exercise identity | unchanged | — |

The RIR floor is a floor, not a target: an item already prescribed at RIR 4 stays at RIR 4.

## 4. Ordering and precedence

```text
1. base item and DUP scheme
2. readiness, back-flare effort and continuity load modifiers
3. top-set/back-off structure
4. volume budget, compensation, under-MEV, exposure and MRV/spinal trims
5. technique throttle (updates parent and structured groups)
6. warm-up attachment from the final top-set load
7. constraints, minimum-session trim and deload
8. top-set set-count reconciliation and final validation
```

The top-set structure is therefore applied before the volume budget and the later safety trims;
those trims can change the item's set count while the throttle runs after them. The technique
throttle **compares** with the cumulative load factor the earlier load modifiers already
applied; it never multiplies on top. An item already at 0.85 stays at 0.85, and only the RIR
floor can still apply. This is the same rule the deload uses, and it keeps the documented
20% readiness+continuity cap meaningful (`DEC-W3-02`). The throttle runs before the ramp is
attached, so warm-up loads are derived from the final top-set load after the throttle.
Minimum-session trim and deload run after the ramp; a deload week does not create a top set.

For an item with structured top-set/back-off groups, the throttle scales each group's own
load and applies the RIR floor/cap to each group's target. It does not copy the parent summary
into every group, which would erase the top/back-off load distinction. The parent item's
`load_kg` and `rir_target` are then set from the back-off group (or the top group when only
one remains), so the summary and structured work cannot disagree.

## 5. When it refuses or changes nothing

- **No matching item** (`no_match`): a named pattern is not present in this session. The
  prescription is unchanged and the note says so — a typo must not throttle the wrong work.
- **Already reduced** (`already_reduced`): every scoped item is at or below 0.90 and at or
  above the RIR floor.
- **Bodyweight work**: total bodyweight is not a plate to remove, so the load is left alone
  and the item is reported in `load_not_reducible`; the RIR floor still applies.
- **Unknown load**: the same — RIR floor only, never an invented load.

A constraint veto or a non-executable prescription is not overridden: the throttle changes
load and RIR, and final validation still runs afterwards.

## 6. Provenance and the LLM

Changed items cite `MOD-TECH-001`. `Prescription.notes.technique_throttle` records
`requested`, `applied`, `status`, `pattern`, `load_multiplier`, `rir_floor`, `changed`,
`load_not_reducible` and a human `reason`.

The prescription warning names the rule and the changed lifts, and that warning is part of
the narrative payload the LLM receives. The model may explain the throttle in its own words;
it never computes the load or RIR and never adds a reduction of its own.

## 7. What it does not do

- read `form_rating`, `session_form_rating` or any imported `Form` value;
- trigger automatically, or from a pattern-level flag;
- persist any state between sessions — the next prescription is normal unless the athlete
  asks again;
- predict, diagnose or clear an injury;
- change sets, reps, rest or exercise selection;
- stack a second reduction onto readiness, continuity or a deload;
- claim that a 90% cap or RIR 3 is an evidence-based dose (it is `ASSUMPTION-36`).

## 8. Tests

- `tests/test_technique_throttle.py` — cap, floor, no stacking, pattern scoping, default
  scope, bodyweight handling, unknown pattern, config validation, engine wiring, no carry-over;
- `tests/test_web.py` — the API accepts the request and reports the note.

## 9. Files

- `config/technique-throttle.v1.yaml`
- `strength_coach/prescribe/technique_throttle.py`
- `strength_coach/prescribe/engine.py`
- `strength_coach/features/prescription_provenance.py`
- `strength_coach/cli.py`
- `strength_coach/web/server.py`, `strength_coach/web/static/app.js`, `strength_coach/web/static/index.html`
- `tests/test_technique_throttle.py`, `tests/test_web.py`

## Related

- **Rejected automatic variant:** [`FORM-USE-EVIDENCE.md`](FORM-USE-EVIDENCE.md), `DEC-FORM-01`–`05`
- **Precedent for a user-selected modifier:** [`MINIMUM-SESSION.md`](MINIMUM-SESSION.md)
- **Modifier order:** [`W0-EXECUTION-MAP.md`](W0-EXECUTION-MAP.md) §3
- **Decisions:** [`DECISIONS.md`](DECISIONS.md) (`DEC-TECH-01`)
