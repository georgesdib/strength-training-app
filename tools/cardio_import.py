#!/usr/bin/env python
"""Promote an Apple Health export into the cardio corpus.

One-time, re-runnable, offline. Reads the export, writes through the store, records
`history_cutoff`, and refuses to guess a database: `--db` is required so a typo cannot write
into the live store.

    python tools/cardio_import.py --db /tmp/scratch.db --export ~/private/export.zip
    python tools/cardio_import.py --db /tmp/scratch.db --export export.xml --dry-run

Identity is a content key (the export carries no sample UUIDs), so a second run over the same
file writes nothing. Samples are kept only inside a workout or within its 10-minute recovery
tail; everything else is background sampling the policy drops.
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import re
import sys
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.store import cardio, db  # noqa: E402

TAIL_SECONDS = 600
SAMPLE_TYPES = {
    "HKQuantityTypeIdentifierHeartRate": ("heart_rate", "count/min", "bpm"),
    "HKQuantityTypeIdentifierCyclingPower": ("cycling_power", "W", "w"),
    "HKQuantityTypeIdentifierRunningPower": ("running_power", "W", "w"),
}
VO2MAX = "HKQuantityTypeIdentifierVO2Max"
EXPORT_MEMBER = "export.xml"


@dataclass
class WorkoutRow:
    activity: str
    started_at: str
    ended_at: str
    duration_s: int
    source_name: str
    source_bundle_id: str | None = None
    timezone: str | None = None
    avg_heart_rate: int | None = None
    max_heart_rate: int | None = None
    active_energy_kj: float | None = None
    distance_m: float | None = None
    avg_mets: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return cardio.content_key(
            activity_type=self.activity,
            started_at=self.started_at,
            ended_at=self.ended_at,
            duration_s=self.duration_s,
            source_bundle_id=self.source_bundle_id,
        )


def _stream(path: Path) -> Iterator[tuple[str, str, ET.Element]]:
    """Yield (phase, tag, element), streaming from a zip or a bare XML file.

    Both phases are needed: an element's children are already cleared by the time its own end
    event arrives, so workout children (statistics, metadata) must be read at their own end.
    """
    if path.is_dir():
        path = path / EXPORT_MEMBER
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            member = next(
                (name for name in archive.namelist() if name.endswith(EXPORT_MEMBER)), None
            )
            if member is None:
                raise SystemExit(f"no {EXPORT_MEMBER} inside {path}")
            with archive.open(member) as handle:
                yield from _iterparse(handle)
        return
    with path.open("rb") as handle:
        yield from _iterparse(handle)


def _iterparse(handle) -> Iterator[tuple[str, str, ET.Element]]:
    for phase, element in ET.iterparse(handle, events=("start", "end")):
        yield phase, element.tag, element
        if phase == "end":
            element.clear()


def _seconds(value: str | None, unit: str | None) -> int:
    number = float(value or 0)
    unit = (unit or "s").lower()
    if unit.startswith("min"):
        number *= 60
    elif unit.startswith("h"):
        number *= 3600
    return int(round(number))


def _metres(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    unit = (unit or "m").lower()
    factor = {"m": 1.0, "km": 1000.0, "mi": 1609.344, "yd": 0.9144}.get(unit, 1.0)
    return value * factor


def _kilojoules(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    unit = (unit or "kcal").lower()
    factor = {"kcal": 4.184, "cal": 0.004184, "kj": 1.0}.get(unit, 4.184)
    return value * factor


def _iso(text: str) -> str:
    return cardio.utc_iso(text, field="export timestamp")


def _first_number(text: str | None) -> float | None:
    match = re.match(r"\s*(-?[0-9.]+)", text or "")
    return float(match.group(1)) if match else None


def _collect_workouts(path: Path) -> tuple[list[WorkoutRow], int]:
    workouts: list[WorkoutRow] = []
    seen = 0
    current: WorkoutRow | None = None
    for phase, tag, element in _stream(path):
        if tag == "Workout" and phase == "start":
            seen += 1
            attrs = element.attrib
            current = _workout_row(attrs)
            workouts.append(current)
            continue
        if tag == "Workout" and phase == "end":
            current = None
            continue
        if current is None or phase != "end":
            continue
        if tag == "WorkoutStatistics":
            _apply_statistic(current, element.attrib)
        elif tag == "MetadataEntry":
            _apply_metadata(current, element.attrib)
    return workouts, seen


def _workout_row(attrs) -> WorkoutRow:
    return WorkoutRow(
        activity=attrs.get("workoutActivityType", "HKWorkoutActivityTypeOther"),
        started_at=_iso(attrs["startDate"]),
        ended_at=_iso(attrs["endDate"]),
        duration_s=max(_seconds(attrs.get("duration"), attrs.get("durationUnit")), 1),
        source_name=attrs.get("sourceName", "unknown"),
        source_bundle_id=attrs.get("sourceBundleIdentifier"),
    )


def _apply_statistic(row: WorkoutRow, stats) -> None:
    kind = stats.get("type", "")
    if kind.endswith("HeartRate"):
        row.avg_heart_rate = _int(stats.get("average"))
        row.max_heart_rate = _int(stats.get("maximum"))
    elif kind.endswith("ActiveEnergyBurned"):
        row.active_energy_kj = _kilojoules(_float(stats.get("sum")), stats.get("unit"))
    elif kind.startswith("HKQuantityTypeIdentifierDistance"):
        distance = _metres(_float(stats.get("sum")), stats.get("unit"))
        if distance is not None:
            row.distance_m = (row.distance_m or 0.0) + distance


def _apply_metadata(row: WorkoutRow, entry) -> None:
    key, value = entry.get("key", ""), entry.get("value", "")
    if key == "HKAverageMETs":
        row.avg_mets = _first_number(value)
    elif key == "HKTimeZone":
        row.timezone = value
    else:
        row.metadata[key] = value




def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    number = _float(value)
    return int(round(number)) if number is not None else None


class Index:
    """Interval lookup for workout containment and recovery tails."""

    def __init__(self, workouts: list[WorkoutRow]):
        self.workouts = workouts
        self.starts = [w.started_at for w in workouts]
        self.ends = sorted((w.ended_at, i) for i, w in enumerate(workouts))
        self.end_times = [end for end, _ in self.ends]

    def locate(self, at: str) -> tuple[int, str] | None:
        position = bisect.bisect_right(self.starts, at) - 1
        for index in range(position, max(position - 8, -1), -1):
            workout = self.workouts[index]
            if workout.started_at <= at < workout.ended_at:
                return index, "workout"
        tail = bisect.bisect_right(self.end_times, at) - 1
        if tail >= 0:
            end, index = self.ends[tail]
            if end <= at <= _plus(end, TAIL_SECONDS):
                return index, "tail"
        return None


def _plus(iso: str, seconds: int) -> str:
    parsed = dt.datetime.fromisoformat(iso)
    return (parsed + dt.timedelta(seconds=seconds)).isoformat()


def promote(
    *,
    export_path: Path,
    conn,
    dry_run: bool = False,
    link_after: bool = True,
    report: dict | None = None,
) -> dict:
    report = report if report is not None else {}
    workouts, seen = _collect_workouts(export_path)
    report["workouts_seen"] = seen
    report["workouts"] = len(workouts)
    if dry_run:
        return report

    imported_at = dt.datetime.now(dt.UTC).isoformat()
    created_workouts = 0
    workload_ids: list[str] = []
    with db.transaction(conn):
        for workout in workouts:
            row, created = cardio.record_workout(
                conn,
                external_key=workout.key,
                origin="export",
                activity_type=workout.activity,
                started_at=workout.started_at,
                ended_at=workout.ended_at,
                duration_s=workout.duration_s,
                source_name=workout.source_name,
                source_bundle_id=workout.source_bundle_id,
                timezone=workout.timezone,
                avg_heart_rate=workout.avg_heart_rate,
                max_heart_rate=workout.max_heart_rate,
                active_energy_kj=workout.active_energy_kj,
                distance_m=workout.distance_m,
                avg_mets=workout.avg_mets,
                metadata=workout.metadata,
                imported_at=imported_at,
            )
            workload_ids.append(row["external_workout_id"])
            created_workouts += int(created)
    report["workouts_created"] = created_workouts

    index = Index(workouts)
    samples = {kind: 0 for kind in ("workout", "tail")}
    vo2max = 0
    cutoff = ""
    created_samples = 0
    created_vo2max = 0

    with db.transaction(conn):
        for phase, tag, element in _stream(export_path):
            if tag != "Record" or phase != "end":
                continue
            attrs = element.attrib
            kind = attrs.get("type", "")
            if kind not in SAMPLE_TYPES and kind != VO2MAX:
                continue
            at = _iso(attrs["startDate"])
            cutoff = max(cutoff, at)
            if kind == VO2MAX:
                value = _float(attrs.get("value"))
                if value is None:
                    continue
                vo2max += 1
                created_vo2max += int(
                    cardio.record_vo2max(
                        conn,
                        # measurement.external_id is TEXT: hex here, unlike the corpus columns.
                        external_id=cardio.content_key(
                            activity_type=VO2MAX,
                            started_at=at,
                            ended_at=_iso(attrs.get("endDate", attrs["startDate"])),
                            duration_s=1,
                            source_bundle_id=attrs.get("sourceName"),
                        ).hex(),
                        measured_at=at,
                        value=value,
                        method=attrs.get("sourceName", "unknown"),
                        noted_at=imported_at,
                    )
                )
                continue
            sample_kind, unit, _ = SAMPLE_TYPES[kind]
            located = index.locate(at)
            if located is None:
                continue
            index_of_workout, association = located
            samples[association] += 1
            value = _float(attrs.get("value"))
            if value is None:
                continue
            created_samples += int(
                cardio.record_sample(
                    conn,
                    sample_key=cardio.sample_content_key(
                        kind=sample_kind,
                        sampled_at=at,
                        value=value,
                        unit=unit,
                        source_bundle_id=attrs.get("sourceName"),
                    ),
                    kind=sample_kind,
                    sampled_at=at,
                    value=value,
                    unit=unit,
                    source_name=attrs.get("sourceName", "unknown"),
                    imported_at=imported_at,
                    external_workout_id=workload_ids[index_of_workout],
                    association=association,
                )[1]
            )

    cardio.set_sync_state(
        conn,
        "history_cutoff",
        cutoff or imported_at,
        updated_at=imported_at,
    )
    if link_after:
        # Linking belongs to the end of an import, not to a separate chore: a promoted workout that
        # nobody links enriches nothing, and the pass is idempotent.
        from tools.cardio_link import evaluate, write_links

        candidates, deferred = evaluate(conn)
        report["links_written"] = write_links(conn, candidates)
        report["link_queue"] = len(deferred)
    report.update(
        {
            "samples_workout": samples["workout"],
            "samples_tail": samples["tail"],
            "samples_created": created_samples,
            "vo2max_seen": vo2max,
            "vo2max_created": created_vo2max,
            "history_cutoff": cutoff,
        }
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="target database path (required)")
    parser.add_argument("--export", required=True, help="export.xml or the .zip it lives in")
    parser.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    args = parser.parse_args(argv)

    export_path = Path(args.export).expanduser()
    if not export_path.exists():
        print(f"export not found: {export_path}", file=sys.stderr)
        return 2

    conn = db.connect(args.db)
    try:
        db.migrate(conn)
        report = promote(export_path=export_path, conn=conn, dry_run=args.dry_run)
    finally:
        conn.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
