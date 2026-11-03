# INJURY ATTRIBUTION AND VERIFICATION PLAN

**Status:** approved plan, 2026-11-01. **Phases 1–2 closed 2026-11-01.** Phase 1 corrected
verification without a schema change. Phase 2 adds migration `0047` and the optional,
display-only attribution fields. Phase 3 was split into a separate roadmap phase,
[`ROADMAP.md`](../ROADMAP.md) §4.28, and is unscheduled research. Current behaviour is
documented in [`INJURY-SIGNAL.md`](INJURY-SIGNAL.md) and [`SYMPTOM-LOGGING.md`](SYMPTOM-LOGGING.md).

This plan covers two related but separable changes:

1. **Verification hygiene** — correct how the injury signal decides whether a loaded session
   has a follow-up reading, without changing the agreed next-day pre-session rule.
2. **Optional attribution** — let a symptom reading point at the completed session, and at
   most one lift performed in it, that the athlete suspects, with an onset date and a
   confidence label. Display and review only; nothing reads it for suitability, selection,
   load or the signal's status.

A third idea — an exercise-level predictor — is recorded here as a boundary, not as planned
work. Nothing in this plan trains, scores or tunes a model.

---

## 1. Why

The region-level injury signal already answers "has this region been loaded, and did any
recorded reading afterwards show a flare?" Two gaps motivated the plan:

- **The signal can over-credit tolerance.** Superseded symptom rows still participate, a
  same-day pre-session flare does not disqualify the session, a same-day post-session reading
  is ignored, and `unverified` currently conflates "no reading" with "a flare happened".
- **There is no structured link from a symptom to the exposure.** `symptom_log` records a
  region and a level, but not which session or lift the athlete associates with it. A note
  can say it, but the note is not queryable, and a free-standing "exercise" field on a
  pre-session reading cannot say *which session* it belonged to — the suspected lift may have
  been performed days earlier.

The second problem is why attribution is session-linked rather than a bare exercise id. A
symptom reading against a completed session, with an onset date, is a real (exposure, outcome)
pair. A pre-session reading plus an exercise name is not.

## 2. Decisions taken on 2026-11-01

| # | Decision |
|---|---|
| D1 | **Keep the next-day pre-session rule.** A `pre_session` reading on the following training day is valid follow-up evidence, as [`INJURY-SIGNAL.md`](INJURY-SIGNAL.md) §2 and `ASSUMPTION-09` already say. The earlier proposal to require `next_morning` is rejected. |
| D2 | **`tolerated` means "at least one qualifying follow-up reading exists and none is a flare".** It does not establish tissue adaptation. Missing follow-up is `unverified`, never tolerated. Display wording becomes **"no flare recorded in the follow-up window"**. |
| D3 | **Latest-row-wins inside the signal.** For each `(region, logged_on, timing)`, only the row with the greatest `log_id` participates. This matches the rest of the app and stops a superseded flare or clean row from counting. The dedupe is local to the injury signal; other consumers of `symptom_entries` keep their current behaviour. |
| D4 | **Same-day semantics.** A same-day `pre_session` flare means the region was loaded while already symptomatic: the exposure still counts, but the session cannot be `tolerated` (`symptomatic_load`). A same-day `post_session` reading is admissible follow-up. A same-day `pre_session` clean reading is not follow-up (it precedes the load). |
| D5 | **Keep shared readings.** One qualifying reading may verify several loaded dates within its window. Each loaded **date** is credited once. The count is "exposures with a follow-up reading", not independent confirmations; this is documented rather than changed. |
| D6 | **Replace free-standing exercise attribution.** Attribution is one concept: an optional completed session, an optional lift performed in that session, a required onset date, and a required confidence label. There is no separate "exercise on any symptom row" field. |
| D7 | **Attribution is optional, session-scoped and non-causal.** It never changes suitability, constraints, selection, prescription load, the injury signal's status or its recommendation. It is the athlete's suspicion, displayed as such. |
| D8 | **Confidence is ordinal, not a probability.** `possible` / `likely` / `strong`, required whenever a session is attributed. Never displayed as a number or percentage. |
| D9 | **Onset is required for attribution.** No onset, no attribution. `onset_on <= logged_on`. Candidate sessions must precede the onset (see §6), and the lookback is 7 days. |
| D10 | **Completed sessions only.** Link the `session` row that `clean_set` and the signal read, not the live `workout_session`. Imported sessions qualify. |
| D11 | **The 7-day window and the review gate are unchanged.** No new clinical threshold. `verify_within_days` stays 7; `ASSUMPTION-09` remains. The changes are corrections to how the existing rule is evaluated, not a new rule. |
| D12 | **No predictor in this plan.** Exercise-level prediction is a separate, gated research question (§10). |

## 3. Audited current behaviour (2026-10-31)

Confirmed by reading `features/injury_signal.py`, `store/queries.py`, the symptom tests and
the two symptom documents:

- `_verified_tolerated(rule, entries, day)` builds `window = [e for e in entries if day <
  str(e["logged_on"]) <= end]` with `end = day + rule.verify_within_days`. It filters by
  date only and applies no `timing` filter.
- Consequently a next-day `pre_session` reading verifies the previous session (intended), a
  same-day `post_session` reading cannot verify it, and a same-day `pre_session` flare is
  outside the window and does not disqualify the session.
- `queries.symptom_entries` returns every row ordered by `logged_on, log_id`; it does not
  apply latest-wins. The signal uses that full list for `latest`, `flares` and
  `prior_flares`, so a corrected row leaves the superseded row in play.
- The signal's `latest` is the last row in that ordering, so a `post_session` or
  `next_morning` row can become the "latest" reading and affect `latest_level` and the
  streak, while `MOD-BACK-001` and `PRG-EREC-001` read only `pre_session` through
  `latest_symptom`. That consumer split is intentional (safety gate vs descriptive history)
  but should be stated.
- `symptom_log` has no session, exercise, onset or confidence field. The free-text `note`
  is the only place a suspected lift can appear.
- Exposure is computed from `clean_set` working sets, excluding voided sessions, voided
  sets and superseded sets, weighted direct 2 / indirect 1, with the configured
  `min_session_load`. This is sound and is not changed.
- The signal reports `loaded_sessions`, `tolerated_sessions` and
  `unverified_sessions`; the last is `loaded - tolerated`, so it mixes "no reading" with
  "a flare was recorded".
- The CLI and web display call the count "tolerated" without the "no flare recorded"
  qualification.

Confirmed design choices, not defects:

- next-day pre-session follow-up ([§2 of INJURY-SIGNAL.md](INJURY-SIGNAL.md));
- one clean reading may verify multiple sessions (shared window);
- the back safety gate reads only pre-session readings.

## 4. Defects to correct (Phase 1)

| # | Defect | Correction |
|---|---|---|
| V1 | Superseded symptom rows participate in flares, streak and `prior_flares` | Dedupe to the latest row per `(region, logged_on, timing)` inside the signal |
| V2 | A same-day pre-session flare does not disqualify the session | Add `symptomatic_load`; never `tolerated` |
| V3 | A same-day post-session reading is ignored | Admit `post_session` on the session date as follow-up |
| V4 | `unverified` conflates missing follow-up with a recorded flare | Report `flared` and `symptomatic_load` separately; `unverified` becomes "no qualifying follow-up" |
| V5 | "Verified tolerated" overstates the claim | Use "no flare recorded in the follow-up window" in CLI, API text and UI; keep the stored field names for compatibility where practical |
| V6 | No structured exposure link | Optional attribution (Phase 2) |

## 5. Target verification rule (Phase 1)

Deterministic, date-granular. No timestamp is introduced.

1. Load the region's rows with `logged_on <= on_date`, then keep the row with the greatest
   `log_id` for each `(logged_on, timing)`.
2. Order the deduped rows by `logged_on, log_id`. The last row is `latest`.
3. `flares` are the deduped rows where `flare_from(level, settled_within_48h)` is true.
   `prior_flares = max(0, len(flares) - 1)`, unchanged. The streak starts at the last flare
   or the first entry, unchanged.
4. Loaded dates are computed from `clean_set` working sets from the streak start date
   through `on_date` (the start date is included so a same-day pre-session flare is visible),
   with the weights and `min_session_load` unchanged.
5. For each loaded date `D`, build follow-ups:
   - every deduped row with `D < logged_on <= D + verify_within_days` (any timing), plus
   - a `post_session` row dated `D` itself.
   A `pre_session` or `next_morning` row dated `D` is not follow-up.
6. Classify the exposure, in this priority order:
   1. **`flared`** — a same-day `post_session` follow-up is a flare. A flare on a later
      date starts a new streak; that earlier loaded date is outside the current window and
      is not counted as a separate `flared` exposure.
   2. **`symptomatic_load`** — no follow-up flare, but the same-day `pre_session` row on
      `D` is a flare. The exposure counts; tolerance does not.
   3. **`tolerated`** — at least one follow-up, and none is a flare.
   4. **`unverified`** — no follow-up.
7. The counts partition the loaded dates:
   `loaded = tolerated + flared + symptomatic_load + unverified`.
8. The review gate is unchanged: `streak >= window` **and** `tolerated >= required`.
9. A date with more than one session fragment is one loaded date. The response is date-level;
   the plan does not introduce per-session verification (that would need a session link in the
   signal, not just in symptom attribution).

The signal's JSON and CLI gain `flared_sessions` and `symptomatic_load_sessions`.
`unverified_sessions` keeps its key but changes meaning to "no qualifying follow-up"; all
consumers (web, CLI, tests, docs) are updated in the same change. The stored field names stay
to avoid a needless API rename; the display wording changes.

## 6. Attribution model (Phase 2)

Optional fields on a symptom reading, all unused by the signal and by every prescription path.

- **Session** — a completed `session` row. The session date must be on or before
  `onset_on`, and within `attribution_lookback_days` (7) before it.
- **Lift** — optional. It must be an exercise actually performed in that session according
  to `clean_set` (not the planned items; substitutions are real). At most one.
- **Onset** — required. `onset_on <= logged_on`.
- **Confidence** — required when a session is set: `possible`, `likely`, `strong`.
- **Timing interaction** — if the reading is `pre_session`, the symptom already existed
  before that day's session, so candidate sessions must be dated strictly before
  `onset_on`. For `post_session` and `next_morning` readings, a session on `onset_on`
  is allowed. This uses the existing timing label; it does not claim a clock time.
- **Lookback** — a new config key `attribution_lookback_days: 7` with a one-line domain
  comment; it is a capture convenience, not a clinical threshold.
- **Validation** — one shared validator used by the repository, CLI and web API. Reject
  missing onset, onset after the reading, session after onset, session outside the lookback,
  an exercise not performed in the session, an unknown session, an unknown exercise id or an
  invalid confidence value. Unknown exercise ids (removed from the taxonomy after the fact)
  remain displayable.
- **Corrections** — append-only. A correction appends a full new symptom row with the same
  `logged_on`, `timing` and region; latest wins. Historical rows are never updated or
  deleted.
- **No free-standing exercise field.** If no session fits, the reading has no attribution and
  the note carries the context. This keeps one source of truth.

Display rules:

- symptom history: "suspected: <lift> · <confidence> · session <date>" with an explicit
  **athlete-attributed** label; "session only" when no lift was chosen;
- session detail/history: the attached symptom events for that session;
- region panel: a separate "athlete-attributed symptoms" block; never merged into
  `linked_exercises`; the signal's status, counts and recommendation do not read it;
- confidence is shown as the word only;
- if the lift is not in the region's configured links, show a muted "not in configured links"
  without blocking the entry.

## 7. Schema (migration 0047, implemented)

Migration numbering followed the previous head (0046); `0047` is the applied migration.

| column | type | notes |
|---|---|---|
| `attributed_session_id` | TEXT, nullable | declarative reference to `session(session_id)`; validated in code |
| `attributed_exercise_id` | TEXT, nullable | taxonomy id; no foreign key (taxonomy is YAML); validated in code |
| `onset_on` | TEXT, nullable | ISO date; `<= logged_on` |
| `attribution_confidence` | TEXT, nullable | `CHECK (attribution_confidence IN ('possible','likely','strong'))` |

- All four are nullable; historical rows stay `NULL`. No backfill.
- Cross-field consistency cannot be expressed by an `ADD COLUMN` CHECK (SQLite constraints
  on a new column cannot reference other columns), so the validator enforces: if any
  attribution field is set, session, onset and confidence are set; lift is optional.
- No update/delete triggers change; `symptom_log` stays append-only.
- Optional index on `attributed_session_id` if the session detail view needs it.
- `DATA-MODEL.md` §11.5 is updated in the implementation change, not before.

## 8. CLI, API and web (Phase 2)

- **CLI**: `strength-coach symptom` gains `--session`, `--exercise`, `--onset` and
  `--confidence`; `symptom list`/history shows the attribution. Errors name the failing
  field.
- **API**: the symptom POST accepts the four fields and returns them; validation failures are
  the existing 400 shape with field errors.
- **Web**: the symptom form gets an optional attribution section (onset first, then confidence,
  then a session picker limited to sessions before the onset within the lookback, then a lift
  picker populated from that session's performed sets). A completed workout offers a quiet
  "log a symptom for this session" link that prefills the session and `post_session` timing;
  there is no automatic prompt after every workout.
- **Parity**: the CLI and web call the same validator and the same repository function
  (AGENTS.md §10). The UI never re-implements the rules.

## 9. Display wording

- "no flare recorded in the follow-up window" instead of "verified tolerated" in help text,
  summaries and docs.
- `tolerated`, `flared`, `symptomatic load` and `unverified` are named as such; the
  status and recommendation logic is unchanged.
- Attribution is always labelled **athlete-attributed** or **suspected**, never "cause".
- The region panel states that attribution is not used by the signal.

## 10. Predictor boundary (not scheduled)

Attribution is not a predictor input. It is recorded only when symptoms exist, so it cannot
supply a rate; it is the athlete's belief, subject to recency and expectation bias; and
regional symptoms often follow several co-occurring lifts.

A future exercise-level analysis, if ever proposed, would use the existing mechanical
exposure (`clean_set`) and the daily region readings as the substrate, with a pre-registered
descriptive screen and the same gated adoption pattern as other shadow work (for example
`DEC-VOLUME-29`). Attribution would be an interpretability label, not the label source.
Nothing in this plan authorises a model, a score, a selection change or a load change.

## 11. Phasing and acceptance

| phase | scope | acceptance |
|---|---|---|
| 0 — plan (done 2026-11-01) | this document; roadmap and doc pointers | docs consistency passes; no code, schema or behaviour change |
| 1 — verification hygiene | **implemented 2026-11-01**: dedupe, same-day rules, response states, counts, wording | the tests in §12 pass; the existing next-day test is unchanged; status changes are listed in the change note; no schema change |
| 2 — attribution | **implemented 2026-11-01**: migration, validator, CLI/API/web, display, history/session/region views | validation matrix passes; CLI/UI parity; attribution changes no signal status or prescription; docs updated |
| 3 — research (unscheduled; separate roadmap §4.28) | exercise-level descriptive analysis | separate decision and pre-registration; not part of the closed Phase 1–2 plan |

Phase 1 and Phase 2 are independent. Phase 1 can ship without attribution; Phase 2 can ship
without changing verification.

## 12. Tests

Verification:

- a superseded flare row no longer disqualifies a session; a superseded clean row no longer
  verifies one;
- a next-day `pre_session` reading still verifies (the existing test stays);
- a same-day `post_session` clean reading verifies; a same-day `post_session` flare
  disqualifies;
- a same-day `pre_session` flare produces `symptomatic_load`, not `tolerated`;
- no follow-up is `unverified`, never tolerated;
- one reading may verify several loaded dates (documented, asserted);
- `loaded = tolerated + flared + symptomatic_load + unverified` on a mixed fixture;
- the review gate still needs the streak and the required tolerated count;
- the signal still reads all timings for its history while the back rules read only
  `pre_session` (the consumer split is asserted, not changed).

Attribution:

- optional: a reading without attribution is valid;
- session required when any attribution field is set; onset and confidence required;
- `onset_on > logged_on` rejected; session after onset rejected; session outside the
  lookback rejected; exercise not performed in the session rejected; unknown ids rejected;
- `pre_session` attribution cannot point at a session on the onset date;
- append-only correction: the latest row wins; the superseded row remains in the table;
- no signal status, recommendation, suitability, constraint, selection or load changes;
- CLI, API and web produce the same validation errors (parity);
- a removed exercise still displays its stored id.

## 13. Risks and compatibility

- **Status movement.** Phase 1 can move a region both ways: dedupe may remove a phantom flare
  (more tolerated) and the same-day rule may remove tolerance (less tolerated). The release
  note lists the meaning change; no calibration data is affected.
- **`unverified_sessions` changes meaning.** `flared` and `symptomatic_load` are split
  out. Update every consumer and say so in the API/CLI notes.
- **Date granularity.** `timing` is a label, not a clock. The plan does not enforce elapsed
  time, does not add timestamps and does not claim a 24–48 h response. That limitation is
  documented.
- **Attribution is belief.** It must not be read as causation; UI and docs state this.
- **Privacy.** Symptom rows are local and private; attribution adds no outbound field. LLM
  payload rules are unchanged.
- **No migration backfill.** Historical rows have `NULL` attribution; counts and analyses
  must treat `NULL` as "not recorded", never "no trigger".

## 14. Documentation and decision records at implementation

- New decision entries in [`DECISIONS.md`](DECISIONS.md) for the verification corrections
  and for attribution (allocated then, with enforcement paths). `DEC-INJURY-03`,
  `DEC-SYMPTOM-02` and `DEC-SYMPTOM-04` remain in force; `ASSUMPTION-09` is unchanged.
- `INJURY-SIGNAL.md`: verification definition and the four response states.
- `SYMPTOM-LOGGING.md`: attribution workflow, onset and confidence, and what attribution
  does not establish.
- `DATA-MODEL.md` §11.5: the new columns and validation.
- `USER-GUIDE.md`, `WEB-UI.md`, `UI-MAP.md`: the new form fields and displays.
- `ROADMAP.md` status and `CHANGELOG.md` at the release that ships each phase.
- `LIMITATIONS-REGISTER.md` if a new accepted limitation is recorded (attribution is
  self-reported and case-only).

## 15. Non-goals

- no new symptom scale, diagnosis, injury entity or parallel logging system;
- no timestamps, per-session verification or session link in the injury signal;
- no multiple lifts per reading;
- no session-less exercise attribution;
- no automatic suitability, constraint, selection, load or prescription change;
- no model, score or predictor;
- no historical rewrite or backfill.

## 16. References

- [`INJURY-SIGNAL.md`](INJURY-SIGNAL.md) — current tolerated definition, window scaling,
  evidence and limitations.
- [`SYMPTOM-LOGGING.md`](SYMPTOM-LOGGING.md) — the 0–3 scale, flare rule and episode
  workflow.
- [`DATA-MODEL.md`](DATA-MODEL.md) §11.5 — `symptom_log`.
- [`DECISIONS.md`](DECISIONS.md) — `DEC-BACKSIGNAL-01`, `DEC-INJURY-01`,
  `DEC-INJURY-02`, `DEC-INJURY-03`, `DEC-SYMPTOM-01`–`DEC-SYMPTOM-04`.
- [`../ROADMAP.md`](../ROADMAP.md) §4.26 — closed Phases 1–2; §4.28 — separate Phase 3 research.
