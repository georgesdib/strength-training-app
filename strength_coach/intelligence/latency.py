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
    "ODROID, copied production database (377 sessions, 7,978 clean sets), "
    "real MCP HTTP, 30 measured requests and 5 warm-ups"
)

#: capability name -> (HTTP p95 in milliseconds, classification)
MEASURED: dict[str, tuple[int, str]] = {
    "get_exercise_progression": (67, "fast"),
    "get_prescription": (40, "fast"),
    "get_vbt_analysis": (63, "fast"),
    "get_adherence_analysis": (130, "fast"),
    "compare_training_periods": (194, "fast"),
    "get_readiness_history": (1663, "slow"),
    "get_programme_block_summary": (3800, "slow"),
    "get_training_overview": (4058, "slow"),
    "get_session_details": (6201, "very_slow"),
}

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
    return (
        f"\n\nMeasured latency: {kind} (HTTP p95 {p95:,} ms on {MEASURED_ON}; {SOURCE}). "
        "This is a historical benchmark, not a runtime guarantee. "
        f"{_GUIDANCE[kind]} Never omit or alter required evidence merely to avoid latency."
    )


def catalogue() -> list[dict[str, object]]:
    return [
        {"capability": name, "http_p95_ms": p95, "classification": kind}
        for name, (p95, kind) in sorted(MEASURED.items())
    ]
