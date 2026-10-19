"""A local-only HTTP UI over the same Python core the CLI uses.

Design constraints, deliberately:

* bind to 127.0.0.1 by default and refuse to pretend there is authentication;
* every number still comes from the deterministic core — the UI only serialises it;
* the CLI remains the automation surface; this is an additional front end;
* no external assets, so the page works offline.
"""

from __future__ import annotations

import datetime
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
from strength_coach.eval import ITEM_GUIDE, ITEM_KEYS, backtest, format_report, load_marks, record_marks
from strength_coach.features import back_signal, readiness as readiness_feature
from strength_coach.prescribe import build_prescription
from strength_coach.prescribe.config import Thresholds
from strength_coach.rules import RuleContext
from strength_coach.store import db, queries
from strength_coach.utils import readiness as readiness_utils
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
            elif path == "/api/state":
                self._json(200, self._with_conn(self._state))
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
            if path == "/api/prescribe":
                self._json(200, self._with_conn(lambda c: self._prescribe(c, body)))
            elif path == "/api/readiness":
                self._json(200, self._with_conn(lambda c: self._set_readiness(c, body)))
            elif path.startswith("/api/review/"):
                session = path[len("/api/review/"):]
                self._json(200, self._with_conn(lambda c: self._save_review(c, session, body)))
            else:
                self._error(404, "not found")
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
        signal = back_signal.compute(
            conn, today, Thresholds.load(), ramp_week=context.block_week_index
        ).as_dict()
        return {
            "today": today,
            "profile": dict(profile) if profile else None,
            "block_week": context.block_week_index,
            "readiness": readiness,
            "back_signal": signal,
            "unreviewed": queries.unreviewed_sessions(conn, limit=50),
            "sessions": _session_rows(conn, 12),
        }

    def _prescribe(self, conn, body: dict) -> dict:
        for_date = str(body.get("date") or datetime.date.today().isoformat())
        day = str(body.get("day") or "A").upper()
        if day not in {"A", "B", "C"}:
            raise ValueError("day must be A, B or C")
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
        data = queries.readiness_day(conn, day)
        return data or {"on_date": day, "known": False}

    def _set_readiness(self, conn, body: dict) -> dict:
        day = str(body.get("date") or datetime.date.today().isoformat())
        values = body.get("values") or {}
        if not isinstance(values, dict):
            raise ValueError("values must be an object")
        clean = {key: value for key, value in values.items() if value not in (None, "")}
        readiness_feature.record_manual(conn, day, clean, note=body.get("note") or None)
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
        return {
            "profile": dict(queries.athlete_profile(conn) or {}) or None,
            "constraints": constraints,
            "suitability": queries.exercise_suitability(conn),
            "symptoms": queries.symptom_entries(conn)[-10:],
            "e1rm_overrides": queries.e1rm_overrides(conn),
            "block_week": context.block_week_index,
            "back_signal": back_signal.compute(
                conn, today, Thresholds.load(), ramp_week=context.block_week_index
            ).as_dict(),
        }

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
