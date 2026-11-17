#!/usr/bin/env python
"""Link imported workouts to training sessions, and report what cannot be linked.

Two tiers, both recorded on the link itself:

* interval overlap — a session with a measured interval (watch-recorded sessions only) is compared
  with each workout's interval; Jaccard >= 0.90 links, 0.60-0.90 queues, below that is not a candidate;
* day containment — a session with no interval matches a strength workout on the same day in the
  server's zone, and links only when that day holds exactly one session and one strength workout.

Linking never creates, edits or voids a session, and a later run never modifies an existing link.
Corrections are explicit: --unlink, then --link.

    python tools/cardio_link.py --db data/coach.db --dry-run
    python tools/cardio_link.py --db data/coach.db --apply
    python tools/cardio_link.py --db data/coach.db --report
    python tools/cardio_link.py --db data/coach.db --link <workout-key-hex>=<session_id>
    python tools/cardio_link.py --db data/coach.db --unlink <workout-key-hex>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.store import cardio, db  # noqa: E402

BAND_VERSION = "link_v1"
AUTO_OVERLAP = 0.90
QUEUE_OVERLAP = 0.60
SERVER_ZONE = "Europe/London"
STRENGTH_TYPES = (
    "HKWorkoutActivityTypeTraditionalStrengthTraining",
    "HKWorkoutActivityTypeFunctionalStrengthTraining",
)


@dataclass(frozen=True)
class Candidate:
    workout_id: str
    workout_key: str
    session_id: str
    method: str
    overlap: float | None


@dataclass(frozen=True)
class Deferred:
    workout_id: str
    workout_key: str
    reason: str
    session_id: str | None = None


def _local_date(utc_iso: str) -> str:
    """Server-zone date for an instant. Sessions are dated in this zone, so matching uses it."""
    return dt.datetime.fromisoformat(utc_iso).astimezone(ZoneInfo(SERVER_ZONE)).date().isoformat()


def _overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> float:
    a0, a1 = dt.datetime.fromisoformat(a_start), dt.datetime.fromisoformat(a_end)
    b0, b1 = dt.datetime.fromisoformat(b_start), dt.datetime.fromisoformat(b_end)
    intersection = max(0.0, (min(a1, b1) - max(a0, b0)).total_seconds())
    union = max((max(a1, b1) - min(a0, b0)).total_seconds(), 1.0)
    return intersection / union


def _sessions(conn) -> list[dict]:
    return [dict(row) for row in conn.execute("SELECT * FROM session WHERE voided = 0")]


def _session_intervals(conn) -> dict[str, tuple[str, str]]:
    rows = conn.execute(
        """
        SELECT s.session_id, w.started_at, w.ended_at
        FROM session s
        JOIN workout_session w ON w.workout_id = s.workout_id
        WHERE s.voided = 0 AND w.ended_at IS NOT NULL AND w.status = 'completed'
        """
    ).fetchall()
    return {row["session_id"]: (row["started_at"], row["ended_at"]) for row in rows}


def _workouts(conn) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM external_workout ORDER BY started_at, rowid"
        )
    ]


def _linked_workouts(conn) -> set[str]:
    linked = set()
    for workout in _workouts(conn):
        if cardio.active_link(conn, workout["external_workout_id"]) is not None:
            linked.add(workout["external_workout_id"])
    return linked


def evaluate(conn) -> tuple[list[Candidate], list[Deferred]]:
    """Classify every unlinked strength workout into an auto-link or a deferred reason."""
    sessions = _sessions(conn)
    intervals = _session_intervals(conn)
    # A session with a measured interval is decided by tier A only: using its date as well would let
    # day containment claim a workout that the interval says is a different session.
    sessions_by_date: dict[str, list[str]] = {}
    measured_by_date: dict[str, list[str]] = {}
    for session in sessions:
        if session["session_id"] in intervals:
            measured_by_date.setdefault(str(session["occurred_on"]), []).append(
                session["session_id"]
            )
            continue
        sessions_by_date.setdefault(str(session["occurred_on"]), []).append(session["session_id"])

    linked = _linked_workouts(conn) | cardio.hidden_workout_ids(conn)
    used_sessions = set()
    candidates: list[Candidate] = []
    deferred: list[Deferred] = []

    strength = [w for w in _workouts(conn) if w["activity_type"] in STRENGTH_TYPES]
    for workout in strength:
        if workout["external_workout_id"] in linked:
            continue
        key = cardio.key_text(workout["external_key"])

        # Tier A — any session with a measured interval.
        best: tuple[float, str] | None = None
        for session_id, (start, end) in intervals.items():
            if session_id in used_sessions:
                continue
            ratio = _overlap(start, end, workout["started_at"], workout["ended_at"])
            if best is None or ratio > best[0]:
                best = (ratio, session_id)
        if best is not None and best[0] >= QUEUE_OVERLAP:
            ratio, session_id = best
            if ratio >= AUTO_OVERLAP:
                used_sessions.add(session_id)
                candidates.append(
                    Candidate(
                        workout["external_workout_id"], key, session_id, "interval_overlap", ratio
                    )
                )
            else:
                deferred.append(
                    Deferred(
                        workout["external_workout_id"],
                        key,
                        f"interval overlap {ratio:.2f} is below the auto threshold",
                        session_id,
                    )
                )
            continue

        # Tier B — day containment, unique on both sides. A low interval overlap falls through
        # here rather than being rejected: the workout may still be the only one on that day.
        day = _local_date(workout["started_at"])
        same_day_sessions = sessions_by_date.get(day, [])
        measured_today = measured_by_date.get(day, [])
        if best is not None and best[0] > 0 and not same_day_sessions:
            deferred.append(
                Deferred(
                    workout["external_workout_id"],
                    key,
                    f"closest interval overlap {best[0]:.2f} is below {QUEUE_OVERLAP}",
                    best[1],
                )
            )
            continue
        if measured_today and not same_day_sessions:
            deferred.append(
                Deferred(
                    workout["external_workout_id"],
                    key,
                    f"{day} holds only a measured session with no overlap",
                    measured_today[0],
                )
            )
            continue
        same_day_workouts = [
            w
            for w in strength
            if w["external_workout_id"] not in linked and _local_date(w["started_at"]) == day
        ]
        if not same_day_sessions:
            deferred.append(
                Deferred(workout["external_workout_id"], key, f"no session on {day}")
            )
            continue
        if len(same_day_sessions) > 1:
            deferred.append(
                Deferred(
                    workout["external_workout_id"],
                    key,
                    f"{len(same_day_sessions)} sessions on {day}",
                )
            )
            continue
        if len(same_day_workouts) > 1:
            deferred.append(
                Deferred(
                    workout["external_workout_id"],
                    key,
                    f"{len(same_day_workouts)} strength workouts on {day}",
                )
            )
            continue
        candidates.append(
            Candidate(
                workout["external_workout_id"], key, same_day_sessions[0], "day_containment", None
            )
        )
        used_sessions.add(same_day_sessions[0])

    return candidates, deferred


def write_links(conn, candidates: list[Candidate]) -> int:
    written = 0
    with db.transaction(conn):
        for candidate in candidates:
            cardio.link_workout(
                conn,
                external_workout_id=candidate.workout_id,
                session_id=candidate.session_id,
                method=candidate.method,
                band_version=BAND_VERSION,
                confidence=candidate.overlap,
            )
            written += 1
    return written


def _report(conn, candidates: list[Candidate], deferred: list[Deferred]) -> dict:
    by_method: dict[str, int] = {}
    for row in conn.execute(
        """
        SELECT method, COUNT(*) n FROM workout_link WHERE action = 'link' GROUP BY method
        """
    ):
        by_method[row["method"]] = row["n"]
    active = sum(1 for w in _workouts(conn) if cardio.active_link(conn, w["external_workout_id"]))
    return {
        "band_version": BAND_VERSION,
        "server_zone": SERVER_ZONE,
        "auto_linkable": len(candidates),
        "active_links": active,
        "link_events_by_method": by_method,
        "queue": [f.__dict__ for f in deferred],
        "queue_size": len(deferred),
        "workouts": conn.execute("SELECT COUNT(*) FROM external_workout").fetchone()[0],
        "sessions": conn.execute(
            "SELECT COUNT(*) FROM session WHERE voided = 0"
        ).fetchone()[0],
    }


def _resolve_key(conn, key_hex: str) -> dict:
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as exc:
        raise SystemExit(f"workout key must be hex: {key_hex!r}") from exc
    workout = cardio.get_workout(conn, key)
    if workout is None:
        raise SystemExit(f"no workout with key {key_hex}")
    return workout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    parser.add_argument("--apply", action="store_true", help="append link events")
    parser.add_argument("--report", action="store_true", help="link and queue counts only")
    parser.add_argument("--link", metavar="WORKOUT_KEY=SESSION_ID")
    parser.add_argument("--unlink", metavar="WORKOUT_KEY")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    try:
        if args.link:
            key_text, _, session_id = args.link.partition("=")
            workout = _resolve_key(conn, key_text)
            link = cardio.link_workout(
                conn,
                external_workout_id=workout["external_workout_id"],
                session_id=session_id,
                method="manual",
                band_version=BAND_VERSION,
            )
            print(json.dumps({"linked": link["link_id"], "method": "manual"}))
            return 0
        if args.unlink:
            workout = _resolve_key(conn, args.unlink)
            event = cardio.unlink_workout(conn, external_workout_id=workout["external_workout_id"])
            print(json.dumps({"unlinked": event["supersedes_id"]}))
            return 0

        candidates, deferred = evaluate(conn)
        if args.report:
            print(json.dumps(_report(conn, candidates, deferred), indent=2, sort_keys=True))
            return 0
        if args.dry_run:
            payload = _report(conn, candidates, deferred)
            payload["would_link"] = [
                {**c.__dict__, "overlap": c.overlap} for c in candidates
            ]
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if args.apply:
            written = write_links(conn, candidates)
            payload = _report(conn, candidates, deferred)
            payload["linked_now"] = written
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 1 if deferred else 0
        parser.error("choose --dry-run, --apply, --report, --link or --unlink")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
