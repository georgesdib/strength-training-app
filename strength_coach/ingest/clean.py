"""Ingestion: raw export rows -> clean, flagged, traceable sets.

Layering: below `features`. May import `utils` and `domain` only. Derived metrics (e1RM,
velocity trends) belong to `features.derived`.

Nothing here judges programme compliance. Every row either becomes a clean set, gets an
explicit flag, or is quarantined with a reason — nothing is dropped silently.

Column names are canonicalised *first*, so every helper below speaks one vocabulary and the
raw export's mixed naming (`Weight_Used`, `Reps_Done`, `RIR`, ...) appears exactly once, in
`RAW_RENAME`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from strength_coach.domain import load as load_mod
from strength_coach.domain import rir as rir_mod
from strength_coach.utils import dates, exercises, numeric

# The single place raw export names are mapped to the domain vocabulary.
RAW_RENAME = {
    "Exercise": "raw_exercise",
    "Workout": "workout_label",
    "Weight_Used": "load_kg",
    "Reps_Done": "reps",
    "RIR": "rir",
    "Avg_velocity": "velocity_mps",
    "Avg_rom": "rom_mm",
    "TUT": "tut_s",
    "Form": "form_score",
}
NUMERIC_COLUMNS = ["load_kg", "reps", "rir", "velocity_mps", "rom_mm", "tut_s", "form_score"]

FLAG_WARMUP = "WARMUP"
FLAG_REPS_TYPO = "REPS_TYPO"
FLAG_SECONDS = "SECONDS_NOT_REPS"
FLAG_LOAD_UNKNOWN = "LOAD_BASIS_UNKNOWN"
FLAG_NO_RIR = "NO_RIR"
FLAG_SUSPECT_RIR = "SUSPECT_RIR"

# A rep count above this is not a set. The reference export contains a four-digit rep count
# on a push-up variant and a 70-rep bench set at a heavy load, both clearly keying errors.
REPS_IMPLAUSIBLE = 50
REPS_IMPLAUSIBLE_BODYWEIGHT = 200

Q_NULL_DATE = "null_date"
Q_UNKNOWN_EXERCISE = "unknown_exercise"


@dataclass
class CleanResult:
    """Clean sets plus what was set aside, and why."""

    sets: pd.DataFrame
    quarantine: pd.DataFrame
    issues: dict[str, int] = field(default_factory=dict)

    @property
    def n_sets(self) -> int:
        return len(self.sets)

    @property
    def n_quarantined(self) -> int:
        return len(self.quarantine)


def attach_bodyweight(
    frame: pd.DataFrame,
    readiness: pd.DataFrame,
    *,
    tolerance_days: int = 7,
) -> pd.DataFrame:
    """Nearest bodyweight within a tolerance window, via an as-of join.

    Bodyweight is required to disambiguate bodyweight-style loads (DQ-BW-01). A nearest join
    within +/-7 days is used because weighing is sporadic but body mass is stable across a
    week; outside the tolerance the load basis becomes `unknown` rather than a guess.
    """
    ready = readiness.copy()
    ready["date"] = dates.parse_dates(ready["Date"])
    weight = numeric.coerce_numeric(ready["Weight"])
    # DQ-SENT-02: a recorded bodyweight of 0 is a missing-value sentinel, and letting it
    # through would turn every bodyweight ratio into infinity and silently break DQ-BW-01.
    weight = weight.where(weight > 0)
    body = pd.DataFrame({"date": ready["date"], "bodyweight_kg": weight})
    body = body.dropna().drop_duplicates("date", keep="last").sort_values("date")

    if frame.empty:
        # An all-quarantined export must still survive: pandas refuses to as-of join an empty
        # datetime64[s] key against a datetime64[us] one, and there is nothing to attach.
        out = frame.copy()
        out["bodyweight_kg"] = pd.Series(dtype="float64")
        return out

    left = frame.sort_values("date")
    merged = pd.merge_asof(
        left, body, on="date", direction="nearest",
        tolerance=pd.Timedelta(days=tolerance_days),
    )
    return merged.sort_index()


def build_clean_sets(
    training: pd.DataFrame,
    readiness: pd.DataFrame,
    *,
    bodyweight_tolerance_days: int = 7,
) -> CleanResult:
    """The one entry point: raw training log + readiness -> clean sets + quarantine."""
    frame = training.rename(columns=RAW_RENAME).copy()
    frame["source_row"] = range(1, len(frame) + 1)
    frame["date"] = dates.parse_dates(frame["Date"])
    frame = numeric.coerce_frame(frame, NUMERIC_COLUMNS)

    taxonomy = exercises.taxonomy()
    frame["exercise_id"] = frame["raw_exercise"].map(exercises.canonical_id)

    quarantined = frame[frame["date"].isna() | frame["exercise_id"].isna()].copy()
    quarantined["quarantine_reason"] = [
        Q_NULL_DATE if pd.isna(d) else Q_UNKNOWN_EXERCISE for d in quarantined["date"]
    ]
    frame = frame.drop(index=quarantined.index).copy()

    frame = attach_bodyweight(frame, readiness, tolerance_days=bodyweight_tolerance_days)

    props = {
        exercise_id: dict(taxonomy.entities.get(exercise_id, {}))
        for exercise_id in frame["exercise_id"].unique()
    }
    frame = _resolve_loads(frame, props)
    frame = _resolve_reps_unit(frame, props)
    frame = _resolve_rir(frame)
    frame = _flag_rows(frame, props)
    frame = _resolve_tonnage(frame)
    # DQ-SENT-01: 0.000000 means "device unused", so presence requires a positive reading.
    frame["velocity_present"] = numeric.positive_measurement_present(frame["velocity_mps"])

    issues = {
        "rows_total": int(len(training)),
        "rows_quarantined": int(len(quarantined)),
        "rows_clean": int(len(frame)),
        "working_sets": int(frame["is_working_set"].sum()),
        "warmup_sets": int((~frame["is_working_set"]).sum()),
        "load_basis_unknown": int((frame["load_basis"] == "unknown").sum()),
        "reps_typos": int(_has_flag(frame, FLAG_REPS_TYPO).sum()),
        "suspect_rir": int(frame["suspect_rir"].sum()),
    }

    keep = [
        "source_row", "date", "exercise_id", "raw_exercise", "workout_label",
        "load_kg", "load_basis", "external_load_kg", "total_load_kg", "progression_load_kg",
        "reps", "reps_unit", "rir", "rir_class", "rir_source", "suspect_rir",
        "velocity_mps", "velocity_present", "rom_mm", "tut_s", "form_score",
        "is_working_set", "tonnage_kg", "flags",
    ]
    # reindex rather than select: a partial export (or a synthetic fixture) must not raise,
    # it should simply carry nulls for the columns it omitted.
    return CleanResult(
        sets=frame.reindex(columns=keep).copy(), quarantine=quarantined, issues=issues
    )


def _resolve_loads(frame: pd.DataFrame, props: dict[str, dict]) -> pd.DataFrame:
    """Apply DQ-BW-01 + DEC-LOAD-02 per row."""
    basis: list[str] = []
    external: list[float | None] = []
    total: list[float | None] = []
    progression: list[float | None] = []

    for weight, bodyweight, exercise_id in zip(
        frame["load_kg"], frame["bodyweight_kg"], frame["exercise_id"], strict=True
    ):
        entity = props.get(exercise_id, {})
        is_bw = bool(entity.get("bodyweight_type", False))
        is_time = bool(entity.get("time_based", False))
        resolved = load_mod.resolve_load_basis(
            None if pd.isna(weight) else float(weight),
            bodyweight_kg=None if pd.isna(bodyweight) else float(bodyweight),
            is_bodyweight_type=is_bw,
            is_time_based=is_time,
        )
        basis.append(resolved.basis)
        external.append(resolved.external_load_kg)
        total.append(resolved.total_load_kg)
        progression.append(load_mod.progression_load(resolved, is_bodyweight_type=is_bw))

    frame["load_basis"] = basis
    frame["external_load_kg"] = pd.Series(external, index=frame.index, dtype="float64")
    frame["total_load_kg"] = pd.Series(total, index=frame.index, dtype="float64")
    frame["progression_load_kg"] = pd.Series(progression, index=frame.index, dtype="float64")
    return frame


def _resolve_reps_unit(frame: pd.DataFrame, props: dict[str, dict]) -> pd.DataFrame:
    """Seconds vs reps, from the taxonomy (DQ-REPS-01)."""
    frame["reps_unit"] = frame["exercise_id"].map(
        lambda e: str(props.get(e, {}).get("rep_semantics", "reps"))
    )
    return frame


def _resolve_rir(frame: pd.DataFrame) -> pd.DataFrame:
    """Classify RIR through domain.rir so warm-up handling has one implementation."""
    readings = frame["rir"].map(rir_mod.classify)
    frame["rir"] = readings.map(lambda r: r.value)
    frame["rir_class"] = readings.map(lambda r: r.klass)
    frame["rir_source"] = readings.map(lambda r: r.source)
    frame["suspect_rir"] = readings.map(lambda r: bool(r.suspect))
    # DEC-RIR-01: a warm-up marker makes the set a warm-up, not working volume.
    frame["is_working_set"] = readings.map(lambda r: r.klass != "warmup")
    return frame


def _flag_rows(frame: pd.DataFrame, props: dict[str, dict]) -> pd.DataFrame:
    """Attach a ';'-joined flag string per row. Flags inform; they never delete."""
    flags: list[str] = []
    for reps, rir_class, suspect, basis, unit, exercise_id, working in zip(
        frame["reps"], frame["rir_class"], frame["suspect_rir"], frame["load_basis"],
        frame["reps_unit"], frame["exercise_id"], frame["is_working_set"], strict=True,
    ):
        row_flags: list[str] = []
        if not working:
            row_flags.append(FLAG_WARMUP)
        if rir_class == "missing":
            row_flags.append(FLAG_NO_RIR)
        if suspect:
            row_flags.append(FLAG_SUSPECT_RIR)
        if basis == "unknown":
            row_flags.append(FLAG_LOAD_UNKNOWN)
        if unit == "seconds":
            row_flags.append(FLAG_SECONDS)
        elif reps is not None and not pd.isna(reps):
            is_bw = bool(props.get(exercise_id, {}).get("bodyweight_type", False))
            cap = REPS_IMPLAUSIBLE_BODYWEIGHT if is_bw else REPS_IMPLAUSIBLE
            if reps > cap:
                row_flags.append(FLAG_REPS_TYPO)
        flags.append(";".join(row_flags))
    # Explicit string dtype: an all-quarantined frame is empty and would otherwise give the
    # column a float dtype, making `.str` accessors explode downstream.
    frame["flags"] = pd.Series(flags, index=frame.index, dtype="string")
    return frame


def _has_flag(frame: pd.DataFrame, flag: str) -> pd.Series:
    """Safe flag lookup that works on an empty frame."""
    if frame.empty:
        return pd.Series(False, index=frame.index, dtype=bool)
    return frame["flags"].astype("string").str.contains(flag, na=False).fillna(False)


def _resolve_tonnage(frame: pd.DataFrame) -> pd.DataFrame:
    """Tonnage = added load x reps, and only where both are defined.

    Undefined for: isometric holds (seconds), unresolved load basis, and flagged rep typos.
    Bodyweight mass is excluded so week-on-week comparability survives DEC-LOAD-02.
    """
    frame["tonnage_kg"] = frame["external_load_kg"] * frame["reps"]
    undefined = (
        (frame["reps_unit"] != "reps")
        | (frame["load_basis"] == "unknown")
        | _has_flag(frame, FLAG_REPS_TYPO)
    )
    frame.loc[undefined, "tonnage_kg"] = pd.NA
    return frame
