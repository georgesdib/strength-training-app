"""Feature store: derived per-session, per-lift and per-week quantities.

Each module here answers a question the prescription, critique or policy layer asks.
Nothing here contains a rule threshold — thresholds are config, and the rules engine
decides what a value *means*.
"""

from strength_coach.features import baseline

__all__ = ["baseline"]
