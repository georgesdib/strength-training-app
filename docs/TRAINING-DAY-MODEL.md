# Training day and session fragments

**Status:** implemented 2026-11-01 (backend, API and UI). No schema migration.

## 1. Problem

The previous model assumed one session per calendar date, although the storage layer never
enforced it:

- imported sessions are grouped by date because the export has no timestamps;
- the session table has no unique constraint on `occurred_on`;
- a second live workout can be started after the first is completed;
- `queries.sessions()` was documented as one row per date but returned every fragment;
- `completed_sessions()` counted session rows, so two same-date rows counted as two attendance
  sessions.

This specification replaces that assumption with an explicit **training day plus fragments** model.

## 2. Core model

- A **training day** is one local calendar date, identified by `occurred_on`.
- A **session fragment** is an existing `session` row: it keeps its own `session_id`, session type, sets, duration, prescription link and provenance.
- A training day may contain one or more fragments.
- Fragments are never merged, renumbered or rewritten into one row.
- Training-day identity is virtual: group fragments by `occurred_on`. No new table and no migration are required.
- The date is the athlete's local date. Overnight and timezone-boundary cases are out of scope.

If `occurred_on` is corrected later, the fragment moves to the corresponding training day automatically.

## 3. Planning

- A training day has **at most one prescription/plan**.
- The existing prescription-for-date rule remains: rebuilding a plan for a date with recorded work is a revision of the day's plan, not a second plan.
- A later fragment on the same day uses the same day plan; it does not create a second prescription.
- Extra work logged outside the plan is recorded as unplanned work attached to the fragment.
- Two genuinely separate plans in one day are out of scope; that would require a separate planning model.
- Only one workout may be active at a time. The second fragment can start only after the first is completed or abandoned.

## 4. Session type and scheduling

- Each fragment preserves its own session type.
- The day displays the planned type when fragments agree with the plan.
- If fragment types differ, the day display type is `mixed`; the fragments keep their individual types.
- The rolling schedule advances once per **training day** by the day's planned type, not once per fragment.
- A second fragment does not consume another session-type slot, advance the DUP cycle again, or create a second scheduled day.

## 5. Attendance and targets

- Attendance counts **training days**, not fragments.
- `sessions_per_week_target` is a target for training days.
- A day with two fragments counts as one completed session.
- `completed_sessions()` and the volume-budget `sessions_done`/`sessions_target` use distinct training dates.
- A day with no completed session fragment does not count as attendance, even if it contains a test or exposure record.

## 6. Volume, spinal cost and dose

- All working sets from all fragments count toward the same day and week.
- There is no volume reset between fragments.
- Weekly volume targets, per-pattern caps, MRV, spinal cost and the weekly budget use the combined day.
- Same-date revision accounting continues to exclude the day's recorded work from the prior-week baseline and count the proposed plan once.
- High-intensity exposures remain individual records; their day-level context is aggregated, not merged.

## 7. e1RM and calibration

- For each exercise and training day, produce **one day-level e1RM observation**.
- Collapse the valid fragment observations using the existing session-best/quality rules; do not average fragments and do not count each fragment separately.
- Rolling medians, series-break detection and calibration use the day-level observation.
- Invalid, degraded or excluded observations remain excluded under the existing rules.

## 8. Readiness

- Readiness is recorded once per training day.
- The second fragment reuses the day's effective readiness state.
- The second fragment does not prompt for a second readiness entry and does not create a separate readiness context.
- If multiple readiness rows already exist for a date, the existing latest/complete-row rules resolve the effective state.

## 9. Duration and time target

- Each fragment keeps its own measured or manual duration.
- `max_session_minutes` applies to each fragment's planning target.
- The training day displays the sum of fragment durations as total training time.
- The day total is descriptive; it does not retroactively cut sets.
- Imported fragments without measured duration remain unknown.

## 10. UI behaviour

- After completing a fragment, the workout screen offers **Start another session today**.
- That action creates a new fragment linked to the same `occurred_on` date.
- It does not create a new plan.
- History shows one expandable training-day row. Fragments are shown inside it with their type, duration and sets; day totals are shown at the row level.
- If an imported session and a live fragment share a date, both are shown as fragments of the day with a warning that the date was already recorded.
- The Today/Workout surfaces must never imply that a second fragment is a separate attendance session.

## 11. Exposures and tests

- Tests, max attempts, competition lifts and unplanned near-max work remain separate high-intensity exposure records.
- Each exposure keeps its link to the fragment that produced it.
- Guard windows use the exposure timestamps/dates as today; the training-day grouping does not collapse or duplicate exposures.

## 12. Data migration and compatibility

- No schema migration is required for the initial implementation.
- Existing session rows remain unchanged.
- Grouping is derived from `occurred_on` in queries and reports.
- Existing duplicate-date rows become fragments of one day.
- A future explicit `training_day` table is not part of this specification; it would be a separate decision if ordering, timezones or independent day plans require it.

## 13. Out of scope

- Two independent prescriptions per day.
- Overnight training days or timezone-aware day boundaries.
- Splitting imported date-only groups into multiple fragments.
- Merging session rows or rewriting `session_id`.
- Changing the four session templates or the prescription engine's per-session dose logic.
- Automatic creation of a second plan.

## 14. Implementation acceptance criteria

- Two same-date fragments can be created manually; only one is active at a time.
- Attendance and budget session counts use distinct dates.
- Weekly volume, spinal and MRV accounting include both fragments once.
- e1RM produces one day-level observation per exercise.
- Readiness is shared by the day's fragments.
- History groups fragments under one expandable day row.
- Exposures stay separate and linked.
- Rebuilding a plan on a day with fragments remains a single revision.
- Tests cover same-date fragments, imported-plus-manual dates, different fragment types, duplicate e1RM, readiness reuse and attendance.

## Related

**Decisions:** [DECISIONS.md](DECISIONS.md) — `DEC-SESSION-02`, `DEC-SESSION-03`, `DEC-VOLUME-30`, `DEC-VOLUME-31`.
**Open questions:** none; the model is implemented without a schema change.
**Roadmap:** [ROADMAP.md](../ROADMAP.md) §4.27.

- [DATA-MODEL.md](DATA-MODEL.md)
