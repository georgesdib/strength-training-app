#!/usr/bin/env python3
"""
Build an offline PDF containing the repository's Markdown documentation
from the latest default branch.

Usage:
    python3 build_docs_pdf.py
Optional:
    python3 build_docs_pdf.py --repo-dir /path/to/strength-training-app
    python3 build_docs_pdf.py --output strength-training-app-docs.pdf

Requirements:
    git, Python 3, reportlab
Install ReportLab if needed:
    python3 -m pip install --user reportlab
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

REPO_URL = "https://github.com/georgesdib/strength-training-app.git"
DEFAULT_DIR = Path("strength-training-app")
DEFAULT_OUTPUT = Path("strength-training-app-docs.pdf")

def run(args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)

def md_to_flowables(text, styles, preformatted):
    """Convert common Markdown constructs into readable ReportLab flowables."""
    from reportlab.platypus import (
        Paragraph, Spacer, PageBreak, Preformatted, ListFlowable, ListItem,
        Table, TableStyle, KeepTogether
    )
    from reportlab.lib import colors
    from reportlab.lib.units import inch

    out = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    in_code = False
    code_lines = []
    paragraph_lines = []
    list_items = []
    list_kind = None

    def flush_paragraph():
        nonlocal paragraph_lines
        if paragraph_lines:
            raw = " ".join(x.strip() for x in paragraph_lines).strip()
            if raw:
                # Keep inline Markdown readable; preserve emphasis and code approximately.
                raw = escape(raw)
                raw = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', raw)
                raw = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", raw)
                raw = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", raw)
                raw = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'\1 <font color="#2457A7">(\2)</font>', raw)
                out.append(Paragraph(raw, styles["BodyText"]))
                out.append(Spacer(1, 4))
            paragraph_lines = []

    def flush_list():
        nonlocal list_items, list_kind
        if list_items:
            bullets = []
            for item in list_items:
                val = escape(item)
                val = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', val)
                val = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", val)
                bullets.append(ListItem(Paragraph(val, styles["BodyText"]), leftIndent=12))
            out.append(ListFlowable(
                bullets, bulletType="bullet" if list_kind == "ul" else "1",
                start="1", leftIndent=18, bulletFontSize=7
            ))
            out.append(Spacer(1, 5))
        list_items = []
        list_kind = None

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            flush_paragraph()
            flush_list()
            if not in_code:
                in_code = True
                code_lines = []
            else:
                out.append(Preformatted("\n".join(code_lines), preformatted))
                out.append(Spacer(1, 6))
                in_code = False
                code_lines = []
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if not line.strip():
            flush_paragraph()
            flush_list()
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = min(len(heading.group(1)), 4)
            htxt = escape(heading.group(2))
            if level == 1 and out:
                out.append(Spacer(1, 8))
            out.append(Paragraph(htxt, styles[f"Heading{level}"]))
            out.append(Spacer(1, 5))
            i += 1
            continue

        if re.match(r"^\s*([-*_])\s*\1\s*\1+\s*$", line):
            flush_paragraph()
            flush_list()
            out.append(Spacer(1, 6))
            i += 1
            continue

        # Tables: turn each pipe-delimited row into a simple text row.
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[i+1]):
            flush_paragraph()
            flush_list()
            rows = []
            while i < len(lines) and "|" in lines[i]:
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
                    rows.append([Paragraph(escape(c), styles["SmallText"]) for c in cells])
                i += 1
            if rows:
                max_cols = max(len(r) for r in rows)
                rows = [r + [Paragraph("", styles["SmallText"])] * (max_cols-len(r)) for r in rows]
                widths = [6.6 * inch / max_cols] * max_cols
                tbl = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
                tbl.setStyle(TableStyle([
                    ("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
                    ("BACKGROUND", (0,0), (-1,0), colors.whitesmoke),
                    ("VALIGN", (0,0), (-1,-1), "TOP"),
                    ("LEFTPADDING", (0,0), (-1,-1), 4),
                    ("RIGHTPADDING", (0,0), (-1,-1), 4),
                    ("TOPPADDING", (0,0), (-1,-1), 3),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 3),
                ]))
                out.append(tbl)
                out.append(Spacer(1, 8))
            continue

        bullet = re.match(r"^\s*[-+*]\s+(.+)$", line)
        numbered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if bullet or numbered:
            flush_paragraph()
            kind = "ul" if bullet else "ol"
            if list_kind and kind != list_kind:
                flush_list()
            list_kind = kind
            list_items.append((bullet or numbered).group(1))
            i += 1
            continue

        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            flush_list()
            paragraph_lines.append(quote.group(1))
            i += 1
            continue

        flush_list()
        paragraph_lines.append(line)
        i += 1

    flush_paragraph()
    flush_list()
    if in_code and code_lines:
        out.append(Preformatted("\n".join(code_lines), preformatted))
    return out

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", type=Path, default=None,
                        help="use an existing checkout (does not update or modify it)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    temp_root = None
    if args.repo_dir is None:
        # Clone into a temporary directory so the user's existing checkout and
        # uncommitted work are never modified.
        temp_root = tempfile.TemporaryDirectory(prefix="strength-coach-docs-")
        repo = Path(temp_root.name) / "strength-training-app"
        run(["git", "clone", "--depth", "1", REPO_URL, str(repo)])
    else:
        repo = args.repo_dir.resolve()
        if not (repo / ".git").exists():
            sys.exit(f"Not a Git checkout: {repo}. Omit --repo-dir to clone the latest main branch safely.")

    try:
        import reportlab
    except ImportError:
        sys.exit("Missing ReportLab. Install it with: python3 -m pip install --user reportlab")

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted

    # Include Markdown documentation throughout the repo, excluding vendored/generated folders.
    excluded = {".git", ".venv", "venv", "node_modules", "dist", "build", ".pytest_cache"}
    files = []
    for p in repo.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".md", ".markdown", ".rst"}:
            continue
        rel = p.relative_to(repo)
        if any(part in excluded for part in rel.parts):
            continue
        files.append(p)
    files.sort(key=lambda p: (0 if p.name.lower() == "readme.md" else 1, str(p.relative_to(repo)).lower()))

    if not files:
        sys.exit("No Markdown documentation files found.")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Heading1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=22, spaceBefore=8, textColor=colors.HexColor("#17365D")))
    styles.add(ParagraphStyle(name="Heading2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=14, leading=18, spaceBefore=7, textColor=colors.HexColor("#24476B")))
    styles.add(ParagraphStyle(name="Heading3", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=6))
    styles.add(ParagraphStyle(name="Heading4", parent=styles["Heading4"], fontName="Helvetica-Bold", fontSize=10, leading=12, spaceBefore=5))
    styles.add(ParagraphStyle(name="SmallText", parent=styles["BodyText"], fontSize=7.5, leading=9))
    styles["BodyText"].fontName = "Helvetica"
    styles["BodyText"].fontSize = 8.5
    styles["BodyText"].leading = 11
    styles["BodyText"].spaceAfter = 3
    pre = ParagraphStyle(name="CodeBlock", fontName="Courier", fontSize=6.5, leading=8, leftIndent=6, rightIndent=6, borderColor=colors.lightgrey, borderWidth=0.4, borderPadding=5, backColor=colors.HexColor("#F6F7F8"), spaceBefore=3, spaceAfter=6)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(0.65 * inch, 0.42 * inch, "Strength Training App — documentation snapshot")
        canvas.drawRightString(A4[0] - 0.65 * inch, 0.42 * inch, f"Page {doc.page}")
        canvas.restoreState()

    story = [
        Paragraph("Strength Training App", styles["Title"]),
        Paragraph("Offline Documentation Compendium", ParagraphStyle("Subtitle", parent=styles["BodyText"], alignment=TA_CENTER, fontSize=12, leading=16)),
        Spacer(1, 10),
        Paragraph("Source: latest main branch of github.com/georgesdib/strength-training-app", styles["BodyText"]),
        Paragraph(f"Generated from {len(files)} Markdown/RST files. Source revision: " + subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=repo, text=True).strip(), styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Contents", styles["Heading1"]),
    ]
    for p in files:
        rel = p.relative_to(repo).as_posix()
        story.append(Paragraph(escape(rel), styles["BodyText"]))
    for p in files:
        rel = p.relative_to(repo).as_posix()
        story.append(PageBreak())
        story.append(Paragraph(escape(rel), styles["Heading1"]))
        story.append(Spacer(1, 4))
        content = p.read_text(encoding="utf-8", errors="replace")
        story.extend(md_to_flowables(content, styles, pre))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(args.output), pagesize=A4,
        rightMargin=0.62*inch, leftMargin=0.62*inch,
        topMargin=0.62*inch, bottomMargin=0.68*inch,
        title="Strength Training App — Offline Documentation",
        author="Generated from GitHub repository"
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"Created {args.output.resolve()} with {len(files)} documents.")
    if temp_root is not None:
        temp_root.cleanup()

if __name__ == "__main__":
    main()
