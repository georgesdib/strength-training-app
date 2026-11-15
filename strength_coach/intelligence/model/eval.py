"""A small end-to-end evaluation harness for server narration.

The fake client keeps this runnable in CI: every case exercises the real capability and the real
validator, but no network or API key is involved. The CLI tool can optionally use the configured
real client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strength_coach.agents.client import LLMClient
from strength_coach.intelligence.auth import INTERNAL_PRINCIPAL
from strength_coach.intelligence.model.narrative import narrate_envelope
from strength_coach.intelligence.service import IntelligenceService


@dataclass(frozen=True)
class EvalCase:
    capability: str
    payload: dict[str, Any]
    expect_error: str | None = None


@dataclass(frozen=True)
class EvalResult:
    capability: str
    ok: bool
    status: str
    detail: str
    warnings: tuple[str, ...] = ()
    tokens: int | None = None


CASES: tuple[EvalCase, ...] = (
    EvalCase("get_weekly_review", {}),
    EvalCase("get_training_overview", {}),
    EvalCase("get_exercise_progression", {"exercise_id": "trap_bar_deadlift"}),
    EvalCase(
        "get_readiness_history",
        {"from": "2026-10-01", "to": "2026-11-14", "fields": ["score"]},
    ),
    EvalCase("get_session_details", {"workout_id": "missing"}, expect_error="not_found"),
    EvalCase("get_prescription", {}),
    EvalCase("get_programme_block_summary", {}),
    EvalCase("get_adherence_analysis", {"weeks": 4}),
    EvalCase(
        "compare_training_periods",
        {
            "period_a": {"start": "2026-09-01", "end": "2026-09-30"},
            "period_b": {"start": "2026-10-01", "end": "2026-10-31"},
            "metric": "attendance",
        },
    ),
    EvalCase("get_vbt_analysis", {"window_days": 56}),
)


def run_eval(service: IntelligenceService, client: LLMClient) -> list[EvalResult]:
    results: list[EvalResult] = []
    for case in CASES:
        result = service.execute(INTERNAL_PRINCIPAL, case.capability, case.payload)
        if not result.ok:
            error = result.error
            expected = case.expect_error is not None and error.code == case.expect_error
            results.append(
                EvalResult(
                    case.capability,
                    expected,
                    "expected_error" if expected else "error",
                    f"{error.code}: {error.message}",
                )
            )
            continue
        try:
            narrative = narrate_envelope(client, result.envelope)
        except Exception as exc:  # the harness reports, it does not hide
            results.append(
                EvalResult(case.capability, False, result.envelope.status, str(exc))
            )
            continue
        results.append(
            EvalResult(
                case.capability,
                True,
                result.envelope.status,
                narrative.headline,
                narrative.warnings,
                narrative.tokens,
            )
        )
    return results
