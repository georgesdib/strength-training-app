"""Rolling session-type selection.

The programme chooses one of four canonical session types from recent history instead of
advancing a rigid calendar: squat, hinge, bench+squat or bench+hinge. The target over six
sessions is two squat, two hinge and two bench-emphasis sessions.

When the target is already met, the tie-break rotates to the family seen least recently. A
fixed family order here would repeatedly choose squat after a history with no squat, which is
how three consecutive squat sessions were produced.
"""

from __future__ import annotations

from collections import Counter

from strength_coach.store import queries

SESSION_TYPES = ("squat", "hinge", "bench_squat", "bench_hinge")
TARGETS = ("squat", "hinge", "bench")
TARGET_COUNTS = {"squat": 2, "hinge": 2, "bench": 2}
WINDOW = 6


def _family(session_type: str) -> str | None:
    if session_type == "technique":
        return None
    if session_type.startswith("volume_fill_"):
        session_type = session_type[len("volume_fill_"):]
    if session_type not in SESSION_TYPES:
        return None
    if session_type in ("bench_squat", "bench_hinge"):
        return "bench"
    return session_type


def _choose_family(recent: list[str]) -> str:
    """Pick the emphasis family, with least-recent rotation on a target tie."""
    if not recent:
        return "squat"

    counts: Counter[str] = Counter()
    last_seen: dict[str, int] = {}
    last_family = None
    for index, value in enumerate(recent):
        family = _family(value)
        if family is None:
            continue
        counts[family] += 1
        last_seen[family] = index
        last_family = family

    deficits = {
        family: TARGET_COUNTS[family] - counts.get(family, 0) for family in TARGETS
    }

    # Prefer the next family in the squat -> hinge -> bench cycle while it still has a
    # deficit. This is what keeps the rhythm rather than always taking the largest gap.
    successor = {"squat": "hinge", "hinge": "bench", "bench": "squat"}.get(last_family)
    if successor is not None and deficits[successor] > 0:
        return successor

    # If the successor has no remaining deficit, rotate rather than taking the largest
    # deficit: history can already be over target for a family, and a max-deficit rule would
    # then avoid it for many sessions. Least-recent keeps the emphasis cycle moving.
    return min(TARGETS, key=lambda family: last_seen.get(family, -1))


def next_session_type(conn, before: str, *, prior_types=()) -> str:
    """Choose the next type from recent sessions plus any forecast choices."""
    sessions = queries.sessions(conn, end=before)
    recent = [] if sessions.empty else [str(v) for v in sessions.tail(WINDOW)["session_type"]]
    recent.extend(str(item) for item in prior_types)

    family = _choose_family(recent)
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
        supports_squat = recent.count("squat") <= recent.count("hinge")
        return "bench_squat" if supports_squat else "bench_hinge"
    return family