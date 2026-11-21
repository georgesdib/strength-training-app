"""Small checks for the resolver benchmark helpers; the build timing is run by hand."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from strength_coach.prescribe import evaluator as evaluator_mod

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "resolver_benchmark_tool", ROOT / "tools" / "resolver_benchmark.py"
)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_percentile_uses_nearest_rank() -> None:
    assert benchmark._percentile([], 95) is None
    assert benchmark._percentile([1.0], 95) == 1.0
    assert benchmark._percentile([1, 2, 3, 4, 5], 50) == 3
    assert benchmark._percentile([1, 2, 3, 4, 5], 95) == 5
    assert benchmark._percentile(list(range(1, 11)), 95) == 10


def test_timed_reports_p95_and_runs() -> None:
    result = benchmark._timed(lambda: "ok", 4)
    assert result["runs"] == 4
    assert result["result"] == "ok"
    assert result["p50_s"] <= result["p95_s"] <= result["max_s"]


def test_build_counter_restores_the_evaluator_callable() -> None:
    original = evaluator_mod.build_prescription
    with benchmark._counted_build() as (count, set_enabled):
        assert evaluator_mod.build_prescription is not original
        set_enabled(True)
        assert count() == 0
    assert evaluator_mod.build_prescription is original
