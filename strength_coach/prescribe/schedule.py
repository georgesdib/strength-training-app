"""Rolling session-type selection.

The programme chooses one of four canonical session types from recent history instead of
advancing a rigid calendar: squat, hinge, bench+squat or bench+hinge. The target over six
sessions is two squat, two hinge and two bench-emphasis sessions.
"""

from __future__ import annotations

from collections import Counter

from strength_coach.store import queries

SESSION_TYPES = ("squat", "hinge", "bench_squat", "bench_hinge")
TARGETS = {"squat": 2, "hinge": 2, "bench": 2}
WINDOW = 6


def _family(session_type: str) -> str:
    if session_type in ("bench_squat", "bench_hinge"):
        return "bench"
    return session_type


def next_session_type(conn, before: str, *, prior_types=()) -> str:
    """Choose the next type from recent sessions plus any forecast choices."""
    sessions = queries.sessions(conn, end=before)
    recent = [] if sessions.empty else [str(v) for v in sessions.tail(WINDOW)["session_type"]]
    for item in prior_types:
        recent.append(str(item))

    counts: Counter[str] = Counter()
    last = None
    for value in recent:
        if value not in SESSION_TYPES:
            continue
        counts[_family(value)] += 1
        last = value

    deficits = {family: TARGETS[family] - counts.get(family, 0) for family in TARGETS}
    if not recent:
        return "squat"

    # Two rules, in order:
    #   1. follow the preferred emphasis cycle if the next family still has a deficit;
    #   2. otherwise take the largest deficit.
    last_family = _family(str(last)) if last is not None else None
    successor = {"squat": "hinge", "hinge": "bench", "bench": "squat"}.get(last_family)
    if successor is not None and deficits.get(successor, 0) > 0:
        family = successor
    else:
        best = max(deficits.values())
        family = next(f for f in ("squat", "hinge", "bench") if deficits[f] == best)

    if family == "bench":
        last_bench = next(
            (value for value in reversed(recent)
             if value in ("bench_squat", "bench_hinge")),
            None,
        )
        if last_bench == "bench_squat":
            return "bench_hinge"
        if last_bench == "bench_hinge":
            return "bench_squat"
        supports_squat = counts.get("squat", 0) <= counts.get("hinge", 0)
        return "bench_squat" if supports_squat else "bench_hinge"
    return family
