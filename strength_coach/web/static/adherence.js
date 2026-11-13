/* Prescription adherence: target-vs-actual rendering for completed workouts.
 *
 * The server owns every number. This module only formats and labels the payload from
 * /api/history/<id> (and later the longitudinal API). It never computes a score or infers a
 * target. Set completion is shown separately from rep/load/RIR target attainment because a
 * filled set can still miss its target.
 */

var ADHERENCE_REASON_TEXT = {
  no_prescription_items: "No prescription items were recorded for this workout.",
  no_prescription_snapshot: "No frozen prescription snapshot exists for this session.",
  session_voided: "This session is voided, so it is excluded from adherence analysis.",
  workout_not_found: "The workout record linked to this session is missing.",
  workout_not_completed: "The linked workout was not completed.",
  missing_materialised_session: "The completed workout has no materialised session row.",
  invalid_plan_json: "The workout prescription snapshot could not be read.",
  swapped_exercise: "The exercise was swapped during the workout, so original-plan attribution is unavailable.",
  missing_prescribed_load: "No comparable prescribed load was recorded.",
  unknown_prescribed_load_basis: "The prescribed load basis is unknown.",
  unsupported_bodyweight_total_target: "The prescribed total-mass target cannot be compared safely.",
  missing_actual_load: "No actual load was recorded.",
  unknown_actual_load_basis: "The actual load basis could not be resolved.",
  actual_load_includes_bodyweight: "The actual load includes bodyweight, so the added plate is unknown.",
  time_based_load: "This is a time-based movement; load is not the target.",
  missing_prescribed_reps: "No valid repetition target was recorded.",
  missing_actual_reps: "No actual repetitions were recorded.",
  missing_prescribed_rir: "No RIR target was recorded.",
  missing_actual_rir: "No actual RIR was recorded.",
  ambiguous_set_role: "The set role is unknown, so the top-set/back-off target cannot be chosen.",
  unknown_set_role: "The set role does not match this item's set groups.",
  non_rir_effort_model: "This item is not RIR-scored.",
  ambiguous_attribution: "The exercise appears more than once and the set has no plan-item identity.",
  mismatched_exercise: "The stored plan-item identity names a different exercise.",
  stale_identity: "The stored plan-item identity is not present in this plan.",
  invalid_identity: "The stored plan-item identity is not a number.",
  unresolved_identity: "The stored plan-item identity could not be resolved.",
  added_in_final_plan: "This set belongs to an exercise added during the workout.",
  removed_from_final_plan: "This set belongs to an exercise removed from the final plan.",
  unattributed: "No plan-item identity was stored for this set.",
  ambiguous_warm_up_attribution: "Warm-up sets cannot be split across repeated exercise occurrences.",
};

var ADHERENCE_STATUS_TEXT = {
  within: "within target",
  below: "below target",
  above: "above target",
  at_target: "at target",
  unavailable: "unavailable",
  missing: "missing",
  under: "under",
  complete: "complete",
  over: "over prescription",
};

function adherenceReason(code) {
  if (!code) return "Unknown limitation.";
  return ADHERENCE_REASON_TEXT[code] || String(code).replace(/_/g, " ");
}

function adherencePct(value) {
  if (value == null || !isFinite(Number(value))) return "—";
  var pct = Math.round(Number(value) * 1000) / 10;
  return (Number.isInteger(pct) ? String(pct) : pct.toFixed(1)) + "%";
}

function adherenceRatio(metric) {
  if (!metric) return "—";
  var numerator = metric.numerator == null ? 0 : metric.numerator;
  var denominator = metric.denominator == null ? 0 : metric.denominator;
  return numerator + " / " + denominator + " (" + adherencePct(metric.ratio) + ")";
}

function adherenceShortRatio(metric) {
  if (!metric) return "—";
  return (metric.numerator == null ? 0 : metric.numerator) + "/" +
    (metric.denominator == null ? 0 : metric.denominator);
}

function adherenceSigned(value, digits, unit) {
  if (value == null || value === "" || !isFinite(Number(value))) return "—";
  var n = Number(value);
  var text = fmt(n, digits == null ? 1 : digits);
  return (n > 0 ? "+" : "") + text + (unit ? " " + unit : "");
}

function adherenceStatus(status) {
  var label = ADHERENCE_STATUS_TEXT[status] || String(status || "unavailable");
  var tone = (status === "above" || status === "below" || status === "under" ||
    status === "missing" || status === "over") ? " warn" : "";
  return "<span class='badge" + tone + "'>" + esc(label) + "</span>";
}

function adherenceFact(label, value) {
  return "<div><dt>" + esc(label) + "</dt><dd>" + value + "</dd></div>";
}

function adherenceRange(low, high, unit) {
  if (low == null || high == null) return "—";
  var text = low === high ? String(low) : low + "–" + high;
  return text + (unit ? " " + unit : "");
}

function adherenceRepsCell(row) {
  var unit = row.reps_unit === "seconds" ? "s" : "reps";
  var target = adherenceRange(row.reps_target_low, row.reps_target_high);
  var actual = row.reps_actual == null ? "—" : String(row.reps_actual) +
    (row.reps_unit === "seconds" ? " s" : "");
  return "<strong>" + esc(actual) + "</strong> <span class='muted'>vs " + esc(target) +
    " " + esc(unit) + "</span><br>" + adherenceStatus(row.reps_status);
}

function adherenceLoadCell(row) {
  var target = row.load_target_kg == null ? "—" : fmt(row.load_target_kg, 1) + " kg";
  var actual = row.load_actual_external_kg == null
    ? "—" : fmt(row.load_actual_external_kg, 1) + " kg";
  var deviation = row.load_deviation_kg == null
    ? "" : " · &Delta; " + adherenceSigned(row.load_deviation_kg, 1, "kg") +
      (row.load_deviation_pct == null ? "" : " (" + adherenceSigned(row.load_deviation_pct, 1, "%") + ")");
  return "<strong>" + esc(actual) + "</strong> <span class='muted'>vs " + esc(target) +
    deviation + "</span><br>" + adherenceStatus(row.load_status);
}

function adherenceRirCell(row) {
  var target = row.rir_target == null ? "—" : String(row.rir_target);
  var actual = row.rir_actual == null ? "—" : String(row.rir_actual);
  var deviation = row.rir_deviation == null
    ? "" : " · &Delta; " + adherenceSigned(row.rir_deviation, 0, "");
  return "<strong>" + esc(actual) + "</strong> <span class='muted'>vs " + esc(target) +
    deviation + "</span><br>" + adherenceStatus(row.rir_status);
}

function adherenceLimitationText(row) {
  var parts = [];
  if (row.extra) parts.push("extra set; not counted in target attainment");
  (row.limitations || []).forEach(function (code) {
    var text = adherenceReason(code);
    if (parts.indexOf(text) < 0) parts.push(text);
  });
  return parts.join(" · ");
}

function adherenceTargetTable(view) {
  var reps = view.reps || {};
  var load = view.load || {};
  var rir = view.rir || {};
  return "<div class='table-scroll adherence-targets'><table aria-label='Target attainment " +
    esc(view.view) + "'><thead><tr><th scope='col'>Target</th><th scope='col'>Attained</th>" +
    "<th scope='col'>Evaluated</th><th scope='col'>Breakdown</th></tr></thead><tbody>" +
    "<tr><th scope='row'>Repetitions</th><td>" + adherenceRatio(reps.attainment) + "</td><td>" +
    (reps.evaluated_sets == null ? 0 : reps.evaluated_sets) + "</td><td>" +
    "within " + (reps.within_target || 0) + " · below " + (reps.below_target || 0) +
    " · above " + (reps.above_target || 0) +
    ((reps.unavailable_sets || 0) ? " · unavailable " + reps.unavailable_sets : "") +
    "</td></tr>" +
    "<tr><th scope='row'>Load</th><td>" + adherenceRatio(load.attainment) + "</td><td>" +
    (load.evaluated_sets == null ? 0 : load.evaluated_sets) + "</td><td>" +
    "at " + (load.at_target || 0) + " · below " + (load.below_target || 0) +
    " · above " + (load.above_target || 0) +
    ((load.unavailable_sets || 0) ? " · unavailable " + load.unavailable_sets : "") +
    (load.mean_absolute_deviation_kg == null ? "" :
      " · mean |&Delta;| " + fmt(load.mean_absolute_deviation_kg, 1) + " kg") +
    "</td></tr>" +
    "<tr><th scope='row'>RIR</th><td>" + adherenceRatio(rir.attainment) + "</td><td>" +
    (rir.evaluated_sets == null ? 0 : rir.evaluated_sets) + "</td><td>" +
    "at " + (rir.at_target || 0) + " · above " + (rir.above_target || 0) +
    " · below " + (rir.below_target || 0) +
    ((rir.unavailable_sets || 0) ? " · unavailable " + rir.unavailable_sets : "") +
    (rir.mean_deviation == null ? "" :
      " · mean &Delta; " + adherenceSigned(rir.mean_deviation, 1, "RIR")) +
    "</td></tr></tbody></table></div>";
}

function adherenceUnmatchedTable(rows) {
  if (!rows || !rows.length) {
    return "<p class='muted'>No unmatched working sets.</p>";
  }
  return "<div class='table-scroll'><table class='adherence-unmatched-table' " +
    "aria-label='Unmatched actual sets'><thead><tr><th scope='col'>Set</th>" +
    "<th scope='col'>Exercise</th><th scope='col'>Reps</th><th scope='col'>Load kg</th>" +
    "<th scope='col'>RIR</th><th scope='col'>Reason</th></tr></thead><tbody>" +
    rows.map(function (row) {
      return "<tr><td>" + (row.set_index == null ? "—" : row.set_index) + "</td><td>" +
        esc(row.exercise_id) + "</td><td>" + (row.reps == null ? "—" : row.reps) +
        "</td><td>" + (row.load_kg == null ? "—" : row.load_kg) + "</td><td>" +
        (row.rir == null ? "—" : row.rir) + "</td><td>" + esc(adherenceReason(row.reason)) +
        "</td></tr>";
    }).join("") + "</tbody></table></div>";
}

function adherenceViewQuality(quality) {
  quality = quality || {};
  var items = [];
  items.push("Unmatched working sets: " + (quality.unmatched_sets || 0));
  if (quality.ambiguous_attribution) {
    items.push("Ambiguous attribution: " + quality.ambiguous_attribution);
  }
  if (quality.mismatched_attribution) {
    items.push("Mismatched plan-item identity: " + quality.mismatched_attribution);
  }
  if (quality.stale_attribution) {
    items.push("Stale plan-item identity: " + quality.stale_attribution);
  }
  if (quality.added_exercise_sets) {
    items.push("Sets for exercises added in the final plan: " + quality.added_exercise_sets);
  }
  if (quality.removed_exercise_sets) {
    items.push("Sets for exercises removed from the final plan: " + quality.removed_exercise_sets);
  }
  if (quality.unattributable_items) {
    items.push("Items with unavailable attribution: " + quality.unattributable_items);
  }
  (quality.unavailable_metrics || []).forEach(function (code) {
    var text = adherenceReason(code);
    if (items.indexOf("Unavailable: " + text) < 0) items.push("Unavailable: " + text);
  });
  return "<details class='adherence-quality'><summary>Unmatched work and data quality</summary>" +
    "<ul class='list'>" + items.map(function (item) {
      return "<li>" + esc(item) + "</li>";
    }).join("") + "</ul>" + adherenceUnmatchedTable(quality.unmatched) + "</details>";
}

function adherenceExercise(exercise) {
  var name = exercise.exercise_name || exercise.exercise_id || "Unknown exercise";
  var summary = "<summary><strong>" + esc(name) + "</strong> " +
    adherenceStatus(exercise.status) + " <span class='muted'>" +
    (exercise.matched_sets || 0) + "/" + (exercise.prescribed_sets || 0) + " sets filled" +
    " · reps " + adherenceShortRatio(exercise.reps && exercise.reps.attainment) +
    " · load " + adherenceShortRatio(exercise.load && exercise.load.attainment) +
    " · RIR " + adherenceShortRatio(exercise.rir && exercise.rir.attainment) +
    "</span></summary>";
  if (exercise.attributable === false) {
    return "<details class='adherence-exercise'>" + summary +
      "<p class='warnbox'>" + esc(adherenceReason(
        (exercise.limitations || [])[0] || "swapped_exercise"
      )) + "</p></details>";
  }
  var rows = (exercise.sets || []).map(function (row) {
    var setLabel = (row.set_index == null ? "—" : row.set_index) +
      (row.set_role ? " · " + esc(row.set_role).replace(/_/g, " ") : "") +
      (row.extra ? " <span class='badge warn'>extra</span>" : "");
    var limitations = adherenceLimitationText(row);
    return "<tr><td>" + setLabel + "</td><td>" + adherenceRepsCell(row) + "</td><td>" +
      adherenceLoadCell(row) + "</td><td>" + adherenceRirCell(row) + "</td><td class='muted'>" +
      (limitations ? esc(limitations) : "—") + "</td></tr>";
  }).join("");
  var facts = "<dl class='adherence-facts'>" +
    adherenceFact("Planned sets", exercise.planned_sets == null ? "—" : exercise.planned_sets) +
    adherenceFact("Performed sets", exercise.performed_sets == null ? "—" : exercise.performed_sets) +
    adherenceFact("Filled sets", exercise.matched_sets == null ? "—" : exercise.matched_sets) +
    adherenceFact("Missing sets", exercise.missing_sets == null ? "—" : exercise.missing_sets) +
    adherenceFact("Extra sets", exercise.extra_sets == null ? "—" : exercise.extra_sets) +
    adherenceFact("Set completion", adherenceRatio(exercise.set_completion)) +
    "</dl>";
  var limitations = (exercise.limitations || []).map(adherenceReason);
  var limitationBlock = limitations.length
    ? "<p class='adherence-note'>Unavailable: " + esc(limitations.join(" · ")) + "</p>" : "";
  var table = rows
    ? "<div class='table-scroll'><table class='adherence-set-table' aria-label='Per-set targets for " +
      esc(name) + "'><thead><tr><th scope='col'>Set</th><th scope='col'>Reps (actual vs target)</th>" +
      "<th scope='col'>Load (actual vs target)</th><th scope='col'>RIR (actual vs target)</th>" +
      "<th scope='col'>Notes</th></tr></thead><tbody>" + rows + "</tbody></table></div>"
    : "<p class='muted'>No attributed sets.</p>";
  return "<details class='adherence-exercise'>" + summary + facts + limitationBlock + table +
    "</details>";
}

function adherenceExercises(exercises) {
  if (!exercises || !exercises.length) {
    return "<p class='muted'>No prescribed exercises.</p>";
  }
  return "<details class='adherence-exercises'><summary>Exercise breakdown (" +
    exercises.length + ")</summary>" + exercises.map(adherenceExercise).join("") + "</details>";
}

function adherenceViewCard(view, title, badge) {
  var head = "<div class='adherence-view-head'><h4>" + esc(title) + "</h4>" + badge + "</div>";
  if (!view || view.status !== "available") {
    return "<article class='adherence-view'>" + head + "<p class='warnbox'>" +
      esc(adherenceReason(view && view.reason)) + "</p></article>";
  }
  var facts = "<dl class='adherence-facts'>" +
    adherenceFact("Prescribed sets", view.prescribed_sets == null ? "—" : view.prescribed_sets) +
    adherenceFact("Performed working sets", view.performed_sets == null ? "—" : view.performed_sets) +
    adherenceFact("Filled prescribed sets", view.matched_sets == null ? "—" : view.matched_sets) +
    adherenceFact("Missing prescribed sets", view.missing_sets == null ? "—" : view.missing_sets) +
    adherenceFact("Extra work", view.extra_sets == null ? "—" : view.extra_sets) +
    adherenceFact("Set completion", adherenceRatio(view.set_completion)) +
    "</dl>";
  var notes = "";
  if (view.unattributable_planned_sets) {
    notes += "<p class='warnbox'>" + view.unattributable_planned_sets +
      " planned set(s) could not be attributed to this prescription.</p>";
  }
  if (view.warm_up_sets_excluded) {
    notes += "<p class='adherence-note'>" + view.warm_up_sets_excluded +
      " warm-up set(s) excluded from working-set counts.</p>";
  }
  return "<article class='adherence-view'>" + head + facts + adherenceTargetTable(view) + notes +
    adherenceExercises(view.exercises) + adherenceViewQuality(view.quality) + "</article>";
}

function adherenceChanges(adherence) {
  var quality = adherence.quality || {};
  if (!quality.plan_modified) {
    return "<p class='muted'>Final plan was not modified during the workout.</p>";
  }
  var changes = adherence.changes || {};
  var items = [];
  (changes.swapped || []).forEach(function (row) {
    items.push("Swapped " + esc(row.from_exercise_id) + " → " + esc(row.to_exercise_id) +
      " (item " + row.plan_item_index + ")");
  });
  (changes.added || []).forEach(function (row) {
    items.push("Added " + esc(row.exercise_id) + " (" + row.sets + " set(s), item " +
      row.plan_item_index + ")" + (row.identity_reused ? " · legacy identity reuse" : ""));
  });
  (changes.removed || []).forEach(function (row) {
    items.push("Removed " + esc(row.exercise_id) + " (" + row.sets + " set(s), item " +
      row.plan_item_index + ")" + (row.identity_reused ? " · legacy identity reuse" : ""));
  });
  (changes.set_count_changed || []).forEach(function (row) {
    items.push("Set count for " + esc(row.exercise_id) + ": " + row.from_sets + " → " +
      row.to_sets + " (item " + row.plan_item_index + ")");
  });
  (changes.targets_changed || []).forEach(function (row) {
    items.push("Targets changed for " + esc(row.exercise_id) + ": " +
      esc((row.fields || []).join(", ")) + " (item " + row.plan_item_index + ")");
  });
  if (!items.length) {
    return "<p class='muted'>Plan marked modified; no item-level differences remain.</p>";
  }
  return "<ul class='list adherence-changes'>" + items.map(function (item) {
    return "<li>" + item + "</li>";
  }).join("") + "</ul>";
}

function adherenceGlobalQuality(quality) {
  quality = quality || {};
  var items = [];
  if (quality.warm_up_sets_excluded) {
    items.push("Warm-up sets excluded: " + quality.warm_up_sets_excluded);
  }
  if (quality.ambiguous_status_sets) {
    items.push("Sets with contradictory working/warm-up status: " + quality.ambiguous_status_sets);
  }
  if (quality.sets_without_rir) {
    items.push("Sets without RIR: " + quality.sets_without_rir);
  }
  if (quality.legacy_plan_without_order_index) {
    items.push("Legacy plan without stable item identities; attribution uses initial positions.");
  }
  (quality.unavailable_metrics || []).forEach(function (code) {
    var text = adherenceReason(code);
    if (items.indexOf("Unavailable: " + text) < 0) items.push("Unavailable: " + text);
  });
  if (!items.length) items.push("No known data-quality limitations.");
  return "<details class='adherence-quality'><summary>Data quality and coverage</summary>" +
    "<ul class='list'>" + items.map(function (item) {
      return "<li>" + esc(item) + "</li>";
    }).join("") + "</ul></details>";
}

function renderHistoryAdherence(adherence) {
  var head = "<div class='panel-head'><h3 id='history-adherence-title'>Prescription adherence</h3>" +
    "<span class='muted'>derived from completed working sets; no composite score</span></div>";
  var intro = "<p class='section-help adherence-intro'>Compares actual working sets with the " +
    "prescription issued at start and the final plan after in-workout edits. Set completion counts " +
    "filled prescribed slots; target attainment counts matching reps, load and RIR. A filled set " +
    "can still miss its target.</p>";
  if (!adherence) {
    return "<section class='adherence-section' aria-labelledby='history-adherence-title'>" + head +
      intro + "<p class='warnbox'>Adherence data is unavailable for this session.</p></section>";
  }
  if (adherence.status !== "available") {
    return "<section class='adherence-section' aria-labelledby='history-adherence-title'>" + head +
      intro + "<p class='warnbox'>Prescription adherence is unavailable: " +
      esc(adherenceReason(adherence.reason)) + "</p></section>";
  }
  var modified = Boolean(adherence.quality && adherence.quality.plan_modified);
  var originalBadge = "<span class='badge'>issued at start</span>";
  var finalBadge = modified
    ? "<span class='badge warn'>modified during workout</span>"
    : "<span class='badge'>unmodified</span>";
  return "<section class='adherence-section' aria-labelledby='history-adherence-title'>" + head +
    intro + "<h4>Prescription changes during the workout</h4>" + adherenceChanges(adherence) +
    "<div class='adherence-views'>" +
    adherenceViewCard(adherence.original, "Original prescription", originalBadge) +
    adherenceViewCard(adherence.final_plan, "Final modified prescription", finalBadge) +
    "</div>" + adherenceGlobalQuality(adherence.quality) +
    "<p class='adherence-note'>RIR deviation is actual minus target: positive means further from " +
    "failure than prescribed; negative means closer to failure.</p></section>";
}
