"""Periodic review reminders.

These are prompts to inspect evidence, not controllers. The only write is an append-only
human acknowledgement (completed/snoozed); no threshold or prescription is changed here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import yaml

from strength_coach.domain.symptoms import flare_from
from strength_coach.features import test_cadence
from strength_coach.store import queries
from strength_coach.utils import paths


@dataclass(frozen=True)
class ReviewTask:
    key: str
    label: str
    kind: str
    status: str
    due_on: str | None
    summary: str
    why: str
    steps: tuple[str, ...]
    dont: tuple[str, ...]
    doc: str
    periodic: bool = False
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "kind": self.kind,
            "status": self.status, "due_on": self.due_on, "summary": self.summary,
            "why": self.why, "steps": list(self.steps), "dont": list(self.dont),
            "doc": self.doc, "periodic": self.periodic, "details": self.details or {},
        }


def _config() -> dict:
    path = paths.config_dir("reviews.v1.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _latest(conn, task_key: str) -> dict | None:
    row = conn.execute(
        """
        SELECT * FROM maintenance_review
         WHERE task_key = ?
         ORDER BY reviewed_on DESC, rowid DESC LIMIT 1
        """,
        (task_key,),
    ).fetchone()
    return dict(row) if row is not None else None


def snooze_days(task_key: str) -> int:
    config = _config()
    if task_key in {
        "readiness_thresholds", "exercise_substitution", "fatigue_signals",
        "phase5a_review",
    }:
        return int((config.get(task_key) or {}).get("snooze_days", 14))
    raise ValueError(f"no snooze policy for {task_key!r}")


def _task(conn, key: str, on_date: str, config: dict) -> ReviewTask:
    cfg = config.get(key) or {}
    if key == "readiness_thresholds":
        return _readiness_task(conn, on_date, cfg)
    if key == "exercise_substitution":
        return _substitution_task(conn, on_date, cfg)
    if key == "fatigue_signals":
        return _periodic_task(conn, on_date, "fatigue_signals", cfg, "Fatigue signals")
    if key == "rubric_labels":
        return _rubric_task(conn, on_date, cfg)
    if key == "strength_test":
        return _test_task(conn, on_date, cfg)
    if key == "srpe_coverage":
        return _srpe_task(conn, on_date, cfg)
    if key == "readiness_baseline":
        return _baseline_task(conn, on_date, cfg)
    if key == "back_pattern":
        return _back_task(conn, on_date, cfg)
    if key == "phase5a_review":
        return _phase5a_task(conn, on_date, cfg)
    raise ValueError(f"unknown review task {key!r}")


def _periodic_task(
    conn, on_date: str, key: str, cfg: dict, default_label: str,
) -> ReviewTask:
    last = _latest(conn, key)
    interval = dt.timedelta(weeks=int(cfg.get("interval_weeks", 12)))
    if last and last["action"] == "snoozed" and str(last["snoozed_until"]) >= on_date:
        return ReviewTask(
            key, str(cfg.get("label", default_label)), "periodic", "snoozed",
            str(last["snoozed_until"]),
            f"Snoozed until {last['snoozed_until']}.", str(cfg.get("why", "")),
            tuple(cfg.get("steps") or ()), tuple(cfg.get("dont") or ()),
            str(cfg.get("doc", "")), True,
            {"last_completed": last.get("reviewed_on")},
        )
    completed = str(last["reviewed_on"]) if last and last["action"] == "completed" else None
    sessions_since = None
    if completed is not None:
        sessions_since = conn.execute(
            "SELECT COUNT(*) AS n FROM session WHERE occurred_on > ? AND occurred_on <= ? AND voided = 0",
            (completed, on_date),
        ).fetchone()[0]
    if completed is None:
        due_on = on_date
        status, summary = "due", f"No {default_label.lower()} recorded."
    else:
        due_on = (dt.date.fromisoformat(completed) + interval).isoformat()
        by_sessions = sessions_since is not None and sessions_since >= int(cfg.get("interval_sessions", 40))
        status = "due" if (on_date >= due_on or by_sessions) else "not_due"
        summary = (
            f"{default_label} are due for review."
            if status == "due" else f"Next review {due_on}."
        )
    return ReviewTask(
        key, str(cfg.get("label", default_label)), "periodic", status, due_on,
        summary, str(cfg.get("why", "")), tuple(cfg.get("steps") or ()),
        tuple(cfg.get("dont") or ()), str(cfg.get("doc", "")), True,
        {"last_completed": completed, "interval_weeks": cfg.get("interval_weeks", 12),
         "sessions_since": sessions_since},
    )


def _phase5a_task(conn, on_date: str, cfg: dict) -> ReviewTask:
    """Explicit Phase 5A gate; never starts Phase 5B or changes monitoring."""
    start = str(cfg.get("start_date", "2026-10-30"))
    due = str(cfg.get("due_date", "2027-01-22"))
    last = _latest(conn, "phase5a_review")
    if last and last["action"] == "completed":
        return ReviewTask(
            "phase5a_review", str(cfg.get("label", "Phase 5A — Prospective validation review")),
            "roadmap", "completed", due,
            f"Completed {last['reviewed_on']}; decision {last.get('decision')}.",
            str(cfg.get("why", "")), tuple(cfg.get("steps") or ()),
            tuple(cfg.get("dont") or ()), str(cfg.get("doc", "")), True,
            {"start_date": start, "due_date": due, "last_completed": last.get("reviewed_on"),
             "decision": last.get("decision")},
        )
    if last and last["action"] == "snoozed" and str(last["snoozed_until"]) >= on_date:
        return ReviewTask(
            "phase5a_review", str(cfg.get("label", "Phase 5A — Prospective validation review")),
            "roadmap", "snoozed", str(last["snoozed_until"]),
            f"Snoozed until {last['snoozed_until']}.",
            str(cfg.get("why", "")), tuple(cfg.get("steps") or ()),
            tuple(cfg.get("dont") or ()), str(cfg.get("doc", "")), True,
            {"start_date": start, "due_date": due, "last_completed": None},
        )
    if on_date < start:
        status = "planned"
        summary = f"Planned to start {start}; due {due}."
    elif on_date >= due:
        status = "attention"
        summary = f"Phase 5A review is due (window ended {due})."
    else:
        status = "due"
        summary = f"Phase 5A observation window is active until {due}; review remains pending."
    return ReviewTask(
        "phase5a_review", str(cfg.get("label", "Phase 5A — Prospective validation review")),
        "roadmap", status, due, summary, str(cfg.get("why", "")),
        tuple(cfg.get("steps") or ()), tuple(cfg.get("dont") or ()),
        str(cfg.get("doc", "")), True,
        {"start_date": start, "due_date": due, "last_completed": None},
    )


def _readiness_task(conn, on_date: str, cfg: dict) -> ReviewTask:
    return _periodic_task(conn, on_date, "readiness_thresholds", cfg,
                          "Readiness thresholds")


def _substitution_task(conn, on_date: str, cfg: dict) -> ReviewTask:
    return _periodic_task(conn, on_date, "exercise_substitution", cfg,
                          "Substitution suggestions")


def _rubric_task(conn, on_date: str, cfg: dict) -> ReviewTask:
    target = int(cfg.get("target_per_item", 10))
    wanted = tuple(cfg.get("measurable_items") or ())
    marks = queries.latest_rubric_marks(conn)
    counts = {key: 0 for key in wanted}
    for mark in marks:
        if mark["item"] in counts and mark["score"] is not None and mark["confidence"] == "high":
            counts[mark["item"]] += 1
    missing = {key: target - count for key, count in counts.items() if count < target}
    status = "attention" if missing else "ok"
    summary = (
        f"{sum(counts.values())}/{len(wanted) * target} high-confidence marks; "
        f"{len(missing)} item(s) below target."
    )
    return ReviewTask(
        "rubric_labels", str(cfg.get("label", "Deepen rubric calibration labels")),
        "data", status, None, summary, str(cfg.get("why", "")),
        tuple(cfg.get("steps") or ()), tuple(cfg.get("dont") or ()),
        str(cfg.get("doc", "")), False,
        {"counts": counts, "target_per_item": target, "missing": missing},
    )


def _test_task(conn, on_date: str, cfg: dict) -> ReviewTask:
    report = test_cadence.status(conn, on_date)
    status = "due" if report.get("due") else "not_due"
    summary = (
        f"{report.get('next_scheme')} due by {report.get('next_due')}."
        if status == "due" else f"Not due; next {report.get('next_scheme')} by {report.get('next_due')}."
    )
    return ReviewTask(
        "strength_test", str(cfg.get("label", "3RM/5RM strength test")),
        "data", status, report.get("next_due"), summary, str(cfg.get("why", "")),
        tuple(cfg.get("steps") or ()), tuple(cfg.get("dont") or ()),
        str(cfg.get("doc", "")), False, report,
    )


def _srpe_task(conn, on_date: str, cfg: dict) -> ReviewTask:
    days = int(cfg.get("window_days", 56))
    start = (dt.date.fromisoformat(on_date) - dt.timedelta(days=days)).isoformat()
    sessions = conn.execute(
        "SELECT COUNT(*) AS n FROM session WHERE occurred_on BETWEEN ? AND ? AND voided = 0",
        (start, on_date),
    ).fetchone()[0]
    covered = conn.execute(
        """
        SELECT COUNT(DISTINCT f.session_id) AS n
          FROM session_feedback f
          JOIN session s ON s.session_id = f.session_id
         WHERE s.occurred_on BETWEEN ? AND ?
           AND f.srpe IS NOT NULL AND f.duration_min IS NOT NULL
        """,
        (start, on_date),
    ).fetchone()[0]
    pct = round(100 * covered / sessions, 1) if sessions else 0.0
    target = float(cfg.get("target_pct", 80))
    minimum = int(cfg.get("minimum_sessions", 6))
    status = "ok" if (sessions >= minimum and pct >= target) else "attention"
    return ReviewTask(
        "srpe_coverage", str(cfg.get("label", "sRPE/duration coverage")),
        "data", status, None,
        f"{covered}/{sessions} recent sessions with sRPE + duration ({pct}%).",
        str(cfg.get("why", "")), tuple(cfg.get("steps") or ()),
        tuple(cfg.get("dont") or ()), str(cfg.get("doc", "")), False,
        {"sessions": sessions, "covered": covered, "pct": pct, "target_pct": target},
    )


def _baseline_task(conn, on_date: str, cfg: dict) -> ReviewTask:
    days = int(cfg.get("window_days", 28))
    start = (dt.date.fromisoformat(on_date) - dt.timedelta(days=days)).isoformat()
    n = conn.execute(
        """
        SELECT COUNT(*) AS n FROM (
            SELECT on_date FROM readiness_day WHERE on_date BETWEEN ? AND ?
            UNION
            SELECT on_date FROM readiness_entry WHERE on_date BETWEEN ? AND ?
        )
        """,
        (start, on_date, start, on_date),
    ).fetchone()[0]
    minimum = int(cfg.get("minimum_readings", 10))
    status = "ok" if n >= minimum else "insufficient"
    return ReviewTask(
        "readiness_baseline", str(cfg.get("label", "Readiness baseline sufficiency")),
        "data", status, None,
        f"{n}/{minimum} readiness readings in the last {days} days.",
        str(cfg.get("why", "")), tuple(cfg.get("steps") or ()),
        tuple(cfg.get("dont") or ()), str(cfg.get("doc", "")), False,
        {"readings": n, "minimum": minimum, "window_days": days},
    )


def _back_task(conn, on_date: str, cfg: dict) -> ReviewTask:
    symptom = queries.latest_symptom(conn, on_date)
    recent = int(cfg.get("recent_days", 14))
    # A clean level-0 reading is not an episode; only an actual flare asks for a review.
    # Use the shared flare definition so a settled level-1 reading is also not a false alarm.
    is_flare = bool(
        symptom
        and flare_from(int(symptom["level"]), symptom.get("settled_within_48h")) is True
    )
    status = "attention" if is_flare and symptom.get("logged_on") and (
        dt.date.fromisoformat(on_date) - dt.date.fromisoformat(str(symptom["logged_on"]))
    ).days <= recent else "ok"
    summary = (
        f"Recent back flare logged {symptom['logged_on']} (level {symptom['level']}/3)."
        if status == "attention" else "No recent back flare logged."
    )
    return ReviewTask(
        "back_pattern", str(cfg.get("label", "Back-pattern review")),
        "data", status, None, summary, str(cfg.get("why", "")),
        tuple(cfg.get("steps") or ()), tuple(cfg.get("dont") or ()),
        str(cfg.get("doc", "")), False,
        {"latest_symptom": symptom.get("logged_on") if symptom else None,
         "level": symptom.get("level") if symptom else None},
    )


def status(conn, on_date: str) -> dict:
    config = _config()
    tasks = []
    for key in (
        "readiness_thresholds", "exercise_substitution", "fatigue_signals",
        "rubric_labels", "strength_test", "srpe_coverage", "readiness_baseline",
        "back_pattern", "phase5a_review",
    ):
        tasks.append(_task(conn, key, on_date, config).as_dict())
    profile = queries.athlete_profile(conn) or {}
    if profile.get("volume_budget_enabled"):
        # Standing review after the plan closed: it appears while the budget is enabled and
        # never changes a prescription. It is not a roadmap milestone.
        tasks.append(ReviewTask(
            key="volume_review", label="Volume review (standing)", kind="reminder",
            status="attention", due_on=on_date,
            summary="Standing review: check trims and top-ups after 2-3 weeks of budget use.",
            why="The volume-modulation plan is closed; this is a standing follow-up review.",
            steps=(
                "Use the budget for 2-3 weeks.",
                "Review trims, top-ups, blocked warnings and the high-band guard.",
                "Keep or adjust config; roll back to hard if a defect appears.",
            ),
            dont=("Do not treat this reminder as an unresolved plan item.",),
            doc="docs/VOLUME-MODULATION-PLAN.md",
        ).as_dict())
    due = [task for task in tasks if task["status"] in {"due", "attention"}]
    return {"on_date": on_date, "due_count": len(due), "tasks": tasks}
