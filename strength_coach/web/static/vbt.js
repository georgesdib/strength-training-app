/* VBT target display and applicability helpers.
 *
 * The server owns calibration and comparison arithmetic. This module only formats target
 * provenance and renders the server's applicability/comparison result. A target is conditional
 * on rep count and RIR band; it is never presented as a load-specific target or a success score.
 */

var VBT_REASON_TEXT = {
  no_target: "No trustworthy VBT target was issued for this exercise.",
  no_vbt_target_issued: "No trustworthy VBT target was issued for this workout.",
  legacy_target: "This is a legacy target without a calibration band, rep count or calibration id.",
  target_missing: "No target is available.",
  unattributed_set: "The set has no stable prescription-item attribution.",
  exercise_mismatch: "The set's exercise does not match its prescription item.",
  missing_velocity: "No actual mean velocity was recorded.",
  invalid_velocity: "The actual mean velocity is not positive and finite.",
  warm_up: "Warm-up sets are not target comparisons.",
  rep_mismatch: "The actual rep count differs from the target's calibration rep count.",
  group_rep_mismatch: "The selected set group's rep count differs from the target's calibration rep count.",
  ambiguous_set_role: "Choose a set role so the target can be applied to the right set group.",
  actual_rir_missing: "Actual RIR is missing, so effort comparability cannot be established.",
  actual_rir_outside_band: "Actual RIR is outside the target's calibration band.",
  load_basis_unknown: "The prescribed load basis is unknown or not comparable.",
  time_based: "Time-based movements are not scored against a velocity target.",
};

function vbtReason(code) {
  if (!code) return "Unknown VBT limitation.";
  return VBT_REASON_TEXT[code] || String(code).replace(/_/g, " ");
}

function vbtTargetInline(target) {
  if (!target) return "No VBT target";
  var band = target.low_mps != null && target.high_mps != null
    ? " (" + fmt(target.low_mps, 2) + "–" + fmt(target.high_mps, 2) + " m/s)"
    : "";
  return fmt(target.target_mps, 2) + " m/s" + band + " @ " + target.rep_count + " reps";
}

function vbtTargetDetails(item) {
  var target = item && item.vbt;
  if (!target) {
    if (item && item.velocity_target != null) {
      return "<details class='vbt-details'><summary>VBT target " +
        fmt(item.velocity_target, 2) + " m/s (legacy)</summary>" +
        "<p class='muted'>Legacy target; calibration band, rep count, RIR band and " +
        "calibration id were not recorded. No historical metadata is reconstructed.</p></details>";
    }
    return "";
  }
  var scope = esc(target.scope || "unknown");
  if (target.family) scope += " · family " + esc(target.family);
  var rir = target.rir_low == null || target.rir_high == null
    ? "not recorded" : "RIR " + target.rir_low + "–" + target.rir_high;
  var sample = (target.n_sets == null ? "—" : target.n_sets) + " sets / " +
    (target.n_sessions == null ? "—" : target.n_sessions) + " sessions";
  return "<details class='vbt-details'><summary>VBT " + vbtTargetInline(target) +
    "</summary><p class='muted'>Band: " +
    (target.low_mps == null || target.high_mps == null
      ? "not recorded"
      : fmt(target.low_mps, 2) + "–" + fmt(target.high_mps, 2) + " m/s") +
    " · " + esc(rir) + " · " + scope + " · calibration n " + esc(sample) +
    " · method " + esc(target.method_version || "—") +
    (target.calibration_id ? " · id " + esc(target.calibration_id) : "") +
    (target.source ? " · source " + esc(target.source) : "") +
    "</p><p class='muted'>The target is conditional on rep count and RIR band; load is " +
    "context, not a target input.</p></details>";
}

function vbtGroupForRole(item, role) {
  var groups = (item && item.set_groups) || [];
  if (!groups.length) return null;
  if (!role) return groups.length === 1 ? groups[0] : null;
  return groups.find(function (group) { return String(group.role) === String(role); }) || null;
}

function vbtApplicability(item, role, reps, rir) {
  var target = item && item.vbt;
  if (!target) {
    if (item && item.velocity_target != null) {
      return {status: "legacy", reason: "legacy_target", target: null};
    }
    return {status: "unavailable", reason: "no_target", target: null};
  }
  var groups = item.set_groups || [];
  var group = vbtGroupForRole(item, role);
  if (groups.length && !group) {
    return {status: "not_applicable", reason: "ambiguous_set_role", target: target};
  }
  if (group && Number(group.reps_low) !== Number(target.rep_count)) {
    return {status: "not_applicable", reason: "group_rep_mismatch", target: target, group: group};
  }
  if (reps !== "" && reps != null && Number(reps) !== Number(target.rep_count)) {
    return {status: "not_applicable", reason: "rep_mismatch", target: target, group: group};
  }
  if (rir === "" || rir == null) {
    return {status: "effort_unknown", reason: "actual_rir_missing", target: target, group: group};
  }
  if (target.rir_low != null && target.rir_high != null &&
      (Number(rir) < Number(target.rir_low) || Number(rir) > Number(target.rir_high))) {
    return {status: "effort_outside_band", reason: "actual_rir_outside_band",
      target: target, group: group};
  }
  return {status: "applicable", reason: null, target: target, group: group};
}

function vbtApplicabilityHtml(item, role, reps, rir) {
  if (!item) return "";
  var result = vbtApplicability(item, role, reps, rir);
  if (!result.target) {
    return "<span class='muted'>" + esc(vbtReason(result.reason)) + "</span>";
  }
  var text = "VBT target <strong>" + esc(vbtTargetInline(result.target)) + "</strong>";
  if (result.group) {
    text += " · group " + esc(String(result.group.role || "").replace(/_/g, " "));
  }
  var basis = (result.target.scope || "unknown") +
    (result.target.family ? " (" + result.target.family + ")" : "") +
    (result.target.n_sets == null ? "" :
      " · " + result.target.n_sets + " sets/" + result.target.n_sessions + " sessions");
  text += " · " + esc(basis) + " · method " + esc(result.target.method_version || "—");
  if (result.status === "applicable") {
    return text + " · target applies to these reps; enter a velocity to compare.";
  }
  return text + " · <span class='muted'>" + esc(vbtReason(result.reason)) + "</span>";
}

function vbtFeedbackHtml(comparison) {
  if (!comparison) return "";
  var actual = comparison.actual_velocity_mps;
  var target = comparison.target_mps;
  if (actual == null && target == null) {
    return "<span class='muted'>No VBT target or actual velocity for this set.</span>";
  }
  if (actual == null) {
    return "<span class='muted'>VBT target " + fmt(target, 2) +
      " m/s; no actual mean velocity was recorded, so no comparison is made.</span>";
  }
  if (target == null) {
    return "<span class='muted'>Actual velocity " + fmt(actual, 2) +
      " m/s stored without a target comparison.</span>";
  }
  var text = "Target " + fmt(target, 2) + " m/s · actual " + fmt(actual, 2) +
    " m/s · Δ " + (comparison.delta_mps > 0 ? "+" : "") + fmt(comparison.delta_mps, 2) +
    " m/s" + (comparison.delta_pct == null ? "" :
      " (" + (comparison.delta_pct > 0 ? "+" : "") + fmt(comparison.delta_pct, 1) + "%)");
  if (comparison.within_calibration_band === true) text += " · within calibration band";
  else if (comparison.within_calibration_band === false) text += " · outside calibration band";
  else text += " · calibration band unavailable";
  if (comparison.comparable) {
    return "<span class='vbt-feedback-valid'>" + esc(text) + "</span>";
  }
  var reasons = (comparison.reasons || []).map(vbtReason).join(" · ");
  return "<span class='vbt-feedback-invalid'>" + esc(text) +
    (reasons ? " · not comparable: " + esc(reasons) : " · not comparable") + "</span>";
}

function vbtPrescriptionNote(note) {
  if (!note) return "";
  var withheld = (note.withheld || []).length
    ? " Withheld: " + note.withheld.join(", ") + "."
    : "";
  if (note.status === "available") {
    return "<p class='muted'><strong>VBT:</strong> " + (note.targets || 0) +
      " target(s) issued from stored velocity history." + esc(withheld) + "</p>";
  }
  var reason = note.reason || "no trustworthy target was available";
  return "<p class='muted'><strong>VBT:</strong> " + esc(reason) + "." +
    esc(withheld) + "</p>";
}

function vbtSigned(value, digits) {
  if (value == null) return "—";
  return (Number(value) > 0 ? "+" : "") + fmt(value, digits == null ? 2 : digits);
}

function vbtBandText(row) {
  if (row.within_calibration_band === true) return "within band";
  if (row.within_calibration_band === false) return "outside band";
  return "band unavailable";
}

function vbtSetNotes(row) {
  var parts = [];
  if (row.extra_set) parts.push("extra set");
  if (row.velocity_source === "override") parts.push("velocity override");
  if (row.target_source === "original_plan") parts.push("original-plan target");
  (row.reasons || []).forEach(function (reason) {
    var text = vbtReason(reason);
    if (parts.indexOf(text) < 0) parts.push(text);
  });
  return parts.join(" · ");
}

function vbtExerciseTargetLine(exercise) {
  var targets = exercise.targets || [];
  if (!targets.length) return "<span class='muted'>No VBT target for this exercise.</span>";
  return targets.map(function (target) {
    return "Target " + esc(vbtTargetInline(target)) +
      " · " + esc(target.scope || "unknown") +
      (target.family ? " (" + esc(target.family) + ")" : "") +
      " · n " + (target.n_sets == null ? "—" : target.n_sets) + " sets/" +
      (target.n_sessions == null ? "—" : target.n_sessions) + " sessions" +
      " · method " + esc(target.method_version || "—") +
      (target.calibration_id ? " · id " + esc(target.calibration_id) : "");
  }).join(" · ");
}

function vbtSectionHtml(vbt) {
  if (!vbt) return "";
  var head = "<div class='panel-head'><h3>VBT target comparison</h3>" +
    "<span class='muted'>historical target; no score or prescription change</span></div>";
  if (vbt.status !== "available") {
    return "<section class='vbt-section'>" + head +
      "<p class='warnbox'>" + esc(vbtReason(vbt.reason)) + "</p>" +
      "<p class='muted'>" + esc((vbt.quality || {}).logged_sets || 0) +
      " set(s) recorded; no target comparison was possible.</p></section>";
  }
  var quality = vbt.quality || {};
  var byExercise = {};
  (vbt.sets || []).forEach(function (row) {
    var id = String(row.exercise_id || "");
    if (!byExercise[id]) byExercise[id] = [];
    byExercise[id].push(row);
  });
  var summary = "<p class='muted'>" + (quality.comparable_sets || 0) + " comparable · " +
    (quality.excluded_sets || 0) + " excluded · " +
    (quality.target_sets || 0) + " target set(s). Target adherence is separate from " +
    "within-set velocity loss.</p>";
  var blocks = (vbt.exercises || []).map(function (exercise) {
    var rows = byExercise[String(exercise.exercise_id)] || [];
    var tableRows = rows.map(function (row) {
      var rir = (row.actual_rir == null ? "—" : row.actual_rir) +
        (row.target_rir_low == null ? "" :
          " / " + row.target_rir_low + "–" + row.target_rir_high);
      return "<tr><td>" + esc(row.set_index == null ? "—" : row.set_index) + "</td><td>" +
        esc(row.reps == null ? "—" : row.reps) + "</td><td>" +
        (row.load_kg == null ? "—" : fmt(row.load_kg, 1) + " kg") + "<br><span class='muted'>" +
        esc(row.load_basis || "—") + "</span></td><td>" + esc(rir) + "</td><td>" +
        (row.target_mps == null ? "—" : fmt(row.target_mps, 2) +
          (row.low_mps == null || row.high_mps == null ? "" :
            " <span class='muted'>(" + fmt(row.low_mps, 2) + "–" +
            fmt(row.high_mps, 2) + ")</span>")) + "</td><td>" +
        (row.actual_velocity_mps == null ? "—" : fmt(row.actual_velocity_mps, 2)) + "</td><td>" +
        vbtSigned(row.delta_mps, 2) + "</td><td>" +
        (row.delta_pct == null ? "—" : vbtSigned(row.delta_pct, 1) + "%") + "</td><td>" +
        esc(vbtBandText(row)) + "</td><td>" +
        (row.comparable ? "comparable" : "excluded") + "</td><td class='muted'>" +
        esc(vbtSetNotes(row) || "—") + "</td></tr>";
    }).join("");
    var table = rows.length
      ? "<div class='table-scroll'><table class='vbt-analysis-table' aria-label='VBT target comparison for " +
        esc(exercise.exercise_name || exercise.exercise_id) + "'><thead><tr><th scope='col'>Set</th>" +
        "<th scope='col'>Reps</th><th scope='col'>Load</th><th scope='col'>RIR actual / target</th>" +
        "<th scope='col'>Target m/s</th><th scope='col'>Actual m/s</th><th scope='col'>Δ m/s</th>" +
        "<th scope='col'>Δ %</th><th scope='col'>Band</th><th scope='col'>Comparable</th>" +
        "<th scope='col'>Notes</th></tr></thead><tbody>" + tableRows +
        "</tbody></table></div>"
      : "<p class='muted'>No attributed sets.</p>";
    return "<details class='vbt-analysis-exercise'><summary><strong>" +
      esc(exercise.exercise_name || exercise.exercise_id) + "</strong> " +
      (exercise.comparable_sets || 0) + "/" + (exercise.sets || 0) + " comparable · median Δ " +
      vbtSigned(exercise.median_signed_delta_mps, 2) + " m/s · mean |Δ| " +
      (exercise.mean_absolute_error_mps == null ? "—" : fmt(exercise.mean_absolute_error_mps, 2)) +
      " m/s</summary><p class='muted'>" + vbtExerciseTargetLine(exercise) +
      (exercise.mean_actual_rir == null ? "" :
        " · mean actual RIR " + fmt(exercise.mean_actual_rir, 1) +
        " / prescribed " + fmt(exercise.mean_prescribed_rir, 1)) +
      "</p>" + table + "</details>";
  }).join("");
  var reasons = quality.reasons || {};
  var reasonRows = Object.keys(reasons).sort().map(function (code) {
    return "<li>" + esc(vbtReason(code)) + ": " + reasons[code] + "</li>";
  }).join("");
  var qualityBlock = "<details class='vbt-quality'><summary>VBT data quality (" +
    (quality.logged_sets || 0) + " logged sets)</summary><ul class='list'>" +
    "<li>Working sets: " + (quality.working_sets || 0) + "</li>" +
    "<li>Sets with velocity: " + (quality.sets_with_velocity || 0) + "</li>" +
    "<li>Comparable target sets: " + (quality.comparable_sets || 0) + "</li>" +
    "<li>Excluded target sets: " + (quality.excluded_sets || 0) + "</li>" +
    "<li>Extra sets: " + (quality.extra_sets || 0) + "</li>" +
    (reasonRows ? "<li>Exclusion reasons:<ul>" + reasonRows + "</ul></li>" : "") +
    "</ul></details>";
  return "<section class='vbt-section'>" + head + summary +
    (blocks || "<p class='empty'>No exercise-level VBT observations.</p>") +
    qualityBlock + "</section>";
}
