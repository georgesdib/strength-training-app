"""A small, dependency-free Markdown renderer for the local docs pages.

It covers what the repository's docs actually use: headings, paragraphs, lists, fenced code,
tables, blockquotes, inline code, bold/italic and links. It is deliberately not a general
Markdown implementation; adding a dependency for a local docs viewer is not worth it.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import quote

_INLINE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))")


def _inline(text: str, link_for) -> str:
    parts: list[str] = []
    for piece in _INLINE.split(text):
        if not piece:
            continue
        if piece.startswith("`") and piece.endswith("`") and len(piece) > 1:
            parts.append("<code>" + html.escape(piece[1:-1]) + "</code>")
        elif piece.startswith("**") and piece.endswith("**"):
            parts.append("<strong>" + html.escape(piece[2:-2]) + "</strong>")
        elif piece.startswith("*") and piece.endswith("*"):
            parts.append("<em>" + html.escape(piece[1:-1]) + "</em>")
        elif piece.startswith("[") and "](" in piece:
            label, target = piece[1:-1].split("](", 1)
            href = link_for(target)
            parts.append(f'<a href="{html.escape(href, quote=True)}">'
                         f"{html.escape(label)}</a>")
        else:
            parts.append(html.escape(piece))
    return "".join(parts)


def _table(lines: list[str], link_for) -> str:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    header, body = rows[0], rows[2:]
    out = ["<table><thead><tr>"]
    out += [f"<th>{_inline(cell, link_for)}</th>" for cell in header]
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>" + "".join(f"<td>{_inline(cell, link_for)}</td>" for cell in row)
                   + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _slug(text: str) -> str:
    plain = re.sub(r"`([^`]+)`", r"\1", text)
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"\*\*?([^*]+)\*\*?", r"\1", plain)
    plain = html.unescape(plain).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "section"


def render(text: str, *, docs_root: Path | None = None,
           base_dir: Path | None = None) -> str:
    def link_for(target: str) -> str:
        if target.startswith(("http://", "https://", "#", "mailto:")):
            return target
        path, _, anchor = target.partition("#")
        if path.endswith(".md") and docs_root is not None:
            candidates = []
            if base_dir is not None:
                candidates.append((base_dir / path).resolve())
            candidates.append((docs_root / path).resolve())
            for candidate in candidates:
                if candidate.is_file() and docs_root.resolve() in candidate.parents:
                    name = candidate.relative_to(docs_root).as_posix()
                    href = "#docs?doc=" + quote(name, safe="/")
                    if anchor:
                        href += "&anchor=" + quote(anchor, safe="")
                    return href
        return target

    lines = text.splitlines()
    out: list[str] = []
    used: dict[str, int] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(block)) + "</code></pre>")
            continue
        if not stripped:
            i += 1
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            level = min(level, 6)
            heading = stripped[level:].strip()
            slug = _slug(heading)
            used[slug] = used.get(slug, 0) + 1
            anchor = slug if used[slug] == 1 else f"{slug}-{used[slug]}"
            out.append(f'<h{level} id="{anchor}">'
                       f"{_inline(heading, link_for)}</h{level}>")
            i += 1
            continue
        if stripped in {"---", "***", "___"}:
            out.append("<hr>")
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table(block, link_for))
            continue
        if stripped.startswith(("- ", "* ")) or re.match(r"^\d+\.\s", stripped):
            ordered = bool(re.match(r"^\d+\.\s", stripped))
            items = []
            while i < len(lines):
                item = lines[i].strip()
                if ordered and not re.match(r"^\d+\.\s", item):
                    break
                if not ordered and not item.startswith(("- ", "* ")):
                    break
                items.append(re.sub(r"^(?:- |\* |\d+\.\s)", "", item))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(item, link_for)}</li>" for item in items)
                       + f"</{tag}>")
            continue
        if stripped.startswith(">"):
            out.append("<blockquote>" + _inline(stripped[1:].strip(), link_for)
                       + "</blockquote>")
            i += 1
            continue

        para = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(
            ("#", "|", "```", "- ", "* ", ">")
        ) and not re.match(r"^\d+\.\s", lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>" + _inline(" ".join(para), link_for) + "</p>")

    return "\n".join(out)
