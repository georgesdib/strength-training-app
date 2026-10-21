"""Readiness merge: several rows per date -> one defensible row.

The export contains multiple readiness rows for some dates, and most of them *conflict*
rather than repeat (OPEN-QUESTIONS Q6). The documented default is:

    most-complete row wins; ties go to the latest row in the file.

"Most complete" means the row that actually measured the most fields. It is an assumption
that completeness equals authority -- recorded as ASSUMPTION-04, not a claim. The decision is
reversible because `merge_note` keeps every candidate and the reason it lost.

The composite is deliberately left empty: it needs declared metric directions (Q6 part 2),
and inventing a 0-1 score would make a guess indistinguishable from a measurement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from strength_coach.utils import dates, numeric

# Raw column -> canonical column. The raw export is the only place these names appear.
RAW_RENAME = {
    "Sleep": "sleep",
    "Energy": "energy",
    "Mood": "mood",
    "Soreness": "soreness",
    "Stress": "stress",
    "Nutrition": "nutrition",
    "Hydration": "hydration",
    "Squat_Readiness": "squat_readiness",
    "Bench_Readiness": "bench_readiness",
    "Deadlift_Readiness": "deadlift_readiness",
    "HRV": "hrv_ms",
    "RHR": "rhr_bpm",
    "Weight": "bodyweight_kg",
    "Fat_Percent": "fat_pct",
    # Optional third-party readiness score. Aliases cover the common export headers.
    "Wearable_Score": "wearable_score",
    "Wearable Score": "wearable_score",
    "Readiness_Score": "wearable_score",
    "Readiness Score": "wearable_score",
    "Bevel_Readiness": "wearable_score",
    "Bevel Readiness": "wearable_score",
}

# Columns where a physical 0 is impossible, so 0 is a missing-value sentinel. These are the
# RAW names, because `apply_zero_sentinels` is keyed by the export's own vocabulary.
SENTINEL_COLUMNS = [
    "HRV", "RHR", "Weight", "Fat_Percent",
    "Squat_Readiness", "Bench_Readiness", "Deadlift_Readiness", "Grip_Strength",
]

FIELDS = tuple(RAW_RENAME.values())


@dataclass(frozen=True)
class ReadinessResult:
    days: pd.DataFrame
    duplicate_rows: int = 0
    conflicting_dates: int = 0
    notes: dict[str, dict] = field(default_factory=dict)


def build_readiness_day(readiness: pd.DataFrame) -> ReadinessResult:
    """Merge duplicate readiness rows into one row per date, with provenance."""
    if readiness.empty:
        return ReadinessResult(days=_empty_frame())

    frame = readiness.copy()
    frame["source_row"] = range(1, len(frame) + 1)
    frame["date"] = dates.parse_dates(frame["Date"])
    frame = numeric.coerce_frame(frame, [c for c in SENTINEL_COLUMNS if c in frame.columns])
    frame = numeric.apply_zero_sentinels(frame) if set(SENTINEL_COLUMNS) & set(frame.columns) else frame
    # 1-5 scales have no zero bucket and no sentinel; the remaining columns were coerced above.
    frame = numeric.coerce_frame(
        frame, [c for c in RAW_RENAME if c not in SENTINEL_COLUMNS and c in frame.columns]
    )
    frame = frame.dropna(subset=["date"])
    frame = frame.rename(columns=RAW_RENAME)

    present = [c for c in FIELDS if c in frame.columns]
    frame["completeness"] = frame[present].notna().sum(axis=1)

    rows: list[dict] = []
    notes: dict[str, dict] = {}
    duplicate_rows = 0
    conflicting_dates = 0

    for date, group in frame.groupby("date", sort=True):
        key = pd.Timestamp(date).date().isoformat()
        if len(group) > 1:
            duplicate_rows += len(group) - 1
            distinct = group[present].drop_duplicates()
            if len(distinct) > 1:
                conflicting_dates += 1
        best = group["completeness"].max()
        candidates = group[group["completeness"] == best]
        # Tie-break on source order: the later row is the athlete's most recent word for that
        # day, which is the only ordering the file gives us (there are no timestamps).
        chosen = candidates.sort_values("source_row").iloc[-1]
        reason = "most_complete" if len(candidates) == 1 else "latest_tie"
        rows.append(
            {
                "on_date": key,
                **{name: chosen.get(name) for name in present},
                "composite": None,
                "composite_basis": None,
                "source_row": int(chosen["source_row"]),
            }
        )
        notes[key] = {
            "considered": int(len(group)),
            "chosen_source_row": int(chosen["source_row"]),
            "complete_fields": int(best),
            "reason": reason,
        }

    out = pd.DataFrame(rows)
    out["merge_note"] = [json.dumps(notes[key], sort_keys=True) for key in out["on_date"]]
    return ReadinessResult(
        days=out,
        duplicate_rows=duplicate_rows,
        conflicting_dates=conflicting_dates,
        notes=notes,
    )


def _empty_frame() -> pd.DataFrame:
    columns = ["on_date", *FIELDS, "composite", "composite_basis", "source_row", "merge_note"]
    return pd.DataFrame(columns=columns)
