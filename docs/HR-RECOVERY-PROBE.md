# Per-set heart-rate recovery: probe, display and decision

**Status:** decided 2026-11-22 — shown as context, never used as an input. The number appears next
to the set that produced it in session detail (web and phone) with its caveat, and the Today view
carries a review card (`hr_recovery_probe`) that reports the measurement and prompts a re-run on a
12-week cadence. `strength_coach.features.hr_recovery` is the single implementation;
[`tools/hr_recovery_probe.py`](../tools/hr_recovery_probe.py) is the CLI over it.

## Why this exists

Apple Watch sessions already carry what a per-set recovery number needs: `health_sample` stores
heart rate about every 5 s during a workout plus a ten-minute tail, `workout_link` binds the
workout to the session, and `workout_execution_event` records the `set_completed` taps. The
question was never whether it could be computed; it was whether it says anything.

## What the measurement showed

Four watch sessions, 71 set completions, 64 with both endpoints inside tolerance (coverage 0.901):

| Measure | Value |
|---|---|
| Delta 60 s after the set | median 12 bpm, SD 12.8, range roughly -18 to +43 |
| Within- vs between-session spread | 12.8 vs 7.1 bpm — the noise is the signal |
| Correlation with load | +0.283 |
| Correlation with set duration | about -0.5 in the first looser run (see note) |

Decisive failure: **within-session noise exceeds the between-session signal**. The load
correlation is below its 0.40 bar with the strict endpoint matcher this module uses; the earlier
ad-hoc run, which matched the end-of-set sample by nearest rather than last-preceding, measured
+0.51 and -0.57 for duration. Either way the conference is the same: the number tracks how hard
the set was, and it varies more inside one session than between sessions.

## How it is shown

- Session detail (web and phone) adds `hrr60_bpm` per set and a footnote stating the caveat:
  "tracks set duration and load; not a recovery measure". A set without both endpoints shows
  nothing — the derivation never interpolates.
- Session detail also reports recovery from the **final set** at one and two minutes, anchored to
  that set's completion rather than to the workout's `ended_at` tap — the tap can come minutes
  later, by which time the heart rate has already fallen, and the number would then measure how
  long the user took to stop the workout. The two horizons are reported independently and each may
  be absent. Heart rate often rises again after the session while the user moves around, so a
  two-minute value can be smaller than the one-minute value; that is the physiology, not a bug.
- The Today card shows the corpus figures and the verdict, read-only.
- Nothing reads the value back: not adherence, not readiness, not the prescription, not the
  watch. It exists so the owner can see what was measured rather than take it on trust.

Values are only computed for sets whose clean rows still point at their workout set. A set created
or replaced by a session edit reports no value, which is why the per-set count (46 on the same
corpus at the time of writing) is lower than the corpus measurement's 64.

## When to re-run

Four sessions cannot prove absence of signal, so the question is re-measured rather than settled
for ever. The Today card waits visibly until 15 watch sessions carry telemetry, then asks for a
review; a review is due again 12 weeks later. Run the probe on the host that holds the database:

```
python tools/hr_recovery_probe.py --db data/coach.db
```

It applies the decision rule fixed in the module: coverage >= 0.70, within-session SD below
between-session SD, and |corr(delta, load)| <= 0.40. Do not move the bars after seeing a result,
and do not copy the database off the server to run it.

## Open question it exposed

`corr(hr_end, set_duration)` is negative, which is not physiological. The watch's set taps are
user input, not sensor events, so any timing-derived analysis (tempo, time under tension, wasted
setup) inherits that error and would need the taps fixed first.
