"""A local-only HTTP UI over the same Python core the CLI uses.

Design constraints, deliberately:

* bind to 127.0.0.1 by default and refuse to pretend there is authentication;
* every number still comes from the deterministic core — the UI only serialises it;
* the CLI remains the automation surface; this is an additional front end;
* no external assets, so the page works offline.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import logging
import mimetypes
import os
import sqlite3
import threading
import uuid
import webbrowser
from collections import deque
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

from strength_coach import __version__, history, modalities, settings_profile, settings_registry, workout
from strength_coach.agents import selection as agent_selection
from strength_coach.agents.client import LLMError
from strength_coach.agents.config import (
    PROVIDERS,
    LLMConfigError,
    build_client,
    config_path,
    describe,
    load_settings,
    update_llm_settings,
)
from strength_coach.critique import UnknownSessionError, build_facts, score_session
from strength_coach.critique.rubric import RUBRIC_VERSION
from strength_coach.domain import athlete_state
from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.eval import ITEM_GUIDE, ITEM_KEYS, backtest, format_report, load_marks, record_marks
from strength_coach.features import breaks as breaks_feature
from strength_coach.features import cardio as cardio_feature
from strength_coach.features import (
    config_inventory,
    continuity_calibration,
    heavy_spinal,
    injury_signal,
    monitoring,
    readiness_baseline,
    readiness_calibration,
    readiness_feedback,
    readiness_score,
    rep_velocity,
    retrospective_validation,
)
from strength_coach.features import deload as deload_feature
from strength_coach.features import demands as demands_feature
from strength_coach.features import derived as derived_feature
from strength_coach.features import e1rm_calibration as e1rm_calibration_feature
from strength_coach.features import exposure as exposure_ratio_feature
from strength_coach.features import fatigue_fitness as fatigue_fitness_feature
from strength_coach.features import form_assessment as form_assessment_feature
from strength_coach.features import high_intensity_exposure as exposure_feature
from strength_coach.features import measurements as measurements_feature
from strength_coach.features import monitoring_analysis as monitoring_analysis_feature
from strength_coach.features import outcomes as outcomes_feature
from strength_coach.features import programme as programme_feature
from strength_coach.features import progress as progress_feature
from strength_coach.features import prospective as prospective_feature
from strength_coach.features import readiness as readiness_feature
from strength_coach.features import regime_change as regime_feature
from strength_coach.features import relative_strength as relative_strength_feature
from strength_coach.features import residual as residual_feature
from strength_coach.features import reviews as reviews_feature
from strength_coach.features import session_feedback as session_feedback_feature
from strength_coach.features import shadow_report as shadow_report_feature
from strength_coach.features import strength_trend as strength_trend_feature
from strength_coach.features import volume as volume_feature
from strength_coach.prescribe import (
    build_prescription,
    fatigue_selection,
    session_identity,
    templates,
    volume_settings,
)
from strength_coach.prescribe import deload as deload_mod
from strength_coach.prescribe import persistence as prescription_persistence
from strength_coach.prescribe import schedule as schedule_mod
from strength_coach.prescribe import selection as selection_mod
from strength_coach.prescribe import summary as programme_summary
from strength_coach.prescribe import volume_budget as volume_budget_mod
from strength_coach.prescribe.config import Thresholds
from strength_coach.rules import RuleContext
from strength_coach.store import db, exercise_admin, importer, queries, repositories
from strength_coach.utils import exercises, io_utils, paths
from strength_coach.utils import readiness as readiness_utils
from strength_coach.web import markdown, validation
from strength_coach.web import options as options_mod

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).resolve().parent / "static"
TOLERANCE = 0.25

# Two 20 MiB CSVs plus JSON escaping and keys; see docs/WEB-UI.md. The per-file limit
# remains in _import; this is the HTTP-boundary guard.
MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_IMPORT_FILE_BYTES = 20 * 1024 * 1024
LOGGER = logging.getLogger(__name__)
_LOG_BUFFER: deque[dict[str, Any]] = deque(maxlen=500)
_LOG_LOCK = threading.Lock()


class _BufferLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        with _LOG_LOCK:
            _LOG_BUFFER.append({
                "time": datetime.datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "message": message,
            })


if not any(isinstance(handler, _BufferLogHandler) for handler in logging.getLogger().handlers):
    _log_handler = _BufferLogHandler()
    _log_handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(_log_handler)


class RequestError(Exception):
    """A client error raised before the route; close the socket for framing faults."""

    def __init__(self, status: int, message: str, *, close: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.close = close


class FieldError(ValueError):
    """A validation failure that names the form fields responsible."""

    def __init__(self, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.fields = dict(fields or {})


TEMPLATE_BACKUPS = ROOT / "data" / "template-backups"
TEMPLATE_BACKUP_KEEP = 20


def _backup_template(path) -> None:
    TEMPLATE_BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    (TEMPLATE_BACKUPS / f"session-types-{stamp}.yaml").write_bytes(path.read_bytes())
    backups = sorted(TEMPLATE_BACKUPS.glob("session-types-*.yaml"))
    for old in backups[:-TEMPLATE_BACKUP_KEEP]:
        old.unlink(missing_ok=True)


def _write_template(text: str) -> None:
    path = paths.session_types_yaml()
    if path.exists():
        _backup_template(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_readiness_presets(text: str) -> None:
    """Atomically replace the preset YAML after the caller has validated it."""
    path = paths.config_dir("readiness-presets.v1.yaml")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _item_dict(item) -> dict:
    return {
        "order_index": item.order_index,
        "exercise_id": item.exercise_id,
        "sets": item.sets,
        "reps_low": item.reps_low,
        "reps_high": item.reps_high,
        "load_kg": item.load_kg,
        "load_basis": item.load_basis,
        "rir_target": item.rir_target,
        "effort_model": item.effort_model,
        "quality_stop": item.quality_stop,
        "rest_s": item.rest_s,
        "essential": item.essential,
        "refs": list(item.rationale_refs),
        "rounding_increment_kg": item.rounding_increment_kg,
        "time_cap_s": item.time_cap_s,
        "substitution_for": item.substitution_for,
        "vbt_basis": item.vbt_basis,
        "e1rm_source_sets": item.e1rm_source_sets,
        "e1rm_kg": item.e1rm_kg,
        "e1rm_ref": item.e1rm_ref,
        "e1rm_quality": item.e1rm_quality,
        "e1rm_age_days": item.e1rm_age_days,
        "velocity_target": item.velocity_target,
        "unknown_load_reason": item.unknown_load_reason,
        "warmup": [
            {"percent": w.percent, "reps": w.reps, "load_kg": w.load_kg}
            for w in item.warmup
        ],
    }


def prescription_dict(prescription) -> dict:
    return {
        "for_date": prescription.for_date,
        "session_type": prescription.session_type,
        "session_label": session_identity.label(prescription.session_type),
        "session_kind": (
            "volume_fill" if session_identity.is_volume_fill(prescription.session_type)
            else "technique" if session_identity.is_technique(prescription.session_type)
            else "normal"
        ),
        "session_original_type": session_identity.original_type(prescription.session_type),
        "counts_as_main": session_identity.counts_as_main(prescription.session_type),
        "fallback_level": prescription.fallback_level,
        "rule_document_version": prescription.rule_document_version,
        "calibration_ids": list(prescription.calibration_ids),
        "executable": prescription.executable,
        "items": [_item_dict(item) for item in prescription.items],
        "warnings": list(prescription.warnings),
        "issues": list(prescription.issues),
        "notes": prescription.notes,
    }


def _session_rows(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """
        SELECT s.session_id, s.occurred_on, s.session_type, s.set_count, s.working_set_count,
               s.main_lifts, s.tonnage_kg, s.needs_review, s.edited_at,
               (SELECT COUNT(*) FROM rubric_mark m WHERE m.session_id = s.session_id) AS marks
          FROM session s
         WHERE s.voided = 0
         ORDER BY s.occurred_on DESC
         LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        try:
            data["main_lifts"] = json.loads(data.get("main_lifts") or "[]")
        except (TypeError, ValueError):
            data["main_lifts"] = []
        out.append(data)
    return out


def _docs() -> list[dict]:
    files = [ROOT / "USER-GUIDE.md", ROOT / "ROADMAP.md", ROOT / "README.md"]
    docs_dir = ROOT / "docs"
    if docs_dir.is_dir():
        files.extend(sorted(docs_dir.glob("*.md")))
    out = []
    for path in files:
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        title = path.stem.replace("-", " ").title()
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        out.append({"name": rel, "title": title})
    return out


def _number(value):
    if value in (None, ""):
        return None
    return float(value)


def _integer(value):
    if value in (None, ""):
        return None
    number = float(value)
    if number != int(number):
        raise ValueError("integer value expected")
    return int(number)


def _exercise_fields(message: str) -> dict[str, str]:
    """Map the exercise writer's messages to the editor's form fields."""
    text = message.lower()
    if "id must" in text:
        field = "id"
    elif "display" in text:
        field = "display"
    elif "log name" in text:
        field = "log_names"
    elif "pattern" in text:
        field = "pattern"
    elif "primary_muscles" in text:
        field = "primary_muscles"
    elif "vbt_family" in text:
        field = "vbt_family"
    elif "spinal_cost" in text:
        field = "spinal_cost"
    else:
        field = "props"
    return {field: message}


def _manual_set_values(body: dict) -> tuple[int, int | None, float | None, float | None]:
    """Validate one manually entered set; imports keep their own legacy path."""
    try:
        reps = _integer(body.get("reps"))
    except (TypeError, ValueError) as exc:
        raise FieldError("reps must be an integer", {"reps": "must be an integer"}) from exc
    try:
        rir = _integer(body.get("rir"))
    except (TypeError, ValueError) as exc:
        raise FieldError("RIR must be an integer", {"rir": "must be an integer"}) from exc
    try:
        load = _number(body.get("load_kg"))
    except (TypeError, ValueError) as exc:
        raise FieldError("load must be a number", {"load_kg": "must be a number"}) from exc
    try:
        velocity = _number(body.get("velocity"))
    except (TypeError, ValueError) as exc:
        raise FieldError("velocity must be a number", {"velocity": "must be a number"}) from exc
    if reps is None:
        raise FieldError("reps are required", {"reps": "required"})
    if reps < 0:
        raise FieldError("reps cannot be negative", {"reps": "must be non-negative"})
    if rir is not None and not 0 <= rir <= 6:
        raise FieldError("RIR must be 0-6", {"rir": "must be 0-6"})
    if load is not None and load < 0:
        raise FieldError("load cannot be negative", {"load_kg": "must be non-negative"})
    if velocity is not None and velocity < 0:
        raise FieldError("velocity cannot be negative", {"velocity": "must be non-negative"})
    return reps, rir, load, velocity


def _field_call(fn, field: str, *args, **kwargs):
    """Run one validator and turn its message into a field-scoped 400."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise FieldError(str(exc), {field: str(exc)}) from exc


def _list(value, default=None) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return list(default or [])


def _int_or_none(value):
    return None if value in (None, "") else int(value)


def _truth(value) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _settled(value):
    if value in (None, "", "unknown"):
        return None
    return _truth(value)



_PROGRAMME_JOBS: dict[str, dict[str, Any]] = {}
_PROGRAMME_JOBS_LOCK = threading.Lock()
_READ_CACHE: dict[tuple, dict] = {}
_READ_CACHE_LOCK = threading.Lock()
_READ_CACHE_MAX = 16


def _db_stamp(path: str | Path) -> tuple[int, int]:
    stat = Path(path).stat()
    return stat.st_mtime_ns, stat.st_size


def _cache_get(key: tuple) -> dict | None:
    with _READ_CACHE_LOCK:
        return _READ_CACHE.get(key)


def _cache_set(key: tuple, value: dict) -> None:
    with _READ_CACHE_LOCK:
        _READ_CACHE[key] = value
        while len(_READ_CACHE) > _READ_CACHE_MAX:
            _READ_CACHE.pop(next(iter(_READ_CACHE)))
_PROGRAMME_JOB_TTL_SECONDS = 3600
_PROGRAMME_JOB_MAX = 20


MAX_PROGRAMME_WEEKS = 26


def _programme_request(body: dict) -> dict[str, Any]:
    # The UI already bounds the horizon; the API must too, or a huge forecast is a local DoS
    # (DEC-PROGRAMME-09).
    weeks = int(body.get("weeks") or 4)
    if not 1 <= weeks <= MAX_PROGRAMME_WEEKS:
        raise ValueError(
            f"weeks must be between 1 and {MAX_PROGRAMME_WEEKS}, got {weeks}"
        )
    return {
        "start": datetime.date.today().isoformat() if _truth(body.get("remaining"))
        else (body.get("start") or None),
        "weeks": weeks,
        "sessions_per_week": int(body.get("sessions_per_week") or 3),
        "start_session_type": body.get("start_session_type") or None,
        "apply_selection": _truth(body.get("apply_selection")),
        "selection_llm": _truth(body.get("selection_llm")),
        "selection_confirmed": _truth(body.get("selection_confirmed")),
    }


def programme_payload(conn, body: dict) -> dict:
    request = _programme_request(body)
    chooser = (
        agent_selection.chooser(build_client(load_settings()))
        if request["apply_selection"] and request["selection_llm"] else None
    )
    pages = programme_feature.build_programme(
        conn,
        start=request["start"],
        weeks=request["weeks"],
        per_week=request["sessions_per_week"],
        start_session_type=request["start_session_type"],
        apply_deload=True,
        apply_selection=request["apply_selection"],
        selection_chooser=chooser,
        selection_confirmed=request["selection_confirmed"],
    )
    return {"entries": [
        {"date": entry.on_date,
         "session_type": entry.session_type,
         "deload_reason": entry.deload_reason,
         "deload_suggestion": entry.deload_suggestion,
         "deload_applied": entry.deload_applied,
         "prescription": prescription_dict(entry.prescription)}
        for entry in pages
    ]}


def _database_revision(conn) -> list[list[str | int]]:
    """Cheap fingerprint of the live database files for the programme cache.

    Hashing every history row would make the key as expensive as the build. SQLite writes
    update the database or WAL file metadata, so size/mtime is enough to stop a cached
    forecast surviving newly imported sessions, readiness or profile state. The `-shm` file
    is deliberately excluded: it changes on ordinary reads and would defeat the cache.
    """
    row = conn.execute("PRAGMA database_list").fetchone()
    path = str(row[2]) if row and row[2] else ""
    if not path:
        return []
    revision: list[list[str | int]] = []
    for suffix in ("", "-wal"):
        candidate = Path(path + suffix)
        try:
            stat = candidate.stat()
        except FileNotFoundError:
            continue
        revision.append([suffix, stat.st_size, stat.st_mtime_ns])
    return revision


def programme_cache_key(conn, body: dict) -> str:
    request = _programme_request(body)
    day = request["start"] or datetime.date.today().isoformat()
    state = settings_profile.state(conn, day)
    state.pop("history", None)
    material = {
        "version": __version__,
        "request": request,
        "database_revision": _database_revision(conn),
        "profile": state,
        "config": {
            relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for relative in (
                "config/templates/session-types.v1.yaml",
                "config/volume.v1.yaml",
                "config/deload.v1.yaml",
                "config/rules/programme.v1.yaml",
            )
            if (ROOT / relative).is_file()
        },
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _programme_job_cleanup() -> None:
    cutoff = datetime.datetime.now().timestamp() - _PROGRAMME_JOB_TTL_SECONDS
    stale = [
        job_id for job_id, job in _PROGRAMME_JOBS.items()
        if job["created_at"] < cutoff
    ]
    for job_id in stale:
        _PROGRAMME_JOBS.pop(job_id, None)
    while len(_PROGRAMME_JOBS) > _PROGRAMME_JOB_MAX:
        oldest = min(_PROGRAMME_JOBS, key=lambda key: _PROGRAMME_JOBS[key]["created_at"])
        _PROGRAMME_JOBS.pop(oldest, None)


def _run_programme_job(job_id: str, db_path, body: dict) -> None:
    try:
        with db.Store(db_path) as store:
            result = programme_payload(store.connection, body)
        with _PROGRAMME_JOBS_LOCK:
            if job_id in _PROGRAMME_JOBS:
                _PROGRAMME_JOBS[job_id].update(status="done", result=result)
    except Exception as exc:  # expected validation failures are returned to the poller
        with _PROGRAMME_JOBS_LOCK:
            if job_id in _PROGRAMME_JOBS:
                _PROGRAMME_JOBS[job_id].update(status="error", error=str(exc))


MAX_RUNNING_PROGRAMME_JOBS = 1


def start_programme_job(db_path, body: dict) -> dict:
    _programme_request(body)  # validate the horizon before spending a thread
    with _PROGRAMME_JOBS_LOCK:
        _programme_job_cleanup()
        running = sum(
            1 for job in _PROGRAMME_JOBS.values() if job["status"] == "running"
        )
        if running >= MAX_RUNNING_PROGRAMME_JOBS:
            # A forecast is CPU-bound and reads the same database; queueing duplicates only
            # makes both slower (DEC-PROGRAMME-09).
            raise RequestError(409, "a programme forecast is already running")
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "status": "running",
        "created_at": datetime.datetime.now().timestamp(),
        "result": None,
        "error": None,
    }
    with _PROGRAMME_JOBS_LOCK:
        _PROGRAMME_JOBS[job_id] = job
    threading.Thread(
        target=_run_programme_job, args=(job_id, db_path, body), daemon=True,
    ).start()
    return job


def programme_job(job_id: str) -> dict:
    with _PROGRAMME_JOBS_LOCK:
        _programme_job_cleanup()
        job = _PROGRAMME_JOBS.get(job_id)
        if job is None:
            raise KeyError("programme job not found")
        return dict(job)


class ReadinessRequired(Exception):
    """The date needs a usable readiness score before a workout is generated."""


def analysis_readonly_connection(db_path: str | Path) -> sqlite3.Connection:
    """Dedicated read-only connection for the monitoring-analysis endpoint."""
    path = Path(db_path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


class Handler(BaseHTTPRequestHandler):
    db_path: str | Path | None = None
    server_version = "strength-coach-web"

    # --- plumbing ---------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:
        message = f"{self.address_string()} - {fmt % args}"
        LOGGER.info(message)
        print(message)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if getattr(self, "close_connection", False):
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, default=_json_default).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str, fields: dict[str, str] | None = None) -> None:
        payload: dict[str, Any] = {"error": message}
        if fields:
            payload["fields"] = fields
        self._json(status, payload)

    def _body(self) -> dict:
        if self.headers.get("Transfer-Encoding"):
            raise RequestError(400, "Transfer-Encoding is not supported", close=True)
        values = self.headers.get_all("Content-Length") or []
        if not values:
            raise RequestError(411, "Content-Length is required", close=True)
        if len(values) != 1:
            raise RequestError(400, "multiple Content-Length headers", close=True)
        raw_length = values[0].strip()
        if (not raw_length or len(raw_length) > 20
                or not raw_length.isascii() or not raw_length.isdigit()):
            raise RequestError(400, "invalid Content-Length", close=True)
        length = int(raw_length)
        if length > MAX_BODY_BYTES:
            raise RequestError(413, "request body too large", close=True)
        media_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            # A text/plain body is a browser "simple request" that skips the CORS preflight,
            # so accepting it would bypass the origin check instead of complementing it.
            raise RequestError(415, "Content-Type must be application/json", close=True)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestError(400, "incomplete request body", close=True)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RequestError(400, "invalid JSON body") from None
        if not isinstance(data, dict):
            raise RequestError(400, "JSON body must be an object")
        return data

    def _with_conn(self, fn):
        store = db.Store(self.db_path)
        try:
            return fn(store.connection)
        finally:
            store.close()

    def _with_analysis_conn(self, fn):
        conn = analysis_readonly_connection(self.db_path)
        try:
            return fn(conn)
        finally:
            conn.close()

    def _monitoring_analysis(self, as_of: str) -> dict:
        key = (
            "monitoring-analysis", str(self.db_path), _db_stamp(self.db_path),
            as_of, monitoring_analysis_feature.ANALYSIS_VERSION,
        )
        cached = _cache_get(key)
        if cached is not None:
            return cached
        value = self._with_analysis_conn(
            lambda c: monitoring_analysis_feature.build_analysis(c, as_of=as_of)
        )
        _cache_set(key, value)
        return value

    def _performance_ratios_cached(self, query: dict) -> dict:
        to_date = query.get("to", [datetime.date.today().isoformat()])[0]
        from_date = query.get("from", [to_date])[0]
        relationship_id = query.get("relationship_id", [None])[0]
        key = (
            "performance-ratios", str(self.db_path), _db_stamp(self.db_path),
            from_date, to_date, relationship_id,
        )
        cached = _cache_get(key)
        if cached is not None:
            return cached
        value = self._with_conn(lambda c: self._performance_ratios(c, query))
        _cache_set(key, value)
        return value

    # --- routes -----------------------------------------------------------
    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/":
                self._serve_file(STATIC / "index.html", "text/html; charset=utf-8")
            elif path.startswith("/static/"):
                self._serve_file(STATIC / Path(path).name,
                                 mimetypes.guess_type(path)[0] or "application/octet-stream")
            elif path == "/api/settings":
                self._json(200, self._with_conn(lambda c: self._settings(c)))
            elif path == "/api/settings/monitoring":
                self._json(200, config_inventory.build_inventory())
            elif path == "/api/settings/drop/window":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0] or datetime.date.today().isoformat()
                self._json(200, self._with_conn(
                    lambda c: self._drop_confirmation_window(c, day)
                ))
            elif path == "/api/modalities":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0] or datetime.date.today().isoformat()
                self._json(200, self._with_conn(lambda c: modalities.state(c, day)))
            elif path.startswith("/api/modalities/"):
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0] or datetime.date.today().isoformat()
                module_id = path.rsplit("/", 1)[-1]
                self._json(200, self._with_conn(
                    lambda c: modalities.show(c, module_id, day)
                ))
            elif path == "/api/settings/volume":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0] or datetime.date.today().isoformat()
                self._json(200, self._with_conn(lambda c: self._volume_settings(c, day)))
            elif path == "/api/settings/profile":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0] or datetime.date.today().isoformat()
                self._json(200, self._with_conn(lambda c: settings_profile.state(c, day)))
            elif path == "/api/regime":
                query = parse_qs(urlparse(self.path).query)
                self._json(200, self._with_conn(lambda c: regime_feature.detect(
                    c,
                    weeks=int(query.get("weeks", ["8"])[0]),
                    on_date=query.get("date", [None])[0],
                )))
            elif path == "/api/overview":
                self._json(200, self._with_conn(self._overview))
            elif path == "/api/workout/active":
                self._json(200, self._with_conn(
                    lambda c: {"workout": workout.active_workout(c)}
                ))
            elif path.startswith("/api/workout/") and path.endswith("/summary"):
                workout_id = path[len("/api/workout/"):-len("/summary")].strip("/")
                self._json(200, self._with_conn(
                    lambda c: {"summary": self._summary_or_error(c, workout_id)}
                ))
            elif path.startswith("/api/workout/"):
                workout_id = path.rsplit("/", 1)[-1]
                self._json(200, self._with_conn(
                    lambda c: {"workout": self._workout_or_404(c, workout_id)}
                ))
            elif path == "/api/performance/e1rm":
                query = parse_qs(urlparse(self.path).query)
                self._json(200, self._with_conn(
                    lambda c: self._performance_e1rm(c, query)
                ))
            elif path == "/api/performance/dose":
                query = parse_qs(urlparse(self.path).query)
                self._json(200, self._with_conn(
                    lambda c: self._performance_dose(c, query)
                ))
            elif path == "/api/performance/ratios":
                query = parse_qs(urlparse(self.path).query)
                self._json(200, self._performance_ratios_cached(query))
            elif path == "/api/performance/relationship-options":
                self._json(200, self._relationship_options())
            elif path == "/api/performance/relationships":
                self._json(200, self._relationship_list())
            elif path == "/api/monitoring-analysis":
                query = parse_qs(urlparse(self.path).query)
                as_of = query.get("as_of", [datetime.date.today().isoformat()])[0]
                try:
                    datetime.date.fromisoformat(as_of)
                except ValueError as exc:
                    raise ValueError("as_of must be YYYY-MM-DD") from exc
                self._json(200, self._monitoring_analysis(as_of))
            elif path == "/api/sessions":
                self._json(200, self._with_conn(lambda c: _session_rows(c, 40)))
            elif path == "/api/history":
                query = parse_qs(urlparse(self.path).query)
                self._json(200, self._with_conn(lambda c: history.list_sessions(
                    c, limit=int(query.get("limit", ["50"])[0]),
                    offset=int(query.get("offset", ["0"])[0]),
                    start=query.get("start", [None])[0],
                    end=query.get("end", [None])[0],
                )))
            elif path.startswith("/api/history/"):
                session_id = path.rsplit("/", 1)[-1]
                self._json(200, self._with_conn(
                    lambda c: history.detail(c, session_id)
                ))
            elif path == "/api/calibrate":
                self._json(200, self._with_conn(self._calibrate))
            elif path == "/api/readiness/shadow":
                self._json(200, self._with_conn(
                    lambda c: {"text": readiness_baseline.report(c)}
                ))
            elif path == "/api/readiness/calibrate":
                self._json(200, self._with_conn(
                    lambda c: {"text": readiness_calibration.report(c)}
                ))
            elif path == "/api/state":
                self._json(200, self._with_conn(self._state))
            elif path == "/api/cardio":
                query = parse_qs(urlparse(self.path).query)
                weeks = int(query.get("weeks", ["12"])[0])
                on_date = query.get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: self._cardio(c, {"weeks": weeks, "date": on_date})
                ))
            elif path == "/api/breaks":
                self._json(200, self._with_conn(self._breaks))
            elif path == "/api/measurements":
                self._json(200, self._with_conn(self._measurements))
            elif path == "/api/fatigue":
                day = parse_qs(urlparse(self.path).query).get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: self._fatigue(c, day)
                ))
            elif path == "/api/continuity":
                day = parse_qs(urlparse(self.path).query).get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: self._continuity(c, day)
                ))
            elif path == "/api/volume":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0]
                weeks = int(query.get("weeks", ["4"])[0])
                self._json(200, self._with_conn(
                    lambda c: self._volume(c, day, weeks)
                ))
            elif path == "/api/exposure":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0] or datetime.date.today().isoformat()
                self._json(200, self._with_conn(
                    lambda c: exposure_ratio_feature.compute(c, day).as_dict()
                ))
            elif path == "/api/shadow":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0] or datetime.date.today().isoformat()
                window = query.get("window_days", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: shadow_report_feature.report(
                        c, day, window_days=None if window in (None, "") else int(window)
                    ).as_dict()
                ))
            elif path == "/api/residual":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0] or datetime.date.today().isoformat()
                window = int(query.get("window_days", ["84"])[0])
                self._json(200, self._with_conn(
                    lambda c: residual_feature.compute(
                        c, day, window_days=window
                    ).as_dict()
                ))
            elif path == "/api/volume/budget":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0] or datetime.date.today().isoformat()
                self._json(200, self._with_conn(
                    lambda c: volume_budget_mod.report(c, day)
                ))
            elif path == "/api/rep-velocity":
                query = parse_qs(urlparse(self.path).query)
                session_id = query.get("session", [None])[0]
                if not session_id:
                    raise ValueError("session is required")
                self._json(200, self._with_conn(
                    lambda c: rep_velocity.session_report(c, session_id)
                ))
            elif path == "/api/rep-velocity/analysis":
                query = parse_qs(urlparse(self.path).query)
                weeks = int(query.get("weeks", ["12"])[0])
                day = query.get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: rep_velocity.analysis_report(c, on_date=day, weeks=weeks)
                ))
            elif path == "/api/progress":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: progress_feature.dashboard(c, day)
                ))
            elif path == "/api/validation":
                query = parse_qs(urlparse(self.path).query)
                max_dates = int(query.get("max_dates", ["12"])[0])
                self._json(200, self._with_conn(
                    lambda c: {"text": retrospective_validation.report(c, max_dates=max_dates)}
                ))
            elif path == "/api/reviews":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: reviews_feature.status(c, day or datetime.date.today().isoformat())
                ))
            elif path == "/api/readiness/feedback":
                query = parse_qs(urlparse(self.path).query)
                weeks = int(query.get("weeks", ["12"])[0])
                day = query.get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: readiness_feedback.report(c, weeks=weeks, on_date=day)
                ))
            elif path == "/api/prospective":
                query = parse_qs(urlparse(self.path).query)
                weeks = int(query.get("weeks", ["8"])[0])
                day = query.get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: prospective_feature.report(c, weeks=weeks, on_date=day)
                ))
            elif path == "/api/form-trend":
                query = parse_qs(urlparse(self.path).query)
                self._json(200, self._with_conn(lambda c: form_assessment_feature.report(
                    c,
                    weeks=int(query.get("weeks", ["12"])[0]),
                    on_date=query.get("date", [None])[0],
                )))
            elif path == "/api/outcomes":
                query = parse_qs(urlparse(self.path).query)
                weeks = int(query.get("weeks", ["8"])[0])
                day = query.get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: outcomes_feature.report(c, weeks=weeks, on_date=day)
                ))
            elif path == "/api/exposures":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [None])[0] or datetime.date.today().isoformat()
                self._json(200, self._with_conn(
                    lambda c: exposure_feature.status(c, day).as_dict()
                ))
            elif path == "/api/substitution":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [datetime.date.today().isoformat()])[0]
                session_type = query.get("session_type", ["squat"])[0]
                if session_type not in templates.SESSION_TYPES:
                    self._json(400, {"error": f"unknown session type {session_type!r}"})
                else:
                    self._json(200, self._with_conn(
                        lambda c: fatigue_selection.suggest(c, day, session_type).as_dict()
                    ))
            elif path == "/api/selection":
                query = parse_qs(urlparse(self.path).query)
                day = query.get("date", [datetime.date.today().isoformat()])[0]
                session_type = query.get("session_type", [None])[0]
                use_llm = query.get("llm", ["0"])[0] == "1"
                include_different = query.get("include_different", ["0"])[0] == "1"
                self._json(200, self._with_conn(
                    lambda c: self._selection(
                        c, day, session_type, use_llm, include_different
                    )
                ))
            elif path.startswith("/api/programme/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                try:
                    job = programme_job(job_id)
                except KeyError as exc:
                    self._error(404, str(exc.args[0]))
                else:
                    self._json(200, job)
            elif path == "/api/logs":
                query = parse_qs(urlparse(self.path).query)
                limit = max(1, min(500, int(query.get("limit", ["200"])[0])))
                with _LOG_LOCK:
                    records = list(_LOG_BUFFER)[-limit:]
                self._json(200, {"logs": records})
            elif path == "/api/options":
                self._json(200, options_mod.canonical_options())
            elif path == "/api/exercises/catalog":
                catalogue = demands_feature.load()
                payload = exercise_admin.catalog()
                for row in payload["entities"]:
                    row["demands"] = {
                        "rated": catalogue.in_scope_rated(row["id"]),
                        "dimensions": catalogue.profile(row["id"]),
                    }
                payload["demand_catalogue"] = {
                    "digest": catalogue.digest,
                    "reviewed_on": catalogue.reviewed_on,
                    "overlay": catalogue.overlay_path is not None,
                    "in_scope": list(demands_feature.IN_SCOPE),
                }
                self._json(200, payload)
            elif path == "/api/exercises":
                self._json(200, [
                    {"id": key, "display": str(value.get("display") or key),
                     "pattern": value.get("pattern")}
                    for key, value in exercises.taxonomy().entities.items()
                ])
            elif path == "/api/templates":
                source = paths.session_types_yaml()
                doc = ROOT / "docs" / "STRENGTH-PROGRAM-REVIEW.md"
                current = programme_summary.extract(doc.read_text(encoding="utf-8"))
                self._json(200, {
                    "yaml": source.read_text(encoding="utf-8"),
                    "path": str(source.relative_to(ROOT)),
                    "docs": "docs/SESSION-TEMPLATES.md",
                    "summary_stale": current != programme_summary.render(),
                })
            elif path == "/api/docs":
                self._json(200, _docs())
            elif path.startswith("/api/docs/"):
                self._json(200, self._doc(path[len("/api/docs/"):]))
            elif path.startswith("/docs/"):
                self._doc_page(path[len("/docs/"):])
            elif path.startswith("/api/review/"):
                session = path[len("/api/review/"):]
                self._json(200, self._with_conn(lambda c: self._review_sheet(c, session)))
            elif path == "/api/readiness/presets":
                source = paths.config_dir("readiness-presets.v1.yaml")
                self._json(200, {
                    "yaml": source.read_text(encoding="utf-8"),
                    "path": str(source.relative_to(ROOT)),
                    "presets": readiness_feature.presets(),
                })
            elif path.startswith("/api/readiness/"):
                day = path[len("/api/readiness/"):]
                self._json(200, self._with_conn(lambda c: self._readiness(c, day)))
            else:
                self._error(404, "not found")
        except ReadinessRequired as exc:
            self._error(409, str(exc))
        except workout.WorkoutNotCompleted as exc:
            self._error(409, str(exc))
        except UnknownSessionError as exc:
            self._error(404, str(exc))
        except (ValueError, KeyError) as exc:
            self._error(400, str(exc))
        except Exception:
            LOGGER.exception("unhandled GET %s", self.path)
            self._error(500, "internal server error")

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            body = self._body()
            if path == "/api/import":
                self._json(200, self._with_conn(lambda c: self._import(c, body)))
            elif path == "/api/workout/start":
                self._json(200, self._with_conn(lambda c: self._workout_start(c, body)))
            elif path.startswith("/api/workout/"):
                self._json(200, self._with_conn(lambda c: self._workout_action(c, path, body)))
            elif path.startswith("/api/history/") and path.endswith("/edit"):
                session_id = path[len("/api/history/"):-len("/edit")].strip("/")
                self._json(200, self._with_conn(
                    lambda c: self._edit_history(c, session_id, body)
                ))
            elif path.startswith("/api/history/") and path.endswith("/void"):
                session_id = path[len("/api/history/"):-len("/void")].strip("/")
                self._json(200, self._with_conn(lambda c: history.void_session(
                    c, session_id, reason=body.get("reason"),
                    unvoid=bool(body.get("unvoid", False)),
                )))
            elif path.startswith("/api/history/") and path.endswith("/vbt"):
                session_id = path[len("/api/history/"):-len("/vbt")].strip("/")
                self._json(200, self._with_conn(lambda c: history.apply_vbt(
                    c, session_id, body.get("sets") or [], reason=body.get("reason"),
                )))
            elif path == "/api/performance/relationships":
                self._json(200, self._add_relationship(body))
            elif path.startswith("/api/performance/relationships/"):
                parts = path.strip("/").split("/")
                if len(parts) != 5:
                    raise ValueError("unknown relationship action")
                relationship_id, action = parts[3], parts[4]
                self._json(200, self._relationship_action(relationship_id, action, body))
            elif path == "/api/reviews":
                self._json(200, self._with_conn(lambda c: self._save_review_task(c, body)))
            elif path == "/api/readiness/feedback":
                query = parse_qs(urlparse(self.path).query)
                weeks = int(query.get("weeks", ["12"])[0])
                day = query.get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: readiness_feedback.report(c, weeks=weeks, on_date=day)
                ))
            elif path == "/api/prospective":
                query = parse_qs(urlparse(self.path).query)
                weeks = int(query.get("weeks", ["8"])[0])
                day = query.get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: prospective_feature.report(c, weeks=weeks, on_date=day)
                ))
            elif path == "/api/form-trend":
                query = parse_qs(urlparse(self.path).query)
                self._json(200, self._with_conn(lambda c: form_assessment_feature.report(
                    c,
                    weeks=int(query.get("weeks", ["12"])[0]),
                    on_date=query.get("date", [None])[0],
                )))
            elif path == "/api/outcomes":
                query = parse_qs(urlparse(self.path).query)
                weeks = int(query.get("weeks", ["8"])[0])
                day = query.get("date", [None])[0]
                self._json(200, self._with_conn(
                    lambda c: outcomes_feature.report(c, weeks=weeks, on_date=day)
                ))
            elif path == "/api/exposures":
                self._json(200, self._with_conn(lambda c: self._save_exposure(c, body)))
            elif path == "/api/settings/llm":
                self._json(200, self._save_llm_settings(body))
            elif path == "/api/settings/drop":
                self._json(200, self._with_conn(lambda c: self._save_drop_settings(c, body)))
            elif path == "/api/settings/volume":
                self._json(200, self._with_conn(lambda c: self._save_volume_settings(c, body)))
            elif path == "/api/settings/profile":
                self._json(200, self._with_conn(lambda c: self._save_settings_profile(c, body)))
            elif path.startswith("/api/modalities/"):
                module_id = path.rsplit("/", 1)[-1]
                self._json(200, self._with_conn(
                    lambda c: self._save_modality(c, module_id, body)
                ))
            elif path == "/api/settings/llm/test":
                self._json(200, self._test_llm())
            elif path == "/api/prescribe":
                self._json(200, self._with_conn(lambda c: self._prescribe(c, body)))
            elif path == "/api/readiness/presets":
                text = str(body.get("yaml") or "")
                if not text.strip():
                    raise ValueError("readiness preset YAML is empty")
                presets = readiness_feature.validate_presets_text(text)
                _write_readiness_presets(text)
                self._json(200, {"ok": True, "presets": presets})
            elif path == "/api/readiness":
                self._json(200, self._with_conn(lambda c: self._set_readiness(c, body)))
            elif path == "/api/readiness/override":
                self._json(200, self._with_conn(lambda c: self._set_readiness_override(c, body)))
            elif path == "/api/readiness/preset":
                self._json(200, self._with_conn(lambda c: self._set_readiness_preset(c, body)))
            elif path == "/api/readiness/context":
                self._json(200, self._with_conn(lambda c: self._set_readiness_context(c, body)))
            elif path == "/api/readiness/settings":
                self._json(200, self._with_conn(lambda c: self._set_readiness_settings(c, body)))
            elif path == "/api/readiness/volume":
                self._json(200, self._with_conn(lambda c: self._set_readiness_volume(c, body)))
            elif path == "/api/programme/key":
                self._json(200, {"cache_key": self._with_conn(
                    lambda c: programme_cache_key(c, body)
                )})
            elif path == "/api/programme/jobs":
                job = start_programme_job(self.db_path, body)
                self._json(202, job)
            elif path == "/api/programme":
                self._json(200, self._with_conn(lambda c: self._programme(c, body)))
            elif path == "/api/cardio":
                self._json(200, self._with_conn(lambda c: self._save_cardio(c, body)))
            elif path == "/api/measurements":
                self._json(200, self._with_conn(
                    lambda c: self._save_measurement(c, body)
                ))
            elif path == "/api/continuity/settings":
                value = _truth(body.get("allow_relax_fixed"))
                cfg = continuity_calibration.save_allow_relax_fixed(value)
                self._json(200, {"allow_relax_fixed": cfg.allow_relax_fixed})
            elif path == "/api/templates/restore":
                backups = sorted(TEMPLATE_BACKUPS.glob("session-types-*.yaml"))
                if not backups:
                    raise ValueError("no template backup is available")
                text = backups[-1].read_text(encoding="utf-8")
                templates.validate_text(text)
                _write_template(text)
                templates._parse_session_template.cache_clear()
                self._json(200, {"ok": True, "restored": backups[-1].name})
            elif path == "/api/templates/summary":
                doc = ROOT / "docs" / "STRENGTH-PROGRAM-REVIEW.md"
                original = doc.read_text(encoding="utf-8")
                doc.write_text(
                    programme_summary.replace(original, programme_summary.render()),
                    encoding="utf-8",
                )
                self._json(200, {"ok": True})
            elif path == "/api/templates":
                text = str(body.get("yaml") or "")
                if not text.strip():
                    raise ValueError("template YAML is empty")
                raw = templates.validate_text(text)
                taxonomy = exercises.taxonomy()
                known = set(taxonomy.entities)
                unknown = sorted({
                    exercise_id
                    for block in (raw.get("session_types") or {}).values()
                    for slot in ((block or {}).get("prescription") or {}).get("slots") or []
                    for exercise_id in ([slot.get("exercise")] + list(slot.get("exercise_variants") or []))
                    if exercise_id and str(exercise_id) not in known
                })
                if unknown:
                    raise ValueError("unknown exercise ids: " + ", ".join(map(str, unknown)))
                _write_template(text)
                templates._parse_session_template.cache_clear()
                self._json(200, {"ok": True, "path": str(paths.session_types_yaml().relative_to(ROOT))})
            elif path == "/api/exercises/demands":
                self._json(200, self._rate_demand(body))
            elif path == "/api/exercises":
                entity_id = str(body.get("id") or "").strip()
                props = body.get("props") or {}
                roles = props.get("day_roles") or []
                invalid = sorted(set(map(str, roles)) - set(templates.SESSION_TYPES))
                if invalid:
                    raise ValueError(
                        "day_roles must be canonical session types: "
                        + ", ".join(templates.SESSION_TYPES)
                    )
                try:
                    payload = exercise_admin.save(entity_id, props)
                except ValueError as exc:
                    raise FieldError(str(exc), _exercise_fields(str(exc))) from exc
                self._json(200, payload)
            elif path == "/api/state/profile":
                self._json(200, self._with_conn(lambda c: self._save_profile(c, body)))
            elif path == "/api/state/constraint":
                self._json(200, self._with_conn(lambda c: self._save_constraint(c, body)))
            elif path == "/api/state/suitability":
                self._json(200, self._with_conn(lambda c: self._save_suitability(c, body)))
            elif path == "/api/state/e1rm":
                self._json(200, self._with_conn(lambda c: self._save_e1rm(c, body)))
            elif path == "/api/state/symptom":
                self._json(200, self._with_conn(lambda c: self._save_symptom(c, body)))
            elif path == "/api/state/block":
                self._json(200, self._with_conn(lambda c: self._save_block(c, body)))
            elif path == "/api/state/break":
                self._json(200, self._with_conn(lambda c: self._save_break(c, body)))
            elif path == "/api/state/break/cancel":
                self._json(200, self._with_conn(lambda c: self._cancel_break(c, body)))
            elif path == "/api/state/test":
                self._json(200, self._with_conn(lambda c: self._save_test(c, body)))
            elif path.startswith("/api/review/"):
                session = path[len("/api/review/"):]
                self._json(200, self._with_conn(lambda c: self._save_review(c, session, body)))
            else:
                self._error(404, "not found")
        except ReadinessRequired as exc:
            self._error(409, str(exc))
        except UnknownSessionError as exc:
            self._error(404, str(exc))
        except RequestError as exc:
            if exc.close:
                self.close_connection = True
            self._error(exc.status, exc.message)
        except FieldError as exc:
            self._error(400, str(exc), exc.fields)
        except (ValueError, KeyError) as exc:
            self._error(400, str(exc))
        except Exception:
            LOGGER.exception("unhandled POST %s", self.path)
            self._error(500, "internal server error")

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._error(404, "not found")
            return
        self._send(200, path.read_bytes(), content_type)

    def _settings(self, conn=None) -> dict:
        drop = volume_settings.load_drop()
        if conn is not None:
            day = datetime.date.today().isoformat()
            state = settings_profile.state(conn, day)
            budget = state["budget"]
            drop = {
                "enabled": bool(budget.get("drop_enabled")),
                "competition_confirm_days": budget.get("drop_competition_confirm_days"),
                "max_slots_per_group": budget.get("drop_max_slots_per_group"),
                "technique_minutes": budget.get("drop_technique_minutes"),
                "tolerance": budget.get("tolerance"),
                "high_band": budget.get("high_band"),
                "slots": budget.get("drop_slots") or {},
                "source": "profile" if state.get("profile_id") is not None
                else drop.get("source"),
            }
        return {
            "llm": describe(),
            "llm_config_path": str(config_path()),
            "database": str(self.db_path or db.default_db_path()),
            "version": __version__,
            "providers": list(PROVIDERS),
            "drop": drop,
            "registry": [
                {
                    "key": setting.key, "group": setting.group,
                    "label": setting.label, "kind": setting.kind,
                    "default": setting.default, "source": setting.source,
                    "classification": setting.classification,
                    "description": setting.description,
                    "minimum": setting.minimum, "maximum": setting.maximum,
                    "choices": list(setting.choices),
                }
                for setting in settings_registry.SETTINGS
            ],
            "local_only": True,
        }

    def _drop_confirmation_window(self, conn, day: str) -> dict:
        """The single server-side answer for whether the Prescribe checkbox applies."""
        profile = dict(queries.athlete_profile(conn) or {})
        cfg = volume_budget_mod.BudgetConfig.load(conn=conn, on_date=day)
        active = volume_budget_mod.drop_mode_active(profile, cfg)
        window = volume_budget_mod.drop_competition_window(
            profile, day, cfg.drop_competition_confirm_days
        )
        applies = bool(active and window["in_window"])
        reason = (
            "confirmation required" if applies
            else "drop mode is not active" if not active
            else window["reason"]
        )
        return {
            "date": day,
            "applies": applies,
            "drop_mode_active": active,
            "in_window": window["in_window"],
            "days_until": window["days_until"],
            "window_days": window["window_days"],
            "competition_date": window["competition_date"],
            "reason": reason,
        }

    def _volume_settings(self, conn, day: str) -> dict:
        cfg = volume_budget_mod.BudgetConfig.load(conn=conn, on_date=day)
        state = settings_profile.state(conn, day)
        policy = {
            key: value for key, value in state["resolved"].items()
            if key.startswith("volume.")
        }
        policy_overrides = {
            key: value for key, value in state["overrides"].items()
            if key.startswith("volume.")
        }
        athlete = dict(queries.athlete_profile(conn) or {})
        overlay = paths.config_dir("volume.v1.yaml").with_name("volume.local.yaml")
        budget_overrides = settings_profile.budget_overrides(conn, day)
        if budget_overrides or policy_overrides:
            source = "profile"
        elif overlay.is_file():
            source = "local overlay"
        else:
            source = "config"
        warnings = []
        if overlay.is_file():
            warnings.append(
                "config/volume.local.yaml is present. Profile values override it, but it still "
                "supplies any values the profile does not set."
            )
        return {
            "date": day,
            "source": source,
            "budget": cfg.as_config_dict(),
            "policy": policy,
            "policy_overrides": policy_overrides,
            "athlete": {
                "volume_budget_enabled": bool(athlete.get("volume_budget_enabled", 0)),
                "main_lift_policy": str(athlete.get("main_lift_policy") or "preserve"),
                "sessions_per_week_target": athlete.get("sessions_per_week_target"),
                "max_session_minutes": athlete.get("max_session_minutes"),
            },
            "profile": {
                "profile_id": state.get("profile_id"),
                "effective_from": state.get("effective_from"),
                "reason": state.get("reason"),
            },
            "high_band": round(cfg.total_target() * (1.0 + cfg.tolerance), 1),
            "has_local_overlay": overlay.is_file(),
            "warnings": warnings,
        }

    @staticmethod
    def _merge_volume_budget(base: dict, patch: dict) -> None:
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                Handler._merge_volume_budget(base[key], value)
            else:
                base[key] = value

    @staticmethod
    def _volume_mapping_changed(current, candidate) -> bool:
        left = {str(key): float(value) for key, value in (current or {}).items()}
        right = {str(key): float(value) for key, value in (candidate or {}).items()}
        return left.keys() != right.keys() or any(
            abs(left[key] - right[key]) > 1e-9 for key in left
        )

    @classmethod
    def _volume_high_impact_changes(
        cls, current_cfg, candidate_cfg, current_policy: dict, candidate_policy: dict
    ) -> list[str]:
        changes = []
        if cls._volume_mapping_changed(
            current_cfg.weekly_target, candidate_cfg.weekly_target
        ):
            changes.append("weekly targets")
        if cls._volume_mapping_changed(
            current_cfg.weekly_target_effective, candidate_cfg.weekly_target_effective
        ):
            changes.append("effective weekly targets")
        if int(current_cfg.session_cap_total) != int(candidate_cfg.session_cap_total):
            changes.append("session cap")
        if cls._volume_mapping_changed(
            current_cfg.session_cap_pattern, candidate_cfg.session_cap_pattern
        ):
            changes.append("per-pattern session caps")
        if bool(current_policy.get("volume.apply_mrv_cap")) != bool(
            candidate_policy.get("volume.apply_mrv_cap")
        ):
            changes.append("MRV cap")
        current_landmarks = {
            key: value for key, value in current_policy.items()
            if key.startswith("volume.landmarks.")
        }
        candidate_landmarks = {
            key: value for key, value in candidate_policy.items()
            if key.startswith("volume.landmarks.")
        }
        if cls._volume_mapping_changed(current_landmarks, candidate_landmarks):
            changes.append("volume landmarks")
        return changes

    def _save_volume_settings(self, conn, body: dict) -> dict:
        day = str(body.get("effective_from") or datetime.date.today().isoformat())
        try:
            datetime.date.fromisoformat(day)
        except ValueError as exc:
            raise FieldError("effective date must be YYYY-MM-DD", {"effective_from": str(exc)}) from exc
        budget_patch = body.get("budget") or {}
        policy_patch = body.get("policy") or {}
        if not isinstance(budget_patch, dict):
            raise FieldError("budget must be an object", {"budget": "must be an object"})
        if not isinstance(policy_patch, dict):
            raise FieldError("policy must be an object", {"policy": "must be an object"})
        unknown = [
            key for key in policy_patch
            if key not in settings_registry.BY_KEY or not str(key).startswith("volume.")
        ]
        if unknown:
            raise FieldError(
                f"unknown volume setting(s): {', '.join(sorted(unknown))}",
                {"policy": f"unknown: {', '.join(sorted(unknown))}"},
            )
        reason = str(body.get("reason") or "").strip()
        if not reason:
            raise FieldError("a reason is required for a volume settings change", {"reason": "required"})

        current_cfg = volume_budget_mod.BudgetConfig.load(conn=conn, on_date=day)
        current_budget_overrides = settings_profile.budget_overrides(conn, day)
        merged_budget_overrides = copy.deepcopy(current_budget_overrides)
        self._merge_volume_budget(merged_budget_overrides, budget_patch)
        candidate_budget = copy.deepcopy(current_cfg.as_config_dict())
        self._merge_volume_budget(candidate_budget, budget_patch)
        candidate_cfg = volume_budget_mod.BudgetConfig.load(profile_budget=candidate_budget)
        state = settings_profile.state(conn, day)
        current_policy = {
            key: value for key, value in state["resolved"].items()
            if key.startswith("volume.")
        }
        candidate_policy = {**current_policy, **policy_patch}
        changes = self._volume_high_impact_changes(
            current_cfg, candidate_cfg, current_policy, candidate_policy
        )
        confirm = str(body.get("confirm_text") or "").strip().upper()
        if changes and confirm != "VOLUME":
            raise FieldError(
                f"type VOLUME to confirm changes to {', '.join(changes)}",
                {"confirm_text": "type VOLUME"},
            )
        set_values = dict(policy_patch)
        if merged_budget_overrides:
            set_values["budget"] = merged_budget_overrides
        try:
            settings_profile.save(
                conn,
                set_values=set_values,
                effective_from=day,
                guard_confirmed=True,
                reason=reason,
            )
        except ValueError as exc:
            text = str(exc)
            field = "reason" if "reason" in text else "budget" if "budget" in text else "policy"
            raise FieldError(text, {field: text}) from exc
        return self._volume_settings(conn, day)

    def _save_settings_profile(self, conn, body: dict) -> dict:
        try:
            return settings_profile.save(
                conn,
                set_values=body.get("set") or {},
                unset=list(body.get("unset") or []),
                reset=_truth(body.get("reset")),
                effective_from=str(body.get("effective_from") or datetime.date.today().isoformat()),
                guard_confirmed=_truth(body.get("guard_confirmed")),
                reason=(str(body.get("reason")) if body.get("reason") else None),
            )
        except ValueError as exc:
            text = str(exc)
            if "guarded settings require confirmation" in text:
                field = "guard_confirmed"
            elif "guarded settings require a reason" in text:
                field = "reason"
            else:
                candidates = list((body.get("set") or {}).keys())
                field = next((key for key in candidates if str(key) in text), "settings")
            raise FieldError(text, {field: text}) from exc

    def _save_modality(self, conn, module_id: str, body: dict) -> dict:
        try:
            return modalities.update(
                conn, module_id,
                enabled=(_truth(body.get("enabled")) if "enabled" in body else None),
                factors=body.get("factors") or {},
                guard_confirmed=_truth(body.get("guard_confirmed")),
                reason=(str(body.get("reason")) if body.get("reason") else None),
                effective_from=str(body.get("effective_from") or datetime.date.today().isoformat()),
            )
        except ValueError as exc:
            text = str(exc)
            if "confirmation" in text:
                field = "guard_confirmed"
            elif "reason" in text:
                field = "reason"
            elif "factor" in text:
                field = "factors"
            else:
                field = "settings"
            raise FieldError(text, {field: text}) from exc

    def _save_drop_settings(self, conn, body: dict) -> dict:
        day = datetime.date.today().isoformat()
        current = settings_profile.budget_overrides(conn, day)
        drop = dict(current.get("drop") or {})
        for field, low, high in (
            ("competition_confirm_days", 0, 28),
            ("max_slots_per_group", 1, 4),
            ("technique_minutes", 1, 120),
        ):
            if field in body:
                try:
                    value = int(body[field])
                except (TypeError, ValueError) as exc:
                    raise FieldError(f"{field} must be an integer", {field: "must be an integer"}) from exc
                if not low <= value <= high:
                    raise FieldError(
                        f"{field} must be between {low} and {high}",
                        {field: f"must be between {low} and {high}"},
                    )
                drop[field] = value
        if "slots" in body:
            if not isinstance(body["slots"], dict):
                raise FieldError("slots must be a JSON object", {"slots": "must be an object"})
            drop["slots"] = body["slots"]
        if "enabled" in body:
            drop["enabled"] = _truth(body["enabled"])
        budget = dict(current)
        budget["drop"] = drop
        if "tolerance" in body:
            try:
                tolerance = float(body["tolerance"])
            except (TypeError, ValueError) as exc:
                raise FieldError("tolerance must be a number", {"tolerance": "must be a number"}) from exc
            if not 0 <= tolerance <= 1:
                raise FieldError("tolerance must be between 0 and 1", {"tolerance": "must be 0-1"})
            budget["tolerance"] = tolerance
        settings_profile.save(
            conn, set_values={"budget": budget}, effective_from=day,
        )
        return self._settings(conn)

    def _save_llm_settings(self, body: dict) -> dict:
        try:
            return update_llm_settings(
                enabled=_truth(body.get("enabled")),
                model=str(body.get("model") or ""),
                base_url=str(body.get("base_url") or ""),
                api_key=(str(body["api_key"]) if body.get("api_key") else None),
                clear_api_key=_truth(body.get("clear_api_key")),
                temperature=float(body.get("temperature", 0.2)),
                max_tokens=int(body.get("max_tokens", 700)),
                timeout_s=float(body.get("timeout_s", 30.0)),
            )
        except LLMConfigError as exc:
            text = str(exc)
            field = next(
                (name for name in ("model", "base_url", "temperature", "max_tokens", "timeout_s")
                 if name in text),
                "settings",
            )
            raise FieldError(text, {field: text}) from exc
        except (TypeError, ValueError) as exc:
            raise FieldError(str(exc), {"temperature": str(exc)}) from exc

    def _test_llm(self) -> dict:
        settings = load_settings()
        if not settings.enabled:
            raise ValueError("LLM is disabled or incomplete")
        client = build_client(settings)
        try:
            response = client.complete(
                "Reply with the single word: ready.",
                system="You are a connection test. Reply only with the requested word.",
            )
        except LLMError as exc:
            raise ValueError(str(exc)) from exc
        return {
            "ok": True,
            "model": response.model,
            "tokens": response.tokens,
            "text": response.text[:200],
        }

    # --- data -------------------------------------------------------------
    def _overview(self, conn) -> dict:
        today = datetime.date.today().isoformat()
        profile = queries.athlete_profile(conn)
        context = RuleContext.from_store(conn, end=today)
        readiness = queries.readiness_day(conn, today)
        signal = injury_signal.compute(
            conn, today, ramp_week=context.block_week_index
        ).as_dict()
        return {
            "today": today,
            "profile": dict(profile) if profile else None,
            "block_week": context.block_week_index,
            "readiness": readiness,
            "readiness_score": readiness_score.compute(conn, today).as_dict(),
            "cardio": cardio_feature.compute(conn, weeks=4).as_dict(),
            "injury_signal": signal,
            "unreviewed": queries.unreviewed_sessions(conn, limit=50),
            "sessions": _session_rows(conn, 12),
            "calibration": self._calibration_status(conn),
            "form_evaluation": form_assessment_feature.followup(conn, as_of=today),
        }

    def _import(self, conn, body: dict) -> dict:
        """Import two uploaded CSV bodies without writing them to disk.

        The browser sends text, not paths: there is no filesystem surface to traverse. The
        raw rows (with their hashes) are the durable record inside SQLite.
        """
        def content(part_name: str) -> tuple[str, str]:
            part = body.get(part_name) or {}
            if not isinstance(part, dict):
                raise ValueError(f"{part_name} must be an object with name and text")
            name = str(part.get("name") or part_name + ".csv")
            text = part.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"{part_name} file is missing or empty")
            if len(text.encode("utf-8")) > MAX_IMPORT_FILE_BYTES:
                raise ValueError(f"{part_name} file is larger than the import limit")
            return name, text

        training_name, training_text = content("training")
        readiness_name, readiness_text = content("readiness")
        training = io_utils.read_raw_csv_text(training_text)
        readiness = io_utils.read_raw_csv_text(readiness_text)
        report = importer.import_export(
            conn, training, readiness,
            training_sha256=hashlib.sha256(training_text.encode("utf-8")).hexdigest(),
            readiness_sha256=hashlib.sha256(readiness_text.encode("utf-8")).hexdigest(),
        )
        return {
            "training_name": training_name,
            "readiness_name": readiness_name,
            "raw_rows_inserted": report.raw_rows_inserted,
            "raw_rows_overlap": report.raw_rows_overlap,
            "clean_sets_inserted": report.clean_sets_inserted,
            "clean_sets_existing": report.clean_sets_existing,
            "sessions_written": report.sessions_written,
            "quarantined": report.quarantined,
            "readiness_days": report.readiness_days,
            "issues": report.issues,
            "window_start": report.window_start,
            "window_end": report.window_end,
        }

    def _workout_or_404(self, conn, workout_id: str) -> dict:
        result = workout.get(conn, workout_id)
        if result is None:
            raise ValueError("workout not found")
        return result

    def _performance_e1rm(self, conn, query: dict) -> dict:
        exercise_id = query.get("exercise_id", [None])[0]
        if not exercise_id:
            raise ValueError("exercise_id is required")
        to_date = query.get("to", [datetime.date.today().isoformat()])[0]
        from_date = query.get("from", ["1900-01-01"])[0]
        session_type = query.get("session_type", [None])[0] or None
        include_deloads = str(query.get("include_deloads", ["false"])[0]).lower() in {
            "1", "true", "yes", "on"
        }
        min_quality = str(query.get("quality", ["ok"])[0]).lower()
        if min_quality not in {"ok", "degraded"}:
            raise ValueError("quality must be ok or degraded")
        points = strength_trend_feature.observations(
            conn, exercise_id, from_date, to_date,
            session_type=session_type, include_deloads=include_deloads,
        )
        trend = strength_trend_feature.rolling_median(points)
        degraded = (
            strength_trend_feature.degraded_observations(
                conn, exercise_id, from_date, to_date,
                session_type=session_type, include_deloads=include_deloads,
            )
            if min_quality == "degraded" else []
        )
        return {
            "exercise_id": exercise_id,
            "from": from_date,
            "to": to_date,
            "filters": {
                "session_type": session_type,
                "include_deloads": include_deloads,
                "quality": min_quality,
            },
            "basis": "raw_formula_epley_rir",
            "decay": "not_applied",
            "calibration": "not_applied",
            "points": [
                {
                    "date": point.date,
                    "kg": round(point.kg, 1),
                    "rolling_median_kg": round(point.rolling_median_kg, 1),
                    "n_window": point.n_window,
                }
                for point in trend
            ],
            "degraded": [
                {
                    "date": point.date,
                    "kg": round(point.estimate.kg, 1),
                    "quality": point.estimate.quality,
                    "reason": "degraded observation; excluded from primary line and median",
                }
                for point in degraded
            ],
            "breaks": [
                {"date": item.date, "reason": item.reason}
                for item in strength_trend_feature.series_breaks(points)
            ],
            "break_detection": {
                "raw_exercise_alias": True,
                "load_basis": True,
                "equipment": False,
                "limitation": "equipment changes are not stored and cannot be detected",
            },
            "summary": strength_trend_feature.summarize(points),
        }

    def _performance_dose(self, conn, query: dict) -> dict:
        to_date = query.get("to", [datetime.date.today().isoformat()])[0]
        from_date = query.get("from", [to_date])[0]
        group_by = query.get("group_by", ["session"])[0]
        if group_by != "session":
            raise ValueError("group_by must be session")
        sets = queries.clean_sets(conn, start=from_date, end=to_date)
        sessions = queries.sessions(conn, start=from_date, end=to_date)
        exposure_config = exposure_ratio_feature.ExposureConfig.load()
        buckets = []
        for _, row in sessions.iterrows():
            session_id = str(row["session_id"])
            group = sets[sets["session_id"].astype(str).eq(session_id)] if not sets.empty else sets
            work = group[group["is_working_set"].fillna(False).astype(bool)] if not group.empty else group
            tonnage = pd.to_numeric(work.get("tonnage_kg"), errors="coerce").dropna().sum() if not work.empty else 0.0
            buckets.append({
                "session_id": session_id,
                "date": str(row["occurred_on"])[:10],
                "session_type": row.get("session_type"),
                "working_sets": int(len(work)),
                "hard_sets": monitoring.hard_sets(work, exposure_config),
                "tonnage_kg": round(float(tonnage), 1),
            })
        return {"from": from_date, "to": to_date, "group_by": "session", "buckets": buckets}

    def _relationship_options(self) -> dict:
        entities = exercises.taxonomy().entities
        choices = [
            {"id": str(key), "label": str(value.get("display") or key)}
            for key, value in entities.items()
            if derived_feature.e1rm_applicable(dict(value))
        ]
        return {
            "relationship_types": list(relative_strength_feature.relationship_types()),
            "exercises": sorted(choices, key=lambda item: item["label"].lower()),
            "criteria": [
                "numerator and denominator are distinct known exercises",
                "both sides support a formula e1RM",
                "the pair is not already configured",
                "max_gap_days is positive",
                "max_age_days is at least max_gap_days",
                "min_observations is at least 2",
                "notes are present; ratios are descriptive only",
            ],
        }

    def _relationship_from_body(
        self, body: dict, relationship_id: str | None = None,
    ) -> relative_strength_feature.Relationship:
        numerator = str(body.get("numerator") or "").strip()
        denominator = str(body.get("denominator") or "").strip()
        entities = exercises.taxonomy().entities
        if numerator not in entities or denominator not in entities:
            raise ValueError("choose two known exercises")
        relationship_type = str(body.get("relationship_type") or "").strip()
        try:
            max_gap_days = int(body.get("max_gap_days", 14))
            max_age_days = int(body.get("max_age_days", 42))
            min_observations = int(body.get("min_observations", 2))
        except (TypeError, ValueError) as exc:
            raise ValueError("gap, age and observation fields must be integers") from exc
        label = str(body.get("label") or "").strip() or (
            f"{entities[numerator].get('display') or numerator} / "
            f"{entities[denominator].get('display') or denominator}"
        )
        notes = str(body.get("notes") or "").strip() or (
            "Descriptive relative performance only; not a weakness diagnosis."
        )
        return relative_strength_feature.Relationship(
            id=relationship_id or f"{numerator}_to_{denominator}",
            label=label,
            numerator=numerator,
            denominator=denominator,
            relationship_type=relationship_type,
            max_gap_days=max_gap_days,
            max_age_days=max_age_days,
            min_observations=min_observations,
            notes=notes,
        )

    @staticmethod
    def _check_relationship_revision(body: dict, *, required: bool) -> None:
        supplied = str(body.get("revision") or "").strip()
        if required and not supplied:
            raise ValueError("revision is required; reload the pair list and retry")
        if supplied and supplied != relative_strength_feature.relationship_config_revision():
            raise RequestError(409, "relationship configuration changed; reload and retry")

    @staticmethod
    def _relationship_payload(
        relationships: list[relative_strength_feature.Relationship],
    ) -> dict:
        records = relative_strength_feature.load_relationships_with_sources()
        canonical_ids = relative_strength_feature.canonical_relationship_ids()
        sources = {
            item.id: {"source": source, "source_kind": kind}
            for item, source, kind in records
        }
        hidden = relative_strength_feature.hidden_relationships()
        return {
            "ok": True,
            "revision": relative_strength_feature.relationship_config_revision(),
            "relationships": [
                {
                    "id": item.id,
                    "label": item.label,
                    "numerator": item.numerator,
                    "denominator": item.denominator,
                    "relationship_type": item.relationship_type,
                    "max_gap_days": item.max_gap_days,
                    "max_age_days": item.max_age_days,
                    "min_observations": item.min_observations,
                    "notes": item.notes,
                    "source": sources.get(item.id, {}).get("source", "canonical config"),
                    "source_kind": sources.get(item.id, {}).get("source_kind", "canonical_config"),
                    "origin": "canonical" if item.id in canonical_ids else "local",
                }
                for item in relationships
            ],
            "hidden": [
                {"id": item.id, "label": item.label, "origin": "canonical",
                 "source": "locally hidden canonical pair", "source_kind": "local_override"}
                for item in hidden
            ],
        }

    def _relationship_list(self) -> dict:
        return self._relationship_payload(relative_strength_feature.load_relationships())

    def _add_relationship(self, body: dict) -> dict:
        self._check_relationship_revision(body, required=True)
        relationship = self._relationship_from_body(body)
        relationships = relative_strength_feature.append_relationship(relationship)
        _READ_CACHE.clear()
        return self._relationship_payload(relationships)

    def _relationship_action(self, relationship_id: str, action: str, body: dict) -> dict:
        self._check_relationship_revision(body, required=True)
        if action == "update":
            relationship = self._relationship_from_body(body, relationship_id)
            relationships = relative_strength_feature.update_relationship(relationship)
        elif action == "delete":
            relationships = relative_strength_feature.delete_relationship(relationship_id)
        elif action == "reset":
            relationships = relative_strength_feature.reset_relationship(relationship_id)
        else:
            raise ValueError("unknown relationship action")
        _READ_CACHE.clear()
        return self._relationship_payload(relationships)

    def _performance_ratios(self, conn, query: dict) -> dict:
        to_date = query.get("to", [datetime.date.today().isoformat()])[0]
        from_date = query.get("from", [to_date])[0]
        relationship_id = query.get("relationship_id", [None])[0]
        relationships = relative_strength_feature.load_relationships()
        selected = [item for item in relationships if relationship_id in (None, item.id)]
        exercise_ids = sorted({
            exercise for item in selected for exercise in (item.numerator, item.denominator)
        })
        lookback_starts = [
            (
                datetime.date.fromisoformat(from_date)
                - datetime.timedelta(days=max(item.max_age_days, item.max_gap_days))
            ).isoformat()
            for item in selected
        ] + [
            (
                datetime.date.fromisoformat(to_date)
                - datetime.timedelta(days=item.max_age_days)
            ).isoformat()
            for item in selected
        ]
        history_start = min(lookback_starts) if lookback_starts else to_date
        sets = queries.clean_sets(conn, start=history_start, end=to_date)
        points_by_exercise = {
            exercise: strength_trend_feature.observations(
                conn, exercise, "1900-01-01", to_date, frame=sets
            )
            for exercise in exercise_ids
        }
        values = []
        for relationship in selected:
            current = relative_strength_feature.current_ratio(
                conn, relationship, to_date, points=points_by_exercise
            )
            values.append({
                "current": current.as_dict() if hasattr(current, "as_dict") else current,
                "trend": relative_strength_feature.ratio_trend(
                    conn, relationship, from_date, to_date,
                    points=points_by_exercise,
                ),
            })
        return {
            "from": from_date,
            "to": to_date,
            "basis": "raw_formula_epley_rir",
            "relationships": values,
        }

    def _summary_or_error(self, conn, workout_id: str) -> dict:
        result = workout.get(conn, workout_id)
        if result is None:
            raise UnknownSessionError("workout not found")
        if result.get("status") != "completed":
            raise workout.WorkoutNotCompleted("workout is not completed")
        return workout.summary(conn, workout_id)

    def _workout_start(self, conn, body: dict) -> dict:
        for_date = str(body.get("date") or datetime.date.today().isoformat())
        plan = body.get("plan")
        readiness = body.get("readiness")
        if not isinstance(readiness, dict):
            raise ValueError("readiness must be an object")
        acknowledge = _truth(body.get("readiness_ack"))
        # Validate ranges first, then persist what was actually supplied so the score reflects
        # this form rather than only yesterday’s stored row. Missing fields stay missing.
        clean = workout.validate_readiness(readiness, allow_partial=True)
        readiness_feature.record_manual(
            conn, for_date, clean, note=body.get("readiness_note") or None
        )
        assessment = readiness_score.compute(conn, for_date)
        if assessment.status != "ready" and not acknowledge:
            raise ValueError(
                "readiness score unavailable; acknowledge starting without a score"
            )
        allow_partial = acknowledge or assessment.status == "ready"
        # Persist the committed plan and start the workout in one transaction. A failed start
        # (including an already-active workout) leaves no orphan prescription.
        conn.execute("BEGIN IMMEDIATE")
        try:
            prescription_id = prescription_persistence.store_plan(conn, plan)
            result = workout.start(
                conn,
                for_date=for_date,
                plan=plan,
                readiness=clean,
                session_type=(plan or {}).get("session_type") if isinstance(plan, dict) else None,
                prescription_id=prescription_id,
                note=body.get("note") or None,
                allow_partial_readiness=allow_partial,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return {"workout": result}

    def _workout_action(self, conn, path: str, body: dict) -> dict:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 4:
            raise ValueError("workout action is required")
        workout_id = parts[2]
        action = parts[3]
        if action == "import":
            if len(parts) > 4 and parts[4] == "undo":
                return {"workout": workout.undo_import(conn, workout_id)}
            imported = workout.import_csv(
                conn, workout_id, str(body.get("text") or ""),
                apply=_truth(body.get("apply")),
                rep_text=str(body.get("rep_text") or "") or None,
            )
            return {"workout": imported["workout"], "preview": imported["preview"]}
        if action == "form":
            return {"workout": workout.set_form_rating(
                conn, workout_id,
                exercise_id=str(body.get("exercise_id") or ""),
                rating=int(body.get("rating")),
                note=body.get("note") or None,
            )}
        if action == "plan":
            sub = parts[4] if len(parts) > 4 else ""
            if sub == "swap":
                result = workout.swap_exercise(
                    conn, workout_id, _integer(body.get("item_index")),
                    str(body.get("exercise_id") or ""),
                )
            elif sub == "add-exercise":
                result = workout.add_exercise(
                    conn, workout_id,
                    exercise_id=str(body.get("exercise_id") or ""),
                    sets=_integer(body.get("sets")) or 3,
                    reps_low=_integer(body.get("reps_low")) or 8,
                    reps_high=_integer(body.get("reps_high")) or 12,
                    load_kg=_number(body.get("load_kg")),
                    rir_target=_integer(body.get("rir_target")),
                )
            elif sub == "remove-exercise":
                result = workout.remove_exercise(
                    conn, workout_id, _integer(body.get("item_index"))
                )
            elif sub == "set-count":
                result = workout.change_sets(
                    conn, workout_id, _integer(body.get("item_index")),
                    _integer(body.get("delta")),
                )
            else:
                raise ValueError("unknown plan action")
        elif action == "sets":
            source = str(body.get("source") or "manual")
            if source == "manual":
                reps, rir, load, velocity = _manual_set_values(body)
            else:
                reps = _integer(body.get("reps"))
                rir = _integer(body.get("rir"))
                load = _number(body.get("load_kg"))
                velocity = _number(body.get("velocity"))
            result = workout.add_set(
                conn, workout_id,
                exercise_id=str(body.get("exercise_id") or ""),
                load_kg=load,
                reps=reps,
                rir=rir,
                velocity=velocity,
                source=source,
                set_index=_integer(body.get("set_index")),
            )
        elif action == "update-set":
            reps, rir, load, velocity = _manual_set_values(body)
            result = workout.update_set(
                conn, workout_id, _integer(body.get("set_id")),
                load_kg=load,
                reps=reps,
                rir=rir,
                velocity=velocity,
            )
        elif action == "remove-set":
            result = workout.remove_set(conn, workout_id, _integer(body.get("set_id")))
        elif action == "end":
            result = workout.end(
                conn, workout_id,
                session_rpe=_number(body.get("session_rpe")),
                not_recorded=_truth(body.get("not_recorded")),
                duration_min=_number(body.get("duration_min")),
                productivity=_integer(body.get("productivity")),
                notes=body.get("notes") or None,
            )
        elif action == "abandon":
            result = workout.abandon(conn, workout_id)
        else:
            raise ValueError("unknown workout action")
        return {"workout": result}

    def _save_review_task(self, conn, body: dict) -> dict:
        task_key = str(body.get("task_key") or "").strip()
        if task_key not in {
            "readiness_thresholds", "exercise_substitution", "fatigue_signals",
            "phase5a_review",
        }:
            raise ValueError("unknown periodic review task")
        action = str(body.get("action") or "completed").strip().lower()
        on_date = str(body.get("date") or datetime.date.today().isoformat())
        decision = body.get("decision") if action == "completed" else None
        note = body.get("note")
        snoozed_until = None
        if action == "snoozed":
            days = int(body.get("snooze_days") or reviews_feature.snooze_days(task_key))
            snoozed_until = (
                datetime.date.fromisoformat(on_date) + datetime.timedelta(days=days)
            ).isoformat()
        repositories.append_maintenance_review(
            conn, task_key=task_key, action=action, reviewed_on=on_date,
            decision=decision, note=note, snoozed_until=snoozed_until,
        )
        return reviews_feature.status(conn, on_date)

    def _prescribe(self, conn, body: dict) -> dict:
        for_date = str(body.get("date") or datetime.date.today().isoformat())
        requested_type = body.get("session_type")
        session_type = (
            schedule_mod.next_session_type(conn, for_date)
            if requested_type in (None, "", "auto") else str(requested_type)
        )
        allow_unknown = _truth(body.get("allow_unknown_readiness"))
        if for_date >= datetime.date.today().isoformat():
            assessment = readiness_score.compute(conn, for_date)
            if assessment.status != "ready" and not allow_unknown:
                raise ReadinessRequired(
                    f"readiness required for {for_date}: {assessment.status} — "
                    f"{assessment.basis}; acknowledge an unknown/partial score to proceed"
                )
        apply_selection = _truth(body.get("apply_selection"))
        selection_confirmed = _truth(body.get("selection_confirmed")) and apply_selection
        selection_llm = _truth(body.get("selection_llm")) and apply_selection
        chooser = (
            agent_selection.chooser(build_client(load_settings()))
            if selection_llm else None
        )
        minimum_session = _truth(body.get("minimum_session"))
        minimum_include_main = _truth(body.get("minimum_include_main")) and minimum_session
        # MOD-TECH-001 is a user request, so it only runs when explicitly asked for; selected
        # patterns narrow it to those movement patterns, and an empty list means main work.
        technique_throttle = _truth(body.get("technique_throttle"))
        raw_patterns = body.get("technique_throttle_pattern")
        if isinstance(raw_patterns, list):
            # An empty string is the UI's "All lifts (main work)" choice. Keep one sentinel
            # so it can be combined with named patterns; only an empty list is the default.
            technique_patterns = list(dict.fromkeys(
                str(value).strip() for value in raw_patterns
            ))
            if technique_patterns == [""] or not technique_patterns:
                technique_patterns = None
        elif isinstance(raw_patterns, str):
            technique_patterns = raw_patterns.strip() or None
        else:
            technique_patterns = None
        target = body.get("target_minutes")
        target_minutes = int(target) if target not in (None, "") else None
        # Resolve deload before building: it must run before minimum session and final
        # validation, not after validation.
        resolved = settings_profile.feature_settings(conn, for_date)
        reactive = deload_feature.reactive_decision(
            conn, for_date, config=resolved.deload
        )
        scheduled = deload_feature.scheduled_decision(
            conn, for_date, config=resolved.deload
        )
        deload_decision = None
        scheduled_suggestion = None
        if reactive is not None:
            deload_decision = reactive
        elif scheduled is not None:
            if _truth(body.get("deload_confirmed")):
                deload_decision = scheduled
            else:
                scheduled_suggestion = scheduled
        prescription = build_prescription(
            conn, for_date=for_date, session_type=session_type,
            apply_selection=apply_selection, selection_chooser=chooser,
            selection_confirmed=selection_confirmed,
            minimum_session=minimum_session,
            minimum_target_minutes=target_minutes,
            minimum_include_main=minimum_include_main,
            deload_decision=deload_decision,
            technique_throttle=technique_throttle,
            technique_throttle_pattern=technique_patterns,
            drop_confirmed=_truth(body.get("drop_confirmed")),
        )
        if scheduled_suggestion is not None:
            prescription = deload_mod.suggest(prescription, scheduled_suggestion)
        return prescription_dict(prescription)

    def _review_sheet(self, conn, session: str) -> dict:
        facts = build_facts(conn, session)
        critique = score_session(conn, session, facts=facts)
        marks = load_marks(conn).sessions.get(session)
        existing = dict(marks.scores) if marks else {}
        workout_data = workout.get(conn, session)
        return {
            "session": session,
            "workout": ({
                "workout_id": workout_data["workout_id"],
                "plan_modified": workout_data.get("plan_modified"),
                "comparison": workout_data.get("comparison"),
                "original_comparison": workout_data.get("original_comparison"),
            } if workout_data else None),
            "occurred_on": facts.occurred_on,
            "session_type": facts.session_type,
            "week": facts.week,
            "week_cost": facts.week_cost,
            "composite": critique.composite,
            "confidence": marks.confidence if marks else "unknown",
            "feedback": queries.session_feedback(conn, session),
            "form_context": form_assessment_feature.review_context(conn, session),
            "items": [
                {
                    "key": item.key,
                    "score": item.score,
                    "measurable": item.measurable,
                    "detail": item.detail,
                    "question": ITEM_GUIDE.get(item.key, ("", ""))[0],
                    "anchors": ITEM_GUIDE.get(item.key, ("", ""))[1],
                    "existing": existing.get(item.key),
                }
                for item in critique.items
            ],
        }

    def _calibration_status(self, conn) -> dict:
        from collections import Counter
        labels = load_marks(conn)
        report = backtest(conn, labels, tolerance=TOLERANCE)
        high = {
            str(row["session_id"]): int(row["n"])
            for row in conn.execute(
                "SELECT session_id, COUNT(DISTINCT item) AS n FROM rubric_mark "
                "WHERE confidence = 'high' AND rubric_version = ? GROUP BY session_id",
                (RUBRIC_VERSION,),
            )
        }
        marks = Counter()
        for row in conn.execute(
            "SELECT item, COUNT(DISTINCT session_id) AS n FROM rubric_mark "
            "WHERE confidence = 'high' AND rubric_version = ? GROUP BY item",
            (RUBRIC_VERSION,),
        ):
            marks[str(row["item"])] = int(row["n"])
        comparable = Counter(str(item.key) for item in report.comparable_items)
        items = []
        for key in ITEM_KEYS:
            items.append({
                "item": key,
                "marks": marks.get(key, 0),
                "comparable": comparable.get(key, 0),
                "status": "ready" if marks.get(key, 0) >= 10 and comparable.get(key, 0) >= 10
                          else "collect",
            })
        gaps = [item["item"] for item in items if item["status"] != "ready"]
        return {
            "high_sessions": len(high),
            "excluded_sessions": labels.excluded_sessions,
            "excluded_versions": dict(labels.excluded_rubric_versions),
            "rubric_version": RUBRIC_VERSION,
            "comparable_items": len(report.comparable_items),
            "agreement": (round(report.agreement_rate * 100, 1)
                          if report.agreement_rate is not None else None),
            "mae": (round(report.mean_abs_error, 3)
                    if report.mean_abs_error is not None else None),
            "items": items,
            "gaps": gaps,
            "next_action": (
                "Use live Workout mode and the optional per-rep CSV to build comparable "
                "progression, essential-work, duration and velocity-loss scores; then review "
                "the rubric. Do not retune from labels alone."
            ),
        }

    def _edit_history(self, conn, session: str, body: dict) -> dict:
        sets = body.get("sets")
        if not isinstance(sets, list):
            raise ValueError("sets must be a list")
        # A correction must not introduce an unknown exercise id into the clean-set store,
        # and a manually changed set must satisfy the same reps/RIR bounds as the logger.
        detail = history.detail(conn, session)
        existing = {int(row["set_id"]): row for row in (detail.get("sets") or [])}
        for index, item in enumerate(sets):
            if not isinstance(item, dict):
                continue
            validation.exercise_id(item.get("exercise_id"), f"sets[{index}].exercise_id")
            old = None
            if item.get("set_id") not in (None, ""):
                try:
                    old = existing.get(int(item["set_id"]))
                except (TypeError, ValueError):
                    old = None
            try:
                reps = None if item.get("reps") in (None, "") else int(item["reps"])
                rir = None if item.get("rir") in (None, "") else int(item["rir"])
            except (TypeError, ValueError) as exc:
                raise FieldError(
                    f"set {index + 1}: reps and RIR must be integers",
                    {f"sets[{index}].reps": "must be an integer"},
                ) from exc
            unchanged = old is not None and reps == old.get("reps") and rir == old.get("rir")
            if unchanged:
                continue
            if reps is None:
                raise FieldError(
                    f"set {index + 1}: reps are required",
                    {f"sets[{index}].reps": "required"},
                )
            if reps < 0:
                raise FieldError(
                    f"set {index + 1}: reps cannot be negative",
                    {f"sets[{index}].reps": "must be non-negative"},
                )
            if rir is not None and not 0 <= rir <= 6:
                raise FieldError(
                    f"set {index + 1}: RIR must be 0-6",
                    {f"sets[{index}].rir": "must be 0-6"},
                )
        return history.edit_session(
            conn, session, sets=sets,
            forms=body.get("forms"),
            session_rpe=body.get("session_rpe"),
            duration_min=body.get("duration_min"),
            notes=body.get("notes"),
            reason=body.get("reason"),
        )

    def _save_review(self, conn, session: str, body: dict) -> dict:
        build_facts(conn, session)  # refuse marks for a session that does not exist
        raw_scores = body.get("scores") or {}
        if not isinstance(raw_scores, dict):
            raise ValueError("scores must be an object")
        scores: dict[str, float | None] = {}
        for key, value in raw_scores.items():
            if key not in ITEM_KEYS:
                raise ValueError(f"unknown rubric item {key}")
            if value is None or value == "":
                scores[key] = None
                continue
            number = float(value)
            if not 0.0 <= number <= 1.0:
                raise ValueError(f"{key} must be between 0 and 1")
            scores[key] = number
        confidence = str(body.get("confidence") or "unknown")
        if confidence not in {"high", "low", "unknown"}:
            raise ValueError("confidence must be high, low or unknown")
        feedback = session_feedback_feature.record(
            conn, session,
            srpe=body.get("session_rpe"),
            duration_min=body.get("session_minutes"),
            productivity=body.get("productivity"),
        )
        written = record_marks(
            conn, session, scores, confidence=confidence,
            rubric_version=RUBRIC_VERSION, note=body.get("note") or None,
        )
        if written == 0 and feedback is None:
            raise ValueError("no marks recorded; give at least one score")
        conn.execute(
            "UPDATE session SET needs_review = 0 WHERE session_id = ?", (session,)
        )
        workout_reviewed = workout.mark_reviewed(conn, session)
        return {
            "written": written,
            "feedback": feedback,
            "calibration": self._calibrate(conn),
            "reviewed_workout": workout_reviewed,
            "postprocess": {
                "rubric": "persisted at end workout",
                "marks": written,
                "calibration": "report only",
                "workout_closed": workout_reviewed,
            },
        }

    def _readiness(self, conn, day: str) -> dict:
        data = dict(queries.readiness_day(conn, day) or {"on_date": day, "known": False})
        # Legacy column kept for historical rows; grip is a measurement now (DEC-GRIP-01).
        data.pop("grip_strength_kg", None)
        data["score"] = readiness_score.compute(conn, day).as_dict()
        data["context_flags"] = queries.readiness_context(conn, day)
        data["presets"] = readiness_feature.presets()
        data["settings"] = readiness_feature.as_dict(
            readiness_score.effective_settings(conn, day)
        )
        cfg = settings_profile.feature_settings(conn, day).readiness
        data["volume_valve"] = {
            "enabled": cfg.set_reduction_enabled,
            "score_below": cfg.set_reduction_score_below,
            "sets": cfg.set_reduction_sets,
            "include_essential": cfg.set_reduction_include_essential,
        }
        return data

    def _set_readiness(self, conn, body: dict) -> dict:
        day = str(body.get("date") or datetime.date.today().isoformat())
        try:
            datetime.date.fromisoformat(day)
        except ValueError as exc:
            raise FieldError("date must be YYYY-MM-DD", {"date": "must be YYYY-MM-DD"}) from exc
        values = body.get("values") or {}
        if not isinstance(values, dict):
            raise FieldError("values must be an object", {"values": "must be an object"})
        clean = {key: value for key, value in values.items() if value not in (None, "")}
        for field, value in clean.items():
            try:
                readiness_utils.validate(field, value)
            except ValueError as exc:
                raise FieldError(str(exc), {str(field): str(exc)}) from exc
        readiness_feature.record_manual(conn, day, clean, note=body.get("note") or None)
        return self._readiness(conn, day)

    def _set_readiness_preset(self, conn, body: dict) -> dict:
        day = str(body.get("date") or datetime.date.today().isoformat())
        name = str(body.get("name") or "").strip()
        if not name:
            raise ValueError("preset name is required")
        readiness_feature.record_preset(conn, day, name, note=body.get("note") or None)
        return self._readiness(conn, day)

    def _set_readiness_context(self, conn, body: dict) -> dict:
        day = str(body.get("date") or datetime.date.today().isoformat())
        flags = body.get("flags")
        if isinstance(flags, str):
            flags = [flags]
        if not isinstance(flags, list):
            raise ValueError("flags must be a list")
        readiness_feature.record_context(
            conn, day, [str(flag) for flag in flags], note=body.get("note") or None,
        )
        return self._readiness(conn, day)

    def _set_readiness_settings(self, conn, body: dict) -> dict:
        day = str(body.get("date") or datetime.date.today().isoformat())
        current = readiness_score.effective_settings(conn, day)
        fields = ("baseline_days", "baseline_min_readings", "hrv_slope", "rhr_slope",
                  "hrv_weight", "rhr_weight", "wearable_weight")
        values = {
            name: body[name] if body.get(name) not in (None, "") else getattr(current, name)
            for name in fields
        }
        repositories.append_readiness_setting(
            conn, effective_from=day, note=body.get("note") or None, **values,
        )
        return self._readiness(conn, day)

    def _set_readiness_volume(self, conn, body: dict) -> dict:
        day = str(body.get("date") or datetime.date.today().isoformat())
        readiness_feature.save_set_reduction(
            enabled=_truth(body.get("enabled")),
            score_below=float(body.get("score_below", 0.50)),
            sets=int(body.get("sets", 1)),
            include_essential=_truth(body.get("include_essential")),
        )
        return self._readiness(conn, day)

    def _set_readiness_override(self, conn, body: dict) -> dict:
        day = str(body.get("date") or datetime.date.today().isoformat())
        scope = str(body.get("scope") or "global")
        value = body.get("value")
        reason = str(body.get("reason") or "").strip()
        if value is None:
            raise ValueError("value is required")
        repositories.append_readiness_override(
            conn, effective_on=day, scope=scope, value=float(value), reason=reason,
        )
        return self._readiness(conn, day)

    def _state(self, conn) -> dict:
        # One calibration build feeds both tables: the report and the tests-needed coverage.
        calibration = e1rm_calibration_feature.build(conn)
        today = datetime.date.today().isoformat()
        context = RuleContext.from_store(conn, end=today)
        constraints = []
        for row in queries.athlete_constraints(conn):
            data = dict(row)
            # JSON columns are stored as text; the browser needs arrays, not strings.
            for key in ("forbidden_patterns", "forbidden_exercises"):
                try:
                    data[key] = json.loads(data.get(key) or "[]")
                except (TypeError, ValueError):
                    data[key] = []
            constraints.append(data)
        profile = dict(queries.athlete_profile(conn) or {}) or None
        return {
            "profile": profile,
            "constraints": constraints,
            "suitability": queries.exercise_suitability(conn),
            "symptoms": queries.symptom_entries(conn)[-10:],
            "e1rm_overrides": queries.e1rm_overrides(conn),
            "declared_breaks": breaks_feature.as_dict(breaks_feature.all_breaks(conn)),
            "e1rm_calibration": e1rm_calibration_feature.as_dict(calibration),
            "e1rm_tests_needed": e1rm_calibration_feature.coverage_as_dict(
                e1rm_calibration_feature.coverage(conn, report=calibration)
            ),
            "block_week": context.block_week_index,
            "injury_signal": injury_signal.compute(
                conn, today, ramp_week=context.block_week_index
            ).as_dict(),
            # Canonical choices for the athlete forms. The browser must not own these lists.
            "options": options_mod.canonical_options(),
        }

    def _cardio(self, conn, body: dict | None = None) -> dict:
        body = body or {}
        weeks = int(body.get("weeks") or 12)
        # `date` anchors the window like `cardio --show --date`; without it, today.
        return cardio_feature.compute(
            conn, weeks=weeks, on_date=body.get("date") or None
        ).as_dict()

    def _save_cardio(self, conn, body: dict) -> dict:
        """Log one cardio session through the same writer the CLI uses."""
        def optional(name: str):
            value = body.get(name)
            return None if value in (None, "") else value

        day = str(body.get("date") or datetime.date.today().isoformat())
        try:
            datetime.date.fromisoformat(day)
        except ValueError as exc:
            raise FieldError("date must be YYYY-MM-DD", {"date": "must be YYYY-MM-DD"}) from exc
        modality = str(body.get("modality") or "").strip()
        if not modality:
            raise FieldError("modality is required", {"modality": "required"})
        minutes = optional("minutes")
        if minutes is None:
            raise FieldError("minutes is required", {"minutes": "required"})
        try:
            minutes_value = float(minutes)
        except (TypeError, ValueError) as exc:
            raise FieldError("minutes must be a number", {"minutes": "must be a number"}) from exc
        if minutes_value <= 0:
            raise FieldError("minutes must be positive", {"minutes": "must be positive"})
        avg_hr = optional("avg_hr")
        max_hr = optional("max_hr")
        distance_km = optional("distance_km")
        srpe = optional("srpe")
        for name, value, low, high in (
            ("avg_hr", avg_hr, 30, 230),
            ("max_hr", max_hr, 30, 250),
            ("srpe", srpe, 1, 10),
        ):
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise FieldError(f"{name} must be a number", {name: "must be a number"}) from exc
            if not low <= number <= high:
                raise FieldError(
                    f"{name} must be between {low} and {high}",
                    {name: f"must be between {low} and {high}"},
                )
        distance_value = None
        if distance_km is not None:
            try:
                distance_value = float(distance_km)
            except (TypeError, ValueError) as exc:
                raise FieldError(
                    "distance_km must be a number", {"distance_km": "must be a number"}
                ) from exc
            if distance_value < 0:
                raise FieldError(
                    "distance_km must be non-negative",
                    {"distance_km": "must be non-negative"},
                )
        repositories.append_cardio(
            conn,
            performed_on=day,
            modality=modality,
            duration_s=round(minutes_value * 60),
            avg_hr=avg_hr,
            max_hr=max_hr,
            distance_m=None if distance_value is None else distance_value * 1000,
            srpe=srpe,
            note=body.get("note") or None,
        )
        return self._cardio(conn, body)

    def _selection(self, conn, day: str, session_type: str | None,
                   use_llm: bool, include_different: bool = False) -> dict:
        chooser = None
        if use_llm:
            chooser = agent_selection.chooser(build_client(load_settings()))
        resolved = (
            schedule_mod.next_session_type(conn, day)
            if session_type in (None, "", "auto") else str(session_type)
        )
        rows = selection_mod.select(
            conn, None, day, resolved, chooser=chooser,
            include_different=include_different,
        )
        return {
            "on_date": day,
            "session_type": resolved,
            "slots": selection_mod.as_dict(rows),
        }

    def _volume(self, conn, day: str | None = None, weeks: int = 4) -> dict:
        on_date = day or datetime.date.today().isoformat()
        context = RuleContext.from_store(conn, end=on_date)
        cfg = settings_profile.feature_settings(conn, on_date).volume
        cfg = replace(cfg, window_weeks=weeks)
        report = volume_feature.compute(context.sets, on_date=on_date, config=cfg)
        heavy_cfg = heavy_spinal.HeavySpinalConfig.load()
        heavy_cfg = heavy_spinal.HeavySpinalConfig(
            window_weeks=weeks, rir_max=heavy_cfg.rir_max,
            source_path=heavy_cfg.source_path,
        )
        report["heavy_spinal"] = heavy_spinal.compute(
            context.sets, on_date=on_date, config=heavy_cfg
        )
        return {"on_date": on_date, "window_weeks": weeks, **report}

    def _continuity(self, conn, day: str | None = None) -> dict:
        on_date = day or datetime.date.today().isoformat()
        context = RuleContext.from_store(conn, end=on_date)
        thresholds = Thresholds.load()
        cfg = continuity_calibration.CalibrationConfig.load()
        report = continuity_calibration.compute(
            context.sets,
            short_days=thresholds.continuity_short_days,
            medium_days=thresholds.continuity_medium_days,
            long_days=thresholds.continuity_long_days,
            medium_multiplier=thresholds.continuity_medium_multiplier,
            long_multiplier=thresholds.continuity_long_multiplier,
            config=cfg,
        )
        return {
            "on_date": on_date,
            "allow_relax_fixed": cfg.allow_relax_fixed,
            "calibration": report.as_dict(),
        }

    def _fatigue(self, conn, day: str | None = None) -> dict:
        on_date = day or datetime.date.today().isoformat()
        return {
            "on_date": on_date,
            "models": fatigue_fitness_feature.as_dict(
                fatigue_fitness_feature.compute_cached(conn, on_date)
            ),
        }

    def _measurements(self, conn) -> dict:
        return {
            "summary": measurements_feature.summary(conn),
            "entries": measurements_feature.entries(conn, limit=50),
        }

    def _save_measurement(self, conn, body: dict) -> dict:
        metric = str(body.get("metric") or "").strip()
        try:
            measurements_feature.record(
                conn,
                metric_key=metric,
                value=body.get("value"),
                measured_on=body.get("date") or None,
                method=body.get("method") or None,
                note=body.get("note") or None,
            )
        except measurements_feature.MeasurementError as exc:
            text = str(exc)
            if "unknown measurement metric" in text:
                field = "metric"
            elif "date must" in text:
                field = "date"
            else:
                field = "value"
            raise FieldError(text, {field: text}) from exc
        except (TypeError, ValueError) as exc:
            raise FieldError("value must be a number", {"value": "must be a number"}) from exc
        return self._measurements(conn)

    def _programme(self, conn, body: dict) -> dict:
        return programme_payload(conn, body)

    def _save_profile(self, conn, body: dict) -> dict:
        current = dict(queries.athlete_profile(conn) or {})
        try:
            main_lift_policy = validation.choice(
                body.get("main_lift_policy") or current.get("main_lift_policy") or "preserve",
                ("preserve", "reduce", "drop"),
                "main_lift_policy",
            )
        except ValueError as exc:
            raise FieldError(str(exc), {"main_lift_policy": str(exc)}) from exc
        block_start = body.get("block_start_date", current.get("block_start_date"))
        repositories.append_athlete_profile(
            conn,
            effective_from=str(body.get("effective_from") or datetime.date.today().isoformat()),
            competition_date=body.get("competition_date") or None,
            sessions_per_week_target=_int_or_none(body.get("sessions_per_week_target")),
            max_session_minutes=_int_or_none(body.get("max_session_minutes")),
            block_start_date=block_start or None,
            volume_budget_enabled=_truth(
                body.get("volume_budget_enabled", current.get("volume_budget_enabled", 0))
            ),
            main_lift_policy=main_lift_policy,
            # Absent from the body means "leave it alone": a profile edit must not silently
            # switch the exposure trim off (DEC-EXPOSURE-02).
            exposure_trim_enabled=(
                None if "exposure_trim_enabled" not in body
                else _truth(body.get("exposure_trim_enabled"))
            ),
        )
        return self._state(conn)

    def _rate_demand(self, body: dict) -> dict:
        """Write one demand rating to the git-ignored local overlay, then return the profile."""
        exercise_id = str(body.get("exercise_id") or "").strip()
        dimension = str(body.get("dimension") or "").strip()
        if body.get("clear"):
            catalogue = demands_feature.clear_claim(exercise_id, dimension)
        else:
            catalogue = demands_feature.set_claim(
                exercise_id, dimension, str(body.get("level") or ""),
                confidence=body.get("confidence"),
                reason=body.get("reason"),
                evidence=body.get("evidence") or (),
            )
        return {
            "exercise_id": exercise_id,
            "digest": catalogue.digest,
            "overlay": catalogue.overlay_path is not None,
            "demands": {
                "rated": catalogue.in_scope_rated(exercise_id),
                "dimensions": catalogue.profile(exercise_id),
            },
        }

    def _save_constraint(self, conn, body: dict) -> dict:
        repositories.append_athlete_constraint(
            conn,
            kind=_field_call(
                validation.choice, "kind",
                body.get("kind"), athlete_state.CONSTRAINT_KINDS, "kind",
            ),
            region=_field_call(validation.region, "region", body.get("region")),
            severity=_field_call(
                validation.choice, "severity",
                body.get("severity") or "monitor", athlete_state.SEVERITIES, "severity",
            ),
            forbidden_patterns=_field_call(
                validation.list_choice, "forbidden_patterns",
                _list(body.get("forbidden_patterns")),
                exercises.canonical_patterns(),
                "forbidden_patterns",
            ),
            forbidden_exercises=_field_call(
                validation.exercise_ids, "forbidden_exercises",
                _list(body.get("forbidden_exercises")), "forbidden_exercises",
            ),
            rom_limit=body.get("rom_limit") or None,
            since=body.get("since") or None,
            settled_on=body.get("settled_on") or None,
            evidence=body.get("evidence") or None,
        )
        return self._state(conn)

    def _save_suitability(self, conn, body: dict) -> dict:
        exercise_id = _field_call(
            validation.exercise_id, "exercise_id", body.get("exercise_id")
        )
        repositories.append_exercise_suitability(
            conn,
            exercise_id=exercise_id,
            rated_on=str(body.get("rated_on") or datetime.date.today().isoformat()),
            can_do=_truth(body.get("can_do", True)),
            will_do=_truth(body.get("will_do", True)),
            feels_bad=_truth(body.get("feels_bad", False)),
            note=body.get("note") or None,
        )
        return self._state(conn)

    def _breaks(self, conn, body: dict | None = None) -> dict:
        body = body or {}
        day = str(body.get("date") or datetime.date.today().isoformat())
        return {
            "breaks": breaks_feature.as_dict(breaks_feature.all_breaks(conn)),
            "active": breaks_feature.as_dict(breaks_feature.active_on(conn, day)),
        }

    def _save_break(self, conn, body: dict) -> dict:
        """Record a break through the same writer the CLI uses; nothing is edited later."""
        try:
            break_id = breaks_feature.record(
                conn,
                starts_on=str(body.get("starts_on") or "").strip(),
                ends_on=str(body.get("ends_on") or "").strip(),
                reason=str(body.get("reason") or "").strip(),
                note=body.get("note") or None,
            )
        except ValueError as exc:
            text = str(exc)
            if "starts_on" in text:
                field = "starts_on"
            elif "ends_on" in text:
                field = "ends_on"
            elif "reason" in text:
                field = "reason"
            else:
                field = "starts_on"
            raise FieldError(text, {field: text}) from exc
        return {"break_id": break_id, **self._breaks(conn)}

    def _cancel_break(self, conn, body: dict) -> dict:
        cancel_id = breaks_feature.cancel(
            conn, _integer(body.get("break_id")), note=body.get("note") or None
        )
        return {"cancel_id": cancel_id, **self._breaks(conn)}

    def _save_e1rm(self, conn, body: dict) -> dict:
        exercise_id = _field_call(
            validation.exercise_id, "exercise_id", body.get("exercise_id")
        )
        try:
            kg = float(body.get("e1rm_kg"))
        except (TypeError, ValueError) as exc:
            raise FieldError("e1rm_kg must be a number", {"e1rm_kg": "must be a number"}) from exc
        if kg <= 0:
            raise FieldError(
                "a positive e1rm_kg is required", {"e1rm_kg": "must be positive"}
            )
        repositories.append_e1rm_override(
            conn,
            exercise_id=exercise_id,
            e1rm_kg=kg,
            effective_from=str(body.get("effective_from") or datetime.date.today().isoformat()),
            expires_on=body.get("expires_on") or None,
            reason=body.get("reason") or None,
        )
        return self._state(conn)

    def _save_symptom(self, conn, body: dict) -> dict:
        region = _field_call(validation.region, "region", body.get("region") or "low_back")
        try:
            level = int(body.get("level"))
        except (TypeError, ValueError) as exc:
            raise FieldError("level must be an integer 0-3", {"level": "must be 0-3"}) from exc
        if not 0 <= level <= 3:
            raise FieldError("symptom level must be 0-3", {"level": "must be 0-3"})
        day = str(body.get("date") or datetime.date.today().isoformat())
        try:
            datetime.date.fromisoformat(day)
        except ValueError as exc:
            raise FieldError("date must be YYYY-MM-DD", {"date": "must be YYYY-MM-DD"}) from exc
        repositories.append_symptom(
            conn,
            logged_on=day,
            timing="pre_session",
            region=region,
            level=level,
            settled_within_48h=_settled(body.get("settled")),
            note=body.get("note") or None,
        )
        return self._state(conn)

    def _save_test(self, conn, body: dict) -> dict:
        exercise_id = _field_call(
            validation.exercise_id, "exercise_id", body.get("exercise_id")
        )
        try:
            kg = float(body.get("kg"))
        except (TypeError, ValueError) as exc:
            raise FieldError("kg must be a number", {"kg": "must be a number"}) from exc
        try:
            reps = int(body.get("reps"))
        except (TypeError, ValueError) as exc:
            raise FieldError("reps must be an integer", {"reps": "must be an integer"}) from exc
        if kg <= 0:
            raise FieldError("a positive load is required", {"kg": "must be positive"})
        if not 1 <= reps <= 10:
            raise FieldError("reps must be 1-10", {"reps": "must be 1-10"})
        if reps == 1 and not _truth(body.get("max", False)):
            raise ValueError("a single-rep test must be confirmed with max=true")
        on_date = str(body.get("date") or datetime.date.today().isoformat())
        try:
            datetime.date.fromisoformat(on_date)
        except ValueError as exc:
            raise FieldError("date must be YYYY-MM-DD", {"date": "must be YYYY-MM-DD"}) from exc
        thresholds = Thresholds.load()
        previous = queries.last_measured_override(conn, exercise_id)
        if reps == 1 and previous is not None:
            days = (datetime.date.fromisoformat(on_date)
                    - datetime.date.fromisoformat(previous["effective_from"])).days
            if days < thresholds.test_max_single_min_interval_days:
                raise ValueError(
                    f"a 1RM for {exercise_id} was recorded {days} days ago; "
                    f"minimum interval is {thresholds.test_max_single_min_interval_days}"
                )
        guard = exposure_feature.status(conn, on_date)
        if guard.status == "blocked":
            raise ValueError(
                f"{guard.reason}; next maximal exposure allowed on {guard.next_maximal_on}"
            )
        value = e1rm_mod.epley_rir_adjusted(kg, reps, 0)
        override_id = repositories.append_e1rm_override(
            conn, exercise_id=exercise_id, e1rm_kg=float(value),
            effective_from=on_date, reason=body.get("reason") or f"{reps}RM test",
            source="measured",
        )
        exposure_feature.register_test(
            conn, override_id=override_id, exercise_id=exercise_id,
            performed_on=on_date,
            test_type=exposure_feature.test_type_for_reps(reps),
            note=body.get("reason") or f"{reps}RM test",
        )
        return self._state(conn)

    def _save_exposure(self, conn, body: dict) -> dict:
        day = str(body.get("date") or datetime.date.today().isoformat())
        kind = str(body.get("kind") or "unplanned")
        region = str(body.get("region_load") or "unknown")
        intensity = str(body.get("intensity_class") or "near_max")
        if kind == "test":
            raise ValueError("use the test form to record a test")
        exposure_feature.log_manual(
            conn,
            performed_on=day,
            kind=kind,
            region_load=region,
            exercise_id=_field_call(
                validation.optional_exercise_id, "exercise_id", body.get("exercise_id")
            ),
            intensity_class=intensity,
            axial_cost=body.get("axial_cost"),
            test_type=body.get("test_type") or None,
            session_id=body.get("session_id") or None,
            set_id=body.get("set_id") or None,
            note=body.get("note") or None,
        )
        return exposure_feature.status(conn, day).as_dict()

    def _save_block(self, conn, body: dict) -> dict:
        current = queries.athlete_profile(conn)
        if current is None:
            raise FieldError("record an athlete profile first", {})
        block_date = str(body.get("date") or "").strip() or None
        if block_date is not None:
            try:
                datetime.date.fromisoformat(block_date)
            except ValueError as exc:
                raise FieldError("date must be YYYY-MM-DD", {"date": "must be YYYY-MM-DD"}) from exc
        if current["block_start_date"] and not _truth(body.get("force", False)):
            raise FieldError(
                "the block already started; tick reset to replace it",
                {"force": "tick to reset an existing block start"},
            )
        repositories.append_athlete_profile(
            conn,
            effective_from=datetime.date.today().isoformat(),
            competition_date=current["competition_date"],
            sessions_per_week_target=current["sessions_per_week_target"],
            max_session_minutes=current["max_session_minutes"],
            block_start_date=block_date,
            volume_budget_enabled=bool(current.get("volume_budget_enabled", 0)),
            main_lift_policy=current.get("main_lift_policy", "preserve"),
        )
        return self._state(conn)

    def _calibrate(self, conn) -> dict:
        labels = load_marks(conn)
        if not labels.sessions:
            return {"text": "no marks yet; review a session first", "empty": True}
        report = backtest(conn, labels, tolerance=TOLERANCE)
        return {"text": format_report(report), "empty": False}

    def _doc(self, name: str) -> dict:
        allowed = {entry["name"]: entry for entry in _docs()}
        # Links rendered from docs/ use the bare filename (e.g. REFERENCES.md); resolve those
        # against docs/ without making the URL depend on the current page.
        if name not in allowed and f"docs/{name}" in allowed:
            name = f"docs/{name}"
        if name not in allowed:
            raise KeyError(f"unknown document {name}")
        text = (ROOT / name).read_text(encoding="utf-8")
        return {
            "name": name,
            "title": allowed[name]["title"],
            "html": markdown.render(text, docs_root=ROOT, base_dir=(ROOT / name).parent),
        }

    def _doc_page(self, name: str) -> None:
        doc = self._doc(name)
        page = (
            "<!doctype html><meta charset='utf-8'><title>"
            + doc["title"] + "</title>"
            + "<link rel='stylesheet' href='/static/style.css'>"
            + "<main class='doc'><p><a href='/'>← back to coach</a></p>"
            + doc["html"] + "</main>"
        )
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")


def create_server(db_path: str | Path | None = None, host: str = "127.0.0.1",
                  port: int = 8000) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"db_path": db_path})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(db_path: str | Path | None = None, host: str = "0.0.0.0", port: int = 8000,
          open_browser: bool = False) -> None:
    server = create_server(db_path, host=host, port=port)
    port = server.server_address[1]
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{port}/"
    print(
        f"strength-coach web bound {host}:{port} (home network, no authentication); "
        f"open {url}; Ctrl-C to stop"
    )
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
