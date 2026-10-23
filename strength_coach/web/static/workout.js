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
    plan.for_date + " · " + (plan.session_type || ("Day " + plan.session_day));
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

function renderWorkout(w) {
  activeWorkoutId = w.workout_id;
  $("#workout-empty").hidden = true;
  $("#workout-start-panel").hidden = true;
  $("#workout-ended-panel").hidden = true;
  $("#workout-active-panel").hidden = false;
  $("#workout-title").textContent = w.for_date + " · " + (w.session_type || ("Day " + w.session_day));
  $("#workout-meta").innerHTML = "Started " + esc(w.started_at) + " · status <strong>" +
    esc(w.status) + "</strong>";

  var plan = w.plan || {};
  var items = plan.items || [];
  var rows = items.map(function (item) {
    return "<tr><td><strong>" + esc(item.exercise_id) + "</strong></td><td>" + item.sets +
      "</td><td>" + item.reps_low + "–" + item.reps_high + "</td><td>" + fmt(item.load_kg) +
      "</td><td>" + (item.rir_target == null ? "—" : item.rir_target) + "</td></tr>";
  }).join("");
  $("#workout-plan").innerHTML = "<table><thead><tr><th>Prescribed</th><th>Sets</th><th>Reps</th>" +
    "<th>kg</th><th>RIR</th></tr></thead><tbody>" + rows + "</tbody></table>";

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
      (set.velocity == null ? "—" : set.velocity) + "</td><td>" +
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
  var compRows = comparison.items.map(function (row) {
    return "<tr><td>" + esc(row.exercise_id) + "</td><td>" + esc(row.status) + "</td><td>" +
      row.actual_sets + " / " + row.planned_sets + "</td><td>" +
      (row.actual_reps.length ? row.actual_reps.join(", ") : "—") + "</td><td>" +
      (row.actual_load_kg.length ? row.actual_load_kg.join(", ") : "—") + "</td><td>" +
      (row.actual_rir.length ? row.actual_rir.join(", ") : "—") + "</td></tr>";
  }).join("");
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
    renderWorkoutEnded(data.workout);
  }).catch(function (error) {
    $("#workout-end-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + "</p>";
  });
}

function abandonWorkout() {
  if (!activeWorkoutId) return;
  if (!window.confirm("Abandon this workout? Sets stay in history but it will not count as completed.")) return;
  api("/api/workout/" + activeWorkoutId + "/abandon", { method: "POST", body: "{}" })
    .then(loadActiveWorkout)
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
  var notRecorded = document.getElementById("workout-end-not-recorded");
  if (notRecorded) notRecorded.addEventListener("change", function () {
    document.getElementById("workout-end-srpe").disabled = notRecorded.checked;
  });
  loadActiveWorkout();
});
