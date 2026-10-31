/* Performance view: raw e1RM observations, rolling median and configured ratios.
 * Descriptive only; no decay, calibration, target ratio or diagnosis. */
var performanceExercisesLoaded = false;
var monitoringAnalysisData = null;
var performanceRelationshipOptions = null;
var performanceRelationshipConfig = null;
var performanceDoseShowAll = false;
var monitoringAnalysisShowAll = false;
var monitoringAnalysisShowAllDose = false;

function performanceDate(daysAgo) {
  var date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return formatLocalDate(date);
}

function performanceSvg(points) {
  if (!points || points.length < 2) return "";
  var values = points.map(function (point) { return Number(point.kg); });
  var min = Math.min.apply(null, values);
  var max = Math.max.apply(null, values);
  var span = Math.max(1, max - min);
  var width = 640;
  var height = 220;
  var coords = points.map(function (point, index) {
    var x = points.length === 1 ? 0 : (index / (points.length - 1)) * (width - 40) + 20;
    var y = height - 20 - ((Number(point.kg) - min) / span) * (height - 40);
    return [x, y];
  });
  var line = coords.map(function (pair) { return pair[0].toFixed(1) + "," + pair[1].toFixed(1); }).join(" ");
  var circles = coords.map(function (pair) {
    return "<circle cx='" + pair[0].toFixed(1) + "' cy='" + pair[1].toFixed(1) + "' r='3'></circle>";
  }).join("");
  return "<svg class='performance-chart' viewBox='0 0 " + width + " " + height +
    "' role='img' aria-label='Raw e1RM observations'><title>Raw e1RM observations</title>" +
    "<polyline points='" + line + "' fill='none' stroke='currentColor' stroke-width='2'></polyline>" +
    circles + "</svg>";
}

function renderPerformanceE1rm(data) {
  var target = document.getElementById("performance-e1rm");
  if (!target) return;
  var summary = data.summary || {};
  var points = data.points || [];
  var rows = points.map(function (point) {
    return "<tr><td>" + esc(point.date) + "</td><td>" + fmt(point.kg) +
      "</td><td>" + fmt(point.rolling_median_kg) + "</td><td>" + point.n_window + "</td></tr>";
  }).join("");
  target.innerHTML =
    "<div class='panel'><h3>" + esc(data.exercise_id) + "</h3>" +
    "<p>Latest: " + (summary.latest ? fmt(summary.latest.kg) + " kg on " + esc(summary.latest.date) : "Unavailable") +
    " · Recent median: " + (summary.recent_median_kg == null ? "Unavailable" : fmt(summary.recent_median_kg) + " kg") +
    " · Observations: " + (summary.n == null ? "Unavailable" : summary.n) + "</p>" +
    "<p class='muted'>" + esc(summary.status || "unavailable") +
    " · Basis: raw_formula_epley_rir; decay and calibration not applied.</p>" +
    performanceSvg(points) +
    (rows ? "<div class='table-scroll'><table><thead><tr><th>Date</th><th>e1RM kg</th><th>Rolling median</th><th>Window n</th></tr></thead><tbody>" + rows + "</tbody></table></div>" : "<p class='empty'>No eligible observations in this range.</p>") +
    ((data.breaks || []).length ? "<p class='muted'>Series breaks: " + data.breaks.map(function (item) { return esc(item.date + " — " + item.reason); }).join("; ") + "</p>" : "") +
    ((data.break_detection && data.break_detection.equipment === false)
      ? "<p class='muted'>Equipment changes are not stored and cannot be detected.</p>" : "") +
    ((data.degraded || []).length
      ? "<details><summary>Degraded observations (not in line or median)</summary><div class='table-scroll'><table><thead><tr><th>Date</th><th>e1RM kg</th><th>Quality</th></tr></thead><tbody>" +
        data.degraded.map(function (point) { return "<tr><td>" + esc(point.date) + "</td><td>" + fmt(point.kg) + "</td><td>" + esc(point.quality) + "</td></tr>"; }).join("") +
        "</tbody></table></div></details>" : "") +
    "</div>";
}

function renderPerformanceDose(data) {
  var target = document.getElementById("performance-dose");
  if (!target) return;
  var allRows = data.buckets || [];
  var shown = performanceDoseShowAll ? allRows : allRows.slice(-8);
  var rows = shown.map(function (row) {
    return "<tr><td>" + esc(row.date) + "</td><td>" + esc(row.session_type) +
      "</td><td>" + row.working_sets + "</td><td>" + row.hard_sets +
      "</td><td>" + fmt(row.tonnage_kg) + " kg</td></tr>";
  }).join("");
  target.innerHTML = "<div class='panel'><h3>Dose by session</h3>" +
    (rows ? "<div class='table-scroll'><table><thead><tr><th>Date</th><th>Type</th><th>Working sets</th><th>Hard sets</th><th>Tonnage</th></tr></thead><tbody>" + rows + "</tbody></table></div>" : "<p class='empty'>No sessions in this range.</p>") +
    (allRows.length > 8 ? "<button type='button' class='ghost' id='performance-dose-toggle'>" +
      (performanceDoseShowAll ? "Show latest dose only" : "Show full dose list (" + allRows.length + ")") + "</button>" : "") +
    "</div>";
  var toggle = document.getElementById("performance-dose-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      performanceDoseShowAll = !performanceDoseShowAll;
      renderPerformanceDose(data);
    });
  }
}

async function loadRelationshipOptions() {
  if (performanceRelationshipOptions) return performanceRelationshipOptions;
  performanceRelationshipOptions = await api("/api/performance/relationship-options");
  return performanceRelationshipOptions;
}

function fillRelationshipOptions(options) {
  var numerator = document.getElementById("relationship-numerator");
  var denominator = document.getElementById("relationship-denominator");
  var type = document.getElementById("relationship-type");
  if (!numerator || !denominator || !type) return;
  var choices = (options.exercises || []).map(function (item) {
    return "<option value='" + esc(item.id) + "'>" + esc(item.label) + "</option>";
  }).join("");
  numerator.innerHTML = choices;
  denominator.innerHTML = choices;
  type.innerHTML = (options.relationship_types || []).map(function (item) {
    return "<option value='" + esc(item) + "'>" + esc(item) + "</option>";
  }).join("");
}

async function addRelationship(event) {
  event.preventDefault();
  var status = document.getElementById("relationship-add-status");
  if (!performanceRelationshipConfig || !performanceRelationshipConfig.revision) {
    if (status) status.textContent = "Relationship configuration is still loading; wait for the revision before adding.";
    return;
  }
  var body = {
    numerator: document.getElementById("relationship-numerator").value,
    denominator: document.getElementById("relationship-denominator").value,
    relationship_type: document.getElementById("relationship-type").value,
    max_gap_days: Number(document.getElementById("relationship-gap").value),
    max_age_days: Number(document.getElementById("relationship-age").value),
    min_observations: Number(document.getElementById("relationship-min").value),
    revision: performanceRelationshipConfig.revision,
  };
  if (status) status.textContent = "Saving…";
  try {
    await api("/api/performance/relationships", {
      method: "POST", body: JSON.stringify(body),
    });
    performanceRelationshipConfig = null;
    if (status) status.textContent = "Pair added.";
    await loadPerformanceData();
  } catch (error) {
    if (error.status === 409) {
      showRelationshipConflict("relationship-add-status");
    } else if (status) {
      status.textContent = error.message;
    }
  }
}

function showRelationshipConflict(targetId) {
  var target = document.getElementById(targetId);
  if (!target) return;
  target.innerHTML = "<span class='warnbox'>Configuration changed elsewhere. Reload the latest pairs, review the changes, then retry.</span> " +
    "<button type='button' class='ghost' id='relationship-reload-" + targetId + "'>Reload configuration</button>";
  var button = document.getElementById("relationship-reload-" + targetId);
  if (!button) return;
  button.addEventListener("click", async function () {
    button.disabled = true;
    button.textContent = "Reloading…";
    await loadRelationshipConfig(true);
    var status = document.getElementById("relationship-add-status");
    if (status) status.textContent = "Configuration reloaded. Review the pairs and retry.";
  });
}

var RELATIONSHIP_TYPE_OPTIONS = [
  "variant_to_main", "accessory_to_main", "equipment_variant", "range_variant",
];

function relationshipSourceBadge(item) {
  var label = item.source_kind === "local_override" ? "Local override" : "Canonical";
  return "<span class='badge'>" + esc(label) + "</span>";
}

function relationshipEditForm(item) {
  var options = RELATIONSHIP_TYPE_OPTIONS.map(function (kind) {
    var selected = kind === item.relationship_type ? " selected" : "";
    return "<option value='" + esc(kind) + "'" + selected + ">" + esc(kind) + "</option>";
  }).join("");
  return "<form id='relationship-edit-form' class='relationship-edit-form'>" +
    "<label>Label<input id='relationship-edit-label' value='" + esc(item.label) + "'></label>" +
    "<label>Type<select id='relationship-edit-type'>" + options + "</select></label>" +
    "<div class='form-row'>" +
    "<label>Gap days<input type='number' id='relationship-edit-gap' min='1' value='" + item.max_gap_days + "'></label>" +
    "<label>Max age<input type='number' id='relationship-edit-age' min='1' value='" + item.max_age_days + "'></label>" +
    "<label>Min obs<input type='number' id='relationship-edit-min' min='2' value='" + item.min_observations + "'></label>" +
    "</div>" +
    "<label>Notes<input id='relationship-edit-notes' value='" + esc(item.notes) + "'></label>" +
    "<div class='form-row'><button type='submit' class='primary'>Save pair</button>" +
    "<button type='button' class='ghost' id='relationship-edit-cancel'>Cancel</button>" +
    "<span class='muted' id='relationship-edit-status'></span></div></form>";
}

function openRelationshipEdit(item) {
  var host = document.getElementById("performance-relationship-edit");
  if (!host) return;
  host.innerHTML = relationshipEditForm(item);
  var form = document.getElementById("relationship-edit-form");
  var cancel = document.getElementById("relationship-edit-cancel");
  if (cancel) cancel.addEventListener("click", function () {
    if (performanceRelationshipConfig) renderRelationshipManagement();
  });
  if (form) form.addEventListener("submit", async function (event) {
    event.preventDefault();
    var status = document.getElementById("relationship-edit-status");
    if (status) status.textContent = "Saving…";
    try {
      await api("/api/performance/relationships/" + encodeURIComponent(item.id) + "/update", {
        method: "POST",
        body: JSON.stringify({
          numerator: item.numerator,
          denominator: item.denominator,
          label: document.getElementById("relationship-edit-label").value,
          relationship_type: document.getElementById("relationship-edit-type").value,
          max_gap_days: Number(document.getElementById("relationship-edit-gap").value),
          max_age_days: Number(document.getElementById("relationship-edit-age").value),
          min_observations: Number(document.getElementById("relationship-edit-min").value),
          notes: document.getElementById("relationship-edit-notes").value,
          revision: performanceRelationshipConfig.revision,
        }),
      });
      performanceRelationshipConfig = null;
      await loadPerformanceData();
    } catch (error) {
      if (error.status === 409) {
        showRelationshipConflict("relationship-edit-status");
      } else if (status) {
        status.textContent = error.message;
      }
    }
  });
}

async function relationshipAction(item, action, button) {
  if (action === "delete" && button.dataset.confirm !== "1") {
    button.dataset.confirm = "1";
    button.textContent = "Confirm delete";
    return;
  }
  var endpointAction = action === "restore" ? "reset" : action;
  try {
    var payload = await api(
      "/api/performance/relationships/" + encodeURIComponent(item.id) + "/" + endpointAction,
      {
        method: "POST",
        body: JSON.stringify({ revision: performanceRelationshipConfig.revision }),
      },
    );
    performanceRelationshipConfig = payload;
    await loadPerformanceData();
  } catch (error) {
    if (error.status === 409) {
      showRelationshipConflict("performance-relationship-status");
    } else {
      var status = document.getElementById("performance-relationship-status");
      if (status) status.textContent = error.message;
    }
  }
}

function renderRelationshipManagement() {
  var host = document.getElementById("performance-relationship-management");
  if (!host) return;
  var config = performanceRelationshipConfig;
  if (!config) return;
  var items = config.relationships || [];
  var hidden = config.hidden || [];
  var rows = items.map(function (item) {
    var actions = "<button type='button' class='ghost' data-relationship-action='edit' data-relationship-id='" +
      esc(item.id) + "'>Edit</button>";
    if (item.origin === "canonical" && item.source_kind === "local_override") {
      actions += "<button type='button' class='ghost' data-relationship-action='reset' data-relationship-id='" +
        esc(item.id) + "'>Reset</button>";
    }
    actions += "<button type='button' class='ghost' data-relationship-action='delete' data-relationship-id='" +
      esc(item.id) + "'>Delete</button>";
    return "<div class='relationship-admin-row'><div><strong>" + esc(item.label) +
      "</strong><div class='monitoring-key'>" + esc(item.id) + "</div>" +
      relationshipSourceBadge(item) + "</div><div class='relationship-actions'>" +
      actions + "</div></div>";
  }).join("");
  var hiddenHtml = hidden.length
    ? "<details><summary>Locally hidden pairs (" + hidden.length + ")</summary>" +
      hidden.map(function (item) {
        return "<div class='relationship-admin-row'><div><strong>" + esc(item.label) +
          "</strong><div class='monitoring-key'>" + esc(item.id) + "</div></div>" +
          "<div class='relationship-actions'><button type='button' class='ghost' " +
          "data-relationship-action='restore' data-relationship-id='" + esc(item.id) +
          "'>Restore</button></div></div>";
      }).join("") + "</details>"
    : "";
  host.innerHTML = "<h3>Manage configured pairs</h3>" +
    "<p class='muted'>Changes are local overrides; the reviewed canonical YAML is never edited. Revision " +
    esc(String(config.revision || "").slice(0, 12)) + ".</p>" +
    "<div id='performance-relationship-list'>" + (rows || "<p class='empty'>No configured pairs.</p>") + "</div>" +
    "<div id='performance-relationship-edit'></div>" + hiddenHtml +
    "<p class='muted' id='performance-relationship-status'></p>";
  host.querySelectorAll("[data-relationship-action]").forEach(function (button) {
    button.addEventListener("click", function () {
      var id = button.dataset.relationshipId;
      var item = items.find(function (value) { return value.id === id; }) ||
        hidden.find(function (value) { return value.id === id; });
      if (!item) return;
      if (button.dataset.relationshipAction === "edit") {
        openRelationshipEdit(item);
      } else {
        relationshipAction(item, button.dataset.relationshipAction, button);
      }
    });
  });
}

async function loadRelationshipConfig(force) {
  var host = document.getElementById("performance-relationship-management");
  if (!host) return;
  if (!force && performanceRelationshipConfig) {
    renderRelationshipManagement();
    var cachedAddButton = document.getElementById("relationship-add-submit");
    if (cachedAddButton) {
      cachedAddButton.disabled = false;
      cachedAddButton.title = "";
    }
    return;
  }
  host.innerHTML = "<p class='empty'>Loading pair configuration…</p>";
  try {
    performanceRelationshipConfig = await api("/api/performance/relationships");
    renderRelationshipManagement();
    var addButton = document.getElementById("relationship-add-submit");
    if (addButton) {
      addButton.disabled = false;
      addButton.title = "";
    }
  } catch (error) {
    host.innerHTML = "<p class='warnbox'>Pair configuration failed: " + esc(error.message) + "</p>";
    var addButton = document.getElementById("relationship-add-submit");
    if (addButton) {
      addButton.disabled = true;
      addButton.title = "Relationship configuration and revision must load first.";
    }
  }
}

function renderPerformanceRatios(data) {
  var target = document.getElementById("performance-ratios");
  if (!target) return;
  var filter = document.getElementById("performance-ratio-filter");
  var selected = filter ? filter.value : "";
  var relationships = data.relationships || [];
  var rows = [];
  relationships.forEach(function (item) {
    var row = item.current || {};
    if (selected && row.relationship_id !== selected) return;
    rows.push("<tr><td>" + esc(row.label || row.relationship_id) + "</td><td>" +
      (row.ratio_pct == null ? "Unavailable" : fmt(row.ratio_pct) + "%") + "</td><td>" +
      esc(row.numerator_date || "Unavailable") + "</td><td>" +
      esc(row.denominator_date || "Unavailable") + "</td><td>" +
      (row.gap_days == null ? "Unavailable" : row.gap_days) + "</td><td>" +
      (row.numerator_observations == null ? "?" : row.numerator_observations) + "/" +
      (row.denominator_observations == null ? "?" : row.denominator_observations) +
      "</td><td>" + esc(row.status || "unavailable") + "</td><td>" +
      esc(row.reason || "") + "</td></tr>");
  });
  var options = "<option value=''>All configured pairs</option>" + relationships.map(function (item) {
    var row = item.current || {};
    var chosen = selected === row.relationship_id ? " selected" : "";
    return "<option value='" + esc(row.relationship_id) + "'" + chosen + ">" +
      esc(row.label || row.relationship_id) + "</option>";
  }).join("");
  target.innerHTML = "<div class='panel'><h3>Configured relative strength</h3>" +
    "<div class='form-row'><label>Pair<select id='performance-ratio-filter'>" + options + "</select></label></div>" +
    "<details><summary>Add a configured pair</summary>" +
    "<form id='relationship-add-form' class='form-row'>" +
    "<label>Numerator<select id='relationship-numerator'></select></label>" +
    "<label>Denominator<select id='relationship-denominator'></select></label>" +
    "<label>Type<select id='relationship-type'></select></label>" +
    "<label>Gap days<input type='number' id='relationship-gap' value='14' min='1'></label>" +
    "<label>Max age<input type='number' id='relationship-age' value='42' min='1'></label>" +
    "<label>Min obs<input type='number' id='relationship-min' value='2' min='2'></label>" +
    "<button type='submit' class='primary' id='relationship-add-submit' disabled>Add pair</button></form>" +
    "<p id='relationship-add-status' class='muted'></p>" +
    "<p class='muted'>Only pairs that meet the configured criteria can be added: distinct known exercises that support an e1RM, a unique pair, positive gap, age at least the gap, at least two observations, and descriptive-only notes.</p>" +
    "</details>" +
    (rows.length ? "<div class='table-scroll'><table><thead><tr><th>Pair</th><th>Ratio</th><th>Numerator date</th><th>Denominator date</th><th>Gap days</th><th>Recent obs (num/den)</th><th>Status</th><th>Reason</th></tr></thead><tbody>" + rows.join("") + "</tbody></table></div>" : "<p class='empty'>No configured relationships.</p>") +
    "<p class='muted'>Only the explicitly configured pairs are shown; this is not an exhaustive lift catalogue. Descriptive ratio of two raw estimates; no target, diagnosis or confidence claim.</p>" +
    "<p class='section-help'><a class='doc-link' href='#docs?doc=docs/MONITORING-ANALYSIS.md&anchor=configuring-relative-strength-pairs'>Pair criteria and documentation</a></p>" +
    "<div id='performance-relationship-management'><p class='empty'>Loading pair configuration…</p></div></div>";
  var nextFilter = document.getElementById("performance-ratio-filter");
  if (nextFilter && !nextFilter.dataset.wired) {
    nextFilter.dataset.wired = "1";
    nextFilter.addEventListener("change", function () {
      renderPerformanceRatios(data);
    });
  }
  var addForm = document.getElementById("relationship-add-form");
  if (addForm && !addForm.dataset.wired) {
    addForm.dataset.wired = "1";
    addForm.addEventListener("submit", addRelationship);
    loadRelationshipOptions().then(fillRelationshipOptions).catch(function (error) {
      var status = document.getElementById("relationship-add-status");
      if (status) status.textContent = error.message;
    });
  }
  loadRelationshipConfig(false);
}

async function loadPerformanceData() {
  var exercise = document.getElementById("performance-exercise");
  var from = document.getElementById("performance-from");
  var to = document.getElementById("performance-to");
  if (!exercise || !exercise.value) return;
  var e1rmTarget = document.getElementById("performance-e1rm");
  if (e1rmTarget) e1rmTarget.innerHTML = "<p class='empty'>Loading performance…</p>";
  performanceDoseShowAll = false;
  var sessionType = document.getElementById("performance-session-type");
  var includeDeloads = document.getElementById("performance-include-deloads");
  var quality = document.getElementById("performance-quality");
  var query = "?exercise_id=" + encodeURIComponent(exercise.value) +
    "&from=" + encodeURIComponent(from.value || "") +
    "&to=" + encodeURIComponent(to.value || today()) +
    "&session_type=" + encodeURIComponent(sessionType ? sessionType.value : "") +
    "&include_deloads=" + (includeDeloads && includeDeloads.checked ? "true" : "false") +
    "&quality=" + encodeURIComponent(quality ? quality.value : "ok");
  try {
    var results = await Promise.all([
      api("/api/performance/e1rm" + query),
      api("/api/performance/dose?from=" + encodeURIComponent(from.value || "") +
        "&to=" + encodeURIComponent(to.value || today()) + "&group_by=session"),
      api("/api/performance/ratios?from=" + encodeURIComponent(from.value || "") +
        "&to=" + encodeURIComponent(to.value || today())),
    ]);
    renderPerformanceE1rm(results[0]);
    renderPerformanceDose(results[1]);
    renderPerformanceRatios(results[2]);
  } catch (error) {
    if (e1rmTarget) e1rmTarget.innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  }
}

async function loadPerformance() {
  var select = document.getElementById("performance-exercise");
  if (!select) return;
  if (!select.value) {
    document.getElementById("performance-from").value = performanceDate(180);
    document.getElementById("performance-to").value = today();
  }
  if (!performanceExercisesLoaded) {
    try {
      var exercises = await api("/api/exercises");
      select.innerHTML = exercises.map(function (row) {
        return "<option value='" + esc(row.id) + "'>" + esc(row.display || row.id) + "</option>";
      }).join("");
      performanceExercisesLoaded = true;
    } catch (error) {
      select.innerHTML = "";
    }
  }
  var analysisDate = document.getElementById("monitoring-analysis-date");
  if (analysisDate && !analysisDate.value) analysisDate.value = today();
  var analysisButton = document.getElementById("monitoring-analysis-run");
  if (analysisButton && !analysisButton.dataset.wired) {
    analysisButton.dataset.wired = "1";
    analysisButton.addEventListener("click", loadMonitoringAnalysis);
  }
  var form = document.getElementById("performance-form");
  if (form && !form.dataset.wired) {
    form.dataset.wired = "1";
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      loadPerformanceData();
    });
  }
  loadPerformanceData();
}

function monitoringAnalysisAssociation(row) {
  if (!row) return "Unavailable";
  if (row.r == null) return esc(row.status + " (n=" + row.n + ")");
  return "r = " + fmt(row.r, 2) + " (n=" + row.n + "; " + esc(row.status) + ")";
}


function analysisLineChart(rows) {
  if (!Array.isArray(rows) || rows.length < 2) return "<p class='empty'>Insufficient session dose observations for a chart.</p>";
  var width = 640, height = 220, max = 1;
  rows.forEach(function (row) {
    max = Math.max(max, Number(row.hard_sets || 0), Number(row.working_sets || 0));
  });
  function coords(key) {
    return rows.map(function (row, index) {
      var x = (index / (rows.length - 1)) * (width - 40) + 20;
      var y = height - 20 - (Number(row[key] || 0) / max) * (height - 40);
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
  }
  return "<svg class='performance-chart' style='width:100%;height:auto' viewBox='0 0 " + width + " " + height +
    "' role='img' aria-label='Session dose over time'><title>Session dose over time: hard sets and working sets</title>" +
    "<polyline points='" + coords("working_sets") + "' fill='none' stroke='currentColor' stroke-width='2'></polyline>" +
    "<polyline points='" + coords("hard_sets") + "' fill='none' stroke='currentColor' stroke-width='2' stroke-dasharray='5 3'></polyline></svg>" +
    "<p class='muted'>Solid: working sets. Dashed: hard sets. Missing values are not plotted as zero.</p>";
}

function analysisScatter(points, association, label) {
  if (!Array.isArray(points) || points.length < 3) {
    return "<p class='empty'>Insufficient observations for " + esc(label) + " chart.</p>";
  }
  var width = 640, height = 220;
  var xs = points.map(function (point) { return Number(point.x); });
  var ys = points.map(function (point) { return Number(point.y); });
  var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
  var yMin = Math.min.apply(null, ys), yMax = Math.max.apply(null, ys);
  var xSpan = Math.max(1, xMax - xMin), ySpan = Math.max(1, yMax - yMin);
  var circles = points.map(function (point) {
    var x = 20 + ((Number(point.x) - xMin) / xSpan) * (width - 40);
    var y = height - 20 - ((Number(point.y) - yMin) / ySpan) * (height - 40);
    return "<circle cx='" + x.toFixed(1) + "' cy='" + y.toFixed(1) + "' r='4'></circle>";
  }).join("");
  return "<svg class='performance-chart' style='width:100%;height:auto' viewBox='0 0 " + width + " " + height +
    "' role='img' aria-label='" + esc(label) + "'><title>" + esc(label) + "</title>" + circles + "</svg>" +
    "<p class='muted'>" + esc(monitoringAnalysisAssociation(association)) +
    ". The displayed correlation is calculated by the analysis service, never by this page.</p>";
}

function renderMonitoringAnalysis(data) {
  var target = document.getElementById("monitoring-analysis-result");
  if (!target) return;
  var meta = data.meta || {};
  var coverage = data.missingness || {};
  var allDoseRows = data.dose || [];
  var doseRows = monitoringAnalysisShowAllDose ? allDoseRows : allDoseRows.slice(-8);
  var rows = doseRows.map(function (row) {
    return "<tr><td>" + esc(row.date) + "</td><td>" + esc(row.session_type) +
      "</td><td>" + row.working_sets + "</td><td>" + row.hard_sets +
      "</td><td>" + (row.tonnage_kg == null ? "Unavailable" :
        fmt(row.tonnage_kg) + " kg (" + esc(row.tonnage_status || "observed") + ")") +
      "</td><td>" + (row.session_load_au == null ? "Unavailable" : fmt(row.session_load_au) + " AU") +
      "</td></tr>";
  }).join("");
  var calibration = data.calibration || {};
  var associationSelect = document.getElementById("monitoring-analysis-association");
  var selectedAssociationId = associationSelect ? associationSelect.value : "";
  var associationRows = data.associations || [];
  if (!selectedAssociationId && associationRows.length) {
    selectedAssociationId = associationRows[0].exercise_id;
  }
  if (associationSelect) {
    associationSelect.innerHTML = associationRows.map(function (row) {
      var chosen = row.exercise_id === selectedAssociationId ? " selected" : "";
      return "<option value='" + esc(row.exercise_id) + "'" + chosen + ">" +
        esc(row.exercise_id) + "</option>";
    }).join("");
  }
  var selectedAssociation = associationRows.find(function (row) {
    return row.exercise_id === selectedAssociationId;
  }) || associationRows[0];
  var associationTableRows = monitoringAnalysisShowAll ? associationRows : (
    selectedAssociation ? [selectedAssociation] : []
  );
  var associations = associationTableRows.map(function (row) {
    return "<tr><td>" + esc(row.exercise_id) + "</td><td>" + row.observations +
      "</td><td>" + monitoringAnalysisAssociation(row.hard_sets_vs_next_e1rm) +
      "</td><td>" + monitoringAnalysisAssociation(row.session_load_vs_next_e1rm) +
      "</td></tr>";
  }).join("");
  var calibrationRows = (calibration.observations || []).map(function (row) {
    var prior = row.prior_raw_e1rm_kg == null ? "Unavailable" : fmt(row.prior_raw_e1rm_kg) + " kg";
    var ci = row.calibration_ci_low == null ? "Unavailable" :
      fmt(row.calibration_ci_low, 2) + "–" + fmt(row.calibration_ci_high, 2);
    return "<tr><td>" + esc(row.performed_on) + "</td><td>" + esc(row.calibration_context_as_of || "Unavailable") + "</td><td>" + esc(row.exercise_id) +
      "</td><td>" + fmt(row.measured_kg) + " kg</td><td>" + prior +
      "</td><td>" + esc(row.prior_raw_method || "Unavailable") +
      "</td><td>" + esc(row.prior_raw_method_version || "Unavailable") +
      "</td><td>" + fmt(row.existing_calibration_factor, 3) +
      "</td><td>" + esc(String(row.existing_factor_applied)) +
      "</td><td>" + ci + "</td></tr>";
  }).join("");
  target.innerHTML =
    "<p class='muted'>As of <strong>" + esc(meta.as_of || "Unavailable") +
    "</strong> · analysis " + esc(meta.analysis_version || "Unavailable") +
    " · seed " + esc(String(meta.seed)) + " · database fingerprint " +
    esc(meta.database_fingerprint || "Unavailable") + "</p>" +
    "<p class='muted'>Sessions " + (coverage.sessions == null ? "Unavailable" : coverage.sessions) +
    " · with feedback " + (coverage.sessions_with_feedback == null ? "Unavailable" : coverage.sessions_with_feedback) +
    " · sets " + (coverage.sets == null ? "Unavailable" : coverage.sets) +
    " · exercises " + (coverage.exercises == null ? "Unavailable" : coverage.exercises) + "</p>" +
    "<h3>Training dose over time</h3>" + analysisLineChart(data.dose || []) +
    (rows ? "<h4>Dose by session</h4><div class='table-scroll'><table><thead><tr><th>Date</th><th>Type</th><th>Working sets</th><th>Hard sets</th><th>Tonnage</th><th>Session load</th></tr></thead><tbody>" + rows + "</tbody></table></div>" : "<p class='empty'>No session dose observations.</p>") +
    (allDoseRows.length > 8 ? "<button type='button' class='ghost' id='monitoring-analysis-toggle-dose'>" +
      (monitoringAnalysisShowAllDose ? "Show latest dose only" : "Show full dose list (" + allDoseRows.length + ")") + "</button>" : "") +
    "<h3>Hard sets vs subsequent e1RM</h3><p class='muted'>Session dose precedes the next session best for the same lift. Correlation is descriptive and not causal.</p>" +
    (selectedAssociation ? "<h4>" + esc(selectedAssociation.exercise_id) + "</h4>" +
      analysisScatter(selectedAssociation.hard_sets_points, selectedAssociation.hard_sets_vs_next_e1rm, selectedAssociation.exercise_id + " hard sets vs next e1RM") +
      analysisScatter(selectedAssociation.session_load_points, selectedAssociation.session_load_vs_next_e1rm, selectedAssociation.exercise_id + " session load vs next e1RM") :
      "<p class='empty'>Insufficient observations for lagged associations.</p>") +
    (associations ? "<div class='table-scroll'><table><thead><tr><th>Exercise</th><th>Obs</th><th>Hard sets vs next e1RM</th><th>Session load vs next e1RM</th></tr></thead><tbody>" + associations + "</tbody></table></div>" : "") +
    (associationRows.length > 1 ? "<button type='button' class='ghost' id='monitoring-analysis-toggle-list'>" +
      (monitoringAnalysisShowAll ? "Show selected only" : "Show full association list") + "</button>" : "") +
    "<h3>Data coverage and missingness</h3><p class='muted'>Unavailable values are not zero. Missing feedback reduces session-load coverage.</p>" +
    "<h3>Calibration transparency</h3>" +
    "<p class='muted'>Factor and CI are the state available as of " + esc(calibration.as_of || "Unavailable") +
    "; historical calibration state is not reconstructed. Method version: " + esc(calibration.method_version || "Unavailable") + ".</p>" +
    (calibrationRows ? "<div class='table-scroll'><table><thead><tr><th>Test</th><th>Context as of</th><th>Exercise</th><th>Measured</th><th>Prior raw</th><th>Method</th><th>Version</th><th>Factor</th><th>Applied</th><th>CI</th></tr></thead><tbody>" + calibrationRows + "</tbody></table></div>" : "<p class='empty'>No measured tests in this analysis.</p>") +
    "<p class='muted'>" + esc((calibration.note || "")) + "</p>";
  wireMonitoringAnalysisControls();
}

function wireMonitoringAnalysisControls() {
  var toggleList = document.getElementById("monitoring-analysis-toggle-list");
  if (toggleList) {
    toggleList.addEventListener("click", function () {
      monitoringAnalysisShowAll = !monitoringAnalysisShowAll;
      if (monitoringAnalysisData) renderMonitoringAnalysis(monitoringAnalysisData);
    });
  }
  var toggleDose = document.getElementById("monitoring-analysis-toggle-dose");
  if (toggleDose) {
    toggleDose.addEventListener("click", function () {
      monitoringAnalysisShowAllDose = !monitoringAnalysisShowAllDose;
      if (monitoringAnalysisData) renderMonitoringAnalysis(monitoringAnalysisData);
    });
  }
  var associationSelect = document.getElementById("monitoring-analysis-association");
  if (associationSelect && !associationSelect.dataset.wired) {
    associationSelect.dataset.wired = "1";
    associationSelect.addEventListener("change", function () {
      if (monitoringAnalysisData) renderMonitoringAnalysis(monitoringAnalysisData);
    });
  }
}

async function loadMonitoringAnalysis() {
  var target = document.getElementById("monitoring-analysis-result");
  var date = document.getElementById("monitoring-analysis-date");
  if (!target) return;
  target.innerHTML = "<p class='empty'>Running analysis…</p>";
  try {
    var data = await api("/api/monitoring-analysis?as_of=" +
      encodeURIComponent((date && date.value) || today()));
    monitoringAnalysisData = data;
    monitoringAnalysisShowAll = false;
    monitoringAnalysisShowAllDose = false;
    renderMonitoringAnalysis(data);
  } catch (error) {
    target.innerHTML = "<p class='warnbox'>Analysis unavailable: " + esc(error.message) + "</p>";
  }
}
