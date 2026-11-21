"""Derived actual structure: a descriptive segmentation of a recorded sequence.

This layer never rewrites a raw set, the working-set flag, working volume, e1RM or fatigue, and
it is never an evaluator input (DEC-RESOLVER-20). It describes what the sequence looks like:
preparatory work, a top-set-like exposure, back-offs, straight sets, multiple heavy exposures, or
insufficient evidence. Thresholds are versioned config (config/derived-structure.v1.yaml).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from strength_coach.domain import load as load_mod
from strength_coach.features import set_matching
from strength_coach.utils import paths, yaml_files

CONFIG_NAME = "derived-structure.v1.yaml"


@dataclass(frozen=True)
class StructureConfig:
    version: int = 1
    load_tolerance_increments: int = 1
    rir_tolerance: int = 1
    min_load_gap_increments: int = 2
    min_back_off_sets: int = 2

    @classmethod
    def load(cls, path: str | None = None) -> StructureConfig:
        source = path or paths.config_dir(CONFIG_NAME)
        raw = yaml_files.load_yaml_file(source) or {}
        top = raw.get("top_set") or {}
        return cls(
            version=max(1, int(raw.get("version", 1))),
            load_tolerance_increments=max(
                1, int(raw.get("load_tolerance_increments", 1))
            ),
            rir_tolerance=max(0, int(raw.get("rir_tolerance", 1))),
            min_load_gap_increments=max(
                1, int(top.get("min_load_gap_increments", 2))
            ),
            min_back_off_sets=max(1, int(top.get("min_back_off_sets", 2))),
        )


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ordered(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            _integer(row.get("set_index")) or 0,
            _integer(row.get("set_id")) or 0,
        ),
    )


def _increment(item: Mapping[str, Any] | None, loads: Sequence[float | None]) -> float:
    value = _number((item or {}).get("rounding_increment_kg"))
    if value is not None and value > 0:
        return value
    fallback = next((load for load in loads if load is not None), 0.0)
    return float(load_mod.default_increment_kg(fallback))


def _load_shape(loads: Sequence[float | None], tolerance: float) -> str:
    values = [load for load in loads if load is not None]
    if len(values) < 2:
        return "insufficient_data"
    diffs = [values[index + 1] - values[index] for index in range(len(values) - 1)]
    if all(abs(diff) <= tolerance for diff in diffs):
        return "constant"
    if all(diff > tolerance for diff in diffs):
        return "ascending"
    if all(diff < -tolerance for diff in diffs):
        return "descending"
    if all(diff <= tolerance for diff in diffs):
        return "descending"
    if all(diff >= -tolerance for diff in diffs):
        return "ascending"
    signs = [1 if diff > tolerance else -1 if diff < -tolerance else 0 for diff in diffs]
    compressed = [sign for sign in signs if sign != 0]
    if compressed == [1, -1]:
        return "ascending_then_descending"
    return "irregular"


def _confidence(working: Sequence[Mapping[str, Any]]) -> tuple[str, list[str]]:
    limitations: list[str] = []
    if any(_number(row.get("load_kg")) is None for row in working):
        limitations.append("missing_load")
    if any(_integer(row.get("rir")) is None for row in working):
        limitations.append("missing_rir")
    if any(_integer(row.get("reps")) is None for row in working):
        limitations.append("missing_reps")
    if "missing_load" in limitations:
        return "unknown", limitations
    if "missing_rir" in limitations and "missing_reps" in limitations:
        return "low", limitations
    if limitations:
        return "medium", limitations
    return "high", limitations


def derive(
    rows: Sequence[Mapping[str, Any]],
    *,
    item: Mapping[str, Any] | None = None,
    config: StructureConfig | None = None,
) -> dict[str, Any]:
    """Describe one exercise's recorded sequence. Never mutates a row."""
    cfg = config or StructureConfig.load()
    ordered = _ordered(rows)
    warm_ups = set_matching.warm_up_sets(ordered)
    working = set_matching.working_sets(ordered)
    loads = [_number(row.get("load_kg")) for row in working]
    increment = _increment(item, loads)
    tolerance = increment * cfg.load_tolerance_increments
    limitations: list[str] = []
    confidence, confidence_limitations = _confidence(working)
    limitations.extend(confidence_limitations)
    if not working:
        limitations.append("no_working_sets")

    segments: list[dict[str, Any]] = []
    if warm_ups:
        segments.append({
            "kind": "preparatory_progression",
            "set_indexes": [_integer(row.get("set_index")) for row in warm_ups],
            "confidence": "high" if all(
                _integer(row.get("rir")) == set_matching.WARM_UP_RIR for row in warm_ups
            ) else "medium",
            "evidence": {"rir": [_integer(row.get("rir")) for row in warm_ups]},
        })

    structure = "insufficient_data"
    if not working:
        structure = "insufficient_data"
        confidence = "unknown"
    elif any(load is None for load in loads):
        structure = "ambiguous"
        confidence = "unknown"
        limitations.append("structure_needs_load")
    else:
        numbers = [load for load in loads if load is not None]
        first = numbers[0]
        rest = numbers[1:]
        min_gap = cfg.min_load_gap_increments * increment
        rest_lower = bool(rest) and max(rest) <= first - min_gap
        enough_back_off = len(rest) >= cfg.min_back_off_sets
        first_rir = _integer(working[0].get("rir"))
        rest_rirs = [_integer(row.get("rir")) for row in working[1:]]
        rir_drop = (
            bool(rest_rirs)
            and first_rir is not None
            and all(rir is not None for rir in rest_rirs)
            and first_rir <= min(rir for rir in rest_rirs if rir is not None) - 1
        )
        first_reps = _integer(working[0].get("reps"))
        rest_reps = [_integer(row.get("reps")) for row in working[1:]]
        reps_not_higher = (
            first_reps is None
            or all(reps is None or first_reps <= reps for reps in rest_reps)
        )
        if rest_lower and enough_back_off and reps_not_higher:
            structure = "top_set_like_plus_back_off"
            segments.append({
                "kind": "top_set_like_effort",
                "set_indexes": [_integer(working[0].get("set_index"))],
                "confidence": "high" if rir_drop and not confidence_limitations else "medium",
                "evidence": {
                    "load_kg": first,
                    "rir": first_rir,
                    "reps": first_reps,
                    "gap_kg": round(first - max(rest), 2),
                    "gap_increments": round((first - max(rest)) / increment, 1),
                },
            })
            segments.append({
                "kind": "back_off_sequence",
                "set_indexes": [
                    _integer(row.get("set_index")) for row in working[1:]
                ],
                "confidence": "high" if rir_drop else "medium",
                "evidence": {
                    "load_kg": rest,
                    "rir": rest_rirs,
                    "reps": rest_reps,
                },
            })
            if not rir_drop:
                limitations.append("top_set_load_only")
        elif all(abs(load - numbers[0]) <= tolerance for load in numbers):
            structure = "straight_working_sets"
            segments.append({
                "kind": "straight_working_sets",
                "set_indexes": [_integer(row.get("set_index")) for row in working],
                "confidence": confidence,
                "evidence": {"load_kg": numbers},
            })
        else:
            peaks = [
                index for index, load in enumerate(numbers)
                if (index == 0 or load > numbers[index - 1] + tolerance)
                and (index == len(numbers) - 1 or load > numbers[index + 1] + tolerance)
            ]
            if len(peaks) >= 2:
                structure = "multiple_heavy_exposures"
                segments.append({
                    "kind": "multiple_heavy_exposures",
                    "set_indexes": [
                        _integer(working[index].get("set_index")) for index in peaks
                    ],
                    "confidence": confidence,
                    "evidence": {"load_kg": [numbers[index] for index in peaks]},
                })
            elif len(numbers) == 1:
                structure = "heavy_working_exposure"
                segments.append({
                    "kind": "heavy_working_exposure",
                    "set_indexes": [_integer(working[0].get("set_index"))],
                    "confidence": confidence,
                    "evidence": {"load_kg": numbers[0]},
                })
            else:
                structure = "ambiguous"
                confidence = "medium" if confidence in ("high", "medium") else confidence
                limitations.append("structure_evidence_ambiguous")

    shape = _load_shape(loads, tolerance)
    if shape == "insufficient_data" and working:
        limitations.append("load_shape_insufficient")
    return {
        "structure": structure,
        "confidence": confidence,
        "load_shape": shape,
        "segments": segments,
        "working_sets": len(working),
        "warm_up_sets": len(warm_ups),
        "increment_kg": increment,
        "config_version": cfg.version,
        "limitations": sorted(set(limitations)),
    }

