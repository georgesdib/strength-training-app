# W1 / W7 — ATTENDANCE AND ROLLING SCHEDULE

**Status:** W1 and W7 audits complete 2026-10-23. No behaviour changed.
**Method:** deterministic synthetic attendance simulations plus a code-path review of the
attendance reports. No personal training data.

---

## W1 — the schedule under imperfect attendance

### Question

Does the rolling four-session-type schedule remain coherent when sessions are missed?

### Simulated patterns

Synthetic 24-week sequences, starting with no history:

| pattern | sessions | family counts (squat / hinge / bench) | max consecutive same family |
|---|---:|---|---:|
| 3/week | 72 | 24 / 24 / 24 | 1 |
| 2/week (miss Wednesday) | 48 | 16 / 16 / 16 | 1 |
| 1/week | 24 | 8 / 8 / 8 | 1 |
| 3/week, 4-week gap | 60 | 20 / 20 / 20 | 1 |
| 3/week, skip every 4th | 54 | 18 / 18 / 18 | 1 |
| 3/week, skip one squat | 71 | 24 / 24 / 23 | 1 |
| 3/week, skip one hinge | 71 | 24 / 24 / 23 | 1 |
| 3/week, skip one bench | 71 | 24 / 24 / 23 | 1 |

The 3/week sequence starts:

```text
squat → hinge → bench_squat → squat → hinge → bench_hinge → ...
```

### Findings

**W1-01 — Attendance does not distort the family balance.**  
Classification: passed.

Lower attendance changes the number of sessions, not the ratio. One session per week still
produces a 1:1:1 squat/hinge/bench balance over 24 weeks.

**W1-02 — No backlog or catch-up sessions.**  
Classification: passed / design trade-off.

Missed sessions are not added to a later week. The next session is selected from the recent
window, so the programme continues from the current shape rather than replaying a missed day.
This is coherent for a rolling programme but means “missed work” is not recovered.

**W1-03 — No consecutive same-family run in the simulated patterns.**  
Classification: passed.

The least-recent tie-break prevented the previously observed three-squat run.

**W1-04 — A gap does not reset the schedule.**  
Classification: design trade-off.

After a four-week gap, the sequence resumes from the prior six-session window. Continuity
handles the load/RIR side; the schedule has no explicit “return block”. The synthetic ratio
remained balanced.

**W1-05 — A permanently unavailable family can stall the schedule.**  
Classification: confirmed limitation, not a defect in normal use.

If the chosen family is skipped every time it comes up, the selector keeps choosing it because
the recent window has no successful session of another type. A one-off missed session does not
stall; permanent unavailability does. Constraints/selection handle the exercise level, but the
schedule has no family-level fallback.

**W1-06 — The programme forecast still applies deload after the build.**  
Classification: confirmed code-path inconsistency.

`features/programme.build_programme` calls `deload_mod.apply` after `build_prescription`. The CLI
and web paths now pass the deload decision into the build, but the forecast path still applies
it after validation. A forecast can therefore show the same stale/post-validation interaction
that W3 fixed in the main path, including an uncapped primary RIR.

The forecast is not persisted, but it is user-visible. It should use the same build-time path.

**W1-07 — `max_session_minutes` is not consumed.**  
Classification: confirmed documentation/engine gap.

`athlete_profile.max_session_minutes` is stored and displayed, but the prescription engine uses
the template's fixed `time_cap_s` (80 minutes). Changing the profile value does not change the
session or the warning; it is informational only.

**W1-08 — Session duration is not enforced.**  
Classification: confirmed limitation.

The schedule does not estimate or enforce duration. Templates carry an 80-minute cap, but no
actual duration is available for imported sessions. Live workouts can measure duration; the
engine does not consume it.

---

## W7 — attendance metrics

### Current state

- `Outcomes` already has a target-based attendance figure from
  `sessions_per_week_target × weeks`.
- `Today` / `progress.dashboard` does **not** report attendance.
- “Adherence” in older docs means RIR/progression compliance, not attendance.
- There is no stored planned-session calendar. A “missed session” can only mean a shortfall
  against the weekly target, not a specific missed planned day.

### Proposed definitions

All are descriptive and have no prescription effect.

| metric | definition | missing rule |
|---|---|---|
| `completed_sessions` | distinct session dates in the window | `0` is a real zero |
| `target_sessions` | `weeks × sessions_per_week_target` | `unknown` if target absent |
| `attendance_pct` | completed / target | `unknown` if target absent |
| `target_shortfall` | max(0, target − completed) | `unknown` if target absent |
| `family_exposures` | session counts by squat/hinge/bench family | `0` is a real zero |
| `main_lift_exposures` | per-main-lift session counts | `0` is a real zero |
| `session_type_balance` | counts of the four canonical types | `0` is a real zero |
| `measured_duration` | mean/median measured workout duration | `unknown` if none |
| `injury_free_weeks` | weeks with no symptom flare | `unknown` if symptom coverage is absent |
| `completed_vs_planned` | only possible with a stored plan | currently `unknown` |

Do **not** call the target shortfall “missed planned sessions”; there is no stored plan.

### Proposed location

- One core function in `features` (not UI arithmetic).
- A compact attendance block on **Today** and a fuller block on **Outcomes**.
- No separate dashboard and no new table.
- CLI parity: `volume`/`outcomes` already expose the underlying counts; add attendance to the
  existing summary rather than a new command if possible.

### W7 findings

**W7-01 — Attendance is visible in Outcomes but not on Today.**  
Classification: confirmed UX gap.

**W7-02 — There is no planned-session calendar.**  
Classification: confirmed data limitation.

The rolling programme is a forecast, not a stored plan. Attendance must stay target-based unless
a plan is persisted.

**W7-03 — Injury-free weeks are not computable from absent symptom logs.**  
Classification: confirmed missing-data rule.

Use `unknown`; do not infer “no flare” from no entry.

**W7-04 — Session-type balance is already available in Outcomes but not in the progress
dashboard.**  
Classification: confirmed reporting gap.

---

## Recommended next actions

1. Fix the programme forecast to pass `deload_decision` into `build_prescription`.
2. Decide whether `max_session_minutes` should constrain generation or be relabelled
   informational.
3. Implement W7 attendance metrics in one shared function; no load effect.
4. Do not add a stored plan or a catch-up/backlog mechanism without a separate decision.

No code was changed by W1/W7.
