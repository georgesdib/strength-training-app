/* Live workout mode: start, manual sets, end.
 * Kept out of app.js so the workout lifecycle can evolve without touching the
 * prescription renderer. All reads/writes go through the same JSON API. */

const WORKOUT_REQUIRED = ["sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration"];
const WORKOUT_OPTIONAL = ["hrv_ms", "rhr_bpm", "bodyweight_kg", "fat_pct", "wearable_score"];
const WORKOUT_LABELS = {
  sleep: "Sleep", energy: "Energy", mood: "Mood", soreness: "Soreness", stress: "Stress",
  nutrition: "Nutrition", hydration: "Hydration", hrv_ms: "HRV (ms)", rhr_bpm: "Resting HR",
  bodyweight_kg: "Bodyweight (kg)", fat_pct: "Body fat (%)", wearable_score: "Wearable (0-100)"
};
let workoutTimer = null;
let activeWorkoutId = null;

function workoutField(key, required) {
  var label = '<label>' + esc(WORKOUT_LABELS[key] || key);
  if (WORKOUT_OPTIONAL.includes(key)) {
    return label + '<input type="number" step="0.1" data-workout-field="' + key + '"' +
      (required ? ' required' : '') + '></label>';
  }
  var options = '<option value="">—</option>';
  [1, 2, 3, 4, 5].forEach(function (n) {
    options += '<option value="' + n + '">' + n + '</option>';
  });
  return label + '<select data-workout-field="' + key + '"' +
    (required ? ' required' : '') + '>' + options + '</select></label>';
}

function openWorkoutStart() {
  var plan = window.__lastPrescription;
  if (!plan) return;
  $("#workout-empty").hidden = true;
  $("#workout-active-panel").hidden = true;
  $("#workout-ended-panel").hidden = true;
  $("#workout-start-panel").hidden = false;
  $("#workout-start-summary").textContent =
    plan.for_date + " · " + (plan.session_type || "unknown");
  $("#workout-readiness-required").innerHTML =
    WORKOUT_REQUIRED.map(function (key) { return workoutField(key, true); }).join("");
  $("#workout-readiness-optional").innerHTML =
    WORKOUT_OPTIONAL.map(function (key) { return workoutField(key, false); }).join("");
  $("#workout-start-msg").textContent = "Loading readiness…";
  setView("workout");
  api("/api/readiness/" + encodeURIComponent(plan.for_date)).then(function (data) {
    document.querySelectorAll("[data-workout-field]").forEach(function (input) {
      input.value = data[input.dataset.workoutField] == null ? "" : data[input.dataset.workoutField];
    });
    $("#workout-readiness-note").value = data.note || "";
    $("#workout-start-msg").textContent = "";
  }).catch(function (error) {
    $("#workout-start-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + '</p>';
  });
}

function cancelWorkoutStart() {
  $("#workout-start-panel").hidden = true;
  $("#workout-empty").hidden = false;
  setView("prescribe");
}

function submitWorkoutStart(event) {
  event.preventDefault();
  var plan = window.__lastPrescription;
  if (!plan) {
    $("#workout-start-msg").textContent = "Build a prescription first.";
    return;
  }
  var readiness = {};
  WORKOUT_REQUIRED.concat(WORKOUT_OPTIONAL).forEach(function (key) {
    var input = document.querySelector('[data-workout-field="' + key + '"]');
    if (input && input.value !== "") readiness[key] = input.value;
  });
  var missing = WORKOUT_REQUIRED.filter(function (key) { return readiness[key] === undefined; });
  if (missing.length) {
    $("#workout-start-msg").innerHTML =
      '<p class="warnbox">Required readiness missing: ' + esc(missing.join(", ")) + '</p>';
    return;
  }
  var loaded = window.__workoutReadinessLoaded || {};
  var changed = WORKOUT_REQUIRED.some(function (key) {
    return String(readiness[key]) !== String(loaded[key] || "");
  });
  if (changed && !window.confirm(
    "Readiness changed after this prescription was built. Start with the existing plan? " +
    "Cancel to go back and rebuild the prescription."
  )) {
    setView("prescribe");
    return;
  }
  $("#workout-start-msg").textContent = "Starting…";
  api("/api/workout/start", {
    method: "POST",
    body: JSON.stringify({
      date: plan.for_date,
      plan: plan,
      readiness: readiness,
      readiness_note: $("#workout-readiness-note").value || null,
      note: $("#workout-start-note").value || null
    })
  }).then(function (data) {
    $("#workout-start-panel").hidden = true;
    notify("Workout started.");
    renderWorkout(data.workout);
  }).catch(function (error) {
    $("#workout-start-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + '</p>';
  });
}

function fmtClock(totalSeconds) {
  var s = Math.max(0, Math.floor(totalSeconds));
  var h = Math.floor(s / 3600);
  var m = Math.floor((s % 3600) / 60);
  var sec = s % 60;
  var prefix = h ? String(h).padStart(2, "0") + ":" : "";
  return prefix + String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
}

function startWorkoutTimer(startedAt, elapsed) {
  if (workoutTimer) clearInterval(workoutTimer);
  var base = new Date(startedAt).getTime();
  function tick() {
    var seconds = Math.max(elapsed || 0, (Date.now() - base) / 1000);
    $("#workout-timer").textContent = fmtClock(seconds);
  }
  tick();
  workoutTimer = setInterval(tick, 1000);
}

function stopWorkoutTimer() {
  if (workoutTimer) clearInterval(workoutTimer);
  workoutTimer = null;
}

let workoutExerciseList = [];

function workoutExerciseOptions(selected) {
  return '<option value="">choose…</option>' + workoutExerciseList.map(function (item) {
    var id = item.id || item.exercise_id;
    var label = item.display || id;
    return '<option value="' + esc(id) + '"' + (String(selected) === String(id) ? " selected" : "") +
      ">" + esc(label) + "</option>";
  }).join("");
}

function loadWorkoutExercises() {
  if (workoutExerciseList.length) return Promise.resolve(workoutExerciseList);
  return api("/api/exercises").then(function (list) {
    workoutExerciseList = list || [];
    if (activeWorkoutId) loadActiveWorkout();
    return workoutExerciseList;
  }).catch(function () { return []; });
}

function planAction(action, body) {
  if (!activeWorkoutId) return;
  $("#workout-plan-msg").textContent = "Updating plan…";
  api("/api/workout/" + activeWorkoutId + "/plan/" + action, {
    method: "POST", body: JSON.stringify(body)
  }).then(function (data) {
    $("#workout-plan-msg").textContent = "";
    notify("Workout plan updated.");
    renderWorkout(data.workout);
  }).catch(function (error) {
    $("#workout-plan-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + "</p>";
  });
}

function renderImportPreview(preview) {
  var rows = (preview.rows || []).map(function (row) {
    return "<tr><td>" + row.line + "</td><td>" + esc(row.exercise) + "</td><td>" +
      (row.exercise_id == null ? "<strong>unknown</strong>" : "<code>" + esc(row.exercise_id) + "</code>" + (row.plan_new ? ' <span class="badge">new to plan</span>' : "")) +
      "</td><td>" + row.set_index + "</td><td>" + (row.rpe == null ? "—" : row.rpe) +
      "</td><td>" + (row.rir == null ? "—" : row.rir) + (row.warmup ? " (warm-up)" : "") +
      "</td><td>" + fmt(row.load_kg) + "</td><td>" + row.reps + "</td><td>" +
      (row.velocity_mps == null ? "—" : row.velocity_mps) + "</td><td>" +
      (row.conflicts && Object.keys(row.conflicts).length
        ? Object.keys(row.conflicts).map(function (key) {
            return key + ": " + row.conflicts[key][1] + " → " + row.conflicts[key][0];
          }).join("; ")
        : "—") + "</td></tr>";
  }).join("");
  var errors = (preview.errors || []).map(function (error) {
    return "<li>line " + error.line + ": " + esc(error.error) + "</li>";
  }).join("");
  var warnings = (preview.rows || []).reduce(function (out, row) {
    (row.warnings || []).forEach(function (text) {
      out.push("<li>" + esc(row.exercise) + " set " + row.set_index + ": " + esc(text) + "</li>");
    });
    return out;
  }, []).join("");
  var rep = preview.rep || {};
  var repRows = (rep.sets || []).map(function (item) {
    var count = (item.reps || []).length;
    return "<tr><td>" + esc(item.exercise) + "</td><td>" + item.set_index + "</td><td>" +
      (item.mean == null ? "—" : item.mean) + "</td><td>" + count + "</td><td>" +
      (count ? item.reps[0].velocity_mps + " → " + item.reps[count - 1].velocity_mps : "—") +
      "</td></tr>";
  }).join("");
  $("#workout-import-preview-area").innerHTML =
    (errors ? '<div class="warnbox"><strong>Errors</strong><ul class="list">' + errors + "</ul></div>" : "") +
    (warnings ? '<div class="warnbox"><strong>Warnings</strong><ul class="list">' + warnings + "</ul></div>" : "") +
    (rows ? "<table><thead><tr><th>line</th><th>exercise</th><th>canonical</th><th>set</th>" +
      "<th>RPE</th><th>RIR</th><th>kg</th><th>reps</th><th>m/s</th><th>manual → import</th></tr></thead><tbody>" +
      rows + "</tbody></table>" : "<p class='empty'>No rows parsed.</p>") +
    (repRows ? "<h4>Per-rep detail</h4><table><thead><tr><th>exercise</th><th>set</th>" +
      "<th>mean</th><th>reps</th><th>first → last</th></tr></thead><tbody>" +
      repRows + "</tbody></table>" : "");
}

function submitImport(apply) {
  if (!activeWorkoutId) return;
  var text = $("#workout-import-text").value;
  var repText = ($("#workout-rep-import-text") || {}).value || "";
  if (!text.trim()) {
    $("#workout-import-msg").textContent = "Paste CSV or choose a file first.";
    return;
  }
  $("#workout-import-msg").textContent = apply ? "Applying…" : "Previewing…";
  api("/api/workout/" + activeWorkoutId + "/import", {
    method: "POST", body: JSON.stringify({ text: text, rep_text: repText, apply: apply })
  }).then(function (data) {
    renderImportPreview(data.preview || {});
    if (apply) {
      $("#workout-import-msg").textContent = "Imported.";
      notify("Workout CSV imported.");
      renderWorkout(data.workout);
    } else {
      $("#workout-import-msg").textContent = "Preview only; nothing applied.";
    }
  }).catch(function (error) {
    $("#workout-import-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + "</p>";
  });
}

function editWorkoutSet(setId) {
  if (!window.__workoutData) return;
  var set = (window.__workoutData.sets || []).filter(function (item) {
    return String(item.set_id) === String(setId);
  })[0];
  if (!set) return;
  window.__editingSetId = setId;
  $("#workout-edit-load").value = set.load_kg == null ? "" : set.load_kg;
  $("#workout-edit-reps").value = set.reps == null ? "" : set.reps;
  $("#workout-edit-rir").value = set.rir == null ? "" : set.rir;
  $("#workout-edit-velocity").value = set.velocity == null ? "" : set.velocity;
  $("#workout-set-edit").hidden = false;
  $("#workout-set-edit-msg").textContent = set.exercise_id + " · set " + set.set_index;
  $("#workout-set-edit").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function saveWorkoutSetEdit() {
  if (!activeWorkoutId || !window.__editingSetId) return;
  api("/api/workout/" + activeWorkoutId + "/update-set", {
    method: "POST",
    body: JSON.stringify({
      set_id: Number(window.__editingSetId),
      load_kg: $("#workout-edit-load").value || null,
      reps: $("#workout-edit-reps").value || null,
      rir: $("#workout-edit-rir").value || null,
      velocity: $("#workout-edit-velocity").value || null
    })
  }).then(function (data) {
    $("#workout-set-edit").hidden = true;
    window.__editingSetId = null;
    notify("Set updated.");
    renderWorkout(data.workout);
  }).catch(function (error) {
    $("#workout-set-edit-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + "</p>";
  });
}

function renderWorkout(w) {
  activeWorkoutId = w.workout_id;
  window.__workoutData = w;
  $("#workout-empty").hidden = true;
  $("#workout-start-panel").hidden = true;
  $("#workout-ended-panel").hidden = true;
  $("#workout-active-panel").hidden = false;
  $("#workout-title").textContent = w.for_date + " · " + (w.session_type || "unknown");
  $("#workout-meta").innerHTML = "Started " + esc(w.started_at) + " · status <strong>" +
    esc(w.status) + "</strong>";

  var plan = w.plan || {};
  var items = plan.items || [];
  var rows = items.map(function (item, index) {
    return "<tr><td><strong>" + esc(item.exercise_id) + "</strong>" +
      (item.substitution_for ? '<div class="muted">swapped from ' + esc(item.substitution_for) + "</div>" : "") +
      (item.added_during_workout ? '<div class="muted">added during workout</div>' : "") +
      '</td><td><button class="ghost" type="button" data-plan-set="-1" data-index="' +
      index + '">−</button> ' + item.sets +
      ' <button class="ghost" type="button" data-plan-set="1" data-index="' + index + '">+</button></td><td>' +
      item.reps_low + "–" + item.reps_high + "</td><td>" + fmt(item.load_kg) +
      "</td><td>" + (item.rir_target == null ? "—" : item.rir_target) + "</td><td>" +
      '<select data-swap-select="' + index + '">' + workoutExerciseOptions("") + "</select>" +
      ' <button class="ghost" type="button" data-swap-index="' + index + '">Swap</button></td><td>' +
      '<button class="ghost" type="button" data-remove-item="' + index + '">Remove</button></td></tr>';
  }).join("");
  $("#workout-plan").innerHTML = "<p class='muted'>This is the editable workout plan; the original prescription is kept separately.</p>" +
    "<table><thead><tr><th>Planned</th><th>Sets</th><th>Reps</th><th>kg</th><th>RIR</th>" +
    "<th>Swap</th><th></th></tr></thead><tbody>" + rows + "</tbody></table>" +
    '<div class="form-row" style="margin-top:0.75rem">' +
    '<label>Add exercise <select id="workout-add-exercise">' + workoutExerciseOptions("") + "</select></label>" +
    '<label>Sets <input id="workout-add-sets" type="number" min="1" max="20" value="3"></label>' +
    '<label>Reps low <input id="workout-add-reps-low" type="number" min="1" max="50" value="8"></label>' +
    '<label>Reps high <input id="workout-add-reps-high" type="number" min="1" max="50" value="12"></label>' +
    '<label>kg <input id="workout-add-load" type="number" step="0.5"></label>' +
    '<label>RIR <input id="workout-add-rir" type="number" min="0" max="10" value="2"></label>' +
    '<button class="ghost" type="button" id="workout-add-exercise-run">Add to plan</button></div>' +
    '<div id="workout-plan-msg"></div>';
  document.querySelectorAll("[data-plan-set]").forEach(function (button) {
    button.addEventListener("click", function () {
      planAction("set-count", { item_index: Number(button.dataset.index), delta: Number(button.dataset.planSet) });
    });
  });
  document.querySelectorAll("[data-remove-item]").forEach(function (button) {
    button.addEventListener("click", function () {
      planAction("remove-exercise", { item_index: Number(button.dataset.removeItem) });
    });
  });
  document.querySelectorAll("[data-swap-index]").forEach(function (button) {
    button.addEventListener("click", function () {
      var index = Number(button.dataset.swapIndex);
      var select = document.querySelector('[data-swap-select="' + index + '"]');
      if (!select || !select.value) {
        $("#workout-plan-msg").textContent = "Choose an exercise to swap to.";
        return;
      }
      planAction("swap", { item_index: index, exercise_id: select.value });
    });
  });
  var add = document.getElementById("workout-add-exercise-run");
  if (add) add.addEventListener("click", function () {
    var select = document.getElementById("workout-add-exercise");
    if (!select || !select.value) return;
    planAction("add-exercise", {
      exercise_id: select.value,
      sets: Number(document.getElementById("workout-add-sets").value),
      reps_low: Number(document.getElementById("workout-add-reps-low").value),
      reps_high: Number(document.getElementById("workout-add-reps-high").value),
      load_kg: document.getElementById("workout-add-load").value || null,
      rir_target: document.getElementById("workout-add-rir").value || null
    });
  });

  var seen = {};
  var options = "";
  items.forEach(function (item) {
    if (seen[item.exercise_id]) return;
    seen[item.exercise_id] = true;
    options += '<option value="' + esc(item.exercise_id) + '">' + esc(item.exercise_id) + "</option>";
  });
  $("#workout-set-exercise").innerHTML = options;

  var setRows = (w.sets || []).map(function (set) {
    return "<tr><td>" + esc(set.exercise_id) + "</td><td>" + set.set_index + "</td><td>" +
      fmt(set.load_kg) + "</td><td>" + (set.reps == null ? "—" : set.reps) + "</td><td>" +
      (set.rir == null ? "—" : set.rir) + "</td><td>" +
      (set.velocity == null ? "—" : set.velocity) +
      (set.rep_summary ? '<div class="muted">loss ' + set.rep_summary.loss_pct + '%</div>' : "") + "</td><td>" +
      '<button class="ghost" type="button" data-edit-set="' + set.set_id + '">Edit</button> ' +
      '<button class="ghost" type="button" data-remove-set="' + set.set_id + '">Remove</button>' +
      "</td></tr>";
  }).join("");
  $("#workout-sets").innerHTML = setRows
    ? "<table><thead><tr><th>Exercise</th><th>Set</th><th>kg</th><th>Reps</th><th>RIR</th>" +
      "<th>Velocity</th><th></th></tr></thead><tbody>" + setRows + "</tbody></table>"
    : "<p class='empty'>No sets logged yet.</p>";
  document.querySelectorAll("[data-remove-set]").forEach(function (button) {
    button.addEventListener("click", function () { removeWorkoutSet(button.dataset.removeSet); });
  });
  document.querySelectorAll("[data-edit-set]").forEach(function (button) {
    button.addEventListener("click", function () { editWorkoutSet(button.dataset.editSet); });
  });
  var measured = Math.max(1, Math.round((w.elapsed_seconds || 0) / 60));
  $("#workout-end-duration").placeholder = "measured ~" + measured + " min";
  startWorkoutTimer(w.started_at, w.elapsed_seconds);
}

function renderWorkoutEnded(w) {
  stopWorkoutTimer();
  activeWorkoutId = null;
  $("#workout-active-panel").hidden = true;
  $("#workout-start-panel").hidden = true;
  $("#workout-empty").hidden = true;
  $("#workout-ended-panel").hidden = false;
  var rpe = w.session_rpe_recorded ? fmt(w.session_rpe) : "not recorded";
  var comparison = w.comparison || { items: [], extra: [] };
  var original = w.original_comparison || comparison;
  var origRows = original.items.map(function (row) {
    return "<tr><td>" + esc(row.exercise_id) + "</td><td>" + esc(row.status) + "</td><td>" +
      row.actual_sets + " / " + row.planned_sets + "</td></tr>";
  }).join("");
  var compRows = comparison.items.map(function (row) {
    return "<tr><td>" + esc(row.exercise_id) + "</td><td>" + esc(row.status) + "</td><td>" +
      row.actual_sets + " / " + row.planned_sets + "</td><td>" +
      (row.actual_reps.length ? row.actual_reps.join(", ") : "—") + "</td><td>" +
      (row.actual_load_kg.length ? row.actual_load_kg.join(", ") : "—") + "</td><td>" +
      (row.actual_rir.length ? row.actual_rir.join(", ") : "—") + "</td></tr>";
  }).join("");
  var repRows = (w.sets || []).filter(function (set) { return set.rep_summary; }).map(function (set) {
    var summary = set.rep_summary;
    return "<tr><td>" + esc(set.exercise_id) + "</td><td>" + set.set_index + "</td><td>" +
      summary.count + "</td><td>" + summary.first + "</td><td>" + summary.last + "</td><td>" +
      summary.loss_abs + " (" + summary.loss_pct + "%)</td></tr>";
  }).join("");
  var repBlock = repRows
    ? "<h3>Per-rep velocity</h3><table><thead><tr><th>Exercise</th><th>Set</th><th>Reps</th>" +
      "<th>First</th><th>Last</th><th>Loss</th></tr></thead><tbody>" + repRows +
      "</tbody></table><p class=\"muted\">Descriptive only; no prescription or autoregulation reads this.</p>"
    : "";
  var extra = comparison.extra.length
    ? "<p class='muted'>Extra sets: " + comparison.extra.map(function (row) {
        return esc(row.exercise_id) + " #" + row.set_index;
      }).join(", ") + "</p>"
    : "";
  $("#workout-ended").innerHTML = "<p><strong>" + esc(w.for_date) + "</strong> ended. Duration <strong>" +
    fmt(w.duration_min) + " min</strong> (" + esc(w.duration_source || "measured") +
    "), session RPE <strong>" + rpe + "</strong>.</p>" +
    "<table><thead><tr><th>Exercise</th><th>Status</th><th>Sets actual / planned</th>" +
    "<th>Reps</th><th>kg</th><th>RIR</th></tr></thead><tbody>" + compRows + "</tbody></table>" +
    extra +
    repBlock +
    (w.plan_modified
      ? '<h3>Original prescription</h3><table><thead><tr><th>Exercise</th><th>Status</th>' +
        '<th>Actual / planned sets</th></tr></thead><tbody>' + origRows + '</tbody></table>' +
        '<p class="muted">The table above compares against the modified workout plan; this table compares against the original prescription.</p>'
      : "") +
    '<div class="form-row" style="margin-top:1rem">' +
    '<button class="primary" type="button" id="workout-review">Review workout</button>' +
    '<span class="muted">The deterministic rubric was saved at End workout.</span></div>';
  var review = document.getElementById("workout-review");
  if (review) review.addEventListener("click", function () { openReview(w.workout_id); });
}

function loadActiveWorkout() {
  api("/api/workout/active").then(function (data) {
    if (data.workout) {
      renderWorkout(data.workout);
    } else {
      stopWorkoutTimer();
      activeWorkoutId = null;
      $("#workout-active-panel").hidden = true;
      $("#workout-start-panel").hidden = true;
      $("#workout-ended-panel").hidden = true;
      $("#workout-empty").hidden = false;
    }
  }).catch(function (error) {
    $("#workout-empty").hidden = false;
    $("#workout-empty").innerHTML = '<div class="panel-head"><h2>Workout</h2></div>' +
      '<p class="warnbox">' + esc(error.message) + "</p>";
  });
}

function removeWorkoutSet(setId) {
  if (!activeWorkoutId) return;
  api("/api/workout/" + activeWorkoutId + "/remove-set", {
    method: "POST", body: JSON.stringify({ set_id: setId })
  }).then(function (data) {
    notify("Set removed.");
    renderWorkout(data.workout);
  }).catch(function (error) {
    $("#workout-set-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + "</p>";
  });
}

function submitWorkoutSet(event) {
  event.preventDefault();
  if (!activeWorkoutId) return;
  var body = {
    exercise_id: $("#workout-set-exercise").value,
    load_kg: $("#workout-set-load").value || null,
    reps: $("#workout-set-reps").value || null,
    rir: $("#workout-set-rir").value || null,
    velocity: $("#workout-set-velocity").value || null
  };
  $("#workout-set-msg").textContent = "Adding…";
  api("/api/workout/" + activeWorkoutId + "/sets", {
    method: "POST", body: JSON.stringify(body)
  }).then(function (data) {
    $("#workout-set-msg").textContent = "";
    $("#workout-set-load").value = "";
    $("#workout-set-reps").value = "";
    $("#workout-set-rir").value = "";
    $("#workout-set-velocity").value = "";
    notify("Set added.");
    renderWorkout(data.workout);
  }).catch(function (error) {
    $("#workout-set-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + "</p>";
  });
}

function submitWorkoutEnd(event) {
  event.preventDefault();
  if (!activeWorkoutId) return;
  var body = {
    duration_min: $("#workout-end-duration").value || null,
    session_rpe: $("#workout-end-srpe").value || null,
    not_recorded: $("#workout-end-not-recorded").checked,
    notes: $("#workout-end-note").value || null
  };
  $("#workout-end-msg").textContent = "Ending…";
  api("/api/workout/" + activeWorkoutId + "/end", {
    method: "POST", body: JSON.stringify(body)
  }).then(function (data) {
    notify("Workout ended; session saved.");
    renderWorkoutEnded(data.workout);
  }).catch(function (error) {
    $("#workout-end-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + "</p>";
  });
}

function abandonWorkout() {
  if (!activeWorkoutId) return;
  if (!window.confirm("Abandon this workout? Sets stay in history but it will not count as completed.")) return;
  api("/api/workout/" + activeWorkoutId + "/abandon", { method: "POST", body: "{}" })
    .then(function () { notify("Workout abandoned."); return loadActiveWorkout(); })
    .catch(function (error) {
      $("#workout-end-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + "</p>";
    });
}

document.addEventListener("DOMContentLoaded", function () {
  var cancel = document.getElementById("workout-start-cancel");
  if (cancel) cancel.addEventListener("click", cancelWorkoutStart);
  var start = document.getElementById("workout-start-form");
  if (start) start.addEventListener("submit", submitWorkoutStart);
  var setForm = document.getElementById("workout-set-form");
  if (setForm) setForm.addEventListener("submit", submitWorkoutSet);
  var endForm = document.getElementById("workout-end-form");
  if (endForm) endForm.addEventListener("submit", submitWorkoutEnd);
  var abandon = document.getElementById("workout-abandon");
  if (abandon) abandon.addEventListener("click", abandonWorkout);
  var editCancel = document.getElementById("workout-set-edit-cancel");
  if (editCancel) editCancel.addEventListener("click", function () { $("#workout-set-edit").hidden = true; });
  var editSave = document.getElementById("workout-set-edit-save");
  if (editSave) editSave.addEventListener("click", saveWorkoutSetEdit);
  var importFile = document.getElementById("workout-import-file");
  if (importFile) importFile.addEventListener("change", function () {
    var file = importFile.files && importFile.files[0];
    if (!file) return;
    file.text().then(function (text) { document.getElementById("workout-import-text").value = text; });
  });
  var repImportFile = document.getElementById("workout-rep-import-file");
  if (repImportFile) repImportFile.addEventListener("change", function () {
    var file = repImportFile.files && repImportFile.files[0];
    if (!file) return;
    file.text().then(function (text) { document.getElementById("workout-rep-import-text").value = text; });
  });
  var importPreview = document.getElementById("workout-import-preview");
  if (importPreview) importPreview.addEventListener("click", function () { submitImport(false); });
  var importApply = document.getElementById("workout-import-apply");
  if (importApply) importApply.addEventListener("click", function () { submitImport(true); });
  var importUndo = document.getElementById("workout-import-undo");
  if (importUndo) importUndo.addEventListener("click", function () {
    if (!activeWorkoutId) return;
    api("/api/workout/" + activeWorkoutId + "/import/undo", { method: "POST", body: "{}" })
      .then(function (data) { $("#workout-import-msg").textContent = "Last import undone."; notify("Last import undone."); renderWorkout(data.workout); })
      .catch(function (error) { $("#workout-import-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + "</p>"; });
  });
  var notRecorded = document.getElementById("workout-end-not-recorded");
  if (notRecorded) notRecorded.addEventListener("change", function () {
    document.getElementById("workout-end-srpe").disabled = notRecorded.checked;
  });
  loadWorkoutExercises();
  loadActiveWorkout();
});
