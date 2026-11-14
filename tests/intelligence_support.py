"""Synthetic builders shared by the intelligence tests.

No real training data, no personal values: every row here is invented.
"""

from __future__ import annotations

import datetime as dt

from conftest import make_readiness, make_training

from strength_coach.features.evidence import EvidenceItem, make_source_fingerprint
from strength_coach.intelligence import (
    Envelope,
    FactBlock,
    IntelligenceConfig,
    IntelligenceService,
    Period,
    Privacy,
    Provenance,
)
from strength_coach.store import db, importer

FIXED_DAY = dt.date(2026, 11, 14)
FIXED_NOW = dt.datetime(2026, 11, 14, 9, 0, tzinfo=dt.UTC)
ZERO_HASH = "sha256:" + "0" * 64


class FixedClock:
    def __init__(self, *, day: dt.date = FIXED_DAY, now: dt.datetime = FIXED_NOW) -> None:
        self._day = day
        self._now = now

    def today(self) -> dt.date:
        return self._day

    def now_utc(self) -> dt.datetime:
        return self._now


def enabled_config(**overrides: object) -> IntelligenceConfig:
    values: dict[str, object] = {"enabled": True}
    values.update(overrides)
    return IntelligenceConfig(**values)  # type: ignore[arg-type]


def sample_rows() -> list[dict[str, object]]:
    return [
        {"Date": "2026-10-19", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2026-10-26", "Exercise": "Trap Bar Deadlift", "Weight_Used": "155",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2026-11-02", "Exercise": "Trap Bar Deadlift", "Weight_Used": "160",
         "RIR": "2", "Reps_Done": "5"},
    ]


def seed_store(
    rows: list[dict[str, object]] | None = None,
    readiness_rows: list[dict[str, object]] | None = None,
) -> db.Store:
    training = make_training(sample_rows() if rows is None else rows)
    readiness = make_readiness(
        [{"Date": "2026-10-26", "Sleep": "4", "Soreness": "2", "Stress": "2"}]
        if readiness_rows is None
        else readiness_rows
    )
    store = db.Store(":memory:")
    importer.import_export(
        store.connection,
        training,
        readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def service(conn, config: IntelligenceConfig | None = None, **kwargs: object) -> IntelligenceService:
    return IntelligenceService(
        conn,
        config=config if config is not None else enabled_config(),
        clock=FixedClock(),
        **kwargs,  # type: ignore[arg-type]
    )


def evidence_item(value: object = 1) -> dict[str, object]:
    return EvidenceItem(
        source="test.attendance",
        source_ids=("session-1",),
        window_start="2026-11-08",
        window_end="2026-11-14",
        value=value,
        source_fingerprint=make_source_fingerprint([{"session_id": "session-1"}]),
        unit=None,
        n=1,
        gate="signal",
        comparability="comparable",
    ).as_dict()


def envelope(**overrides: object) -> Envelope:
    item = evidence_item()
    fact = FactBlock(
        value={"completed": 1},
        basis="derived",
        method="strength_coach.features.attendance.summary",
        n=1,
        evidence_ids=(str(item["evidence_id"]),),
    )
    base: dict[str, object] = {
        "capability": "get_training_overview",
        "version": "1.0.0",
        "status": "ok",
        "as_of": "2026-11-14",
        "period": Period(
            start="2026-11-08", end="2026-11-14", days=7, weeks=1, timezone="Europe/London"
        ),
        "units": {"load": "kg"},
        "facts": {"attendance": fact},
        "evidence": (item,),
        "observations": (),
        "coverage": {"sessions": 1},
        "missing": (),
        "limitations": ("synthetic",),
        "quality_flags": (),
        "privacy": Privacy(classification="training"),
        "provenance": Provenance(
            services=(("strength_coach.features.attendance", "1.4.1"),),
            config_revision=ZERO_HASH,
            database_revision=1,
            builder_version="context.v1",
            context_hash=ZERO_HASH,
        ),
        "generated_at": "2026-11-14T09:00:00Z",
    }
    base.update(overrides)
    return Envelope(**base)  # type: ignore[arg-type]
