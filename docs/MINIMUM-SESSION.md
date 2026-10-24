# MINIMUM EFFECTIVE SESSION — MOD-MIN-001

**Status:** implemented 2026-10-23.
**Nature:** user-selected, volume-only fallback. It never changes load, RIR, reps or exercise
identity.

---

## 1. Why this exists

Some days cannot fit the planned session. The safe response is not to invent a new load or
silently delete training. It is to offer a smaller **volume** version of the same session,
with the same load and RIR, and label it clearly.

The evidence supports low-volume training maintaining strength better than it builds it. It
does not define a universal minimum dose for this athlete. This is a coaching heuristic, not a
validated dose.

## 2. User flow

UI:

```text
Prescribe → tick Minimum session → the 30/45/60 target and deeper-tier options appear (hidden while unticked)
→ optional “also reduce main lifts” (deeper tier)
→ build
```

CLI:

```bash
strength-coach run --date 2026-10-23 --minimum-session --target-minutes 45
strength-coach run --date 2026-10-23 --minimum-session --target-minutes 30 \
  --minimum-include-main
```

It is never automatic and is not selected from the calendar.

## 3. Reduction order

```text
1. automatic modifiers (readiness, continuity, deload, volume cap)
2. minimum-session tier
3. warm-up attachment
4. final validation
```

Default tier:

1. reduce non-essential accessory sets, from the end of the template backwards;
2. stop at one accessory set;
3. if still over target, remove non-essential accessory exercises from the end;
4. preserve every essential/main-lift item and all warm-up sets.

Deeper explicit tier (`--minimum-include-main` / UI checkbox):

5. reduce essential/main-lift sets to the configured floor (default 2);
6. never remove an essential item.

Loads and RIR targets are copied unchanged. Rep ranges are unchanged.

## 4. Time estimate

The target is checked against an explicit planning estimate:

```text
sets × (30 s set + rest_s) + warm-up sets × 30 s
```

The seconds are config (`config/minimum-session.v1.yaml`). This is **not** a measured session
length and is not a fatigue model. A partial result is labelled `partial` when the floors are
reached before the target.

## 5. Safety and refusal

`MOD-MIN-001` is not applied when:

- any item has no executable load;
- the prescription already fails validation;
- a stored hard constraint vetoes an exercise.

In those cases the prescription is unchanged and the note says why. The mode can only remove
work; it cannot bypass an injury ceiling, readiness floor, deload, MRV cap or constraint.

It is **not** provided when the session is already under the target. That status is
`already_short`, with no set changes.

## 6. Provenance

Changed items cite:

```text
MOD-MIN-001
```

`Prescription.notes.minimum_session` records:

- requested;
- applied;
- status: `applied`, `partial`, `already_short` or `unavailable`;
- target minutes;
- deep-tier flag;
- estimated before/after minutes;
- removed sets and exercises.

The UI start-workout path persists the prescription, item provenance and workout in one
transaction. The frozen workout plan therefore records the reduced volume, and the workout
comparison shows planned versus actual sets.

## 7. What it does not do

- no load reduction;
- no RIR increase;
- no exercise substitution;
- no automatic use;
- no change to session type;
- no new fatigue model;
- no guarantee that a 30/45/60-minute estimate is the true duration;
- no separate outcome claim from a single minimum session.

## 8. Interaction rules

- Readiness may already have removed accessory sets. The minimum tier reduces from the
  current prescription and stops at the floors; it does not remove the same set twice.
- A deload may already have reduced sets. The minimum tier can only reduce further to the
  floors, never below them, and never touches load.
- The MRV cap and constraints are applied before the final validation.
- The primary/main-lift pattern is preserved in both tiers; the deeper tier changes set count,
  not the lift.

## 9. Files

- `config/minimum-session.v1.yaml`
- `strength_coach/prescribe/minimum_session.py`
- `strength_coach/prescribe/engine.py`
- `strength_coach/features/prescription_provenance.py`
- `strength_coach/web/server.py`, `strength_coach/web/static/app.js`, `index.html`
- `strength_coach/cli.py`
- `tests/test_minimum_session.py`, `tests/test_prescribe.py`, `tests/test_web.py`
