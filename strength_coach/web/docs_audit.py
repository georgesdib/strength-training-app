"""Audit the UI documentation contract (P4).

Checks the static page and every document it links to. Kept under the web layer because it is
a UI contract, but it has no server dependency and can run in tests or from tools/.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs

from strength_coach.web import markdown


@dataclass(frozen=True)
class Finding:
    kind: str
    where: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.where}: {self.detail}"


FIELDS = ("Decisions", "Open questions", "Roadmap")


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _doc_target(root: Path, href: str) -> tuple[Path | None, str | None, str | None]:
    if not href.startswith("#docs?"):
        return None, None, "link is not a docs route"
    params = parse_qs(href.split("?", 1)[1])
    name = (params.get("doc") or [None])[0]
    if not name:
        return None, None, "missing doc parameter"
    path = (root / name).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None, None, "doc escapes the repository"
    if not path.is_file():
        return None, None, f"doc does not exist: {name}"
    return path, (params.get("anchor") or [None])[0], None


def audit(root: Path | None = None) -> list[Finding]:
    root = (root or _root()).resolve()
    index = root / "strength_coach/web/static/index.html"
    text = index.read_text(encoding="utf-8")
    findings: list[Finding] = []
    docs: set[Path] = set()

    panel_re = re.compile(r'<div class="panel-head"[^>]*>([\s\S]*?)</div>')
    heading_re = re.compile(r"<h([23])[^>]*>([\s\S]*?)</h\1>")
    help_re = re.compile(r'^<p class="section-help">([\s\S]*?)</p>')
    link_re = re.compile(r'<a class="doc-link" href="([^"]+)">([^<]*)</a>')

    for match in panel_re.finditer(text):
        heading = heading_re.search(match.group(1))
        if not heading:
            continue
        title = re.sub(r"<[^>]+>", "", heading.group(2)).strip()
        after = text[match.end():].lstrip()
        help_match = help_re.match(after)
        where = f"panel {title!r}"
        if not help_match:
            findings.append(Finding("missing-help", where, "no section-help follows panel-head"))
            continue
        links = link_re.findall(help_match.group(1))
        if len(links) != 1:
            findings.append(Finding("bad-link-count", where, f"expected one doc-link, found {len(links)}"))
            continue
        raw_href, label = links[0]
        href = html.unescape(raw_href)
        path, anchor, error = _doc_target(root, href)
        if error:
            findings.append(Finding("bad-doc-link", where, error))
            continue
        assert path is not None
        if not label.strip():
            findings.append(Finding("empty-link-label", where, href))
        if anchor:
            rendered = markdown.render(path.read_text(encoding="utf-8"),
                                       docs_root=root, base_dir=path.parent)
            if f'id="{anchor}"' not in rendered:
                findings.append(Finding("bad-anchor", where, f"{path.name}#{anchor} missing"))
        docs.add(path)

    for path in sorted(docs):
        page = path.read_text(encoding="utf-8")
        if "## Related" not in page:
            findings.append(Finding("missing-related", str(path), "no ## Related footer"))
            continue
        footer = page.rsplit("## Related", 1)[-1]
        for field in FIELDS:
            if f"**{field}:**" not in footer:
                findings.append(Finding("related-field", str(path), f"missing {field}"))
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", footer):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            clean = target.split("#", 1)[0]
            if clean and not (path.parent / clean).exists():
                findings.append(Finding("broken-related", str(path), target))

    return findings


def report(root: Path | None = None) -> str:
    findings = audit(root)
    if not findings:
        return "UI documentation contract: OK"
    return "\n".join(str(item) for item in findings)
