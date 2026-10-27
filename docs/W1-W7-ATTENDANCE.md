# W1 / W7 — ATTENDANCE AND ROLLING SCHEDULE

**Status:** W1 and W7 audits complete 2026-10-23; W1/W7 recommendations implemented
2026-10-23. No loads changed.
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
Classification: confirmed code-path inconsistency; **fixed**.

`features/programme.build_programme` calls `deload_mod.apply` after `build_prescription`. The CLI
and web paths now pass the deload decision into the build, but the forecast path still applies
it after validation. A forecast can therefore show the same stale/post-validation interaction
that W3 fixed in the main path, including an uncapped primary RIR.

The forecast now passes `deload_decision` into `build_prescription` and uses the same ordered
pipeline as the CLI/web paths.

**W1-07 — `max_session_minutes` is not consumed.**  
Classification: resolved as an explicit metadata/planned-cap rule.

`athlete_profile.max_session_minutes` now tightens the planned cap (default 80 minutes, maximum
90) and adds a `notes.session_time` estimate plus a warning when the estimate exceeds it. It
does **not** silently cut sets or load; the optional minimum session remains the explicit
reduction. The hard ceiling is 90 minutes.

**W1-08 — Session duration is not enforced.**  
Classification: confirmed limitation.

The engine now estimates and warns against the planned cap, but imported sessions still have no
reliable measured duration. Live workouts measure duration; the rubric duration item remains
unmeasurable for imported sessions.

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
| `injury_free_weeks` | weeks in the latest logged state with no flare; a log persists until another log changes it | `unknown` before the first symptom log |
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
Classification: resolved. Today now shows completed/target, shortfall, family exposures and
session-type data; Outcomes shows the fuller block.

**W7-02 — There is no planned-session calendar.**  
Classification: confirmed data limitation.

The rolling programme is a forecast, not a stored plan. Attendance must stay target-based unless
a plan is persisted.

**W7-03 — Injury-free weeks are not computable from absent symptom logs.**  
Classification: confirmed missing-data rule.

Use `unknown`; do not infer “no flare” from no entry.

**W7-04 — Session-type balance is already available in Outcomes but not in the progress
dashboard.**  
Classification: resolved. The shared attendance summary feeds both surfaces.

---

## Implemented follow-up

- Forecast deload now uses the build-time path.
- `max_session_minutes` now sets the planned cap and emits a warning; it does not cut sets.
- `features/attendance.py` is the single attendance summary.
- Today and Outcomes render it.
- No stored plan, backlog or catch-up mechanism was added.

Remaining limitations: permanent family unavailability can stall the selector; imported
duration remains unmeasured.
