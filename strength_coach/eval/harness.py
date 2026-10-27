"""The backtest harness: replay sessions, compare the rubric against a human.

A backtest answers one question -- does the rubric agree with a person who watched the session?
It is deliberately not a self-consistency check: the engine's scores are compared against marks
made outside the engine, so a rubric that is merely stable scores badly here.

The replay is honest about time: every score is computed with history cut at the session date,
which is what `critique.facts` already does. A backtest that could see the future would report
agreement that the production path cannot reproduce.
"""

from __future__ import annotations

from dataclasses import dataclass

from strength_coach.critique import build_facts, score_session
from strength_coach.critique.rubric import Critique
from strength_coach.eval.labels import ITEM_KEYS, LabelledSession, LabelledSet


@dataclass(frozen=True)
class ItemComparison:
    key: str
    engine: float | None
    human: float | None
    delta: float | None
    within_tolerance: bool | None

    @property
    def comparable(self) -> bool:
        return self.delta is not None


@dataclass(frozen=True)
class SessionComparison:
    session_id: str
    items: tuple[ItemComparison, ...]
    disagreements: tuple[str, ...]
    confidence: str = "unknown"

    @property
    def reliable(self) -> bool:
        return self.confidence == "high"

    @property
    def comparable_items(self) -> tuple[ItemComparison, ...]:
        return tuple(item for item in self.items if item.comparable)

    @property
    def agreement_rate(self) -> float | None:
        comparable = self.comparable_items
        if not comparable:
            return None
        agreed = sum(1 for item in comparable if item.within_tolerance)
        return agreed / len(comparable)

    @property
    def mean_abs_error(self) -> float | None:
        comparable = self.comparable_items
        if not comparable:
            return None
        return sum(abs(item.delta) for item in comparable) / len(comparable)


@dataclass(frozen=True)
class BacktestReport:
    tolerance: float
    sessions: tuple[SessionComparison, ...]

    @property
    def reliable_sessions(self) -> tuple[SessionComparison, ...]:
        """Only sessions the marker actually remembers; the rest are recorded, not scored."""
        return tuple(session for session in self.sessions if session.reliable)

    @property
    def unreliable_sessions(self) -> tuple[SessionComparison, ...]:
        return tuple(session for session in self.sessions if not session.reliable)

    @property
    def comparable_items(self) -> tuple[ItemComparison, ...]:
        return tuple(
            item for session in self.reliable_sessions for item in session.comparable_items
        )

    @property
    def mean_abs_error(self) -> float | None:
        items = self.comparable_items
        if not items:
            return None
        return sum(abs(item.delta) for item in items) / len(items)

    @property
    def agreement_rate(self) -> float | None:
        items = self.comparable_items
        if not items:
            return None
        return sum(1 for item in items if item.within_tolerance) / len(items)

    @property
    def per_item(self) -> dict[str, dict[str, float | None]]:
        """Agreement and error per rubric item, so a systematically bad line is visible."""
        out: dict[str, dict[str, float | None]] = {}
        for key in ITEM_KEYS:
            pairs = [
                item for item in self.comparable_items if item.key == key
            ]
            if not pairs:
                out[key] = {"n": 0, "agreement": None, "mae": None}
                continue
            out[key] = {
                "n": len(pairs),
                "agreement": sum(1 for p in pairs if p.within_tolerance) / len(pairs),
                "mae": sum(abs(p.delta) for p in pairs) / len(pairs),
            }
        return out


def compare(
    critique: Critique,
    label: LabelledSession,
    *,
    tolerance: float = 0.25,
) -> SessionComparison:
    """Compare one engine critique with one human mark."""
    items: list[ItemComparison] = []
    disagreements: list[str] = []
    for key in ITEM_KEYS:
        engine_item = critique.item(key)
        human = label.score_for(key)
        engine = engine_item.score if engine_item.measurable else None

        if engine is None or human is None:
            # An item the engine could not measure is reported, never scored as agreement.
            items.append(ItemComparison(key=key, engine=engine, human=human, delta=None,
                                        within_tolerance=None))
            continue

        delta = round(human - engine, 4)
        within = abs(delta) <= tolerance + 1e-9
        if not within:
            disagreements.append(key)
        items.append(
            ItemComparison(
                key=key, engine=engine, human=human, delta=delta, within_tolerance=within
            )
        )
    return SessionComparison(
        session_id=label.session_id,
        items=tuple(items),
        disagreements=tuple(disagreements),
        confidence=label.confidence,
    )


def backtest(
    conn,
    labels: LabelledSet,
    *,
    tolerance: float | None = None,
    document=None,
) -> BacktestReport:
    """Replay every labelled session and compare."""
    tolerance = labels.tolerance if tolerance is None else tolerance
    comparisons: list[SessionComparison] = []
    for session_id, label in labels.sessions.items():
        facts = build_facts(conn, session_id, document=document)
        critique = score_session(conn, session_id, document=document, facts=facts)
        comparisons.append(compare(critique, label, tolerance=tolerance))
    return BacktestReport(tolerance=tolerance, sessions=tuple(comparisons))
