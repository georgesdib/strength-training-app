"""Backtest harness and labelled eval set.

Layering: the top of the stack, beside `agents`. It may read `critique` and `prescribe`; it
must never be imported by them, or the production path would depend on the evaluation.
"""

from strength_coach.eval.harness import (
    BacktestReport,
    ItemComparison,
    SessionComparison,
    backtest,
    compare,
)
from strength_coach.eval.labels import (
    ITEM_KEYS,
    LabelError,
    LabelledSession,
    LabelledSet,
    load_labels,
    template,
    write_template,
)

__all__ = [
    "BacktestReport",
    "ITEM_KEYS",
    "ItemComparison",
    "LabelError",
    "LabelledSession",
    "LabelledSet",
    "SessionComparison",
    "backtest",
    "compare",
    "load_labels",
    "template",
    "write_template",
]
