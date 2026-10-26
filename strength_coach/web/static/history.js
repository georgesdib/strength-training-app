/* Session history: read all sessions and append audited corrections. */
var historyOffset = 0;
var historyTotal = 0;
var historyDetail = null;
var historyLimit = 25;

// Read-only fact for the details sheet; a missing value is said out loud, never left blank.
function fact(label, value) {
  var text = value == null || value === "" ? "not recorded" : String(value);
  return "<div><dt>" + esc(label) + "</dt><dd>" + esc(text) + "</dd></div>";
}

function historyParam(name) {
  var el = document.getElementById(name);
  return el && el.value ? encodeURIComponent(el.value) : "";
}

async function loadHistory() {
  var target = document.getElementById("history-list");
  if (!target) return;
  target.innerHTML = "<p class='empty'>Loading history…</p>";
  var query = "?limit=" + historyLimit + "&offset=" + historyOffset;
  var start = historyParam("history-start");
  var end = historyParam("history-end");
  if (start) query += "&start=" + start;
  if (end) query += "&end=" + end;
  try {
    var data = await api("/api/history" + query);
    historyTotal = data.total;
    var rows = (data.sessions || []).map(function (s) {
      var edited = s.edited_at ? '<span class="badge warn">edited</span>' : "";
      var review = s.needs_review ? '<span class="badge bad">re-review</span>' : "";
      var voided = s.voided ? '<span class="badge bad">voided</span>' : "";
      return "<tr><td>" + esc(s.occurred_on) + "</td><td>" + esc(s.session_id) +
        "</td><td>" + esc(s.session_type) + "</td><td>" + s.working_set_count + "/" + s.set_count +
        "</td><td>" + esc((s.main_lifts || []).join(", ")) + "</td><td>" +
        (s.marks ? '<span class="badge">' + s.marks + "</span>" : '<span class="badge warn">none</span>') +
        " " + edited + " " + review + " " + voided + "</td><td>" +
        '<button class="ghost" type="button" data-history-details="' + esc(s.session_id) + '">Details</button> ' +
        '<button class="ghost" type="button" data-history-edit="' + esc(s.session_id) + '">Edit</button> ' +
        '<button class="ghost" type="button" data-history-review="' + esc(s.session_id) + '">Review</button> ' +
        '<button class="ghost" type="button" data-history-void="' + esc(s.session_id) + '">' + (s.voided ? "Unvoid" : "Void") + "</button>" +
        "</td></tr>";
    }).join("");
    target.innerHTML = rows
      ? "<table><thead><tr><th>Date</th><th>Session</th><th>Type</th><th>Sets</th>" +
        "<th>Main lifts</th><th>Marks</th><th></th></tr></thead><tbody>" + rows + "</tbody></table>"
      : "<p class='empty'>No sessions in this range.</p>";
    document.getElementById("history-total").textContent =
      historyTotal + " session(s) · showing " + (data.sessions || []).length;
    document.querySelectorAll("[data-history-details]").forEach(function (button) {
      button.addEventListener("click", function () { openHistoryDetails(button.dataset.historyDetails); });
    });
    document.querySelectorAll("[data-history-edit]").forEach(function (button) {
      button.addEventListener("click", function () { openHistoryEdit(button.dataset.historyEdit); });
    });
    document.querySelectorAll("[data-history-review]").forEach(function (button) {
      button.addEventListener("click", function () { openReview(button.dataset.historyReview); });
    });
    document.querySelectorAll("[data-history-void]").forEach(function (button) {
      button.addEventListener("click", function () {
        var id = button.dataset.historyVoid;
        var voided = button.textContent.trim() === "Unvoid";
        var reason = voided ? null : prompt("Reason for voiding this session (optional):");
        if (!voided && reason === null) return;
        api("/api/history/" + encodeURIComponent(id) + "/void", {
          method: "POST", body: JSON.stringify({ unvoid: voided, reason: reason })
        }).then(function (data) {
          loadHistory();
          if (historyDetail && historyDetail.session_id === id) openHistoryEdit(id);
        }).catch(function (error) { alert(error.message); });
      });
    });
  } catch (error) {
    target.innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  }
}

function historyRepValues(item) {
  var values = {};
  ((item && item.device_reps) || []).forEach(function (rep) {
    values[rep.rep_index] = rep.velocity_mps;
  });
  ((item && item.vbt_reps) || []).forEach(function (rep) {
    values[rep.rep_index] = rep.velocity_mps;
  });
  return Object.keys(values).sort(function (a, b) { return Number(a) - Number(b); })
    .map(function (index) {
      return { rep_index: Number(index), velocity_mps: values[index] };
    });
}

function historySetRow(item, index) {
  var reps = historyRepValues(item);
  var repRows = reps.map(function (rep, repIndex) {
    return '<label class="rep-field">Rep ' + (repIndex + 1) +
      ' <input type="number" step="0.01" min="0" data-h-rep value="' +
      (rep.velocity_mps == null ? "" : rep.velocity_mps) + '"></label>';
  }).join("");
  var device = item && item.velocity_mps != null ? " (device " + item.velocity_mps + ")" : "";
  return '<div class="history-set" data-history-set data-set-id="' +
    (item && item.set_id ? item.set_id : "") + '" data-original-velocity="' +
    (item && item.velocity_mps != null ? item.velocity_mps : "") + '">' +
    '<div class="history-set-head"><strong>Set ' + (index + 1) + '</strong>' +
    '<input list="exercise-options" data-h-exercise value="' +
    esc(item ? item.exercise_id : "") + '"></div>' +
    '<div class="history-set-grid">' +
    '<label>Load kg <input type="number" step="0.5" data-h-load value="' +
    (item && item.load_kg != null ? item.load_kg : "") + '"></label>' +
    '<label>Reps <input type="number" min="0" data-h-reps value="' +
    (item && item.reps != null ? item.reps : "") + '"></label>' +
    '<label>RIR <input type="number" min="0" max="6" data-h-rir value="' +
    (item && item.rir != null ? item.rir : "") + '"></label>' +
    '<label>VBT m/s override' + device + ' <input type="number" step="0.01" min="0" data-h-vbt value="' +
    (item && item.vbt_mean != null ? item.vbt_mean : "") + '"></label>' +
    '</div>' +
    '<div class="history-set-actions">' +
    '<button class="ghost" type="button" data-h-show-reps>Show reps</button>' +
    '<button class="ghost" type="button" data-h-remove>Remove set</button></div>' +
    '<div class="history-reps" hidden><div class="history-rep-grid">' + repRows +
    '</div><button class="ghost" type="button" data-h-add-rep>Add rep</button></div></div>';
}

function wireHistorySetButtons() {
  document.querySelectorAll("[data-h-remove]").forEach(function (button) {
    button.onclick = function () { button.closest("[data-history-set]").remove(); };
  });
  document.querySelectorAll("[data-h-show-reps]").forEach(function (button) {
    button.onclick = function () {
      var editor = button.closest("[data-history-set]").querySelector(".history-reps");
      editor.hidden = !editor.hidden;
      button.textContent = editor.hidden ? "Show reps" : "Hide reps";
    };
  });
  document.querySelectorAll("[data-h-add-rep]").forEach(function (button) {
    button.onclick = function () {
      var grid = button.closest("[data-history-set]").querySelector(".history-rep-grid");
      var index = grid.querySelectorAll("[data-h-rep]").length + 1;
      grid.insertAdjacentHTML("beforeend",
        '<label class="rep-field">Rep ' + index +
        ' <input type="number" step="0.01" min="0" data-h-rep value=""></label>');
    };
  });
}

async function openHistoryEdit(sessionId) {
  var panel = document.getElementById("history-edit-panel");
  panel.hidden = false;
  document.getElementById("history-edit-msg").textContent = "Loading…";
  try {
    var data = await api("/api/history/" + encodeURIComponent(sessionId));
    historyDetail = data;
    document.getElementById("history-edit-title").textContent =
      "Edit " + data.occurred_on + " · " + data.session_type;
    document.getElementById("history-edit-sets").innerHTML =
      (data.sets || []).map(historySetRow).join("") ||
      "<p class='muted'>No current sets.</p>";
    wireHistorySetButtons();
    // Backfilled values live in session_feedback for imported sessions; show them rather than
    // an empty box that would overwrite them with a blank on the next save.
    var feedback = data.feedback || {};
    document.getElementById("history-edit-srpe").value =
      data.session_rpe != null ? data.session_rpe
        : (feedback.srpe == null ? "" : feedback.srpe);
    document.getElementById("history-edit-duration").value =
      data.duration_min != null ? data.duration_min
        : (feedback.duration_min == null ? "" : feedback.duration_min);
    renderHistoryVbt(data);
    document.getElementById("history-edit-notes").value =
      (data.feedback && data.feedback.note) || "";
    document.getElementById("history-edit-reason").value = "";
    document.getElementById("history-edit-msg").textContent = "";
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    panel.hidden = true;
    alert(error.message);
  }
}

function collectHistorySets() {
  return Array.from(document.querySelectorAll("[data-history-set]")).map(function (row) {
    var reps = Array.from(row.querySelectorAll("[data-h-rep]")).map(function (input, index) {
      return input.value === "" ? null : { rep_index: index + 1, velocity_mps: input.value };
    }).filter(function (rep) { return rep !== null; });
    return {
      set_id: row.dataset.setId ? Number(row.dataset.setId) : undefined,
      exercise_id: row.querySelector("[data-h-exercise]").value.trim(),
      load_kg: row.querySelector("[data-h-load]").value || null,
      reps: row.querySelector("[data-h-reps]").value || null,
      rir: row.querySelector("[data-h-rir]").value || null,
      velocity_mps: row.dataset.originalVelocity || null,
      vbt_mean: row.querySelector("[data-h-vbt]").value || null,
      vbt_reps: reps
    };
  });
}

async function saveHistoryEdit() {
  if (!historyDetail) return;
  document.getElementById("history-edit-msg").textContent = "Saving correction…";
  try {
    var data = await api("/api/history/" + encodeURIComponent(historyDetail.session_id) + "/edit", {
      method: "POST",
      body: JSON.stringify({
        sets: collectHistorySets(),
        forms: collectHistoryForms(),
        session_rpe: document.getElementById("history-edit-srpe").value || null,
        duration_min: document.getElementById("history-edit-duration").value || null,
        notes: document.getElementById("history-edit-notes").value || null,
        reason: document.getElementById("history-edit-reason").value || null
      })
    });
    document.getElementById("history-edit-msg").textContent =
      "Correction saved" + ((data.warnings || []).length ? ": " + data.warnings.join("; ") : ".");
    notify("Session correction saved.");
    await loadHistory();
    await openHistoryEdit(historyDetail.session_id);
  } catch (error) {
    document.getElementById("history-edit-msg").innerHTML = "<span class='warnbox'>" + esc(error.message) + "</span>";
  }
}

document.getElementById("history-refresh").addEventListener("click", function () {
  historyOffset = 0; loadHistory();
});
document.getElementById("history-prev").addEventListener("click", function () {
  historyOffset = Math.max(0, historyOffset - historyLimit); loadHistory();
});
document.getElementById("history-next").addEventListener("click", function () {
  if (historyOffset + historyLimit < historyTotal) { historyOffset += historyLimit; loadHistory(); }
});
document.getElementById("history-add-set").addEventListener("click", function () {
  var body = document.querySelector("#history-edit-sets tbody");
  if (!body) return;
  body.insertAdjacentHTML("beforeend", historySetRow(null));
  wireHistoryRemoveButtons();
});
document.getElementById("history-save").addEventListener("click", saveHistoryEdit);
document.getElementById("history-vbt-save").addEventListener("click", saveHistoryVbt);
document.getElementById("history-cancel").addEventListener("click", function () {
  document.getElementById("history-edit-panel").hidden = true;
});

function renderHistoryVbt(data) {
  var rows = (data.sets || []).map(function (item) {
    var reps = (item.vbt_reps && item.vbt_reps.length
      ? item.vbt_reps
      : (item.device_reps || [])).map(function (rep) { return rep.velocity_mps; }).join(", ");
    return '<tr data-vbt-set data-set-id="' + item.set_id + '"><td>' + esc(item.exercise_id) +
      '</td><td><input type="number" step="0.01" data-vbt-mean value="' +
      (item.vbt_mean == null ? "" : item.vbt_mean) + '"></td><td><input data-vbt-reps value="' +
      esc(reps) + '" placeholder="e.g. 0.74, 0.72, 0.68"></td></tr>';
  }).join("");
  document.getElementById("history-vbt").innerHTML = rows
    ? "<table><thead><tr><th>Set</th><th>Mean m/s</th><th>Rep velocities</th></tr></thead><tbody>" +
      rows + "</tbody></table>"
    : "<p class='muted'>No current sets.</p>";
  document.getElementById("history-vbt-msg").textContent = "";
}

async function saveHistoryVbt() {
  if (!historyDetail) return;
  var entries = Array.from(document.querySelectorAll("[data-vbt-set]")).map(function (row) {
    var text = row.querySelector("[data-vbt-reps]").value.trim();
    var reps = text ? text.split(",").map(function (value, index) {
      return { rep_index: index + 1, velocity_mps: value.trim() };
    }).filter(function (rep) { return rep.velocity_mps !== ""; }) : [];
    return {
      set_id: Number(row.dataset.setId),
      mean: row.querySelector("[data-vbt-mean]").value || null,
      reps: reps
    };
  });
  document.getElementById("history-vbt-msg").textContent = "Saving VBT overrides…";
  try {
    var data = await api("/api/history/" + encodeURIComponent(historyDetail.session_id) + "/vbt", {
      method: "POST",
      body: JSON.stringify({ sets: entries, reason: "VBT override" })
    });
    historyDetail = data.session;
    renderHistoryVbt(data.session);
    document.getElementById("history-vbt-msg").textContent = "VBT overrides saved.";
    loadHistory();
  } catch (error) {
    document.getElementById("history-vbt-msg").innerHTML = "<span class='warnbox'>" + esc(error.message) + "</span>";
  }
}

function openHistoryDetails(sessionId) {
  var panel = document.getElementById("history-detail-panel");
  panel.hidden = false;
  document.getElementById("history-details").innerHTML = "<p class='empty'>Loading details…</p>";
  api("/api/history/" + encodeURIComponent(sessionId)).then(function (data) {
    document.getElementById("history-detail-title").textContent =
      "Session details · " + data.occurred_on + " · " + data.session_type;
    var feedback = data.feedback || {};
    // One view, grouped in performed order: exercise heading, its sets, then optional rep
    // detail. The set list keeps the log order (raw_id) instead of grouping by exercise.
    var order = [];
    var byExercise = {};
    (data.sets || []).forEach(function (item) {
      if (!byExercise[item.exercise_id]) {
        byExercise[item.exercise_id] = [];
        order.push(item.exercise_id);
      }
      byExercise[item.exercise_id].push(item);
    });
    var blocks = order.map(function (exerciseId) {
      var group = byExercise[exerciseId];
      var setRows = group.map(function (item, index) {
        var units = item.reps_unit === "seconds" ? " s" : "";
        return "<tr><td>" + (index + 1) + "</td><td>" +
          (item.load_kg == null ? "—" : item.load_kg) + "</td><td>" +
          (item.reps == null ? "—" : item.reps + units) + "</td><td>" +
          (item.rir == null ? "—" : item.rir) + "</td><td>" +
          esc((Array.isArray(item.flags) ? item.flags : []).join(", ") || "—") + "</td><td>" +
          (item.velocity_mps == null ? "—" : item.velocity_mps) + "</td><td>" +
          (item.vbt_mean == null ? "—" : item.vbt_mean) + "</td></tr>";
      }).join("");
      var repTables = group.map(function (item, index) {
        var reps = (item.vbt_reps || []).length ? item.vbt_reps : (item.device_reps || []);
        if (!reps.length) return "";
        return "<p class='muted'>Set " + (index + 1) + " · " + reps.length + " rep(s)</p>" +
          "<table><thead><tr><th>Rep</th><th>Velocity m/s</th></tr></thead><tbody>" +
          reps.map(function (rep) {
            return "<tr><td>" + rep.rep_index + "</td><td>" + rep.velocity_mps + "</td></tr>";
          }).join("") + "</tbody></table>";
      }).join("");
      return "<section class='history-exercise'><h3>" + esc(exerciseId) + "</h3>" +
        "<p class='muted'>" + group.length + " set(s)</p>" +
        "<div class='table-scroll'><table><thead><tr><th>#</th><th>Load kg</th><th>Reps</th>" +
        "<th>RIR</th><th>Flags</th><th>Device VBT</th><th>VBT override</th></tr></thead><tbody>" +
        setRows + "</tbody></table></div>" +
        (repTables ? "<details class='history-reps'><summary>Rep details (velocity)</summary>" +
          repTables + "</details>" : "") +
        "</section>";
    }).join("");
    var facts =
      fact("Date", data.occurred_on) +
      fact("Session type", data.session_type) +
      fact("Status", (data.voided
        ? "voided" + (data.void_reason ? " · " + data.void_reason : "")
        : "active") + (data.needs_review ? " · needs re-review" : "")) +
      fact("Source", data.source) +
      fact("Session RPE", data.session_rpe != null
        ? data.session_rpe
        : (feedback.srpe == null ? null : feedback.srpe + " (backfilled)")) +
      fact("Duration", data.duration_min != null
        ? data.duration_min + " min (" + (data.duration_basis || "unknown") + ")"
        : (feedback.duration_min != null
          ? feedback.duration_min + " min (backfilled)"
          : (data.duration_basis === "unavailable"
            ? "not recorded (imported session: no timestamps)" : "not recorded"))) +
      fact("Sets (working / total)", (data.working_set_count == null ? "—" : data.working_set_count) +
        " / " + (data.set_count == null ? "—" : data.set_count)) +
      fact("Exercises", data.exercise_count) +
      fact("Tonnage", data.tonnage_kg == null ? null : Math.round(data.tonnage_kg) + " kg") +
      fact("Main lifts", (data.main_lifts || []).join(", ")) +
      fact("Flags", (Array.isArray(data.flags) ? data.flags : []).join(", ")) +
      fact("Prescription", data.prescription_id) +
      fact("Workout", data.workout_id) +
      fact("VBT overrides", data.vbt_override_count) +
      fact("Created", data.created_at) +
      fact("Updated", data.updated_at) +
      fact("Edited", data.edited_at);
    var forms = (data.forms || []).map(function (item) {
      return "<tr><td>" + esc(item.exercise_id) + "</td><td>" + item.rating +
        "</td><td>" + esc(item.note || "") + "</td></tr>";
    }).join("");
    document.getElementById("history-details").innerHTML =
      "<dl class='history-facts'>" + facts + "</dl>" +
      (feedback.note ? "<p class='muted'>Note: " + esc(feedback.note) + "</p>" : "") +
      (forms ? "<h3>Form ratings</h3><table><thead><tr><th>Exercise</th><th>Rating (1–5)</th>" +
        "<th>Note</th></tr></thead><tbody>" + forms + "</tbody></table>" +
        "<p class='muted'>Optional self-assessment; rubric input only, never a load or set.</p>" : "") +
      "<h3>Exercises and sets</h3>" +
      (blocks || "<p class='muted'>No sets.</p>");
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }).catch(function (error) {
    document.getElementById("history-details").innerHTML =
      "<p class='warnbox'>" + esc(error.message) + "</p>";
  });
}

document.getElementById("history-details-close").addEventListener("click", function () {
  document.getElementById("history-detail-panel").hidden = true;
});
