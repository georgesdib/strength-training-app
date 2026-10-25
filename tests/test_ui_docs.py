"""P4: the UI documentation contract must stay green."""

from __future__ import annotations

from pathlib import Path

from strength_coach.web import docs_audit


def test_ui_documentation_contract_is_clean():
    assert docs_audit.audit() == []


def test_audit_catches_a_missing_help_block(tmp_path):
    root = tmp_path
    (root / "strength_coach/web/static").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "docs" / "EXISTING.md").write_text(
        "# Existing\n\n## Related\n\n"
        "- **Decisions:** [DECISIONS.md](DECISIONS.md)\n"
        "- **Open questions:** [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md)\n"
        "- **Roadmap:** [ROADMAP.md](../ROADMAP.md)\n"
    )
    (root / "docs" / "DECISIONS.md").write_text("# Decisions\n")
    (root / "docs" / "OPEN-QUESTIONS.md").write_text("# Questions\n")
    (root / "ROADMAP.md").write_text("# Roadmap\n")
    (root / "strength_coach/web/static/index.html").write_text(
        '<div class="panel"><div class="panel-head"><h2>No help</h2></div>'
        '<div id="x"></div></div>'
    )
    findings = docs_audit.audit(root)
    assert any(item.kind == "missing-help" for item in findings)


def test_audit_catches_broken_js_docs_link(tmp_path):
    root = tmp_path
    (root / "strength_coach/web/static").mkdir(parents=True)
    (root / "strength_coach/web/static/index.html").write_text(
        '<div class="panel"><div class="panel-head"><h2>No help</h2></div>'
        '<div id="x"></div></div>'
    )
    (root / "strength_coach/web/static/app.js").write_text(
        '<a href="#docs?doc=MISSING.md">x</a>'
    )
    findings = docs_audit.audit(root)
    assert any(item.kind == "bad-js-doc-link" for item in findings)
