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
let workoutSetBusy = false;
const WORKOUT_HISTORY_LIMIT = 5;
let workoutHistoryState = {};

function workoutField(key, required) {
  var label = '<label>' + esc(WORKOUT_LABELS[key] || key);
  if (WORKOUT_OPTIONAL.includes(key)) {
    return label + '<input type="number" step="0.1" data-workout-field="' + key + '"' +
      (required ? ' required' : '') + '></label>';
  }
  var options = readinessScaleOptions(key);
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
  var startTime = plan.notes && plan.notes.session_time;
  var startEstimate = startTime && startTime.estimated_minutes != null
    ? " · estimated ~" + fmt(startTime.estimated_minutes) + " min" : "";
  $("#workout-start-summary").textContent =
    plan.for_date + " · " + (plan.session_type || "unknown") + startEstimate;
  $("#workout-readiness-required").innerHTML =
    WORKOUT_REQUIRED.map(function (key) { return workoutField(key, false); }).join("");
  $("#workout-readiness-optional").innerHTML =
    WORKOUT_OPTIONAL.map(function (key) { return workoutField(key, false); }).join("");
  $("#workout-start-ack").checked = false;
  $("#workout-start-ack-wrap").hidden = true;
  $("#workout-start-msg").textContent = "Loading readiness…";
  setView("workout");
  if (typeof setWorkflowStep === "function") setWorkflowStep("active");
  api("/api/readiness/" + encodeURIComponent(plan.for_date)).then(function (data) {
    document.querySelectorAll("[data-workout-field]").forEach(function (input) {
      input.value = data[input.dataset.workoutField] == null ? "" : data[input.dataset.workoutField];
    });
    $("#workout-readiness-note").value = data.note || "";
    window.__workoutReadinessLoaded = data;
    var scored = data.score && data.score.status === "ready";
    $("#workout-start-ack-wrap").hidden = Boolean(scored);
    $("#workout-start-msg").textContent = scored
      ? ""
      : "Readiness score unavailable; tick the acknowledgement to start with partial data.";
  }).catch(function (error) {
    $("#workout-start-msg").innerHTML = '<p class="warnbox">' + esc(error.message) + '</p>';
  });
}

function cancelWorkoutStart() {
  $("#workout-start-panel").hidden = true;
  $("#workout-empty").hidden = false;
  setView("workout");
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
  var acknowledge = $("#workout-start-ack").checked;
  var loaded = window.__workoutReadinessLoaded || {};
  var changed = WORKOUT_REQUIRED.some(function (key) {
    return String(readiness[key]) !== String(loaded[key] || "");
  });
  if (changed && !window.confirm(
    "Readiness changed after this prescription was built. Start with the existing plan? " +
    "Cancel to go back and rebuild the prescription."
  )) {
    setView("workout");
    return;
  }
  $("#workout-start-msg").textContent = "Starting…";
  api("/api/workout/start", {
    method: "POST",
    body: JSON.stringify({
      date: plan.for_date,
      plan: plan,
      readiness: readiness,
      readiness_ack: acknowledge,
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

function workoutExerciseLabel(exerciseId) {
  var match = workoutExerciseList.find(function (item) {
    return String(item.id || item.exercise_id) === String(exerciseId);
  });
  return match ? (match.display || match.id || exerciseId) : exerciseId;
}

function workoutExerciseOptions(selected) {
  return '<option value="">choose…</option>' + workoutExerciseList.map(function (item) {
    var id = item.id || item.exercise_id;
    var label = item.display || id;
    return '<option value="' + esc(id) + '"' + (String(selected) === String(id) ? " selected" : "") +
      ">" + esc(label) + "</option>";
  }).join("");
}

function numericOrNull(selector) {
  var value = $(selector).value;
  return value === "" ? null : Number(value);
}

function workoutPlanItem(exerciseId) {
  var data = window.__workoutData || {};
  var items = (data.plan && data.plan.items) || [];
  return items.find(function (item) { return String(item.exercise_id) === String(exerciseId); }) || null;
}

function nextWorkoutSetNumber(exerciseId) {
  var data = window.__workoutData || {};
  var used = (data.sets || []).filter(function (set) {
    return String(set.exercise_id) === String(exerciseId);
  });
  return used.reduce(function (max, set) {
    return Math.max(max, Number(set.set_index) || 0);
  }, 0) + 1;
}

function updateWorkoutSetTarget() {
  var target = document.getElementById("workout-set-target");
  if (!target) return;
  var exerciseId = $("#workout-set-exercise").value;
  var item = workoutPlanItem(exerciseId);
  if (!exerciseId) {
    target.textContent = "Choose an exercise to see the planned target.";
    return;
  }
  if (!item) {
    target.textContent = "This exercise is not in the current plan; log it anyway if intended.";
    return;
  }
  var effort = item.effort_model === "quality"
    ? (item.quality_stop || "quality stop")
    : (item.rir_target == null ? "no RIR target" : "RIR " + item.rir_target);
  target.innerHTML = "Planned <strong>" + esc(item.sets) + " × " + esc(item.reps_low) +
    "–" + esc(item.reps_high) + " @ " + (item.load_kg == null ? "load unknown" : fmt(item.load_kg) + " kg") +
    "</strong>, " + esc(effort) + ". Logging set <strong>" +
    nextWorkoutSetNumber(exerciseId) + "</strong>.";
}

function prefillWorkoutSetFields(force) {
  var item = workoutPlanItem($("#workout-set-exercise").value);
  if (!item) return;
  if (force || $("#workout-set-load").value === "") {
    $("#workout-set-load").value = item.load_kg == null ? "" : item.load_kg;
  }
  if (force || $("#workout-set-reps").value === "") {
    $("#workout-set-reps").value = item.reps_low == null ? "" : item.reps_low;
  }
  if (force || $("#workout-set-rir").value === "") {
    $("#workout-set-rir").value = item.effort_model === "quality" || item.rir_target == null
      ? "" : item.rir_target;
  }
  if (force) $("#workout-set-velocity").value = "";
}

function loadWorkoutExercises() {
  if (workoutExerciseList.length) return Promise.resolve(workoutExerciseList);
  return api("/api/exercises").then(function (list) {
    workoutExerciseList = list || [];
    if (activeWorkoutId) loadActiveWorkout();
    return workoutExerciseList;
  }).catch(function () { return []; });
}

function openWorkoutSwapDialog(index) {
  var data = window.__workoutData || {};
  var item = ((data.plan && data.plan.items) || [])[index];
  if (!item) return;
  window.__workoutSwapIndex = index;
  $("#workout-swap-current").textContent = workoutExerciseLabel(item.exercise_id);
  $("#workout-swap-exercise").innerHTML = workoutExerciseOptions("");
  var filter = $("#workout-swap-filter");
  filter.value = "";
  filterNativeSelect(filter);
  $("#workout-swap-msg").textContent = "";
  $("#workout-swap-dialog").showModal();
  filter.focus();
}

function submitWorkoutSwap(event) {
  event.preventDefault();
  var exerciseId = $("#workout-swap-exercise").value;
  var index = window.__workoutSwapIndex;
  if (!exerciseId) {
    $("#workout-swap-msg").textContent = "Choose a replacement exercise.";
    $("#workout-swap-exercise").focus();
    return;
  }
  $("#workout-swap-dialog").close();
  window.__workoutSwapIndex = null;
  planAction("swap", { item_index: Number(index), exercise_id: exerciseId });
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
    (rows ? "<div class='table-scroll'><table><thead><tr><th>line</th><th>exercise</th><th>canonical</th><th>set</th>" +
      "<th>RPE</th><th>RIR</th><th>kg</th><th>reps</th><th>m/s</th><th>manual → import</th></tr></thead><tbody>" +
      rows + "</tbody></table></div>" : "<p class='empty'>No rows parsed.</p>") +
    (repRows ? "<h4>Per-rep detail</h4><div class='table-scroll'><table><thead><tr><th>exercise</th><th>set</th>" +
      "<th>mean</th><th>reps</th><th>first → last</th></tr></thead><tbody>" +
      repRows + "</tbody></table></div>" : "");
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
      load_kg: numericOrNull("#workout-edit-load"),
      reps: numericOrNull("#workout-edit-reps"),
      rir: numericOrNull("#workout-edit-rir"),
      velocity: numericOrNull("#workout-edit-velocity")
    })
  }).then(function (data) {
    $("#workout-set-edit").hidden = true;
    window.__editingSetId = null;
    notify("Set updated.");
    renderWorkout(data.workout);
  }).catch(function (error) {
    applyFieldErrors(error, $("#workout-set-edit-msg"), {
      load_kg: "#workout-edit-load",
      reps: "#workout-edit-reps",
      rir: "#workout-edit-rir",
      velocity: "#workout-edit-velocity",
    });
  });
}

function renderWorkout(w) {
  activeWorkoutId = w.workout_id;
  window.__workoutData = w;
  $("#workout-empty").hidden = true;
  $("#workout-start-panel").hidden = true;
  $("#workout-ended-panel").hidden = true;
  $("#workout-active-panel").hidden = false;
  if (typeof setWorkflowStep === "function") setWorkflowStep("active");
  $("#workout-title").textContent = w.for_date + " · " + (w.session_type || "unknown");
  var plan = w.plan || {};
  var sessionTime = plan.notes && plan.notes.session_time;
  var timeEstimate = sessionTime && sessionTime.estimated_minutes != null
    ? " · estimated ~" + fmt(sessionTime.estimated_minutes) + " min" : "";
  $("#workout-meta").innerHTML = "Started " + esc(w.started_at) + " · status <strong>" +
    esc(w.status) + "</strong>" + timeEstimate;
  var volumeBox = document.getElementById("workout-volume");
  if (volumeBox) {
    volumeBox.innerHTML = plan.volume_panel
      ? volumePanelHtml(plan.volume_panel, "Planned weekly volume") : "";
  }
  var items = plan.items || [];
  var formById = {};
  (w.forms || []).forEach(function (form) { formById[form.exercise_id] = form; });
  var rows = items.map(function (item, index) {
    var form = formById[item.exercise_id];
    var history = workoutHistoryFor(item.exercise_id);
    var formOptions = ['<option value="">—</option>'];
    for (var rating = 1; rating <= 5; rating += 1) {
      formOptions.push('<option value="' + rating + '"' +
        (form && Number(form.rating) === rating ? " selected" : "") + ">" + rating + "</option>");
    }
    var effort = item.effort_model === "quality"
      ? (item.quality_stop || "quality stop")
      : (item.rir_target == null ? "no RIR target" : "RIR " + item.rir_target);
    return '<article class="workout-plan-card">' +
      '<div class="workout-plan-card-head"><strong>' + esc(workoutExerciseLabel(item.exercise_id)) + '</strong>' +
      '<span class="workout-plan-card-tools"><span class="badge">' + item.sets + ' sets</span>' +
      '<button class="ghost workout-history-toggle" type="button" data-history-toggle data-history-exercise="' +
      esc(item.exercise_id) + '" aria-expanded="' + (history.open ? "true" : "false") +
      '" aria-controls="workout-history-' + index + '">' +
      (history.open ? "Hide history" : "History") + '</button></span></div>' +
      '<p class="workout-plan-prescription">' + item.reps_low + "–" + item.reps_high +
      ' reps · ' + (item.load_kg == null ? "load unknown" : fmt(item.load_kg) + " kg") +
      ' · ' + esc(effort) + '</p>' +
      (item.substitution_for ? '<p class="muted">swapped from ' + esc(item.substitution_for) + '</p>' : "") +
      (item.added_during_workout ? '<p class="muted">added during workout</p>' : "") +
      workoutHistoryPanel(item.exercise_id, index, history) +
      '<div class="workout-plan-actions">' +
      '<div class="set-stepper" role="group" aria-label="Planned sets for ' + esc(item.exercise_id) + '">' +
      '<button class="ghost" type="button" data-plan-set="-1" data-index="' + index +
      '" aria-label="Remove one planned set">−</button><span>' + item.sets + '</span>' +
      '<button class="ghost" type="button" data-plan-set="1" data-index="' + index +
      '" aria-label="Add one planned set">+</button></div>' +
      '<label class="inline-field">Form ' +
      '<select data-form-exercise="' + esc(item.exercise_id) + '" aria-label="Form rating for ' +
      esc(item.exercise_id) + '">' + formOptions.join("") + '</select></label>' +
      '</div>' +
      '<details class="plan-options"><summary>Swap or remove</summary>' +
      '<button class="ghost" type="button" aria-label="Swap ' + esc(item.exercise_id) +
      '" data-swap-open="' + index + '">Swap exercise</button> ' +
      '<button class="ghost danger" type="button" aria-label="Remove ' + esc(item.exercise_id) + ' from plan" data-remove-item="' + index + '">Remove from plan</button>' +
      '</details></article>';
  }).join("");
  $("#workout-plan").innerHTML = '<div id="workout-plan-msg" role="status" aria-live="polite"></div>' +
    (rows || "<p class='empty'>No planned exercises.</p>") +
    '<details class="advanced"><summary>Form scale (optional)</summary><p class="muted">5 = intended technique on every rep; 4 = minor deviation, no compromised rep; 3 = clear deviation in at least one rep; 2 = multiple compromised reps or a noticeably altered rep; 1 = technique broke down / set stopped. Rate after the lift, per exercise.</p></details>' +
    '<details class="advanced"><summary>Add an exercise to the plan</summary><div class="form-row">' +
    '<label>Add exercise <span class="search-select">' +
    '<input type="search" class="search-select-filter" placeholder="Filter exercises…" aria-label="Filter exercise list">' +
    '<select id="workout-add-exercise" aria-label="Exercise to add">' + workoutExerciseOptions("") + "</select></span></label>" +
    '<label>Sets <input id="workout-add-sets" type="number" min="1" max="20" value="3"></label>' +
    '<label>Reps low <input id="workout-add-reps-low" type="number" min="1" max="50" value="8"></label>' +
    '<label>Reps high <input id="workout-add-reps-high" type="number" min="1" max="50" value="12"></label>' +
    '<label>kg <input id="workout-add-load" type="number" step="0.5"></label>' +
    '<label>RIR <input id="workout-add-rir" type="number" min="0" max="6" value="2"></label>' +
    '<button class="ghost" type="button" id="workout-add-exercise-run">Add to plan</button></div></details>';
  document.querySelectorAll("[data-form-exercise]").forEach(function (select) {
    select.addEventListener("change", function () {
      if (!select.value || !activeWorkoutId) return;
      api("/api/workout/" + activeWorkoutId + "/form", {
        method: "POST",
        body: JSON.stringify({ exercise_id: select.dataset.formExercise, rating: Number(select.value) })
      }).then(function (data) {
        notify("Form rating saved.");
        renderWorkout(data.workout);
      }).catch(function (error) {
        notify(error.message, "error");
      });
    });
  });
  document.querySelectorAll("[data-plan-set]").forEach(function (button) {
    button.addEventListener("click", function () {
      planAction("set-count", { item_index: Number(button.dataset.index), delta: Number(button.dataset.planSet) });
    });
  });
  document.querySelectorAll("[data-remove-item]").forEach(function (button) {
    button.addEventListener("click", function () {
      var item = items[Number(button.dataset.removeItem)];
      var name = item ? workoutExerciseLabel(item.exercise_id) : "this exercise";
      if (!window.confirm("Remove " + name + " from the workout plan? The original prescription stays.")) return;
      planAction("remove-exercise", { item_index: Number(button.dataset.removeItem) });
    });
  });
  document.querySelectorAll("[data-swap-open]").forEach(function (button) {
    button.addEventListener("click", function () {
      openWorkoutSwapDialog(Number(button.dataset.swapOpen));
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
  var previousExercise = $("#workout-set-exercise").value;
  items.forEach(function (item) {
    if (seen[item.exercise_id]) return;
    seen[item.exercise_id] = true;
    options += '<option value="' + esc(item.exercise_id) + '">' + esc(item.exercise_id) + "</option>";
  });
  $("#workout-set-exercise").innerHTML = options;
  var desired = previousExercise || (items[0] && items[0].exercise_id) || "";
  $("#workout-set-exercise").value = desired;
  if (!$("#workout-set-exercise").value) {
    $("#workout-set-exercise").selectedIndex = 0;
  }
  var keptSelection = Boolean(
    previousExercise && $("#workout-set-exercise").value === previousExercise
  );
  $("#workout-set-exercise").addEventListener("change", function () {
    prefillWorkoutSetFields(true);
    updateWorkoutSetTarget();
  });

  var setRows = (w.sets || []).map(function (set) {
    return '<article class="workout-set-card"><div class="workout-set-card-head">' +
      '<strong>' + esc(workoutExerciseLabel(set.exercise_id)) + '</strong><span class="badge">Set ' +
      set.set_index + '</span></div><p class="workout-set-values">' +
      (set.load_kg == null ? "load —" : fmt(set.load_kg) + " kg") + " · " +
      (set.reps == null ? "reps —" : set.reps + " reps") + " · RIR " +
      (set.rir == null ? "—" : set.rir) +
      (set.velocity == null ? "" : " · " + set.velocity + " m/s") +
      (set.rep_summary ? " · loss " + set.rep_summary.loss_pct + "%" : "") +
      '</p><div class="workout-set-actions">' +
      '<button class="ghost" type="button" aria-label="Edit ' + esc(workoutExerciseLabel(set.exercise_id)) +
      ' set ' + set.set_index + '" data-edit-set="' + set.set_id + '">Edit</button> ' +
      '<button class="ghost danger" type="button" aria-label="Remove ' + esc(workoutExerciseLabel(set.exercise_id)) +
      ' set ' + set.set_index + '" data-remove-set="' + set.set_id + '">Remove</button>' +
      '</div></article>';
  }).join("");
  $("#workout-sets").innerHTML = setRows
    ? '<div class="workout-set-list">' + setRows + '</div>'
    : "<p class='empty'>No sets logged yet.</p>";
  updateWorkoutSetTarget();
  prefillWorkoutSetFields(!keptSelection);
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

function workoutHistoryFor(exerciseId) {
  var key = String(exerciseId);
  if (!workoutHistoryState[key]) {
    workoutHistoryState[key] = {
      open: false,
      loaded: false,
      loading: false,
      error: "",
      sessions: [],
      total: 0,
      hasMore: false,
      included: []
    };
  }
  return workoutHistoryState[key];
}

function workoutHistoryLoadLabel(set) {
  var load = set.load_kg == null
    ? "—"
    : (Number(set.load_kg) === 0 && set.load_basis !== "external"
      ? "BW" : fmt(set.load_kg) + " kg");
  var reps = set.reps == null
    ? "—"
    : set.reps + (set.reps_unit === "seconds" ? " sec" : "");
  return load + " × " + reps;
}

function workoutHistorySessionHtml(session) {
  var rows = (session.sets || []).map(function (set) {
    return "<tr><td>" + esc(set.set_index) + "</td><td>" +
      esc(workoutHistoryLoadLabel(set)) + "</td><td>" +
      (set.rir == null ? "—" : "RIR " + esc(set.rir)) + "</td></tr>";
  }).join("");
  return '<div class="workout-history-session"><div class="workout-history-date">' +
    "<strong>" + esc(session.occurred_on) + "</strong> " +
    '<span class="muted">' + esc(session.session_type || "") + "</span></div>" +
    '<table class="workout-history-table"><thead><tr><th>Set</th>' +
    "<th>Load × reps</th><th>RIR</th></tr></thead><tbody>" + rows +
    "</tbody></table></div>";
}

function workoutHistoryPanel(exerciseId, index, state) {
  if (!state.open) return "";
  var body;
  if (state.error) {
    body = '<p class="warnbox">' + esc(state.error) + "</p>";
  } else if (state.loading && !state.sessions.length) {
    body = "<p class='muted'>Loading history…</p>";
  } else if (!state.sessions.length) {
    body = "<p class='empty'>No completed history for this exercise.</p>";
  } else {
    body = state.sessions.map(workoutHistorySessionHtml).join("");
    if (state.hasMore || state.loading) {
      body += '<button class="ghost workout-history-more" type="button" data-history-more ' +
        'data-history-exercise="' + esc(exerciseId) + '"' +
        (state.loading ? " disabled" : "") + ">" +
        (state.loading ? "Loading…" : "Show more") + "</button>";
    }
  }
  var included = "";
  if (state.loaded) {
    var extras = (state.included || []).filter(function (row) {
      return String(row.id) !== String(exerciseId);
    });
    if (extras.length) {
      included = '<p class="muted">Includes ' + extras.map(function (row) {
        return esc(row.display || row.id);
      }).join(", ") + " history.</p>";
    }
  }
  return '<div class="workout-history" id="workout-history-' + index +
    '" data-history-panel data-history-exercise="' + esc(exerciseId) + '">' +
    included + body + "</div>";
}

function renderWorkoutHistory(exerciseId) {
  var id = String(exerciseId);
  var state = workoutHistoryFor(id);
  document.querySelectorAll("[data-history-toggle]").forEach(function (button) {
    if (String(button.dataset.historyExercise) !== id) return;
    button.textContent = state.open ? "Hide history" : "History";
    button.setAttribute("aria-expanded", state.open ? "true" : "false");
  });
  document.querySelectorAll("[data-history-panel]").forEach(function (panel) {
    if (String(panel.dataset.historyExercise) !== id) return;
    if (!state.open) {
      panel.remove();
      return;
    }
    var index = panel.id.replace("workout-history-", "");
    panel.outerHTML = workoutHistoryPanel(id, index, state);
  });
}

function loadWorkoutHistory(exerciseId, append) {
  var id = String(exerciseId);
  var state = workoutHistoryFor(id);
  if (state.loading) return;
  state.loading = true;
  state.error = "";
  renderWorkoutHistory(id);
  var offset = append ? state.sessions.length : 0;
  var date = window.__workoutData && window.__workoutData.for_date;
  var query = "?exercise_id=" + encodeURIComponent(id) +
    "&limit=" + WORKOUT_HISTORY_LIMIT + "&offset=" + offset +
    (date ? "&on_or_before=" + encodeURIComponent(date) : "");
  api("/api/exercise-history" + query).then(function (data) {
    var next = data.sessions || [];
    state.sessions = append ? state.sessions.concat(next) : next;
    state.total = Number(data.total) || 0;
    state.hasMore = Boolean(data.has_more);
    state.included = data.included_exercises || [];
    state.loaded = true;
    state.loading = false;
    renderWorkoutHistory(id);
  }).catch(function (error) {
    state.loading = false;
    state.error = error.message;
    renderWorkoutHistory(id);
  });
}

function handleWorkoutHistoryClick(event) {
  var toggle = event.target.closest("[data-history-toggle]");
  if (toggle) {
    var id = toggle.dataset.historyExercise;
    var state = workoutHistoryFor(id);
    state.open = !state.open;
    renderWorkoutHistory(id);
    if (state.open && !state.loaded) loadWorkoutHistory(id, false);
    return;
  }
  var more = event.target.closest("[data-history-more]");
  if (more) {
    var moreId = more.dataset.historyExercise;
    var moreState = workoutHistoryFor(moreId);
    if (!moreState.loading) loadWorkoutHistory(moreId, true);
  }
}

function renderWorkoutEnded(w) {
  stopWorkoutTimer();
  var endedVolume = document.getElementById("workout-ended-volume");
  if (endedVolume) {
    endedVolume.innerHTML = w.plan && w.plan.volume_panel
      ? volumePanelHtml(w.plan.volume_panel, "Weekly volume at the end (planned position)") : "";
  }
  activeWorkoutId = null;
  $("#workout-active-panel").hidden = true;
  $("#workout-start-panel").hidden = true;
  $("#workout-empty").hidden = true;
  $("#workout-ended-panel").hidden = false;
  var summaryTarget = document.getElementById("workout-ended-summary");
  if (summaryTarget) summaryTarget.innerHTML = "<p class='muted'>Loading summary…</p>";
  if (typeof setWorkflowStep === "function") setWorkflowStep("post");
  var rpe = w.session_rpe_recorded ? fmt(w.session_rpe) : "not recorded";
  var minimum = w.minimum_session;
  // LIM-47: the target is judged against a planning estimate, so show that estimate next to
  // the measured clock rather than letting it stand in for the session length.
  var minimumLine = minimum
    ? "<p class='muted'>Minimum session (MOD-MIN-001): target <strong>" +
      fmt(minimum.target_minutes) + " min</strong> · estimated <strong>" +
      fmt(minimum.estimated_minutes) + " min</strong> · measured <strong>" +
      (minimum.measured_minutes == null ? "not measured"
        : fmt(minimum.measured_minutes) + " min") + "</strong>" +
      (minimum.measured_minutes != null && minimum.duration_source &&
       minimum.duration_source !== "measured"
        ? " (" + esc(minimum.duration_source) + ")" : "") +
      ". The estimate ignores transitions and idle time; the measured value is the clock.</p>"
    : "";
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
    ? "<h3>Per-rep velocity</h3><div class='table-scroll'><table><thead><tr><th>Exercise</th><th>Set</th><th>Reps</th>" +
      "<th>First</th><th>Last</th><th>Loss</th></tr></thead><tbody>" + repRows +
      "</tbody></table></div><p class=\"muted\">Descriptive only; no prescription or autoregulation reads this.</p>"
    : "";
  var extra = comparison.extra.length
    ? "<p class='muted'>Extra sets: " + comparison.extra.map(function (row) {
        return esc(row.exercise_id) + " #" + row.set_index;
      }).join(", ") + "</p>"
    : "";
  var postOptions = "";
  var seenPost = {};
  // The workout payload carries the plan; the comparison is the fallback when the plan was
  // edited away. Either way, only lifts that were actually part of this session are offered.
  var postSource = (w.plan && w.plan.items) || (w.comparison && w.comparison.items) || [];
  postSource.forEach(function (item) {
    if (seenPost[item.exercise_id]) return;
    seenPost[item.exercise_id] = true;
    postOptions += '<option value="' + esc(item.exercise_id) + '">' +
      esc(workoutExerciseLabel(item.exercise_id)) + "</option>";
  });
  var postBlock = postOptions
    ? '<div class="panel" id="post-e1rm-panel" style="margin-top:1rem">' +
      '<div class="panel-head"><h2>Record an e1RM</h2>' +
      '<span class="muted">optional; a test registers a high-intensity exposure</span></div>' +
      '<form id="post-test-form" class="grid-fields">' +
      '<label>Exercise<select id="post-test-exercise">' + postOptions + "</select></label>" +
      '<label>kg<input id="post-test-kg" type="number" step="0.5" min="0.5"></label>' +
      '<label>Reps<input id="post-test-reps" type="number" min="1" max="10" value="3"></label>' +
      '<label>Date<input id="post-test-date" type="date" value="' + esc(w.for_date) + '"></label>' +
      '<button class="primary" type="submit">Record test</button></form>' +
      '<form id="post-e1rm-form" class="grid-fields" style="margin-top:.75rem">' +
      '<label>or set e1RM<select id="post-e1rm-exercise">' + postOptions + "</select></label>" +
      '<label>e1RM kg<input id="post-e1rm-kg" type="number" step="0.5" min="0.5"></label>' +
      '<label>Date<input id="post-e1rm-date" type="date" value="' + esc(w.for_date) + '"></label>' +
      '<label class="grow">Reason<input id="post-e1rm-reason" placeholder="coach call, correction"></label>' +
      '<button type="submit">Set override</button></form>' +
      '<div id="post-e1rm-msg" class="muted"></div></div>'
    : "";
  $("#workout-ended").innerHTML = "<p><strong>" + esc(w.for_date) + "</strong> ended. Duration <strong>" +
    fmt(w.duration_min) + " min</strong> (" + esc(w.duration_source || "measured") +
    "), session RPE <strong>" + rpe + "</strong>.</p>" +
    minimumLine +
    "<div class='table-scroll'><table><thead><tr><th>Exercise</th><th>Status</th><th>Sets actual / planned</th>" +
    "<th>Reps</th><th>kg</th><th>RIR</th></tr></thead><tbody>" + compRows + "</tbody></table></div>" +
    extra +
    repBlock +
    (w.plan_modified
      ? '<h3>Original prescription</h3><div class="table-scroll"><table><thead><tr><th>Exercise</th><th>Status</th>' +
        '<th>Actual / planned sets</th></tr></thead><tbody>' + origRows + '</tbody></table></div>' +
        '<p class="muted">The table above compares against the modified workout plan; this table compares against the original prescription.</p>'
      : "") +
    postBlock +
    '<div class="form-row" style="margin-top:1rem">' +
    '<button class="primary" type="button" id="workout-review">Review workout</button>' +
    '<span class="muted">The deterministic rubric was saved at End workout.</span></div>';
  var review = document.getElementById("workout-review");
  if (review) review.addEventListener("click", function () { openReview(w.workout_id); });
  if (typeof loadWorkoutSummary === "function") loadWorkoutSummary(w.workout_id);
  var postTest = document.getElementById("post-test-form");
  if (postTest) postTest.addEventListener("submit", function (event) {
    event.preventDefault();
    var message = document.getElementById("post-e1rm-msg");
    message.textContent = "Recording…";
    api("/api/state/test", {
      method: "POST",
      body: JSON.stringify({
        exercise_id: document.getElementById("post-test-exercise").value,
        kg: document.getElementById("post-test-kg").value,
        reps: document.getElementById("post-test-reps").value,
        date: document.getElementById("post-test-date").value,
        reason: "post-workout"
      })
    }).then(function (state) {
      var row = (state.e1rm_overrides || []).filter(function (item) {
        return item.exercise_id === document.getElementById("post-test-exercise").value;
      }).pop();
      message.textContent = row
        ? "Measured e1RM recorded: " + row.e1rm_kg + " kg from " + row.effective_from + "."
        : "Measured e1RM recorded.";
      document.getElementById("post-test-kg").value = "";
    }).catch(function (error) {
      message.innerHTML = '<span class="warnbox">' + esc(error.message) + "</span>";
    });
  });
  var postOverride = document.getElementById("post-e1rm-form");
  if (postOverride) postOverride.addEventListener("submit", function (event) {
    event.preventDefault();
    var message = document.getElementById("post-e1rm-msg");
    message.textContent = "Saving…";
    api("/api/state/e1rm", {
      method: "POST",
      body: JSON.stringify({
        exercise_id: document.getElementById("post-e1rm-exercise").value,
        e1rm_kg: document.getElementById("post-e1rm-kg").value,
        effective_from: document.getElementById("post-e1rm-date").value,
        reason: document.getElementById("post-e1rm-reason").value || "post-workout"
      })
    }).then(function () {
      message.textContent = "e1RM override appended.";
      document.getElementById("post-e1rm-kg").value = "";
    }).catch(function (error) {
      message.innerHTML = '<span class="warnbox">' + esc(error.message) + "</span>";
    });
  });
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
      if (typeof updateWorkflowStep === "function") updateWorkflowStep();
    }
  }).catch(function (error) {
    $("#workout-empty").hidden = false;
    $("#workout-empty").innerHTML = '<div class="panel-head"><h2>Workout</h2></div>' +
      '<p class="warnbox">' + esc(error.message) + "</p>";
  });
}

function removeWorkoutSet(setId) {
  if (!activeWorkoutId) return;
  var data = window.__workoutData || {};
  var set = (data.sets || []).find(function (item) {
    return String(item.set_id) === String(setId);
  });
  var label = set ? workoutExerciseLabel(set.exercise_id) + " set " + set.set_index : "this set";
  if (!window.confirm("Remove " + label + "? This records a removal event.")) return;
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
  if (!activeWorkoutId || workoutSetBusy) return;
  var exerciseId = $("#workout-set-exercise").value;
  if (!exerciseId) {
    $("#workout-set-msg").textContent = "Choose an exercise first.";
    $("#workout-set-exercise").setAttribute("aria-invalid", "true");
    $("#workout-set-exercise").focus();
    return;
  }
  $("#workout-set-exercise").removeAttribute("aria-invalid");
  if ($("#workout-set-reps").value === "") {
    $("#workout-set-msg").textContent = "Enter reps (or seconds for a timed movement).";
    $("#workout-set-reps").setAttribute("aria-invalid", "true");
    $("#workout-set-reps").focus();
    return;
  }
  $("#workout-set-reps").removeAttribute("aria-invalid");
  var body = {
    exercise_id: exerciseId,
    load_kg: numericOrNull("#workout-set-load"),
    reps: numericOrNull("#workout-set-reps"),
    rir: numericOrNull("#workout-set-rir"),
    velocity: numericOrNull("#workout-set-velocity"),
    set_index: nextWorkoutSetNumber(exerciseId)
  };
  workoutSetBusy = true;
  var submit = document.querySelector('#workout-set-form button[type="submit"]');
  if (submit) submit.disabled = true;
  $("#workout-set-msg").textContent = "Adding…";
  api("/api/workout/" + activeWorkoutId + "/sets", {
    method: "POST", body: JSON.stringify(body)
  }).then(function (data) {
    $("#workout-set-msg").textContent = "";
    // Keep the exercise and the last set's values for the next set; the athlete can edit
    // any field or add a deliberate different set. Only velocity is optional per set.
    $("#workout-set-velocity").value = "";
    notify("Set added.");
    renderWorkout(data.workout);
  }).catch(function (error) {
    applyFieldErrors(error, $("#workout-set-msg"), {
      exercise_id: "#workout-set-exercise",
      load_kg: "#workout-set-load",
      reps: "#workout-set-reps",
      rir: "#workout-set-rir",
      velocity: "#workout-set-velocity",
    });
  }).finally(function () {
    workoutSetBusy = false;
    if (submit) submit.disabled = false;
  });
}

function submitWorkoutEnd(event) {
  event.preventDefault();
  if (!activeWorkoutId) return;
  var body = {
    duration_min: $("#workout-end-duration").value || null,
    session_rpe: $("#workout-end-srpe").value || null,
    not_recorded: $("#workout-end-not-recorded").checked,
    productivity: $("#workout-end-productivity").value || null,
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
  var swapForm = document.getElementById("workout-swap-form");
  if (swapForm) swapForm.addEventListener("submit", submitWorkoutSwap);
  var swapCancel = document.getElementById("workout-swap-cancel");
  if (swapCancel) swapCancel.addEventListener("click", () => $("#workout-swap-dialog").close());
  ["#workout-set-exercise", "#workout-set-reps"].forEach(function (selector) {
    var input = document.querySelector(selector);
    if (!input) return;
    ["input", "change"].forEach(function (eventName) {
      input.addEventListener(eventName, function () { input.removeAttribute("aria-invalid"); });
    });
  });
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
  var plan = document.getElementById("workout-plan");
  if (plan) plan.addEventListener("click", handleWorkoutHistoryClick);
  loadWorkoutExercises();
  loadActiveWorkout();
});
