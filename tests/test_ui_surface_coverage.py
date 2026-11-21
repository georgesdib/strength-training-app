"""Client-rendered headings: the unindexed set may shrink, never grow.

The server index can only see index.html. Headings that app.js and friends build at runtime are
collected from the live DOM by the palette, so they are searchable once their view has rendered.
This test keeps a ledger of those headings: a new one fails until it is indexed or listed, and a
stale ledger line fails once its title becomes indexed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from strength_coach.web import search

ROOT = Path(__file__).resolve().parents[1]
DEBT = Path(__file__).with_name("ui_surface_debt.txt")
HEADING = re.compile(r"<h[23][^>]*>([^<]{2,80})</h[23]>")
TEMPLATE = ("$" + "{", "' +", '" +')


@pytest.fixture(scope="module")
def indexed():
    return [entry.title.lower() for entry in search.build_index(ROOT)]


def _rendered() -> set[str]:
    titles: set[str] = set()
    for script in sorted((ROOT / "strength_coach/web/static").glob("*.js")):
        for raw in HEADING.findall(script.read_text(encoding="utf-8")):
            title = re.sub(r"\s+", " ", raw).strip()
            if not title or any(marker in title for marker in TEMPLATE):
                continue
            titles.add(title)
    return titles


def _ledger() -> set[str]:
    return {
        line.strip()
        for line in DEBT.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _missing(indexed: list[str]) -> set[str]:
    return {
        title
        for title in _rendered()
        if not any(title.lower() in known or known in title.lower() for known in indexed)
    }


def test_new_client_surfaces_are_indexed_or_listed(indexed):
    new = _missing(indexed) - _ledger()
    assert not new, "unindexed client headings; index them or add to ui_surface_debt.txt: " + repr(
        sorted(new)
    )


def test_the_debt_list_has_no_stale_entries(indexed):
    stale = _ledger() - _missing(indexed)
    assert not stale, "these headings are indexed now; remove them from ui_surface_debt.txt: " + repr(
        sorted(stale)
    )
