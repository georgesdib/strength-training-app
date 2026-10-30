"""Static frontend contracts.

The browser workflow is covered by the manual checklist in docs/WEB-UI.md. These checks
cover the parts that must never regress silently: executable inline handlers, missing
script files, escaping regressions and unsafe date/error patterns added by later workstreams.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "strength_coach/web/static"
INDEX = STATIC / "index.html"

# An inline event handler is an attribute assigned a string. A property assignment such as
# element.onclick = fn is not this pattern and is allowed.
INLINE_HANDLER_RE = re.compile(r'\bon[a-z]+\s*=\s*["\']')


def _static_files() -> list[Path]:
    return [INDEX, *sorted(STATIC.glob("*.js"))]


def test_no_inline_event_handlers() -> None:
    offenders = []
    for path in _static_files():
        text = path.read_text(encoding="utf-8")
        for match in INLINE_HANDLER_RE.finditer(text):
            line = text[:match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0)}")
    assert offenders == []


def test_every_referenced_script_exists() -> None:
    page = INDEX.read_text(encoding="utf-8")
    srcs = re.findall(r'<script src="([^"]+)"', page)
    assert srcs
    for src in srcs:
        assert src.startswith("/static/"), src
        assert (STATIC / src.removeprefix("/static/")).is_file(), src

def test_summary_script_and_panel_are_wired() -> None:
    page = INDEX.read_text(encoding="utf-8")
    assert 'id="workout-ended-summary"' in page
    assert "/static/summary.js" in page
    assert (STATIC / "summary.js").is_file()


def test_script_load_order() -> None:
    page = INDEX.read_text(encoding="utf-8")
    order = [src.removeprefix("/static/")
             for src in re.findall(r'<script src="([^"]+)"', page)]
    assert order.index("app.js") < order.index("history.js")
    assert order.index("app.js") < order.index("workout.js")
    if "core.js" in order:
        assert order.index("core.js") == 0


def test_scripts_parse() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    for path in sorted(STATIC.glob("*.js")):
        subprocess.run([node, "--check", str(path)], check=True,
                       capture_output=True, text=True)



def test_esc_escapes_html_metacharacters() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = "\n".join(path.read_text(encoding="utf-8")
                        for path in (STATIC / "app.js", STATIC / "core.js") if path.exists())
    match = re.search(r"function esc\(value\) \{[\s\S]*?\n\}", source)
    assert match, "esc() not found in the client bundle"
    script = (
        f"eval({json.dumps(match.group(0))});"
        "const got = esc(\"'\\\"><&\");"
        "if (got !== \"&#39;&quot;&gt;&lt;&amp;\") throw new Error(got);"
    )
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

def test_no_utc_or_locale_date_contract() -> None:
    source = "\n".join(path.read_text(encoding="utf-8")
                        for path in (STATIC / "app.js", STATIC / "core.js") if path.exists())
    assert "toISOString().slice(0, 10)" not in source
    assert "toLocaleDateString" not in source


def test_format_local_date_uses_the_local_calendar_day() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = "\n".join(path.read_text(encoding="utf-8")
                        for path in (STATIC / "app.js", STATIC / "core.js") if path.exists())
    functions = []
    for name in ("pad2", "formatLocalDate"):
        match = re.search(rf"function {name}\([^)]*\) \{{[\s\S]*?\n\}}", source)
        assert match, f"{name}() not found in the client bundle"
        functions.append(match.group(0))
    script = (
        "".join(f"eval({json.dumps(fn)});" for fn in functions)
        + "const cases = ["
        + "[new Date('2026-01-01T00:30:00Z'), '2025-12-31'],"
        + "[new Date(2026, 0, 1, 0, 0), '2026-01-01'],"
        + "[new Date('not-a-date'), ''],"
        + "[new Date(2026, 2, 8, 12, 0), '2026-03-08'],"
        + "];"
        + "for (const [date, expected] of cases) {"
        + "  const got = formatLocalDate(date);"
        + "  if (got !== expected) throw new Error(expected + ' != ' + got);"
        + "}"
    )
    env = {**os.environ, "TZ": "America/New_York"}
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, env=env)


def test_constrained_controls_are_not_free_text() -> None:
    page = INDEX.read_text(encoding="utf-8")
    assert '<select id="exercise-pattern" required>' in page
    assert 'id="exercise-muscles" class="choice-list"' in page
    assert 'id="exercise-detail-pattern" required>' in page
    assert 'id="exercise-detail-muscles" class="choice-list"' in page
    assert '<select id="exercise-vbt"></select>' in page
    assert 'id="exercise-vbt-new"' in page
    assert '<select id="exercise-detail-vbt"></select>' in page
    assert 'id="exercise-detail-vbt-new"' in page
    assert 'exercise-vbt-families' not in page
    exercises_js = (STATIC / "exercises.js").read_text(encoding="utf-8")
    assert "VBT_NEW_VALUE" in exercises_js
    assert "Add new family" in exercises_js
    assert "vbtFamilyOptions" in exercises_js

    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "choiceOptions(opts.constraint_kinds" in app
    assert 'choiceChecklist("forbidden_patterns"' in app
    assert 'choiceChecklist("forbidden_exercises"' in app
    assert 'data-constraint="kind"' in app
    assert 'data-constraint="region"' in app


def test_dead_controls_have_regression_guards() -> None:
    exercises = (STATIC / "exercises.js").read_text(encoding="utf-8")
    history = (STATIC / "history.js").read_text(encoding="utf-8")
    assert "props.day_roles.length" not in exercises
    assert 'document.getElementById("history-edit-sets")' in history
    assert "wireHistorySetButtons()" in history
    assert "wireHistoryRemoveButtons" not in history


def test_active_workout_is_card_based_and_keeps_context() -> None:
    page = INDEX.read_text(encoding="utf-8")
    assert 'id="workout-set-target"' in page
    assert 'id="workout-plan-details"' in page
    assert 'id="workout-import-details"' in page
    assert 'id="workout-set-rir"' in page and 'max="6"' in page
    assert 'id="workout-logger-title"' in page

    workout = (STATIC / "workout.js").read_text(encoding="utf-8")
    assert "workout-plan-card" in workout
    assert "workout-set-card" in workout
    assert "updateWorkoutSetTarget" in workout
    assert "numericOrNull" in workout
    assert 'id="workout-set-load").value = ""' not in workout


def test_readiness_scale_labels_are_shared() -> None:
    core = (STATIC / "core.js").read_text(encoding="utf-8")
    assert "READINESS_SCALE_ENDS" in core
    assert "stress: [\"extreme\", \"none\"]" in core
    assert "soreness: [\"severe\", \"none\"]" in core
    page = INDEX.read_text(encoding="utf-8")
    assert 'id="workflow-readiness-presets"' in page
    assert "5 means none" in page


def test_workout_logger_precedes_plan_and_import() -> None:
    page = INDEX.read_text(encoding="utf-8")
    assert page.index('id="workout-set-form"') < page.index('id="workout-plan-details"')
    assert page.index('id="workout-plan-details"') < page.index('id="workout-end-form"')
    assert page.index('id="workout-end-form"') < page.index('id="workout-import-details"')


def test_mobile_cards_replace_core_tables_on_narrow_screens() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    history = (STATIC / "history.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "prescription-cards" in app
    assert "history-card" in history
    assert "mobile-cards" in css
    assert "desktop-table" in css
    assert ".app-dialog" in css
    assert "font-size: 16px" in css


def test_accessibility_and_navigation_guards() -> None:
    page = INDEX.read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    workout = (STATIC / "workout.js").read_text(encoding="utf-8")
    assert 'aria-controls="sidebar"' in page
    assert 'aria-labelledby="exercise-details-title"' in page
    assert 'aria-labelledby="template-dialog-title"' in page
    assert 'id="today-session"' in page
    assert 'id="workflow-readiness-presets"' in page
    assert "aria-current" in app
    assert "sidebarFocusables" in app
    assert "main.inert" in app
    assert "goalRankHtml" not in app
    assert "primary_goal" not in app
    assert "focus_lifts" not in app
    assert "aria-invalid" in workout
    assert "setAttribute(\"aria-invalid\"" in workout
    assert "role=\"status\"" in page


def test_checkbox_states_are_read_from_checked_not_value() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "Boolean(values.max)" not in app
    assert "Boolean(values.force)" not in app
    assert "[data-test=\"max\"]" in app
    assert "[data-block=\"force\"]" in app


def test_readiness_presets_show_values_and_open_yaml_editor() -> None:
    page = INDEX.read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="readiness-preset-dialog"' in page
    assert 'id="readiness-preset-yaml"' in page
    assert "/api/readiness/presets" in app
    assert "edit-readiness-presets" in app
    assert "preset-values" in app
    assert "openReadinessPresetEditor" in app
    assert "saveReadinessPresetEditor" in app


def test_remaining_ui_controls_are_present() -> None:
    page = INDEX.read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    core = (STATIC / "core.js").read_text(encoding="utf-8")
    workout = (STATIC / "workout.js").read_text(encoding="utf-8")
    assert 'id="exercise-detail-spinal-cost" type="number" step="0.5" min="0" max="5"' in page
    assert 'id="exercise-extra"' in page and '<details class="advanced">' in page
    assert 'id="settings-volume-form"' in page
    assert 'id="settings-volume-fields"' in page
    assert "review-table" in app and "review-why" in app
    assert "search-select" in core and "filterNativeSelect" in core
    assert "exercisePickerHtml" in app
    assert 'id="workout-swap-dialog"' in page
    assert "openWorkoutSwapDialog" in workout
    assert "applyFieldErrors" in core
    assert "PROFILE_ERRORS" in app and "CONSTRAINT_ERRORS" in app


def test_remaining_forms_use_field_errors() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    core = (STATIC / "core.js").read_text(encoding="utf-8")
    assert "applyFieldErrors" in core
    assert "applyFieldErrors(error, $(" in app
    for marker in (
        '[data-symptom="region"]', '[data-block="date"]', '[data-break="starts_on"]',
        '#cardio-modality', '#measure-metric', '#settings-volume-fields',
        '#settings-volume-reason', '#settings-volume-confirm',
        '#settings-llm-model', '#settings-profile-guard',
    ):
        assert marker in app, marker


def test_volume_panel_is_consolidated_and_linked_to_its_guide() -> None:
    page = INDEX.read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="settings-volume-form"' in page
    assert 'href="#docs?doc=docs/VOLUME-BUDGET.md"' in page
    assert 'id="settings-drop-form"' not in page
    assert 'id="profile-volume' not in page
    assert 'setting.group === "Volume"' in app
    assert "renderVolumeSettings" in app
    assert "/api/settings/volume" in app
    assert "budgetValue(key)" in app
    assert "settings-volume-cap-sum" in app

    node = shutil.which("node")
    if node:
        match = re.search(r"function volumeNestedValue\([^)]*\) \{[\s\S]*?\n\}", app)
        assert match, "volumeNestedValue() not found"
        script = (
            f"eval({json.dumps(match.group(0))});"
            "const budget = {session_cap: {total: 30}, tolerance: 0.1};"
            "if (volumeNestedValue(budget, 'session_cap.total') !== 30) throw new Error('nested cap');"
            "if (volumeNestedValue(budget, 'tolerance') !== 0.1) throw new Error('flat value');"
            "if (volumeNestedValue(budget, 'missing.total') !== undefined) throw new Error('missing');"
        )
        subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def test_technique_throttle_scope_is_a_constrained_select() -> None:
    page = INDEX.read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    exercises = (STATIC / "exercises.js").read_text(encoding="utf-8")

    assert '<select id="prescribe-throttle-pattern" multiple size="6">' in page
    assert '<option value="" selected>All lifts (main work)</option>' in page
    assert 'list="exercise-patterns"' not in page
    assert "populateThrottlePatterns" in app
    assert "loadThrottlePatterns" in app
    assert "mainSelected" in app
    assert "selectedOptions" in app
    assert "syncThrottleSelection" not in app
    assert "/api/options" in app
    assert "populateThrottlePatterns(data.patterns)" in exercises


def test_estimated_session_time_is_at_the_top_of_a_generated_workout() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    workout = (STATIC / "workout.js").read_text(encoding="utf-8")

    assert "Estimated session time:" in app
    assert "sessionTime.estimated_minutes" in app
    assert "estimated ~" in workout
    assert "startEstimate" in workout


def test_drop_confirmation_is_only_offered_inside_the_competition_window() -> None:
    page = INDEX.read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    core = (STATIC / "core.js").read_text(encoding="utf-8")

    assert 'id="prescribe-drop-confirm-wrap" hidden' in page
    assert "updateDropConfirmVisibility" in app
    assert "loadDropWindow" in app
    assert "/api/settings/drop/window" in app
    # The window rule lives in Python; the browser must not grow a second copy.
    assert "localDateOrdinal" not in core
    assert "dropConfirmationApplies" not in app


def test_summary_rendering_contracts() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "summary.js").read_text(encoding="utf-8")
    script = r"""
global.__summaryTarget = {innerHTML: ""};
global.document = {getElementById: function () { return global.__summaryTarget; }};
global.esc = function (value) { return String(value == null ? "" : value); };
global.fmt = function (value) { return Number(value).toFixed(1).replace(/\.0+$/, ""); };
global.api = function () { return Promise.resolve({}); };
eval(SOURCE);
function render(payload) {
  renderWorkoutSummary(payload);
  return global.__summaryTarget.innerHTML;
}
var base = {
  completion: {items: [], planned_sets: 0, completed_sets: 0},
  strength: [{exercise_id: "squat", post: {status: "estimated", kg: 100},
              recent_reference: {}, difference: {status: "unavailable"}}],
  dose: {per_exercise: [], relative_intensity: {}, rir: {},
         patterns: {squat: 2, hinge: 1}},
  special: {power: {sets: 2, reps: 8,
                    mean_velocity_change: [{exercise_id: "jump_squats", load_kg: 20,
                                            n: 2, change_pct: -10.0}]},
            high_intensity: [],
            quality_stop: {status: "not_recorded"},
            spinal: {label: "ordinal exposure", weekly_cost: 1, weekly_cap: 6,
                     heavy_sets: {total_sets: 1, rir_max: 1},
                     axial_demand: {high: 1, moderate: 2, low: 3, unknown: 4}}},
  feedback: {}, basis: {}
};
var html = render(base);
if (html.indexOf("estimated") < 0 || html.indexOf("observed") >= 0) throw new Error("status");
if (html.indexOf("squat: 2") < 0 || html.indexOf("hinge: 1") < 0) throw new Error("patterns");
if (html.indexOf("high: 1") < 0 || html.indexOf("moderate: 2") < 0 ||
    html.indexOf("low: 3") < 0 || html.indexOf("unknown: 4") < 0) throw new Error("axial");
if (html.indexOf("1 heavy spinal sets") < 0) throw new Error("heavy");
if (html.indexOf("-10%") < 0) throw new Error("velocity");
if (html.indexOf("Quality stop: Not recorded") < 0) throw new Error("quality");
base.special.power.mean_velocity_change = [{exercise_id: "jump_squats", load_kg: 20,
                                             status: "unavailable", reason: "fewer than two"}];
base.special.quality_stop = {status: "recorded"};
html = render(base);
if (html.indexOf("Unavailable (fewer than two)") < 0) throw new Error("velocity unavailable");
if (html.indexOf("Quality stop: Recorded") < 0) throw new Error("quality recorded");
base.strength[0].post.status = "degraded";
html = render(base);
if (html.indexOf("degraded") < 0) throw new Error("degraded status");
"""
    script = script.replace("SOURCE", json.dumps(source))
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
