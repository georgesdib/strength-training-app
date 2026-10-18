"""Shared renderers for the calibration loop.

Kept in one place so the CLI and the tools cannot drift: the sheet shown while marking and
the report shown afterwards are the same text in both.
"""

from __future__ import annotations

import pandas as pd

from strength_coach.eval.labels import ITEM_GUIDE, ITEM_KEYS


def format_session_sheet(facts, critique) -> str:
    """The side-by-side view: session as performed, then the engine's scores."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(
        f"session {facts.session_id}  ({facts.occurred_on}, day {facts.day}, "
        f"label {facts.workout_label or 'none'})"
    )
    lines.append("=" * 78)

    working = facts.sets[facts.sets["is_working_set"]]
    lines.append(f"working sets: {len(working)}   all sets: {len(facts.sets)}")
    lines.append("")
    header = f"{'exercise':<24}{'sets':>5}{'reps':>8}{'load kg':>14}{'rir':>10}"
    lines.append(header)
    lines.append("-" * len(header))
    for exercise_id, group in working.groupby("exercise_id"):
        rir = sorted({int(v) for v in group["rir"].dropna()})
        lines.append(
            f"{exercise_id:<24}{len(group):>5}{_range(group['reps']):>8}"
            f"{_range(group['load_kg']):>14}{str(rir):>10}"
        )

    lines.append("")
    lines.append("engine scores")
    lines.append("-" * 60)
    for item in critique.items:
        if item.measurable and item.score is not None:
            lines.append(f"  {item.key:<24}{item.score:>6.2f}   {item.detail[:60]}")
        else:
            lines.append(f"  {item.key:<24}{'  n/a':>6}   {item.detail[:60]}")
    if critique.composite is not None:
        lines.append("")
        lines.append(f"  composite {critique.composite:.2f}")
    return "\n".join(lines)


def format_report(report) -> str:
    """Agreement per session and per item, with the confidence split."""
    lines: list[str] = []
    lines.append(f"tolerance: +/-{report.tolerance:g}")
    lines.append("confidence: only 'high' marks count toward agreement; reconstructed marks are shown")
    lines.append("")
    header = (f"{'session':<14}{'confidence':<12}{'compared':>10}"
              f"{'agreement':>11}{'mae':>8}  disagreements")
    lines.append(header)
    lines.append("-" * (len(header) + 20))
    for session in report.sessions:
        compared = len(session.comparable_items)
        agreement = "-" if session.agreement_rate is None else f"{session.agreement_rate:.0%}"
        mae = "-" if session.mean_abs_error is None else f"{session.mean_abs_error:.2f}"
        lines.append(
            f"{session.session_id:<14}{session.confidence:<12}{compared:>10}"
            f"{agreement:>11}{mae:>8}  {', '.join(session.disagreements) or '-'}"
        )

    overall = report.agreement_rate
    lines.append("")
    lines.append(
        f"headline (high confidence only): {len(report.comparable_items)} comparable items, "
        f"agreement {'-' if overall is None else f'{overall:.0%}'}, "
        f"mean absolute error {'-' if report.mean_abs_error is None else f'{report.mean_abs_error:.2f}'}"
    )
    excluded = report.unreliable_sessions
    if excluded:
        lines.append(
            "excluded as reconstructed/unknown: "
            + ", ".join(s.session_id for s in excluded)
        )

    lines.append("")
    lines.append("per item (high confidence only)")
    lines.append(f"  {'item':<24}{'n':>4}{'agreement':>11}{'mae':>8}  note")
    for key, stats in report.per_item.items():
        agreement = "-" if stats["agreement"] is None else f"{stats['agreement']:.0%}"
        mae = "-" if stats["mae"] is None else f"{stats['mae']:.2f}"
        lines.append(f"  {key:<24}{stats['n']:>4}{agreement:>11}{mae:>8}  {_advice(stats)}")
    return "\n".join(lines)


def _advice(stats: dict) -> str:
    """When an item has enough marks and still disagrees, flag it -- never auto-tune."""
    if not stats["n"] or stats["mae"] is None:
        return ""
    if stats["n"] >= 5 and stats["mae"] > 0.25:
        return "revisit this item's definition or weight"
    if stats["n"] < 5:
        return ""
    return ""


def _range(values: pd.Series) -> str:
    clean = values.dropna()
    if clean.empty:
        return "-"
    low, high = clean.min(), clean.max()
    if low == high:
        return f"{low:g}"
    return f"{low:g}-{high:g}"


def item_guide_lines() -> list[str]:
    """The question each item asks, printed before a review."""
    lines = ["", "what each score means (higher is always better):"]
    for key in ITEM_KEYS:
        question, anchors = ITEM_GUIDE[key]
        lines.append(f"  {key}")
        lines.append(f"    {question}")
        lines.append(f"    {anchors}")
    lines.append("")
    return lines
