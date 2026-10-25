/* Session history: read all sessions and append audited corrections. */
var historyOffset = 0;
var historyTotal = 0;
var historyDetail = null;
var historyLimit = 25;

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
      return "<tr><td>" + esc(s.occurred_on) + "</td><td>" + esc(s.session_id) +
        "</td><td>" + esc(s.session_type) + "</td><td>" + s.working_set_count + "/" + s.set_count +
        "</td><td>" + esc((s.main_lifts || []).join(", ")) + "</td><td>" +
        (s.marks ? '<span class="badge">' + s.marks + "</span>" : '<span class="badge warn">none</span>') +
        " " + edited + " " + review + "</td><td>" +
        '<button class="ghost" type="button" data-history-edit="' + esc(s.session_id) + '">Edit</button> ' +
        '<button class="ghost" type="button" data-history-review="' + esc(s.session_id) + '">Review</button>' +
        "</td></tr>";
    }).join("");
    target.innerHTML = rows
      ? "<table><thead><tr><th>Date</th><th>Session</th><th>Type</th><th>Sets</th>" +
        "<th>Main lifts</th><th>Marks</th><th></th></tr></thead><tbody>" + rows + "</tbody></table>"
      : "<p class='empty'>No sessions in this range.</p>";
    document.getElementById("history-total").textContent =
      historyTotal + " session(s) · showing " + (data.sessions || []).length;
    document.querySelectorAll("[data-history-edit]").forEach(function (button) {
      button.addEventListener("click", function () { openHistoryEdit(button.dataset.historyEdit); });
    });
    document.querySelectorAll("[data-history-review]").forEach(function (button) {
      button.addEventListener("click", function () { openReview(button.dataset.historyReview); });
    });
  } catch (error) {
    target.innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  }
}

function historySetRow(item) {
  return '<tr data-history-set data-set-id="' + (item && item.set_id ? item.set_id : "") + '">' +
    '<td><input list="exercise-options" data-h-exercise value="' + esc(item ? item.exercise_id : "") + '"></td>' +
    '<td><input type="number" step="0.5" data-h-load value="' + (item && item.load_kg != null ? item.load_kg : "") + '"></td>' +
    '<td><input type="number" min="0" data-h-reps value="' + (item && item.reps != null ? item.reps : "") + '"></td>' +
    '<td><input type="number" min="0" max="6" data-h-rir value="' + (item && item.rir != null ? item.rir : "") + '"></td>' +
    '<td><input type="number" step="0.01" min="0" data-h-velocity value="' + (item && item.velocity_mps != null ? item.velocity_mps : "") + '"></td>' +
    '<td><button class="ghost" type="button" data-h-remove>Remove</button></td></tr>';
}

function wireHistoryRemoveButtons() {
  document.querySelectorAll("[data-h-remove]").forEach(function (button) {
    button.onclick = function () { button.closest("tr").remove(); };
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
      "<table><thead><tr><th>Exercise</th><th>kg</th><th>Reps</th><th>RIR</th><th>m/s</th><th></th></tr></thead><tbody>" +
      (data.sets || []).map(historySetRow).join("") + "</tbody></table>";
    wireHistoryRemoveButtons();
    document.getElementById("history-edit-srpe").value =
      data.session_rpe == null ? "" : data.session_rpe;
    document.getElementById("history-edit-duration").value =
      data.duration_min == null ? "" : data.duration_min;
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
    return {
      set_id: row.dataset.setId ? Number(row.dataset.setId) : undefined,
      exercise_id: row.querySelector("[data-h-exercise]").value.trim(),
      load_kg: row.querySelector("[data-h-load]").value || null,
      reps: row.querySelector("[data-h-reps]").value || null,
      rir: row.querySelector("[data-h-rir]").value || null,
      velocity_mps: row.querySelector("[data-h-velocity]").value || null
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
        session_rpe: document.getElementById("history-edit-srpe").value || null,
        duration_min: document.getElementById("history-edit-duration").value || null,
        notes: document.getElementById("history-edit-notes").value || null,
        reason: document.getElementById("history-edit-reason").value || null
      })
    });
    document.getElementById("history-edit-msg").textContent =
      "Correction saved" + ((data.warnings || []).length ? ": " + data.warnings.join("; ") : ".");
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
document.getElementById("history-cancel").addEventListener("click", function () {
  document.getElementById("history-edit-panel").hidden = true;
});
