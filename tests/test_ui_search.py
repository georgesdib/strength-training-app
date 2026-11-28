"""UI search: the index, ranking and endpoint cover the real page.

The contract: every view and id-carrying panel in index.html is findable, every profile setting is
findable by its label, every doc result points at an anchor the renderer actually emits, and the
endpoint never leaks a filesystem path.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from strength_coach import settings_registry
from strength_coach.store import db
from strength_coach.web import markdown, search, server

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "strength_coach/web/static/index.html"


@pytest.fixture(scope="module")
def entries():
    return search.build_index(ROOT)


def test_every_view_is_indexed(entries):
    text = INDEX_HTML.read_text(encoding="utf-8")
    views = set(re.findall(r'<section id="view-([a-z0-9-]+)"', text))
    indexed = {entry.view for entry in entries if entry.kind == "view"}
    assert views
    assert views == indexed


def test_every_panel_with_an_id_is_indexed(entries):
    text = INDEX_HTML.read_text(encoding="utf-8")
    panel_ids = set(re.findall(r'<div class="panel[^"]*" id="([^"]+)"', text))
    targets = {entry.target for entry in entries if entry.kind == "panel"}
    assert panel_ids
    assert panel_ids <= targets


def test_every_setting_is_indexed_with_its_editor_id(entries):
    indexed = {entry.target for entry in entries if entry.kind == "setting"}
    assert len(indexed) == len(settings_registry.SETTINGS)
    for spec in settings_registry.SETTINGS:
        expected = "profile-" + re.sub(r"[^A-Za-z0-9_-]", "-", spec.key)
        assert expected in indexed
    script = (ROOT / "strength_coach/web/static/settings.js").read_text(encoding="utf-8")
    assert 'setting.key.replace(/[^a-zA-Z0-9_-]/g, "-")' in script


def test_symptoms_find_the_athlete_panel_first(entries):
    results = search.rank(entries, "where can I see the table of symptoms")
    assert results
    assert results[0][0].target == "state-symptom-panel"


def test_resolver_dwell_finds_the_panel_and_its_settings(entries):
    results = search.rank(entries, "resolver dwell settings")
    assert results[0][0].target == "settings-resolver-panel"
    targets = {entry.target for entry, _ in results}
    assert "profile-resolver-dwell-target" in targets


def test_dwell_prefers_a_dwell_labelled_setting(entries):
    results = search.rank(entries, "dwell")
    assert results[0][0].kind == "setting"
    assert "dwell" in results[0][0].title.lower()


@pytest.mark.parametrize(
    ("question", "views"),
    [
        ("I want to remove an e1rm override, where can I do that?", {"state-metrics"}),
        ("where can I see the table of symptoms?", {"state-symptoms"}),
        ("where do I add a constraint?", {"state-limits"}),
        ("where do I rate an exercise's suitability?", {"state-limits"}),
        ("where do I declare a break?", {"state-events"}),
        ("where do I record a strength test?", {"state-metrics", "state"}),
        ("where do I log a set?", {"workout"}),
        ("where do I edit a past session?", {"history"}),
        ("where do I configure relative strength ratios?", {"performance"}),
        ("where do I rate resolver suggestions?", {"settings-resolver"}),
        ("where do I change the readiness baseline?", {"readiness"}),
        ("where do I import a CSV?", {"import", "workout"}),
        ("where do I log a symptom before training?", {"state-symptoms"}),
        ("where do I see the resolver generation preview?", {"settings-resolver"}),
    ],
)
def test_realistic_questions_land_in_the_expected_view(entries, question, views):
    results = search.rank(entries, question)
    assert results
    assert results[0][0].view in views


def test_curated_actions_point_at_real_elements():
    text = INDEX_HTML.read_text(encoding="utf-8")
    for item in search.ACTION_TARGETS:
        assert f'id="{item["target"]}"' in text
        assert f'id="view-{item["view"]}"' in text


def test_removing_an_override_finds_the_athlete_ledger(entries):
    results = search.rank(
        entries, "I want to remove an e1rm override, where can I do that?"
    )
    assert results
    assert results[0][0].view == "state-metrics"
    assert results[0][0].target == "state-forms-metrics"


def test_the_dwell_counter_question_finds_the_resolver_section(entries):
    query = "where can I see/configure the count of an exercise which is used in dwell?"
    results = search.rank(entries, query)
    sections = [entry for entry, _ in results if entry.title == "Dwell counters"]
    assert sections
    assert sections[0].target.startswith("settings-dwell")
    assert sections[0].subtitle == "Resolver"


def test_layout_words_do_not_hide_a_result(entries):
    results = search.rank(entries, "where do I change the maximum heart rate")
    assert results[0][0].target == "profile-cardio-max_hr_bpm"


def test_doc_results_point_at_rendered_anchors(entries):
    hits = [
        (entry, score)
        for entry, score in search.rank(entries, "dwell")
        if entry.kind == "doc" and entry.anchor
    ][:3]
    assert hits
    for entry, _score in hits:
        source = (ROOT / entry.doc).read_text(encoding="utf-8")
        rendered = markdown.render(source, docs_root=ROOT, base_dir=(ROOT / entry.doc).parent)
        assert f'id="{entry.anchor}"' in rendered


def test_queries_are_validated():
    with pytest.raises(ValueError):
        search.search("   ")
    with pytest.raises(ValueError):
        search.search("x" * (search.MAX_QUERY + 1))


def test_limit_is_clamped():
    payload = search.search("settings", limit=500)
    assert 0 < len(payload["results"]) <= search.MAX_LIMIT


@pytest.fixture()
def web(tmp_path):
    path = tmp_path / "coach.db"
    db.Store(path).close()
    httpd = server.create_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_search_endpoint_returns_targets(web):
    with urllib.request.urlopen(web + "/api/search?q=dwell&limit=5", timeout=20) as response:
        body = json.loads(response.read().decode())
    assert response.status == 200
    assert body["query"] == "dwell"
    assert body["results"]
    first = body["results"][0]
    assert {"kind", "score", "title", "subtitle", "view", "target", "doc", "anchor"} <= set(first)
    strings = [value for row in body["results"] for value in row.values() if isinstance(value, str)]
    assert not [value for value in strings if value.startswith("/")]


def test_search_endpoint_rejects_a_long_query(web):
    with pytest.raises(urllib.error.HTTPError) as failure:
        urllib.request.urlopen(web + "/api/search?q=" + "x" * 200, timeout=20)
    assert failure.value.code == 400


def test_page_ships_the_palette():
    text = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="search-palette"' in text
    assert 'id="search-input"' in text
    assert "/static/search.js" in text

def test_athlete_is_split_into_wired_subsections():
    """The Athlete page is six real views, each with its own container and section links.

    A sub-page that exists in the nav but has nowhere to render is the failure this guards:
    the panels are injected by JS, so a missing container would silently drop a form.
    """
    text = INDEX_HTML.read_text(encoding="utf-8")
    views = re.findall(r'<section id="view-(state[a-z-]*)"', text)
    assert views == [
        "state", "state-symptoms", "state-limits",
        "state-profile", "state-metrics", "state-events",
    ]
    nav = re.search(r"<summary>Athlete</summary>(.*?)</details>", text, re.S)
    assert nav is not None
    assert re.findall(r'data-view="([a-z-]+)"', nav.group(1)) == views

    containers = {
        "state-symptoms": "state-forms-symptoms",
        "state-limits": "state-forms-limits",
        "state-profile": "state-forms-profile",
        "state-metrics": "state-forms-metrics",
        "state-events": "state-forms-events",
    }
    for view in views:
        section = text.split(f'<section id="view-{view}"', 1)[1].split("</section>", 1)[0]
        assert 'class="subnav"' in section, view
        assert 'class="state-result"' in section, view
        if view in containers:
            assert f'id="{containers[view]}"' in section, view

    script = (ROOT / "strength_coach/web/static/app.js").read_text(encoding="utf-8")
    # Panels declare their sub-page rather than relying on template order.
    assert "data-state-section=" in script
    assert 'getElementById("state-forms-" + section)' in script
    # loadState() runs on every sub-page switch, so the container must be replaced rather
    # than appended to; appending duplicated every form on each visit.
    assert "replaceChildren(...panels)" in script
    assert "appendChild(panel)" not in script
    # The workout deep link must land on the form, not on the overview.
    assert 'setView("state-symptoms")' in script

def test_settings_is_split_into_wired_subsections():
    text = INDEX_HTML.read_text(encoding="utf-8")
    views = re.findall(r'<section id="view-(settings[a-z-]*)"', text)
    assert views == [
        "settings", "settings-ios", "settings-training",
        "settings-resolver", "settings-reports", "settings-profile",
    ]
    nav = re.search(r"<summary>Settings</summary>(.*?)</details>", text, re.S)
    assert nav is not None
    assert re.findall(r'data-view="([a-z-]+)"', nav.group(1)) == views
    for view in views:
        section = text.split(f'<section id="view-{view}"', 1)[1].split("</section>", 1)[0]
        assert 'class="subnav"' in section, view
    # Re-homed, never lost: every panel heading appears exactly once across the six pages.
    joined = "".join(
        text.split(f'<section id="view-{view}"', 1)[1].split("</section>", 1)[0]
        for view in views
    )
    for heading in (
        "Appearance", "Language model", "iOS settings", "Prescribe defaults",
        "Volume budget", "Monitoring &amp; reports", "Modules", "Resolver",
        "Settings profile", "Programme cache", "App",
    ):
        assert joined.count(f"<h2>{heading}</h2>") == 1, heading


def test_administration_nests_athlete_and_settings():
    text = INDEX_HTML.read_text(encoding="utf-8")
    admin = re.search(r"<summary>Administration</summary>(.*?)</nav>", text, re.S)
    assert admin is not None
    body = admin.group(1)
    assert body.count('class="nav-subgroup"') == 2
    assert "<summary>Athlete</summary>" in body
    assert "<summary>Settings</summary>" in body
    for view in ("import", "logs", "docs"):
        assert f'data-view="{view}"' in body


def test_every_indexed_view_is_a_real_section(entries):
    # A palette result that navigates to a view id with no section would silently do nothing.
    text = INDEX_HTML.read_text(encoding="utf-8")
    views = set(re.findall(r'<section id="view-([a-z0-9-]+)"', text))
    # Doc entries carry no view; every surface entry must name a real section.
    assert {entry.view for entry in entries if entry.view} <= views

def test_every_nav_and_subnav_link_has_a_section():
    # A nav button or sub-navigation link that names no section silently does nothing.
    text = INDEX_HTML.read_text(encoding="utf-8")
    views = set(re.findall(r'<section id="view-([a-z0-9-]+)"', text))
    nav = re.search(r'<nav id="nav".*?</nav>', text, re.S)
    assert nav is not None
    assert set(re.findall(r'data-view="([a-z0-9-]+)"', nav.group(0))) <= views
    assert set(re.findall(r'data-view-link="([a-z0-9-]+)"', text)) <= views
