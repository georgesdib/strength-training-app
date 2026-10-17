"""Ingestion layer: raw exports -> clean sets -> reconstructed sessions.

Above `utils` and `domain`, below `features`. It never judges programme compliance; it
establishes what happened.
"""

from strength_coach.ingest import clean, sessions

__all__ = ["clean", "sessions"]
