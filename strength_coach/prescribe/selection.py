"""Advisory exercise selection for variant slots (roadmap §4.15).

Only the variants already configured for a slot are candidates. The score is transparent and
does **not** change a prescription; it shows whether a different variant looks better given
readiness, recent stress, rotation and preference. A future phase may apply one substitution
under `MOD-SELECT-001`; this module deliberately stops short of that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from strength_coach.features import fatigue_fitness, injury_signal, recent_stress
from strength_coach.features import readiness_score
from strength_coach.prescribe import constraints as constraints_mod
from strength_coach.prescribe import templates
from strength_coach.rules import RuleContext
from strength_coach.store import queries
from strength_coach.utils import exercises, paths


@dataclass(frozen=True)
class ComparisonConfig:
    """A/B/C classification for a current -> candidate substitution."""

    default_class: str = "B"
    load_basis: Mapping[str, str] = field(default_factory=dict)
    pair_classes: Mapping[frozenset[str], str] = field(default_factory=dict)
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ComparisonConfig":
        source = Path(path or paths.config_dir("selection-comparability.v1.yaml"))
        if not source.exists():
            return cls(source_path=source)
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        default = str(raw.get("default_class", "B")).upper()
        if default not in {"A", "B", "C"}:
            raise ValueError(f"default_class must be A/B/C, got {default!r}")
        load_basis: dict[str, str] = {}
        for basis, ids in (raw.get("load_basis") or {}).items():
            for exercise_id in ids or ():
                load_basis[str(exercise_id)] = str(basis)
        pair_classes: dict[frozenset[str], str] = {}
        for klass, pairs in (raw.get("pairs") or {}).items():
            name = str(klass).upper()
            if name not in {"A", "B", "C"}:
                raise ValueError(f"pair class must be A/B/C, got {klass!r}")
            for pair in pairs or ():
                if len(pair) != 2:
                    raise ValueError("each comparability pair needs two exercise ids")
                pair_classes[frozenset((str(pair[0]), str(pair[1])))] = name
        return cls(default_class=default, load_basis=load_basis,
                   pair_classes=pair_classes, source_path=source)

    def classify(self, current: str, candidate: str) -> tuple[str, str]:
        if current == candidate:
            return "A", "same exercise"
        pair = frozenset((current, candidate))
        if pair in self.pair_classes:
            klass = self.pair_classes[pair]
            if klass == "C":
                return "C", "configured as a different lift/load basis"
            if klass == "B":
                return "B", "near-comparable; confirmation required"
            return "A", "configured as load-comparable"
        left = self.load_basis.get(current)
        right = self.load_basis.get(candidate)
        if left and right and left != right:
            return "C", f"different load basis ({left} -> {right})"
        return self.default_class, "same load basis; confirmation required"


@dataclass(frozen=True)
class SelectionConfig:
    weights: Mapping[str, float]
    rotation_days: float
    injury_penalty: float
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "SelectionConfig":
        source = Path(path or paths.selection_yaml())
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        weights = {key: float(value) for key, value in (raw.get("weights") or {}).items()}
        total = sum(weights.values()) or 1.0
        return cls(
            weights={key: value / total for key, value in weights.items()},
            rotation_days=float(raw.get("rotation_days", 28)),
            injury_penalty=float(raw.get("injury_penalty", 0.15)),
            source_path=source,
        )


def _catalogue() -> dict[str, dict[str, tuple[str, ...]]]:
    path = paths.config_dir("variants.v1.yaml")
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        str(day): {
            str(slot): tuple(str(item) for item in items)
            for slot, items in (slots or {}).items()
        }
        for day, slots in (raw.get("slots") or {}).items()
    }


@dataclass(frozen=True)
class Candidate:
    exercise_id: str
    score: float
    reasons: tuple[str, ...]
    comparison_class: str
    comparison_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "score": round(self.score, 3),
            "reasons": list(self.reasons),
            "comparison_class": self.comparison_class,
            "comparison_reason": self.comparison_reason,
        }


@dataclass(frozen=True)
class SlotSelection:
    slot_id: str
    current: str
    suggested: str
    changed: bool
    source: str                 # python | llm | none
    reason: str
    candidates: tuple[Candidate, ...]
    comparison_class: str
    requires_confirmation: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "current": self.current,
            "suggested": self.suggested,
            "changed": self.changed,
            "source": self.source,
            "reason": self.reason,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "comparison_class": self.comparison_class,
            "requires_confirmation": self.requires_confirmation,
            "applied": False,
            "blocked_reason": None,
        }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _current(slot: templates.Slot, context) -> str:
    latest: tuple[Any, str] | None = None
    for exercise_id in slot.exercises:
        history = context.sets[context.sets["exercise_id"] == exercise_id]
        if history.empty:
            continue
        when = history["date"].max()
        if latest is None or when > latest[0]:
            latest = (when, exercise_id)
    return latest[1] if latest else slot.exercises[0]


def _preference(exercise_id: str, suitability: Mapping[str, Mapping[str, Any]]) -> float:
    rating = suitability.get(exercise_id) or {}
    if not rating:
        return 0.5
    if rating.get("can_do") in (0, False):
        return 0.0
    if rating.get("feels_bad") in (1, True):
        return 0.0
    return 1.0 if rating.get("will_do") in (1, True) else 0.5


def _light_context(conn, on_date: str, exercise_ids: tuple[str, ...]) -> RuleContext:
    """Only the candidate history is needed; loading the full enriched log made the UI slow."""
    sets = queries.clean_sets(conn, exercise_ids=exercise_ids)
    sessions = queries.sessions(conn, end=on_date)
    return RuleContext(
        sets=sets,
        sessions=sessions,
        entities=exercises.taxonomy().entities,
        block_week_index=None,
    )


def select(
    conn,
    context: RuleContext | None,
    on_date: str,
    day: str,
    *,
    session_type: str | None = None,
    config: SelectionConfig | None = None,
    chooser: Callable[[templates.Slot, tuple[Candidate, ...]], tuple[str, str] | None] | None = None,
    include_different: bool = False,
    comparability: ComparisonConfig | None = None,
) -> list[SlotSelection]:
    """Rank variants per slot; never modify the prescription.

    `chooser` is an optional LLM/policy hook. It receives the slot and the deterministic
    candidates and must return `(exercise_id, reason)` or None. The id is validated here.
    """
    cfg = config or SelectionConfig.load()
    comparison = comparability or ComparisonConfig.load()
    template = (
        templates.SessionTemplate.load(session_type)
        if session_type is not None else templates.DayTemplate.load(day)
    )
    extra = _catalogue().get(session_type or day, {})
    slot_ids = {
        slot.id: tuple(dict.fromkeys((*slot.exercises, *extra.get(slot.id, ()))))
        for slot in template.slots
    }
    if context is None:
        wanted = tuple(sorted({item for ids in slot_ids.values() for item in ids}))
        context = _light_context(conn, on_date, wanted)
    assessment = readiness_score.compute(conn, on_date)
    injury = injury_signal.compute(conn, on_date, ramp_week=context.block_week_index)
    stress = recent_stress.compute(context.sets, on_date)
    stress_cfg = recent_stress.StressConfig.load()
    try:
        models = {
            model.exercise_id: model
            for model in fatigue_fitness.compute_cached(conn, on_date)
        }
    except Exception:
        models = {}
    suitability = queries.exercise_suitability(conn)
    all_ids = sorted({item for ids in slot_ids.values() for item in ids})
    veto_report = constraints_mod.evaluate(conn, all_ids)
    vetoed = {exercise_id for exercise_id, _ in veto_report.vetoes}
    active_regions = {
        region.region: set(region.linked_exercises)
        for region in injury.regions if region.status == injury_signal.STATUS_ACTIVE
    }

    out: list[SlotSelection] = []
    for slot in template.slots:
        candidate_ids = list(slot_ids.get(slot.id, slot.exercises))
        if len(candidate_ids) < 2:
            continue
        current = _current(slot, context)
        candidates: list[Candidate] = []
        for exercise_id in candidate_ids:
            comparison_class, comparison_reason = comparison.classify(current, exercise_id)
            if comparison_class == "C" and not include_different:
                continue
            entity = context.entity(exercise_id)
            if exercise_id in vetoed:
                continue
            if not _preference(exercise_id, suitability):
                continue
            base, _, _, _ = readiness_score.effective(
                assessment, conn, exercise_id, entity, signal=injury
            )
            readiness = 1.0 if base is None else _clamp(float(base))
            stress_entry = stress.get(exercise_id)
            stress_score = 0.5
            if stress_entry is not None:
                stress_score = _clamp(1.0 - stress_entry.decayed_sets / stress_cfg.high_decayed_sets)
            history = context.sets[
                context.sets["exercise_id"].isin(exercises.history_equivalents(exercise_id))
            ]
            days_since = (
                (context.sets["date"].max() - history["date"].max()).days
                if not history.empty else cfg.rotation_days
            )
            rotation = _clamp(float(days_since) / cfg.rotation_days)
            preference = _preference(exercise_id, suitability)
            model = models.get(exercise_id)
            fatigue = 0.5
            if model and model.latest_e1rm and model.state_kg:
                fatigue = _clamp(0.5 + (model.state_kg / model.latest_e1rm - 1.0) / 0.10)
            score = (
                cfg.weights.get("readiness", 0.35) * readiness
                + cfg.weights.get("stress", 0.25) * stress_score
                + cfg.weights.get("rotation", 0.20) * rotation
                + cfg.weights.get("preference", 0.10) * preference
                + cfg.weights.get("fatigue", 0.10) * fatigue
            )
            if any(exercise_id in linked for linked in active_regions.values()):
                score -= cfg.injury_penalty
            reasons = [
                f"readiness {readiness:.2f}",
                f"recent stress {stress_entry.status if stress_entry else 'unknown'}",
                f"rotation {days_since}d",
                f"preference {preference:.1f}",
                f"fatigue {fatigue:.2f}",
            ]
            candidates.append(Candidate(
                exercise_id, _clamp(score), tuple(reasons),
                comparison_class, comparison_reason,
            ))

        if not candidates:
            continue
        ranked = tuple(sorted(candidates, key=lambda c: (-c.score, c.exercise_id)))
        suggested = ranked[0].exercise_id
        source = "python"
        reason = "highest deterministic score"
        if chooser is not None:
            try:
                chosen = chooser(slot, ranked)
            except Exception as exc:  # LLM failure must fall back, never break the page
                chosen = None
                reason = f"deterministic fallback: {exc}"
            if chosen is not None:
                chosen_id, chosen_reason = chosen
                if any(candidate.exercise_id == chosen_id for candidate in ranked):
                    suggested, source, reason = chosen_id, "llm", chosen_reason
        # Stable preference: a tie keeps the current variant.
        if suggested != current:
            top = next(c for c in ranked if c.exercise_id == suggested)
            current_c = next(
                (c for c in ranked if c.exercise_id == current), None
            )
            if current_c is not None and abs(top.score - current_c.score) < 1e-9:
                suggested = current
                reason = "tie; keep the current variant"
        out.append(SlotSelection(
            slot_id=slot.id,
            current=current,
            suggested=suggested,
            changed=suggested != current,
            source=source,
            reason=reason,
            candidates=ranked,
            comparison_class=(
                next(c.comparison_class for c in ranked if c.exercise_id == suggested)
                if suggested != current else "A"
            ),
            requires_confirmation=(
                suggested != current and next(
                    c.comparison_class for c in ranked if c.exercise_id == suggested
                ) != "A"
            ),
        ))
    return out


def as_dict(report: list[SlotSelection]) -> list[dict[str, Any]]:
    return [row.as_dict() for row in report]
