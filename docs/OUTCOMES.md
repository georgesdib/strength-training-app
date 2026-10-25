# OUTCOMES — descriptive 4/8/12-week review

**Status:** implemented 2026-10-23.
**Scope:** read-only. No prescription, load, RIR, set or rule change.

---

## 1. What it answers

“What changed over the last 4, 8 or 12 weeks?” It does **not** answer “what caused it?”

Command:

```bash
strength-coach outcomes --weeks 8
strength-coach outcomes --weeks 12 --date 2026-10-23 --json
```

Web: **Outcomes** page.

API:

```text
GET /api/outcomes?weeks=8&date=YYYY-MM-DD
```

---

## 2. Strength section

- main-lift e1RM first/last/change, with observation count;
- weekly hard-set volume by movement pattern;
- target-based attendance (`sessions_per_week_target` × weeks), with shortfall, family
  exposures, session types, duration and observed symptom coverage;
- average sRPE and duration where recorded;
- readiness trend;
- low-back and other-region symptom entries and flares;
- weeks at or above the spinal cap;
- deload modifiers from `prescription_modifier`.

## 3. Longevity section

- cardio minutes by week and rolling four-week average;
- cardio sessions by modality and weeks with data;
- WHO 150–300 minutes/week as **context only**;
- steps, sitting, bodyweight, body fat, grip, VO2max estimate, sit-to-stand where measured;
- sleep/energy/stress/soreness readiness trends (n, average, first/last);
- readiness score trend and status counts;
- symptom history by region.

Cardio and measurements are **captured, not prescribed**.

## 4. Missing data

Everything missing is `unknown` or `null`:

- no readiness → no readiness score;
- no symptom entry → unknown, not “no flare”;
- no target → attendance percent unknown;
- no deload provenance → deload count unknown;
- no sRPE/duration → average unknown.

## 5. Attendance definition

```text
target = weeks × athlete_profile.sessions_per_week_target
completed = distinct session dates in the window
attendance = completed / target
```

This is target-based, not a stored plan. It is labelled as such.

## 6. Deload provenance

`prescription_modifier` is append-only and records modifiers actually cited by a stored
prescription. The web `/api/prescribe` endpoint currently returns a prescription without
persisting it, so a deload shown only in the web response is not provenance. The report says
`unknown` rather than guessing from changed sets or loads.

## 7. Readiness feedback report

`strength-coach readiness feedback --weeks 12` or the **Readiness feedback** panel on the
Outcomes page.

For each `MOD-FAT-001` reduction in the window it includes:

- completed **workout snapshots** whose plan cites `MOD-FAT-001` (the UI start-workout path);
- CLI-stored prescription modifiers when no workout snapshot exists for that date;
- planned versus actual working sets from the frozen workout plan;
- next-session sRPE, duration and RIR adherence;
- e1RM before/after for the first affected lift;
- any symptom flare within 7 days.

The UI path therefore records both the prescription and what was actually performed. The
report is still association-only: it does not know whether the athlete would have done better
without the reduction, and it does not tune weights, cut-points or the volume valve.

## 8. What it does not do

- no causal claims;
- no ranking of programme quality;
- no new fatigue model;
- no automatic rule or weight change;
- no snapshot table;
- no prescription change.

## Related

- **UI surface:** [UI-MAP.md](UI-MAP.md)
- **Evidence:** [REFERENCES.md](REFERENCES.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)
- **Roadmap:** [ROADMAP.md](../ROADMAP.md)
