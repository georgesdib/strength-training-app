"""Golden equivalence for the readiness metric registry refactor (WP3).

The fixture is captured from the pre-registry engine (WRITE_READINESS_GOLDEN=1) and then
compared after the engine reads the registry. The seeded registry must reproduce the old
assessment exactly: status, score, components (field, value, normalised, weight), basis,
overrides, category scores/factors, context flags and suppression.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from strength_coach.features import readiness as readiness_config
from strength_coach.features import readiness_score
from strength_coach.store import db, repositories

GOLDEN = Path(__file__).parent / "fixtures" / "readiness_equivalence.json"
BASELINE = [f"2026-01-{day:02d}" for day in range(1, 8)]


def _conn() -> object:
    conn = db.connect(":memory:")
    db.migrate(conn)
    return conn


def _day(conn, on_date: str, **values) -> None:
    fields = ["on_date", *values]
    placeholders = ", ".join("?" for _ in fields)
    conn.execute(
        f"INSERT INTO readiness_day ({', '.join(fields)}) VALUES ({placeholders})",
        (on_date, *values.values()),
    )


def _core(conn, on_date: str = "2026-01-10", **overrides) -> None:
    values = {"sleep": 4, "energy": 3, "mood": 5, "stress": 2, "soreness": 4}
    values.update(overrides)
    _day(conn, on_date, **{key: value for key, value in values.items() if value is not None})


def _device_history(conn, days=BASELINE) -> None:
    for index, day in enumerate(days):
        _day(conn, day, sleep=4, energy=4, mood=4, stress=4, soreness=4,
             hrv_ms=60 + index, rhr_bpm=60 - index)


def _scenarios() -> list[tuple[str, object]]:
    scenarios: list[tuple[str, object]] = []

    def scenario(name, build, date="2026-01-10", **compute_kwargs):
        scenarios.append((name, (build, date, compute_kwargs)))

    scenario("core_all", lambda c: _core(c))
    for missing in ("sleep", "energy", "mood", "stress", "soreness"):
        scenario(
            f"core_missing_{missing}",
            lambda c, missing=missing: _core(c, **{missing: None}),
        )
    scenario(
        "insufficient_no_sleep_or_energy",
        lambda c: _core(c, sleep=None, energy=None),
    )
    scenario("insufficient_two_fields", lambda c: _core(c, mood=None, stress=None, soreness=None))
    scenario("unknown_no_entry", lambda c: None, date="2026-02-01")

    def with_device(c):
        _device_history(c)
        _core(c, hrv_ms=90, rhr_bpm=45)

    scenario("device_ready", with_device)

    def device_below_min(c):
        _device_history(c, BASELINE[:6])
        _core(c, hrv_ms=90, rhr_bpm=45)

    scenario("device_below_min_readings", device_below_min)

    for value in (0, 55, 100, 101):
        scenario(
            f"wearable_{value}",
            lambda c, value=value: _core(c, wearable_score=value),
        )

    def global_override(c):
        _core(c)
        repositories.append_readiness_override(
            c, effective_on="2026-01-10", scope="global", value=0.42, reason="test",
        )

    scenario("override_global", global_override)

    def category_override(c):
        _core(c)
        repositories.append_readiness_override(
            c, effective_on="2026-01-10", scope="category:hinge", value=0.61, reason="test",
        )

    scenario("override_category", category_override)

    def override_without_score(c):
        repositories.append_readiness_override(
            c, effective_on="2026-01-10", scope="global", value=0.3, reason="test",
        )

    scenario("override_without_score", override_without_score)

    def suppressed(c):
        _device_history(c)
        _core(c, hrv_ms=90, rhr_bpm=45)
        conn = c
        conn.execute(
            "INSERT INTO readiness_context (on_date, flag, note, created_at) "
            "VALUES ('2026-01-10', 'travel', 'test', '2026-01-10T08:00:00+00:00')"
        )

    config = replace(readiness_config.ReadinessConfig.load(), device_suppression_flags=("travel",))
    scenario("device_suppressed", suppressed, config=config)

    return scenarios


def _assessments() -> list[dict]:
    results = []
    for name, (build, date, kwargs) in _scenarios():
        conn = _conn()
        try:
            build(conn)
            assessment = readiness_score.compute(conn, date, **kwargs).as_dict()
            # Override rows carry a generated id and a receipt timestamp; they are not part of
            # score behaviour and differ between identical runs.
            for row in assessment["overrides"].values():
                row.pop("override_id", None)
                row.pop("created_at", None)
            results.append({"name": name, "assessment": assessment})
        finally:
            conn.close()
    return results


def test_registry_matches_the_pre_registry_golden():
    if os.environ.get("WRITE_READINESS_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        with GOLDEN.open("w", encoding="utf-8") as handle:
            print(json.dumps(_assessments(), indent=2, sort_keys=True), file=handle)
        pytest.skip("golden fixture written")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert _assessments() == expected
