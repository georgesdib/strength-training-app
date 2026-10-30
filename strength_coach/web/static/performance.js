/* Performance view: raw e1RM observations, rolling median and configured ratios.
 * Descriptive only; no decay, calibration, target ratio or diagnosis. */
var performanceExercisesLoaded = false;

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
  var rows = (data.buckets || []).map(function (row) {
    return "<tr><td>" + esc(row.date) + "</td><td>" + esc(row.session_type) +
      "</td><td>" + row.working_sets + "</td><td>" + row.hard_sets +
      "</td><td>" + fmt(row.tonnage_kg) + " kg</td></tr>";
  }).join("");
  target.innerHTML = "<div class='panel'><h3>Dose by session</h3>" +
    (rows ? "<div class='table-scroll'><table><thead><tr><th>Date</th><th>Type</th><th>Working sets</th><th>Hard sets</th><th>Tonnage</th></tr></thead><tbody>" + rows + "</tbody></table></div>" : "<p class='empty'>No sessions in this range.</p>") + "</div>";
}

function renderPerformanceRatios(data) {
  var target = document.getElementById("performance-ratios");
  if (!target) return;
  var rows = [];
  (data.relationships || []).forEach(function (item) {
    var row = item.current || {};
    rows.push("<tr><td>" + esc(row.label || row.relationship_id) + "</td><td>" +
      (row.ratio_pct == null ? "Unavailable" : fmt(row.ratio_pct) + "%") + "</td><td>" +
      esc(row.numerator_date || "Unavailable") + "</td><td>" +
      esc(row.denominator_date || "Unavailable") + "</td><td>" +
      (row.gap_days == null ? "Unavailable" : row.gap_days) + "</td><td>" +
      esc(row.status || "unavailable") + "</td></tr>");
  });
  target.innerHTML = "<div class='panel'><h3>Configured relative strength</h3>" +
    (rows.length ? "<div class='table-scroll'><table><thead><tr><th>Pair</th><th>Ratio</th><th>Numerator date</th><th>Denominator date</th><th>Gap days</th><th>Status</th></tr></thead><tbody>" + rows.join("") + "</tbody></table></div>" : "<p class='empty'>No configured relationships.</p>") +
    "<p class='muted'>Descriptive ratio of two raw estimates; no target, diagnosis or confidence claim.</p></div>";
}

async function loadPerformanceData() {
  var exercise = document.getElementById("performance-exercise");
  var from = document.getElementById("performance-from");
  var to = document.getElementById("performance-to");
  if (!exercise || !exercise.value) return;
  var e1rmTarget = document.getElementById("performance-e1rm");
  if (e1rmTarget) e1rmTarget.innerHTML = "<p class='empty'>Loading performance…</p>";
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
