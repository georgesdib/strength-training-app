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
    rotation_main: float
    rotation_accessory: float
    rotation_default: float
    max_dwell: int
    require_can_do: bool
    unrated_mode: str
    will_do_blocks: bool
    feels_bad_blocks: bool
    coverage_priority: str
    under_target_weight: float
    over_target_weight: float
    weights: Mapping[str, float]
    tie_break: str

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
            for key in ("readiness", "fatigue", "spinal", "injury")
        }
        return cls(
            enabled=bool(values["resolver.enabled"]),
            rotation_main=float(values["resolver.rotation.main"]),
            rotation_accessory=float(values["resolver.rotation.accessory"]),
            rotation_default=float(values["resolver.rotation.default"]),
            max_dwell=int(values["resolver.rotation.max_dwell"]),
            require_can_do=bool(values["resolver.eligibility.auto_requires_can_do"]),
            unrated_mode=str(values["resolver.eligibility.unrated_mode"]),
            will_do_blocks=bool(values["resolver.eligibility.will_do_blocks"]),
            feels_bad_blocks=bool(values["resolver.eligibility.feels_bad_blocks"]),
            coverage_priority=str(values["resolver.coverage.priority"]),
            under_target_weight=float(values["resolver.coverage.under_target_weight"]),
            over_target_weight=float(values["resolver.coverage.over_target_weight"]),
            weights=MappingProxyType(weights),
            tie_break=str(values["resolver.tie_break"]),
        )

    def rotation_for(self, *, role: str) -> float:
        """Rotation for a slot role; the default is the secondary/unclassified fallback."""
        if role == "main":
            return self.rotation_main
        if role == "accessory":
            return self.rotation_accessory
        return self.rotation_default

    def rotation_dwell(self, rotation: float) -> int | None:
        """Sessions before a voluntary change. None means never (rotation 0)."""
        if rotation <= 0.0:
            return None
        if rotation >= 1.0:
            return 1
        return 1 + round((1.0 - rotation) * (self.max_dwell - 1))
