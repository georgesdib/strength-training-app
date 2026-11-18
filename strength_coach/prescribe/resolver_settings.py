"""Resolver scalar settings for the Step 2 generator.

Structural policy (pools, patterns, top-set eligibility) lives in
config/template-resolver.v1.yaml. The scalar values below come from the effective-dated
settings profile, with registry defaults when no profile value exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from strength_coach import settings_profile


@dataclass(frozen=True)
class ResolverSettings:
    enabled: bool
    dwell_target: int
    dwell_tau: float
    dwell_probability: float
    full_evaluations: int
    require_can_do: bool
    unrated_mode: str
    will_do_blocks: bool
    feels_bad_blocks: bool
    coverage_priority: str
    under_target_weight: float
    over_target_weight: float
    weights: Mapping[str, float]
    tie_break: str
    top_set_mode: str
    top_set_eligible: str
    top_set_backoff_percent: float
    top_set_protect_top_set: bool
    top_set_fallback_above_rir: int
    top_set_rir_maximal: int
    top_set_rir_strength: int
    top_set_rir_off: int
    competition_override_enabled: bool
    competition_peak_weeks: int
    competition_taper_days: int

    @classmethod
    def load(cls, conn, on_date: str) -> ResolverSettings:
        row = settings_profile.latest(conn, on_date)
        overrides = row["overrides"] if row else {}
        values = settings_profile.resolved_registry(overrides)
        return cls.from_values(values)

    @classmethod
    def from_values(cls, values: Mapping[str, object]) -> ResolverSettings:
        weights = {
            key: float(values[f"resolver.weights.{key}"])
            for key in ("readiness", "fatigue", "spinal", "injury", "dwell")
        }
        return cls(
            enabled=bool(values["resolver.enabled"]),
            dwell_target=int(values["resolver.dwell.target"]),
            dwell_tau=float(values["resolver.dwell.tau"]),
            dwell_probability=float(values["resolver.dwell.probability"]),
            full_evaluations=int(values["resolver.full_evaluations"]),
            require_can_do=bool(values["resolver.eligibility.auto_requires_can_do"]),
            unrated_mode=str(values["resolver.eligibility.unrated_mode"]),
            will_do_blocks=bool(values["resolver.eligibility.will_do_blocks"]),
            feels_bad_blocks=bool(values["resolver.eligibility.feels_bad_blocks"]),
            coverage_priority=str(values["resolver.coverage.priority"]),
            under_target_weight=float(values["resolver.coverage.under_target_weight"]),
            over_target_weight=float(values["resolver.coverage.over_target_weight"]),
            weights=MappingProxyType(weights),
            tie_break=str(values["resolver.tie_break"]),
            top_set_mode=str(values["resolver.top_set.mode"]),
            top_set_eligible=str(values["resolver.top_set.eligible"]),
            top_set_backoff_percent=float(values["resolver.top_set.backoff_percent"]),
            top_set_protect_top_set=bool(values["resolver.top_set.protect_top_set"]),
            top_set_fallback_above_rir=int(values["resolver.top_set.fallback_above_rir"]),
            top_set_rir_maximal=int(values["resolver.top_set.rir_by_main_scheme.maximal"]),
            top_set_rir_strength=int(values["resolver.top_set.rir_by_main_scheme.strength"]),
            top_set_rir_off=int(values["resolver.top_set.rir_by_main_scheme.off"]),
            competition_override_enabled=bool(values["resolver.competition.override_enabled"]),
            competition_peak_weeks=int(values["resolver.competition.peak_weeks"]),
            competition_taper_days=int(values["resolver.competition.taper_days"]),
        )


