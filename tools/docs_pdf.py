#!/usr/bin/env python
"""Build one PDF from the public documentation set.

Usage
-----
    .venv/bin/python tools/docs_pdf.py                  # write the default PDF
    .venv/bin/python tools/docs_pdf.py --help           # show every option
    .venv/bin/python tools/docs_pdf.py --list           # show what will be included
    .venv/bin/python tools/docs_pdf.py -o build/docs.pdf
    .venv/bin/python tools/docs_pdf.py --title "My docs" --include data/README.md

By default the bundle contains README, USER-GUIDE, ROADMAP, AGENTS, CHANGELOG and every
Markdown file under docs/, in that order. Links between included documents become internal
PDF links; links to code, config or personal paths stay readable text rather than dangling
targets. The PDF is a build artifact, not source (dist/ is git-ignored).

Install the optional docs dependencies once:

    .venv/bin/pip install -e '.[docs]'
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_OUTPUT = ROOT / "dist" / "strength-coach-docs.pdf"
DEFAULT_TITLE = "Strength Coach documentation"
ROOT_DOCUMENTS = ("README.md", "USER-GUIDE.md", "ROADMAP.md", "AGENTS.md", "CHANGELOG.md")

EPILOG = """examples:
  .venv/bin/python tools/docs_pdf.py
      Write dist/strength-coach-docs.pdf from the default document set.
  .venv/bin/python tools/docs_pdf.py --list
      Print each included document and its title without rendering.
  .venv/bin/python tools/docs_pdf.py -o build/docs.pdf --title "Strength Coach"
      Choose the output path and the cover/PDF title.
  .venv/bin/python tools/docs_pdf.py --include data/README.md
      Add a Markdown file outside the default set (repeat --include as needed).
  .venv/bin/python tools/docs_pdf.py --help
      Show this help text again.

The PDF is generated locally; nothing is uploaded. Install the optional docs dependencies first:
  .venv/bin/pip install -e '.[docs]'
"""

# Fenced blocks must not be scanned for links: a documentation example may contain Markdown.
FENCE_RE = re.compile(r"(^```.*?^```[ \t]*$)", re.MULTILINE | re.DOTALL)
LINK_RE = re.compile(r'(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
HEADING_ID_RE = re.compile(r'(<h[1-6]\b[^>]*\bid=")([^"]+)(")')
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


@dataclass(frozen=True)
class Document:
    path: Path
    relative: str
    title: str

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.relative.lower().removesuffix(".md")).strip("-")

    @property
    def section_id(self) -> str:
        return f"doc-{self.slug}"


def _plain_title(text: str) -> str:
    """Turn the first heading's inline Markdown into a TOC label."""
    text = LINK_RE.sub(lambda match: match.group(1), text)
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def title_for(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return path.stem
    for line in text.splitlines():
        if line.startswith("# "):
            return _plain_title(line[2:].strip()) or path.stem
    return path.stem


def collect_documents(
    root: Path = ROOT, include: list[str] | tuple[str, ...] = ()
) -> list[Document]:
    """All public Markdown docs, in reading order, with no duplicates."""
    paths: list[Path] = []
    for name in ROOT_DOCUMENTS:
        path = root / name
        if path.is_file():
            paths.append(path)
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        paths.extend(sorted(docs_dir.rglob("*.md")))
    for item in include:
        path = Path(item)
        if not path.is_absolute():
            path = root / path
        paths.append(path)

    seen: set[Path] = set()
    documents: list[Document] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not resolved.is_file():
            raise FileNotFoundError(f"document not found: {path}")
        try:
            relative = resolved.relative_to(root.resolve()).as_posix()
        except ValueError:
            relative = resolved.name
        documents.append(Document(resolved, relative, title_for(resolved)))
    return documents


def _rewrite_link(match: re.Match[str], source: Document, by_path: dict[Path, Document]) -> str:
    label, target = match.group(1), match.group(2)
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    if not target or target == "#":
        return label
    if target.startswith("#docs?"):
        # Web-app routes such as #docs?doc=docs/WEB-UI.md&anchor=pages become real PDF links
        # when the target is bundled; otherwise the label is more useful than a dead anchor.
        route = urlsplit(target).fragment.partition("?")[2]
        params = parse_qs(route)
        doc_path = (params.get("doc") or [None])[0]
        if doc_path:
            destination = by_path.get((ROOT / doc_path).resolve())
            if destination is not None:
                anchor = (params.get("anchor") or [None])[0]
                if anchor:
                    return f"[{label}](#{destination.slug}-{anchor})"
                return f"[{label}](#{destination.section_id})"
        return label
    if target.startswith("#"):
        return f"[{label}](#{source.slug}-{target[1:]})"
    if target.startswith("//") or SCHEME_RE.match(target):
        return match.group(0)

    parsed = urlsplit(target)
    path_part = unquote(parsed.path)
    if not path_part:
        fragment = parsed.fragment
        return f"[{label}](#{source.slug}-{fragment})" if fragment else match.group(0)

    candidate = (source.path.parent / path_part).resolve()
    destination = by_path.get(candidate)
    if destination is None:
        # A config/code path cannot be a useful link inside a PDF; keep its readable label.
        return label
    if parsed.fragment:
        return f"[{label}](#{destination.slug}-{parsed.fragment})"
    return f"[{label}](#{destination.section_id})"


def rewrite_links(text: str, source: Document, documents: list[Document]) -> str:
    """Point links between bundled documents at their internal PDF anchors."""
    by_path = {document.path: document for document in documents}
    parts = FENCE_RE.split(text)
    out: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:  # fenced code block: leave example Markdown untouched
            out.append(part)
        else:
            out.append(LINK_RE.sub(lambda match: _rewrite_link(match, source, by_path), part))
    return "".join(out)


def _prefix_heading_ids(body: str, slug: str) -> str:
    """Keep heading ids unique across the bundle so links cannot collide."""
    return HEADING_ID_RE.sub(
        lambda match: f"{match.group(1)}{slug}-{match.group(2)}{match.group(3)}", body
    )


def _markdown_to_html(text: str) -> str:
    import markdown

    editor = markdown.Markdown(
        extensions=["extra", "toc", "sane_lists"],
        extension_configs={"toc": {"permalink": False}},
        output_format="html5",
    )
    return editor.convert(text)


def build_html(documents: list[Document], title: str = DEFAULT_TITLE) -> str:
    """Build one self-contained HTML document, ready for WeasyPrint."""
    toc: list[str] = []
    sections: list[str] = []
    for document in documents:
        source = document.path.read_text(encoding="utf-8")
        body = _prefix_heading_ids(
            _markdown_to_html(rewrite_links(source, document, documents)), document.slug
        )
        sections.append(
            f'<section class="doc" id="{document.section_id}">'
            f'<div class="source">{html.escape(document.relative)}</div>'
            f"{body}</section>"
        )
        toc.append(
            f'<li><a href="#{document.section_id}">'
            f'<span class="toc-title">{html.escape(document.title)}</span>'
            f'<span class="toc-path">{html.escape(document.relative)}</span></a></li>'
        )

    cover = f"""
    <section class="cover">
      <div class="cover-kicker">Documentation bundle</div>
      <h1>{html.escape(title)}</h1>
      <p class="cover-copy">All public Markdown documentation rendered as one searchable PDF.</p>
      <p class="cover-meta">{len(documents)} documents · generated {date.today().isoformat()}</p>
    </section>
    """
    contents = f"""
    <section class="toc">
      <h2>Contents</h2>
      <ol class="toc-list">{''.join(toc)}</ol>
    </section>
    """
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
{cover}
{contents}
{''.join(sections)}
</body>
</html>
"""


CSS = """
@page {
  size: A4;
  margin: 19mm 16mm 18mm 16mm;
  @top-left {
    content: "Strength Coach documentation";
    color: #6b7280;
    font-size: 7.5pt;
  }
  @top-right {
    content: string(doctitle);
    color: #6b7280;
    font-size: 7.5pt;
  }
  @bottom-center {
    content: counter(page);
    color: #6b7280;
    font-size: 8pt;
  }
}
@page cover {
  margin: 0;
  @top-left { content: none; }
  @top-right { content: none; }
  @bottom-center { content: none; }
}
html { font-size: 9.5pt; }
body {
  margin: 0;
  color: #1f2933;
  font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
  line-height: 1.45;
}
.cover {
  page: cover;
  height: 297mm;
  padding: 42mm 28mm 28mm;
  box-sizing: border-box;
  background: #123047;
  color: #f8fafc;
}
.cover-kicker {
  color: #9cc3dd;
  font-size: 10pt;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.cover h1 {
  margin: 14mm 0 8mm;
  font-size: 28pt;
  line-height: 1.15;
  bookmark-level: none;
}
.cover-copy { max-width: 125mm; font-size: 12pt; color: #d7e6f0; }
.cover-meta { margin-top: 42mm; font-size: 9pt; color: #9cc3dd; }
.toc { break-before: page; }
.toc h2 { font-size: 20pt; margin: 0 0 8mm; bookmark-level: 1; bookmark-label: "Contents"; }
.toc-list { margin: 0; padding: 0; list-style: none; }
.toc li { border-bottom: 0.5pt solid #d9dee5; padding: 2.4mm 0; }
.toc a { color: inherit; text-decoration: none; }
.toc-title { font-weight: bold; }
.toc-path { float: right; color: #6b7280; font-family: "DejaVu Sans Mono", monospace; font-size: 8pt; }
.toc a::after { content: target-counter(attr(href), page); float: right; margin-left: 4mm; color: #374151; }
section.doc { break-before: page; }
section.doc h1 { string-set: doctitle content(); }
.source {
  color: #6b7280;
  font-family: "DejaVu Sans Mono", monospace;
  font-size: 7.5pt;
  margin-bottom: 3mm;
}
h1, h2, h3, h4, h5, h6 { color: #123047; line-height: 1.25; bookmark-level: auto; }
h1 { font-size: 20pt; margin: 0 0 5mm; bookmark-level: 1; }
h2 { font-size: 14pt; margin: 7mm 0 3mm; bookmark-level: 2; }
h3 { font-size: 11.5pt; margin: 5mm 0 2mm; bookmark-level: 3; }
h4 { font-size: 10pt; margin: 4mm 0 1.5mm; bookmark-level: 4; }
p { margin: 0 0 2.4mm; }
ul, ol { margin: 0 0 2.8mm; padding-left: 6mm; }
li { margin: 0.5mm 0; }
blockquote { margin: 3mm 0; padding: 2mm 4mm; border-left: 2.5pt solid #9cc3dd; color: #374151; }
a { color: #155e91; text-decoration: none; }
code {
  font-family: "DejaVu Sans Mono", monospace;
  font-size: 8.2pt;
  background: #f1f5f9;
  padding: 0 0.6mm;
  border-radius: 1pt;
}
pre {
  background: #f4f6f8;
  border: 0.5pt solid #d9dee5;
  border-radius: 2pt;
  padding: 2.5mm 3mm;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 8pt;
  line-height: 1.35;
  margin: 2.5mm 0 3.5mm;
}
pre code { background: none; padding: 0; font-size: 7.8pt; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 2.5mm 0 4mm;
  font-size: 7.8pt;
  line-height: 1.3;
}
th, td { border: 0.5pt solid #c9d0d8; padding: 1.3mm 1.6mm; vertical-align: top; text-align: left; }
th { background: #eaf0f4; color: #123047; }
tr { break-inside: avoid; }
hr { border: none; border-top: 0.7pt solid #c9d0d8; margin: 5mm 0; }
img { max-width: 100%; }
"""


def render_pdf(
    documents: list[Document],
    output: Path = DEFAULT_OUTPUT,
    title: str = DEFAULT_TITLE,
    base_url: Path = ROOT,
) -> int:
    """Render the bundle and return its page count."""
    try:
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover - depends on the optional extra
        raise RuntimeError(
            "PDF generation needs the optional docs dependencies; run "
            ".venv/bin/pip install -e '.[docs]'"
        ) from exc

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = HTML(string=build_html(documents, title), base_url=str(base_url)).render()
    document.write_pdf(str(output))
    return len(document.pages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build one PDF from the public documentation set.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=DEFAULT_OUTPUT,
        help=f"PDF path (default: {DEFAULT_OUTPUT.relative_to(ROOT)})",
    )
    parser.add_argument("--title", default=DEFAULT_TITLE, help="cover and PDF title")
    parser.add_argument(
        "--include", action="append", default=[], metavar="PATH",
        help="additional Markdown file, relative to the repository root (repeatable)",
    )
    parser.add_argument("--list", action="store_true", help="print the document list and exit")
    args = parser.parse_args(argv)

    try:
        documents = collect_documents(include=args.include)
        if args.list:
            for document in documents:
                print(f"{document.relative}\t{document.title}")
            print(f"{len(documents)} documents")
            return 0
        pages = render_pdf(documents, args.output, args.title)
    except (FileNotFoundError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"wrote {args.output} ({len(documents)} documents, {pages} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
