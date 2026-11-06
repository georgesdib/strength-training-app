"""Authoritative documentation manifest.

The manifest is the single source of truth for which documents exist, what they are called,
where they live, how they are grouped and whether they are public. The web docs viewer, the
documentation tests and the archive/index checks all read it; there is no second hardcoded
document list.

Private documents are deliberately absent: `private/` is git-ignored and must never appear in
the public manifest or any public documentation route.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "docs" / "manifest.yaml"

STATUSES = {"canonical", "evidence", "reference", "plan", "archived", "design", "development"}
AUDIENCES = {"public", "maintainer"}


class ManifestError(ValueError):
    """The documentation manifest is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class Document:
    id: str
    path: str
    title: str
    description: str
    category: str
    status: str
    audience: str
    nav: bool


@dataclass(frozen=True)
class Manifest:
    categories: tuple[tuple[str, str], ...]
    documents: tuple[Document, ...]

    @property
    def category_labels(self) -> dict[str, str]:
        return dict(self.categories)

    def entry(self, path: str) -> Document | None:
        return next((doc for doc in self.documents if doc.path == path), None)

    def public(self) -> tuple[Document, ...]:
        """Documents the Docs viewer may list and serve.

        Maintainer-only design documents stay out of the viewer; private files are not in the
        manifest at all, so this is also the visibility boundary.
        """
        return tuple(doc for doc in self.documents if doc.audience == "public")


def _parse(path: Path) -> Manifest:
    if not path.is_file():
        raise ManifestError(f"documentation manifest not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - malformed YAML is a hard failure
        raise ManifestError(f"invalid documentation manifest: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError("documentation manifest must be a mapping")
    if raw.get("schema_version") != "1.0.0":
        raise ManifestError("unsupported documentation manifest schema_version")

    categories: list[tuple[str, str]] = []
    for item in raw.get("categories") or []:
        if not isinstance(item, dict) or not item.get("key") or not item.get("label"):
            raise ManifestError("each category needs a key and a label")
        if item["key"] in dict(categories):
            raise ManifestError(f"duplicate category: {item['key']}")
        categories.append((str(item["key"]), str(item["label"])))
    if not categories:
        raise ManifestError("documentation manifest has no categories")
    keys = {key for key, _ in categories}

    documents: list[Document] = []
    ids: set[str] = set()
    paths: set[str] = set()
    for item in raw.get("documents") or []:
        if not isinstance(item, dict):
            raise ManifestError("each document entry must be a mapping")
        try:
            doc = Document(
                id=str(item["id"]),
                path=str(item["path"]),
                title=str(item["title"]),
                description=str(item["description"]),
                category=str(item["category"]),
                status=str(item["status"]),
                audience=str(item["audience"]),
                nav=bool(item["nav"]),
            )
        except KeyError as exc:
            raise ManifestError(f"document entry missing {exc}") from exc
        if not doc.id or not doc.path or not doc.title or not doc.description:
            raise ManifestError(f"document entry has empty required metadata: {doc.path}")
        if doc.id in ids:
            raise ManifestError(f"duplicate document id: {doc.id}")
        if doc.path in paths:
            raise ManifestError(f"duplicate document path: {doc.path}")
        if doc.category not in keys:
            raise ManifestError(f"unknown category {doc.category!r} for {doc.path}")
        if doc.status not in STATUSES:
            raise ManifestError(f"unknown status {doc.status!r} for {doc.path}")
        if doc.audience not in AUDIENCES:
            raise ManifestError(f"unknown audience {doc.audience!r} for {doc.path}")
        if doc.audience != "public" and doc.nav:
            raise ManifestError(f"non-public document cannot be navigable: {doc.path}")
        rel = PurePosixPath(doc.path)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise ManifestError(f"document path must be repository-relative: {doc.path}")
        if rel.parts[0] == "private":
            raise ManifestError(f"private document in public manifest: {doc.path}")
        if rel.suffix != ".md":
            raise ManifestError(f"document is not Markdown: {doc.path}")
        full = ROOT.joinpath(*rel.parts)
        if not full.is_file():
            raise ManifestError(f"document does not exist: {doc.path}")
        ids.add(doc.id)
        paths.add(doc.path)
        documents.append(doc)

    if not documents:
        raise ManifestError("documentation manifest has no documents")
    return Manifest(tuple(categories), tuple(documents))


@lru_cache(maxsize=1)
def manifest() -> Manifest:
    return _parse(MANIFEST_PATH)


def public_docs() -> tuple[Document, ...]:
    return manifest().public()
