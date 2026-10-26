# SYMPTOM LOGGING — the 0–3 reading, and what to log when it settles

One number per region, logged **before** the session. Three consumers read the same rows, and
they read different things from them:

| consumer | reads | so it needs |
|---|---|---|
| `MOD-BACK-001` (back flare) | the **latest** `low_back` pre-session reading at or before the session date | a reading from today, not from three weeks ago |
| `PRG-EREC-001` (erector-ramp stability gate) | the same latest reading | the same |
| injury signal (`features/injury_signal.py`) | the **whole history** for a region: flares, last flare date, streak, prior flares, tolerated sessions | the flare to stay in history after it settles |

That split is why "it settled" is a **new reading**, not an edit of the old one:
`symptom_log` is append-only (migration 0003, tightened by 0005 with no-update and no-delete
triggers), and multiple rows per day are allowed with the latest winning.

## 1. The scale

`0`–`3` is the athlete's own agreed scale, with anchors in `private/docs/INFO-REQUESTS.md` §6.
The app does not reinterpret the anchors; it applies the flare definition to the number.

## 2. What counts as a flare

| reading | flare? |
|---|---|
| level `2` or `3` | **yes**, whatever `settled` says |
| level `1` with `settled_within_48h = no` | **yes** |
| level `1` with `settled_within_48h = yes` | no |
| level `1` with `settled_within_48h = unknown` (the default) | **yes** — no settlement is recorded, so it is not settled (`DEC-SYMPTOM-04`) |
| level `0` | never |
| no reading at all | `unknown`, never "no flare" |

So `settled_within_48h` answers exactly one question, and only for a level-1 reading: *is it
confirmed to have settled over the last two days?* Only a recorded `yes` clears it. An
unrecorded answer counts as **not** settled, because a missing observation is not evidence that
it settled (`DEC-SYMPTOM-04`). For level 2–3 the field is recorded but ignored, because
severity already decides. The definition lives in one place, `domain/symptoms.py::flare_from`.

## 3. Logging an episode

1. **Onset.** Log the level you have, before the session:

   ```bash
   strength-coach symptom --level 2 --note "sharp on flexion"
   ```

   - level **≥ 2** — it is a flare now. `--settled no` is the honest value (it has not
     settled), but it changes nothing; the flare comes from severity.
   - level **1** — it is a flare until a settlement is recorded, so say which:
     `--settled yes` if it has settled within 48 h (a niggle already on its way out),
     `--settled no` if it has not. Omitting the flag (`unknown`) behaves like `no` and fails
     safe.

2. **It settles.** Log a **new reading with level 0** on the day it is gone:

   ```bash
   strength-coach symptom --date 2026-10-28 --level 0 --note "settled after two days"
   ```

   This is the reading that ends the current flare. From that date the next prescription no
   longer applies `MOD-BACK-001`, and the injury signal's clean streak starts — dated from
   the **flare**, not from the clean reading. Leave `settled` alone on a 0 row: the question
   belongs to the episode, not to the clean reading.

3. **A level-1 niggle that is still there at 48 h.** Log level 1 again with `--settled no`.
   That reading is the flare; the erector ramp holds and the back modifier applies from that
   date. This is the only case where you *must* set the field deliberately.

4. **Wrong value on today's row?** Append another row for the same date and region; the
   latest wins (`symptom_for_date`). Never edit or delete — the triggers refuse.

Worked example:

| date | level | settled | why | effect from that date |
|---|---|---|---|---|
| 2026-10-26 | 2 | no | onset, sharp | flare: `MOD-BACK-001`, ramp holds |
| 2026-10-28 | 0 | — | gone after two days | back rules clean; streak starts at the 26th |
| 2026-11-03 | 1 | unknown | mild tightness, no settlement recorded | flare (fails safe) until a settled or clean reading |
| 2026-11-05 | 1 | no | still present at 48 h | flare: ramp holds |

## 4. How often to log

- Pre-session on training days is the intended habit. The back rules use the latest reading,
  so silence is not "no flare" — it is `unknown`.
- A reading older than `max_entry_age_days` (14, `config/injuries.v1.yaml`) makes the injury
  signal `insufficient` rather than healthy.
- A loaded session counts as **tolerated** only when a reading within the next
  `verify_within_days` (7) shows no flare. Unlogged stays `unverified`, never tolerated.
- Rest alone earns no credit: the streak only counts once loaded sessions are verified
  (`DEC-BACKSIGNAL-01`).

## 5. What not to do

- **Do not log 0 to "clear" a flare you still have.** It makes the safety gate pass by
  assertion, which is the failure mode the flare definition exists to prevent.
- **Do not expect `--settled yes` to excuse a level 2.** Severity decides.
- **Do not log post-session and expect the rules to see it.** Only `pre_session` rows drive
  `latest_symptom`; other timings are stored for context.
- **Do not back-date a clean reading to before a session you already trained.** The row is
  dated, and the date is the evidence.

## 6. Why an unanswered settle question is a flare

A level-1 reading with `settled` left at `unknown` counts as **not settled**, so it is a flare
(`DEC-SYMPTOM-04`, closing Q25). The reason is the same one that makes a missing reading
`unknown` rather than "no flare": a safety gate must not pass by silence. One conservative
session is the cost, and the remedy is one word — record `--settled yes` when it has settled.

## Related

- **Decisions:** [DECISIONS.md](DECISIONS.md) — `DEC-SYMPTOM-01` (one number, now per region),
  `DEC-SYMPTOM-02` (the flare definition), `DEC-SYMPTOM-03` (regions stay separate),
  `DEC-SYMPTOM-04` (an unrecorded settlement is not a settlement).
- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) — Q25, closed by `DEC-SYMPTOM-04`.
- **Roadmap:** [ROADMAP.md](../ROADMAP.md) §3.3 (symptom input) and §4.7 (injury signal).
- Schema and consumers: [DATA-MODEL.md](DATA-MODEL.md) §11.5, [INJURY-SIGNAL.md](INJURY-SIGNAL.md).
