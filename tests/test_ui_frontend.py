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


def _run_node(script: str, *, check: bool = False, env=None):
    """Run a large inline script through stdin; argv has an OS length limit."""
    node = shutil.which("node")
    assert node is not None
    return subprocess.run(
        [node, "-"], input=script, text=True, capture_output=True, check=check, env=env
    )


def test_no_inline_event_handlers() -> None:
    offenders = []
    for path in _static_files():
        text = path.read_text(encoding="utf-8")
        for match in INLINE_HANDLER_RE.finditer(text):
            line = text[:match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0)}")
    assert offenders == []


def test_transport_errors_have_actionable_copy() -> None:
    core = (STATIC / "core.js").read_text(encoding="utf-8")
    assert "411:" in core and "missing its size" in core
    assert "413:" in core and "too large to import" in core


def test_every_referenced_script_exists() -> None:
    page = INDEX.read_text(encoding="utf-8")
    srcs = re.findall(r'<script src="([^"]+)"', page)
    assert srcs
    for src in srcs:
        assert src.startswith("/static/"), src
        assert (STATIC / src.removeprefix("/static/")).is_file(), src

def test_workout_exercise_history_is_wired() -> None:
    page = INDEX.read_text(encoding="utf-8")
    source = (STATIC / "workout.js").read_text(encoding="utf-8")
    assert 'id="workout-plan-details" open' in page
    assert "data-history-toggle" in source
    assert "data-history-more" in source
    assert "/api/exercise-history" in source
    assert "WORKOUT_HISTORY_LIMIT = 5" in source
    assert "Show more" in source


def test_summary_script_and_panel_are_wired() -> None:
    page = INDEX.read_text(encoding="utf-8")
    assert 'id="workout-ended-summary"' in page
    assert "/static/summary.js" in page
    assert (STATIC / "summary.js").is_file()


def test_performance_script_and_view_are_wired() -> None:
    page = INDEX.read_text(encoding="utf-8")
    assert 'id="view-performance"' in page
    assert 'data-view="performance"' in page
    assert "/static/performance.js" in page
    assert (STATIC / "performance.js").is_file()


def test_performance_filters_are_sent_to_the_api() -> None:
    source = (STATIC / "performance.js").read_text(encoding="utf-8")
    assert 'session_type=' in source
    assert 'include_deloads=' in source
    assert 'quality=' in source
    assert 'Degraded observations' in source
    assert 'Equipment changes are not stored' in source


def test_monitoring_analysis_is_in_performance_view() -> None:
    page = INDEX.read_text(encoding="utf-8")
    source = (STATIC / "performance.js").read_text(encoding="utf-8")
    assert 'id="monitoring-analysis-panel"' in page
    assert 'id="monitoring-analysis-run"' in page
    assert 'id="monitoring-analysis-date"' in page
    assert "/api/monitoring-analysis" in source
    assert "Run the analysis" in page
    assert "exploratory observational associations" in page
    assert "historical calibration state is not reconstructed" in source


def test_phase5a_review_actions_are_exposed() -> None:
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "phase5a_review" in source
    assert "Proceed to Phase 5B" in source
    assert "Extend Phase 5A once" in source
    assert "Close Phase 5A without Phase 5B" in source


def test_performance_full_list_and_pair_editor_are_exposed() -> None:
    source = (STATIC / "performance.js").read_text(encoding="utf-8")
    assert "Show full association list" in source
    assert "Show full dose list" in source
    assert "performance-dose-toggle" in source
    assert "Add a configured pair" in source
    assert "/api/performance/relationship-options" in source
    assert "/api/performance/relationships" in source


def test_monitoring_inventory_settings_panel_is_read_only() -> None:
    page = INDEX.read_text(encoding="utf-8")
    source = (STATIC / "settings.js").read_text(encoding="utf-8")
    assert 'id="settings-monitoring-panel"' in page
    assert 'id="settings-monitoring-search"' in page
    assert 'id="settings-monitoring-group"' in page
    assert "/api/settings/monitoring" in source
    assert "Phase 5A locked" in source
    assert "Python default" in source
    assert "Canonical config" in source
    assert "Local override" in source


def test_view_loaders_are_registered() -> None:
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "const VIEW_LOADERS" in source
    assert "const loader = VIEW_LOADERS[name]" in source
    assert "if (name ===" not in source


def test_script_load_order() -> None:
    page = INDEX.read_text(encoding="utf-8")
    order = [src.removeprefix("/static/")
             for src in re.findall(r'<script src="([^"]+)"', page)]
    assert order.index("core.js") == 0
    assert order.index("core.js") < order.index("adherence.js")
    assert order.index("adherence.js") < order.index("vbt.js")
    assert order.index("vbt.js") < order.index("app.js")
    assert order.index("vbt.js") < order.index("history.js")
    assert order.index("vbt.js") < order.index("performance.js")
    assert order.index("settings.js") < order.index("app.js")
    assert order.index("app.js") < order.index("history.js")
    assert order.index("app.js") < order.index("workout.js")


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
    result = _run_node(script)
    assert result.returncode == 0, result.stderr

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
    _run_node(script, check=True, env=env)


def test_constrained_controls_are_not_free_text() -> None:
    page = INDEX.read_text(encoding="utf-8")
    assert 'id="exercise-detail-id" required pattern="[a-z][a-z0-9_]*"' in page
    assert 'id="exercise-detail-pattern" required>' in page
    assert 'id="exercise-detail-muscles" class="choice-list"' in page
    assert '<select id="exercise-detail-vbt"></select>' in page
    assert 'id="exercise-detail-vbt-new"' in page
    assert 'id="exercise-editor"' not in page
    assert 'id="exercise-details-dialog"' in page
    assert 'id="exercise-detail-e1rm"' in page and 'id="exercise-detail-dose"' in page
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
    assert "optional source/context" in app
    assert 'data-constraint="evidence"' in app


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


def test_readiness_override_lives_with_the_daily_score() -> None:
    page = INDEX.read_text(encoding="utf-8")
    workflow = page.split('id="workflow-readiness"', 1)[1].split('id="workflow-preview"', 1)[0]
    assert 'id="readiness-date"' in workflow
    assert 'id="readiness-score"' in workflow
    assert 'id="override-form"' in workflow
    assert 'id="override-date-label"' in workflow
    assert 'id="override-scope"' in workflow

    # The settings page keeps policy, not the daily score override.
    settings = page.split('id="view-readiness"', 1)[1].split('id="view-cardio"', 1)[0]
    assert 'id="override-form"' not in settings

    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "syncOverrideDateLabel" in app
    assert 'date: $("#readiness-date").value' in app


def test_docs_viewer_groups_by_manifest_category() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "category_label" in app
    assert "docs-group-label" in app
    index = INDEX.read_text(encoding="utf-8")
    assert 'id="docs-list"' in index


def test_today_progress_ratio_is_explained_and_links_to_its_doc() -> None:
    page = INDEX.read_text(encoding="utf-8")
    assert "session best e1RM" in page
    assert "prior 84-day best" in page
    assert "docs/WEB-UI.md&amp;anchor=progress-snapshot-ratio-today" in page
    doc = (ROOT / "docs" / "WEB-UI.md").read_text(encoding="utf-8")
    assert "### Progress snapshot ratio (Today)" in doc
    assert "preceding 84 days" in doc
    assert "last 56 days" in doc


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


def test_exercise_catalogue_columns_fill_the_table_width() -> None:
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    widths = {}
    for column in range(1, 8):
        match = re.search(
            rf"\.exercise-table th:nth-child\({column}\), "
            rf"\.exercise-table td:nth-child\({column}\) \{{ width: (\d+)%; \}}",
            css,
        )
        assert match, f"exercise catalogue column {column} has no desktop width"
        widths[column] = int(match.group(1))
    # Seven fixed columns must add up to the table width. The actions column lost its width
    # when Demands was inserted before it in the markup, so the buttons stacked into a
    # zero-width column and every row grew three or four lines tall on desktop.
    assert sum(widths.values()) == 100


def test_fatigue_diagnostic_reveals_ten_rows_at_a_time() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    page_size = re.search(r"const FATIGUE_PAGE_SIZE = \d+;", source)
    assert page_size, "FATIGUE_PAGE_SIZE not found in the client bundle"
    pieces = []
    # const does not leak out of eval, so the page size is injected directly and only the
    # functions are evaluated (they close over the script-scope binding).
    for pattern in (
        r"function fatigueRowHtml\(m\) \{[\s\S]*?\n\}",
        r"function fatigueTableHtml\(models, shown\) \{[\s\S]*?\n\}",
    ):
        match = re.search(pattern, source)
        assert match, f"{pattern} not found in the client bundle"
        pieces.append(match.group(0))
    models = [
        {"exercise_id": f"lift_{index}", "family": "squat", "n_observations": 12,
         "span_days": 90, "r2": 0.4, "backtest_mae": 3, "backtest_naive_mae": 4,
         "fitness_kg": 100, "fatigue_kg": -2, "state_kg": 98, "state_ci": [95, 101],
         "latest_e1rm": 99, "status": "ok", "unit": "kg"}
        for index in range(23)
    ]
    script = (
        "global.esc = function (value) { return String(value == null ? '' : value); };"
        + page_size.group(0)
        + "".join(f"eval({json.dumps(piece)});" for piece in pieces)
        + f"const models = {json.dumps(models)};"
        + "const first = fatigueTableHtml(models, FATIGUE_PAGE_SIZE);"
        + "const all = fatigueTableHtml(models, 100);"
        + "if ((first.match(/<tr>/g) || []).length !== 11)"
        + " throw new Error('expected ten lift rows plus the header');"
        + "if (first.indexOf('Showing 10 of 23 lifts') < 0) throw new Error('count missing');"
        + "if (first.indexOf('Show 10 more') < 0) throw new Error('show more missing');"
        + "if ((all.match(/<tr>/g) || []).length !== 24) throw new Error('all rows missing');"
        + "if (all.indexOf('Show 10 more') >= 0) throw new Error('button should disappear');"
        + "if (all.indexOf('Showing all 23 lifts') < 0) throw new Error('all count missing');"
    )
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_accessibility_and_navigation_guards() -> None:
    page = INDEX.read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    workout = (STATIC / "workout.js").read_text(encoding="utf-8")
    assert 'aria-controls="sidebar"' in page
    assert 'aria-labelledby="exercise-details-title"' in page
    assert 'aria-labelledby="template-dialog-title"' in page
    assert 'id="today-session"' in page
    for area in ("Today", "Training", "Progress", "Health &amp; Longevity",
                 "Programme Intelligence", "Administration"):
        assert area in page
    assert 'id="view-progress"' in page
    assert 'id="progress-dashboard"' in page
    assert 'id="today-priorities"' in page
    assert 'data-view="progress"' in page
    assert "Continue workout" in app and "/api/workout/active" in app
    assert "progressRatioSvg" in app
    assert 'id="rep-velocity-progress"' in page
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
    assert 'id="exercise-detail-extra"' in page and '<details class="advanced">' in page
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
    settings = (STATIC / "settings.js").read_text(encoding="utf-8")
    core = (STATIC / "core.js").read_text(encoding="utf-8")
    assert "applyFieldErrors" in core
    assert "applyFieldErrors(error, $(" in app
    assert "applyFieldErrors(error, $(" in settings
    for marker in (
        '[data-symptom="region"]', '[data-block="date"]', '[data-break="starts_on"]',
        '#cardio-modality', '#measure-metric',
    ):
        assert marker in app, marker
    for marker in (
        '#settings-volume-fields', '#settings-volume-reason', '#settings-volume-confirm',
        '#settings-llm-model', '#settings-profile-guard',
    ):
        assert marker in settings, marker


def test_volume_panel_is_consolidated_and_linked_to_its_guide() -> None:
    page = INDEX.read_text(encoding="utf-8")
    settings = (STATIC / "settings.js").read_text(encoding="utf-8")

    assert 'id="settings-volume-form"' in page
    assert 'href="#docs?doc=docs/VOLUME-BUDGET.md"' in page
    assert 'id="settings-drop-form"' not in page
    assert 'id="profile-volume' not in page
    assert 'setting.group === "Volume"' in settings
    assert "renderVolumeSettings" in settings
    assert "/api/settings/volume" in settings
    assert "budgetValue(key)" in settings
    assert "settings-volume-cap-sum" in settings

    node = shutil.which("node")
    if node:
        match = re.search(r"function volumeNestedValue\([^)]*\) \{[\s\S]*?\n\}", settings)
        assert match, "volumeNestedValue() not found"
        script = (
            f"eval({json.dumps(match.group(0))});"
            "const budget = {session_cap: {total: 30}, tolerance: 0.1};"
            "if (volumeNestedValue(budget, 'session_cap.total') !== 30) throw new Error('nested cap');"
            "if (volumeNestedValue(budget, 'tolerance') !== 0.1) throw new Error('flat value');"
            "if (volumeNestedValue(budget, 'missing.total') !== undefined) throw new Error('missing');"
        )
        result = _run_node(script)
    assert result.returncode == 0, result.stderr


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
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_monitoring_analysis_charts_and_missingness_render() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "performance.js").read_text(encoding="utf-8") + "\n" + (STATIC / "analytics-charts.js").read_text(encoding="utf-8")
    script = r"""
global.__target = {innerHTML: "", dataset: {}, addEventListener: function () {}};
global.document = {getElementById: function () { return global.__target; }};
global.esc = function (value) { return String(value == null ? "" : value); };
global.fmt = function (value) { return Number(value).toFixed(1).replace(/\.0+$/, ""); };
global.today = function () { return "2024-01-31"; };
global.api = function () { return Promise.resolve({}); };
eval(SOURCE);
renderMonitoringAnalysis({
  meta: {as_of: "2024-01-31", analysis_version: "monitoring-analysis-v1",
         seed: 0, database_fingerprint: "abc"},
  missingness: {sessions: 3, sessions_with_feedback: 2, sets: 10, exercises: 1},
  dose: [{date: "2024-01-01", session_type: "hinge", working_sets: 2, hard_sets: 1,
          tonnage_kg: null, tonnage_status: "unavailable_missing_tonnage", session_load_au: null},
         {date: "2024-01-08", session_type: "hinge", working_sets: 3, hard_sets: 2,
          tonnage_kg: 0, tonnage_status: "observed_zero", session_load_au: 100},
         {date: "2024-01-15", session_type: "hinge", working_sets: 4, hard_sets: 3,
          tonnage_kg: 500, tonnage_status: "observed", session_load_au: 200}],
  associations: [{exercise_id: "squat", observations: 4,
    dose: [{date: "2024-01-01", working_sets: 2, hard_sets: 1},
           {date: "2024-01-08", working_sets: 3, hard_sets: 2}],
    hard_sets_vs_next_e1rm: {n: 3, r: 0.5, status: "descriptive"},
    session_load_vs_next_e1rm: {n: 2, r: null, status: "insufficient"},
    hard_sets_points: [{x: 1, y: 100}, {x: 2, y: 110}, {x: 3, y: 120}],
    session_load_points: [{x: 100, y: 100}, {x: 200, y: 110}]}],
  calibration: {as_of: "2024-01-31", method_version: "epley_rir_v1",
    historical_state_reconstructable: false,
    note: "Current as-of state.", observations: [{performed_on: "2024-01-20",
    calibration_context_as_of: "2024-01-31", exercise_id: "squat", measured_kg: 120,
    prior_raw_e1rm_kg: 110, prior_raw_method: "epley_plus_rir",
    prior_raw_method_version: "epley_rir_v1", existing_calibration_factor: 1.0,
    existing_factor_applied: false, calibration_ci_low: null, calibration_ci_high: null}]},
  limitations: []
});
var html = global.__target.innerHTML;
if (html.indexOf("<svg") < 0) throw new Error("charts missing");
if (html.indexOf("chart-frame") < 0) throw new Error("chart expand frame missing");
if (html.indexOf("Session date") < 0) throw new Error("x axis title missing");
if (html.indexOf("squat training dose over time") < 0) throw new Error("per-exercise dose chart missing");
if (html.indexOf("Hard sets") < 0) throw new Error("scatter x axis title missing");
if (html.indexOf("click to enlarge") < 0) throw new Error("expand hint missing");
if (html.indexOf("Insufficient observations for squat session load vs next e1RM") < 0) throw new Error("insufficient chart state");
if (html.indexOf("2024-01-31") < 0) throw new Error("calibration context date");
if (html.indexOf("Unavailable") < 0) throw new Error("missing tonnage shown as unavailable");
if (html.indexOf("0 kg (observed_zero)") < 0) throw new Error("genuine zero lost");
"""
    script = script.replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_performance_chart_renders_a_single_observation() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "performance.js").read_text(encoding="utf-8") + "\n" + (STATIC / "analytics-charts.js").read_text(encoding="utf-8")
    script = r"""
global.__target = {innerHTML: ""};
global.document = {getElementById: function () { return global.__target; },
                  addEventListener: function () {}};
global.esc = function (value) { return String(value == null ? "" : value); };
global.fmt = function (value) { return Number(value).toFixed(1).replace(/\.0+$/, ""); };
global.today = function () { return "2024-01-31"; };
global.api = function () { return Promise.resolve({}); };
eval(SOURCE);
renderPerformanceE1rm({
  exercise_id: "ssb_squat",
  points: [{date: "2024-01-20", kg: 120, rolling_median_kg: 120, n_window: 1}],
  summary: {n: 1, status: "points_only", latest: {date: "2024-01-20", kg: 120},
            recent_median_kg: 120},
});
var html = global.__target.innerHTML;
if (html.indexOf("<svg") < 0) throw new Error("single-point chart missing");
if (html.indexOf("Raw e1RM observations") < 0) throw new Error("chart title missing");
if (html.indexOf("Date") < 0) throw new Error("date axis missing");
if (html.indexOf("chart-series-median") < 0) throw new Error("rolling median overlay missing");
if (html.indexOf("rolling median") < 0) throw new Error("rolling median legend missing");
"""
    script = script.replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_measurement_pagination_and_volume_controls_are_present() -> None:
    page = INDEX.read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    progress = (STATIC / "progress.js").read_text(encoding="utf-8")
    assert 'id="measure-older"' not in page  # button is rendered only when a next page exists
    assert "measure-older" in app
    assert "progress-accounting" in page
    assert "progress-weekly" in page
    assert "volumeData.groups" in progress
    assert "effective_counts" in progress
    assert "progressRenderWeekly" in progress


def test_progress_ratio_chart_is_observation_based_and_handles_empty_data() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "performance.js").read_text(encoding="utf-8") + "\n" + (STATIC / "analytics-charts.js").read_text(encoding="utf-8")
    script = r"""
global.esc = function (value) { return String(value == null ? "" : value); };
eval(SOURCE);
const empty = progressRatioSvg([], "Cross-lift ratio");
if (empty.indexOf("No performance-ratio observations") < 0) throw new Error("empty state missing");
const html = progressRatioSvg([
  {date: "2024-01-01", ratio: 0.91, lifts: 2},
  {date: "2024-01-20", ratio: 1.06, lifts: 3}
], "Cross-lift ratio");
if (html.indexOf("<svg") < 0) throw new Error("chart missing");
if (html.indexOf("2024-01-01: ratio 0.910; 2 lift comparisons") < 0) throw new Error("exact tooltip missing");
if (html.indexOf("chart-reference") < 0) throw new Error("neutral reference line missing");
if (html.indexOf("no values are imputed") < 0) throw new Error("missing-data disclosure missing");
if (html.indexOf("role='button'") < 0 || html.indexOf("tabindex='0'") < 0) throw new Error("accessible expansion missing");
"""
    script = script.replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_longevity_coverage_counts_observations_and_uses_returned_fields() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    match = re.search(r"async function loadLongevity\(\) \{[\s\S]*?\n\}", source)
    assert match, "loadLongevity() not found"
    script = r"""
const els = {
  "#longevity-weeks": {value: "8"}, "#longevity-date": {value: "2024-01-31"},
  "#longevity-summary": {innerHTML: ""}, "#longevity-details": {innerHTML: ""}
};
global.$ = function (selector) { return els[selector]; };
global.esc = function (value) { return String(value == null ? "" : value); };
global.fmt = function (value) { return Number(value).toFixed(1).replace(/\.0+$/, ""); };
global.api = function () { return Promise.resolve({
  window: {from: "2023-12-07", to: "2024-01-31"},
  longevity: {cardio: {average_weekly_minutes: null, reference_min: 150, reference_max: 300, weekly_minutes: {}},
    measurements: {bodyweight_kg: {count: 0}, grip_strength_kg: {count: 2, latest_value: 44, change: 4, latest_on: "2024-01-20"}},
    readiness: {fields: {sleep: {n: 1, average: 4, first: 4, last: 4}, energy: {n: 0}, stress: {n: 0}, soreness: {n: 0}}},
    symptoms: {}},
  strength: {symptoms: {regions: {}}, attendance: {completed: 0, pct: null}}, note: "descriptive"
}); };
eval(FUNCTION);
loadLongevity().then(() => {
  const html = els["#longevity-summary"].innerHTML;
  if (!html.includes("recorded metric types")) throw new Error("metric count label missing");
  if (!html.includes("1/4")) throw new Error("readiness denominator must match returned fields");
  if (html.includes("80%") || html.includes("Going well") || html.includes("Needs attention"))
    throw new Error("unsupported status threshold remains");
  if (!html.includes("latest values below use available history")) throw new Error("measurement window caveat missing");
});
""".replace("FUNCTION", json.dumps(match.group(0)))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_today_workout_action_handles_active_and_missing_workouts() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    match = re.search(r"function todaySessionActionLabel\(workout\) \{[\s\S]*?\n\}", source)
    assert match, "todaySessionActionLabel() not found"
    script = f"eval({json.dumps(match.group(0))});\n"
    script += "if (todaySessionActionLabel({status: 'in_progress'}) !== 'Continue workout') throw new Error('active action');\n"
    script += "if (todaySessionActionLabel(null) !== 'Start today’s workout') throw new Error('missing action');\n"
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_progress_overview_renders_strength_dose_frequency_and_real_api_fields() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    app = (STATIC / "progress.js").read_text(encoding="utf-8")
    charts = (STATIC / "analytics-charts.js").read_text(encoding="utf-8")
    performance = (STATIC / "performance.js").read_text(encoding="utf-8")
    source = performance + "\n" + charts + "\n" + app
    script = r"""
function el(value) { return {innerHTML: "", textContent: "", value: value || "", disabled: false,
  addEventListener: function () {}}; }
const els = {
  "#progress-dashboard": el(), "#progress-overview-status": el(), "#progress-overview-weeks": el("4"),
  "#progress-overview-date": el("2024-04-30"), "#progress-exercise": el(), "#progress-pattern": el(),
  "#progress-strength-chart": el(), "#progress-strength-summary": el(), "#progress-load-chart": el(),
  "#progress-dose-chart": el(), "#progress-dose-note": el(), "#progress-frequency-chart": el(),
  "#progress-calendar": el(), "#progress-exercise-frequency-chart": el(), "#progress-exercise-volume-chart": el(),
  "#progress-frequency-note": el(), "#progress-ratio-chart": el(), "#progress-association": el(), "#progress-load-association": el(),
  "#progress-workout": el(), "#progress-execution": el(), "#progress-accounting": el(),
  "#progress-weekly": el(), "#progress-weekly-note": el()
};
global.$ = function (selector) { return els[selector] || null; };
global.document = {addEventListener: function () {}};
global.esc = function (value) { return String(value == null ? "" : value); };
global.fmt = function (value) { return Number(value).toFixed(1).replace(/\.0+$/, ""); };
global.today = function () { return "2024-04-30"; };
const calls = [];
global.api = function (url) {
  calls.push(url);
  if (url.startsWith("/api/outcomes")) return Promise.resolve({window: {from: "2024-04-03", to: "2024-04-30"}, note: "descriptive",
    strength: {sessions: 3, attendance: {completed: 3, target: 4, weeks: 4, pct: 75},
      main_lifts: [{exercise_id: "ssb_squat", n: 2, first_e1rm: 100, first_on: "2024-04-05", last_e1rm: 105,
        last_on: "2024-04-25", change_kg: 5, best_e1rm: 105}], volume: [], sRPE: {n: 2, average: 6.5}}});
  if (url.startsWith("/api/volume")) return Promise.resolve({from: "2024-04-08", to: "2024-04-30", weeks: [16, 17], patterns: [{pattern: "squat", weeks: [6, 7], total: 13}],
    coverage: {mode: "unknown", observed_weeks: 2, denominator: 2}});
  if (url.startsWith("/api/history/days")) return Promise.resolve({days: [
    {occurred_on: "2024-04-05", active_fragment_count: 1, workout_ids: []},
    {occurred_on: "2024-04-08", active_fragment_count: 0, workout_ids: []},
    {occurred_on: "2024-04-25", active_fragment_count: 2, workout_ids: []}
  ]});
  if (url === "/api/performance/relationship-options") return Promise.resolve({exercises: [{id: "ssb_squat", label: "Safety bar squat"}]});
  if (url.startsWith("/api/progress?")) return Promise.resolve({coverage: {with_srpe: 4, sessions: 8, pct: 50},
    performance: {points: [{date: "2024-04-25", ratio: 1.02, lifts: 2}]},
    weekly: {weeks: [{week_start: "2024-04-22", week_end: "2024-04-28", working_sets: 4,
      hard_sets: 3, rir: {observed_sets: 3, mean: 2.0}, tonnage_kg: 800,
      tonnage: {observed_sets: 3}, residual: {n: 1, mean_mps: 0.1, status: "insufficient"}}],
      missing_weeks: ["2024-04-15"]}});
  if (url.startsWith("/api/performance/e1rm")) return Promise.resolve({exercise_id: "ssb_squat", points: [
    {date: "2024-04-05", kg: 100, rolling_median_kg: 100, n_window: 1},
    {date: "2024-04-25", kg: 105, rolling_median_kg: 102.5, n_window: 2}],
    summary: {n: 2, status: "points_only", latest: {date: "2024-04-25", kg: 105}, best: {date: "2024-04-25", kg: 105}}});
  if (url.startsWith("/api/exercise-history")) return Promise.resolve({total: 1, has_more: false, start: "2024-04-03", end: "2024-04-30", included_exercises: [],
    analytics: {session_count: 1, training_dates: 1, working_sets: 1, load_observed_sets: 1, load_missing_sets: 0,
      reps_observed_sets: 1, reps_missing_sets: 0, rir_observed_sets: 1, rir_missing_sets: 0,
      tonnage_observed_sets: 1, tonnage_missing_sets: 0,
      daily: [{date: "2024-04-05", sessions: 1, working_sets: 1, tonnage_kg: 400, tonnage_observed_sets: 1}],
      weekly: [{iso_year: 2024, iso_week: 14, start: "2024-04-03", end: "2024-04-09", training_dates: 1, working_sets: 1}],
      loads: [{basis: "external", points: [{date: "2024-04-05", median_kg: 80, observations: 1}]}],
      repetitions: [{unit: "reps", points: [{date: "2024-04-05", total: 5, observed_sets: 1}]}],
      rir: [{date: "2024-04-05", median: 2, observations: 1}], rir_distribution: [{rir: 2, sets: 1}],
      tonnage_daily: [{date: "2024-04-05", tonnage_kg: 400, tonnage_observed_sets: 1, working_sets: 1}]}, sessions: []});
  return Promise.reject(new Error("unexpected API request: " + url));
};
eval(SOURCE);
loadProgressOverview().then(() => {
  if (!calls.some((url) => url.startsWith("/api/outcomes?weeks=4&date=2024-04-30"))) throw new Error("outcomes as-of filter missing");
  if (!calls.some((url) => url.startsWith("/api/volume?date=2024-04-30&weeks=4"))) throw new Error("volume window missing");
  if (!calls.some((url) => url.includes("/api/history/days?start=2024-04-03&end=2024-04-30"))) throw new Error("history date window missing");
  if (!calls.some((url) => url.includes("/api/performance/e1rm?exercise_id=ssb_squat&from=2024-04-03&to=2024-04-30"))) throw new Error("selected exercise date filter missing");
  if (els["#progress-exercise"].value !== "ssb_squat") throw new Error("main-lift-first default missing");
  if (!els["#progress-strength-chart"].innerHTML.includes("Trailing 3-observation median")) throw new Error("e1RM rolling median missing");
  if (!els["#progress-dose-chart"].innerHTML.includes("weekly working sets")) throw new Error("dose chart missing");
  if (!els["#progress-dose-chart"].innerHTML.includes("2024-04-15 to 2024-04-21")) throw new Error("exact volume week dates missing");
  const yearCrossing = progressVolumeCategories({from: "2023-12-25", to: "2024-01-07", weeks: [52, 1]});
  if (yearCrossing[0].label !== "W52 2023" || yearCrossing[1].label !== "W1 2024" || yearCrossing[1].start !== "2024-01-01") throw new Error("ISO week-year mapping incorrect");
  if (!els["#progress-frequency-chart"].innerHTML.includes("Recorded training days")) throw new Error("frequency chart missing");
  if (!els["#progress-frequency-note"].textContent.includes("not planned dates")) throw new Error("target semantics missing");
  if (!els["#progress-calendar"].innerHTML.includes("2024-04-05")) throw new Error("observed-day calendar missing");
  if (!els["#progress-exercise-frequency-chart"].innerHTML.includes("training dates per ISO week")) throw new Error("exercise exposure frequency missing");
  if (!els["#progress-exercise-volume-chart"].innerHTML.includes("working sets per ISO week")) throw new Error("exercise working-set volume missing");
  if (!els["#progress-load-chart"].innerHTML.includes("median recorded load")) throw new Error("load trend missing");
  if (!els["#progress-load-chart"].innerHTML.includes("recorded RIR")) throw new Error("RIR history missing");
  if (!els["#progress-dashboard"].innerHTML.includes("all-to-date coverage 4 / 8")) throw new Error("sRPE coverage field missing");
  if (!els["#progress-dashboard"].innerHTML.includes("Main-lift change table")) throw new Error("main-lift change detail missing");
  if (!els["#progress-ratio-chart"].innerHTML.includes("ratio 1.020; 2 lift comparisons")) throw new Error("existing ratio chart missing");
  if (!els["#progress-dashboard"].innerHTML.includes("bodyweight-relative strength")) throw new Error("unsupported graph limitations missing");
  if (!els["#progress-weekly"].innerHTML.includes("RIR observed / mean")) throw new Error("weekly RIR table missing");
  if (!els["#progress-weekly"].innerHTML.includes("0.1 m/s")) throw new Error("weekly residual missing");
  if (!els["#progress-weekly-note"].textContent.includes("missing weeks")) throw new Error("weekly missing-week caveat missing");
  if (els["#progress-overview-status"].textContent !== "Updated") throw new Error("status missing");
});
""".replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_health_longevity_charts_preserve_logged_observations_and_methods() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    chunks = []
    for name in ("cardioWeeklyChart", "measurementHistoryChart", "measureChartMetrics",
                 "measureWindowFrom", "measureWindowLabel"):
        match = re.search(r"function " + name + r"\([\s\S]*?^}", source, re.MULTILINE)
        assert match, f"{name}() not found"
        chunks.append(match.group(0))
    script = r"""
global.esc = function (value) { return String(value == null ? "" : value); };
global.formatLocalDate = function (date) {
  return date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" +
    String(date.getDate()).padStart(2, "0");
};
let barSpec = null, lineSpec = null;
global.groupedBarChart = function (spec) { barSpec = spec; return "bars"; };
global.dateSeriesChart = function (spec) { lineSpec = spec; return "dots"; };
eval(CHUNKS);
const cardio = cardioWeeklyChart({weekly_minutes: {"2024-W01": 45, "2024-W03": 20}, reference_min: 150, reference_max: 300});
if (cardio !== "bars") throw new Error("weekly cardio chart not returned");
if (barSpec.categories.map(x => x.label).join(",") !== "2024-W01,2024-W03") throw new Error("unlogged weeks were invented");
if (barSpec.series[0].values.join(",") !== "45,20") throw new Error("logged minutes changed");
if (barSpec.referenceLines.length !== 2 || barSpec.referenceLines[0].value !== 150 || barSpec.referenceLines[1].value !== 300)
  throw new Error("cardio context references missing");
if (!barSpec.note.includes("omitted, not treated as zero") || !barSpec.note.includes("partial"))
  throw new Error("cardio missing-data caveat absent");
if (!cardioWeeklyChart({weekly_minutes: {}}).includes("No logged cardio weeks")) throw new Error("cardio empty state absent");

const data = {summary: [{key: "grip", label: "Grip", unit: "kg"}], entries: [
  {metric_key: "grip", measured_on: "2024-01-01", value: 30, method: "dynamometer"},
  {metric_key: "grip", measured_on: "2024-01-01", value: 31, method: "dynamometer"},
  {metric_key: "grip", measured_on: "2024-02-01", value: 32, method: "alternate device"},
  {metric_key: "steps", measured_on: "2024-02-02", value: 9000, method: null}
]};
if (measurementHistoryChart(data, "grip") !== "dots") throw new Error("measurement chart not returned");
if (lineSpec.series.length !== 2 || lineSpec.series.some(x => x.line !== false)) throw new Error("measurement methods were combined or connected");
if (lineSpec.series.reduce((sum, series) => sum + series.points.length, 0) !== 3) throw new Error("measurement observations were averaged or discarded");
if (!lineSpec.note.includes("newest-first pages") || !lineSpec.note.includes("no averaging, interpolation")) throw new Error("measurement coverage caveat absent");
if (!measurementHistoryChart(data, "missing").includes("Select a configured measurement")) throw new Error("metric empty state absent");
const charted = measureChartMetrics([{key: "a", count: 0}, {key: "b", count: 3}, {key: "c", count: null}, {key: "d", count: 1}]);
if (charted.map(m => m.key).join(",") !== "b,d") throw new Error("only recorded measures may get a chart");
const perMetric = measurementHistoryChart({summary: data.summary, entries: data.entries}, "grip", true, "the last 3 months");
if (perMetric !== "dots") throw new Error("per-metric chart not returned");
if (!lineSpec.note.includes("the last 3 months (3)") || !lineSpec.note.includes("no averaging"))
  throw new Error("per-metric chart window note missing");
const boundary = new Date(2024, 5, 15);
if (measureWindowFrom("3", boundary) !== "2024-03-15") throw new Error("window start incorrect");
if (measureWindowFrom("all", boundary) !== "") throw new Error("all-history window must be unbounded");
if (measureWindowLabel("all") !== "all history" || measureWindowLabel("6") !== "the last 6 months")
  throw new Error("window label incorrect");
""".replace("CHUNKS", json.dumps("\n".join(chunks)))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_measures_page_charts_every_metric_with_recorded_data() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function measureChartMetrics" in app
    assert "data-measure-chart" in app
    assert "loadMeasureCharts" in app
    assert "measureWindowFrom" in app
    assert "fetchMeasurementWindow" in app
    assert '"/api/measurements?"' in app
    assert "metric_key: metricKey" in app
    page = INDEX.read_text(encoding="utf-8")
    assert 'id="measure-result"' in page
    assert 'id="measure-window"' in page
    assert '<option value="all">all history</option>' in page


def test_shared_chart_core_renders_dates_bars_tooltips_and_reference_bands() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "performance.js").read_text(encoding="utf-8") + "\n" + (STATIC / "analytics-charts.js").read_text(encoding="utf-8")
    script = r"""
global.esc = function (value) { return String(value == null ? "" : value); };
global.fmt = function (value) { return Number(value).toFixed(1); };
global.document = {addEventListener: function () {}};
eval(SOURCE);
const line = dateSeriesChart({title: "Strength", xTitle: "Date", yTitle: "kg",
  series: [{id: "raw", label: "Raw", points: [{date: "2024-01-01", value: 100}, {date: "2024-01-31", value: 110}]},
           {id: "median", label: "Rolling median", points: [{date: "2024-01-01", value: 100}, {date: "2024-01-31", value: 105}]}],
  referenceLines: [{value: 100, label: "Reference"}], referenceBands: [{from: 101, to: 104, label: "Band"}]});
if (!line.includes("2024-01-01: Raw 100")) throw new Error("exact point tooltip missing");
if (!line.includes("data-chart-series-toggle='median'")) throw new Error("series toggle missing");
if (!line.includes("aria-pressed='true'")) throw new Error("accessible series state missing");
if (!line.includes("chart-reference-band") || !line.includes("chart-reference")) throw new Error("reference overlays missing");
if (!line.includes("68.0,") || !line.includes("622.0,")) throw new Error("date-proportional spacing missing");
const bars = groupedBarChart({title: "Dose", categories: [{label: "W1"}, {label: "W2"}],
  series: [{id: "sets", label: "Working sets", values: [3, 5]}, {id: "hard", label: "Hard sets", values: [2, null]}],
  referenceLines: [{value: 4, label: "Target"}]});
if ((bars.match(/<rect class=/g) || []).length !== 3) throw new Error("bar series/missing-value behavior incorrect");
if (!bars.includes("Target") || !bars.includes("Working sets")) throw new Error("bar labels missing");
if (!groupedBarChart({categories: [], series: []}).includes("No observations")) throw new Error("empty state missing");
""".replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_chart_series_toggle_and_complete_range_exercise_analytics() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "performance.js").read_text(encoding="utf-8") + "\n" + (STATIC / "analytics-charts.js").read_text(encoding="utf-8") + "\n" + (STATIC / "progress.js").read_text(encoding="utf-8")
    script = r"""
const listeners = [];
const els = {"#progress-exercise-frequency-chart": {innerHTML: ""}, "#progress-exercise-volume-chart": {innerHTML: ""}};
global.$ = function (selector) { return els[selector] || null; };
global.document = {addEventListener: function (name, callback) { listeners.push({name, callback}); }};
global.esc = function (value) { return String(value == null ? "" : value); };
global.fmt = function (value) { return Number(value).toFixed(1); };
eval(SOURCE);
let pressed = "true";
const group = {style: {}, getAttribute: function (name) { return name === "data-chart-series" ? "raw" : null; }};
const chart = {querySelectorAll: function () { return [group]; }};
const button = {closest: function (selector) { return selector === "[data-chart-series-toggle]" ? button : chart; },
  getAttribute: function (name) { return name === "data-chart-series-toggle" ? "raw" : pressed; },
  setAttribute: function (name, value) { if (name === "aria-pressed") pressed = value; }};
const seriesHandler = listeners.filter(function (entry) { return entry.name === "click"; }).pop().callback;
seriesHandler({target: button});
if (pressed !== "false" || group.style.display !== "none") throw new Error("series did not hide");
seriesHandler({target: button});
if (pressed !== "true" || group.style.display !== "") throw new Error("series did not restore");
progressRenderExerciseExposure({weekly: [
  {iso_year: 2024, iso_week: 14, start: "2024-04-03", end: "2024-04-09", training_dates: 0, working_sets: 0},
  {iso_year: 2024, iso_week: 15, start: "2024-04-10", end: "2024-04-16", training_dates: 1, working_sets: 3},
  {iso_year: 2024, iso_week: 16, start: "2024-04-17", end: "2024-04-23", training_dates: 0, working_sets: 0}
]}, "2024-04-03", 6, "squat", "Squat", {included_exercises: []});
const frequency = els["#progress-exercise-frequency-chart"].innerHTML;
if (!frequency.includes("complete-range Python aggregates")) throw new Error("complete-range analytics disclosure missing");
if (!frequency.includes("W14 2024") || !frequency.includes("W15 2024")) throw new Error("complete older ISO-week analytics missing");
if ((frequency.match(/<rect class=/g) || []).length !== 3) throw new Error("complete weekly categories missing");
""".replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_progress_association_and_original_workout_execution_are_descriptive() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "performance.js").read_text(encoding="utf-8") + "\n" + (STATIC / "analytics-charts.js").read_text(encoding="utf-8") + "\n" + (STATIC / "progress.js").read_text(encoding="utf-8")
    script = r"""
function el(value) { return {innerHTML: "", textContent: "", value: value || "", disabled: false, addEventListener: function () {}}; }
const els = {"#progress-execution": el(), "#progress-association": el(), "#progress-exercise": el("squat"), "#progress-load-association": el()};
global.$ = function (selector) { return els[selector] || null; };
global.document = {addEventListener: function () {}};
global.esc = function (value) { return String(value == null ? "" : value); };
global.fmt = function (value) { return Number(value).toFixed(1); };
global.api = function (url) {
  if (url === "/api/workout/w1") return Promise.resolve({workout: {status: "completed", for_date: "2024-04-25", plan_modified: true,
    original_plan: {items: [{exercise_id: "squat", sets: 2}, {exercise_id: "bench", sets: 3}]},
    sets: [{}, {}, {}, {}]}});
  if (url.includes("/api/monitoring-analysis")) return Promise.resolve({meta: {as_of: "2024-04-30", note: "Descriptive associations only."},
    associations: [{exercise_id: "squat", hard_sets_points: [{x: 1, y: 100}, {x: 2, y: 110}, {x: 3, y: 120}],
      hard_sets_vs_next_e1rm: {n: 3, r: 0.5, status: "descriptive"}, session_load_points: [], session_load_vs_next_e1rm: {n: 0, r: null, status: "insufficient"}}]});
  return Promise.reject(new Error("unexpected API request " + url));
};
eval(SOURCE);
Promise.all([loadProgressExecution("w1"), loadProgressAssociation()]).then(() => {
  if (!els["#progress-execution"].innerHTML.includes("Original planned sets")) throw new Error("original prescription series missing");
  if (!els["#progress-execution"].innerHTML.includes("Logged set rows")) throw new Error("logged execution missing");
  if (!els["#progress-execution"].innerHTML.includes("original start-time plan")) throw new Error("edited-plan disclosure missing");
  if (!els["#progress-association"].innerHTML.includes("Prior hard sets vs next e1RM")) throw new Error("dose/performance association missing");
  if (!els["#progress-association"].innerHTML.includes("not refit or predict")) throw new Error("association caveat missing");
});
""".replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr

def test_step5_report_controls_are_wired() -> None:
    page = INDEX.read_text(encoding="utf-8")
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    settings = (STATIC / "settings.js").read_text(encoding="utf-8")
    for marker in (
        'id="state-e1rm-calibration-window"',
        'id="state-e1rm-coverage-window"',
        'id="volume-weeks"',
        'id="volume-date"',
        'id="continuity-date"',
        'id="fatigue-date"',
        'id="validation-max-dates"',
        'id="state-symptom-history"',
        'id="state-test-cadence"',
    ):
        assert marker in page
    assert "/api/e1rm/" in source
    assert 'coverage" ? "tests-needed" : "calibration"' in source
    assert "/api/symptoms/history" in source
    assert "/api/test-cadence" in source
    assert "Show all " in source
    assert "Measured-test coverage:" in source
    assert "Record a strength test" in source
    assert "state-test-record" in source
    assert "Show calibration details" in source
    assert "calibration-details" in source
    assert "Session time cap min" not in settings
    assert "Session target comes from the Athlete profile" in settings


def test_relationship_crud_ui_is_wired() -> None:
    source = (STATIC / "performance.js").read_text(encoding="utf-8")
    assert "/api/performance/relationships" in source
    assert "/update" in source
    assert "endpointAction" in source
    assert "data-relationship-action='delete'" in source
    assert "data-relationship-action='reset'" in source
    assert "Locally hidden pairs" in source
    assert "Confirm delete" in source
    assert "id='relationship-add-submit' disabled" in source
    assert 'item.origin === "canonical"' in source
    assert "Reload configuration" in source


def test_relationship_conflict_reload_is_explicit_and_contextual() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "performance.js").read_text(encoding="utf-8")
    start = source.index("async function reloadRelationshipConfig(stableId, button) {")
    end = source.index("var RELATIONSHIP_TYPE_OPTIONS", start)
    function_source = source[start:end]
    script = r"""
const elements = {
  "performance-relationship-feedback": {innerHTML: "", textContent: ""},
  "relationship-add-status": {innerHTML: "", textContent: ""},
};
const buttons = {};
global.document = {
  getElementById(id) {
    if (elements[id]) return elements[id];
    if (id.startsWith("relationship-reload-")) {
      if (!buttons[id]) {
        buttons[id] = {disabled: false, textContent: "", click: null,
          addEventListener(name, fn) { if (name === "click") this.click = fn; }};
      }
      return buttons[id];
    }
    return null;
  }
};
global.esc = value => String(value);
var relationshipReloadInFlight = {};
let success = false;
let reloads = 0;
global.loadRelationshipConfig = async function (force) {
  if (force) reloads += 1;
  return success;
};
eval(FUNC);
(async () => {
  showRelationshipConflict("performance-relationship-feedback");
  const feedback = elements["performance-relationship-feedback"];
  if (!feedback.innerHTML.includes("Configuration changed elsewhere")) throw new Error("missing conflict message");
  if (reloads !== 0) throw new Error("conflict auto-retried");
  const first = buttons["relationship-reload-performance-relationship-feedback"];
  first.click();
  if (!first.disabled || first.textContent !== "Reloading…") {
    throw new Error("reload control did not enter loading state");
  }
  await Promise.resolve();
  if (reloads !== 1) throw new Error("reload was not attempted");
  if (!feedback.innerHTML.includes("could not be retrieved")) throw new Error("failed reload looked successful");
  if (feedback.innerHTML.includes("Configuration reloaded")) throw new Error("false success message");
  const retry = buttons["relationship-reload-performance-relationship-feedback-retry"];
  if (!retry) throw new Error("retry action missing after failed reload");
  success = true;
  retry.click();
  if (!retry.disabled || retry.textContent !== "Reloading…") {
    throw new Error("retry control did not enter loading state");
  }
  retry.click();
  await Promise.resolve();
  if (reloads !== 2) throw new Error("concurrent retry invoked an extra reload");
  if (feedback.textContent !== "Configuration reloaded. Review the pairs and retry.") {
    throw new Error("successful retry did not report success");
  }
  showRelationshipConflict("relationship-add-status");
  if (!elements["relationship-add-status"].innerHTML.includes("Configuration changed elsewhere")) {
    throw new Error("add conflict used the wrong context");
  }
  if (!feedback.textContent.includes("Configuration reloaded")) {
    throw new Error("add conflict overwrote unrelated feedback");
  }
})().catch(error => { throw error; });
"""
    script = script.replace("FUNC", json.dumps(function_source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_relationship_config_reload_returns_failure_and_clears_stale() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "performance.js").read_text(encoding="utf-8")
    start = source.index("async function loadRelationshipConfig(force) {")
    end = source.index("function renderPerformanceRatios(data) {", start)
    function_source = source[start:end]
    script = r"""
const host = {innerHTML: ""};
const add = {disabled: true, title: ""};
global.document = {getElementById(id) {
  if (id === "performance-relationship-management") return host;
  if (id === "relationship-add-submit") return add;
  return null;
}};
global.esc = value => String(value);
global.renderRelationshipManagement = () => {};
var performanceRelationshipConfig = {revision: "old"};
let fail = false;
global.api = async function () {
  if (fail) throw new Error("network unavailable");
  return {revision: "new", relationships: [], hidden: []};
};
eval(FUNC);
(async () => {
  const ok = await loadRelationshipConfig(true);
  if (!ok) throw new Error("successful reload returned failure");
  if (!performanceRelationshipConfig || performanceRelationshipConfig.revision !== "new") {
    throw new Error("successful reload did not update configuration");
  }
  if (add.disabled) throw new Error("add remained disabled after successful reload");
  fail = true;
  const failed = await loadRelationshipConfig(true);
  if (failed) throw new Error("failed reload returned success");
  if (performanceRelationshipConfig !== null) throw new Error("stale configuration was retained");
  if (!add.disabled) throw new Error("add was not disabled after failed reload");
  if (!host.innerHTML.includes("Pair configuration failed")) throw new Error("reload error not displayed");
})().catch(error => { throw error; });
"""
    script = script.replace("FUNC", json.dumps(function_source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr
def test_monitoring_inventory_reason_disclosures_and_empty_state() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    app = (STATIC / "settings.js").read_text(encoding="utf-8")
    core = (STATIC / "core.js").read_text(encoding="utf-8")
    start = app.index("const MONITORING_SOURCE_LABELS")
    end = app.index("async function loadSettings()", start)
    chunk = app[start:end]
    esc_match = re.search(r"function esc\(value\) \{[\s\S]*?\n\}", core)
    assert esc_match, "esc() not found"

    script = r"""
const elements = {
  "settings-monitoring-groups": {innerHTML: ""},
  "settings-monitoring-group": {value: "", innerHTML: "", dataset: {}, addEventListener() {}},
  "settings-monitoring-summary": {textContent: ""},
  "settings-monitoring-meta": {textContent: "", title: ""},
  "settings-monitoring-phase": {textContent: ""},
  "settings-monitoring-search": {value: "", dataset: {}, addEventListener() {}},
  "settings-monitoring-empty": {hidden: true}
};
global.$ = function (id) { return elements[id.slice(1)]; };
function sectionsFrom(html) {
  const sections = [];
  const sectionRe = /<section class='monitoring-group' data-group='([^']*)'>([\s\S]*?)<\/section>/g;
  let section;
  while ((section = sectionRe.exec(html))) {
    const rows = [];
    const rowRe = /<tr class='monitoring-row' data-group='([^']*)' data-search='([^']*)'/g;
    let row;
    while ((row = rowRe.exec(section[2]))) {
      rows.push({dataset: {group: row[1], search: row[2]}, hidden: false});
    }
    sections.push({hidden: false, querySelectorAll() { return rows; }});
  }
  return sections;
}
global.document = {
  querySelectorAll() { return sectionsFrom(elements["settings-monitoring-groups"].innerHTML); }
};
eval(ESC);
eval(CHUNK);
renderMonitoringInventory({
  application_version: "1.1.0b1",
  revision: "abcdef123456",
  phase: {note: "Phase 5A is active; monitoring and exposure values are locked.", review_due: "2027-01-22"},
  groups: [{key: "monitoring", label: "Monitoring", parameters: [
    {key: "monitoring.a", label: "A", value: 2, unit: "kg",
     source: "config/monitoring.v1.yaml", source_kind: "canonical_config",
     configured: true, editability: "phase5a_locked",
     reason: "<b>why</b> & <script>alert(1)</script>",
     doc: "docs/MONITORING-ANALYSIS.md"},
    {key: "monitoring.b", label: "B", value: 3, unit: "kg",
     source: "config/monitoring.v1.yaml", source_kind: "canonical_config",
     configured: true, editability: "phase5a_locked", reason: "",
     doc: "docs/MONITORING-ANALYSIS.md"}
  ]}]
});
const html = elements["settings-monitoring-groups"].innerHTML;
if (!html.includes("<summary>Why this setting?</summary>")) throw new Error("missing reason summary");
if (html.includes("<script>alert(1)</script>")) throw new Error("reason not escaped");
if (!html.includes("&lt;script&gt;alert(1)&lt;/script&gt;")) throw new Error("escaped reason missing");
if (elements["settings-monitoring-empty"].hidden !== true) throw new Error("empty state should be hidden with results");
elements["settings-monitoring-search"].value = "no-such-parameter";
applyMonitoringFilter();
if (elements["settings-monitoring-empty"].hidden !== false) throw new Error("empty state missing for no matches");
elements["settings-monitoring-search"].value = "";
elements["settings-monitoring-group"].value = "no-such-group";
applyMonitoringFilter();
if (elements["settings-monitoring-empty"].hidden !== false) throw new Error("group filter empty state missing");
elements["settings-monitoring-group"].value = "";
applyMonitoringFilter();
if (elements["settings-monitoring-empty"].hidden !== true) throw new Error("empty state should hide when results return");
"""
    script = script.replace("ESC", json.dumps(esc_match.group(0))).replace("CHUNK", json.dumps(chunk))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_exercise_analytics_charts_render_complete_range_python_observations() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "performance.js").read_text(encoding="utf-8") + "\n" + (STATIC / "analytics-charts.js").read_text(encoding="utf-8")
    script = r"""
function esc(value) { return String(value == null ? "" : value); }
function fmt(value) { return Number(value).toFixed(1).replace(/\.0+$/, ""); }
global.esc = esc; global.fmt = fmt;
global.__frame = function (title, svg, legend, note) { return title + " " + svg + " " + legend + " " + (note || ""); };
var chartFrame = global.__frame;
eval(SOURCE);
const days = Array.from({length: 65}, (_, i) => {
  const date = new Date(Date.UTC(2024, 0, 1 + i)).toISOString().slice(0, 10);
  return {date, sessions: i % 2 ? 1 : 2, working_sets: 3, tonnage_kg: i === 0 ? null : 300 + i,
    tonnage_observed_sets: i === 0 ? 0 : 3, working_sets: 3};
});
const analytics = {session_count: 90, training_dates: 65, working_sets: 195,
  load_observed_sets: 190, load_missing_sets: 5, reps_observed_sets: 180, reps_missing_sets: 15,
  rir_observed_sets: 120, rir_missing_sets: 75, tonnage_observed_sets: 150, tonnage_missing_sets: 45,
  daily: days, loads: [
    {basis: "external", points: days.map(d => ({date: d.date, median_kg: 80, observations: 3}))},
    {basis: "assisted", points: [{date: "2024-03-05", median_kg: 20, observations: 1}]}],
  repetitions: [
    {unit: "reps", points: days.map(d => ({date: d.date, total: 15, observed_sets: 3}))},
    {unit: "seconds", points: [{date: "2024-03-05", total: 60, observed_sets: 2}]}],
  rir: [{date: "2024-01-01", median: 0, observations: 2}],
  rir_distribution: [{rir: 0, sets: 2}, {rir: 2, sets: 10}],
  tonnage_daily: days.filter(d => d.tonnage_kg != null)};
const html = exerciseHistoryAnalyticsCharts(analytics, "Example lift");
if (!html.includes("2024-01-01") || !html.includes("2024-03-05")) throw new Error("complete 65-date range not represented");
if (!html.includes("assisted") || !html.includes("external") || !html.includes("seconds") || !html.includes("reps")) throw new Error("load bases or rep units mixed/omitted");
if (!html.includes("RIR 0") || !html.includes("median recorded RIR")) throw new Error("RIR zero or recorded effort chart missing");
if (!html.includes("stored tonnage_kg") && !html.includes("stored tonnage")) throw new Error("stored tonnage caveat missing");
if (!html.includes("missing 75") || !html.includes("undefined 45")) throw new Error("missingness coverage not displayed");
if (!html.includes("no dates are imputed") && !html.includes("No dates are imputed")) throw new Error("date omission caveat missing");
const empty = exerciseHistoryAnalyticsCharts({working_sets: 0}, "No history");
if (!empty.includes("No completed working-set observations")) throw new Error("empty-state disclosure missing");
""".replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_exercise_history_pages_append_safely_and_report_duplicates() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "exercises.js").read_text(encoding="utf-8")
    names = ["exerciseHistoryUrl", "exerciseMetricCell", "renderExerciseHistoryRecords",
             "compareExerciseSessions", "loadExerciseHistoryPage"]
    chunks = []
    for name in names:
        match = re.search(r"(?:async )?function " + name + r"\([\s\S]*?^}", source, re.MULTILINE)
        assert match, f"{name}() not found"
        chunks.append(match.group(0))
    script = r"""
const els = {
  "#exercise-history-more": {hidden: true, disabled: false, textContent: ""},
  "#exercise-history-page-status": {textContent: ""},
  "#exercise-history-status": {textContent: ""},
  "#exercise-detail-records": {innerHTML: ""},
  "#exercise-detail-dose": {innerHTML: "", insertAdjacentHTML: function (_, html) { this.innerHTML += html; }}
};
global.$ = function (selector) { return els[selector] || null; };
global.window = {__exerciseDetailsId: "lift"};
global.esc = function (value) { return String(value == null ? "" : value); };
global.exerciseHistoryAnalyticsCharts = function () { return "complete-range charts"; };
const EXERCISE_HISTORY_PAGE_SIZE = 50;
let exerciseTrendsGeneration = 1, exerciseHistoryLoading = false;
let exerciseHistoryState = {exerciseId: "lift", display: "Lift", start: "2024-01-01", end: "2024-03-01",
  offset: 0, total: null, sessions: [], hasMore: false, complete: false, analytics: null};
eval(CHUNKS);
function records(begin, count) { return Array.from({length: count}, (_, j) => {
  const index = begin - j;
  return {session_id: "s" + index, occurred_on: new Date(Date.UTC(2024, 0, 1 + index)).toISOString().slice(0, 10),
    session_type: "test", sets: []};
}); }
const urls = [];
global.api = async function (url) {
  urls.push(url);
  const params = new URLSearchParams(url.split("?")[1]);
  const offset = Number(params.get("offset"));
  return {total: 53, start: "2024-01-01", end: "2024-03-01", has_more: offset === 0,
    included_exercises: [], analytics: offset === 0 ? {session_count: 53, working_sets: 53, daily: []} : undefined,
    sessions: offset === 0 ? records(52, 50) : records(2, 3)};
};
(async function () {
  await loadExerciseHistoryPage(1);
  if (exerciseHistoryState.sessions.length !== 50 || exerciseHistoryState.offset !== 50 || !exerciseHistoryState.hasMore)
    throw new Error("first page state not retained");
  await loadExerciseHistoryPage(1);
  if (exerciseHistoryState.sessions.length !== 53 || !exerciseHistoryState.complete)
    throw new Error("second page not appended to completion");
  if (new Set(exerciseHistoryState.sessions.map(x => x.session_id)).size !== 53)
    throw new Error("duplicate session rows were rendered");
  if (els["#exercise-history-status"].textContent.indexOf("Complete: 53 session records") !== 0)
    throw new Error("complete state not announced");
  const offsets = urls.map(url => new URLSearchParams(url.split("?")[1]).get("offset"));
  if (offsets.join(",") !== "0,50") throw new Error("page offsets advanced incorrectly");

  exerciseTrendsGeneration = 2;
  exerciseHistoryState = {exerciseId: "lift", display: "Lift", start: "2024-01-01", end: "2024-03-01",
    offset: 50, total: 53, sessions: records(52, 50), hasMore: true, complete: false, analytics: {session_count: 53}};
  global.api = async function () { return {total: 53, start: "2024-01-01", end: "2024-03-01", has_more: true,
    sessions: [{session_id: "s3", occurred_on: "2024-01-04", session_type: "test", sets: []}]}; };
  await loadExerciseHistoryPage(2);
  if (exerciseHistoryState.sessions.length !== 50) throw new Error("duplicate page partially appended");
  if (!els["#exercise-history-status"].textContent.includes("History records incomplete: Duplicate"))
    throw new Error("duplicate page was not surfaced as incomplete");
})();
""".replace("CHUNKS", json.dumps("\n".join(chunks)))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_exercise_history_range_and_all_history_buttons_refetch() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "exercises.js").read_text(encoding="utf-8")
    handlers = []
    for selector, event in (("exercise-history-range-form", "submit"), ("exercise-history-all", "click")):
        pattern = r'\$\("#' + selector + r'"\)\.addEventListener\("' + event + r'", function \([^)]*\) \{[\s\S]*?\n\}\);'
        match = re.search(pattern, source)
        assert match, f"{selector} handler not found"
        handlers.append(match.group(0))
    script = r"""
const controls = {
  "#exercise-history-range-form": {addEventListener: function (_, handler) { this.handler = handler; },
    querySelector: function () { return {disabled: false}; }},
  "#exercise-history-all": {value: "", addEventListener: function (_, handler) { this.handler = handler; }},
  "#exercise-history-start": {value: ""}, "#exercise-history-end": {value: ""}
};
global.$ = function (selector) { return controls[selector]; };
global.window = {__exerciseDetailsRow: {id: "lift"}};
let fetches = 0, prevented = false;
global.loadExerciseTrends = function (row) { if (row.id !== "lift") throw new Error("wrong exercise"); fetches += 1; };
eval(HANDLERS);
controls["#exercise-history-start"].value = "2024-02-01";
controls["#exercise-history-end"].value = "2024-02-29";
controls["#exercise-history-range-form"].handler({preventDefault: function () { prevented = true; }});
if (!prevented || fetches !== 1) throw new Error("Apply range did not prevent submit and refetch");
controls["#exercise-history-all"].handler();
if (controls["#exercise-history-start"].value || controls["#exercise-history-end"].value)
  throw new Error("All history did not clear both date bounds");
if (fetches !== 2) throw new Error("All history did not refetch");
""".replace("HANDLERS", json.dumps("\n".join(handlers)))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_exercise_views_are_grouped_and_add_edit_share_one_dialog() -> None:
    page = INDEX.read_text(encoding="utf-8")
    exercises = (STATIC / "exercises.js").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'class="nav-group"' in page
    assert all(label in page for label in (
        "Training", "Progress", "Health &amp; Longevity",
        "Programme Intelligence", "Administration",
    ))
    assert "activeGroup" in app and 'details:not([open])' in app
    assert 'data-details-exercise="${esc(row.id)}">Open</button>' in exercises
    assert 'data-edit-exercise=' not in exercises
    assert 'openExerciseEditor' not in exercises
    assert '$("#exercise-add").addEventListener("click", () => openExerciseDetails(null));' in exercises
    assert 'api(exerciseHistoryUrl(state.exerciseId, state, state.offset, firstPage))' in exercises
    assert 'api(exerciseE1rmUrl(id, start, end))' in exercises
    assert 'include_analytics' in exercises and 'Number(page.analytics.session_count)' in exercises
    assert 'Duplicate or missing session id detected across history pages' in exercises
    assert 'Load 50 older sessions' in exercises
    assert 'id="exercise-history-start"' in page and 'id="exercise-history-end"' in page
    assert 'id="exercise-history-all"' in page and 'id="exercise-history-more"' in page
    assert 'id="exercise-detail-records"' in page
    assert page.count('id="exercise-detail-e1rm"') == 1
    assert page.count('id="exercise-trend-e1rm"') == 1
    assert page.count('id="exercise-detail-dose"') == 1
    assert page.count('id="exercise-trends-title"') == 1
    assert 'const target = $("#exercise-trend-e1rm")' in exercises
    assert 'e1rm_applicable: $("#exercise-detail-e1rm").checked' in exercises
    config_form_end = page.index('</form>', page.index('<form id="exercise-details-form">'))
    analytics_start = page.index('<section class="exercise-trends"', config_form_end)
    assert config_form_end < analytics_start
    assert 'exerciseHistoryAnalyticsCharts' in exercises


def test_history_adherence_renders_targets_unmatched_work_and_unavailable_states() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")

    def metric(numerator: int, denominator: int, **extra) -> dict:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "ratio": round(numerator / denominator, 4) if denominator else None,
            **extra,
        }

    def evaluation(sets: int, attained: int, **extra) -> dict:
        return {
            "evaluated_sets": sets,
            "unavailable_sets": 0,
            "attainment": metric(attained, sets),
            **extra,
        }

    def set_row(set_id: int, index: int, **overrides) -> dict:
        row = {
            "set_id": set_id, "set_index": index, "exercise_id": "trap_bar_deadlift",
            "set_role": None, "matched": index <= 2, "extra": index > 2,
            "included_in_attainment": index <= 2,
            "reps_actual": 5, "reps_target_low": 3, "reps_target_high": 5,
            "reps_status": "within", "reps_unit": "reps",
            "load_actual_kg": 100.0, "load_actual_external_kg": 100.0,
            "load_target_kg": 100.0, "load_tolerance_kg": 2.5,
            "load_deviation_kg": 0.0, "load_deviation_pct": 0.0,
            "load_status": "at_target",
            "rir_actual": 2, "rir_target": 2, "rir_deviation": 0,
            "rir_status": "at_target", "limitations": [],
        }
        row.update(overrides)
        return row

    def view(**overrides) -> dict:
        value = {
            "view": "original", "status": "available", "reason": None,
            "prescribed_sets": 3, "performed_sets": 3, "matched_sets": 2,
            "missing_sets": 1, "extra_sets": 1, "unattributable_planned_sets": 0,
            "warm_up_sets_excluded": 1,
            "set_completion": metric(2, 3),
            "reps": evaluation(2, 1, within_target=1, below_target=1, above_target=0,
                               mean_actual_reps=4.5, common_target_low=3,
                               common_target_high=5, unit="reps"),
            "load": evaluation(2, 1, at_target=1, below_target=1, above_target=0,
                               mean_absolute_deviation_kg=2.5,
                               max_absolute_deviation_kg=5.0,
                               mean_relative_deviation_pct=-2.5,
                               common_target_kg=100.0, unit="kg"),
            "rir": evaluation(2, 1, at_target=1, above_target=1, below_target=0,
                              mean_deviation=1.0, tolerance=1,
                              sign="positive = actual RIR above target"),
            "exercises": [{
                "plan_item_index": 0, "position": 0,
                "exercise_id": "trap_bar_deadlift",
                "exercise_name": "Trap-Bar <script>",
                "planned_sets": 3, "attributable": True, "status": "under",
                "attribution": "matched", "prescribed_sets": 3, "performed_sets": 3,
                "matched_sets": 2, "missing_sets": 1, "extra_sets": 1,
                "unattributable_planned_sets": 0, "warm_up_sets_excluded": 1,
                "set_completion": metric(2, 3),
                "reps": evaluation(2, 1), "load": evaluation(2, 1),
                "rir": evaluation(2, 1),
                "sets": [
                    set_row(1, 1, set_role="top_set"),
                    set_row(2, 2, reps_actual=4, reps_status="below",
                            load_actual_kg=95.0, load_actual_external_kg=95.0,
                            load_deviation_kg=-5.0, load_deviation_pct=-5.0,
                            load_status="below", rir_actual=4, rir_deviation=2,
                            rir_status="above"),
                    set_row(3, 3, load_actual_external_kg=None,
                            load_target_kg=100.0, load_deviation_kg=None,
                            load_deviation_pct=None, load_status="unavailable",
                            rir_status="unavailable", rir_deviation=None,
                            limitations=["actual_load_includes_bodyweight"]),
                ],
                "limitations": ["actual_load_includes_bodyweight"],
            }, {
                "plan_item_index": 1, "position": 1,
                "exercise_id": "conventional_deadlift",
                "exercise_name": "Conventional Deadlift",
                "planned_sets": 2, "attributable": False, "status": "unavailable",
                "attribution": "unavailable", "prescribed_sets": 0, "performed_sets": 0,
                "matched_sets": 0, "missing_sets": 0, "extra_sets": 0,
                "unattributable_planned_sets": 2, "warm_up_sets_excluded": 0,
                "set_completion": metric(0, 0), "reps": evaluation(0, 0),
                "load": evaluation(0, 0), "rir": evaluation(0, 0),
                "sets": [], "limitations": ["swapped_exercise"],
            }],
            "quality": {
                "unmatched_sets": 1, "ambiguous_attribution": 0,
                "mismatched_attribution": 0, "stale_attribution": 0,
                "added_exercise_sets": 0, "removed_exercise_sets": 1,
                "unattributable_items": 1,
                "unavailable_metrics": ["actual_load_includes_bodyweight"],
                "unmatched": [{
                    "set_id": 9, "set_index": 4, "exercise_id": "trap_bar_deadlift",
                    "reps": 5, "load_kg": 100, "rir": 2,
                    "reason": "removed_from_final_plan",
                }],
            },
        }
        value.update(overrides)
        return value

    payload = {
        "version": 1, "status": "available", "reason": None,
        "original": view(),
        "final_plan": view(
            view="final_plan", prescribed_sets=2, matched_sets=2, missing_sets=0,
            extra_sets=1, set_completion=metric(2, 2),
        ),
        "changes": {
            "swapped": [], "added": [], "removed": [],
            "set_count_changed": [{
                "plan_item_index": 0, "exercise_id": "trap_bar_deadlift",
                "from_sets": 3, "to_sets": 2,
            }],
            "targets_changed": [],
        },
        "quality": {
            "plan_modified": True, "legacy_plan_without_order_index": False,
            "warm_up_sets_excluded": 1, "ambiguous_status_sets": 0,
            "sets_without_rir": 0,
            "unmatched_sets": {"original": 1, "final_plan": 0},
            "ambiguous_attribution": {"original": 0, "final_plan": 0},
            "unattributable_planned_sets": {"original": 0, "final_plan": 0},
            "unavailable_metrics": ["actual_load_includes_bodyweight"],
        },
        "definitions": {},
    }

    script = r"""
global.esc = function (value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
};
global.fmt = function (value, digits) {
  if (value == null || value === "") return "—";
  return Number(value).toFixed(digits == null ? 1 : digits).replace(/\.0+$/, "");
};
eval(SOURCE);
var payload = PAYLOAD;
var html = renderHistoryAdherence(payload);
function need(text) { if (html.indexOf(text) < 0) throw new Error("missing: " + text); }
need("Prescription adherence");
need("Original prescription");
need("Final modified prescription");
need("Set completion");
need("2 / 3 (66.7%)");
need("Target attainment");
need("Exercise breakdown");
need("within target");
need("below target");
need("above target");
need("at target");
need("extra");
need("Trap-Bar &lt;script&gt;");
if (html.indexOf("<script>") >= 0) throw new Error("exercise name was not escaped");
need("The actual load includes bodyweight, so the added plate is unknown.");
need("removed from the final plan");
need("Set count for trap_bar_deadlift: 3 → 2");
need("Warm-up sets excluded: 1");
need("swapped during the workout");
need("RIR deviation is actual minus target");
need("aria-label='Target attainment");
need("scope='col'");

var empty = JSON.parse(JSON.stringify(payload));
empty.original.exercises = [];
empty.original.quality.unmatched = [];
empty.quality.plan_modified = false;
html = renderHistoryAdherence(empty);
if (html.indexOf("No prescribed exercises.") < 0) throw new Error("empty exercises");
if (html.indexOf("No unmatched working sets.") < 0) throw new Error("empty unmatched");
if (html.indexOf("Final plan was not modified during the workout.") < 0)
  throw new Error("unmodified copy");

html = renderHistoryAdherence({version: 1, status: "unavailable",
  reason: "no_prescription_snapshot"});
if (html.indexOf("Prescription adherence is unavailable") < 0) throw new Error("unavailable");
if (html.indexOf("No frozen prescription snapshot exists") < 0)
  throw new Error("unavailable reason");
html = renderHistoryAdherence(null);
if (html.indexOf("Adherence data is unavailable for this session.") < 0)
  throw new Error("missing payload");
"""
    script = script.replace("SOURCE", json.dumps(
        (STATIC / "adherence.js").read_text(encoding="utf-8")
    )).replace("PAYLOAD", json.dumps(payload))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_progress_adherence_renders_denominators_charts_and_drilldown() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")

    def metric(numerator: int, denominator: int) -> dict:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "ratio": round(numerator / denominator, 4) if denominator else None,
        }

    def target(numerator: int, denominator: int) -> dict:
        return {"attainment": metric(numerator, denominator)}

    def period(key: str, start: str, end: str, workouts: int,
               matched: int, prescribed: int, small: bool, has_data: bool = True) -> dict:
        return {
            "key": key, "label": key, "start": start, "end": end,
            "workouts": workouts, "has_data": has_data, "small_sample": small,
            "set_completion": metric(matched, prescribed),
            "reps": target(matched, matched), "load": target(matched, matched),
            "rir": target(matched, matched),
        }

    def exercise(exercise_id: str, name: str, matched: int, prescribed: int,
                 small: bool = False) -> dict:
        return {
            "exercise_id": exercise_id, "exercise_name": name,
            "workouts": 3, "prescribed_sets": prescribed,
            "has_data": True, "small_sample": small,
            "set_completion": metric(matched, prescribed),
            "reps": target(matched, matched), "load": target(matched, matched),
            "rir": target(matched, matched),
        }

    original_periods = [
        period("2024-W01", "2024-01-01", "2024-01-07", 3, 16, 17, False),
        period("2024-W02", "2024-01-08", "2024-01-14", 0, 0, 0, True, False),
    ]
    final_periods = [
        period("2024-W01", "2024-01-01", "2024-01-07", 3, 17, 17, False),
        period("2024-W02", "2024-01-08", "2024-01-14", 0, 0, 0, True, False),
    ]
    original = {
        "workouts": 3, "prescribed_sets": 17, "matched_sets": 16,
        "missing_sets": 1, "extra_sets": 0, "small_sample": False,
        "set_completion": metric(16, 17),
        "reps": target(16, 16), "load": target(16, 16), "rir": target(16, 16),
        "periods": original_periods,
        "exercises": [
            exercise("trap_bar_deadlift", "Trap-Bar <script>", 16, 17),
            exercise("competition_bench_press", "Bench Press", 0, 0, True),
        ],
    }
    final = {
        "workouts": 3, "prescribed_sets": 17, "matched_sets": 17,
        "missing_sets": 0, "extra_sets": 0, "small_sample": False,
        "set_completion": metric(17, 17),
        "reps": target(17, 17), "load": target(17, 17), "rir": target(17, 17),
        "periods": final_periods,
        "exercises": [exercise("trap_bar_deadlift", "Trap-Bar <script>", 17, 17)],
    }
    workout_metric = {
        "workouts": 1, "prescribed_sets": 3, "matched_sets": 2,
        "missing_sets": 1, "extra_sets": 0, "small_sample": True,
        "set_completion": metric(2, 3),
        "reps": target(2, 2), "load": target(2, 2), "rir": target(2, 2),
    }
    payload = {
        "version": 1, "status": "available", "reason": None,
        "range": {"from": "2024-01-01", "to": "2024-01-31", "group_by": "week"},
        "filters": {"exercise_id": None, "session_type": None,
                    "exercises": [], "session_types": ["hinge"]},
        "definitions": {
            "aggregation": "summed numerators and denominators across workouts",
            "small_sample": "fewer than three workouts or five prescribed sets",
        },
        "coverage": {
            "workouts_in_range": 3, "workouts_analysed": 3,
            "workouts_unavailable": 0, "workouts_voided": 1,
            "workouts_without_session": 0, "invalid_plan_rows": 0,
            "workouts_filtered_out": 0,
            "excluded": [{"workout_id": "voided-id", "for_date": "2024-01-03",
                          "reason": "session_voided"}],
        },
        "original": original, "final_plan": final,
        "workouts": [{
            "workout_id": "w1", "for_date": "2024-01-02", "session_type": "hinge",
            "original": workout_metric, "final_plan": workout_metric,
        }],
    }

    script = r"""
global.esc = function (value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
};
global.fmt = function (value, digits) {
  if (value == null || value === "") return "—";
  return Number(value).toFixed(digits == null ? 1 : digits).replace(/\.0+$/, "");
};
global.today = function () { return "2024-01-31"; };
global.__panelClick = null;
global.$ = function (selector) {
  if (selector === "#progress-adherence")
    return {addEventListener: function (type, handler) {
      if (type === "click") global.__panelClick = handler;
    }};
  return null;
};
global.document = {addEventListener: function () {}};
global.chartNumber = function (value, digits) {
  return Number(value).toFixed(digits == null ? 1 : digits).replace(/\.0+$/, "");
};
global.sessionLabel = function (value) { return String(value || ""); };
global.api = function () { return Promise.resolve({}); };
global.__charts = [];
global.dateSeriesChart = function (spec) {
  global.__charts.push(spec);
  return "<div class='chart-stub'>" + spec.title + "</div>";
};
eval(ADHERENCE_SOURCE);
eval(PROGRESS_SOURCE);
const data = PAYLOAD;
let html = progressAdherenceRender(data);
function need(text) { if (html.indexOf(text) < 0) throw new Error("missing: " + text); }
need("Set completion");
need("Repetition attainment");
need("Load attainment");
need("RIR attainment");
need("16 / 17 (94.1%)");
need("17 / 17 (100%)");
need("Periods and denominators");
need("Exercise comparison");
need("Workout drill-down");
need("Definitions, coverage and exclusions");
need("small sample");
need("not prescribed");
need("Trap-Bar &lt;script&gt;");
need("data-progress-adherence-workout='w1'");
need("This session is voided");
if (html.indexOf("<script>") >= 0) throw new Error("exercise name was not escaped");

if (global.__charts.length !== 4) throw new Error("expected four trend charts");
if (global.__charts[0].series[0].points.length !== 1)
  throw new Error("small-sample period was not omitted from the chart");
if (global.__charts[0].series[0].points[0].value < 94 ||
    global.__charts[0].series[0].points[0].value > 95)
  throw new Error("set-completion point is not a summed ratio");
if (global.__charts[0].note.indexOf("omitted") < 0)
  throw new Error("chart note does not explain omitted periods");

global.setView = function (name) { global.__view = name; };
global.openHistoryDetails = function (id) { global.__opened = id; };
global.__panelClick({target: {closest: function (selector) {
  if (selector !== "[data-progress-adherence-workout]") return null;
  return {getAttribute: function () { return "w1"; }};
}}});
if (global.__view !== "history" || global.__opened !== "w1")
  throw new Error("drill-down did not open History");

var empty = {status: "available", range: {from: "2024-01-01", to: "2024-01-31", group_by: "week"},
  coverage: {workouts_analysed: 0, workouts_in_range: 0}, filters: {}, definitions: {},
  original: {periods: []}, final_plan: {periods: []}};
html = progressAdherenceRender(empty);
if (html.indexOf("No completed app-tracked workouts") < 0)
  throw new Error("empty state missing");
html = progressAdherenceRender({status: "unavailable", reason: "no_prescription_snapshot"});
if (html.indexOf("No frozen prescription snapshot exists") < 0)
  throw new Error("unavailable state missing");
"""
    script = script.replace("ADHERENCE_SOURCE", json.dumps(
        (STATIC / "adherence.js").read_text(encoding="utf-8")
    )).replace("PROGRESS_SOURCE", json.dumps(
        (STATIC / "progress.js").read_text(encoding="utf-8")
    )).replace("PAYLOAD", json.dumps(payload))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_vbt_helpers_render_targets_applicability_and_feedback() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "vbt.js").read_text(encoding="utf-8")
    script = r"""
global.esc = function (value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
};
global.fmt = function (value, digits) {
  if (value == null || value === "") return "—";
  return Number(value).toFixed(digits == null ? 1 : digits).replace(/\.0+$/, "");
};
eval(SOURCE);
var target = {
  target_mps: 0.42, low_mps: 0.39, high_mps: 0.45, rep_count: 3,
  rir_low: 2, rir_high: 3, scope: "lift", family: "squat", n_sets: 18,
  n_sessions: 3, method_version: "1.0.0", calibration_id: "vbt-test",
  source: "computed"
};
var item = {exercise_id: "ssb_squat", reps_low: 3, reps_high: 5, set_groups: [], vbt: target};
var details = vbtTargetDetails(item);
if (details.indexOf("0.42 m/s") < 0 || details.indexOf("0.39–0.45") < 0) throw new Error("target detail");
if (details.indexOf("RIR 2–3") < 0 || details.indexOf("squat") < 0) throw new Error("scope/rir");
if (details.indexOf("18 sets / 3 sessions") < 0 || details.indexOf("1.0.0") < 0) throw new Error("sample/method");
if (details.indexOf("vbt-test") < 0) throw new Error("calibration id");

var ok = vbtApplicability(item, "", 3, 2);
if (ok.status !== "applicable") throw new Error("applicable target");
var reps = vbtApplicability(item, "", 5, 2);
if (reps.reason !== "rep_mismatch") throw new Error("rep mismatch");
var effort = vbtApplicability(item, "", 3, 1);
if (effort.reason !== "actual_rir_outside_band") throw new Error("rir band");
var missingEffort = vbtApplicability(item, "", 3, "");
if (missingEffort.reason !== "actual_rir_missing") throw new Error("rir missing");
var noTarget = vbtApplicability({exercise_id: "ssb_squat", vbt: null}, "", 3, 2);
if (noTarget.reason !== "no_target") throw new Error("no target");
var legacy = vbtApplicability({exercise_id: "ssb_squat", vbt: null, velocity_target: 0.4}, "", 3, 2);
if (legacy.reason !== "legacy_target") throw new Error("legacy target");

var groups = [
  {role: "top_set", sets: 1, reps_low: 5, reps_high: 5, load_kg: 110, rir_target: 1},
  {role: "back_off", sets: 2, reps_low: 3, reps_high: 5, load_kg: 95, rir_target: 2}
];
var groupItem = {exercise_id: "ssb_squat", reps_low: 3, reps_high: 5, set_groups: groups, vbt: target};
var groupMismatch = vbtApplicability(groupItem, "top_set", 5, 1);
if (groupMismatch.reason !== "group_rep_mismatch") throw new Error("group reps");
var ambiguous = vbtApplicability(groupItem, "", 3, 2);
if (ambiguous.reason !== "ambiguous_set_role") throw new Error("ambiguous role");

var comparable = vbtFeedbackHtml({
  target_mps: 0.42, actual_velocity_mps: 0.44, delta_mps: 0.02,
  delta_pct: 4.76, within_calibration_band: true, comparable: true, reasons: []
});
if (comparable.indexOf("Target 0.42") < 0 || comparable.indexOf("actual 0.44") < 0) throw new Error("feedback values");
if (comparable.indexOf("+0.02") < 0 || comparable.indexOf("within calibration band") < 0) throw new Error("feedback delta");
var invalid = vbtFeedbackHtml({
  target_mps: 0.42, actual_velocity_mps: 0.44, delta_mps: 0.02,
  delta_pct: 4.76, within_calibration_band: true, comparable: false,
  reasons: ["rep_mismatch"]
});
if (invalid.indexOf("not comparable") < 0 || invalid.indexOf("rep count") < 0) throw new Error("invalid feedback");

var note = vbtPrescriptionNote({status: "available", targets: 2, withheld: ["trap_bar_deadlift"]});
if (note.indexOf("2 target") < 0 || note.indexOf("trap_bar_deadlift") < 0) throw new Error("available note");
var unavailable = vbtPrescriptionNote({status: "unavailable", reason: "no clean sets"});
if (unavailable.indexOf("no clean sets") < 0) throw new Error("unavailable note");
"""
    script = script.replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_vbt_section_renders_completed_comparison_and_quality() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "vbt.js").read_text(encoding="utf-8")
    script = r"""
global.esc = function (value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
};
global.fmt = function (value, digits) {
  if (value == null || value === "") return "—";
  return Number(value).toFixed(digits == null ? 1 : digits).replace(/\.0+$/, "");
};
eval(SOURCE);
var target = {
  target_mps: 0.42, low_mps: 0.39, high_mps: 0.45, rep_count: 3,
  rir_low: 2, rir_high: 3, scope: "lift", family: "squat", n_sets: 18,
  n_sessions: 3, method_version: "1.0.0", calibration_id: "vbt-test",
  source: "computed", metadata: "complete"
};
var vbt = {
  status: "available", reason: null,
  sets: [
    {set_id: 1, set_index: 1, exercise_id: "ssb_squat", exercise_name: "SSB squat",
     reps: 3, load_kg: 100, load_basis: "external", actual_rir: 2,
     target_rir_low: 2, target_rir_high: 3, target_mps: 0.42,
     actual_velocity_mps: 0.44, delta_mps: 0.02, delta_pct: 4.76,
     within_calibration_band: true, comparable: true, reasons: [],
     target_source: "final_plan", extra_set: false, target: target},
    {set_id: 2, set_index: 2, exercise_id: "ssb_squat", exercise_name: "SSB squat",
     reps: 5, load_kg: 100, load_basis: "external", actual_rir: 2,
     target_rir_low: 2, target_rir_high: 3, target_mps: 0.42,
     actual_velocity_mps: 0.44, delta_mps: 0.02, delta_pct: 4.76,
     within_calibration_band: true, comparable: false,
     reasons: ["rep_mismatch"], target_source: "final_plan",
     extra_set: false, target: target}
  ],
  exercises: [{
    exercise_id: "ssb_squat", exercise_name: "SSB squat", sets: 2,
    comparable_sets: 1, excluded_sets: 1, extra_sets: 0,
    median_signed_delta_mps: 0.02, mean_absolute_error_mps: 0.02,
    mean_actual_rir: 2, mean_prescribed_rir: 2,
    targets: [target], target_sources: ["final_plan"]
  }],
  quality: {
    logged_sets: 2, working_sets: 2, sets_with_velocity: 2,
    comparable_sets: 1, excluded_sets: 1, target_sets: 2, extra_sets: 0,
    reasons: {rep_mismatch: 1}
  }
};
var html = vbtSectionHtml(vbt);
if (html.indexOf("SSB squat") < 0 || html.indexOf("Target 0.42 m/s") < 0) throw new Error("exercise/target");
if (html.indexOf("0.44") < 0 || html.indexOf("+0.02") < 0 || html.indexOf("within band") < 0) throw new Error("per set");
if (html.indexOf("not comparable") < 0 && html.indexOf("rep count") < 0) throw new Error("reason");
if (html.indexOf("VBT data quality") < 0 || html.indexOf("Comparable target sets") < 0) throw new Error("quality");
if (html.indexOf("rep count") < 0) throw new Error("excluded reason");
var unavailable = vbtSectionHtml({status: "unavailable", reason: "no_vbt_target_issued", quality: {logged_sets: 2}});
if (unavailable.indexOf("No trustworthy") < 0 || unavailable.indexOf("2 set") < 0) throw new Error("unavailable");
"""
    script = script.replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr


def test_vbt_performance_helpers_render_cohorts_drilldown_and_drift() -> None:
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("node is not installed")
    source = (STATIC / "performance.js").read_text(encoding="utf-8")
    script = r"""
global.esc = function (value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
};
global.fmt = function (value, digits) {
  if (value == null || value === "") return "—";
  return Number(value).toFixed(digits == null ? 1 : digits).replace(/\.0+$/, "");
};
global.vbtSigned = function (value, digits) {
  if (value == null) return "—";
  return (Number(value) > 0 ? "+" : "") + fmt(value, digits == null ? 2 : digits);
};
global.vbtBandText = function (row) {
  if (row.within_calibration_band === true) return "within band";
  if (row.within_calibration_band === false) return "outside band";
  return "band unavailable";
};
global.vbtSetNotes = function (row) {
  return (row.reasons || []).join(" · ") || (row.target_source === "original_plan" ? "original-plan target" : "");
};
global.vbtTargetInline = function (target) {
  return fmt(target.target_mps, 2) + " m/s @ " + target.rep_count + " reps";
};
global.dateSeriesChart = function () { return "<svg></svg>"; };
global.chartFrame = function (title, svg) { return "<div>" + title + svg + "</div>"; };
eval(SOURCE);
if (vbtPerformanceRatio({numerator: 2, denominator: 3, ratio: 0.6667}) !== "2 / 3 (67%)") {
  throw new Error("ratio");
}
var set = {workout_date: "2024-04-01", set_index: 1, set_id: 9, reps: 3,
  load_kg: 100, load_basis: "external", actual_rir: 2, target_rir_low: 2,
  target_rir_high: 3, target_mps: 0.42, low_mps: 0.39, high_mps: 0.45,
  actual_velocity_mps: 0.44, delta_mps: 0.02, delta_pct: 4.76,
  within_calibration_band: true, comparable: true, reasons: [],
  target_source: "final_plan"};
var setHtml = vbtPerformanceSetTable([set]);
if (setHtml.indexOf("2024-04-01") < 0 || setHtml.indexOf("0.42") < 0) throw new Error("set values");
if (setHtml.indexOf("comparable") < 0 || setHtml.indexOf("within band") < 0) throw new Error("set status");

var drift = {
  gates: {min_sets: 5, min_weeks: 3},
  exercises: [{
    exercise_id: "competition_squat", exercise_name: "Competition squat",
    n_sets: 5, n_reps: 15, weeks: 3, consecutive_weeks: 3,
    median_loss_pct: 8.2, change_pct_points: 1.4, gate: "descriptive",
    reason: "descriptive; at least 5 sets over 3 weeks",
    sets: [{date: "2024-04-01", set_id: 9, rep_count: 3, first_mps: 0.50,
      last_mps: 0.46, loss_mps: 0.04, loss_pct: 8.0}]
  }]
};
var driftHtml = vbtPerformanceDrift(drift);
if (driftHtml.indexOf("Competition squat") < 0 || driftHtml.indexOf("8.2") < 0) throw new Error("drift");
if (driftHtml.indexOf("No trend is fitted") < 0 || driftHtml.indexOf("5") < 0) throw new Error("drift caveat");

var cohortHtml = vbtPerformanceCohortDetails({
  exercise_id: "competition_squat", exercise_name: "Competition squat",
  scope: "lift", family: "squat", target_rep_count: 3, target_rir_low: 2,
  target_rir_high: 3, n: 1, calibration_ids: ["vbt-test"],
  target_sources: ["final_plan"], target: {target_mps: 0.42, rep_count: 3}
}, [set]);
if (cohortHtml.indexOf("vbt-test") < 0 || cohortHtml.indexOf("Target 0.42") < 0) {
  throw new Error("cohort details");
}
"""
    script = script.replace("SOURCE", json.dumps(source))
    result = _run_node(script)
    assert result.returncode == 0, result.stderr
