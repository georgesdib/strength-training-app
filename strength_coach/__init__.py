"""Evidence-based strength coach.

Layering, enforced by import direction (nothing lower imports anything higher):

    utils      pure helpers, no domain state
    domain     pure domain arithmetic (e1RM, rounding, velocity, progression)
    ingest     CSV -> cleaned records -> sessions
    store      SQLite persistence, append-only
    features   feature store + VBT calibration
    rules      versioned rule documents + policy evaluation
    prescribe  deterministic prescription engine
    critique   deterministic rubric scoring
    agents     LLM layer; may only call deterministic functions through tools
    eval       backtest harness
"""

__version__ = "0.3.0"
