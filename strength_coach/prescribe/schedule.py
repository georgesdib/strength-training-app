"""Rolling session-type selection.

The programme chooses one of four canonical session types from recent history instead of
advancing a rigid calendar: squat, hinge, bench+squat or bench+hinge. The target over six
sessions is two squat, two hinge and two bench-emphasis sessions.

When the target is already met, the tie-break rotates to the family seen least recently. A
fixed family order here would repeatedly choose squat after a history with no squat, which is
how three consecutive squat sessions were produced.
"""

from __future__ import annotations

import threading
from collections import Counter, OrderedDict
from typing import Any

from strength_coach.features import training_day
from strength_coach.prescribe import session_identity
from strength_coach.utils import paths

SESSION_TYPES = ("squat", "hinge", "bench_squat", "bench_hinge")
TARGETS = ("squat", "hinge", "bench")
TARGET_COUNTS = {"squat": 2, "hinge": 2, "bench": 2}
WINDOW = 6


def _availability(conn, before: str | None = None) -> dict[str, bool]:
    """Session-type availability, from the resolver when enabled."""
    from strength_coach.prescribe import constraints as constraints_mod
    from strength_coach.prescribe import generator, resolver_settings, templates

    if before is not None and resolver_settings.ResolverSettings.load(conn, before).enabled:
        return generator.available_session_types(conn, before)

    out: dict[str, bool] = {}
    for session_type in SESSION_TYPES:
        primary = templates.SessionTemplate.load(session_type).primary_exercise
        if not primary:
            out[session_type] = True
            continue
        out[session_type] = not constraints_mod.evaluate(
            conn, [primary], as_of=before
        ).vetoes
    return out


def _targets(available: set[str]) -> dict[str, int]:
    """Keep the six-session family target and redistribute unavailable families."""
    counts = {family: 0 for family in TARGETS}
    for family in available:
        counts[family] = TARGET_COUNTS[family]
    missing = sum(TARGET_COUNTS.values()) - sum(counts.values())
    ordered = [family for family in TARGETS if family in available]
    if not ordered:
        raise ValueError("no schedule family is available under the stored constraints")
    for index in range(missing):
        counts[ordered[index % len(ordered)]] += 1
    return counts


def _family(session_type: str) -> str | None:
    return session_identity.rotation_family(session_type)


def _choose_family(recent: list[str], targets: dict[str, int]) -> str:
    """Pick the emphasis family, with least-recent rotation on a target tie."""
    available = {family for family, count in targets.items() if count > 0}
    if not recent:
        return min(available, key=TARGETS.index)

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
        family: targets[family] - counts.get(family, 0) for family in TARGETS
    }

    # Prefer the next family in the squat -> hinge -> bench cycle while it still has a
    # deficit. This is what keeps the rhythm rather than always taking the largest gap.
    successor = {"squat": "hinge", "hinge": "bench", "bench": "squat"}.get(last_family)
    if successor is not None and deficits[successor] > 0:
        return successor

    # If the successor has no remaining deficit, rotate rather than taking the largest
    # deficit: history can already be over target for a family, and a max-deficit rule would
    # then avoid it for many sessions. Least-recent keeps the emphasis cycle moving.
    return min(
        (family for family in TARGETS if targets.get(family, 0) > 0),
        key=lambda family: last_seen.get(family, -1),
    )


def _schedule_stamp(conn) -> tuple[int, int, tuple[int, ...]]:
    """Database and config stamp that makes a per-connection schedule cache safe."""
    try:
        data_version = int(conn.execute("PRAGMA data_version").fetchone()[0])
    except Exception:
        data_version = -1
    try:
        changes = int(conn.total_changes)
    except Exception:
        changes = -1
    mtimes = []
    for path in (paths.session_types_yaml(), paths.template_resolver_yaml()):
        try:
            mtimes.append(int(path.stat().st_mtime_ns))
        except OSError:
            mtimes.append(0)
    return data_version, changes, tuple(mtimes)


#: Choices are shared across connections by database identity and the same stamp that guarded
#: the old per-connection cache. Keying on the connection made every HTTP request (each opens
#: a new one) recompute the full history scan, which is seconds on the production database.
_SCHEDULE_CACHE: OrderedDict[tuple[Any, ...], str] = OrderedDict()
_SCHEDULE_CACHE_LOCK = threading.Lock()
_SCHEDULE_CACHE_MAX = 64


def _database_key(conn) -> str:
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
    except Exception:
        return ""
    if rows and rows[0][2]:
        return str(rows[0][2])
    # In-memory databases have no stable identity across connections; cache per call instead.
    return ""


_AVAILABILITY_CACHE: OrderedDict[tuple[Any, ...], dict[str, bool]] = OrderedDict()
_AVAILABILITY_CACHE_LOCK = threading.Lock()
_AVAILABILITY_CACHE_MAX = 64


def _availability_cached(conn, before: str | None) -> dict[str, bool]:
    """Availability per database revision and date.

    A report asks for the next type once per projected session, and every date-key miss rebuilt
    the full rule context. One computation per revision and date is enough; a writer or config
    edit changes the stamp. In-memory databases have no cross-connection identity and stay
    uncached.
    """
    database = _database_key(conn)
    if not database or before is None:
        return _availability(conn, before)
    data_version, changes, config_stamp = _schedule_stamp(conn)
    key = (database, before, data_version, changes, config_stamp)
    with _AVAILABILITY_CACHE_LOCK:
        cached = _AVAILABILITY_CACHE.get(key)
        if cached is not None:
            _AVAILABILITY_CACHE.move_to_end(key)
            return cached
        value = _availability(conn, before)
        _AVAILABILITY_CACHE[key] = value
        _AVAILABILITY_CACHE.move_to_end(key)
        while len(_AVAILABILITY_CACHE) > _AVAILABILITY_CACHE_MAX:
            _AVAILABILITY_CACHE.popitem(last=False)
        return value


def next_session_type(conn, before: str, *, prior_types=()) -> str:
    """Choose the next type from recent training days plus any forecast choices.

    Results are memoised across connections by database identity, SQLite's data version, the
    connection's write count and the template/policy file mtimes. A writer or config edit
    changes the key; within one database revision every request reuses the same choice.
    """
    prior = tuple(str(item) for item in prior_types)
    database = _database_key(conn)
    if not database:
        return _next_session_type_uncached(conn, before, prior_types=prior)
    data_version, changes, config_stamp = _schedule_stamp(conn)
    key = (database, before, prior, data_version, changes, config_stamp)
    with _SCHEDULE_CACHE_LOCK:
        cached = _SCHEDULE_CACHE.get(key)
        if cached is not None:
            _SCHEDULE_CACHE.move_to_end(key)
            return cached
        value = _next_session_type_uncached(conn, before, prior_types=prior)
        _SCHEDULE_CACHE[key] = value
        _SCHEDULE_CACHE.move_to_end(key)
        while len(_SCHEDULE_CACHE) > _SCHEDULE_CACHE_MAX:
            _SCHEDULE_CACHE.popitem(last=False)
        return value


def _next_session_type_uncached(conn, before: str, *, prior_types=()) -> str:
    """Uncached rolling-session choice used by the memoised public entry point."""
    days = training_day.group(conn, end=before, with_exercises=False)
    recent = [
        str(day["planned_type"]) for day in days
        if day.get("planned_type") and day.get("planned_type") != "mixed"
    ][-WINDOW:]
    recent.extend(str(item) for item in prior_types)

    availability = _availability_cached(conn, before)
    available_families = {
        family for family in TARGETS
        if any(availability.get(session_type) for session_type in SESSION_TYPES
               if _family(session_type) == family)
    }
    targets = _targets(available_families)
    family = _choose_family(recent, targets)
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