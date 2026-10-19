"""A local-only HTTP UI over the same Python core the CLI uses.

Design constraints, deliberately:

* bind to 127.0.0.1 by default and refuse to pretend there is authentication;
* every number still comes from the deterministic core — the UI only serialises it;
* the CLI remains the automation surface; this is an additional front end;
* no external assets, so the page works offline.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from strength_coach.critique import UnknownSessionError, build_facts, score_session
from strength_coach.critique.rubric import RUBRIC_VERSION
from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.eval import ITEM_GUIDE, ITEM_KEYS, backtest, format_report, load_marks, record_marks
from strength_coach.features import injury_signal, readiness as readiness_feature
from strength_coach.features import readiness_calibration, readiness_score
from strength_coach.prescribe import build_prescription
from strength_coach.prescribe.config import Thresholds
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer, queries, repositories
from strength_coach.utils import exercises, io_utils
from strength_coach.web import markdown

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).resolve().parent / "static"
TOLERANCE = 0.25


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
        "rest_s": item.rest_s,
        "essential": item.essential,
        "refs": list(item.rationale_refs),
        "velocity_target": item.velocity_target,
        "unknown_load_reason": item.unknown_load_reason,
    }


def prescription_dict(prescription) -> dict:
    return {
        "for_date": prescription.for_date,
        "session_day": prescription.session_day,
        "fallback_level": prescription.fallback_level,
        "executable": prescription.executable,
        "items": [_item_dict(item) for item in prescription.items],
        "warnings": list(prescription.warnings),
        "issues": list(prescription.issues),
        "notes": prescription.notes,
    }


def _session_rows(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """
        SELECT s.session_id, s.occurred_on, s.day_guess, s.set_count, s.working_set_count,
               s.main_lifts, s.tonnage_kg,
               (SELECT COUNT(*) FROM rubric_mark m WHERE m.session_id = s.session_id) AS marks
          FROM session s
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


class ReadinessRequired(Exception):
    """The date needs a usable readiness score before a workout is generated."""


class Handler(BaseHTTPRequestHandler):
    db_path: str | Path | None = None
    server_version = "strength-coach-web"

    # --- plumbing ---------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, default=_json_default).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _with_conn(self, fn):
        store = db.Store(self.db_path)
        try:
            return fn(store.connection)
        finally:
            store.close()

    # --- routes -----------------------------------------------------------
    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/":
                self._serve_file(STATIC / "index.html", "text/html; charset=utf-8")
            elif path.startswith("/static/"):
                self._serve_file(STATIC / Path(path).name,
                                 mimetypes.guess_type(path)[0] or "application/octet-stream")
            elif path == "/api/overview":
                self._json(200, self._with_conn(self._overview))
            elif path == "/api/sessions":
                self._json(200, self._with_conn(lambda c: _session_rows(c, 40)))
            elif path == "/api/calibrate":
                self._json(200, self._with_conn(self._calibrate))
            elif path == "/api/readiness/calibrate":
                self._json(200, self._with_conn(
                    lambda c: {"text": readiness_calibration.report(c)}
                ))
            elif path == "/api/state":
                self._json(200, self._with_conn(self._state))
            elif path == "/api/exercises":
                self._json(200, [
                    {"id": key, "display": str(value.get("display") or key),
                     "pattern": value.get("pattern")}
                    for key, value in exercises.taxonomy().entities.items()
                ])
            elif path == "/api/docs":
                self._json(200, _docs())
            elif path.startswith("/api/docs/"):
                self._json(200, self._doc(path[len("/api/docs/"):]))
            elif path.startswith("/docs/"):
                self._doc_page(path[len("/docs/"):])
            elif path.startswith("/api/review/"):
                session = path[len("/api/review/"):]
                self._json(200, self._with_conn(lambda c: self._review_sheet(c, session)))
            elif path.startswith("/api/readiness/"):
                day = path[len("/api/readiness/"):]
                self._json(200, self._with_conn(lambda c: self._readiness(c, day)))
            else:
                self._error(404, "not found")
        except ReadinessRequired as exc:
            self._error(409, str(exc))
        except UnknownSessionError as exc:
            self._error(404, str(exc))
        except (ValueError, KeyError) as exc:
            self._error(400, str(exc))
        except Exception as exc:  # local tool: show the problem, do not pretend success
            self._error(500, f"{type(exc).__name__}: {exc}")

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            body = self._body()
            if path == "/api/import":
                self._json(200, self._with_conn(lambda c: self._import(c, body)))
            elif path == "/api/prescribe":
                self._json(200, self._with_conn(lambda c: self._prescribe(c, body)))
            elif path == "/api/readiness":
                self._json(200, self._with_conn(lambda c: self._set_readiness(c, body)))
            elif path == "/api/readiness/override":
                self._json(200, self._with_conn(lambda c: self._set_readiness_override(c, body)))
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
        except (ValueError, KeyError) as exc:
            self._error(400, str(exc))
        except Exception as exc:
            self._error(500, f"{type(exc).__name__}: {exc}")

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._error(404, "not found")
            return
        self._send(200, path.read_bytes(), content_type)

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
            "injury_signal": signal,
            "unreviewed": queries.unreviewed_sessions(conn, limit=50),
            "sessions": _session_rows(conn, 12),
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
            if len(text.encode("utf-8")) > 20 * 1024 * 1024:
                raise ValueError(f"{part_name} file is larger than 20 MB")
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

    def _prescribe(self, conn, body: dict) -> dict:
        for_date = str(body.get("date") or datetime.date.today().isoformat())
        day = str(body.get("day") or "A").upper()
        if day not in {"A", "B", "C"}:
            raise ValueError("day must be A, B or C")
        if for_date >= datetime.date.today().isoformat():
            assessment = readiness_score.compute(conn, for_date)
            if assessment.status != "ready":
                raise ReadinessRequired(
                    f"readiness required for {for_date}: {assessment.status} — "
                    f"{assessment.basis}"
                )
        prescription = build_prescription(conn, for_date=for_date, session_day=day)
        return prescription_dict(prescription)

    def _review_sheet(self, conn, session: str) -> dict:
        facts = build_facts(conn, session)
        critique = score_session(conn, session, facts=facts)
        marks = load_marks(conn).sessions.get(session)
        existing = dict(marks.scores) if marks else {}
        return {
            "session": session,
            "occurred_on": facts.occurred_on,
            "day": facts.day,
            "week": facts.week,
            "week_cost": facts.week_cost,
            "composite": critique.composite,
            "confidence": marks.confidence if marks else "unknown",
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
        written = record_marks(
            conn, session, scores, confidence=confidence,
            rubric_version=RUBRIC_VERSION, note=body.get("note") or None,
        )
        if written == 0:
            raise ValueError("no marks recorded; give at least one score")
        return {"written": written, "calibration": self._calibrate(conn)}

    def _readiness(self, conn, day: str) -> dict:
        data = dict(queries.readiness_day(conn, day) or {"on_date": day, "known": False})
        data["score"] = readiness_score.compute(conn, day).as_dict()
        return data

    def _set_readiness(self, conn, body: dict) -> dict:
        day = str(body.get("date") or datetime.date.today().isoformat())
        values = body.get("values") or {}
        if not isinstance(values, dict):
            raise ValueError("values must be an object")
        clean = {key: value for key, value in values.items() if value not in (None, "")}
        readiness_feature.record_manual(conn, day, clean, note=body.get("note") or None)
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
        if profile:
            for key in ("goal_rank", "focus_lifts"):
                try:
                    profile[key] = json.loads(profile.get(key) or "[]")
                except (TypeError, ValueError):
                    profile[key] = []
        return {
            "profile": profile,
            "constraints": constraints,
            "suitability": queries.exercise_suitability(conn),
            "symptoms": queries.symptom_entries(conn)[-10:],
            "e1rm_overrides": queries.e1rm_overrides(conn),
            "block_week": context.block_week_index,
            "injury_signal": injury_signal.compute(
                conn, today, ramp_week=context.block_week_index
            ).as_dict(),
        }

    def _save_profile(self, conn, body: dict) -> dict:
        current = dict(queries.athlete_profile(conn) or {})
        def current_list(key):
            try:
                return json.loads(current.get(key) or "[]")
            except (TypeError, ValueError):
                return []
        goal = str(body.get("primary_goal") or current.get("primary_goal") or "").strip()
        if not goal:
            raise ValueError("primary_goal is required")
        block_start = body.get("block_start_date", current.get("block_start_date"))
        repositories.append_athlete_profile(
            conn,
            effective_from=str(body.get("effective_from") or datetime.date.today().isoformat()),
            primary_goal=goal,
            goal_rank=_list(body.get("goal_rank"), current_list("goal_rank")),
            focus_lifts=_list(body.get("focus_lifts"), current_list("focus_lifts")),
            competition_date=body.get("competition_date") or None,
            sessions_per_week_target=_int_or_none(body.get("sessions_per_week_target")),
            max_session_minutes=_int_or_none(body.get("max_session_minutes")),
            block_start_date=block_start or None,
        )
        return self._state(conn)

    def _save_constraint(self, conn, body: dict) -> dict:
        repositories.append_athlete_constraint(
            conn,
            kind=str(body.get("kind") or "").strip(),
            region=str(body.get("region") or "").strip(),
            severity=str(body.get("severity") or "monitor").strip(),
            forbidden_patterns=_list(body.get("forbidden_patterns")),
            forbidden_exercises=_list(body.get("forbidden_exercises")),
            rom_limit=body.get("rom_limit") or None,
            since=body.get("since") or None,
            settled_on=body.get("settled_on") or None,
            evidence=body.get("evidence") or None,
        )
        return self._state(conn)

    def _save_suitability(self, conn, body: dict) -> dict:
        exercise_id = str(body.get("exercise_id") or "").strip()
        if not exercise_id:
            raise ValueError("exercise_id is required")
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

    def _save_e1rm(self, conn, body: dict) -> dict:
        exercise_id = str(body.get("exercise_id") or "").strip()
        try:
            kg = float(body.get("e1rm_kg"))
        except (TypeError, ValueError) as exc:
            raise ValueError("e1rm_kg must be a number") from exc
        if not exercise_id or kg <= 0:
            raise ValueError("exercise_id and a positive e1rm_kg are required")
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
        region = str(body.get("region") or "low_back").strip()
        config = injury_signal.InjuryConfig.load()
        if region not in config.regions:
            raise ValueError(f"unknown injury region {region!r}; known: {sorted(config.regions)}")
        level = int(body.get("level"))
        if not 0 <= level <= 3:
            raise ValueError("symptom level must be 0-3")
        repositories.append_symptom(
            conn,
            logged_on=str(body.get("date") or datetime.date.today().isoformat()),
            timing="pre_session",
            region=region,
            level=level,
            settled_within_48h=_settled(body.get("settled")),
            note=body.get("note") or None,
        )
        return self._state(conn)

    def _save_test(self, conn, body: dict) -> dict:
        exercise_id = str(body.get("exercise_id") or "").strip()
        try:
            kg = float(body.get("kg"))
            reps = int(body.get("reps"))
        except (TypeError, ValueError) as exc:
            raise ValueError("kg and reps are required") from exc
        if not exercise_id or kg <= 0 or not 1 <= reps <= 10:
            raise ValueError("exercise, a positive load and 1-10 reps are required")
        if reps == 1 and not _truth(body.get("max", False)):
            raise ValueError("a single-rep test must be confirmed with max=true")
        on_date = str(body.get("date") or datetime.date.today().isoformat())
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
        value = e1rm_mod.epley_rir_adjusted(kg, reps, 0)
        repositories.append_e1rm_override(
            conn, exercise_id=exercise_id, e1rm_kg=float(value),
            effective_from=on_date, reason=body.get("reason") or f"{reps}RM test",
            source="measured",
        )
        return self._state(conn)

    def _save_block(self, conn, body: dict) -> dict:
        current = queries.athlete_profile(conn)
        if current is None:
            raise ValueError("record an athlete profile first")
        if current["block_start_date"] and not _truth(body.get("force", False)):
            raise ValueError("the block already started; pass force=true to reset it")
        repositories.append_athlete_profile(
            conn,
            effective_from=datetime.date.today().isoformat(),
            primary_goal=current["primary_goal"],
            goal_rank=json.loads(current["goal_rank"] or "[]"),
            focus_lifts=json.loads(current["focus_lifts"] or "[]"),
            competition_date=current["competition_date"],
            sessions_per_week_target=current["sessions_per_week_target"],
            max_session_minutes=current["max_session_minutes"],
            block_start_date=str(body.get("date") or "").strip() or None,
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


def serve(db_path: str | Path | None = None, host: str = "127.0.0.1", port: int = 8000,
          open_browser: bool = False) -> None:
    server = create_server(db_path, host=host, port=port)
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"strength-coach web on {url} (local only; Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
