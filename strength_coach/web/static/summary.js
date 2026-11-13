/* Descriptive completed-workout summary. Phase 2: sections 1-5 only.
 * It reads the same API as the CLI and never computes a metric of its own.
 * Adherence reuses the renderers in adherence.js, which loads before this file. */
function summaryValue(value, suffix) {
  if (value === null || value === undefined || value === "") return "Unavailable";
  return fmt(value) + (suffix || "");
}

function summaryStatus(row) {
  if (!row || !row.status) return "Unavailable";
  return row.status;
}

function summaryPatterns(patterns) {
  return summaryCounts(patterns);
}

function summaryAxial(axial) {
  if (!axial) return "Unavailable";
  return ["high", "moderate", "low", "unknown"].map(function (key) {
    return key + ": " + (axial[key] == null ? "Unavailable" : axial[key]);
  }).join(" · ");
}

function summaryHeavy(heavy) {
  if (!heavy || heavy.total_sets == null) return "Unavailable";
  var rir = heavy.rir_max == null ? "≤1" : "≤" + heavy.rir_max;
  return heavy.total_sets + " heavy spinal sets (RIR " + rir + ", context only)";
}

function summaryPowerVelocity(rows) {
  if (!Array.isArray(rows) || !rows.length) return "Unavailable";
  return rows.map(function (row) {
    if (row.status) return "Unavailable (" + esc(row.reason || row.status) + ")";
    return row.exercise_id + " @ " + fmt(row.load_kg) + " kg: " +
      fmt(row.change_pct) + "% (" + row.n + " sets)";
  }).join(" · ");
}

function summaryQualityStop(value) {
  if (!value || value.status !== "recorded") return "Not recorded";
  return "Recorded";
}

function summaryCounts(counts) {
  if (!counts) return "Unavailable";
  return Object.keys(counts).sort().map(function (key) {
    return key + ": " + counts[key];
  }).join(" · ");
}


function summaryComparisonHtml(comparison) {
  if (!comparison) return "";
  if (comparison.status !== "available") {
    return "<h3>Historical comparison</h3><p class='muted'>Unavailable: " +
      esc(comparison.reason || comparison.status || "unknown") + "</p>";
  }
  return "<h3>Historical comparison</h3><p>Median of " + comparison.n +
    " prior comparable sessions; working sets " + fmt(comparison.metrics.working_sets) +
    ", hard sets " + fmt(comparison.metrics.hard_sets) +
    ", tonnage " + fmt(comparison.metrics.tonnage_kg) + " kg.</p>";
}

function summaryRatiosHtml(ratios) {
  if (!Array.isArray(ratios) || !ratios.length) return "";
  var rows = ratios.map(function (row) {
    return "<tr><td>" + esc(row.label || row.relationship_id) + "</td><td>" +
      (row.ratio_pct == null ? "Unavailable" : fmt(row.ratio_pct) + "%") + "</td><td>" +
      esc(row.numerator_date || "Unavailable") + "</td><td>" +
      esc(row.denominator_date || "Unavailable") + "</td><td>" +
      (row.gap_days == null ? "Unavailable" : row.gap_days) + "</td><td>" +
      esc(row.status) + "</td></tr>";
  }).join("");
  return "<h3>Relative strength</h3><div class='table-scroll'><table><thead><tr>" +
    "<th>Pair</th><th>Ratio</th><th>Numerator date</th><th>Denominator date</th>" +
    "<th>Gap days</th><th>Status</th></tr></thead><tbody>" + rows + "</tbody></table></div>";
}

function summaryAdherenceHtml(adherence) {
  var head = "<h3>Prescription adherence</h3>";
  if (!adherence) {
    return head + "<p class='muted'>Not available for this session.</p>";
  }
  if (adherence.status !== "available") {
    return head + "<p class='muted'>Not available: " +
      esc(adherenceReason(adherence.reason)) + "</p>";
  }
  var modified = Boolean(adherence.quality && adherence.quality.plan_modified);
  var primary = adherence.final_plan || {};
  var intro = "<p class='muted'>Set completion counts filled prescribed slots; target " +
    "attainment counts matching reps, load and RIR. A filled set can still miss its target.</p>";
  return head + intro +
    (modified ? adherenceChanges(adherence) : "") +
    adherenceViewCard(primary,
      modified ? "Final prescription" : "Prescription issued",
      modified ? "<span class='badge warn'>modified during workout</span>"
               : "<span class='badge'>unmodified</span>") +
    (modified
      ? adherenceViewCard(adherence.original || {}, "Original prescription",
          "<span class='badge'>issued at start</span>")
      : "") +
    adherenceGlobalQuality(adherence.quality) +
    "<p class='muted'>RIR deviation is actual minus target: positive means further from " +
    "failure than prescribed.</p>";
}

function summaryQualityHtml(quality) {
  quality = quality || {};
  var flags = quality.flags || [];
  var coverage = quality.coverage || {};
  var parts = [];
  if (coverage.rir != null) {
    parts.push("RIR recorded on " + Math.round(coverage.rir * 100) + "% of working sets");
  }
  if (coverage.e1rm != null) {
    parts.push("raw e1RM available for " + Math.round(coverage.e1rm * 100) + "% of lifts");
  }
  var rows = flags.map(function (flag) {
    return "<li>" + esc(flag.code) + (flag.detail ? ": " + esc(flag.detail) : "") + "</li>";
  }).join("");
  return "<h3>Data quality</h3>" +
    (parts.length ? "<p class='muted'>" + esc(parts.join(" · ")) + "</p>" : "") +
    (rows
      ? "<details class='adherence-quality'><summary>Limitations (" + flags.length +
        ")</summary><ul class='list'>" + rows + "</ul></details>"
      : "<p class='muted'>No known data-quality limitations.</p>");
}

function renderWorkoutSummary(summary) {
  var target = document.getElementById("workout-ended-summary");
  if (!target) return;
  var strengthRows = (summary.strength || []).map(function (row) {
    var post = row.post || {};
    var recent = row.recent_reference || {};
    var diff = row.difference || {};
    return "<tr><td>" + esc(row.exercise_id) + "</td><td>" +
      summaryValue(post.kg, " kg") + "</td><td>" + summaryValue(recent.kg, " kg") +
      "</td><td>" + summaryValue(diff.kg, " kg") + "</td><td>" + esc(diff.status || "") +
      "</td><td>" + esc(summaryStatus(post)) + "</td></tr>";
  }).join("");
  var doseRows = ((summary.dose || {}).per_exercise || []).map(function (row) {
    return "<tr><td>" + esc(row.exercise_id) + "</td><td>" + row.sets + "</td><td>" +
      (row.reps && row.reps.status ? summaryStatus(row.reps) : summaryValue(row.reps)) +
      "</td><td>" + (row.tonnage_kg && row.tonnage_kg.status ? summaryStatus(row.tonnage_kg) : summaryValue(row.tonnage_kg, " kg")) +
      "</td><td>" + row.hard_sets + "</td><td>" + row.near_failure_sets + "</td></tr>";
  }).join("");
  var feedback = summary.feedback || {};
  var special = summary.special || {};
  var spinal = special.spinal || {};
  target.innerHTML =
    "<details class='panel' style='margin-top:1rem'><summary><strong>Descriptive session summary</strong></summary>" +
    "<p class='muted'>Raw formula performance; no decay or calibration. No composite score.</p>" +
    summaryAdherenceHtml(summary.adherence) +
    summaryQualityHtml(summary.quality) +
    "<h3>Strength performance</h3>" +
    (strengthRows ? "<div class='table-scroll'><table><thead><tr><th>Exercise</th><th>Post</th><th>Recent median</th><th>Difference</th><th>Status</th><th>Quality</th></tr></thead><tbody>" + strengthRows + "</tbody></table></div>" : "<p class='muted'>No raw strength observations.</p>") +
    "<p class='muted'>Difference is descriptive; no significance or meaningful-change claim.</p>" +
    "<h3>External dose</h3>" +
    (doseRows ? "<div class='table-scroll'><table><thead><tr><th>Exercise</th><th>Sets</th><th>Reps</th><th>Tonnage</th><th>Hard</th><th>Near failure</th></tr></thead><tbody>" + doseRows + "</tbody></table></div>" : "<p class='muted'>No completed sets.</p>") +
    "<p>Relative intensity: " + esc(summaryCounts((summary.dose || {}).relative_intensity)) + "</p>" +
    "<p>RIR: " + esc(summaryCounts((summary.dose || {}).rir)) + "</p>" +
    "<p>Patterns: " + esc(summaryPatterns((summary.dose || {}).patterns)) + "</p>" +
    "<h3>Special exposure</h3>" +
    "<p>Power: " + (special.power ? special.power.sets + " sets, " + special.power.reps + " reps" : "Unavailable") +
    " · Mean velocity change: " + esc(summaryPowerVelocity((special.power || {}).mean_velocity_change)) + "</p>" +
    "<p>Quality stop: " + esc(summaryQualityStop(special.quality_stop)) + "</p>" +
    "<p>High-intensity records: " + ((special.high_intensity || []).length) + "</p>" +
    "<p>Spinal: " + esc(spinal.label || "ordinal exposure") + " · weekly cost " +
    summaryValue(spinal.weekly_cost) + " / cap " + summaryValue(spinal.weekly_cap) + "</p>" +
    "<p>Heavy spinal sets: " + esc(summaryHeavy(spinal.heavy_sets)) + "</p>" +
    "<p>Axial demand: " + esc(summaryAxial(spinal.axial_demand)) + "</p>" +
    summaryComparisonHtml(summary.comparison) +
    summaryRatiosHtml(summary.ratios) +
    "<h3>Feedback</h3>" +
    "<p>sRPE: " + summaryValue(feedback.srpe) + " · Duration: " + summaryValue(feedback.duration_min, " min") +
    " · Session load: " + summaryValue(feedback.session_load_au, " AU") + "</p>" +
    "<p>Productivity: " + (feedback.productivity == null ? "Not recorded" : feedback.productivity) + "</p>" +
    "<p class='muted'>Basis: " + esc((summary.basis || {}).performance || "raw_formula_epley_rir") +
    ". Historical comparison, ratios and longitudinal trends are not part of Phase 2.</p>" +
    "</details>";
}

function loadWorkoutSummary(workoutId) {
  var target = document.getElementById("workout-ended-summary");
  if (!target || !workoutId) return;
  api("/api/workout/" + encodeURIComponent(workoutId) + "/summary")
    .then(function (data) { renderWorkoutSummary(data.summary || {}); })
    .catch(function (error) {
      target.innerHTML = "<p class='warnbox'>Summary unavailable: " + esc(error.message) + "</p>";
    });
}
