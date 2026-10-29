#!/usr/bin/env python3
"""Smoke-test a tagged source archive without a browser.

This verifies the actual deployable artifact for this local Python web app: the source tree is
extracted, required config/docs/static assets are checked, the real HTTP server starts against
a disposable SQLite database, and representative read/write/prescription routes return
successful responses. It does not execute JavaScript or replace a browser test.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

REQUIRED = (
    "pyproject.toml",
    "requirements.lock",
    "run-web.sh",
    "config/rules/programme.v1.yaml",
    "config/templates/session-types.v1.yaml",
    "docs/WORKOUT-GENERATION.md",
    "strength_coach/web/static/index.html",
    "strength_coach/web/static/app.js",
)


def _extract(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise SystemExit(f"unsafe archive member: {member.name}")
        tar.extractall(destination)
    top = {Path(member.name).parts[0] for member in members if member.name.strip("/")}
    if len(top) != 1:
        raise SystemExit(f"archive must have one top-level directory, found {sorted(top)}")
    return destination / next(iter(top))


def _request(base: str, path: str, *, method: str = "GET", body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="source .tar.gz built from the tagged commit")
    args = parser.parse_args()
    if not args.archive.is_file() or args.archive.stat().st_size == 0:
        raise SystemExit(f"archive missing or empty: {args.archive}")

    with tempfile.TemporaryDirectory(prefix="strength-release-smoke-") as temp:
        root = _extract(args.archive, Path(temp))
        missing = [name for name in REQUIRED if not (root / name).is_file()]
        _assert(not missing, f"archive is missing required paths: {missing}")
        _assert((root / "run-web.sh").stat().st_mode & 0o111, "run-web.sh is not executable")

        sys.path.insert(0, str(root))
        from strength_coach.web.server import create_server

        today = date.today().isoformat()
        database = root / "data" / "smoke.db"
        database.parent.mkdir(parents=True, exist_ok=True)
        server = create_server(database, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            status, page = _request(base, "/")
            _assert(status == 200, f"GET / -> {status}")
            _assert('id="docs-list"' in page, "served page is missing the docs browser")
            _assert('src="/static/app.js"' in page, "served page is missing app.js")
            for asset in ("/static/app.js", "/static/core.js", "/static/style.css"):
                status, content = _request(base, asset)
                _assert(status == 200 and content, f"{asset} is missing or empty")

            status, doc_body = _request(base, "/api/docs/docs%2FWORKOUT-GENERATION.md")
            _assert(status == 200, f"workout-generation doc -> {status}")
            doc = json.loads(doc_body)
            _assert("How Workout Generation Works" in doc.get("title", ""), "doc title mismatch")
            _assert('id="related"' in doc.get("html", ""), "doc footer is not rendered")

            status, active = _request(base, "/api/workout/active")
            _assert(status == 200 and "workout" in json.loads(active),
                    "active-workout response invalid")

            readiness = {
                "date": today,
                "values": {
                    "sleep": 4, "energy": 4, "mood": 4, "soreness": 4,
                    "stress": 4, "nutrition": 4, "hydration": 4,
                },
            }
            status, saved = _request(base, "/api/readiness", method="POST", body=readiness)
            saved_data = json.loads(saved)
            _assert(
                status == 200 and saved_data.get("score", {}).get("status") == "ready",
                "readiness save failed",
            )

            status, readiness_body = _request(base, f"/api/readiness/{today}")
            _assert(
                status == 200
                and json.loads(readiness_body).get("score", {}).get("status") == "ready",
                "readiness read-back failed",
            )

            status, prescribed = _request(
                base,
                "/api/prescribe",
                method="POST",
                body={
                    "date": today,
                    "session_type": "auto",
                    "apply_selection": False,
                    "allow_unknown_readiness": True,
                    "minimum_session": False,
                    "technique_throttle": False,
                },
            )
            _assert(status == 200 and "items" in json.loads(prescribed), "prescription response invalid")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    print(f"release smoke: OK ({args.archive.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
