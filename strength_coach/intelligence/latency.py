"""Measured latency metadata for the MCP tool catalogue.

The values come from the extended HTTP benchmark on the ODROID (2026-11-14): a copied production
database of 377 sessions / 7,978 clean sets, 30 measured requests and 5 warm-ups per capability,
real Streamable HTTP transport. They are historical measurements, not runtime guarantees.

This module is the single source for the numbers used in tool descriptions. Update it only with a
new measured run; never copy the values into another component.
"""

from __future__ import annotations

MEASURED_ON = "2026-11-14"
SOURCE = (
    "ODROID, copied production database (377-378 sessions, ~8,000 clean sets), "
    "real MCP HTTP, 30 measured requests and 5 warm-ups; weekly review measured 2026-11-15"
)

#: capability name -> (HTTP p95 in milliseconds, classification)
MEASURED: dict[str, tuple[int, str]] = {
    "get_exercise_progression": (45, "fast"),
    "get_prescription": (46, "fast"),
    "get_vbt_analysis": (69, "fast"),
    "get_adherence_analysis": (145, "fast"),
    "compare_training_periods": (189, "fast"),
    "get_readiness_history": (377, "fast"),
    "get_programme_block_summary": (278, "fast"),
    "get_training_overview": (672, "slow"),
    "get_session_details": (5684, "very_slow"),
    # Added after the ODROID run: measured over real MCP HTTP on the development Mac
    # (221-session synthetic database, 12 measured requests) and provisional until the next
    # ODROID HTTP benchmark.
    "get_weekly_review": (571, "slow"),
}

#: Capabilities whose figure comes from a different run than SOURCE.
PROVISIONAL: dict[str, str] = {}

_GUIDANCE = {
    "fast": "Prefer this capability when it supplies sufficient evidence.",
    "slow": (
        "Invoke it when its additional evidence is materially useful, and avoid repeated calls "
        "in one task."
    ),
    "very_slow": (
        "Use it only when its full evidence is needed; avoid repeated calls and consider whether a "
        "narrower or faster capability answers the question first."
    ),
}


def classification(name: str) -> str:
    return MEASURED[name][1]


def measured_p95(name: str) -> int:
    return MEASURED[name][0]


def description(name: str) -> str:
    """Latency guidance appended to a tool description."""
    if name not in MEASURED:
        raise KeyError(f"no latency measurement for {name!r}")
    p95, kind = MEASURED[name]
    source = PROVISIONAL.get(name, SOURCE)
    return (
        f"\n\nMeasured latency: {kind} (HTTP p95 {p95:,} ms on {MEASURED_ON}; {source}). "
        "This is a historical benchmark, not a runtime guarantee. "
        f"{_GUIDANCE[kind]} Never omit or alter required evidence merely to avoid latency."
    )


def catalogue() -> list[dict[str, object]]:
    return [
        {"capability": name, "http_p95_ms": p95, "classification": kind}
        for name, (p95, kind) in sorted(MEASURED.items())
    ]
