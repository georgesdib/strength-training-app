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

function chartFrame(title, svg, legend) {
  return "<div class='chart-frame' role='button' tabindex='0' data-chart-title='" + esc(title) +
    "' data-chart-legend='" + esc(legend || "") + "' aria-label='Enlarge chart: " + esc(title) + "'>" +
    "<p class='chart-title'><strong>" + esc(title) + "</strong><span class='muted'>click to enlarge</span></p>" +
    svg + (legend ? "<p class='chart-legend'>" + esc(legend) + "</p>" : "") + "</div>";
}

function openChartDialog(frame) {
  var dialog = document.getElementById("chart-dialog");
  var body = document.getElementById("chart-dialog-body");
  var title = document.getElementById("chart-dialog-title");
  if (!dialog || !body || !title || typeof dialog.showModal !== "function") return;
  var svg = frame.querySelector("svg");
  var legend = frame.querySelector(".chart-legend");
  title.textContent = frame.dataset.chartTitle || "Chart";
  body.innerHTML = (svg ? svg.outerHTML : "") + (legend ? legend.outerHTML : "");
  dialog.showModal();
}

if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("click", function (event) {
    var close = event.target.closest("#chart-dialog-close");
    var dialog = document.getElementById("chart-dialog");
    if (close && dialog) {
      dialog.close();
      return;
    }
    var frame = event.target.closest(".chart-frame");
    if (frame) openChartDialog(frame);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    var frame = event.target.closest(".chart-frame");
    if (!frame) return;
    event.preventDefault();
    openChartDialog(frame);
  });
}

function chartAxes(xTitle, yTitle, xTicks, yTicks, plot, width, height) {
  var left = plot.left, right = plot.right, top = plot.top, bottom = plot.bottom;
  var markup = "<g class='chart-axis'>" +
    "<line x1='" + left + "' y1='" + bottom + "' x2='" + right + "' y2='" + bottom + "'></line>" +
    "<line x1='" + left + "' y1='" + top + "' x2='" + left + "' y2='" + bottom + "'></line>";
  xTicks.forEach(function (tick) {
    markup += "<line x1='" + tick.x + "' y1='" + bottom + "' x2='" + tick.x + "' y2='" + (bottom + 4) + "'></line>" +
      "<text class='chart-tick' x='" + tick.x + "' y='" + (height - 18) + "' text-anchor='middle'>" + esc(tick.label) + "</text>";
  });
  yTicks.forEach(function (tick) {
    markup += "<line class='chart-grid' x1='" + left + "' y1='" + tick.y + "' x2='" + right + "' y2='" + tick.y + "'></line>" +
      "<text class='chart-tick' x='" + (left - 8) + "' y='" + (tick.y + 2) + "' text-anchor='end'>" + esc(tick.label) + "</text>";
  });
  markup += "<text class='chart-axis-title' x='" + ((left + right) / 2) + "' y='" + (height - 2) + "' text-anchor='middle'>" + esc(xTitle) + "</text>" +
    "<text class='chart-axis-title' transform='rotate(-90 14 " + ((top + bottom) / 2) + ")' x='14' y='" + ((top + bottom) / 2) + "' text-anchor='middle'>" + esc(yTitle) + "</text>" +
    "</g>";
  return markup;
}

function progressRatioSvg(points, title) {
  var usable = (points || []).map(function (point) {
    return {date: String(point.date || ""), ratio: Number(point.ratio), lifts: Number(point.lifts || 0)};
  }).filter(function (point) {
    return point.date && Number.isFinite(Date.parse(point.date + "T00:00:00Z")) && Number.isFinite(point.ratio);
  }).sort(function (a, b) { return a.date.localeCompare(b.date); });
  if (!usable.length) return "<p class='empty'>No performance-ratio observations in this range.</p>";
  return dateSeriesChart({
    title: title || "Cross-lift performance-ratio observations",
    xTitle: "Training date", yTitle: "Descriptive ratio",
    series: [{id: "ratio", label: "Observed ratio", className: "chart-series-raw",
      points: usable.map(function (point) { return {date: point.date, value: point.ratio, label: point.lifts + " lift comparisons"}; })}],
    referenceLines: [{value: 1, label: "1.00 neutral reference"}],
    formatY: function (value) { return Number(value).toFixed(3); },
    tooltip: function (point) { return point.date + ": ratio " + Number(point.value).toFixed(3) + "; " + point.label; },
    note: "Each point is an observed session-level ratio; same-date fragments can overlap. The 1.00 line is a neutral reference only; no values are imputed."
  });
}

function performanceSvg(points, chartTitle) {
  if (!points || points.length < 1) return "";
  var title = chartTitle || "Raw e1RM observations";
  return dateSeriesChart({
    title: title, xTitle: "Training date", yTitle: "e1RM (kg)",
    series: [
      {id: "raw", label: "Raw e1RM observations", className: "chart-series-raw",
        points: points.map(function (point) { return {date: point.date, value: point.kg}; })},
      {id: "median", label: "Rolling median", className: "chart-series-median",
        points: points.map(function (point) { return {date: point.date, value: point.rolling_median_kg}; })}
    ],
    note: "Solid: raw e1RM observations. Dashed: API-provided rolling median, a trailing median of up to 3 observed points; early points appear only when a window exists. Gaps are not imputed."
  });
}

function exerciseSetCountChart(sessions, exerciseLabel, total) {
  var days = {};
  sessions.forEach(function (session) {
    var date = String(session.occurred_on || "");
    if (!date) return;
    days[date] = (days[date] || 0) + (session.sets || []).length;
  });
  var points = Object.keys(days).sort().map(function (date) { return { date: date, value: days[date] }; });
  if (!points.length) return "<p class='empty'>No completed working-set history for this exercise.</p>";
  var title = exerciseLabel + " working sets by training day";
  var values = points.map(function (point) { return point.value; });
  var min = 0, max = Math.max(1, Math.max.apply(null, values));
  var span = Math.max(1, max - min);
  var width = 640, height = 240;
  var plot = { left: 56, right: width - 16, top: 16, bottom: height - 42 };
  var timestamps = points.map(function (point) { return Date.parse(point.date + "T00:00:00Z"); });
  var dateSpan = Math.max(1, timestamps[timestamps.length - 1] - timestamps[0]);
  var coords = points.map(function (point, index) {
    var x = points.length === 1 ? (plot.left + plot.right) / 2
      : plot.left + ((timestamps[index] - timestamps[0]) / dateSpan) * (plot.right - plot.left);
    var y = plot.bottom - (point.value / span) * (plot.bottom - plot.top);
    return [x, y];
  });
  var line = coords.map(function (pair) { return pair[0].toFixed(1) + "," + pair[1].toFixed(1); }).join(" ");
  var circles = coords.map(function (pair, index) {
    return "<circle cx='" + pair[0].toFixed(1) + "' cy='" + pair[1].toFixed(1) + "' r='3'><title>" +
      esc(points[index].date + ": " + points[index].value + " working sets") + "</title></circle>";
  }).join("");
  var xTicks = points.length === 1
    ? [{ x: (plot.left + plot.right) / 2, label: points[0].date }]
    : [{ x: plot.left, label: points[0].date }, { x: plot.right, label: points[points.length - 1].date }];
  if (points.length > 2) {
    var midIndex = Math.floor((points.length - 1) / 2);
    xTicks.splice(1, 0, { x: plot.left + ((timestamps[midIndex] - timestamps[0]) / dateSpan) * (plot.right - plot.left), label: points[midIndex].date });
  }
  var yTicks = [
    { y: plot.bottom, label: "0" },
    { y: (plot.top + plot.bottom) / 2, label: String(Math.round(max / 2)) },
    { y: plot.top, label: String(max) },
  ];
  var note = "Working sets from completed/imported sessions; same-day fragments are combined. Dots are exact training-day totals; no dates are imputed. " +
    (total > sessions.length ? "Showing the latest " + sessions.length + " of " + total + " sessions." : "");
  var svg = "<svg class='performance-chart' style='width:100%;height:auto' viewBox='0 0 " + width + " " + height +
    "' role='img' aria-label='" + esc(title) + "'><title>" + esc(title) + "</title>" +
    chartAxes("Training day", "Working sets", xTicks, yTicks, plot, width, height) +
    "<polyline class='chart-series-raw' points='" + line + "' fill='none' stroke-width='2'></polyline>" + circles + "</svg>";
  return chartFrame(title, svg, note);
}

function exerciseHistoryMetricCharts(sessions, exerciseLabel, field, groupField, metricLabel, unitLabel) {
  var grouped = {};
  (sessions || []).forEach(function (session) {
    var date = String(session.occurred_on || "");
    if (!date) return;
    (session.sets || []).forEach(function (set) {
      if (set[field] == null) return;
      var value = Number(set[field]);
      if (!Number.isFinite(value)) return;
      var group = String(set[groupField] || "unspecified");
      if (!grouped[group]) grouped[group] = {};
      if (!grouped[group][date]) grouped[group][date] = [];
      grouped[group][date].push(value);
    });
  });
  var groups = Object.keys(grouped).sort();
  if (!groups.length) return "<p class='empty'>No compatible " + esc(metricLabel.toLowerCase()) + " observations.</p>";
  return groups.map(function (group) {
    var actualUnit = groupField === "reps_unit" ? group : unitLabel;
    var points = Object.keys(grouped[group]).sort().map(function (date) {
      var values = grouped[group][date].slice().sort(function (a, b) { return a - b; });
      var mid = Math.floor(values.length / 2);
      var median = values.length % 2 ? values[mid] : (values[mid - 1] + values[mid]) / 2;
      return { date: date, value: median, n: values.length };
    });
    var title = exerciseLabel + " " + metricLabel.toLowerCase() + " (" + group + ") by training day";
    var width = 640, height = 240;
    var plot = { left: 64, right: width - 16, top: 16, bottom: height - 42 };
    var values = points.map(function (point) { return point.value; });
    var min = 0, max = Math.max(1, Math.max.apply(null, values) * 1.1);
    var timestamps = points.map(function (point) { return Date.parse(point.date + "T00:00:00Z"); });
    var dateSpan = Math.max(1, timestamps[timestamps.length - 1] - timestamps[0]);
    function xFor(index) {
      return points.length === 1 ? (plot.left + plot.right) / 2
        : plot.left + ((timestamps[index] - timestamps[0]) / dateSpan) * (plot.right - plot.left);
    }
    function yFor(value) { return plot.bottom - (value / max) * (plot.bottom - plot.top); }
    var coords = points.map(function (point, index) { return [xFor(index), yFor(point.value)]; });
    var polyline = coords.map(function (pair) { return pair[0].toFixed(1) + "," + pair[1].toFixed(1); }).join(" ");
    var circles = coords.map(function (pair, index) {
      var point = points[index];
      return "<circle cx='" + pair[0].toFixed(1) + "' cy='" + pair[1].toFixed(1) + "' r='4'><title>" +
        esc(point.date + ": median " + fmt(point.value) + " " + actualUnit + " across " + point.n + " working sets; " + group) + "</title></circle>";
    }).join("");
    var xTicks = points.length === 1
      ? [{ x: (plot.left + plot.right) / 2, label: points[0].date }]
      : [{ x: plot.left, label: points[0].date }, { x: plot.right, label: points[points.length - 1].date }];
    if (points.length > 2) {
      var midIndex = Math.floor((points.length - 1) / 2);
      xTicks.splice(1, 0, { x: xFor(midIndex), label: points[midIndex].date });
    }
    var yTicks = [
      { y: plot.bottom, label: "0" },
      { y: (plot.top + plot.bottom) / 2, label: fmt(max / 2) },
      { y: plot.top, label: fmt(max) },
    ];
    var svg = "<svg class='performance-chart' style='width:100%;height:auto' viewBox='0 0 " + width + " " + height +
      "' role='img' aria-label='" + esc(title) + "'><title>" + esc(title) + "</title>" +
      chartAxes("Training day", metricLabel + " (" + actualUnit + ")", xTicks, yTicks, plot, width, height) +
      (coords.length > 1 ? "<polyline class='chart-series-raw' points='" + polyline + "' fill='none' stroke-width='2'></polyline>" : "") +
      circles + "</svg>";
    return chartFrame(title, svg, "Each dot is the exact median of completed working sets on that training date; same-day fragments are combined. Grouped by " + groupField + " so unlike units/bases are never mixed. No dates are imputed.");
  }).join("");
}

function exerciseLoadRepsCharts(sessions, exerciseLabel) {
  return "<div class='exercise-history-charts'><h4>Working-set load</h4>" +
    exerciseHistoryMetricCharts(sessions, exerciseLabel, "load_kg", "load_basis", "Load", "kg") +
    "<h4>Repetitions / recorded unit</h4>" +
    exerciseHistoryMetricCharts(sessions, exerciseLabel, "reps", "reps_unit", "Repetitions", "recorded unit") +
    "</div>";
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

var relationshipReloadInFlight = {};

async function reloadRelationshipConfig(stableId, button) {
  if (relationshipReloadInFlight[stableId]) return false;
  relationshipReloadInFlight[stableId] = true;
  var feedback = document.getElementById(stableId);
  if (!feedback) {
    delete relationshipReloadInFlight[stableId];
    return false;
  }
  var control = button || document.getElementById("relationship-reload-" + stableId);
  if (control) {
    control.disabled = true;
    control.textContent = "Reloading…";
  }
  var success = false;
  try {
    success = await loadRelationshipConfig(true);
  } finally {
    delete relationshipReloadInFlight[stableId];
  }
  var current = document.getElementById(stableId);
  if (!current) return success;
  if (success) {
    current.textContent = "Configuration reloaded. Review the pairs and retry.";
    return true;
  }
  current.innerHTML = "<span class='warnbox'>The latest relationship configuration could not be retrieved. Retry the reload.</span> " +
    "<button type='button' class='ghost' id='relationship-reload-" + stableId + "-retry'>Reload configuration</button>";
  var retry = document.getElementById("relationship-reload-" + stableId + "-retry");
  if (retry) retry.addEventListener("click", function () {
    reloadRelationshipConfig(stableId, retry);
  });
  return false;
}

function showRelationshipConflict(targetId) {
  var stableId = targetId === "relationship-add-status"
    ? "relationship-add-status"
    : "performance-relationship-feedback";
  var target = document.getElementById(stableId);
  if (!target) return;
  target.innerHTML = "<span class='warnbox'>Configuration changed elsewhere. Reload the latest pairs, review the changes, then retry.</span> " +
    "<button type='button' class='ghost' id='relationship-reload-" + stableId + "'>Reload configuration</button>";
  var button = document.getElementById("relationship-reload-" + stableId);
  if (!button) return;
  button.addEventListener("click", function () {
    reloadRelationshipConfig(stableId, button);
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
        showRelationshipConflict("performance-relationship-feedback");
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
      showRelationshipConflict("performance-relationship-feedback");
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
  if (!host) return false;
  if (!force && performanceRelationshipConfig) {
    renderRelationshipManagement();
    var cachedAddButton = document.getElementById("relationship-add-submit");
    if (cachedAddButton) {
      cachedAddButton.disabled = false;
      cachedAddButton.title = "";
    }
    return true;
  }
  if (force) performanceRelationshipConfig = null;
  host.innerHTML = "<p class='empty'>Loading pair configuration…</p>";
  try {
    performanceRelationshipConfig = await api("/api/performance/relationships");
    renderRelationshipManagement();
    var addButton = document.getElementById("relationship-add-submit");
    if (addButton) {
      addButton.disabled = false;
      addButton.title = "";
    }
    return true;
  } catch (error) {
    performanceRelationshipConfig = null;
    host.innerHTML = "<p class='warnbox'>Pair configuration failed: " + esc(error.message) + "</p>";
    var disabledAdd = document.getElementById("relationship-add-submit");
    if (disabledAdd) {
      disabledAdd.disabled = true;
      disabledAdd.title = "Relationship configuration and revision must load first.";
    }
    return false;
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
    "<div id='performance-relationship-management'><p class='empty'>Loading pair configuration…</p></div>" +
    "<p class='muted' id='performance-relationship-feedback'></p></div>";
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


function analysisLineChart(rows, chartTitle) {
  if (!Array.isArray(rows) || rows.length < 1) return "<p class='empty'>Insufficient session dose observations for a chart.</p>";
  var title = chartTitle || "Training dose over time";
  return dateSeriesChart({
    title: title, xTitle: "Session date", yTitle: "Sets",
    series: [
      {id: "working", label: "Working sets", className: "chart-series-working",
        points: rows.map(function (row) { return {date: row.date, value: row.working_sets}; })},
      {id: "hard", label: "RIR-defined hard sets", className: "chart-series-hard",
        points: rows.map(function (row) { return {date: row.date, value: row.hard_sets}; })}
    ],
    zeroBaseline: true,
    formatY: function (value) { return chartNumber(value, 0); },
    note: "Working sets and RIR-defined hard sets use different definitions. Dots show recorded sessions; gaps are not imputed."
  });
}

function analysisScatter(points, association, label, xTitle, yTitle) {
  points = (Array.isArray(points) ? points : []).filter(function (point) {
    return Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y));
  });
  if (points.length < 3) {
    return "<p class='empty'>Insufficient observations for " + esc(label) + " chart.</p>";
  }
  var width = 640, height = 240;
  var xs = points.map(function (point) { return Number(point.x); });
  var ys = points.map(function (point) { return Number(point.y); });
  var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
  var yMin = Math.min.apply(null, ys), yMax = Math.max.apply(null, ys);
  var xSpan = Math.max(1, xMax - xMin), ySpan = Math.max(1, yMax - yMin);
  var plot = { left: 56, right: width - 16, top: 16, bottom: height - 42 };
  var circles = points.map(function (point) {
    var x = plot.left + ((Number(point.x) - xMin) / xSpan) * (plot.right - plot.left);
    var y = plot.bottom - ((Number(point.y) - yMin) / ySpan) * (plot.bottom - plot.top);
    return "<circle cx='" + x.toFixed(1) + "' cy='" + y.toFixed(1) + "' r='4'><title>" +
      esc(xTitle + ": " + chartNumber(point.x, 2) + "; " + yTitle + ": " + chartNumber(point.y, 2)) + "</title></circle>";
  }).join("");
  var xTicks = [
    { x: plot.left, label: fmt(xMin) },
    { x: (plot.left + plot.right) / 2, label: fmt((xMin + xMax) / 2) },
    { x: plot.right, label: fmt(xMax) },
  ];
  var yTicks = [
    { y: plot.bottom, label: fmt(yMin) },
    { y: (plot.top + plot.bottom) / 2, label: fmt((yMin + yMax) / 2) },
    { y: plot.top, label: fmt(yMax) },
  ];
  var svg = "<svg class='performance-chart' style='width:100%;height:auto' viewBox='0 0 " + width + " " + height +
    "' role='img' aria-label='" + esc(label) + "'><title>" + esc(label) + "</title>" +
    chartAxes(xTitle, yTitle, xTicks, yTicks, plot, width, height) + circles + "</svg>";
  return chartFrame(label, svg, esc(monitoringAnalysisAssociation(association)) +
    ". Each point is one session pair; the correlation is calculated by the analysis service, never by this page.");
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
    analysisLineChart(data.dose || []) +
    (rows ? "<h4>Dose by session</h4><div class='table-scroll'><table><thead><tr><th>Date</th><th>Type</th><th>Working sets</th><th>Hard sets</th><th>Tonnage</th><th>Session load</th></tr></thead><tbody>" + rows + "</tbody></table></div>" : "<p class='empty'>No session dose observations.</p>") +
    (allDoseRows.length > 8 ? "<button type='button' class='ghost' id='monitoring-analysis-toggle-dose'>" +
      (monitoringAnalysisShowAllDose ? "Show latest dose only" : "Show full dose list (" + allDoseRows.length + ")") + "</button>" : "") +
    "<h3>Hard sets vs subsequent e1RM</h3><p class='muted'>Session dose precedes the next session best for the same lift. Correlation is descriptive and not causal.</p>" +
    (selectedAssociation ? "<h4>" + esc(selectedAssociation.exercise_id) + "</h4>" +
      analysisLineChart(selectedAssociation.dose || [], selectedAssociation.exercise_id + " training dose over time") +
      analysisScatter(selectedAssociation.hard_sets_points, selectedAssociation.hard_sets_vs_next_e1rm, selectedAssociation.exercise_id + " hard sets vs next e1RM", "Hard sets", "Next e1RM (kg)") +
      analysisScatter(selectedAssociation.session_load_points, selectedAssociation.session_load_vs_next_e1rm, selectedAssociation.exercise_id + " session load vs next e1RM", "Session load (AU)", "Next e1RM (kg)") :
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
