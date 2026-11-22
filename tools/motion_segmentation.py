#!/usr/bin/env python
"""Offline rep segmentation and velocity from watch motion recordings (WP5).

Reads the JSON files the watch writes (one per set, see
`StrengthApp/docs/WATCH-MOTION-CAPTURE.md`), segments reps, derives phase durations and a
velocity estimate, and compares the result with a reference (LPT) per-rep list.

    python tools/motion_segmentation.py --file recording.json
    python tools/motion_segmentation.py --dir data/motion --json out.json
    python tools/motion_segmentation.py --file r.json --reference lpt.json

This is the study harness, not server behaviour. It never writes to the database and nothing in
`strength_coach` imports it. The algorithm here is the reference implementation: the on-device
Swift port must reproduce these fixture cases before it may write `method_version`.

Method
------
1. Project the user acceleration onto the movement axis: gravity is "down" for vertical lifts;
   for horizontal lifts the dominant principal axis of the active window is used.
2. Mark rest intervals from the vector acceleration magnitude. Their midpoints are zero-velocity
   anchors, which is what makes integration tractable at 100 Hz.
3. Integrate to velocity, detrending each inter-anchor segment back to zero at both ends, then
   integrate again to displacement with the same anchoring. This is the standard way to remove
   integration drift without inventing a filter.
4. Split each rep at its displacement extremum: that is the turnaround, so the lowering and
   lifting durations fall out rather than being guessed from acceleration peaks.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

# Sampling assumptions. The watch records at the hardware maximum; 100 Hz is the design point.
NOMINAL_RATE_HZ = 100.0
# A rest is a low mean acceleration whose variation over the window is also low.
REST_ACCEL_G = 0.02
REST_VARIATION_G = 0.01
# Relative floors, because sensor scale and movement intensity vary between sets.
REST_VARIATION_FRACTION = 0.05
REST_MIN_MS = 200
# Shorter than this is a jitter, not a rep.
MIN_REP_MS = 300
# Fraction of the peak displacement a turnaround must reach to count as a rep.
MIN_ROM_FRACTION = 0.25
# Below this, the "rep" is sensor noise on a rest interval rather than a movement.
MIN_ROM_M = 0.05
# Displacement closer to the set's start than this fraction of its amplitude marks a rest as a
# rep boundary. Further away means the athlete paused mid-rep, not between reps.
PAUSE_BOUNDARY_FRACTION = 0.15


@dataclass
class Rep:
    index: int
    start_s: float
    end_s: float
    lower_ms: int
    lift_ms: int
    pause_ms: int
    rom_m: float
    mean_velocity_mps: float
    peak_velocity_mps: float


@dataclass
class SetAnalysis:
    reps: list[Rep] = field(default_factory=list)
    duration_s: float = 0.0
    abstention: str | None = None
    reason: str | None = None
    axis: str | None = None
    gap_ok: bool = False


def load_recording(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _samples(recording: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    samples = recording.get("samples") or []
    if not samples:
        raise ValueError("recording has no samples")
    t = np.array([float(sample["t"]) for sample in samples], dtype="float64")
    accel = np.array(
        [[sample["ax"], sample["ay"], sample["az"]] for sample in samples], dtype="float64"
    )
    gravity = np.array(
        [[sample["gx"], sample["gy"], sample["gz"]] for sample in samples], dtype="float64"
    )
    order = np.argsort(t)
    return t[order], accel[order], gravity[order]


def _axis_projection(t, accel, gravity, axis: str | None) -> np.ndarray:
    """Acceleration along the movement axis, positive downward for vertical lifts."""
    if axis == "horizontal":
        # Dominant axis of the motion itself; gravity says nothing about which way a row travels.
        centred = accel - accel.mean(axis=0)
        _, _, components = np.linalg.svd(centred, full_matrices=False)
        direction = components[0]
        if direction[0] < 0:
            direction = -direction
        return centred @ direction
    down = gravity.mean(axis=0)
    norm = float(np.linalg.norm(down))
    direction = down / norm if norm else np.array([0.0, 0.0, -1.0])
    return accel @ direction


def _rest_mask(accel) -> np.ndarray:
    """True where the movement is still.

    Neither acceleration nor velocity alone identifies a rest. Near the turnarounds the velocity
    is zero while the acceleration is at its peak; near the fastest point of a rep the
    acceleration is near zero while the movement is at its peak. Stillness is therefore "low
    acceleration **and** unchanging acceleration over the minimum duration": at a turnaround the
    acceleration is large, and mid-rep it changes quickly, so both are excluded.
    """
    magnitude = np.linalg.norm(accel, axis=1)
    minimum = max(1, int(REST_MIN_MS / 1000 * NOMINAL_RATE_HZ))
    if len(accel) < minimum:
        return magnitude < REST_ACCEL_G

    windows = np.lib.stride_tricks.sliding_window_view(accel, minimum, axis=0)
    # Shape: (n - minimum + 1, axes, minimum)
    means = windows.mean(axis=2)
    deviations = windows.std(axis=2)
    mean_magnitude = np.linalg.norm(means, axis=1)
    variation = np.linalg.norm(deviations, axis=1)
    variation_peak = float(variation.max()) if variation.size else 0.0
    variation_threshold = max(REST_VARIATION_G, REST_VARIATION_FRACTION * variation_peak)

    still = np.zeros(len(accel), dtype=bool)
    half = minimum // 2
    still[half:half + len(variation)] = (
        (mean_magnitude < REST_ACCEL_G) & (variation < variation_threshold)
    )
    # A rest must last, not just flicker: require the whole minimum window to be still.
    counts = np.convolve(still.astype(int), np.ones(minimum), mode="same")
    return counts >= minimum


def _rest_runs(rest: np.ndarray) -> list[tuple[int, int]]:
    """Maximal still runs, as inclusive index pairs."""
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(rest):
        if not rest[index]:
            index += 1
            continue
        end = index
        while end + 1 < len(rest) and rest[end + 1]:
            end += 1
        runs.append((index, end))
        index = end + 1
    return runs


def _expand_runs(
    runs: list[tuple[int, int]], length: int, margin: int
) -> list[tuple[int, int]]:
    """Grow each run by the detection margin.

    A rest is only confirmed once a whole window is still, so the detected run starts late and
    ends early by roughly half a window. Expanding restores the true motion boundary instead of
    charging that lag to the rep's phase duration.
    """
    expanded: list[tuple[int, int]] = []
    for start, end in runs:
        low = max(0, start - margin)
        high = min(length - 1, end + margin)
        if expanded and low <= expanded[-1][1] + 1:
            expanded[-1] = (expanded[-1][0], max(expanded[-1][1], high))
        else:
            expanded.append((low, high))
    return expanded


def _motion_windows(
    runs: list[tuple[int, int]], length: int
) -> list[tuple[int, int, int | None]]:
    """Motion intervals between still runs, each with the still run that follows it."""
    windows: list[tuple[int, int, int | None]] = []
    previous_end = 0
    previous_rest: int | None = None
    for index, (start, end) in enumerate(runs):
        if start > previous_end:
            # The third element is the rest this window follows, which is what decides whether
            # the window belongs to the same rep as the one before it.
            windows.append((previous_end, start - 1, previous_rest))
        previous_end = end + 1
        previous_rest = index
    if previous_end <= length - 1:
        windows.append((previous_end, length - 1, previous_rest))
    return windows


def _integrate(t, values) -> np.ndarray:
    """Plain cumulative trapezoid integral."""
    out = np.zeros_like(values)
    out[1:] = np.cumsum(0.5 * (values[1:] + values[:-1]) * np.diff(t))
    return out


def _integrate_detrended(t, values, anchors) -> np.ndarray:
    """Cumulative integral with each inter-anchor segment forced back to zero at both ends.

    The anchors are rests, where velocity is physically zero. Spreading the residual linearly
    across the segment removes drift without a filter that would also remove the signal.
    """
    integral = np.zeros_like(values)
    for index in range(1, len(values)):
        integral[index] = integral[index - 1] + 0.5 * (values[index] + values[index - 1]) * (
            t[index] - t[index - 1]
        )
    for start, end in zip(anchors[:-1], anchors[1:], strict=True):
        if end <= start:
            continue
        segment = integral[start:end + 1]
        residual_start = integral[start]
        residual_end = integral[end]
        fraction = (t[start:end + 1] - t[start]) / max(t[end] - t[start], 1e-9)
        integral[start:end + 1] = segment - (
            residual_start + (residual_end - residual_start) * fraction
        )
    return integral


def analyse(recording: dict) -> SetAnalysis:
    gap = recording.get("gap") or {}
    if gap and not gap.get("isHealthy", True):
        return SetAnalysis(
            abstention="gaps", reason="capture has delivery gaps", gap_ok=False
        )

    try:
        t, accel, gravity = _samples(recording)
    except ValueError as error:
        return SetAnalysis(abstention="no_samples", reason=str(error))

    axis = (recording.get("context") or {}).get("axis") or "vertical"
    along = _axis_projection(t, accel, gravity, axis)
    # Remove the constant offset: gravity is already excluded, but a bias in the sensor remains.
    along = along - float(np.mean(along))
    rest = _rest_mask(accel)
    # Two window-wide passes shrink a detected run by roughly one full window on each side
    # (the sliding criterion, then the "must last" convolution), so the margin is the window.
    margin = max(1, int(REST_MIN_MS / 1000 * NOMINAL_RATE_HZ))
    runs = _expand_runs(_rest_runs(rest), len(t), margin)

    # Zero-velocity anchors: the middle of every still stretch, including a pause at the bottom
    # of a rep. A pause is a genuine zero-velocity point, so it helps the integration even when
    # it must not separate two reps.
    anchors = sorted({0, len(t) - 1} | {(start + end) // 2 for start, end in runs})

    velocity = _integrate_detrended(t, along, anchors)
    # Velocity is zero at every anchor, so a plain integration keeps displacement continuous:
    # at a pause the position is at the bottom of the rep, not at zero, and forcing it to zero
    # there would erase the rep's range of motion.
    displacement = _integrate(t, velocity)

    # A still stretch at the bottom of a rep is a pause, not a boundary: merge across it when
    # the displacement there is far from the set's starting position.
    baseline = float(displacement[0])
    amplitude = float(displacement.max() - displacement.min())
    merged: list[list[int]] = []
    for start, end, rest_index in _motion_windows(runs, len(t)):
        if merged and rest_index is not None and amplitude > 0:
            run_start, run_end = runs[rest_index]
            boundary = float(displacement[(run_start + run_end) // 2])
            if abs(boundary - baseline) > PAUSE_BOUNDARY_FRACTION * amplitude:
                merged[-1][1] = end
                continue
        merged.append([start, end])

    reps: list[Rep] = []
    for start, end in merged:
        if (t[end] - t[start]) * 1000 < MIN_REP_MS:
            continue
        window = displacement[start:end + 1]
        span = float(window.max() - window.min())
        if span < MIN_ROM_M:
            continue
        # Turnaround is the extremum furthest from the start of the rep.
        if abs(float(window.max() - window[0])) >= abs(float(window.min() - window[0])):
            turn = int(np.argmax(window))
        else:
            turn = int(np.argmin(window))
        if turn <= 0 or turn >= len(window) - 1:
            continue
        turn_index = start + turn
        lower_ms = int(round((t[turn_index] - t[start]) * 1000))
        lift_ms = int(round((t[end] - t[turn_index]) * 1000))
        rom = abs(float(displacement[turn_index] - displacement[start]))
        # Concentric mean velocity is the VBT quantity: displacement over the lifting phase,
        # not over the whole rep, which would dilute it with the descent.
        lift_seconds = max(float(t[end] - t[turn_index]), 1e-9)
        mean_velocity = rom / lift_seconds
        peak_velocity = float(np.max(np.abs(velocity[turn_index:end + 1])))
        pause_ms = int(round(_pause_ms(t, along, start, end) * 1000))
        if rom < MIN_ROM_FRACTION * max(span, 1e-9):
            continue
        reps.append(
            Rep(
                index=len(reps) + 1,
                start_s=round(float(t[start] - t[0]), 3),
                end_s=round(float(t[end] - t[0]), 3),
                lower_ms=lower_ms,
                lift_ms=lift_ms,
                pause_ms=pause_ms,
                rom_m=round(rom, 3),
                mean_velocity_mps=round(mean_velocity, 3),
                peak_velocity_mps=round(peak_velocity, 3),
            )
        )

    if not reps:
        return SetAnalysis(abstention="no_reps", reason="no complete rep found", axis=axis,
                           duration_s=round(float(t[-1] - t[0]), 3), gap_ok=True)
    return SetAnalysis(
        reps=reps,
        duration_s=round(float(t[-1] - t[0]), 3),
        axis=axis,
        gap_ok=True,
    )


def _pause_ms(t, along, start: int, end: int) -> float:
    """Longest stretch inside the rep where the axis acceleration is nearly still."""
    window = along[start:end + 1]
    still = np.abs(window) < REST_ACCEL_G
    best = 0
    run = 0
    for flag in still:
        run = run + 1 if flag else 0
        best = max(best, run)
    if best < 2:
        return 0.0
    return best / NOMINAL_RATE_HZ


def compare(ours: list[float], reference: list[float]) -> dict:
    """Agreement statistics between our per-rep velocities and the reference device."""
    if len(ours) != len(reference) or not ours:
        raise ValueError("per-rep lists must be non-empty and the same length")
    a = np.asarray(ours, dtype="float64")
    b = np.asarray(reference, dtype="float64")
    diff = a - b
    bias = float(diff.mean())
    sd = float(diff.std(ddof=1)) if len(diff) > 1 else 0.0
    return {
        "n": int(len(diff)),
        "bias_mps": round(bias, 4),
        "sd_mps": round(sd, 4),
        "loa_low": round(bias - 1.96 * sd, 4),
        "loa_high": round(bias + 1.96 * sd, 4),
        "cv_pct": round(100 * sd / float(b.mean()), 2) if float(b.mean()) else None,
        "mdc95_mps": round(1.96 * math.sqrt(2) * sd, 4),
        "pearson_r": round(float(np.corrcoef(a, b)[0, 1]), 3) if len(diff) > 2 else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="one recording JSON")
    source.add_argument("--dir", type=Path, help="a directory of recordings")
    parser.add_argument("--reference", type=Path, help="reference per-rep JSON list")
    parser.add_argument("--json", type=Path, help="write the result as JSON")
    args = parser.parse_args(argv)

    paths = [args.file] if args.file else sorted(args.dir.glob("*.json"))
    results = []
    for path in paths:
        analysis = analyse(load_recording(path))
        payload = {"file": path.name, **asdict(analysis)}
        results.append(payload)
        if analysis.abstention:
            print(f"{path.name}: abstain ({analysis.abstention}: {analysis.reason})")
            continue
        print(f"{path.name}: {len(analysis.reps)} reps, axis {analysis.axis}")
        for rep in analysis.reps:
            print(
                f"  rep {rep.index}: lower {rep.lower_ms} ms, lift {rep.lift_ms} ms, "
                f"pause {rep.pause_ms} ms, rom {rep.rom_m} m, "
                f"mv {rep.mean_velocity_mps} m/s, pv {rep.peak_velocity_mps} m/s"
            )

    if args.reference and len(results) == 1 and not results[0]["abstention"]:
        reference = json.loads(args.reference.read_text())
        ours = [rep["mean_velocity_mps"] for rep in results[0]["reps"]]
        print(json.dumps(compare(ours, reference), indent=2))

    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
