"""Training Intelligence capability layer (INT-1).

Read-only, provider-neutral composition of the deterministic training services. Nothing here
imports the web server, a model client or a transport: the layer is the foundation the future MCP
server and the authenticated iPhone route will sit on, not either of them.

Entry points:

* IntelligenceService -- execute a registered capability against a connection;
* authenticate_bearer -- verify a device bearer token without a bookkeeping write;
* load_config -- the switch and bounds in config/intelligence.v1.yaml.
"""

from __future__ import annotations

from strength_coach.intelligence import capabilities  # noqa: F401  (registration side effect)
from strength_coach.intelligence.auth import (
    INTERNAL_PRINCIPAL,
    IntelligenceAuthError,
    Principal,
    authenticate_bearer,
)
from strength_coach.intelligence.config import (
    IntelligenceConfig,
    IntelligenceConfigError,
    load_config,
)
from strength_coach.intelligence.envelope import (
    Envelope,
    FactBlock,
    Period,
    Privacy,
    Provenance,
)
from strength_coach.intelligence.errors import EnvelopeError, IntelligenceError
from strength_coach.intelligence.registry import CAPABILITIES, CapabilityRegistry, CapabilitySpec
from strength_coach.intelligence.service import (
    CapabilityResult,
    Clock,
    IntelligenceService,
)

__all__ = [
    "CAPABILITIES",
    "CapabilityRegistry",
    "CapabilityResult",
    "CapabilitySpec",
    "Clock",
    "Envelope",
    "EnvelopeError",
    "FactBlock",
    "INTERNAL_PRINCIPAL",
    "IntelligenceAuthError",
    "IntelligenceConfig",
    "IntelligenceConfigError",
    "IntelligenceError",
    "IntelligenceService",
    "Period",
    "Principal",
    "Privacy",
    "Provenance",
    "authenticate_bearer",
    "load_config",
]
