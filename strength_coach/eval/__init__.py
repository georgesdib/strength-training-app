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
    CONFIDENCE_LEVELS,
    ITEM_GUIDE,
    ITEM_KEYS,
    LabelError,
    LabelledSession,
    LabelledSet,
    load_labels,
    render_template,
    template,
    write_template,
)
from strength_coach.eval.report import format_report, format_session_sheet, item_guide_lines
from strength_coach.eval.store import load_marks, record_marks

__all__ = [
    "BacktestReport",
    "CONFIDENCE_LEVELS",
    "ITEM_GUIDE",
    "ITEM_KEYS",
    "ItemComparison",
    "LabelError",
    "LabelledSession",
    "LabelledSet",
    "SessionComparison",
    "backtest",
    "compare",
    "format_report",
    "format_session_sheet",
    "item_guide_lines",
    "load_labels",
    "load_marks",
    "record_marks",
    "render_template",
    "template",
    "write_template",
]
