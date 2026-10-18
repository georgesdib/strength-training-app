"""The one way a raw export becomes persisted state.

`import_export` is deliberately the only orchestration point: it cleans, reconstructs
sessions, and writes every artifact inside a single run trace. The acceptance criterion for
phase 3 lives here -- importing the same export twice writes no second copy of anything,
while two genuinely repeated sets stay two rows.

Readiness is imported as `raw_row` only. Materialising `readiness_day` requires the
duplicate-row merge rule (DQ-RD-01), which is still an open question (Q6), and inventing an
answer here would bake a guess into storage.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import pandas as pd

from strength_coach import __version__
from strength_coach.ingest import clean, readiness as readiness_mod, sessions as sessions_mod
from strength_coach.store import repositories as repo
from strength_coach.utils import paths


@dataclass(frozen=True)
class ImportReport:
    """What an import wrote, and what it deliberately did not write again."""

    run_id: str
    raw_rows_inserted: int
    clean_sets_inserted: int
    clean_sets_existing: int
    sessions_written: int
    quarantined: int
    readiness_days: int = 0
    issues: dict[str, int] = field(default_factory=dict)
    window_start: str | None = None
    window_end: str | None = None

    @property
    def wrote_anything(self) -> bool:
        return self.raw_rows_inserted > 0 or self.clean_sets_inserted > 0


def sha256_file(path: str | Path) -> str:
    """Content hash of a source file, so an import is traceable to exact bytes."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_frame(frame: pd.DataFrame) -> str:
    """Stable hash of an in-memory frame (used by tests and by callers holding a frame)."""
    digest = hashlib.sha256()
    digest.update("|".join(map(str, frame.columns)).encode("utf-8"))
    digest.update(frame.to_csv(index=False).encode("utf-8"))
    return digest.hexdigest()


def config_hash() -> str:
    """Hash of the config files the pipeline reads, so a run names the rules it ran under."""
    digest = hashlib.sha256()
    for path in (
        paths.taxonomy_yaml(),
        paths.config_dir("templates", "days.v1.yaml"),
        paths.programme_rules_yaml(),
        # Prescription thresholds change prescribed loads, so a run must name the version
        # they were under, not just the rules version.
        paths.thresholds_yaml(),
    ):
        if Path(path).exists():
            digest.update(Path(path).read_bytes())
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def import_export(
    conn,
    training: pd.DataFrame,
    readiness: pd.DataFrame,
    *,
    training_sha256: str,
    readiness_sha256: str,
    config_hash_value: str | None = None,
    run_id: str | None = None,
) -> ImportReport:
    """Clean a raw export pair and persist it; idempotent in content."""
    input_hash = hashlib.sha256(
        f"{training_sha256}:{readiness_sha256}".encode("utf-8")
    ).hexdigest()

    run = repo.start_run(
        conn,
        input_hash=input_hash,
        code_version=__version__,
        config_hash=config_hash_value if config_hash_value is not None else config_hash(),
        run_id=run_id,
    )

    try:
        training_raw, training_inserted = repo.store_raw_rows(
            conn, training, table_name="training", file_sha256=training_sha256
        )
        readiness_raw, readiness_inserted = repo.store_raw_rows(
            conn, readiness, table_name="readiness", file_sha256=readiness_sha256
        )

        result = clean.build_clean_sets(training, readiness)
        reconstructed = sessions_mod.build_sessions(result.sets)

        # Sessions first: clean_set.session_id is a foreign key into session.
        repo.upsert_sessions(conn, reconstructed)
        inserted, existing = repo.store_clean_sets(conn, result.sets, raw_ids=training_raw)
        quarantined = repo.store_quarantine(conn, result.quarantine, raw_ids=training_raw)

        # Readiness is merged here because the prescription engine needs one row per date for
        # MOD-FAT-001; the merge rule is the documented Q6 default (DEC-READINESS-01).
        readiness_result = readiness_mod.build_readiness_day(readiness)
        readiness_days = repo.upsert_readiness_days(conn, readiness_result.days)

        dates = result.sets["date"].dropna() if "date" in result.sets else pd.Series(dtype="object")
        window_start = pd.Timestamp(dates.min()).date().isoformat() if len(dates) else None
        window_end = pd.Timestamp(dates.max()).date().isoformat() if len(dates) else None

        repo.log_event(
            conn,
            run.run_id,
            "input",
            {
                "training_sha256": training_sha256,
                "readiness_sha256": readiness_sha256,
                "training_rows": int(len(training)),
                "readiness_rows": int(len(readiness)),
            },
        )
        repo.log_event(
            conn,
            run.run_id,
            "artifact",
            {
                "raw_rows_inserted": training_inserted + readiness_inserted,
                "clean_sets_inserted": inserted,
                "clean_sets_existing": existing,
                "sessions_written": len(reconstructed),
                "quarantined": quarantined,
                "readiness_days": readiness_days,
            },
        )
        repo.finish_run(conn, run.run_id, status="ok")

        return ImportReport(
            run_id=run.run_id,
            raw_rows_inserted=training_inserted + readiness_inserted,
            clean_sets_inserted=inserted,
            clean_sets_existing=existing,
            sessions_written=len(reconstructed),
            quarantined=quarantined,
            readiness_days=readiness_days,
            issues=dict(result.issues),
            window_start=window_start,
            window_end=window_end,
        )
    except Exception:
        # The trace must record a failed attempt; swallowing this would leave a run that
        # looks successful with half its artifacts written.
        repo.finish_run(conn, run.run_id, status="error")
        raise
