# POST-LIFT FORM ASSESSMENT

**Status:** implemented 2026-10-25. Optional, descriptive input to the rubric.

---

## 1. What it is

After a lift, the athlete may rate the form of that exercise on a **1–5 scale**, higher is
better. It is optional; an unrated lift is not penalised.

- one rating per **exercise/lift**, not per set or per session;
- editable while the workout is open;
- editable later through **History → Edit**;
- imported sessions can receive ratings through History;
- never changes a load, set, RIR or exercise selection.

## 2. Surfaces

Workout:

```text
Workout → editable plan table → Form column → select 1–5
```

History:

```text
History → Edit → Post-lift form assessment → select 1–5 → Save correction
```

API:

```text
POST /api/workout/<workout_id>/form
{ "exercise_id": "...", "rating": 4 }
```

History corrections use the existing:

```text
POST /api/history/<session_id>/edit
{ "sets": [...], "forms": [{ "exercise_id": "...", "rating": 4 }], ... }
```

## 3. Rubric

Rubric **1.2.0** adds `FORM_ASSESSMENT`:

| property | value |
|---|---|
| weight | 0.05 |
| score | mean `rating / 5` over rated lifts |
| measurable | only when at least one lift has a rating |
| missing | unmeasurable; never treated as zero |
| effect | rubric score only; no load effect |

The previous seven weights were scaled by 0.95 to make room for form.

## 4. Storage

- `workout_form_rating` — append-only active-workout ratings;
- `session_form_rating` — materialised at workout end; corrections supersede the old row;
- latest leaf per session/lift is used by History and the rubric.

The imported `Form` column was a 1=best / 5=worst per-set value with 0/blank treated as
missing. Historical values were backfilled per session/exercise by averaging the valid sets,
inverting with `6 − mean`, and rounding half-up to the new 1–5 rating.

The derived `clean_set.form_score` values were then retired (set to NULL) by migration 0034.
The exact source `Form` value remains in `raw_row.payload` for audit. The new
`session_form_rating` rows are authoritative; a post-lift rating is still a separate,
explicitly directed measure.

## 5. Descriptive uses

- **Outcomes → Form trend** — current vs previous equal window, latest rating, change and
  session counts. The ±0.5 status threshold is a display heuristic, not a validated cut-point.
- **Review → Form context** — this session's rating beside up to five prior ratings for the
  same lift. It is context for the human mark; it does not auto-score anything.
- **History** — the edit sheet shows and amends per-lift ratings.

`GET /api/form-trend?weeks=4|8|12&date=YYYY-MM-DD` returns the descriptive trend.
No load, set or prescription use.

## 6. Limits

- Self-reported and subjective.
- Not validated against a coach or injury outcomes.
- One number per lift loses within-lift variation.
- The rubric weight is a policy choice, not a measurement.
- Unrated lifts are ignored; a partially rated session can look cleaner than it was.
- The trend's ±0.5 display threshold is not validated.
- Ratings are not available per set, so they cannot identify the exact rep where form broke.

## 7. Evidence and use

See [`FORM-USE-EVIDENCE.md`](FORM-USE-EVIDENCE.md). Form is monitoring/rubric-only; the
retrospective association was near zero and does not support e1RM filtering or load changes.

## 8. Files

- migration `0033_form_ratings.sql`
- `workout.py` (`set_form_rating`, materialisation)
- `history.py` (form corrections)
- `critique/facts.py`, `critique/rubric.py`
- `web/server.py`, `web/static/workout.js`, `web/static/history.js`, `web/static/app.js`
- `tests/test_workout.py`, `tests/test_history.py`, `tests/test_critique.py`, `tests/test_web.py`
