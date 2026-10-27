"""Static frontend contracts.

The browser workflow is covered by the manual checklist in docs/WEB-UI.md. These checks
cover the parts that must never regress silently: executable inline handlers, missing
script files, escaping regressions and unsafe date/error patterns added by later workstreams.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "strength_coach/web/static"
INDEX = STATIC / "index.html"

# An inline event handler is an attribute assigned a string. A property assignment such as
# element.onclick = fn is not this pattern and is allowed.
INLINE_HANDLER_RE = re.compile(r'\bon[a-z]+\s*=\s*["\']')


def _static_files() -> list[Path]:
    return [INDEX, *sorted(STATIC.glob("*.js"))]


def test_no_inline_event_handlers() -> None:
    offenders = []
    for path in _static_files():
        text = path.read_text(encoding="utf-8")
        for match in INLINE_HANDLER_RE.finditer(text):
            line = text[:match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0)}")
    assert offenders == []


def test_every_referenced_script_exists() -> None:
    page = INDEX.read_text(encoding="utf-8")
    srcs = re.findall(r'<script src="([^"]+)"', page)
    assert srcs
    for src in srcs:
        assert src.startswith("/static/"), src
        assert (STATIC / src.removeprefix("/static/")).is_file(), src

def test_script_load_order() -> None:
    page = INDEX.read_text(encoding="utf-8")
    order = [src.removeprefix("/static/")
             for src in re.findall(r'<script src="([^"]+)"', page)]
    assert order.index("app.js") < order.index("history.js")
    assert order.index("app.js") < order.index("workout.js")
    if "core.js" in order:
        assert order.index("core.js") == 0


def test_scripts_parse() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    for path in sorted(STATIC.glob("*.js")):
        subprocess.run([node, "--check", str(path)], check=True,
                       capture_output=True, text=True)



def test_esc_escapes_html_metacharacters() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = "\n".join(path.read_text(encoding="utf-8")
                        for path in (STATIC / "app.js", STATIC / "core.js") if path.exists())
    match = re.search(r"function esc\(value\) \{[\s\S]*?\n\}", source)
    assert match, "esc() not found in the client bundle"
    script = (
        f"eval({json.dumps(match.group(0))});"
        "const got = esc(\"'\\\"><&\");"
        "if (got !== \"&#39;&quot;&gt;&lt;&amp;\") throw new Error(got);"
    )
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

def test_no_utc_or_locale_date_contract() -> None:
    source = "\n".join(path.read_text(encoding="utf-8")
                        for path in (STATIC / "app.js", STATIC / "core.js") if path.exists())
    assert "toISOString().slice(0, 10)" not in source
    assert "toLocaleDateString" not in source


def test_format_local_date_uses_the_local_calendar_day() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = "\n".join(path.read_text(encoding="utf-8")
                        for path in (STATIC / "app.js", STATIC / "core.js") if path.exists())
    functions = []
    for name in ("pad2", "formatLocalDate"):
        match = re.search(rf"function {name}\([^)]*\) \{{[\s\S]*?\n\}}", source)
        assert match, f"{name}() not found in the client bundle"
        functions.append(match.group(0))
    script = (
        "".join(f"eval({json.dumps(fn)});" for fn in functions)
        + "const cases = ["
        + "[new Date('2026-01-01T00:30:00Z'), '2025-12-31'],"
        + "[new Date(2026, 0, 1, 0, 0), '2026-01-01'],"
        + "[new Date('not-a-date'), ''],"
        + "[new Date(2026, 2, 8, 12, 0), '2026-03-08'],"
        + "];"
        + "for (const [date, expected] of cases) {"
        + "  const got = formatLocalDate(date);"
        + "  if (got !== expected) throw new Error(expected + ' != ' + got);"
        + "}"
    )
    env = {**os.environ, "TZ": "America/New_York"}
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, env=env)
