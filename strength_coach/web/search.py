"""Deterministic search over the web UI's views, panels, settings and docs.

Domain reason: "where can I see X?" and "where do I change Y?" are navigation questions, not
generation questions. The index is built from the files this server already serves -- the static
page, the settings registry and the public docs -- so a result can never point at a view, panel,
field or anchor that does not exist. Ranking is local and deterministic; no model is involved and
nothing is persisted.

The client never builds targets: it calls GET /api/search and activates whatever comes back.
"""

from __future__ import annotations

import html
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from strength_coach import settings_registry
from strength_coach.utils import docs_manifest
from strength_coach.web import markdown

MAX_QUERY = 120
DEFAULT_LIMIT = 20
MAX_LIMIT = 50

KIND_ORDER = {"setting": 0, "panel": 1, "view": 2, "doc": 3}

# Generic words that say "show me where", not "which thing". Dropping them keeps
# "where can I see the table of symptoms" focused on "symptoms".
STOPWORDS = frozenset({
    "a", "about", "an", "and", "area", "are", "at", "be", "button", "can", "change", "do", "does",
    "field", "find", "for", "from", "get", "go", "how", "i", "in", "into", "is", "it", "list",
    "located", "me", "modify", "my", "of", "on", "open", "option", "options", "or", "page",
    "screen", "section", "see", "set", "show", "table", "that", "the", "this", "to", "view",
    "where", "with",
})

# Everyday words for a surface, mapped to the vocabulary the UI actually uses. Aliases score
# below a direct hit so "resolver" never matches a "dwell" query more strongly than "dwell".
ALIASES = {
    "symptom": ("soreness", "niggle", "ache", "injury", "pain"),
    "dwell": ("resolver", "rotation", "exposure"),
    "deload": ("backoff", "back-off", "reactive"),
}

#: Historical docs stay searchable but must not outrank the live UI.
ARCHIVE_PREFIX = "docs/archive/"

_ROOT = Path(__file__).resolve().parents[2]

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9]+")
_NON_ID = re.compile(r"[^A-Za-z0-9_-]")

_NAV = re.compile(r'<nav id="nav"[^>]*>(?P<body>.*?)</nav>', re.S)
_NAV_GROUP = re.compile(
    r'<details class="nav-group"[^>]*>\s*<summary>(?P<group>.*?)</summary>'
    r"(?P<body>.*?)</details>",
    re.S,
)
_NAV_BUTTON = re.compile(
    r'<button data-view="(?P<view>[^"]+)"[^>]*>(?P<label>.*?)</button>', re.S
)
_SECTION = re.compile(r'<section id="view-(?P<view>[a-z0-9-]+)"[^>]*>')
_PANEL = re.compile(r'<div class="(?P<classes>panel(?:\s[^"]*)?)"(?P<attrs>[^>]*)>')
_PANEL_ID = re.compile(r'id="(?P<id>[^"]+)"')
_PANEL_HEAD = re.compile(r'<div class="panel-head"[^>]*>(?P<body>.*?)</div>', re.S)
_PANEL_HEADING = re.compile(
    r"<h(?P<level>[23])[^>]*>(?P<title>.*?)</h(?P=level)>", re.S
)
_HELP = re.compile(r'\s*<p class="section-help">(?P<body>.*?)</p>', re.S)
_ANY_ID = re.compile(r'id="(?P<id>[^"]+)"')

_HEADING = re.compile(r"^(?P<level>#{2,3})\s+(?P<title>.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(?:\x60{3}|~~~)")


@dataclass(frozen=True)
class Entry:
    """One searchable surface. Targets are DOM ids or doc anchors, never free text."""

    kind: str
    title: str
    subtitle: str = ""
    view: str = ""
    target: str = ""
    doc: str = ""
    anchor: str = ""
    body: str = ""

    def as_result(self, score: float) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "score": score,
            "title": self.title,
            "subtitle": self.subtitle,
            "view": self.view,
            "target": self.target,
            "doc": self.doc,
            "anchor": self.anchor,
        }


@dataclass(frozen=True)
class _Surface:
    """An entry with its fields lowercased once for one build of the index."""

    entry: Entry
    title: str
    subtitle_text: str
    body_text: str


def _clean(fragment: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", fragment))).strip()


def _nav_entries(text: str) -> dict[str, tuple[str, str]]:
    """Map a view id to its nav label and group."""
    block = _NAV.search(text)
    if block is None:
        return {}
    body = block.group("body")
    entries: dict[str, tuple[str, str]] = {}
    first_group = _NAV_GROUP.search(body)
    head = body[: first_group.start()] if first_group else body
    for match in _NAV_BUTTON.finditer(head):
        entries[match.group("view")] = (_clean(match.group("label")), "Home")
    for group_match in _NAV_GROUP.finditer(body):
        group = _clean(group_match.group("group"))
        for match in _NAV_BUTTON.finditer(group_match.group("body")):
            entries[match.group("view")] = (_clean(match.group("label")), group)
    return entries


def _view_entries(text: str) -> list[Entry]:
    nav = _nav_entries(text)
    entries = []
    for match in _SECTION.finditer(text):
        view = match.group("view")
        label, group = nav.get(view, (view.replace("-", " ").title(), ""))
        entries.append(
            Entry(kind="view", title=label, subtitle=group, view=view, target="view-" + view)
        )
    return entries


def _panel_entries(text: str) -> list[Entry]:
    sections = [(match.start(), match.group("view")) for match in _SECTION.finditer(text)]
    starts = [match.start() for match in _PANEL.finditer(text)]
    nav = _nav_entries(text)
    entries = []
    for position, match in enumerate(_PANEL.finditer(text)):
        end = starts[position + 1] if position + 1 < len(starts) else len(text)
        slice_ = text[match.end():end]
        view = ""
        for start, name in sections:
            if start <= match.start():
                view = name
        if not view:
            continue
        head = _PANEL_HEAD.search(slice_)
        if head is None:
            continue
        heading = _PANEL_HEADING.search(head.group("body"))
        if heading is None:
            continue
        title = _clean(heading.group("title"))
        if not title:
            continue
        help_match = _HELP.match(slice_[head.end():])
        body = _clean(help_match.group("body")) if help_match else ""
        own_id = _PANEL_ID.search(match.group("attrs"))
        target = own_id.group("id") if own_id else ""
        if not target:
            inner = _ANY_ID.search(slice_)
            target = inner.group("id") if inner else ""
        label = nav.get(view, (view.replace("-", " ").title(), ""))[0]
        entries.append(
            Entry(
                kind="panel",
                title=title,
                subtitle=label,
                view=view,
                target=target,
                body=body,
            )
        )
    return entries


def _doc_entries(root: Path) -> list[Entry]:
    entries: list[Entry] = []
    for doc in docs_manifest.public_docs():
        try:
            text = (root / doc.path).read_text(encoding="utf-8")
        except OSError:
            continue
        entries.append(Entry(kind="doc", title=doc.title, subtitle=doc.path, doc=doc.path))
        used: dict[str, int] = {}
        fenced = False
        for line in text.splitlines():
            if _FENCE.match(line):
                fenced = not fenced
                continue
            if fenced:
                continue
            match = _HEADING.match(line)
            if match is None:
                continue
            title = match.group("title").strip()
            if not title:
                continue
            base = markdown.slug(title)
            used[base] = used.get(base, 0) + 1
            anchor = base if used[base] == 1 else f"{base}-{used[base]}"
            entries.append(
                Entry(
                    kind="doc",
                    title=title,
                    subtitle=doc.title,
                    doc=doc.path,
                    anchor=anchor,
                )
            )
    return entries


def _setting_entries() -> list[Entry]:
    entries = []
    for setting in settings_registry.SETTINGS:
        entries.append(
            Entry(
                kind="setting",
                title=setting.label,
                subtitle="Settings · " + setting.group,
                view="settings",
                target="profile-" + _NON_ID.sub("-", setting.key),
                body=setting.description,
            )
        )
    return entries


def build_index(root: Path | None = None) -> tuple[Entry, ...]:
    """Build the index from the working tree (tests and cold starts use this)."""
    base = (root or _ROOT).resolve()
    text = (base / "strength_coach/web/static/index.html").read_text(encoding="utf-8")
    entries: list[Entry] = []
    entries.extend(_setting_entries())
    entries.extend(_view_entries(text))
    entries.extend(_panel_entries(text))
    entries.extend(_doc_entries(base))
    return tuple(entries)


def _prepare(entries: tuple[Entry, ...] | list[Entry]) -> tuple[_Surface, ...]:
    return tuple(
        _Surface(
            entry=entry,
            title=entry.title.lower(),
            subtitle_text=entry.subtitle.lower(),
            body_text=entry.body.lower(),
        )
        for entry in entries
    )


_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"signature": None, "surfaces": ()}


def _signature(root: Path) -> tuple:
    parts: list[Any] = []
    for relative in (
        "strength_coach/web/static/index.html",
        "strength_coach/settings_registry.py",
        "docs/manifest.yaml",
    ):
        path = root / relative
        try:
            stat = path.stat()
            parts.append((relative, stat.st_mtime_ns, stat.st_size))
        except OSError:
            parts.append((relative, 0, 0))
    try:
        docs = tuple(
            sorted((path.name, path.stat().st_mtime_ns) for path in (root / "docs").glob("*.md"))
        )
    except OSError:
        docs = ()
    parts.append(docs)
    return tuple(parts)


def _surfaces(root: Path | None = None) -> tuple[_Surface, ...]:
    base = (root or _ROOT).resolve()
    signature = _signature(base)
    with _LOCK:
        if _CACHE["signature"] == signature and _CACHE["surfaces"]:
            return _CACHE["surfaces"]
    surfaces = _prepare(build_index(base))
    with _LOCK:
        _CACHE["signature"] = signature
        _CACHE["surfaces"] = surfaces
    return surfaces


def clear_cache() -> None:
    """Drop the cached index (tests and long-lived processes after a deploy)."""
    with _LOCK:
        _CACHE["signature"] = None
        _CACHE["surfaces"] = ()


def _tokens(query: str) -> list[str]:
    return [
        word for word in _WORD.findall(query.lower()) if len(word) >= 2 and word not in STOPWORDS
    ]


def _forms(token: str) -> tuple[str, ...]:
    """Light morphology so 'symptoms' and 'symptom' are the same word."""
    forms = [token]
    if len(token) > 4 and token.endswith("s"):
        forms.append(token[:-1])
    elif len(token) >= 3:
        forms.append(token + "s")
    return tuple(forms)


def _hit(form: str, text: str) -> bool:
    """True when form starts a word in text (so 'rate' does not match 'moderate')."""
    start = text.find(form)
    while start != -1:
        if start == 0 or not text[start - 1].isalnum():
            return True
        start = text.find(form, start + 1)
    return False


def _present(forms: tuple[str, ...], text: str) -> bool:
    return any(_hit(form, text) for form in forms)


def _field_score(forms: tuple[str, ...], aliases: tuple[str, ...], text: str) -> float:
    if _present(forms, text):
        return 1.0
    if aliases and _present(aliases, text):
        return 0.5
    return 0.0


def _score(surface: _Surface, term: tuple[tuple[str, ...], tuple[str, ...]]) -> float:
    forms, aliases = term
    best = 3 * _field_score(forms, aliases, surface.title)
    if best >= 3.0:
        return best
    if surface.subtitle_text:
        best = max(best, 2 * _field_score(forms, aliases, surface.subtitle_text))
        if best >= 2.0:
            return best
    if surface.body_text:
        best = max(best, _field_score(forms, aliases, surface.body_text))
    return best


def _terms(tokens: list[str]) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    terms = []
    for token in tokens:
        forms = tuple(form for form in _forms(token) if len(form) >= 3)
        aliases = tuple(
            form
            for alias in ALIASES.get(token, ())
            for form in _forms(alias)
            if len(form) >= 3
        )
        terms.append((forms, aliases))
    return terms


def _rank(surfaces: tuple[_Surface, ...], query: str) -> list[tuple[Entry, float]]:
    text = query.strip()
    tokens = _tokens(text)
    if not tokens:
        return []
    normalised = " ".join(_WORD.findall(text.lower()))
    terms = _terms(tokens)
    ranked: list[tuple[Entry, float]] = []
    for surface in surfaces:
        entry = surface.entry
        if normalised and normalised == surface.title:
            ranked.append((entry, 1.0))
            continue
        total = 0.0
        matched = 0
        for term in terms:
            best = _score(surface, term)
            total += best
            if best:
                matched += 1
        if not matched or matched / len(tokens) < 0.5:
            continue
        score = total / (3 * len(tokens))
        if matched == len(tokens) and (
            surface.title.startswith(normalised) or normalised.startswith(surface.title)
        ):
            score = max(score, 0.9)
        if entry.doc.startswith(ARCHIVE_PREFIX):
            score *= 0.7
        ranked.append((entry, round(score, 3)))
    ranked.sort(
        key=lambda item: (
            -item[1],
            KIND_ORDER[item[0].kind],
            len(item[0].title),
            item[0].title,
        )
    )
    return ranked


def rank(
    entries: tuple[Entry, ...] | list[Entry], query: str
) -> list[tuple[Entry, float]]:
    """Score entries for one query. Only entries matching at least half the terms are kept."""
    return _rank(_prepare(entries), query)


def search(query: str, *, limit: int = DEFAULT_LIMIT, root: Path | None = None) -> dict[str, Any]:
    """Return ranked results for one query. Raises ValueError for an unusable query."""
    text = (query or "").strip()
    if not text:
        raise ValueError("search needs a query")
    if len(text) > MAX_QUERY:
        raise ValueError(f"search is limited to {MAX_QUERY} characters")
    limit = max(1, min(MAX_LIMIT, int(limit)))
    ranked = _rank(_surfaces(root), text)
    return {
        "query": text,
        "total": len(ranked),
        "results": [entry.as_result(score) for entry, score in ranked[:limit]],
    }
