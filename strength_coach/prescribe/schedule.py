"""Rolling session-type selection.

A/B/C are historical identities. The new programme chooses a session type from the last few
sessions instead of advancing a rigid calendar: squat, hinge, bench+squat or bench+hinge. The
target over six sessions is two squat, two hinge and two bench-emphasis sessions; every session
still contains bench or another upper-body press/pull.
"""

from __future__ import annotations

from collections import Counter

from strength_coach.store import queries

SESSION_TYPES = ("squat", "hinge", "bench_squat", "bench_hinge")
TYPE_TO_LEGACY = {
    "squat": "A",
    "hinge": "B",
    "bench_squat": "C",
    "bench_hinge": "C",
}
LEGACY_TO_FAMILY = {"A": "squat", "B": "hinge", "C": "bench"}
TARGETS = {"squat": 2, "hinge": 2, "bench": 2}
WINDOW = 6


def legacy_day(session_type: str) -> str:
    try:
        return TYPE_TO_LEGACY[session_type]
    except KeyError as exc:
        raise ValueError(f"unknown session type {session_type!r}") from exc


def _family(session_type: str) -> str:
    if session_type in ("bench_squat", "bench_hinge"):
        return "bench"
    return session_type


def next_session_type(conn, before: str, *, prior_types=()) -> str:
    """Choose the next type from recent day guesses plus any forecast choices.

    `prior_types` is used by the programme forecast, where future sessions do not exist in
    SQLite yet. It accepts session-type names or legacy A/B/C labels.
    """
    sessions = queries.sessions(conn, end=before)
    recent = [] if sessions.empty else [str(v) for v in sessions.tail(WINDOW)["day_guess"]]
    for item in prior_types:
        value = str(item)
        recent.append(value)

    counts: Counter[str] = Counter()
    last = None
    for value in recent:
        if value in TYPE_TO_LEGACY:
            family = _family(value)
        elif value in LEGACY_TO_FAMILY:
            family = LEGACY_TO_FAMILY[value]
        else:
            continue
        counts[family] += 1
        last = value

    deficits = {family: TARGETS[family] - counts.get(family, 0) for family in TARGETS}
    if not recent:
        return "squat"

    # Two rules, in order:
    #   1. follow the preferred emphasis cycle if the next family still has a deficit;
    #   2. otherwise take the largest deficit.
    # This keeps the two-week squat/hinge/bench rhythm while letting missed sessions shift the
    # next choice instead of silently advancing a calendar.
    last_family = LEGACY_TO_FAMILY.get(str(last), str(last))
    if last_family not in TARGETS:
        last_family = _family(str(last)) if str(last) in TYPE_TO_LEGACY else last_family
    successor = {"squat": "hinge", "hinge": "bench", "bench": "squat"}.get(last_family)
    if successor is not None and deficits.get(successor, 0) > 0:
        family = successor
    else:
        best = max(deficits.values())
        family = next(f for f in ("squat", "hinge", "bench") if deficits[f] == best)

    if family == "bench":
        # Alternate the support when the previous bench session is known; otherwise support
        # whichever main lift has fewer recent exposures.
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
