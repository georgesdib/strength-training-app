"""The combined documentation PDF must include every public Markdown document."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import docs_pdf

ROOT = Path(__file__).resolve().parents[1]


def test_collection_covers_root_docs_and_the_whole_docs_tree():
    documents = docs_pdf.collect_documents()
    relative = [document.relative for document in documents]

    assert relative[:5] == [
        "README.md",
        "USER-GUIDE.md",
        "ROADMAP.md",
        "AGENTS.md",
        "CHANGELOG.md",
    ]
    expected_docs = sorted(
        path.relative_to(ROOT).as_posix() for path in (ROOT / "docs").rglob("*.md")
    )
    assert relative[5:] == expected_docs
    assert len({document.path for document in documents}) == len(documents)


def test_titles_come_from_the_first_heading():
    documents = docs_pdf.collect_documents()
    by_path = {document.relative: document for document in documents}
    assert by_path["docs/WORKOUT-GENERATION.md"].title == "How Workout Generation Works"
    assert by_path["README.md"].title == "Evidence-Based Strength Coach"


def test_links_between_bundled_documents_become_internal_anchors():
    documents = docs_pdf.collect_documents()
    by_path = {document.relative: document for document in documents}
    source = by_path["docs/ARCHITECTURE.md"]

    text = "[plan](LLM-INTEGRATION-PLAN.md) and [section](#components)"
    rewritten = docs_pdf.rewrite_links(text, source, documents)
    assert "#doc-docs-llm-integration-plan" in rewritten
    assert "#docs-architecture-components" in rewritten

    route = docs_pdf.rewrite_links(
        "[ui](#docs?doc=docs/WEB-UI.md&anchor=pages)", source, documents
    )
    assert "#docs-web-ui-pages" in route


def test_links_outside_the_bundle_keep_their_label_without_a_dead_target():
    documents = docs_pdf.collect_documents()
    by_path = {document.relative: document for document in documents}
    source = by_path["docs/CORE-TRAINING.md"]

    text = "[config](../config/templates/session-types.v1.yaml)"
    assert docs_pdf.rewrite_links(text, source, documents) == "config"


def test_fenced_markdown_examples_are_not_rewritten():
    documents = docs_pdf.collect_documents()
    source = next(document for document in documents if document.relative == "docs/UI-MAP.md")
    text = "\n".join([
        "```markdown",
        "- **Evidence:** [REFERENCES.md](REFERENCES.md)",
        "```",
    ])
    assert docs_pdf.rewrite_links(text, source, documents) == text


def test_every_document_receives_a_unique_section_and_heading_prefix():
    documents = docs_pdf.collect_documents()
    section_ids = [document.section_id for document in documents]
    slugs = [document.slug for document in documents]
    assert len(set(section_ids)) == len(section_ids)
    assert len(set(slugs)) == len(slugs)

    body = docs_pdf.build_html(documents[:2])
    assert 'id="doc-readme"' in body
    assert 'id="doc-user-guide"' in body
    assert "target-counter" in body


def test_help_documents_usage_and_options(capsys):
    with pytest.raises(SystemExit) as exc:
        docs_pdf.main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Build one PDF from the public documentation set." in output
    assert "--output" in output
    assert "--include" in output
    assert "tools/docs_pdf.py --help" in output
    assert "Usage" in (docs_pdf.__doc__ or "")


def test_render_pdf_writes_a_pdf(tmp_path):
    pytest.importorskip("markdown")
    pytest.importorskip("weasyprint")
    output = tmp_path / "docs.pdf"
    documents = docs_pdf.collect_documents()[:3]

    pages = docs_pdf.render_pdf(documents, output, title="Test bundle")

    assert pages > 0
    assert output.read_bytes().startswith(b"%PDF")
