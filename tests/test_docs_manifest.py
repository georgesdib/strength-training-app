"""The documentation manifest is the single source of truth for the Docs UI.

These checks fail when a document is added, moved, deleted or reclassified without updating
the manifest, when a path escapes the repository, or when the public/private boundary is
weakened.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from strength_coach.utils import docs_manifest

ROOT = Path(__file__).resolve().parents[1] / "docs"


def test_manifest_ids_paths_and_files_are_unique_and_exist() -> None:
    manifest = docs_manifest.manifest()
    ids = [doc.id for doc in manifest.documents]
    paths = [doc.path for doc in manifest.documents]
    assert len(ids) == len(set(ids))
    assert len(paths) == len(set(paths))
    for doc in manifest.documents:
        assert (ROOT.parent / doc.path).is_file(), doc.path
        assert doc.description.strip()
        assert doc.category in manifest.category_labels
        assert doc.status in docs_manifest.STATUSES
        assert doc.audience in docs_manifest.AUDIENCES


def test_every_public_markdown_file_is_classified() -> None:
    manifest = docs_manifest.manifest()
    classified = {doc.path for doc in manifest.documents}
    missing = [
        path.relative_to(ROOT.parent).as_posix()
        for path in ROOT.rglob("*.md")
        if path.relative_to(ROOT.parent).as_posix() not in classified
    ]
    assert missing == []


def test_root_entry_points_are_public() -> None:
    paths = {doc.path for doc in docs_manifest.public_docs()}
    assert {"README.md", "USER-GUIDE.md", "ROADMAP.md", "docs/README.md"} <= paths


def test_archive_and_design_classification() -> None:
    manifest = docs_manifest.manifest()
    archive = [doc for doc in manifest.documents if doc.path.startswith("docs/archive/")]
    assert archive
    for doc in archive:
        if doc.path.endswith("/README.md"):
            assert doc.status == "reference"
        else:
            assert doc.status == "archived"
    design = [doc for doc in manifest.documents if doc.path.startswith("docs/design/")]
    assert design
    assert all(doc.audience == "maintainer" and doc.nav is False for doc in design)
    assert not any(doc.path.startswith("docs/design/") for doc in docs_manifest.public_docs())


def test_public_documents_cannot_be_private() -> None:
    for doc in docs_manifest.manifest().documents:
        parts = PurePosixPath(doc.path).parts
        assert parts[0] != "private"
        assert ".." not in parts
        assert not PurePosixPath(doc.path).is_absolute()
    served = {doc.path for doc in docs_manifest.public_docs()}
    assert not any(path.startswith("private/") for path in served)


def test_documents_are_sorted_by_category_and_title() -> None:
    manifest = docs_manifest.manifest()
    order = [key for key, _ in manifest.categories]
    keys = [(order.index(doc.category), doc.title.lower()) for doc in manifest.documents]
    assert keys == sorted(keys)


def test_public_entries_are_navigable() -> None:
    assert all(doc.nav for doc in docs_manifest.public_docs())
    assert all(not doc.nav for doc in docs_manifest.manifest().documents if doc.audience != "public")
