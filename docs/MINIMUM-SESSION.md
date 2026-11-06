# MINIMUM EFFECTIVE SESSION — MOD-MIN-001

**Status:** implemented 2026-10-23; resolver-compatible shaping added 2026-11-04.
**Nature:** user-selected volume fallback. The fixed-template path removes only accessory work;
the resolver path chooses a minimum-compatible shape before assignment. Explicit accessories-only
mode may omit the main lifts and is labelled accordingly.

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
→ optional “Accessories only” (explicitly omits main lifts; no top set)
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

### Resolver-compatible shape

When the resolver is enabled, minimum session is a **pre-assignment shape** rather than a
post-selection deletion:

1. retain the essential main/support slots;
2. add optional accessory slots in least-trained-pattern order while the planning estimate fits;
3. resize only sets (main floor when “also reduce main lifts” is ticked; accessory sets keep
their planned count up to `accessory_max_sets`);
4. for accessory-only, add accessory sets deterministically while the target fits and the cap
   permits;
5. freeze that shape, then let the resolver choose exercises inside it;
6. never remove an assigned exercise after the resolver search;
7. after readiness/volume/top-up modifiers, apply the final `accessory_max_sets` cap before
   validation.

The operation is deterministic and cites `MOD-MIN-001`. Optional patterns are ordered by
last-trained date within `pattern_history_days` (default 84); ties keep template order. Required
patterns are filtered from the **eligible candidate patterns** of the retained slots, not from a
slot's template-default exercise. A required pattern with no eligible candidate in any slot is an
error, not silently dropped; assignment still has to cover each retained required pattern with a
distinct slot. If floors prevent reaching the target, the result is `partial`; the shape is still
shown and remains executable.

**Accessories only** is an explicit separate mode. It omits the main and secondary lifts, keeps
only accessory slots, and is not a normal main-lift session. A requested top set is reported
as not applicable rather than silently dropped. It requires an explicit session type (not
`auto`).

Selecting the **Accessory only** session type, or enabling “Accessories only” on a normal
type, produces the same effective `accessory` session. Its pool is drawn from non-essential
slots across all four templates, deduplicated by exercise and pattern; power work is optional
and ranked last. A pattern is retained at most once. Accessory slots are capped by
`accessory_max_sets` (default 4). The shape adds accessory sets only while the target fits; a
final pass re-applies the cap after readiness, volume and top-up modifiers, so later modifiers
may trim but cannot leave an accessory above the cap. Selecting the `accessory` session type
**always** enables the time-shaped accessory mode, even when the “Minimum session” box is not
ticked. Without a minimum target, the session uses `athlete_profile.max_session_minutes` (or
the configured fallback when the profile is unset); the explicit 30/45/60 minimum target
overrides it for that build. A profile target of 30 minutes therefore produces a 30-minute
accessory session without a hidden separate default. The target is a fill/cap goal, and the
final estimate may be under it when readiness or volume limits remove sets. A readiness-reduced
item is not directly re-added; the existing under-MEV skip list preserves that item-level rule,
though another eligible accessory may still be topped up by the separate progression rule.

## 4. Time estimate

The target is checked against an explicit planning estimate:

```text
sets × (30 s set + rest_s) + warm-up sets × 30 s
```

The seconds are config (`config/minimum-session.v1.yaml`). This is **not** a measured session
length and is not a fatigue model. The pre-assignment shape uses the template's rest values; the
final resolved prescription can differ by candidate-specific rest and warm-up attachments. The
final note therefore recomputes the estimate from the resolved items and marks the result
`partial` if it exceeds the target. A partial result is labelled `partial` when the floors are
reached before the target.

Because the target is judged against an estimate, the **ended-workout screen shows all three
numbers**: target, estimate (recomputed from the plan as it stands) and measured duration
(`DEC-MIN-02`, `LIM-47`). The estimate ignores transitions and idle time; the measured value is
the clock. Nothing in the prescription changes.

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
