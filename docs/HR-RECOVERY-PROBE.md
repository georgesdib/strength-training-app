# Per-set heart-rate recovery: probe and decision

**Status:** decided 2026-11-22 — not a feature. Re-measured on a cadence by
[`tools/hr_recovery_probe.py`](../tools/hr_recovery_probe.py); the prompt lives in the Today
view under **Periodic reviews** (`hr_recovery_probe`).

## Why this exists

Apple Watch sessions already carry everything needed to compute a per-set heart-rate recovery
number: `health_sample` stores heart rate every ~5 s during a workout plus a ten-minute tail,
`workout_link` binds the workout to the session, and `workout_execution_event` records
`set_started` / `set_completed` taps. The question was never whether it *could* be computed; it
was whether it says anything.

## What the measurement showed

Four watch sessions, 71 completed sets, 64 with both endpoints inside tolerance (coverage 0.90):

| Check | Result |
|---|---|
| `delta60` (HR at set end minus one minute later) | median 12 bpm, SD 13.5, range -18 to +43 |
| Within- vs between-session spread | 12.8 vs 7.1 bpm — noise is the signal |
| Correlation with set duration | -0.57 |
| Correlation with load | +0.51 |
| Correlation with reps | -0.16 |

So the number mostly re-encodes how hard the set was, which the prescription already knows,
and it varies more within a session than between sessions. The rest-window variant does worse:
median HR is 3 bpm *higher* when the next set starts.

## What was shipped instead

Average and peak heart rate from the linked workout are shown on session detail, for the phone
app and the web UI (`history.detail().heart_rate`). That is Apple's own number, needs no
derivation, and answers the question the per-set metric was standing in for.

## When to re-run

Four sessions make the correlations unstable, so absence of signal is not proven. The probe
re-runs on a 12-week cadence once 15 watch sessions carry telemetry. Until then the Today card
stays visible as a *waiting* item carrying the counter (for example "4/15 watch sessions"), so the
prompt is never indistinguishable from one that was never added; it becomes actionable at the
threshold and again 12 weeks after each review. Run it on the host that holds the database:

```
python tools/hr_recovery_probe.py --db data/coach.db
```

It prints a `verdict` block applying the decision rule in its module docstring: coverage ≥ 0.70,
within-session SD < between-session SD, |r| ≤ 0.40 against load and set duration, and |r| ≥ 0.30
against reps. Every bar must clear before the feature question reopens. Do not move the bars
after seeing a result, and do not copy the database off the server to run it.

## Open question it exposed

`corr(hr_end, set_duration)` is negative, which is not physiological. The watch's set taps are
user input, not sensor events, so any timing-derived analysis (tempo, time under tension, wasted
setup) inherits that error and would need the taps fixed first.
