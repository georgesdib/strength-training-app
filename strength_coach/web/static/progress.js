/* Longitudinal Progress views. Metric definitions remain owned by the existing APIs. */
var progressCurrent = {from: null, to: null, weeks: 8, volume: null, days: [], attendance: null, exerciseLabel: ""};
var progressLoadGeneration = 0;
var progressLiftGeneration = 0;
var progressExerciseChoices = [];

function progressShiftDate(dateValue, days) {
  var date = new Date(String(dateValue) + "T12:00:00");
  date.setDate(date.getDate() + Number(days));
  return date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" +
    String(date.getDate()).padStart(2, "0");
}

function progressWeekCategories(start, weeks) {
  return Array.from({length: weeks}, function (_, index) {
    var from = progressShiftDate(start, index * 7);
    var to = progressShiftDate(from, 6);
    return {label: "W" + (index + 1), start: from, end: to};
  });
}

function progressIsoWeekInfo(value) {
  var date = new Date(String(value) + "T12:00:00");
  if (!Number.isFinite(date.getTime())) return null;
  var mondayOffset = (date.getDay() + 6) % 7;
  var monday = new Date(date);
  monday.setDate(monday.getDate() - mondayOffset);
  var thursday = new Date(monday);
  thursday.setDate(thursday.getDate() + 3);
  var year = thursday.getFullYear();
  var jan4 = new Date(year, 0, 4, 12);
  var firstMonday = new Date(jan4);
  firstMonday.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7));
  var week = 1 + Math.round((monday.getTime() - firstMonday.getTime()) / (7 * 86400000));
  return {week: week, year: year, monday: progressShiftDate(
    monday.getFullYear() + "-" + String(monday.getMonth() + 1).padStart(2, "0") + "-" +
      String(monday.getDate()).padStart(2, "0"), 0)};
}

function progressVolumeCategories(volumeData) {
  var byWeek = {};
  var cursor = volumeData.from;
  var end = volumeData.to;
  if (cursor && end) {
    while (cursor <= end) {
      var info = progressIsoWeekInfo(cursor);
      if (!info) break;
      if (!byWeek[info.week]) {
        var periodEnd = progressShiftDate(info.monday, 6);
        if (periodEnd > end) periodEnd = end;
        byWeek[info.week] = {label: "W" + info.week + " " + info.year, start: info.monday, end: periodEnd};
      }
      cursor = progressShiftDate(cursor, 7);
    }
  }
  return (volumeData.weeks || []).map(function (week) {
    return byWeek[Number(week)] || {label: "ISO week " + week};
  });
}

function progressRenderSummary(outcomesData, volumeData, progressData, from, to, exerciseCount) {
  var host = $("#progress-dashboard");
  if (!host) return;
  var strength = outcomesData.strength || {};
  var attendance = strength.attendance || {};
  var summary = volumeData.coverage || {};
  var feedback = (progressData && progressData.coverage) || {};
  var srpe = strength.sRPE || {};
  var attendanceText = attendance.target == null
    ? "No weekly target is configured"
    : attendance.target + " target days across the selected " + (attendance.weeks || progressCurrent.weeks) + " weeks; not a calendar";
  var liftRows = (strength.main_lifts || []).map(function (row) {
    return "<tr><td>" + esc(row.exercise_id) + "</td><td>" + (row.n == null ? "unknown" : row.n) +
      "</td><td>" + (row.first_e1rm == null ? "unknown" : fmt(row.first_e1rm) + " kg") + " <span class='muted'>" + esc(row.first_on || "") + "</span></td>" +
      "<td>" + (row.last_e1rm == null ? "unknown" : fmt(row.last_e1rm) + " kg") + " <span class='muted'>" + esc(row.last_on || "") + "</span></td>" +
      "<td>" + (row.change_kg == null ? "unknown" : (row.change_kg > 0 ? "+" : "") + fmt(row.change_kg) + " kg") +
      "</td><td>" + (row.best_e1rm == null ? "unknown" : fmt(row.best_e1rm) + " kg") + "</td></tr>";
  }).join("");
  host.innerHTML = "<p class='muted'>" + esc(from) + " to " + esc(to) +
    " · all quantities remain in their own units and definitions.</p>" +
    "<div class='cards compact-cards'>" +
    "<div class='card'><div class='label'>Recorded training days</div><div class='value'>" +
      (attendance.completed == null ? "unknown" : attendance.completed) + "</div><div class='sub'>" + esc(attendanceText) + "</div></div>" +
    "<div class='card'><div class='label'>Eligible main lifts</div><div class='value'>" +
      ((strength.main_lifts || []).length) + "</div><div class='sub'>" + ((strength.sessions == null) ? "—" : strength.sessions) + " distinct training days</div></div>" +
    "<div class='card'><div class='label'>sRPE recorded</div><div class='value'>" + (srpe.n == null ? 0 : srpe.n) +
      "</div><div class='sub'>" + (srpe.average == null ? "average unavailable" : "mean " + fmt(srpe.average) + " / 10") +
      " · all-to-date coverage " + (feedback.with_srpe == null ? "unknown" : feedback.with_srpe + " / " + (feedback.sessions || 0)) +
      " (" + (feedback.pct == null ? "unknown" : feedback.pct + "%") + ")</div></div>" +
    "<div class='card'><div class='label'>Working-set coverage</div><div class='value'>" +
      (summary.observed_weeks == null ? "unknown" : summary.observed_weeks + "/" + (summary.denominator || "?")) +
      "</div><div class='sub'>" + esc(summary.mode || "coverage unavailable") + " coverage · " +
      (exerciseCount || 0) + " e1RM-eligible exercises</div></div></div>" +
    "<details class='panel'><summary>Main-lift change table (selected period)</summary><div class='table-scroll'><table><thead><tr><th>Exercise</th><th>Observations</th><th>First estimate</th><th>Latest estimate</th><th>Change</th><th>Best</th></tr></thead>" +
      "<tbody>" + (liftRows || "<tr><td colspan='6' class='muted'>No eligible main-lift observations in this period.</td></tr>") + "</tbody></table></div></details>" +
    "<p class='muted'>Not plotted: bodyweight-relative strength (no dedicated date-indexed bodyweight series or plausibility bounds), muscle-volume totals (overlapping primary-muscle tags without weighted contributions), tonnage/intensity time series (no matching weekly report), or VBT residual trends (aggregate gate/status only). Sets, repetitions, tonnage and RIR are not interchangeable.</p>";
}

function progressRenderDose(volumeData) {
  var host = $("#progress-dose-chart");
  var note = $("#progress-dose-note");
  var select = $("#progress-pattern");
  if (!host || !volumeData) return;
  var rows = volumeData.patterns || [];
  var chosen = select && select.value;
  if (!rows.some(function (row) { return row.pattern === chosen; })) chosen = rows.length ? rows[0].pattern : "";
  if (select) {
    select.innerHTML = rows.map(function (row) {
      return "<option value='" + esc(row.pattern) + "'" + (row.pattern === chosen ? " selected" : "") + ">" +
        esc(String(row.pattern).replace(/_/g, " ")) + "</option>";
    }).join("");
  }
  var row = rows.find(function (item) { return item.pattern === chosen; });
  var categories = progressVolumeCategories(volumeData);
  host.innerHTML = row && categories.length ? groupedBarChart({
    title: String(row.pattern).replace(/_/g, " ") + " weekly working sets",
    xTitle: "Observed ISO week number", yTitle: "Working sets",
    categories: categories,
    series: [{id: "working-sets", label: "Working sets", values: row.weeks || []}],
    formatY: function (value) { return chartNumber(value, 0); },
    note: "Counts are working sets from the volume API, not RIR-defined hard sets. " +
      "Window " + (volumeData.from || progressCurrent.from) + " to " + (volumeData.to || progressCurrent.to) +
      ". The API returns ISO week numbers; weeks absent under unknown coverage are omitted, not zero-filled."
  }) : "<p class='empty'>No working-set observations for this pattern in the selected period.</p>";
  if (note) {
    var coverage = volumeData.coverage || {};
    note.textContent = coverage.mode === "complete"
      ? "Configured complete coverage: empty calendar weeks are shown as zero recorded working sets. This is still the stored training log, not proof of missed sessions."
      : "Coverage is unknown: only weeks represented in the log are listed. Missing weeks are omitted, not interpreted as zero.";
  }
}

function progressRenderFrequency(days, attendance, start, weeks) {
  var host = $("#progress-frequency-chart");
  var note = $("#progress-frequency-note");
  if (!host) return;
  var categories = progressWeekCategories(start, weeks);
  var counts = categories.map(function (period) {
    return (days || []).filter(function (day) {
      var date = String(day.occurred_on || "").slice(0, 10);
      return Number(day.active_fragment_count || 0) > 0 && date >= period.start && date <= period.end;
    }).length;
  });
  var targetPerWeek = attendance && attendance.target != null && Number(attendance.weeks) > 0
    ? Number(attendance.target) / Number(attendance.weeks) : null;
  var referenceLines = targetPerWeek == null ? [] : [{value: targetPerWeek,
    label: "Configured target: " + chartNumber(targetPerWeek, 1) + " sessions per week (not a calendar)"}];
  host.innerHTML = groupedBarChart({
    title: "Recorded training days by 7-day period", xTitle: "7-day period ending on the selected date",
    yTitle: "Distinct active training days", categories: categories.map(function (period) {
      var startDate = new Date(period.start + "T12:00:00");
      var endDate = new Date(period.end + "T12:00:00");
      var label = (startDate.getMonth() + 1) + "/" + startDate.getDate() + "–" + (endDate.getMonth() + 1) + "/" + endDate.getDate();
      return {label: label, start: period.start, end: period.end};
    }),
    series: [{id: "recorded-days", label: "Recorded training days", values: counts}],
    referenceLines: referenceLines, formatY: function (value) { return chartNumber(value, 0); },
    note: "One day counts once even if it contains multiple session fragments. A zero means no active training day is stored in that period; it does not indicate a missed scheduled workout."
  });
  if (note) note.textContent = targetPerWeek == null
    ? "No weekly attendance target is configured. No planned-session calendar is stored."
    : "Dashed reference is the configured weekly target (" + chartNumber(targetPerWeek, 1) + "/week), not planned dates or adherence. Counts are distinct training dates from stored active records.";
}

async function loadProgressLiftCharts(exerciseId) {
  var e1rmHost = $("#progress-strength-chart");
  var loadHost = $("#progress-load-chart");
  var summaryHost = $("#progress-strength-summary");
  if (!e1rmHost || !loadHost) return;
  if (!exerciseId) {
    e1rmHost.innerHTML = "<p class='empty'>Choose an e1RM-eligible exercise.</p>";
    loadHost.innerHTML = "<p class='empty'>Choose an exercise to view recorded working-set loads.</p>";
    if (summaryHost) summaryHost.innerHTML = "";
    return;
  }
  var generation = ++progressLiftGeneration;
  progressCurrent.exerciseId = exerciseId;
  var query = "?exercise_id=" + encodeURIComponent(exerciseId) + "&from=" + encodeURIComponent(progressCurrent.from) +
    "&to=" + encodeURIComponent(progressCurrent.to);
  e1rmHost.innerHTML = "<p class='empty'>Loading eligible strength observations…</p>";
  loadHost.innerHTML = "<p class='empty'>Loading completed working-set history…</p>";
  try {
    var historyQuery = "?exercise_id=" + encodeURIComponent(exerciseId) + "&limit=1&offset=0&include_analytics=true&start=" +
      encodeURIComponent(progressCurrent.from) + "&end=" + encodeURIComponent(progressCurrent.to);
    var results = await Promise.all([
      api("/api/performance/e1rm" + query),
      api("/api/exercise-history" + historyQuery)
    ]);
    if (generation !== progressLiftGeneration) return;
    var e1rm = results[0];
    var points = e1rm.points || [];
    e1rmHost.innerHTML = dateSeriesChart({
      title: String(exerciseId) + " eligible raw e1RM",
      xTitle: "Training date", yTitle: "Raw estimated 1RM (kg)",
      series: [
        {id: "raw", label: "Raw daily best", points: points.map(function (point) { return {date: point.date, value: point.kg}; })},
        {id: "median", label: "Trailing 3-observation median", points: points.map(function (point) { return {date: point.date, value: point.rolling_median_kg}; })}
      ],
      emptyMessage: "No eligible e1RM observations for this exercise in the selected period.",
      note: "API-provided raw formula Epley+RIR best per training day and trailing median of up to 3 observed points. Degraded observations, gaps, equipment changes and missing days are not imputed."
    });
    var summary = e1rm.summary || {};
    if (summaryHost) summaryHost.innerHTML = "<div class='cards compact-cards'>" +
      "<div class='card'><div class='label'>Latest eligible estimate</div><div class='value'>" +
        (summary.latest ? fmt(summary.latest.kg) + " kg" : "unknown") + "</div><div class='sub'>" + esc(summary.latest && summary.latest.date || "no observation") + "</div></div>" +
      "<div class='card'><div class='label'>Best in selected period</div><div class='value'>" +
        (summary.best ? fmt(summary.best.kg) + " kg" : "unknown") + "</div><div class='sub'>" + esc(summary.best && summary.best.date || "no eligible observation") + "</div></div>" +
      "<div class='card'><div class='label'>Eligible observations</div><div class='value'>" + (summary.n == null ? 0 : summary.n) +
        "</div><div class='sub'>" + esc(summary.status || "unavailable") + " · raw formula; no decay/calibration</div></div></div>" +
      "<p class='muted'>Equipment changes are not stored and cannot be detected.</p>";

    var history = results[1];
    var choices = progressExerciseChoices || [];
    var choice = choices.find(function (item) { return item.id === exerciseId; });
    var label = choice ? choice.label : exerciseId;
    progressCurrent.exerciseLabel = label;
    progressRenderExerciseExposure(history.analytics, progressCurrent.from, progressCurrent.weeks, exerciseId, label, history);
    var equivalents = (history.included_exercises || []).filter(function (item) { return item.id !== exerciseId; });
    var equivalentNote = equivalents.length
      ? "<p class='muted'>Declared history equivalents are combined by the existing endpoint: " +
        equivalents.map(function (item) { return esc(item.display || item.id); }).join(", ") + ".</p>" : "";
    loadHost.innerHTML = history.analytics && Number(history.analytics.working_sets || 0)
      ? exerciseHistoryAnalyticsCharts(history.analytics, label) + equivalentNote
      : "<p class='empty'>No completed working-set history for this exercise in the selected period.</p>";
  } catch (error) {
    if (generation !== progressLiftGeneration) return;
    e1rmHost.innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
    loadHost.innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  }
}

async function loadProgressAssociation() {
  var host = $("#progress-association");
  var exercise = $("#progress-exercise");
  var button = $("#progress-load-association");
  if (!host || !exercise || !exercise.value) return;
  if (button) button.disabled = true;
  host.innerHTML = "<p class='empty'>Loading the existing read-only association…</p>";
  try {
    var data = await api("/api/monitoring-analysis?as_of=" + encodeURIComponent(progressCurrent.to));
    var row = (data.associations || []).find(function (item) { return item.exercise_id === exercise.value; });
    if (!row) {
      host.innerHTML = "<p class='empty'>No eligible next-e1RM association is available for this exercise through " + esc(progressCurrent.to) + ".</p>";
      return;
    }
    host.innerHTML = "<div class='progress-dashboard-grid progress-association-grid'>" +
      "<div><h3>Prior hard sets → next eligible e1RM</h3>" + analysisScatter(row.hard_sets_points || [], row.hard_sets_vs_next_e1rm,
        "Prior hard sets vs next e1RM", "Prior-session hard sets", "Next eligible e1RM (kg)") + "</div>" +
      "<div><h3>Prior session load → next eligible e1RM</h3>" + analysisScatter(row.session_load_points || [], row.session_load_vs_next_e1rm,
        "Prior session load vs next e1RM", "Prior session load (AU)", "Next eligible e1RM (kg)") + "</div></div>" +
      "<p class='muted'>" + esc(data.meta && data.meta.note || "Descriptive associations only; no causal claim or model adoption.") +
      " Pairing and correlation are supplied by the read-only analysis service; this chart does not refit or predict.</p>";
  } catch (error) {
    host.innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  } finally {
    if (button) button.disabled = false;
  }
}

async function loadProgressExecution(workoutId) {
  var host = $("#progress-execution");
  if (!host) return;
  if (!workoutId) {
    host.innerHTML = "<p class='empty'>Select a completed workout with a stored plan snapshot.</p>";
    return;
  }
  host.innerHTML = "<p class='empty'>Loading workout snapshot…</p>";
  try {
    var response = await api("/api/workout/" + encodeURIComponent(workoutId));
    var workout = response.workout || {};
    if (workout.status !== "completed") {
      host.innerHTML = "<p class='empty'>Only completed workouts can be compared.</p>";
      return;
    }
    var plan = workout.original_plan || {};
    var items = Array.isArray(plan.items) ? plan.items : [];
    if (!items.length) {
      host.innerHTML = "<p class='empty'>This completed workout has no stored original plan snapshot; planned values are unavailable.</p>";
      return;
    }
    var planned = items.reduce(function (total, item) {
      var value = Number(item.sets);
      return total + (Number.isFinite(value) && value > 0 ? value : 0);
    }, 0);
    var logged = Array.isArray(workout.sets) ? workout.sets.length : 0;
    host.innerHTML = groupedBarChart({
      title: "Original planned set count vs logged set rows",
      xTitle: "Completed workout", yTitle: "Set rows", categories: [{label: String(workout.for_date || workout.started_at || "Selected workout").slice(0, 10)}],
      series: [
        {id: "planned", label: "Original planned sets", values: [planned]},
        {id: "logged", label: "Logged set rows", values: [logged]}
      ],
      formatY: function (value) { return chartNumber(value, 0); },
      note: "Uses the frozen original plan snapshot and all logged set rows for one completed app-tracked workout; actual rows can have different roles and are not matched item-by-item to the plan. It is not a planned-session calendar or a measure of adherence."
    }) + (workout.plan_modified ? "<p class='muted'>The live plan was edited; this comparison uses the original start-time plan.</p>" : "") +
      "<p class='muted'>Imported/legacy sessions without a stored workout snapshot are not shown. Set counts are aggregated to avoid ambiguous item matching when an exercise appears more than once.</p>";
  } catch (error) {
    host.innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  }
}

async function loadProgressOverview() {
  var target = $("#progress-dashboard");
  var status = $("#progress-overview-status");
  if (!target) return;
  var generation = ++progressLoadGeneration;
  var weeks = Number($("#progress-overview-weeks") && $("#progress-overview-weeks").value || 8);
  var to = $("#progress-overview-date") && $("#progress-overview-date").value || today();
  var from = progressShiftDate(to, -(7 * weeks - 1));
  progressCurrent = {from: from, to: to, weeks: weeks, volume: null, days: [], attendance: null, exerciseLabel: "", exerciseId: ""};
  var associationHost = $("#progress-association");
  if (associationHost) associationHost.innerHTML = "<p class='empty'>Load an association to inspect available paired observations.</p>";
  target.innerHTML = "<p class='empty'>Loading progress data…</p>";
  if (status) status.textContent = "Loading";
  try {
    var outcomesQuery = "?weeks=" + encodeURIComponent(weeks) + "&date=" + encodeURIComponent(to);
    var historyQuery = "?start=" + encodeURIComponent(from) + "&end=" + encodeURIComponent(to) + "&limit=200&offset=0";
    var results = await Promise.all([
      api("/api/outcomes" + outcomesQuery),
      api("/api/volume?date=" + encodeURIComponent(to) + "&weeks=" + encodeURIComponent(weeks)),
      api("/api/history/days" + historyQuery),
      api("/api/performance/relationship-options"),
      api("/api/progress?date=" + encodeURIComponent(to))
    ]);
    if (generation !== progressLoadGeneration) return;
    var outcomesData = results[0], volumeData = results[1], historyData = results[2], options = results[3], progressData = results[4];
    var attendance = outcomesData.strength && outcomesData.strength.attendance || {};
    progressCurrent.volume = volumeData;
    progressCurrent.days = historyData.days || [];
    progressCurrent.attendance = attendance;
    progressRenderSummary(outcomesData, volumeData, progressData, from, to, (options.exercises || []).length);
    var ratioHost = $("#progress-ratio-chart");
    if (ratioHost) ratioHost.innerHTML = progressRatioSvg((progressData.performance || {}).points || [], "Recent observed performance ratio");
    progressRenderFrequency(progressCurrent.days, attendance, from, weeks);
    progressRenderCalendar(progressCurrent.days, from, weeks);
    progressRenderDose(volumeData);

    var exerciseSelect = $("#progress-exercise");
    var previousExercise = exerciseSelect && exerciseSelect.value;
    var exercises = options.exercises || [];
    progressExerciseChoices = exercises;
    if (exerciseSelect) {
      exerciseSelect.innerHTML = exercises.length ? exercises.map(function (item) {
        return "<option value='" + esc(item.id) + "'>" + esc(item.label) + "</option>";
      }).join("") : "<option value=''>No e1RM-eligible exercises available</option>";
      var mainLiftIds = new Set(((outcomesData.strength || {}).main_lifts || []).map(function (item) { return item.exercise_id; }));
      var defaultMain = exercises.find(function (item) { return mainLiftIds.has(item.id); });
      if (exercises.some(function (item) { return item.id === previousExercise; })) exerciseSelect.value = previousExercise;
      else if (defaultMain) exerciseSelect.value = defaultMain.id;
      else if (exercises.length) exerciseSelect.value = exercises[0].id;
    }
    var workoutSelect = $("#progress-workout");
    if (workoutSelect) {
      var priorWorkout = workoutSelect.value;
      var choices = [];
      (historyData.days || []).forEach(function (day) {
        if (Number(day.active_fragment_count || 0) < 1) return;
        (day.workout_ids || []).forEach(function (id) {
          if (!choices.some(function (item) { return item.id === id; })) {
            choices.push({id: id, date: day.occurred_on, type: day.session_type});
          }
        });
      });
      workoutSelect.innerHTML = "<option value=''>Select a completed workout</option>" + choices.map(function (item) {
        return "<option value='" + esc(item.id) + "'>" + esc(item.date + " · " + item.type + " · " + item.id.slice(0, 8)) + "</option>";
      }).join("");
      if (choices.some(function (item) { return item.id === priorWorkout; })) workoutSelect.value = priorWorkout;
      else workoutSelect.value = "";
      if (!choices.length) workoutSelect.innerHTML = "<option value=''>No app-tracked workout snapshots in this period</option>";
    }
    if (status) status.textContent = "Updated";
    await loadProgressLiftCharts(exerciseSelect && exerciseSelect.value);
    if (workoutSelect && workoutSelect.value) await loadProgressExecution(workoutSelect.value);
    else if ($("#progress-execution")) $("#progress-execution").innerHTML = "<p class='empty'>Select a completed app-tracked workout with a stored original plan snapshot.</p>";
  } catch (error) {
    if (generation !== progressLoadGeneration) return;
    target.innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
    if (status) status.textContent = "Could not load";
  }
}

if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  $("#progress-overview-form")?.addEventListener("submit", function (event) {
    event.preventDefault();
    loadProgressOverview();
  });
  $("#progress-exercise")?.addEventListener("change", function () {
    $("#progress-association").innerHTML = "<p class='empty'>Load an association to inspect available paired observations.</p>";
    loadProgressLiftCharts(this.value);
  });
  $("#progress-pattern")?.addEventListener("change", function () { progressRenderDose(progressCurrent.volume); });
  $("#progress-load-association")?.addEventListener("click", loadProgressAssociation);
  $("#progress-workout")?.addEventListener("change", function () { loadProgressExecution(this.value); });
}


function progressRenderCalendar(days, start, weeks) {
  var host = $("#progress-calendar");
  if (!host) return;
  var end = progressShiftDate(start, weeks * 7 - 1);
  var startDate = new Date(start + "T12:00:00");
  var endDate = new Date(end + "T12:00:00");
  var mondayOffset = (startDate.getDay() + 6) % 7;
  var displayStart = progressShiftDate(start, -mondayOffset);
  var endOffset = (7 - ((endDate.getDay() + 6) % 7) - 1) % 7;
  var displayEnd = progressShiftDate(end, endOffset);
  var active = new Set((days || []).filter(function (day) {
    return Number(day.active_fragment_count || 0) > 0;
  }).map(function (day) { return String(day.occurred_on || "").slice(0, 10); }));
  var cells = "";
  for (var cursor = displayStart; cursor <= displayEnd; cursor = progressShiftDate(cursor, 1)) {
    var inRange = cursor >= start && cursor <= end;
    var trained = inRange && active.has(cursor);
    var label = !inRange ? cursor + " · outside selected range" : cursor + (trained
      ? " · active training day recorded" : " · no active training day recorded");
    cells += "<div class='activity-cell" + (trained ? " is-active" : "") + (!inRange ? " outside-range" : "") +
      "' role='img' title='" + esc(label) + "' aria-label='" + esc(label) + "'><span>" +
      esc(cursor.slice(8, 10)) + "</span></div>";
  }
  host.innerHTML = "<p class='muted'>Observed training dates only; blank means no active date is stored, not a missed scheduled session.</p>" +
    "<div class='progress-calendar' role='group' aria-label='Stored active training days from " + esc(start) + " to " + esc(end) + "'>" +
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(function (day) {
      return "<div class='activity-weekday' aria-hidden='true'>" + day + "</div>";
    }).join("") + cells + "</div>";
}

function progressRenderExerciseExposure(analytics, start, weeks, exerciseId, exerciseLabel, history) {
  var frequencyHost = $("#progress-exercise-frequency-chart");
  var volumeHost = $("#progress-exercise-volume-chart");
  if (!frequencyHost || !volumeHost) return;
  var weeks = analytics && analytics.weekly || [];
  var equivalents = ((history && history.included_exercises) || []).filter(function (item) { return item.id !== exerciseId; });
  var equivalentNote = equivalents.length
    ? " History includes declared equivalents: " + equivalents.map(function (item) { return item.display || item.id; }).join(", ") + "."
    : "";
  var common = "Based on complete-range Python aggregates for " + exerciseLabel + ". ISO-week buckets are clipped to the selected dates." + equivalentNote;
  var categories = weeks.map(function (period) {
    return {label: "W" + period.iso_week + " " + period.iso_year, start: period.start, end: period.end};
  });
  frequencyHost.innerHTML = groupedBarChart({
    title: exerciseLabel + " training dates per ISO week", xTitle: "ISO week in selected range", yTitle: "Distinct training dates",
    categories: categories, series: [{id: "exercise-days", label: "Days with working sets", values: weeks.map(function (item) { return item.training_dates; })}],
    emptyMessage: "No complete exercise-frequency observations in this period.",
    formatY: function (value) { return chartNumber(value, 0); }, note: common + " Counts are distinct dates, not session fragments."
  });
  volumeHost.innerHTML = groupedBarChart({
    title: exerciseLabel + " working sets per ISO week", xTitle: "ISO week in selected range", yTitle: "Completed working sets",
    categories: categories, series: [{id: "exercise-sets", label: "Working sets", values: weeks.map(function (item) { return item.working_sets; })}],
    emptyMessage: "No complete weekly working-set observations in this period.",
    formatY: function (value) { return chartNumber(value, 0); }, note: common + " This count is not repetitions, tonnage, or RIR-defined hard sets."
  });
}
