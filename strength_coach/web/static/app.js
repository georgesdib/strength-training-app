/* Local UI over the strength-coach HTTP API. No framework, no external assets. */
const $ = (sel) => document.querySelector(sel);
const today = () => new Date().toLocaleDateString("en-CA");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function sessionLabel(value) {
  const text = String(value ?? "");
  if (text.startsWith("volume_fill_")) {
    return `Volume fill (${text.slice("volume_fill_".length).replaceAll("_", " ")} omitted)`;
  }
  if (text === "technique") return "Technique (week complete)";
  return text;
}

function fmt(value, digits = 1) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits).replace(/\.0+$/, "") : esc(value);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

let toastTimer = null;
function notify(message, kind = "ok") {
  const toast = document.querySelector("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.className = "toast " + (kind === "error" ? "toast-error" : "toast-ok");
  toast.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 4500);
}

function setView(name, options = {}) {
  document.querySelectorAll("#nav button").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((v) => {
    v.classList.toggle("active", v.id === "view-" + name);
  });
  if (name === "review") fillSessionSelect();
  if (name === "readiness") loadReadiness($("#readiness-date").value);
  if (name === "exercises") loadExerciseCatalog();
  if (name === "cardio") loadCardio();
  if (name === "measures") loadMeasurements();
  if (name === "prescribe") { loadFatigue(); loadContinuity(); loadVolume(); loadVolumeBudget(); }
  if (name === "workout") { loadReadiness($("#readiness-date").value); updateWorkflowStep(); }
  if (name === "docs") loadDocs(options.doc, options.anchor);
  if (name === "state") loadState();
  if (name === "settings") loadSettings();
  if (name === "history") loadHistory();
  if (name === "outcomes") loadOutcomes();
  if (name === "longevity") loadLongevity();
  if (!options.fromHash && location.hash !== "#" + name) {
    history.replaceState(null, "", "#" + name);
  }
}

document.querySelectorAll("#nav button").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});
document.querySelectorAll("[data-view-link]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    setView(link.dataset.viewLink);
  });
});
// Docs links are hash routes; handle them directly so a stale hash or a listener-order
// problem cannot leave the docs view on its default page.
document.addEventListener("click", (event) => {
  const anchor = event.target?.closest?.('a[href^="#docs?doc="]');
  if (!anchor) return;
  event.preventDefault();
  const href = anchor.getAttribute("href") || "";
  const params = new URLSearchParams(href.slice(href.indexOf("?") + 1));
  setView("docs", {
    doc: params.get("doc"),
    anchor: params.get("anchor"),
    fromHash: true,
  });
  history.replaceState(null, "", href);
});
/* Collapsible left menu. */
function setSidebar(open) {
  const sidebar = document.querySelector("#sidebar");
  const backdrop = document.querySelector("#sidebar-backdrop");
  const toggle = document.querySelector("#menu-toggle");
  if (!sidebar || !backdrop || !toggle) return;
  sidebar.hidden = !open;
  backdrop.hidden = !open;
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  document.body.classList.toggle("menu-open", open);
}
document.querySelector("#menu-toggle")?.addEventListener("click", () => setSidebar(true));
document.querySelector("#sidebar-close")?.addEventListener("click", () => setSidebar(false));
document.querySelector("#sidebar-backdrop")?.addEventListener("click", () => setSidebar(false));
document.querySelectorAll("#nav button").forEach((button) => {
  button.addEventListener("click", () => setSidebar(false));
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setSidebar(false);
});

function routeFromHash() {
  const raw = location.hash.replace("#", "") || "dashboard";
  const [name, query] = raw.split("?");
  const params = new URLSearchParams(query || "");
  return {name, doc: params.get("doc"), anchor: params.get("anchor")};
}

function applyHashRoute() {
  const route = routeFromHash();
  if (document.getElementById("view-" + route.name)) {
    setView(route.name, {...route, fromHash: true});
  }
}
window.addEventListener("hashchange", applyHashRoute);

/* --- dashboard ---------------------------------------------------------- */
async function loadOverview() {
  try {
    const data = await api("/api/overview");
    window.__overview = data;
    $("#today-title").textContent = data.profile?.primary_goal
      ? "Coach for " + data.profile.primary_goal : "No athlete state yet";
    $("#today-sub").textContent = "Block week " + (data.block_week ?? "unknown")
      + " · " + data.today + " · " + (data.unreviewed.length ? data.unreviewed.length
        + " unreviewed session(s)" : "reviews up to date");
    const readiness = data.readiness;
    const signal = data.injury_signal;
    const formEval = data.form_evaluation || {};
    const formStatus = {
      collecting: "collecting", threshold_met_waiting: "waiting",
      ready: "ready", extended: "extended", insufficient: "insufficient",
    }[formEval.status] || formEval.status || "unknown";
    const cards = [
      ["Form review", formEval.low_events == null ? "—" :
        formEval.low_events + "/" + formEval.target_events + " low",
        formEval.low_lifts == null ? "" :
          formEval.low_lifts + "/" + formEval.target_lifts + " lifts · " +
          (formEval.due_on ? "due " + formEval.due_on : formStatus)],
      ["Readiness today", data.readiness_score?.score != null
        ? data.readiness_score.score.toFixed(2) : "unknown",
        data.readiness_score?.status + (data.readiness_score?.basis ? " · " + data.readiness_score.basis : "")],
      ["Block week", data.block_week ?? "unknown", "erector ramp / DUP"],
      ["Injury signal", signal?.status ?? "unknown", signal?.summary ?? ""],
      ["Cardio (4 wk avg)", data.cardio ? data.cardio.average_weekly_minutes + " min/wk" : "unknown",
        data.cardio ? "reference " + data.cardio.reference_min + "-" + data.cardio.reference_max
          + " · " + data.cardio.sessions + " session(s)" : "no entry"],
      ["Calibration", (data.calibration?.high_sessions ?? 0) + " reviewed",
        (data.calibration?.agreement == null ? "agreement —" : data.calibration.agreement + "% agreement")
        + " · " + (data.calibration?.comparable_items ?? 0) + " comparable"],
      ["Unreviewed", data.unreviewed.length, data.unreviewed.length ? "run review to catch up" : "all caught up"],
    ];
    $("#cards").innerHTML = cards.map(([label, value, sub]) => `
      <div class="card"><div class="label">${esc(label)}</div>
      <div class="value">${esc(value)}</div><div class="sub">${esc(sub)}</div></div>`).join("");
    renderFormFollowup(formEval);
    renderRecent(data.sessions);
    renderCalibration(data.calibration);
    fillSessionSelect();
    loadProgress();
    loadRepVelocityProgress();
    loadReviews();
    // The hero button reloads this whole page; the stamp is the only visible proof it ran.
    const stamp = $("#today-updated");
    if (stamp) stamp.textContent = "Updated " + new Date().toLocaleTimeString();
  } catch (error) {
    $("#today-title").textContent = "Could not load";
    $("#today-sub").textContent = error.message;
  }
}

async function refreshToday() {
  const button = $("#today-refresh");
  if (button) {
    button.disabled = true;
    button.textContent = "Refreshing…";
  }
  try {
    await loadOverview();
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "Refresh";
    }
  }
}

const todayRefresh = $("#today-refresh");
if (todayRefresh) todayRefresh.addEventListener("click", refreshToday);

function renderFormFollowup(formEval) {
  const target = $("#form-followup");
  if (!target) return;
  if (!formEval || !formEval.status) {
    target.innerHTML = "<p class='empty'>No form evaluation recorded.</p>";
    return;
  }
  const label = {
    collecting: "collecting", threshold_met_waiting: "waiting for window",
    ready: "ready to analyse", extended: "extended", insufficient: "insufficient",
  }[formEval.status] || formEval.status;
  target.innerHTML = `<p><strong>${esc(label)}</strong> · ${esc(formEval.message || "")}</p>
    <p class="muted">Started ${esc(formEval.started_on)} · 12-week end ${esc(formEval.window_end)}
      · extension ${esc(formEval.extension_end)}${formEval.due_on ? " · due " + esc(formEval.due_on) : ""}</p>
    <p>Low-form events: <strong>${formEval.low_events}</strong> / ${formEval.target_events}
      · lifts: <strong>${formEval.low_lifts}</strong> / ${formEval.target_lifts}</p>
    <p class="muted">${esc(formEval.note || "")}</p>
    <p class="muted">This is a prospective follow-up because the earlier retrospective association
      was near zero. Historical backfilled ratings are not counted. At the due date, the threshold
      decides whether to analyse, extend, or report insufficient data; it never changes a load.</p>
    <p class="muted">Details:
      <a href="#docs?doc=docs/FORM-PROSPECTIVE.md">prospective protocol</a> ·
      <a href="#docs?doc=docs/FORM-USE-EVIDENCE.md">evidence and allowed uses</a> ·
      <a href="#outcomes" data-view-link="outcomes">Outcomes → Form trend</a>.</p>`;
}

function renderCalibration(data) {
  if (!data) {
    $("#calibration").innerHTML = "<p class='muted'>No calibration data.</p>";
    return;
  }
  const rows = (data.items || []).map((item) =>
    "<tr><td>" + esc(item.item) + "</td><td>" + item.marks + "</td><td>" +
    item.comparable + "</td><td>" + esc(item.status) + "</td></tr>").join("");
  $("#calibration").innerHTML =
    "<p class='muted'><strong>" + data.high_sessions + "</strong> high-confidence sessions · " +
    (data.agreement == null ? "agreement unknown" : data.agreement + "% agreement") +
    " · " + (data.mae == null ? "MAE unknown" : "MAE " + data.mae) +
    " · " + data.comparable_items + " comparable items.</p>" +
    "<table><thead><tr><th>Item</th><th>high marks</th><th>comparable</th><th>status</th></tr></thead><tbody>" +
    rows + "</tbody></table>" +
    (data.gaps && data.gaps.length
      ? "<p class='warnbox'><strong>Still collecting:</strong> " + esc(data.gaps.join(", ")) + "</p>"
      : "<p class='muted'>All items have 10 marks and 10 comparable scores.</p>") +
    "<p class='muted'>" + esc(data.next_action) + "</p>";
}

async function loadProgress() {
  try {
    const data = (await api("/api/progress")) || {};
    const coverage = data.coverage || {};
    const p = data.performance || {};
    const latest = p.latest ? `${p.latest.ratio.toFixed(3)} on ${p.latest.date}` : "insufficient";
    const rows = (data.volume || []).filter((row) => row.status !== "untargeted").slice(0, 8)
      .map((row) => `<tr><td>${esc(row.pattern)}</td><td>${row.average}</td>
        <td>${esc(row.status)}</td></tr>`).join("");
    const back = data.back?.level == null ? "none logged" :
      `${data.back.level}/3 on ${data.back.date}`;
    const attendance = data.attendance || {};
    const families = attendance.families || {};
    $("#progress").innerHTML = `
      <p class="muted">sRPE coverage: ${coverage.with_srpe ?? "—"}/${coverage.sessions ?? "—"}
        (${coverage.pct ?? "—"}%). Performance ratio: <strong>${esc(latest)}</strong>;
        median ${p.median_ratio ?? "—"} across ${p.n} sessions. Back: ${esc(back)}.</p>
      <p>Attendance: <strong>${attendance.completed ?? "unknown"}</strong> /
        ${attendance.target ?? "unknown"} (${attendance.pct ?? "unknown"}%). Shortfall:
        ${attendance.target_shortfall ?? "unknown"}. Families:
        squat ${families.squat ?? 0} · hinge ${families.hinge ?? 0} · bench ${families.bench ?? 0}.</p>
      <table><thead><tr><th>Pattern</th><th>avg sets/week</th><th>status</th></tr></thead>
      <tbody>${rows || "<tr><td colspan='3' class='muted'>no targeted volume</td></tr>"}</tbody></table>
      <p class="muted">${esc(data.note)}</p>`;
  } catch (error) {
    $("#progress").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadRepVelocityProgress() {
  try {
    const data = await api("/api/rep-velocity/analysis?weeks=12");
    if (!data.available) {
      $("#rep-velocity-progress").innerHTML =
        "<p class='muted'>No per-rep data yet. Import an optional per-rep CSV in Workout mode.</p>";
      return;
    }
    const corr = (data.correlations || []).map((row) =>
      "<tr><td>" + esc(row.label) + "</td><td>" + row.n + "</td><td>" +
      (row.r == null ? "—" : row.r) + "</td><td>" + esc(row.status) + "</td></tr>").join("");
    const sessionRows = (data.sessions || []).slice(-12).reverse().map((row) =>
      "<tr><td>" + esc(row.date) + "</td><td>" + esc(row.exercise_id) + "</td><td>" +
      (row.mean_loss_pct == null ? "—" : row.mean_loss_pct) + "</td><td>" +
      (row.srpe == null ? "—" : row.srpe) + "</td><td>" +
      (row.readiness == null ? "—" : row.readiness) + "</td><td>" +
      (row.next ? (row.next.delta_pct + "% / " + row.next.days + "d") : "—") +
      "</td></tr>").join("");
    $("#rep-velocity-progress").innerHTML =
      "<p class='muted'>" + esc(data.from) + " to " + esc(data.to) + " · " +
      data.set_count + " sets across " + data.session_count + " sessions. " +
      "Minimum " + data.min_pairs + " pairs for a correlation.</p>" +
      "<table><thead><tr><th>Association</th><th>n</th><th>r</th><th>status</th></tr></thead>" +
      "<tbody>" + corr + "</tbody></table>" +
      "<details><summary>Recent session/exercise rows</summary>" +
      "<table><thead><tr><th>Date</th><th>Exercise</th><th>Mean loss %</th><th>sRPE</th>" +
      "<th>Readiness</th><th>Next e1RM</th></tr></thead><tbody>" +
      (sessionRows || "<tr><td colspan='6' class='muted'>none</td></tr>") +
      "</tbody></table></details>" +
      "<p class='muted'>" + esc(data.note) + "</p>";
  } catch (error) {
    $("#rep-velocity-progress").innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  }
}

async function loadReviews() {
  try {
    const data = await api("/api/reviews");
    const tasks = data.tasks || [];
    const actionable = tasks.filter((t) => ["due", "attention", "insufficient", "snoozed"].includes(t.status));
    if (!actionable.length) {
      $("#reviews").innerHTML = "<p class='muted'>No reviews due.</p>";
      return;
    }
    const cards = actionable.map((task) => {
      const details = (task.steps || []).map((s) => `<li>${esc(s)}</li>`).join("");
      const dont = (task.dont || []).map((s) => `<li>${esc(s)}</li>`).join("");
      const doc = task.doc
        ? `<a href="#docs?doc=${encodeURIComponent(task.doc)}">${esc(task.doc)}</a>`
        : "";
      const actions = task.periodic
        ? `<details><summary>Mark reviewed</summary>
             <div class="form-row">
               <label>Decision <select id="review-decision-${esc(task.key)}">
                 <option value="kept">kept</option><option value="changed">changed</option>
                 <option value="insufficient">insufficient</option>
                 <option value="not_applicable">not applicable</option>
               </select></label>
               <label class="grow">Note <input id="review-note-${esc(task.key)}" placeholder="optional"></label>
               <button type="button" onclick="completeReview('${esc(task.key)}')">Save review</button>
               <button type="button" class="ghost" onclick="snoozeReview('${esc(task.key)}')">Snooze 2 weeks</button>
             </div></details>`
        : `<p class="muted">Use the linked workflow; this is a data-state reminder.</p>`;
      return `<div class="panel" style="margin-bottom:8px">
        <div class="panel-head"><h3>${esc(task.label)}</h3>
          <span class="badge ${task.status === "ok" ? "" : "warn"}">${esc(task.status)}</span></div>
        <p><strong>${esc(task.summary)}</strong></p>
        <p class="muted">${esc(task.why)}</p>
        <ul class="list">${details}</ul>
        ${dont ? `<p class="muted"><strong>Do not:</strong></p><ul class="list">${dont}</ul>` : ""}
        <p class="muted">${doc}</p>${actions}</div>`;
    }).join("");
    $("#reviews").innerHTML = `<p class="muted">${data.due_count} item(s) need attention.</p>${cards}`;
  } catch (error) {
    $("#reviews").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function completeReview(taskKey) {
  const decision = document.querySelector(`#review-decision-${CSS.escape(taskKey)}`).value;
  const note = document.querySelector(`#review-note-${CSS.escape(taskKey)}`).value;
  try {
    await api("/api/reviews", { method: "POST", body: JSON.stringify({
      task_key: taskKey, action: "completed", decision, note,
    }) });
    notify("Review marked complete.");
    await loadReviews();
  } catch (error) {
    notify(error.message, "error");
    $("#reviews").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function snoozeReview(taskKey) {
  try {
    await api("/api/reviews", { method: "POST", body: JSON.stringify({
      task_key: taskKey, action: "snoozed",
    }) });
    notify("Review snoozed.");
    await loadReviews();
  } catch (error) {
    notify(error.message, "error");
    $("#reviews").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

function renderRecent(sessions) {
  if (!sessions.length) { $("#recent").innerHTML = "<p class='empty'>No sessions.</p>"; return; }
  $("#recent").innerHTML = `<table><thead><tr><th>Date</th><th>Day</th><th>Sets</th>
    <th>Main lifts</th><th>Marks</th><th></th></tr></thead><tbody>` +
    sessions.map((s) => `<tr><td>${esc(s.occurred_on)}</td><td>${esc(sessionLabel(s.session_type))}</td>
      <td>${s.working_set_count}/${s.set_count}</td>
      <td>${esc((s.main_lifts || []).join(", "))}</td>
      <td>${s.marks ? '<span class="badge">' + s.marks + "</span>" : '<span class="badge warn">none</span>'}</td>
      <td><button class="ghost" onclick="openReview('${esc(s.session_id)}')">Review</button></td></tr>`).join("")
    + "</tbody></table>";
}

function reviewWorkoutSummary(workout) {
  if (!workout) return "";
  const comp = workout.comparison || { items: [], extra: [] };
  const rows = (comp.items || []).map((row) => `<tr><td>${esc(row.exercise_id)}</td>
    <td>${esc(row.status)}</td><td>${row.actual_sets} / ${row.planned_sets}</td>
    <td>${row.actual_reps.length ? row.actual_reps.join(", ") : "—"}</td>
    <td>${row.actual_load_kg.length ? row.actual_load_kg.join(", ") : "—"}</td></tr>`).join("");
  const original = workout.plan_modified && workout.original_comparison
    ? `<h3>Original prescription</h3><table><thead><tr><th>Exercise</th><th>Status</th>
       <th>Actual / planned</th></tr></thead><tbody>${(workout.original_comparison.items || [])
       .map((row) => `<tr><td>${esc(row.exercise_id)}</td><td>${esc(row.status)}</td>
       <td>${row.actual_sets} / ${row.planned_sets}</td></tr>`).join("")}</tbody></table>`
    : "";
  return `<details open><summary><strong>Actual vs planned</strong></summary>
    <table><thead><tr><th>Exercise</th><th>Status</th><th>Sets actual / planned</th>
    <th>Reps</th><th>kg</th></tr></thead><tbody>${rows}</tbody></table>
    ${original}</details>`;
}

function openReview(session) {
  setView("review");
  $("#review-session").value = session;
  loadReview(session);
}

/* --- outcomes ------------------------------------------------------------ */
async function loadOutcomes() {
  const weeks = $("#outcomes-weeks").value;
  const day = $("#outcomes-date").value;
  $("#outcomes-result").innerHTML = "<p class='empty'>Building review…</p>";
  try {
    const query = new URLSearchParams({ weeks });
    if (day) query.set("date", day);
    const data = (await api("/api/outcomes?" + query.toString())) || {};
    const period = data.window || {};
    const strength = data.strength || {};
    const lifts = (strength.main_lifts || []).map((lift) => `
      <tr><td><strong>${esc(lift.exercise_id)}</strong><div class="muted">n=${lift.n}</div></td>
      <td>${fmt(lift.first_e1rm, 1)} → ${fmt(lift.last_e1rm, 1)} kg</td>
      <td>${lift.change_kg > 0 ? "+" : ""}${fmt(lift.change_kg, 1)} kg
        ${lift.change_pct == null ? "" : "(" + lift.change_pct + "%)"}</td>
      <td>${fmt(lift.best_e1rm, 1)} kg</td></tr>`).join("");
    const volume = (strength.volume || []).map((row) => `
      <tr><td>${esc(row.pattern)}</td><td>${row.average_per_week}</td>
      <td>${row.total_sets}</td><td>${row.weeks_present}</td></tr>`).join("");
    const attendance = strength.attendance || {};
    const longevity = data.longevity || {};
    const cardio = longevity.cardio || {};
    const metrics = Object.entries(longevity.measurements || {}).map(([key, row]) => `
      <tr><td>${esc(key)}</td><td>${row.latest_value ?? "—"}</td>
      <td>${row.change == null ? "—" : (row.change > 0 ? "+" : "") + row.change}</td>
      <td>${row.latest_on ?? "—"}</td></tr>`).join("");
    const symptoms = (strength.symptoms?.regions || {});
    const symptomRows = Object.entries(symptoms).map(([region, row]) => `
      <tr><td>${esc(region)}</td><td>${row.flares}</td><td>${row.readings}</td>
      <td>${esc(row.latest_on)} · level ${row.latest_level}</td></tr>`).join("");
    const cardioWeeks = Object.entries(cardio.weekly_minutes || {}).map(([week, minutes]) =>
      `<tr><td>${esc(week)}</td><td>${fmt(minutes, 1)} min</td></tr>`).join("");
    const modalities = Object.entries(cardio.by_modality || {}).map(([name, count]) =>
      `<tr><td>${esc(name)}</td><td>${count}</td></tr>`).join("");
    const readinessFields = Object.entries(longevity.readiness?.fields || {}).map(([field, row]) => `
      <tr><td>${esc(field)}</td><td>${row.n}</td><td>${row.average ?? "—"}</td>
      <td>${row.first ?? "—"} → ${row.last ?? "—"}</td></tr>`).join("");
    $("#outcomes-result").innerHTML = `
      <p class="muted">${esc(period.from ?? "unknown")} to ${esc(period.to ?? "unknown")} · ${period.weeks ?? "—"} weeks</p>
      <h3>Strength</h3>
      <p class="muted">e1RM values are estimates from working sets, not measured maximums.</p>
      <table><thead><tr><th>Lift</th><th>First → last e1RM</th><th>Change</th><th>Best</th></tr></thead>
      <tbody>${lifts || "<tr><td colspan='4' class='muted'>no main-lift e1RM observations</td></tr>"}</tbody></table>
      <p class="muted">Attendance: ${attendance.completed ?? "unknown"} /
        ${attendance.target ?? "unknown"} (${attendance.pct ?? "unknown"}%).
        Shortfall: ${attendance.target_shortfall ?? "unknown"}.
        Families: squat ${attendance.families?.squat ?? 0} · hinge ${attendance.families?.hinge ?? 0}
        · bench ${attendance.families?.bench ?? 0}.
        Duration: ${attendance.duration?.mean_min ?? "unknown"} min
        (${attendance.duration?.measured_n ?? 0} measured).
        Injury-free weeks: ${attendance.injury_free_weeks ?? "unknown"}.
        ${esc(attendance.note || "")}</p>
      <h3>Volume</h3>
      <table><thead><tr><th>Pattern</th><th>avg sets/week</th><th>total sets</th><th>weeks present</th></tr></thead>
      <tbody>${volume || "<tr><td colspan='4' class='muted'>no working-set volume</td></tr>"}</tbody></table>
      <p class="muted">${esc(data.note)}</p>`;
    await loadReadinessFeedback(weeks, day);
    await loadProspective(weeks, day);
  } catch (error) {
    $("#outcomes-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

$("#outcomes-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadOutcomes();
});

$("#longevity-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadLongevity();
});

async function loadFormTrend(weeks, day) {
  const target = $("#form-trend-result");
  if (!target) return;
  try {
    const query = new URLSearchParams({ weeks });
    if (day) query.set("date", day);
    const data = await api("/api/form-trend?" + query.toString());
    const rows = (data.forms || []).map((row) => `
      <tr><td><strong>${esc(row.exercise_id)}</strong></td>
      <td>${row.latest_rating}/5 <span class="muted">${esc(row.latest_on)}</span></td>
      <td>${row.current_avg ?? "—"} / ${row.baseline_avg ?? "—"}</td>
      <td>${row.change == null ? "—" : (row.change > 0 ? "+" : "") + row.change}</td>
      <td><span class="badge ${row.status === "down" ? "warn" : ""}">${esc(row.status)}</span></td>
      <td class="muted">n ${row.current_n}/${row.baseline_n} · low ${row.low_current}</td></tr>`).join("");
    target.innerHTML = rows
      ? `<p class="muted">${esc(data.window.current_from)} to ${esc(data.window.current_to)}
         · baseline ${esc(data.window.baseline_from)} to ${esc(data.window.baseline_to)}</p>
         <table><thead><tr><th>Lift</th><th>latest</th><th>current / baseline avg</th>
         <th>change</th><th>status</th><th>sessions</th></tr></thead>
         <tbody>${rows}</tbody></table>
         <p class="muted">Low-form events (≤2) in this window: <strong>${data.low_form_events ?? 0}</strong>
         across ${data.low_form_lifts ?? 0} lift(s). ${esc(data.note)}</p>`
      : `<p class="empty">No form ratings in this window.</p>`;
  } catch (error) {
    target.innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadProspective(weeks, day) {
  const target = $("#prospective-result");
  if (!target) return;
  try {
    const query = new URLSearchParams({ weeks });
    if (day) query.set("date", day);
    const data = (await api("/api/prospective?" + query.toString())) || {};
    const period = data.window || {};
    const lifts = (data.strength?.lifts || []).map((lift) => `
      <tr><td>${esc(lift.exercise_id)}</td><td>${esc(lift.status)}</td>
      <td>${lift.baseline_median_e1rm ?? "—"} → ${lift.current_median_e1rm ?? "—"} kg</td>
      <td>${lift.change_pct == null ? "—" : lift.change_pct + "%"}</td>
      <td>${lift.baseline_n}/${lift.current_n}</td></tr>`).join("");
    const flags = (data.flags || []).length
      ? data.flags.map((flag) => `<li><strong>${esc(flag.code)}</strong> — ${esc(flag.detail)}</li>`).join("")
      : "<li class='muted'>none</li>";
    const attendance = data.attendance || {};
    const work = data.work || {};
    const rir = data.rir || {};
    const duration = data.duration || {};
    target.innerHTML = `
      <p class="muted">${esc(period.current_from ?? "unknown")} to ${esc(period.current_to ?? "unknown")}
        · baseline ${esc(period.baseline_from ?? "unknown")} to ${esc(period.baseline_to ?? "unknown")}</p>
      <table><thead><tr><th>Lift</th><th>status</th><th>median e1RM</th><th>change</th><th>n base/current</th></tr></thead>
      <tbody>${lifts || "<tr><td colspan='5' class='muted'>no stable-lift observations</td></tr>"}</tbody></table>
      <p>Attendance: ${attendance.completed ?? "unknown"} / ${attendance.target ?? "unknown"}
        (${attendance.pct ?? "unknown"}%). Work: ${esc(work.status || "unknown")}
        (${work.actual_sets ?? "—"}/${work.planned_sets ?? "—"} sets).
        RIR adherence: ${rir.adherence ?? "unknown"} (${rir.n ?? 0} sets).
        Duration: ${duration.median_min ?? "unknown"} min (${duration.measured_n ?? 0} measured).</p>
      <h3>Review flags</h3><ul class="list">${flags}</ul>
      <p class="muted">${esc(data.note || "")}</p>`;
  } catch (error) {
    target.innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadLongevity() {
  const weeks = $("#longevity-weeks").value;
  const day = $("#longevity-date").value;
  $("#longevity-summary").innerHTML = "<p class='empty'>Building longevity view…</p>";
  $("#longevity-details").innerHTML = "";
  try {
    const query = new URLSearchParams({ weeks });
    if (day) query.set("date", day);
    const data = (await api("/api/outcomes?" + query.toString())) || {};
    const period = data.window || {};
    const longevity = data.longevity || {};
    const cardio = longevity.cardio || {};
    const metrics = longevity.measurements || {};
    const readiness = longevity.readiness || {};
    const fields = readiness.fields || {};
    const symptoms = (data.strength && data.strength.symptoms && data.strength.symptoms.regions) || {};
    const attendance = (data.strength && data.strength.attendance) || {};
    const cardioAvg = cardio.rolling_4w_average ?? cardio.average_weekly_minutes;
    const refMin = cardio.reference_min ?? 150;
    const refMax = cardio.reference_max ?? 300;
    const metricCount = Object.keys(metrics).length;
    const readinessCount = Object.values(fields).filter((row) => row.n > 0).length;
    const regions = Object.values(symptoms);
    const symptomReadings = regions.reduce((sum, row) => sum + (row.readings || 0), 0);
    const flares = regions.reduce((sum, row) => sum + (row.flares || 0), 0);
    const well = [];
    const attention = [];
    if (cardioAvg != null && cardioAvg >= refMin) well.push("Cardio is at or above the WHO reference (" + cardioAvg + " min/wk).");
    else if (cardioAvg == null) attention.push("No cardio minutes captured in this window.");
    else attention.push("Cardio is below the WHO reference (" + cardioAvg + " vs " + refMin + " min/wk).");
    if (metricCount) well.push(metricCount + " longevity measurement(s) captured.");
    else attention.push("No periodic measurements in this window.");
    if (readinessCount >= 7) well.push("Readiness coverage is complete (" + readinessCount + " fields).");
    else attention.push("Readiness coverage is partial (" + readinessCount + "/7 fields).");
    if (symptomReadings === 0) attention.push("No symptom readings; flare status is unknown, not zero.");
    else if (flares === 0) well.push("No recorded symptom flares in the window.");
    else attention.push(flares + " symptom flare(s) recorded; review context.");
    if (attendance.pct != null && attendance.pct >= 80) well.push("Attendance is at or above 80%.");
    else if (attendance.pct != null) attention.push("Attendance is below 80% (" + attendance.pct + "%).");
    else attention.push("Attendance target is unknown.");
    const metricRows = Object.entries(metrics).map(([key, row]) =>
      "<tr><td>" + esc(key) + "</td><td>" + (row.latest_value ?? "—") + "</td><td>" +
      (row.change == null ? "—" : (row.change > 0 ? "+" : "") + row.change) +
      "</td><td>" + esc(row.latest_on || "—") + "</td></tr>").join("");
    const readinessRows = Object.entries(fields).map(([field, row]) =>
      "<tr><td>" + esc(field) + "</td><td>" + row.n + "</td><td>" +
      (row.average ?? "—") + "</td><td>" + (row.first ?? "—") + " → " +
      (row.last ?? "—") + "</td></tr>").join("");
    const symptomRows = Object.entries(symptoms).map(([region, row]) =>
      "<tr><td>" + esc(region) + "</td><td>" + row.flares + "</td><td>" +
      row.readings + "</td><td>" + esc(row.latest_on || "—") + " · level " +
      (row.latest_level ?? "—") + "</td></tr>").join("");
    const cardioWeeks = Object.entries(cardio.weekly_minutes || {}).map(([week, minutes]) =>
      "<tr><td>" + esc(week) + "</td><td>" + fmt(minutes, 1) + " min</td></tr>").join("");
    $("#longevity-summary").innerHTML =
      "<p class='muted'>" + esc(period.from ?? "unknown") + " to " + esc(period.to ?? "unknown") +
      " · " + esc(weeks) + " weeks.</p>" +
      "<div class='cards'>" +
      "<div class='card'><div class='label'>Cardio</div><div class='value'>" +
      (cardioAvg == null ? "unknown" : cardioAvg + " min/wk") + "</div><div class='sub'>reference " +
      refMin + "–" + refMax + " · context only</div></div>" +
      "<div class='card'><div class='label'>Measurements</div><div class='value'>" +
      metricCount + "</div><div class='sub'>captured metrics</div></div>" +
      "<div class='card'><div class='label'>Readiness</div><div class='value'>" +
      readinessCount + "/7</div><div class='sub'>fields with data</div></div>" +
      "<div class='card'><div class='label'>Symptoms</div><div class='value'>" +
      (symptomReadings ? flares + " flare(s)" : "unknown") + "</div><div class='sub'>" +
      symptomReadings + " reading(s)</div></div></div>" +
      "<h3>Going well</h3><ul class='list'>" +
      (well.length ? well.map((x) => "<li>" + esc(x) + "</li>").join("") : "<li class='muted'>nothing confidently positive</li>") +
      "</ul><h3>Needs attention</h3><ul class='list'>" +
      (attention.length ? attention.map((x) => "<li>" + esc(x) + "</li>").join("") : "<li class='muted'>none identified</li>") +
      "</ul><p class='muted'>These are descriptive context labels, not medical advice and not a prescription change.</p>";
    $("#longevity-details").innerHTML =
      "<h3>Cardio weeks</h3><table><thead><tr><th>Week</th><th>minutes</th></tr></thead><tbody>" +
      (cardioWeeks || "<tr><td colspan='2' class='muted'>no cardio entries</td></tr>") + "</tbody></table>" +
      "<h3>Measurements</h3><table><thead><tr><th>Metric</th><th>latest</th><th>change</th><th>date</th></tr></thead><tbody>" +
      (metricRows || "<tr><td colspan='4' class='muted'>none in this window</td></tr>") + "</tbody></table>" +
      "<h3>Readiness fields</h3><table><thead><tr><th>Field</th><th>n</th><th>average</th><th>first → last</th></tr></thead><tbody>" +
      (readinessRows || "<tr><td colspan='4' class='muted'>no readiness fields</td></tr>") + "</tbody></table>" +
      "<h3>Symptoms</h3><table><thead><tr><th>Region</th><th>flares</th><th>readings</th><th>latest</th></tr></thead><tbody>" +
      (symptomRows || "<tr><td colspan='4' class='muted'>no symptom entries — unknown, not “no flare”</td></tr>") + "</tbody></table>" +
      "<p class='muted'>" + esc(longevity.note || "") + "</p>";
  } catch (error) {
    $("#longevity-summary").innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  }
}

async function loadReadinessFeedback(weeks, day) {
  const target = $("#readiness-feedback-result");
  if (!target) return;
  try {
    const query = new URLSearchParams({ weeks });
    if (day) query.set("date", day);
    const data = await api("/api/readiness/feedback?" + query.toString());
    const aggregate = data.aggregate || {};
    const rows = (data.events || []).map((event) => `
      <tr><td>${esc(event.applied_on)}</td><td>${esc(event.next_session_on || "—")}</td>
      <td>${event.adherence ? event.adherence.actual_sets + "/" + event.adherence.planned_sets : "—"}</td>
      <td>${event.next?.srpe ?? "—"}</td><td>${event.next?.rir_adherence ?? "—"}</td>
      <td>${event.e1rm_change_pct == null ? "—" : event.e1rm_change_pct + "%"}</td>
      <td>${event.symptom_flare_7d == null ? "unknown" : (event.symptom_flare_7d ? "yes" : "no")}</td></tr>`).join("");
    target.innerHTML = `<p>Events: ${aggregate.n_events ?? 0}
      · with next session: ${aggregate.n_with_next_session ?? 0}
      · mean sRPE: ${aggregate.mean_srpe ?? "unknown"}
      · mean RIR adherence: ${aggregate.mean_rir_adherence ?? "unknown"}
      · mean set adherence: ${aggregate.mean_set_adherence ?? "unknown"}</p>
      <table><thead><tr><th>Reduction</th><th>next session</th><th>sets done/planned</th><th>sRPE</th>
      <th>RIR adherence</th><th>e1RM change</th><th>flare</th></tr></thead>
      <tbody>${rows || "<tr><td colspan='7' class='muted'>no MOD-FAT-001 provenance</td></tr>"}</tbody></table>
      ${(data.warnings || []).map((warning) => `<p class="muted">! ${esc(warning)}</p>`).join("")}
      <p class="muted">${esc(data.note || "")}</p>`;
  } catch (error) {
    target.innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

/* --- prescribe ---------------------------------------------------------- */
$("#prescribe-date").value = today();
$("#prescribe-date").addEventListener("change", loadVolumeBudget);
function syncMinimumSession() {
  const on = $("#prescribe-minimum").checked;
  $("#prescribe-minimum-options").hidden = !on;
  $("#prescribe-target").disabled = !on;
  $("#prescribe-minimum-main").disabled = !on;
  if (!on) $("#prescribe-minimum-main").checked = false;
}
$("#prescribe-minimum").addEventListener("change", syncMinimumSession);

function syncTechniqueThrottle() {
  $("#prescribe-throttle-pattern-wrap").hidden = !$("#prescribe-technique").checked;
}

$("#prescribe-technique").addEventListener("change", syncTechniqueThrottle);
syncMinimumSession();

let prescribeBusy = false;
let prescribeQueued = false;

$("#prescribe-apply-selection").addEventListener("change", () => {
  const llmWrap = $("#prescribe-selection-llm-wrap");
  const confirmWrap = $("#prescribe-selection-confirm-wrap");
  const on = $("#prescribe-apply-selection").checked;
  llmWrap.hidden = !on;
  confirmWrap.hidden = !on;
  if (!on) {
    $("#prescribe-selection-llm").checked = false;
    $("#prescribe-selection-confirm").checked = false;
  }
  if (prescribeBusy) prescribeQueued = true;
});
$("#prescribe-selection-llm").addEventListener("change", () => {
  if (prescribeBusy) prescribeQueued = true;
});
$("#prescribe-selection-confirm").addEventListener("change", () => {
  if (prescribeBusy) prescribeQueued = true;
});

let lastPrescribePayload = null;

$("#prescribe-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (prescribeBusy) {
    prescribeQueued = true;
    return;
  }
  prescribeBusy = true;
  const date = $("#prescribe-date").value;
  const sessionType = $("#prescribe-session-type").value;
  $("#prescribe-result").innerHTML = "<p class='empty'>Building…</p>";
  const applySelection = $("#prescribe-apply-selection").checked;
  const selectionLlm = applySelection && $("#prescribe-selection-llm").checked;
  const selectionConfirmed = applySelection && $("#prescribe-selection-confirm").checked;
  const scoreReady = window.__workflowReadinessData?.score?.status === "ready";
  lastPrescribePayload = {
    date, session_type: sessionType,
    apply_selection: applySelection, selection_llm: selectionLlm,
    selection_confirmed: selectionConfirmed,
    minimum_session: $("#prescribe-minimum").checked,
    target_minutes: Number($("#prescribe-target").value),
    minimum_include_main: $("#prescribe-minimum-main").checked,
    technique_throttle: $("#prescribe-technique").checked,
    technique_throttle_pattern: ($("#prescribe-throttle-pattern").value || "").trim() || null,
    drop_confirmed: $("#prescribe-drop-confirm").checked,
    allow_unknown_readiness: !scoreReady && Boolean(window.__workflowAllowUnknown),
  };
  try {
    const data = await api("/api/prescribe", { method: "POST", body: JSON.stringify(lastPrescribePayload) });
    if (!prescribeQueued) renderPrescription(data);
  } catch (error) {
    if (!prescribeQueued) {
      $("#prescribe-result").innerHTML = `<div class="panel warnbox">${esc(error.message)}</div>`;
    }
  } finally {
    prescribeBusy = false;
    if (prescribeQueued) {
      prescribeQueued = false;
      $("#prescribe-form").requestSubmit();
    }
  }
});

async function recordCompensationE1rm(exerciseId) {
  const kg = Number($("#comp-e1rm-kg")?.value);
  if (!(kg > 0)) {
    $("#comp-e1rm-msg").textContent = "Enter a positive e1RM.";
    return;
  }
  try {
    await api("/api/state/e1rm", {
      method: "POST",
      body: JSON.stringify({
        exercise_id: exerciseId,
        e1rm_kg: kg,
        effective_from: lastPrescribePayload?.date || new Date().toISOString().slice(0, 10),
        reason: "compensation slot",
      }),
    });
    $("#comp-e1rm-msg").textContent = "Saved; rebuilding...";
    $("#prescribe-form").requestSubmit();
  } catch (error) {
    $("#comp-e1rm-msg").textContent = error.message;
  }
}

async function applySuggestedDeload() {
  if (!lastPrescribePayload) return;
  const payload = { ...lastPrescribePayload, deload_confirmed: true };
  $("#prescribe-result").innerHTML = "<p class='empty'>Applying deload…</p>";
  try {
    const data = await api("/api/prescribe", { method: "POST", body: JSON.stringify(payload) });
    renderPrescription(data);
  } catch (error) {
    $("#prescribe-result").innerHTML = `<div class="panel warnbox">${esc(error.message)}</div>`;
  }
}

function renderPrescription(p) {
  window.__lastPrescription = p;
  const stress = p.notes?.recent_stress || {};
  const liftReady = p.notes?.per_lift_readiness || {};
  const rows = p.items.map((item) => {
    const st = stress[item.exercise_id];
    const lr = liftReady[item.exercise_id];
    const readyCell = lr
      ? `<span class="badge ${lr.status === "low" ? "bad" : ""}">${esc(lr.status)}</span>
         <div class="muted">${lr.score}</div>`
      : "<span class='muted'>—</span>";
    const stressCell = st
      ? `<span class="badge ${st.status === "high" ? "bad" : ""}">${esc(st.status)}</span>
         <div class="muted">${st.decayed_sets} sets · ${st.last_hours}h</div>`
      : "<span class='muted'>—</span>";
    return `<tr>
    <td><strong>${esc(item.exercise_id)}</strong>${item.essential ? ' <span class="badge">essential</span>' : ""}
      ${item.unknown_load_reason ? '<div class="muted">' + esc(item.unknown_load_reason) + "</div>" : ""}
      ${item.warmup && item.warmup.length ? '<div class="muted">warm-up: ' + item.warmup.map((w) => `${Math.round(w.percent * 100)}% × ${w.reps} @ ${fmt(w.load_kg)} kg`).join(" · ") + "</div>" : ""}</td>
    <td>${item.sets}</td><td>${item.reps_low}–${item.reps_high}</td>
    <td>${fmt(item.load_kg)}</td><td>${item.rir_target}</td>
    <td>${stressCell}</td>
    <td>${readyCell}</td>
    <td>${item.e1rm_source_sets == null ? "—" : item.e1rm_source_sets}</td>
    <td class="muted">${esc(item.refs.slice(-2).join(", "))}</td></tr>`;
  }).join("");
  const warnings = p.warnings.length
    ? '<div class="warnbox"><strong>Warnings</strong><ul class="list">' +
      p.warnings.map((w) => "<li>" + esc(w) + "</li>").join("") + "</ul></div>" : "";
  const comp = p.notes?.compensation || {};
  const compSelected = comp.status === "refused" ? comp.selection?.selected : null;
  const compBox = compSelected
    ? `<div class="warnbox"><strong>Compensation needs an e1RM</strong>
       <p>${esc(comp.reason || "No usable e1RM")} for <code>${esc(compSelected.exercise_id)}</code>.</p>
       <label>e1RM (kg)<input id="comp-e1rm-kg" type="number" step="0.5" min="0"></label>
       <button type="button" class="primary" onclick="recordCompensationE1rm('${esc(compSelected.exercise_id)}')">Save e1RM and rebuild</button>
       <span id="comp-e1rm-msg" class="muted"></span></div>`
    : "";
  const selection = p.notes?.selection;
  const selectionSuggestions = (selection?.slots || []).filter(
    (s) => s.trigger && s.trigger !== "none" && s.changed
  );
  const selectionBox = selection?.applied
    ? `<p class="muted">Selection applied (${esc(selection.llm_used ? "LLM" : "Python")}); substituted slots are cited as <code>MOD-SELECT-001</code>.</p>`
    : selection?.slots?.some((s) => s.blocked_reason)
      ? `<p class="warnbox">Selection skipped: ${esc(selection.slots.filter((s) => s.blocked_reason).map((s) => s.slot_id + " (" + s.blocked_reason + ")").join("; "))}</p>`
      : selectionSuggestions.length
        ? `<p class="warnbox">Substitution suggested: ${esc(selectionSuggestions.map((s) => s.slot_id + " → " + s.suggested + " (" + s.trigger + ")").join("; "))}. Use the selection panel to apply explicitly.</p>`
        : "";
  const signal = p.notes?.injury_signal;
  const signalBox = signal ? `<p class="muted">Injury signal: <strong>${esc(signal.status)}</strong>
    — ${esc(signal.summary)}</p>` : "";
  const cadence = p.notes?.test_cadence;
  const cadenceBox = cadence?.enabled ? `<p class="muted">Strength test:
    <strong>${esc(cadence.due ? "due" : "not due")}</strong>
    — ${esc(cadence.next_scheme)} by ${esc(cadence.next_due)}. ${esc(cadence.reason)}</p>` : "";
  const deload = p.notes?.deload;
  const deloadBox = deload ? `<p class="warnbox"><strong>Deload (${esc(deload.trigger)})</strong>
    — ${esc(deload.reason)}. Sets -${deload.set_reduction}, load
    ${Math.round(deload.load_multiplier * 100)}%, RIR +${deload.rir_add}.
    <span class="muted">Policy heuristic; comparative evidence is weak.</span></p>` : "";
  const spinal = p.notes?.spinal_cap;
  const spinalBox = spinal ? `<p class="muted">Weekly spinal cost:
    <strong>${fmt(spinal.cost, 1)} / ${fmt(spinal.cap, 1)}</strong>
    ${spinal.at_cap ? "· at cap, no headroom" : spinal.over_cap ? "· over cap" : `· ${fmt(spinal.headroom, 1)} headroom`}.
    Ordinal exposure guard, not a measured injury threshold.</p>` : "";
  const minimum = p.notes?.minimum_session;
  const minimumBox = minimum ? `<p class="warnbox"><strong>Minimum session</strong>
    — ${esc(minimum.status)}: ${esc(minimum.reason)}.
    ${minimum.removed_sets ? `Removed ${minimum.removed_sets} set(s).` : ""}
    ${minimum.removed_exercises?.length ? `Removed exercises: ${esc(minimum.removed_exercises.join(", "))}.` : ""}
    Load and RIR unchanged. Heuristic, not a validated minimum dose.</p>` : "";
  const suggestion = p.notes?.deload_suggestion;
  const suggestionBox = suggestion ? `<div class="warnbox"><strong>Deload suggested</strong>
    — ${esc(suggestion.reason)}.<br>
    <button type="button" onclick="applySuggestedDeload()">Deload this workout</button>
    <span class="muted">Or train as planned; the suggestion will return next workout this week.</span></div>` : "";
  $("#prescribe-result").innerHTML = `<div class="panel">
    <div class="panel-head"><h2>${esc(p.for_date)} · ${esc(p.session_label || sessionLabel(p.session_type || "unknown"))}</h2>
      <span class="badge ${p.executable ? "" : "bad"}">${p.executable ? "executable" : "not executable"}</span></div>
    ${compBox}${warnings}${spinalBox}${minimumBox}${deloadBox}${suggestionBox}${selectionBox}${signalBox}${cadenceBox}
    <div class="form-row">
      ${p.executable
        ? '<button class="primary" type="button" onclick="openWorkoutStart()">Start workout</button>'
        : '<button class="primary" type="button" disabled>Start workout</button>'}
      <span class="muted">${p.executable ? "Freezes this plan and opens the start form." : "Fix the warnings above before starting."}</span>
    </div>
    <table><thead><tr><th>Exercise</th><th>Sets</th><th>Reps</th><th>kg</th><th>RIR</th><th>recent stress</th><th>readiness</th><th>e1RM n</th><th>refs</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="muted">Loads are solved from estimated e1RM, not a measured maximum; treat the kg as a starting estimate.</p>
    <details><summary class="muted">notes (JSON)</summary><pre>${esc(JSON.stringify(p.notes, null, 2))}</pre></details>
  </div>`;
}

/* --- review ------------------------------------------------------------- */
function fillSessionSelect() {
  const select = $("#review-session");
  const sessions = window.__overview?.sessions || [];
  if (!sessions.length) { select.innerHTML = "<option value=''>no sessions</option>"; return; }
  const current = select.value;
  select.innerHTML = sessions.map((s) => `<option value="${esc(s.session_id)}">
    ${esc(s.occurred_on)} · ${esc(sessionLabel(s.session_type))} · ${s.marks ? s.marks + " marks" : "unreviewed"}</option>`).join("");
  if (current) select.value = current;
}

$("#rubric-calibration-run").addEventListener("click", async () => {
  $("#rubric-calibration").innerHTML = "<p class='empty'>Loading…</p>";
  try {
    const data = await api("/api/calibrate");
    $("#rubric-calibration").innerHTML = `<pre>${esc(data.text)}</pre>`;
  } catch (error) {
    $("#rubric-calibration").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
});

$("#review-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadReview($("#review-session").value);
});

async function loadReview(session) {
  if (!session) return;
  $("#review-result").innerHTML = "<p class='empty'>Loading sheet…</p>";
  try {
    const data = await api("/api/review/" + encodeURIComponent(session));
    const items = data.items.map((item) => `<tr>
      <td><strong>${esc(item.key)}</strong><div class="muted">${esc(item.question)}</div>
        <div class="muted">${esc(item.anchors)}</div></td>
      <td class="muted">${item.measurable ? fmt(item.score, 2) : "n/a"}</td>
      <td><input type="number" min="0" max="1" step="0.05" data-key="${esc(item.key)}"
        value="${item.existing ?? ""}" placeholder="skip"></td>
      <td class="muted">${esc(item.detail)}</td></tr>`).join("");
    const formRows = (data.form_context?.forms || []).map((form) => `
      <tr><td><code>${esc(form.exercise_id)}</code></td><td>${form.rating}/5</td>
      <td>${form.prior_avg ?? "—"} <span class="muted">(n=${form.prior_n})</span></td>
      <td>${form.prior_latest == null ? "—" : form.prior_latest + "/5"}</td></tr>`).join("");
    const formContext = formRows
      ? `<h3>Form context</h3><table><thead><tr><th>Lift</th><th>this session</th>
         <th>prior average</th><th>prior latest</th></tr></thead><tbody>${formRows}</tbody></table>`
      : "";
    $("#review-result").innerHTML = `<div class="panel">
      <div class="panel-head"><h2>${esc(data.session)} · ${esc(sessionLabel(data.session_type))}</h2>
        <span class="badge">composite ${fmt(data.composite, 2)}</span></div>
      <p class="muted">Week ${esc(data.week)} · spinal cost ${fmt(data.week_cost, 2)}</p>
      ${reviewWorkoutSummary(data.workout)}
      ${formContext}
      <table><thead><tr><th>Item</th><th>engine</th><th>your score</th><th>why</th></tr></thead>
      <tbody>${items}</tbody></table>
      <div class="form-row">
        <label>Remembrance <select id="review-confidence">
          <option value="high" ${data.confidence === "high" ? "selected" : ""}>high</option>
          <option value="low" ${data.confidence === "low" ? "selected" : ""}>low</option>
          <option value="unknown" ${data.confidence === "unknown" ? "selected" : ""}>unknown</option>
        </select></label>
        <label>Session RPE <input id="review-srpe" type="number" min="1" max="10"
          step="0.5" placeholder="optional"
          value="${data.feedback && data.feedback.srpe != null ? data.feedback.srpe : ""}"></label>
        <label>Length (min) <input id="review-minutes" type="number" min="1" max="600"
          step="1" placeholder="optional"
          value="${data.feedback && data.feedback.duration_min != null ? data.feedback.duration_min : ""}"></label>
        <label class="grow">Note <input id="review-note" placeholder="optional"></label>
        <button class="primary" id="save-review">End review</button>
      </div>
      <p class="muted">Only high-confidence marks count toward agreement. Blank = skip.</p>
      <div id="review-calibration"></div>
    </div>`;
    $("#save-review").addEventListener("click", () => saveReview(session));
  } catch (error) {
    $("#review-result").innerHTML = `<div class="panel warnbox">${esc(error.message)}</div>`;
  }
}

async function saveReview(session) {
  const button = $("#save-review");
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Saving…";
  const scores = {};
  document.querySelectorAll("#review-result input[data-key]").forEach((input) => {
    if (input.value !== "") scores[input.dataset.key] = Number(input.value);
  });
  const payload = {
    scores,
    confidence: $("#review-confidence").value,
    note: $("#review-note").value || null,
    session_rpe: $("#review-srpe").value || null,
    session_minutes: $("#review-minutes").value || null,
  };
  try {
    const data = await api("/api/review/" + encodeURIComponent(session), {
      method: "POST", body: JSON.stringify(payload),
    });
    const saved = data.written
      ? `Saved ${data.written} marks`
      : "Saved session details (no marks)";
    const post = data.postprocess
      ? `<p class="muted">Rubric: ${esc(data.postprocess.rubric)} · calibration: ${esc(data.postprocess.calibration)} · workout closed: ${data.postprocess.workout_closed ? "yes" : "no"}</p>`
      : "";
    $("#review-calibration").innerHTML = `<div class="warnbox"><strong>${esc(saved)}</strong>${post}
      <pre>${esc(data.calibration.text)}</pre></div>`;
    notify(saved + " · review saved.");
    loadOverview();
  } catch (error) {
    notify(error.message, "error");
    $("#review-calibration").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

/* --- exercise selection -------------------------------------------------- */
async function loadSelection() {
  const date = $("#prescribe-date").value;
  const sessionType = $("#prescribe-session-type").value;
  if (!date) { $("#selection-result").innerHTML = "<p class='empty'>Choose a date first.</p>"; return; }
  const llm = $("#selection-llm").checked ? "1" : "0";
  const different = $("#selection-include-different").checked ? "1" : "0";
  $("#selection-result").innerHTML = "<p class='empty'>Scoring variants…</p>";
  try {
    const data = await api(`/api/selection?date=${encodeURIComponent(date)}&session_type=${encodeURIComponent(sessionType)}&llm=${llm}&include_different=${different}`);
    const rows = (data.slots || []).map((slot) => {
      const candidates = slot.candidates.map((c) =>
        `<li>${esc(c.exercise_id)} — ${c.score}
          <span class="badge">${esc(c.comparison_class)}</span>
          <span class="muted">${esc(c.reasons.join("; "))} · ${esc(c.comparison_reason)}</span>
          ${c.tax ? `<div class="muted">tax: axial ${c.tax.axial} · systemic ${c.tax.systemic} · skill ${c.tax.skill} · ROM ${c.tax.rom}</div>` : ""}
          ${c.history_context ? `<div class="muted">own-history: ${esc(c.history_context.status)}
            (ratio ${fmt(c.history_context.ratio, 2)}, n=${c.history_context.n}); context only</div>` : ""}</li>`).join("");
      const policy = slot.comparison_class === "A" ? "auto-eligible"
        : slot.requires_confirmation ? "confirmation required" : "current";
      const trigger = slot.trigger && slot.trigger !== "none"
        ? `<div class="warnbox">trigger: ${esc(slot.trigger)}${slot.safety_blocked ? " · safety-blocked" : ""}${slot.tax_reason ? " · " + esc(slot.tax_reason) : ""}</div>` : "";
      return `<tr><td><strong>${esc(slot.slot_id)}</strong></td>
        <td>${esc(slot.current)} → <strong>${esc(slot.suggested)}</strong>
        <div class="muted">${esc(slot.reason)} [${esc(slot.source)}] · ${esc(policy)}</div>${trigger}</td>
        <td><ul class="plain">${candidates}</ul></td></tr>`;
    }).join("");
    $("#selection-result").innerHTML = rows
      ? `<table><thead><tr><th>Slot</th><th>current → suggested</th><th>candidates</th></tr></thead>
         <tbody>${rows}</tbody></table>`
      : "<p class='empty'>No multi-variant slots on this day. Add more candidates in <code>config/variants.v1.yaml</code> and the taxonomy — see docs/EXERCISE-VARIANTS.md.</p>";
  } catch (error) {
    $("#selection-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

$("#selection-run").addEventListener("click", loadSelection);

$("#validation-run").addEventListener("click", async () => {
  $("#validation-result").innerHTML = "<p class='empty'>Running walk-forward check…</p>";
  try {
    const data = await api("/api/validation?max_dates=12");
    $("#validation-result").innerHTML = `<pre>${esc(data.text)}</pre>`;
  } catch (error) {
    $("#validation-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
});

/* --- strength fatigue model ---------------------------------------------- */
async function loadFatigue() {
  try {
    const data = await api("/api/fatigue");
    const unit = (m) => m.unit === "ratio" ? "x" : " kg";
    const rows = (data.models || []).map((m) => {
      const u = unit(m);
      const ci = m.state_ci && m.state_ci[0] != null
        ? ` [${m.state_ci[0]}, ${m.state_ci[1]}]` : "";
      const state = m.state_kg == null ? "—" : `${m.state_kg}${u}${ci}`;
      return `<tr><td><strong>${esc(m.exercise_id)}</strong><div class="muted">${esc(m.family || "")}</div></td>
      <td>${m.n_observations} / ${m.span_days} d</td>
      <td>${m.r2 == null ? "—" : m.r2}</td>
      <td>${m.backtest_mae == null ? "—" : m.backtest_mae + " / " + m.backtest_naive_mae}</td>
      <td>${m.fitness_kg == null ? "—" : m.fitness_kg + u}</td>
      <td>${m.fatigue_kg == null ? "—" : m.fatigue_kg + u}</td>
      <td>${state}</td>
      <td>${m.latest_e1rm == null ? "—" : m.latest_e1rm + " kg"}</td>
      <td>${esc(m.status)}</td></tr>`;
    }).join("");
    $("#fatigue-model").innerHTML = rows
      ? `<table><thead><tr><th>Lift</th><th>obs / span</th><th>R²</th><th>backtest MAE / naive</th><th>fitness</th>
          <th>fatigue</th><th>state [95% CI]</th><th>latest e1RM</th><th>status</th></tr></thead>
          <tbody>${rows}</tbody></table>`
      : "<p class='empty'>No e1RM observations for the model yet.</p>";
  } catch (error) {
    $("#fatigue-model").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

/* --- readiness ---------------------------------------------------------- */
const SCORE_FIELDS = ["sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration"];
const DEVICE_FIELDS = ["hrv_ms", "rhr_bpm", "bodyweight_kg", "fat_pct", "wearable_score"];
const LABELS = { sleep: "Sleep", energy: "Energy", mood: "Mood", soreness: "Soreness",
  stress: "Stress", nutrition: "Nutrition", hydration: "Hydration",
  hrv_ms: "HRV (ms)", rhr_bpm: "Resting HR (bpm)",
  bodyweight_kg: "Bodyweight (kg)", fat_pct: "Body fat (%)",
  wearable_score: "Wearable readiness (0-100)" };

function fieldInput(field, device = false) {
  if (device) return `<label>${esc(LABELS[field])} <input type="number" step="0.1" min="0"
    data-field="${field}" placeholder=""></label>`;
  const options = ['<option value="">—</option>']
    .concat([1, 2, 3, 4, 5].map((n) => `<option value="${n}">${n}</option>`)).join("");
  return `<label>${esc(LABELS[field])} <select data-field="${field}">${options}</select></label>`;
}

/* --- workout workflow -------------------------------------------------- */
const WORKFLOW_REQUIRED = ["sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration"];
const WORKFLOW_ORDER = ["readiness", "preview", "active", "post"];

function setWorkflowStep(step) {
  const current = Math.max(0, WORKFLOW_ORDER.indexOf(step));
  document.querySelectorAll("[data-workflow-step]").forEach((item) => {
    const index = WORKFLOW_ORDER.indexOf(item.dataset.workflowStep);
    item.classList.toggle("active", index === current);
    item.classList.toggle("done", index < current);
  });
}

function updateWorkflowStep() {
  const ended = $("#workout-ended-panel");
  const active = $("#workout-active-panel");
  const start = $("#workout-start-panel");
  const preview = $("#workflow-preview");
  let step = "readiness";
  if (ended && !ended.hidden) step = "post";
  else if (active && !active.hidden) step = "active";
  else if (start && !start.hidden) step = "active";
  else if (preview && !preview.classList.contains("locked")) step = "preview";
  setWorkflowStep(step);
}

function setWorkflowReadiness(data) {
  window.__workflowReadinessData = data || null;
  const scored = Boolean(data?.score?.status === "ready");
  const allowed = scored || Boolean(window.__workflowAllowUnknown);
  const preview = $("#workflow-preview");
  const lock = $("#workflow-lock");
  const content = $("#workflow-preview-content");
  if (!preview || !lock || !content) return;
  preview.classList.toggle("locked", !allowed);
  lock.hidden = allowed;
  content.hidden = !allowed;
  const ack = $("#workflow-ack");
  if (ack) ack.hidden = scored;
  const unknown = $("#workflow-unknown-note");
  if (unknown) unknown.hidden = !(allowed && !scored);
  const empty = $("#workout-empty");
  if (empty) {
    const active = $("#workout-active-panel");
    const start = $("#workout-start-panel");
    if (!(active && !active.hidden) && !(start && !start.hidden)) {
      empty.hidden = allowed;
    }
  }
  updateWorkflowStep();
}

$("#workflow-ack")?.addEventListener("click", () => {
  window.__workflowAllowUnknown = true;
  setWorkflowReadiness(window.__workflowReadinessData);
  notify("Building without a readiness score; no score-based load modifier will apply.");
});

$("#readiness-date").value = today();
$("#readiness-fields").innerHTML = SCORE_FIELDS.map((f) => fieldInput(f)).join("");
$("#readiness-device").innerHTML = DEVICE_FIELDS.map((f) => fieldInput(f, true)).join("");
$("#readiness-date").addEventListener("change", () => {
  window.__workflowAllowUnknown = false;
  loadReadiness($("#readiness-date").value);
});

async function loadReadiness(date) {
  if (!date) return;
  try {
    const data = await api("/api/readiness/" + encodeURIComponent(date));
    document.querySelectorAll("#readiness-form [data-field]").forEach((input) => {
      const value = data[input.dataset.field];
      input.value = value ?? "";
    });
    const presets = data.presets || {};
    $("#readiness-presets").innerHTML = Object.entries(presets).map(([name, preset]) =>
      `<button type="button" class="ghost" onclick="applyReadinessPreset('${esc(name)}')">${esc(preset.label || name)}</button>`
    ).join("");
    const flags = ["travel", "timezone_change", "illness", "alcohol", "poor_sleep_environment", "high_work_stress"];
    const active = new Set(data.context_flags || []);
    $("#readiness-context").innerHTML = flags.map((flag) =>
      `<label><input type="checkbox" data-context="${esc(flag)}" ${active.has(flag) ? "checked" : ""}> ${esc(flag.replaceAll("_", " "))}</label>`
    ).join("");
    if (data.settings) {
      const s = data.settings;
      $("#setting-baseline-days").value = s.baseline_days;
      $("#setting-min-readings").value = s.baseline_min_readings;
      $("#setting-hrv-slope").value = s.hrv_slope;
      $("#setting-rhr-slope").value = s.rhr_slope;
      $("#setting-hrv-weight").value = s.hrv_weight;
      $("#setting-rhr-weight").value = s.rhr_weight;
      $("#setting-wearable-weight").value = s.wearable_weight;
      const v = data.volume_valve || {};
      $("#volume-enabled").checked = v.enabled !== false;
      $("#volume-score").value = v.score_below ?? 0.5;
      $("#volume-sets").value = v.sets ?? 1;
      $("#volume-essential").checked = !!v.include_essential;
      $("#settings-source").textContent =
        "effective source: " + s.setting_source + " · config file plus athlete overrides";
    }
    renderReadiness(data);
  } catch (error) {
    setWorkflowReadiness(null);
    $("#readiness-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function applyReadinessPreset(name) {
  const day = $("#readiness-date").value;
  try {
    await api("/api/readiness/preset", { method: "POST", body: JSON.stringify({ date: day, name }) });
    await loadReadiness(day);
  } catch (error) {
    $("#readiness-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function saveReadinessContext() {
  const day = $("#readiness-date").value;
  const flags = [...document.querySelectorAll("#readiness-context [data-context]")]
    .filter((input) => input.checked).map((input) => input.dataset.context);
  try {
    await api("/api/readiness/context", { method: "POST", body: JSON.stringify({ date: day, flags }) });
    $("#context-msg").textContent = "Saved";
    notify("Readiness context saved.");
    await loadReadiness(day);
  } catch (error) {
    $("#context-msg").textContent = error.message;
  }
}

$("#volume-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await api("/api/readiness/volume", {
      method: "POST",
      body: JSON.stringify({
        date: $("#readiness-date").value,
        enabled: $("#volume-enabled").checked,
        score_below: Number($("#volume-score").value),
        sets: Number($("#volume-sets").value),
        include_essential: $("#volume-essential").checked,
      }),
    });
    renderReadiness(data);
    $("#volume-msg").textContent = "Saved";
    notify("Readiness volume valve saved.");
    loadOverview();
  } catch (error) {
    $("#volume-msg").textContent = error.message;
  }
});

$("#settings-drop-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  let slots;
  try {
    slots = JSON.parse($("#settings-drop-slots").value || "{}");
  } catch (error) {
    $("#settings-drop-msg").textContent = "Candidate pool JSON is invalid: " + error.message;
    return;
  }
  try {
    const data = await api("/api/settings/drop", {
      method: "POST",
      body: JSON.stringify({
        enabled: $("#settings-drop-enabled").checked,
        competition_confirm_days: Number($("#settings-drop-days").value),
        max_slots_per_group: Number($("#settings-drop-max").value),
        technique_minutes: Number($("#settings-drop-technique").value),
        tolerance: Number($("#settings-drop-tolerance").value),
        slots,
      }),
    });
    renderSettings(data);
    notify("Drop settings saved.");
  } catch (error) {
    $("#settings-drop-msg").textContent = error.message;
  }
});

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    date: $("#readiness-date").value,
    baseline_days: Number($("#setting-baseline-days").value),
    baseline_min_readings: Number($("#setting-min-readings").value),
    hrv_slope: Number($("#setting-hrv-slope").value),
    rhr_slope: Number($("#setting-rhr-slope").value),
    hrv_weight: Number($("#setting-hrv-weight").value),
    rhr_weight: Number($("#setting-rhr-weight").value),
    wearable_weight: Number($("#setting-wearable-weight").value),
  };
  try {
    const data = await api("/api/readiness/settings", {
      method: "POST", body: JSON.stringify(payload),
    });
    renderReadiness(data);
    $("#settings-source").textContent =
      "effective source: " + data.settings.setting_source + " · athlete setting recorded";
    notify("Readiness settings saved.");
    loadOverview();
  } catch (error) {
    $("#settings-source").textContent = error.message;
  }
});

$("#shadow-run").addEventListener("click", async () => {
  $("#shadow-result").innerHTML = "<p class='empty'>Comparing…</p>";
  try {
    const data = await api("/api/readiness/shadow");
    $("#shadow-result").innerHTML = `<pre>${esc(data.text)}</pre>`;
  } catch (error) {
    $("#shadow-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
});

$("#calibration-run").addEventListener("click", async () => {
  $("#calibration-result").innerHTML = "<p class='empty'>Fitting…</p>";
  try {
    const data = await api("/api/readiness/calibrate");
    $("#calibration-result").innerHTML = `<pre>${esc(data.text)}</pre>`;
  } catch (error) {
    $("#calibration-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
});

$("#override-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await api("/api/readiness/override", {
      method: "POST",
      body: JSON.stringify({
        date: $("#readiness-date").value,
        scope: $("#override-scope").value,
        value: Number($("#override-value").value),
        reason: $("#override-reason").value,
      }),
    });
    renderReadiness(data);
    $("#override-value").value = "";
    $("#override-reason").value = "";
    notify("Readiness override saved.");
    loadOverview();
  } catch (error) {
    $("#readiness-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
});

$("#readiness-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = {};
  document.querySelectorAll("#readiness-form [data-field]").forEach((input) => {
    if (input.value !== "") values[input.dataset.field] = Number(input.value);
  });
  if (!Object.keys(values).length) {
    $("#readiness-result").innerHTML = "<p class='warnbox'>Give at least one field.</p>";
    return;
  }
  try {
    const data = await api("/api/readiness", {
      method: "POST",
      body: JSON.stringify({ date: $("#readiness-date").value, values,
        note: $("#readiness-note").value || null }),
    });
    renderReadiness(data);
    notify("Readiness saved.");
    loadOverview();
  } catch (error) {
    $("#readiness-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
});

function renderReadiness(data) {
  if (!data || data.known === false || Object.keys(data).length === 0) {
    setWorkflowReadiness(null);
    $("#readiness-result").innerHTML = "<p class='empty'>No readiness for this date.</p>";
    return;
  }
  setWorkflowReadiness(data);
  const rows = Object.keys(LABELS).filter((field) => data[field] != null).map((field) => `
    <tr><td>${esc(LABELS[field])}</td><td>${fmt(data[field])}</td>
    <td><span class="badge">${esc(data.sources?.[field] || "import")}</span></td></tr>`).join("");
  $("#readiness-result").innerHTML = `<div class="warnbox"><strong>Merged readiness</strong>
    <table><thead><tr><th>Field</th><th>value</th><th>source</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  renderReadinessScore(data.score);
}

/* --- import ------------------------------------------------------------- */
$("#import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const training = $("#import-training").files[0];
  const readiness = $("#import-readiness").files[0];
  if (!training || !readiness) {
    $("#import-result").innerHTML = "<p class='warnbox'>Choose both CSV files.</p>";
    return;
  }
  if (training.size > 20 * 1024 * 1024 || readiness.size > 20 * 1024 * 1024) {
    $("#import-result").innerHTML = "<p class='warnbox'>Each file must be under 20 MB.</p>";
    return;
  }
  $("#import-result").innerHTML = "<p class='empty'>Importing…</p>";
  try {
    const [trainingText, readinessText] = await Promise.all([training.text(), readiness.text()]);
    const data = await api("/api/import", {
      method: "POST",
      body: JSON.stringify({
        training: { name: training.name, text: trainingText },
        readiness: { name: readiness.name, text: readinessText },
      }),
    });
    const issues = Object.entries(data.issues || {});
    $("#import-result").innerHTML = `<div class="warnbox"><strong>Imported</strong>
      <table><tbody>
        <tr><td>Training file</td><td>${esc(data.training_name)}</td></tr>
        <tr><td>Readiness file</td><td>${esc(data.readiness_name)}</td></tr>
        <tr><td>New raw rows / overlapping</td><td>${data.raw_rows_inserted} / ${data.raw_rows_overlap}</td></tr>
        <tr><td>Clean sets inserted / existing</td><td>${data.clean_sets_inserted} / ${data.clean_sets_existing}</td></tr>
        <tr><td>Sessions written</td><td>${data.sessions_written}</td></tr>
        <tr><td>Quarantined</td><td>${data.quarantined}</td></tr>
        <tr><td>Readiness days</td><td>${data.readiness_days}</td></tr>
        <tr><td>Window</td><td>${esc(data.window_start || "—")} → ${esc(data.window_end || "—")}</td></tr>
      </tbody></table>
      ${issues.length ? "<p>Issues: " + issues.map(([k, v]) => esc(k) + "=" + esc(v)).join(", ") + "</p>" : ""}
    </div>`;
    $("#import-training").value = "";
    $("#import-readiness").value = "";
    loadOverview();
  } catch (error) {
    $("#import-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
});

function renderReadinessScore(score) {
  if (!score) { $("#readiness-score").innerHTML = ""; return; }
  const components = (score.components || []).map((c) => `
    <tr><td>${esc(c.field)}</td><td>${fmt(c.value)}</td><td>${fmt(c.normalised, 2)}</td></tr>`).join("");
  const categories = Object.entries(score.category_scores || {}).map(([name, value]) => `
    <tr><td>${esc(name)}</td><td>${fmt(value, 2)}</td></tr>`).join("");
  const overrides = Object.entries(score.overrides || {}).map(([scope, row]) => `
    <tr><td>${esc(scope)}</td><td>${fmt(row.value, 2)}</td><td>${esc(row.reason)}</td></tr>`).join("");
  $("#readiness-score").innerHTML = `<div class="panel">
    <div class="panel-head"><h2>Computed readiness</h2>
      <span class="badge ${score.status === "ready" ? "" : "warn"}">${esc(score.status)}</span></div>
    <p><strong>${score.score == null ? "—" : fmt(score.score, 2)}</strong> <span class="muted">${esc(score.basis || "")}</span></p>
    <p class="muted">Bounded readiness heuristic; the no-readiness counterfactual is not validated.</p>
    ${(score.context_flags || []).length ? `<p class="muted">Context: ${(score.context_flags || []).map((f) => esc(f.replaceAll("_", " "))).join(", ")}${score.device_suppressed ? " · HRV/RHR suppressed" : ""}</p>` : ""}
    ${components ? `<table><thead><tr><th>Input</th><th>value</th><th>normalised</th></tr></thead><tbody>${components}</tbody></table>` : ""}
    ${categories ? `<h3>Categories</h3><table><thead><tr><th>Category</th><th>score</th></tr></thead><tbody>${categories}</tbody></table>` : ""}
    ${overrides ? `<h3>Overrides</h3><table><thead><tr><th>Scope</th><th>value</th><th>reason</th></tr></thead><tbody>${overrides}</tbody></table>` : ""}
  </div>`;
}

/* --- state -------------------------------------------------------------- */
async function loadExposureStatus() {
  try {
    const data = await api("/api/exposures");
    const exposures = data.exposures || [];
    const badge = data.status === "blocked" ? "bad" : data.status === "caution" ? "warn" : "";
    const rows = exposures.length ? `<table><thead><tr><th>Date</th><th>Kind</th><th>Region</th>
      <th>Intensity</th><th>Exercise</th></tr></thead><tbody>` + exposures.map((row) => `
      <tr><td>${esc(row.performed_on)}</td><td>${esc(row.kind)}</td>
      <td>${esc(row.region_load)}</td><td>${esc(row.intensity_class)}</td>
      <td>${esc(row.exercise_id || "—")}</td></tr>`).join("") + "</tbody></table>" :
      "<p class='muted'>No recent exposure.</p>";
    $("#exposure-status").innerHTML = `<p><span class="badge ${badge}">${esc(data.status)}</span>
      ${esc(data.reason)}${data.next_maximal_on ? " · next maximal " + esc(data.next_maximal_on) : ""}</p>${rows}`;
  } catch (error) {
    $("#exposure-status").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadState() {
  $("#state-result").innerHTML = "<p class='empty'>Loading…</p>";
  try {
    const data = await api("/api/state");
    const profile = data.profile;
    const profileRows = profile ? Object.entries(profile).map(([k, v]) => `
      <tr><td class="muted">${esc(k)}</td><td>${esc(v ?? "—")}</td></tr>`).join("")
      : "<tr><td class='empty'>not recorded</td></tr>";
    const constraints = data.constraints.length ? data.constraints.map((c) => `
      <li><strong>${esc(c.kind)}</strong> · ${esc(c.region)} · ${esc(c.severity)}
      ${Array.isArray(c.forbidden_exercises) && c.forbidden_exercises.length ? " · forbids " + esc(c.forbidden_exercises.join(", ")) : ""}</li>`).join("")
      : "<li class='empty'>none recorded</li>";
    const suitability = Object.entries(data.suitability).map(([exercise, rating]) => `
      <tr><td>${esc(exercise)}</td><td>${rating.can_do ? "yes" : "no"}</td>
      <td>${rating.will_do ? "yes" : "no"}</td><td>${rating.feels_bad ? "yes" : "no"}</td></tr>`).join("");
    const regions = Object.values(data.injury_signal?.regions || {});
    const injuryRows = regions.length ? `<div class="table-scroll"><table class="injury-table"><thead><tr><th>Region</th><th>Status</th>
      <th>Tolerated</th><th>Window</th></tr></thead><tbody>` + regions.map((r) => `
      <tr><td><strong>${esc(r.label)}</strong><div class="muted">${esc(r.summary)}</div></td>
      <td>${esc(r.status)}</td><td>${r.tolerated_sessions}/${r.required_tolerated_sessions}
      <div class="muted">of ${r.loaded_sessions} loaded (${r.unverified_sessions} unverified)</div></td>
      <td>${r.window_days} d</td></tr>`).join("") + "</tbody></table></div>"
      : "<p class='empty'>no regions configured</p>";
    const calibration = data.e1rm_calibration || [];
    const e1rmPair = (raw, eff) => raw == null ? "—" :
      (eff == null ? raw + " kg" : `${raw} → ${eff} kg`);
    const calibrationRows = calibration.map((row) => `
      <tr><td><strong>${esc(row.exercise_id)}</strong><div class="muted">${esc(row.status)}</div></td>
      <td>${e1rmPair(row.formula_raw, row.formula_effective)}</td>
      <td>${e1rmPair(row.override_raw, row.override_effective)}</td>
      <td>${row.active_source || "—"}${row.active_e1rm == null ? "" : ` · ${row.active_e1rm} kg`}</td>
      <td>${row.latest_on || "—"}</td>
      <td>${row.n}</td><td>${row.median_ratio ?? "—"}</td>
      <td>${row.ci_low == null ? "—" : row.ci_low + "–" + row.ci_high}</td></tr>`).join("");
    // P1 coverage: the gate is data, so show which lifts still need tests and by how many.
    // Every number comes from Python; this block only formats it.
    const coverage = data.e1rm_tests_needed || [];
    const mainCoverage = coverage.filter((row) => row.is_main_lift);
    const mainMet = mainCoverage.filter((row) => row.needed === 0).length;
    const coverageRows = coverage.map(function (row) {
      const note = row.note ? "<div class='muted'>" + esc(row.note) + "</div>" : "";
      return "<tr><td><strong>" + esc(row.display) + "</strong><div class='muted'>" +
        esc(row.exercise_id) + (row.is_main_lift ? " · main lift" : "") + "</div></td>" +
        "<td>" + row.counted + " / " + row.min_tests + "</td>" +
        "<td>" + row.needed + "</td>" +
        "<td>" + esc(row.status) + note + "</td>" +
        "<td>" + esc(row.next_action) + "</td></tr>";
    }).join("");
    const coverageTable = coverageRows
      ? "<div class='table-scroll'><table class='e1rm-table'><thead><tr><th>Lift</th><th>tests counted</th><th>need</th><th>gate</th><th>next</th></tr></thead><tbody>" + coverageRows + "</tbody></table></div>"
      : "<p class='empty'>no lifts to report.</p>";
    const coveragePanel = "<div class='panel state-wide'><div class='panel-head'><h2>Measured tests needed</h2>" +
      "<span class='muted'>" + mainMet + "/" + mainCoverage.length + " main lifts at the gate</span></div>" +
      "<p class='section-help'><span>A test counts only when a formula estimate existed within 84 days before it. Record one with <code>strength-coach test</code>; this table is read-only.</span> " + '<a class="doc-link" href="#docs?doc=ROADMAP.md">Roadmap</a></p>' +
      coverageTable + "</div>";
    renderStateForms(data);
    loadExposureStatus();
    $("#state-result").innerHTML = coveragePanel + `
      <div class="panel"><div class="panel-head"><h2>Profile</h2></div>
        <table><tbody>${profileRows}</tbody></table></div>
      <div class="panel"><div class="panel-head"><h2>Constraints</h2></div><ul class="list">${constraints}</ul></div>
      <div class="panel"><div class="panel-head"><h2>Suitability</h2></div>
        ${suitability ? `<table><thead><tr><th>Exercise</th><th>can-do</th><th>will-do</th><th>feels bad</th></tr></thead><tbody>${suitability}</tbody></table>` : "<p class='empty'>none recorded</p>"}</div>
      <div class="panel state-wide"><div class="panel-head"><h2>e1RM calibration</h2>
        <span class="muted">measured vs formula; report only</span></div>
        ${calibrationRows ? `<div class="table-scroll"><table class="e1rm-table"><thead><tr><th>Lift</th><th>formula (raw → effective)</th>
          <th>override (raw → effective)</th><th>used</th><th>last set</th><th>tests</th>
          <th>median ratio</th><th>95% CI</th></tr></thead>
          <tbody>${calibrationRows}</tbody></table></div>
          <p class="muted">A bounded correction is applied only when the 95% CI excludes 1.0;
          measured tests still override the formula. Formula-only rows show the current
          estimate and last set. e1RM is an estimate, not a measured maximum.</p>`
          : "<p class='empty'>no measured tests with a prior estimate yet.</p>"}</div>
      <div class="panel state-wide"><div class="panel-head"><h2>Injury signal</h2></div>
        <p>${esc(data.injury_signal?.summary || "")}</p>
        ${injuryRows}
        <p class="muted">${esc(data.injury_signal?.disclaimer || "")}</p></div>`;
  } catch (error) {
    $("#state-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

function profileField(name, label, value, type = "text") {
  return `<label>${label}<input data-profile="${name}" type="${type}" value="${esc(value ?? "")}"></label>`;
}

function renderStateForms(data) {
  const p = data.profile || {};
  const regions = Object.keys(data.injury_signal?.regions || {});
  const regionOptions = (regions.length ? regions : ["low_back"]).map((r) =>
    `<option value="${esc(r)}">${esc(r)}</option>`).join("");
  // A declared break freezes its weeks; the list is the record, the form appends to it.
  const today = new Date().toISOString().slice(0, 10);
  const breaks = data.declared_breaks || [];
  const breakRows = breaks.length
    ? "<div class='table-scroll'><table><thead><tr><th>From</th><th>To</th><th>Reason</th>" +
      "<th>Days</th><th>Status</th><th></th></tr></thead><tbody>" +
      breaks.map((row) => {
        const status = row.cancelled ? "cancelled"
          : (row.starts_on <= today && today <= row.ends_on) ? "active"
          : row.ends_on < today ? "past" : "future";
        const action = (!row.cancelled && status !== "past")
          ? "<button class='ghost' type='button' data-cancel-break='" + row.break_id +
            "'>Cancel</button>"
          : "";
        return "<tr><td>" + row.starts_on + "</td><td>" + row.ends_on + "</td><td>" +
          esc(row.reason) + "</td><td>" + row.days + "</td><td>" + status + "</td><td>" +
          action + "</td></tr>";
      }).join("") + "</tbody></table></div>"
    : "<p class='empty'>no declared breaks; untrained weeks are already skipped</p>";
  $("#state-forms").innerHTML = `
    <div class="panel"><div class="panel-head"><h2>Edit profile</h2><span class="muted">appends a new version</span></div>
      <form id="profile-form" class="grid-fields">
        ${profileField("primary_goal", "Primary goal", p.primary_goal)}
        ${profileField("goal_rank", "Goal rank (comma)", (p.goal_rank || []).join(", "))}
        ${profileField("focus_lifts", "Focus lifts (comma)", (p.focus_lifts || []).join(", "))}
        ${profileField("competition_date", "Competition date", p.competition_date, "date")}
        ${profileField("sessions_per_week_target", "Sessions/week", p.sessions_per_week_target, "number")}
        ${profileField("max_session_minutes", "Max minutes", p.max_session_minutes, "number")}
        ${profileField("block_start_date", "Block start", p.block_start_date, "date")}
        <label>Volume budget
          <select data-profile="volume_budget_enabled">
            <option value="off" ${p.volume_budget_enabled ? "" : "selected"}>off</option>
            <option value="on" ${p.volume_budget_enabled ? "selected" : ""}>on</option>
          </select>
        </label>
        <label>Main-lift policy
          <select data-profile="main_lift_policy">
            <option value="preserve" ${(p.main_lift_policy || "preserve") === "preserve" ? "selected" : ""}>preserve</option>
            <option value="reduce" ${p.main_lift_policy === "reduce" ? "selected" : ""}>reduce</option>
            <option value="drop" ${p.main_lift_policy === "drop" ? "selected" : ""}>drop</option>
          </select>
        </label>
        <button class="primary" type="submit">Save profile version</button>
      </form>
      <p class="muted">Budget <strong>on</strong> with <strong>preserve</strong> trims and tops up
        accessories only. <strong>reduce</strong> also trims filled-group main lifts;
        <strong>drop</strong> also removes/relabels the main lift. The main-lift policy is ignored
        while the volume budget is off.</p>
    </div>

    <div class="panel"><div class="panel-head"><h2>Add constraint</h2></div>
      <form id="constraint-form" class="grid-fields">
        <label>Kind<select data-constraint="kind"><option>injury</option><option>rom</option><option>preference</option></select></label>
        <label>Region<input data-constraint="region" placeholder="low_back"></label>
        <label>Severity<select data-constraint="severity"><option>monitor</option><option>caution</option><option>hard_exclude</option></select></label>
        <label>Forbidden exercises<input data-constraint="forbidden_exercises" placeholder="a, b"></label>
        <label>Forbidden patterns<input data-constraint="forbidden_patterns" placeholder="hinge, squat"></label>
        <label>Since<input data-constraint="since" placeholder="YYYY-MM"></label>
        <label>Settled on<input data-constraint="settled_on" placeholder="YYYY-MM"></label>
        <label class="grow">Evidence<input data-constraint="evidence"></label>
        <button class="primary" type="submit">Append constraint</button>
      </form>
    </div>

    <div class="panel"><div class="panel-head"><h2>Rate suitability</h2></div>
      <form id="suitability-form" class="grid-fields">
        <label>Exercise<input data-suit="exercise_id" list="exercise-options" placeholder="canonical id"></label>
        <label>Can do<select data-suit="can_do"><option>yes</option><option>no</option></select></label>
        <label>Will do<select data-suit="will_do"><option>yes</option><option>no</option></select></label>
        <label>Feels bad<select data-suit="feels_bad"><option>no</option><option>yes</option></select></label>
        <label class="grow">Note<input data-suit="note"></label>
        <button class="primary" type="submit">Append rating</button>
      </form>
    </div>

    <div class="panel"><div class="panel-head"><h2>e1RM override</h2></div>
      <form id="e1rm-form" class="grid-fields">
        <label>Exercise<input data-e1rm="exercise_id" list="exercise-options" placeholder="canonical id"></label>
        <label>kg<input data-e1rm="e1rm_kg" type="number" step="0.5"></label>
        <label>Effective from<input data-e1rm="effective_from" type="date"></label>
        <label>Expires<input data-e1rm="expires_on" type="date"></label>
        <label class="grow">Reason<input data-e1rm="reason"></label>
        <button class="primary" type="submit">Append override</button>
      </form>
    </div>

    <div class="panel"><div class="panel-head"><h2>Strength test</h2><span class="muted">records a measured e1RM; exposure is automatic</span></div>
      <form id="test-form" class="grid-fields">
        <label>Exercise<input data-test="exercise_id" list="exercise-options" placeholder="canonical id"></label>
        <label>kg<input data-test="kg" type="number" step="0.5"></label>
        <label>Reps<input data-test="reps" type="number" min="1" max="10"></label>
        <label>Date<input data-test="date" type="date"></label>
        <label><input data-test="max" type="checkbox"> confirm true 1RM</label>
        <label class="grow">Reason<input data-test="reason"></label>
        <button class="primary" type="submit">Record test</button>
      </form>
      <p class="muted">Recording a test also registers a high-intensity exposure. It is not volume.</p>
    </div>

    <div class="panel"><div class="panel-head"><h2>High-intensity exposure</h2><span class="muted">max attempts, competition, unplanned work</span></div>
      <div id="exposure-status"><p class="muted">Loading…</p></div>
      <form id="exposure-form" class="grid-fields">
        <label>Date<input data-exposure="date" type="date"></label>
        <label>Kind<select data-exposure="kind">
          <option value="max_attempt">max attempt</option>
          <option value="competition">competition</option>
          <option value="unplanned">unplanned</option>
          <option value="other">other</option>
        </select></label>
        <label>Region<select data-exposure="region_load">
          <option value="axial">axial</option><option value="lower">lower</option>
          <option value="upper">upper</option><option value="mixed">mixed</option>
          <option value="unknown">unknown</option>
        </select></label>
        <label>Exercise<input data-exposure="exercise_id" list="exercise-options" placeholder="optional"></label>
        <label>Intensity<select data-exposure="intensity_class">
          <option value="near_max">near max</option><option value="high">high</option>
          <option value="moderate">moderate</option><option value="unknown">unknown</option>
        </select></label>
        <label class="grow">Note<input data-exposure="note"></label>
        <button class="primary" type="submit">Log exposure</button>
      </form>
    </div>

    <div class="panel"><div class="panel-head"><h2>Symptom</h2></div>
      <p class="section-help"><span>One pre-session 0-3 reading per region. The latest reading drives the back rules; the whole history drives the injury signal. “Settled within 48 hours” clears a level-1 reading only when recorded as yes — unknown counts as not settled. When it settles, log a new level-0 reading.</span> <a class="doc-link" href="#docs?doc=docs/SYMPTOM-LOGGING.md">Symptom logging</a></p>
      <form id="symptom-form" class="grid-fields">
        <label>Date<input data-symptom="date" type="date"></label>
        <label>Region<select data-symptom="region">${regionOptions}</select></label>
        <label>Level<select data-symptom="level"><option>0</option><option>1</option><option>2</option><option>3</option></select></label>
        <label>Settled within 48 hours<select data-symptom="settled"><option value="unknown">unknown (not settled)</option><option value="yes">yes</option><option value="no">no</option></select></label>
        <label class="grow">Note<input data-symptom="note"></label>
        <button class="primary" type="submit">Append symptom</button>
      </form>
    </div>

    <div class="panel"><div class="panel-head"><h2>Declared break</h2>
      <span class="muted">holiday, deload or test week</span></div>
      <p class="section-help"><span>A break freezes its weeks: the DUP cycle and the erector ramp do not advance inside it, nothing is edited or deleted, and no load, RIR or set changes.</span> <a class="doc-link" href="#docs?doc=docs/CONTINUITY.md&anchor=declared-breaks-implemented-2026-10-26">Continuity</a></p>
      <div id="break-list">${breakRows}</div>
      <form id="break-form" class="grid-fields">
        <label>From<input data-break="starts_on" type="date"></label>
        <label>To<input data-break="ends_on" type="date"></label>
        <label>Reason<select data-break="reason">
          <option value="holiday">holiday</option><option value="deload">deload</option>
          <option value="test">test week</option><option value="other">other</option>
        </select></label>
        <label class="grow">Note<input data-break="note"></label>
        <button class="primary" type="submit">Record break</button>
      </form>
      <div id="break-msg" class="muted"></div>
    </div>

    <div class="panel"><div class="panel-head"><h2>Block start</h2><span class="muted">resets the ramp</span></div>
      <form id="block-form" class="form-row">
        <label>Date<input data-block="date" type="date"></label>
        <label><input data-block="force" type="checkbox"> reset if already set</label>
        <button class="primary" type="submit">Set block start</button>
      </form>
    </div>`;

  const collect = (prefix) => Object.fromEntries(
    [...document.querySelectorAll(`[data-${prefix}]`)].map((el) => [el.dataset[prefix], el.value])
  );
  const save = async (path, payload, target = "#state-result") => {
    try {
      await api(path, { method: "POST", body: JSON.stringify(payload) });
      loadState();
      loadOverview();
    } catch (error) {
      $(target).innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
    }
  };
  $("#profile-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = collect("profile");
    save("/api/state/profile", {
      ...values,
      sessions_per_week_target: values.sessions_per_week_target || null,
      max_session_minutes: values.max_session_minutes || null,
    });
  });
  $("#constraint-form").addEventListener("submit", (event) => {
    event.preventDefault();
    save("/api/state/constraint", collect("constraint"));
  });
  $("#suitability-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = collect("suit");
    save("/api/state/suitability", {
      ...values,
      can_do: values.can_do === "yes",
      will_do: values.will_do === "yes",
      feels_bad: values.feels_bad === "yes",
    });
  });
  $("#e1rm-form").addEventListener("submit", (event) => {
    event.preventDefault();
    save("/api/state/e1rm", collect("e1rm"));
  });
  $("#test-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = collect("test");
    save("/api/state/test", { ...values, max: Boolean(values.max) });
  });
  $("#exposure-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = collect("exposure");
    try {
      await api("/api/exposures", { method: "POST", body: JSON.stringify(values) });
      await loadExposureStatus();
    } catch (error) {
      $("#exposure-status").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
    }
  });
  $("#symptom-form").addEventListener("submit", (event) => {
    event.preventDefault();
    save("/api/state/symptom", collect("symptom"));
  });
  $("#block-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = collect("block");
    save("/api/state/block", { ...values, force: Boolean(values.force) });
  });
  $("#break-form").addEventListener("submit", (event) => {
    event.preventDefault();
    save("/api/state/break", collect("break"), "#break-msg");
  });
  document.querySelectorAll("[data-cancel-break]").forEach((button) => {
    button.addEventListener("click", () => {
      save("/api/state/break/cancel",
        { break_id: Number(button.dataset.cancelBreak) }, "#break-msg");
    });
  });
}

/* --- docs --------------------------------------------------------------- */
async function loadDocs(requested, anchor) {
  try {
    const docs = await api("/api/docs");
    $("#docs-list").dataset.loaded = "1";
    $("#docs-list").innerHTML = docs.map((doc) => `<a href="#docs?doc=${encodeURIComponent(doc.name)}">
      ${esc(doc.title)}</a>`).join("");
    if (!requested && $("#doc-body").dataset.loaded) return;
    const target = requested || docs[0]?.name;
    if (!target) return;
    if (!docs.some((doc) => doc.name === target)) {
      $("#doc-body").innerHTML = `<p class="warnbox">Unknown document: ${esc(target)}</p>`;
      return;
    }
    await loadDoc(target, anchor);
  } catch (error) {
    $("#docs-list").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadDoc(name, anchor) {
  try {
    const doc = await api("/api/docs/" + encodeURIComponent(name));
    $("#doc-body").dataset.loaded = "1";
    $("#doc-body").innerHTML = `<p class="muted">${esc(doc.name)}</p>` + doc.html;
    if (anchor) {
      requestAnimationFrame(() => {
        const target = document.getElementById(anchor);
        if (target) target.scrollIntoView({block: "start"});
      });
    }
  } catch (error) {
    $("#doc-body").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadExercises() {
  try {
    const list = await api("/api/exercises");
    $("#exercise-options").innerHTML = list.map((e) =>
      `<option value="${esc(e.id)}">${esc(e.display)}</option>`).join("");
  } catch (error) { /* the page still works without the picker */ }
}





/* --- weekly volume ledger ------------------------------------------------ */
async function loadVolume() {
  const date = $("#prescribe-date").value;
  if (!date) { $("#volume-ledger").innerHTML = "<p class='empty'>Choose a date.</p>"; return; }
  try {
    const data = await api(`/api/volume?date=${encodeURIComponent(date)}&weeks=4`);
    if (!data.patterns.length) {
      $("#volume-ledger").innerHTML = "<p class='empty'>No working sets in the window.</p>";
      return;
    }
    const rows = data.patterns.map((row) => `<tr>
      <td><code>${esc(row.pattern)}</code></td>
      <td>${row.average}</td><td>${row.total}</td>
      <td>${row.mev ?? "—"}</td>
      <td>${row.mav ? row.mav[0] + "–" + row.mav[1] : "—"}</td>
      <td>${row.mrv ?? "—"}</td>
      <td>${esc(row.status)}</td></tr>`).join("");
    const heavy = data.heavy_spinal;
    const heavyLine = heavy
      ? `<p class="muted">Heavy spinal sets (RIR ≤ ${heavy.rir_max}): <strong>${heavy.total_sets}</strong>
         in the last ${heavy.window_weeks} weeks. Context only; not load-weighted and not part of the cap.</p>`
      : "";
    $("#volume-ledger").innerHTML = `<p class="muted">${esc(data.from)} to ${esc(data.to)}</p>${heavyLine}
      <table><thead><tr><th>pattern</th><th>avg sets/week</th><th>total</th>
      <th>MEV</th><th>MAV</th><th>MRV</th><th>status</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="muted">MEV/MAV/MRV are configurable coaching landmarks, not measured individual thresholds.</p>`;
  } catch (error) {
    $("#volume-ledger").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadVolumeBudget() {
  const date = $("#prescribe-date").value;
  if (!date) { $("#volume-budget").innerHTML = "<p class='empty'>Choose a date.</p>"; return; }
  try {
    const data = await api(`/api/volume/budget?date=${encodeURIComponent(date)}`);
    const rows = Object.entries(data.targets).map(([key, target]) => {
      const done = data.completed[key] ?? 0;
      const projected = data.projection[key] ?? 0;
      const short = Math.max(0, (data.effective_targets[key] ?? 0) - projected);
      const diag = (data.per_pattern || {})[key] || {};
      const persistent = (diag.persistent || {}).status || "—";
      return `<tr><td><code>${esc(key)}</code></td><td>${fmt(target, 1)}</td>
        <td>${fmt(done, 1)}</td><td>${fmt(projected, 1)}</td><td>${fmt(short, 1)}</td>
        <td>${esc(diag.status || "fixed")}</td>
        <td>${diag.top_up_capacity ? diag.top_up_capacity.sets : "—"}</td>
        <td>${esc(persistent)}</td></tr>`;
    }).join("");
    const blocked = Object.entries(data.per_pattern || {})
      .filter(([, diag]) => diag.status === "under" && diag.top_up_capacity.sets === 0)
      .map(([key]) => key);
    const blockedLine = blocked.length
      ? `<p class="muted">Under with no top-up capacity: ${blocked.map(esc).join(", ")} (programme decision).</p>`
      : "";
    const feasibility = data.feasibility;
    const planLine = data.plan
      ? `<p class="muted">Today <strong>${esc(data.today.session_type)}</strong>: ${esc(data.plan.action)};
         projected ${fmt(data.plan.total_before, 1)} to ${fmt(data.plan.total_after, 1)};
         estimated ${fmt(data.plan.time_minutes, 1)} min.${data.plan.unreachable_sets ? ` Below the band by ${fmt(data.plan.unreachable_sets, 1)} sets.` : ""}</p>`
      : `<p class="muted">Today's session is already recorded.</p>`;
    const comp = data.compensation || {};
    const compLine = comp.enabled
      ? `<p class="muted">Compensation preview (9a, read-only): ${comp.selected
          ? `${esc(comp.selected.exercise_id)} into ${esc(comp.selected.group)} at ${fmt(comp.selected.sets, 1)} sets (weight ${fmt(comp.selected.weight, 2)})`
          : esc(comp.status)}. No prescription change.</p>`
      : "";
    $("#volume-budget").innerHTML = `
      <p class="muted">Week ${esc(data.week.start)} to ${esc(data.week.end)} · target ${fmt(data.total_target, 1)} ·
        exempt ${fmt(Object.values(data.exempt).reduce((a, b) => a + b, 0), 1)} ·
        effective ${fmt(data.total_effective, 1)} ·
        completed ${fmt(Object.values(data.completed).reduce((a, b) => a + b, 0), 1)} ·
        projected ${fmt(data.total_projected, 1)} · band ±${fmt(data.band.total, 1)}</p>
      <p class="muted">Session cap ${data.session_cap.total} sets · sessions ${data.sessions_done}/${data.sessions_target} ·
        minimum ${feasibility.min_sessions} · ${feasibility.reachable ? "reachable" : "unreachable"}</p>
      <table><thead><tr><th>pattern</th><th>target</th><th>done</th><th>projected</th><th>short</th>
        <th>status</th><th>cap</th><th>4-wk</th></tr></thead>
      <tbody>${rows}</tbody></table>
      ${blockedLine}
      ${planLine}
      ${compLine}
      <p class="muted">${esc(data.note)}</p>`;
  } catch (error) {
    $("#volume-budget").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

/* --- regime change ------------------------------------------------------ */
async function loadRegime() {
  const date = $("#prescribe-date").value;
  if (!date) { $("#regime-result").innerHTML = "<p class='empty'>Choose a date.</p>"; return; }
  $("#regime-msg").textContent = "Checking…";
  try {
    const data = await api(`/api/regime?date=${encodeURIComponent(date)}&weeks=8`);
    const rows = (data.findings || []).map((finding) => {
      const subs = (finding.substitutes || []).map((sub) =>
        `<div>${esc(sub.exercise_id)}: ${sub.baseline_sets} → ${sub.current_sets} sets
         (+${sub.increase})</div>`).join("") || "<span class='muted'>no same-category substitute</span>";
      return `<tr><td><strong>${esc(finding.main_lift)}</strong>
        <div class="muted">${esc(finding.category || "—")} · ${esc(finding.kind)}</div></td>
        <td>${finding.baseline_sets} → ${finding.current_sets}<div class="muted">sets</div></td>
        <td>${finding.drop_pct}%</td><td>${subs}</td></tr>`;
    }).join("");
    if (rows) {
      $("#regime-result").innerHTML = `<table><thead><tr><th>Main lift</th><th>Volume</th>
        <th>drop</th><th>Same-category rise</th></tr></thead><tbody>${rows}</tbody></table>
        <p class="muted">${esc(data.note)}</p>`;
    } else {
      const coverage = data.coverage || {};
      $("#regime-result").innerHTML = `<p><strong>No regime change detected.</strong></p>
        <p class="muted">Checked ${coverage.main_lifts_checked ?? 0} main lift(s) with at least
        four baseline sets. No main lift fell to 25% or less of its prior volume while a
        same-category substitute rose by two or more sets in this window.</p>
        <p class="muted">${esc(data.note)}</p>`;
    }
    $("#regime-msg").textContent = "Checked " + data.coverage.main_lifts_checked + " main lift(s).";
  } catch (error) {
    $("#regime-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
    $("#regime-msg").textContent = "";
  }
}
$("#regime-run").addEventListener("click", loadRegime);

/* --- continuity calibration --------------------------------------------- */
async function loadContinuity() {
  const date = $("#prescribe-date").value;
  if (!date) { $("#continuity-model").innerHTML = "<p class='empty'>Choose a date.</p>"; return; }
  try {
    const data = await api(`/api/continuity?date=${encodeURIComponent(date)}`);
    $("#continuity-relax").checked = !!data.allow_relax_fixed;
    const c = data.calibration;
    $("#continuity-status").textContent = c.applied
      ? "calibrated factors applied"
      : "fixed rule in use";
    const rows = Object.keys(c.bands).map((key) => {
      const b = c.bands[key];
      const ci = b.ci_low == null ? "—" : `${b.ci_low}–${b.ci_high}`;
      return `<tr><td><strong>${esc(key)}</strong></td><td>${b.n}</td>
        <td>${b.median == null ? "—" : b.median}</td><td>${ci}</td>
        <td>${b.fixed}</td><td><strong>${b.factor}</strong></td>
        <td>${esc(b.status)}${b.applied ? " · applied" : ""}</td>
        <td class="muted">${esc(b.reason)}</td></tr>`;
    }).join("");
    $("#continuity-model").innerHTML = `<p class="muted">${c.n_total} return(s);
      ${c.applied ? "calibrated factors applied" : "fixed rule in use"}.</p>
      <table><thead><tr><th>band</th><th>n</th><th>median</th><th>95% CI</th>
      <th>fixed</th><th>factor</th><th>status</th><th>reason</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  } catch (error) {
    $("#continuity-model").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

$("#continuity-save").addEventListener("click", async () => {
  const value = $("#continuity-relax").checked;
  $("#continuity-msg").textContent = "Saving…";
  try {
    const data = await api("/api/continuity/settings", {
      method: "POST", body: JSON.stringify({ allow_relax_fixed: value }),
    });
    $("#continuity-relax").checked = !!data.allow_relax_fixed;
    $("#continuity-msg").textContent = "Saved";
    notify("Continuity setting saved.");
    await loadContinuity();
  } catch (error) {
    $("#continuity-msg").textContent = error.message;
  }
});

/* --- exercise catalogue -------------------------------------------------- */
const EXERCISE_KNOWN = [
  "display", "log_names", "pattern", "primary_muscles", "primary_compound",
  "loadable", "bodyweight_type", "time_based", "e1rm_applicable", "vbt_family",
  "main_lift", "high_fatigue_spinal", "erector_family", "direct_erector",
];

function openExerciseEditor(row) {
  const props = row ? JSON.parse(JSON.stringify(row.props || {})) : {
    display: "", log_names: [], pattern: "", primary_muscles: [],
    primary_compound: false, loadable: true, bodyweight_type: false,
    time_based: false, e1rm_applicable: true,
  };
  $("#exercise-editor").hidden = false;
  $("#exercise-editor-title").textContent = row ? "Edit " + row.id : "Add exercise";
  $("#exercise-id").value = row ? row.id : "";
  $("#exercise-id").readOnly = !!row;
  $("#exercise-display").value = props.display || "";
  $("#exercise-pattern").value = props.pattern || "";
  $("#exercise-vbt").value = props.vbt_family || "";
  $("#exercise-log-names").value = (props.log_names || []).join("\n");
  $("#exercise-muscles").value = (props.primary_muscles || []).join(", ");
  $("#exercise-compound").checked = !!props.primary_compound;
  $("#exercise-loadable").checked = props.loadable !== false;
  $("#exercise-bodyweight").checked = !!props.bodyweight_type;
  $("#exercise-timed").checked = !!props.time_based;
  $("#exercise-e1rm").checked = props.e1rm_applicable !== undefined
    ? !!props.e1rm_applicable
    : (props.loadable !== false && !props.time_based && !props.bodyweight_type);
  $("#exercise-main").checked = !!props.main_lift;
  $("#exercise-spinal").checked = !!props.high_fatigue_spinal;
  $("#exercise-erector").checked = !!props.erector_family;
  $("#exercise-direct-erector").checked = !!props.direct_erector;
  $("#exercise-msg").textContent = row ? "source: " + row.source : "new override entity";
  const extra = { ...props };
  EXERCISE_KNOWN.forEach((key) => delete extra[key]);
  $("#exercise-extra").value = Object.keys(extra).length ? JSON.stringify(extra, null, 2) : "{}";
  $("#exercise-editor").scrollIntoView({ behavior: "smooth", block: "start" });
}

function openExerciseDetails(row) {
  const props = JSON.parse(JSON.stringify(row.props || {}));
  window.__exerciseDetailsId = row.id;
  $("#exercise-details-title").textContent = row.id + " · " + (row.display || "");
  $("#exercise-detail-display").value = props.display || row.display || "";
  $("#exercise-detail-pattern").value = props.pattern || row.pattern || "";
  $("#exercise-detail-vbt").value = props.vbt_family || "";
  $("#exercise-detail-spinal-cost").value = props.spinal_cost == null ? "" : props.spinal_cost;
  $("#exercise-detail-log-names").value = (props.log_names || []).join("\n");
  $("#exercise-detail-muscles").value = (props.primary_muscles || []).join(", ");
  $("#exercise-detail-compound").checked = !!props.primary_compound;
  $("#exercise-detail-loadable").checked = props.loadable !== false;
  $("#exercise-detail-bodyweight").checked = !!props.bodyweight_type;
  $("#exercise-detail-timed").checked = !!props.time_based;
  $("#exercise-detail-e1rm").checked = props.e1rm_applicable !== undefined
    ? !!props.e1rm_applicable
    : (props.loadable !== false && !props.time_based && !props.bodyweight_type);
  $("#exercise-detail-main").checked = !!props.main_lift;
  $("#exercise-detail-spinal").checked = !!props.high_fatigue_spinal;
  $("#exercise-detail-erector").checked = !!props.erector_family;
  $("#exercise-detail-direct-erector").checked = !!props.direct_erector;
  $("#exercise-detail-day-roles").value = (props.day_roles || []).join(", ");
  const extra = { ...props };
  EXERCISE_KNOWN.forEach((key) => delete extra[key]);
  delete extra.spinal_cost;
  delete extra.day_roles;
  $("#exercise-detail-extra").value = Object.keys(extra).length
    ? JSON.stringify(extra, null, 2) : "{}";
  $("#exercise-details-msg").textContent = "source: " + row.source;
  $("#exercise-details-dialog").showModal();
}

function saveExerciseDetails(event) {
  event.preventDefault();
  const id = window.__exerciseDetailsId;
  if (!id) return;
  let extra;
  try {
    extra = JSON.parse($("#exercise-detail-extra").value.trim() || "{}");
  } catch (error) {
    $("#exercise-details-msg").textContent = "Additional properties must be valid JSON.";
    return;
  }
  const props = Object.assign({}, extra, {
    display: $("#exercise-detail-display").value.trim(),
    log_names: $("#exercise-detail-log-names").value.split("\n").filter((line) => line.length > 0),
    pattern: $("#exercise-detail-pattern").value.trim(),
    primary_muscles: $("#exercise-detail-muscles").value.split(",").map((m) => m.trim()).filter(Boolean),
    primary_compound: $("#exercise-detail-compound").checked,
    loadable: $("#exercise-detail-loadable").checked,
    bodyweight_type: $("#exercise-detail-bodyweight").checked,
    time_based: $("#exercise-detail-timed").checked,
    e1rm_applicable: $("#exercise-detail-e1rm").checked,
    main_lift: $("#exercise-detail-main").checked,
    high_fatigue_spinal: $("#exercise-detail-spinal").checked,
    erector_family: $("#exercise-detail-erector").checked,
    direct_erector: $("#exercise-detail-direct-erector").checked,
    day_roles: $("#exercise-detail-day-roles").value.split(",").map((v) => v.trim()).filter(Boolean),
  });
  if ($("#exercise-detail-vbt").value.trim()) props.vbt_family = $("#exercise-detail-vbt").value.trim();
  else delete props.vbt_family;
  if ($("#exercise-detail-spinal-cost").value !== "") {
    props.spinal_cost = Number($("#exercise-detail-spinal-cost").value);
  } else {
    delete props.spinal_cost;
  }
  if (!props.day_roles.length) delete props.day_roles;
  $("#exercise-details-msg").textContent = "Saving…";
  api("/api/exercises", { method: "POST", body: JSON.stringify({ id, props }) })
    .then((data) => {
      window.__exerciseCatalog = data;
      $("#exercise-details-dialog").close();
      loadExerciseCatalog();
      loadExercises();
    })
    .catch((error) => { $("#exercise-details-msg").textContent = error.message; });
}

$("#exercise-details-cancel").addEventListener("click", () => $("#exercise-details-dialog").close());
$("#exercise-details-form").addEventListener("submit", saveExerciseDetails);
function renderExerciseCatalog() {
  const data = window.__exerciseCatalog;
  if (!data) return;
  const query = ($("#exercise-search").value || "").toLowerCase();
  const pattern = $("#exercise-filter").value;
  const rows = data.entities.filter((row) => {
    if (pattern && row.pattern !== pattern) return false;
    const haystack = [row.id, row.display, row.pattern,
      ...(row.props.log_names || [])].join(" ").toLowerCase();
    return !query || haystack.includes(query);
  });
  if (!rows.length) {
    $("#exercise-catalog").innerHTML = "<p class='empty'>No exercises match.</p>";
    return;
  }
  const body = rows.map((row) => {
    const p = row.props || {};
    const flags = [
      p.primary_compound ? "compound" : "",
      p.bodyweight_type ? "bodyweight" : "",
      p.time_based ? "timed" : "",
      p.e1rm_applicable === false ? "no e1rm" : "",
      p.main_lift ? "main lift" : "",
      p.high_fatigue_spinal ? "high spinal" : "",
    ].filter(Boolean).map((f) => `<span class="pill">${esc(f)}</span>`).join("");
    const names = (p.log_names || []).map((n) => `<code>${esc(n)}</code>`).join(", ");
    return `<tr>
      <td><strong>${esc(row.display)}</strong><div class="muted"><code>${esc(row.id)}</code>
        · ${esc(row.source)}</div></td>
      <td><code>${esc(row.pattern || "—")}</code></td>
      <td>${(p.primary_muscles || []).map((m) => `<span class="pill">${esc(m)}</span>`).join("") || "—"}</td>
      <td>${flags || "—"}</td>
      <td>${names || "—"}</td>
      <td><button class="ghost" data-details-exercise="${esc(row.id)}">Details</button>
        <button class="ghost" data-edit-exercise="${esc(row.id)}">Edit</button>
        <button class="ghost" data-e1rm-exercise="${esc(row.id)}" title="Append an e1RM override for this lift">e1RM</button>
        <details><summary class="muted">all fields</summary>
        <pre class="props">${esc(JSON.stringify(p, null, 2))}</pre></details></td>
    </tr>`;
  }).join("");
  $("#exercise-catalog").innerHTML = `<div class="table-scroll"><table class="exercise-table">
    <thead><tr><th>Exercise</th><th>Pattern</th><th>Primary muscles</th><th>Flags</th>
    <th>Log names</th><th></th></tr></thead><tbody>${body}</tbody></table></div>`;
  document.querySelectorAll("[data-edit-exercise]").forEach((button) => {
    button.addEventListener("click", () => {
      const row = window.__exerciseCatalog.entities.find((e) => e.id === button.dataset.editExercise);
      if (row) openExerciseEditor(row);
    });
  });
  document.querySelectorAll("[data-details-exercise]").forEach((button) => {
    button.addEventListener("click", () => {
      const row = window.__exerciseCatalog.entities.find((e) => e.id === button.dataset.detailsExercise);
      if (row) openExerciseDetails(row);
    });
  });
  document.querySelectorAll("[data-e1rm-exercise]").forEach((button) => {
    button.addEventListener("click", () => openExerciseE1rm(button.dataset.e1rmExercise));
  });
}

function renderExerciseE1rmCurrent(exerciseId, overrides) {
  const onDate = today();
  const forLift = (overrides || []).filter((row) => row.exercise_id === exerciseId);
  const inForce = forLift
    .filter((row) => String(row.effective_from) <= onDate
      && (!row.expires_on || String(row.expires_on) >= onDate))
    .sort((a, b) => String(b.effective_from).localeCompare(String(a.effective_from)));
  $("#exercise-e1rm-current").textContent = inForce.length
    ? `active override ${inForce[0].e1rm_kg} kg from ${inForce[0].effective_from} (${forLift.length} recorded)`
    : forLift.length
      ? `${forLift.length} recorded, none in force today`
      : "no override — the load uses the formula estimate";
}

async function openExerciseE1rm(exerciseId) {
  const panel = $("#exercise-e1rm-panel");
  panel.hidden = false;
  $("#exercise-e1rm-id").value = exerciseId;
  $("#exercise-e1rm-kg").value = "";
  $("#exercise-e1rm-date").value = today();
  $("#exercise-e1rm-reason").value = "";
  $("#exercise-e1rm-msg").textContent = "";
  $("#exercise-e1rm-current").textContent = "Loading…";
  try {
    const state = await api("/api/state");
    renderExerciseE1rmCurrent(exerciseId, state.e1rm_overrides);
  } catch (error) {
    $("#exercise-e1rm-current").textContent = error.message;
  }
  panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

$("#exercise-e1rm-close").addEventListener("click", () => {
  $("#exercise-e1rm-panel").hidden = true;
});

$("#exercise-e1rm-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const exerciseId = $("#exercise-e1rm-id").value;
  const kg = $("#exercise-e1rm-kg").value;
  $("#exercise-e1rm-msg").textContent = "Saving…";
  try {
    const state = await api("/api/state/e1rm", {
      method: "POST",
      body: JSON.stringify({
        exercise_id: exerciseId,
        e1rm_kg: kg,
        effective_from: $("#exercise-e1rm-date").value || null,
        reason: $("#exercise-e1rm-reason").value || null,
      }),
    });
    renderExerciseE1rmCurrent(exerciseId, state.e1rm_overrides);
    $("#exercise-e1rm-msg").textContent = `Saved ${kg} kg for ${exerciseId}.`;
    $("#exercise-e1rm-kg").value = "";
    notify("e1RM override appended.");
  } catch (error) {
    $("#exercise-e1rm-msg").innerHTML = `<span class="warnbox">${esc(error.message)}</span>`;
  }
});

async function loadExerciseCatalog() {
  try {
    const data = await api("/api/exercises/catalog");
    window.__exerciseCatalog = data;
    const select = $("#exercise-filter");
    const current = select.value;
    select.innerHTML = "<option value=''>all patterns</option>" +
      data.patterns.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
    select.value = current;
    $("#exercise-patterns").innerHTML = data.patterns.map((p) => `<option value="${esc(p)}">`).join("");
    renderExerciseCatalog();
  } catch (error) {
    $("#exercise-catalog").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

$("#exercise-search").addEventListener("input", renderExerciseCatalog);
$("#exercise-filter").addEventListener("change", renderExerciseCatalog);
$("#exercise-refresh").addEventListener("click", loadExerciseCatalog);
$("#exercise-add").addEventListener("click", () => openExerciseEditor(null));
$("#exercise-cancel").addEventListener("click", () => { $("#exercise-editor").hidden = true; });

$("#exercise-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = $("#exercise-id").value.trim();
  const extraText = $("#exercise-extra").value.trim() || "{}";
  let extra;
  try { extra = JSON.parse(extraText); } catch (error) {
    $("#exercise-msg").textContent = "Additional properties must be valid JSON: " + error.message;
    return;
  }
  if (!extra || Array.isArray(extra) || typeof extra !== "object") {
    $("#exercise-msg").textContent = "Additional properties must be a JSON object.";
    return;
  }
  const props = Object.assign({}, extra, {
    display: $("#exercise-display").value.trim(),
    log_names: $("#exercise-log-names").value.split("\n").filter((line) => line.length > 0),
    pattern: $("#exercise-pattern").value.trim(),
    primary_muscles: $("#exercise-muscles").value.split(",").map((m) => m.trim()).filter(Boolean),
    primary_compound: $("#exercise-compound").checked,
    loadable: $("#exercise-loadable").checked,
    bodyweight_type: $("#exercise-bodyweight").checked,
    time_based: $("#exercise-timed").checked,
    e1rm_applicable: $("#exercise-e1rm").checked,
    vbt_family: $("#exercise-vbt").value.trim() || null,
    main_lift: $("#exercise-main").checked,
    high_fatigue_spinal: $("#exercise-spinal").checked,
    erector_family: $("#exercise-erector").checked,
    direct_erector: $("#exercise-direct-erector").checked,
  });
  if (!props.vbt_family) delete props.vbt_family;
  $("#exercise-msg").textContent = "Saving…";
  try {
    const data = await api("/api/exercises", { method: "POST", body: JSON.stringify({ id, props }) });
    window.__exerciseCatalog = data;
    $("#exercise-editor").hidden = true;
    notify("Exercise saved.");
    await loadExerciseCatalog();
    await loadExercises();
  } catch (error) {
    $("#exercise-msg").textContent = error.message;
  }
});

/* --- programme ---------------------------------------------------------- */
function programmeStatus(entry) {
  if (entry.deload_applied || entry.deload_reason) return "deload";
  if (entry.deload_suggestion) return "suggested deload";
  if (!entry.prescription.executable) return "not executable";
  return entry.prescription.fallback_level || "forecast";
}

function renderProgramme(entries) {
  if (!entries.length) {
    $("#programme-result").innerHTML = "<p class='warnbox'>No sessions in that horizon.</p>";
    return;
  }
  const rows = entries.map((entry) => {
    const stress = entry.prescription.notes?.recent_stress || {};
    const items = entry.prescription.items.map((item) => {
      const st = stress[item.exercise_id];
      const lr = (entry.prescription.notes?.per_lift_readiness || {})[item.exercise_id];
      const tag = st && st.status === "high" ? " · high stress" :
        (st && st.status === "normal" ? " · normal stress" : "");
      const rtag = lr && lr.status !== "ready" ? ` · readiness ${lr.score}` : "";
      return `<li>${esc(item.exercise_id)} — ${item.sets}×${item.reps_low}-${item.reps_high}
       @ ${fmt(item.load_kg)} kg, RIR ${esc(item.rir_target)}${tag}${rtag}</li>`;
    }).join("");
    const warn = entry.prescription.warnings.length
      ? `<details><summary>${entry.prescription.warnings.length} warning(s)</summary><ul>${entry.prescription.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></details>`
      : "<span class='empty'>none</span>";
    return `<tr>
      <td>${esc(entry.date)}</td>
      <td><strong>${esc(sessionLabel(entry.session_type))}</strong>
        ${entry.prescription.notes?.selection?.requested
          ? `<div class="muted">selection ${entry.prescription.notes.selection.applied ? "applied" : "preview"}${entry.prescription.notes.selection.llm_used ? " · LLM" : entry.prescription.notes.selection.llm_requested ? " · LLM fallback" : ""}</div>`
          : ""}</td>
      <td>${esc(programmeStatus(entry))}</td>
      <td><ul class="plain">${items}</ul>
        ${entry.deload_reason ? `<p class="warnbox">deload applied: ${esc(entry.deload_reason)}</p>` : ""}
        ${entry.deload_suggestion ? `<p class="warnbox">deload suggested: ${esc(entry.deload_suggestion)}</p>` : ""}
        ${warn}</td>
    </tr>`;
  }).join("");
  $("#programme-result").innerHTML = `<div class="panel"><table>
    <thead><tr><th>Date</th><th>Session type</th><th>Status</th><th>Session</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

let programmeBusy = false;
let programmeQueued = false;
let programmeHasResult = false;

function programmeSelectionChanged() {
  syncProgrammeSelection();
  if (programmeBusy) {
    programmeQueued = true;
  } else if (programmeHasResult) {
    $("#programme-result").innerHTML =
      "<p class='muted'>Selection options changed; build the forecast again to apply them.</p>";
    programmeHasResult = false;
  }
}

function syncProgrammeSelection() {
  const on = $("#programme-apply-selection").checked;
  $("#programme-selection-llm-wrap").hidden = !on;
  $("#programme-selection-confirm-wrap").hidden = !on;
  if (!on) {
    $("#programme-selection-llm").checked = false;
    $("#programme-selection-confirm").checked = false;
  }
}
$("#programme-apply-selection")?.addEventListener("change", programmeSelectionChanged);
$("#programme-selection-llm")?.addEventListener("change", programmeSelectionChanged);
$("#programme-selection-confirm")?.addEventListener("change", programmeSelectionChanged);
syncProgrammeSelection();

async function runProgramme() {
  if (programmeBusy) {
    programmeQueued = true;
    return;
  }
  programmeBusy = true;
  const applySelection = $("#programme-apply-selection").checked;
  const payload = {
    weeks: Number($("#programme-weeks").value || 4),
    remaining: $("#programme-remaining").checked,
    start: $("#programme-start").value || null,
    sessions_per_week: Number($("#programme-per-week").value || 3),
    start_session_type: $("#programme-session-type").value || "auto",
    apply_selection: applySelection,
    selection_llm: applySelection && $("#programme-selection-llm").checked,
    selection_confirmed: applySelection && $("#programme-selection-confirm").checked,
  };
  const button = $("#programme-form button[type='submit']");
  $("#programme-result").innerHTML = "<p class='empty'>Building forecast… each week is three prescriptions, so this takes a few seconds.</p>";
  button.disabled = true;
  try {
    const data = await api("/api/programme", { method: "POST", body: JSON.stringify(payload) });
    if (!programmeQueued) {
      renderProgramme(data.entries);
      programmeHasResult = true;
    }
  } catch (error) {
    if (!programmeQueued) {
      $("#programme-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
    }
  } finally {
    button.disabled = false;
    programmeBusy = false;
    if (programmeQueued) {
      programmeQueued = false;
      runProgramme();
    }
  }
}

/* --- cardio ------------------------------------------------------------- */
function renderCardio(data) {
  const weeks = Object.entries(data.weekly_minutes || {}).map(([week, minutes]) =>
    `<tr><td>${esc(week)}</td><td>${minutes}</td></tr>`).join("");
  const modalities = Object.entries(data.by_modality || {}).map(([name, count]) =>
    `<tr><td>${esc(name)}</td><td>${count}</td></tr>`).join("");
  $("#cardio-result").innerHTML = `
    <div class="panel"><div class="panel-head"><h2>Summary</h2>
      <span class="muted">${esc(data.from_date)} to ${esc(data.to_date)}</span></div>
      <p><strong>${data.total_minutes}</strong> min across <strong>${data.sessions}</strong>
        session(s) · <strong>${data.average_weekly_minutes}</strong> min/week average</p>
      <p class="muted">Reference: ${data.reference_min}-${data.reference_max} min/week.
        ${esc(data.reference_note)}</p>
      ${weeks ? `<table><thead><tr><th>Week</th><th>Minutes</th></tr></thead>
        <tbody>${weeks}</tbody></table>` : "<p class='empty'>No cardio logged in this window.</p>"}
      ${modalities ? `<table><thead><tr><th>Modality</th><th>Sessions</th></tr></thead>
        <tbody>${modalities}</tbody></table>` : ""}
    </div>`;
}

function cardioWeeks() {
  return Number($("#cardio-weeks")?.value || 12);
}

async function loadCardio(weeks = null) {
  try {
    const params = new URLSearchParams({ weeks: weeks || cardioWeeks() });
    const asOf = $("#cardio-asof")?.value;
    if (asOf) params.set("date", asOf);
    const data = await api("/api/cardio?" + params.toString());
    renderCardio(data);
  } catch (error) {
    $("#cardio-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

$("#cardio-weeks").addEventListener("change", () => loadCardio());
$("#cardio-asof").addEventListener("change", () => loadCardio());

$("#cardio-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    date: $("#cardio-date").value || null,
    modality: $("#cardio-modality").value,
    minutes: $("#cardio-minutes").value,
    avg_hr: $("#cardio-avg-hr").value || null,
    max_hr: $("#cardio-max-hr").value || null,
    distance_km: $("#cardio-distance").value || null,
    srpe: $("#cardio-srpe").value || null,
    note: $("#cardio-note").value || null,
  };
  const button = $("#cardio-form button[type='submit']");
  button.disabled = true;
  try {
    await api("/api/cardio", { method: "POST", body: JSON.stringify(payload) });
    await loadCardio();
    $("#cardio-form").reset();
  } catch (error) {
    $("#cardio-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  } finally {
    button.disabled = false;
  }
});

/* --- measurements ------------------------------------------------------- */
let lastMeasurements = null;

function renderMeasurements(data) {
  lastMeasurements = data;
  const all = data.summary || [];
  const filter = $("#measure-filter").value;
  const summary = all.filter((m) => !filter || m.key === filter);
  const select = $("#measure-metric");
  if (!select.options.length) {
    select.innerHTML = all.map((m) =>
      `<option value="${esc(m.key)}">${esc(m.label)} (${esc(m.unit || "no unit")})</option>`
    ).join("");
  }
  const filterSelect = $("#measure-filter");
  if (filterSelect.options.length <= 1) {
    filterSelect.innerHTML = '<option value="">all metrics</option>' + all.map((m) =>
      `<option value="${esc(m.key)}">${esc(m.label)}</option>`).join("");
  }
  const rows = summary.map((m) => {
    const latest = m.latest_value == null ? "—" : `${m.latest_value} ${m.unit || ""}`;
    const change = m.change == null ? "" :
      `${m.change > 0 ? "+" : ""}${m.change} ${m.unit || ""}`;
    return `<tr><td><strong>${esc(m.label)}</strong>
      <div class="muted">${esc(m.key)} · ${m.higher_is_better ? "higher is better" : "lower is better"}</div></td>
      <td>${esc(latest)}</td><td>${esc(change)}</td>
      <td>${m.count}${m.latest_on ? `<div class="muted">${esc(m.latest_on)}</div>` : ""}</td></tr>`;
  }).join("");
  const entries = (data.entries || []).filter((e) => !filter || e.metric_key === filter)
    .slice().reverse().map((e) => `
    <tr><td>${esc(e.measured_on)}</td><td>${esc(e.metric_key)}</td>
    <td>${e.value}</td><td>${esc(e.method || "")}</td></tr>`).join("");
  $("#measure-result").innerHTML = `
    <div class="panel"><div class="panel-head"><h2>Latest</h2></div>
      <table><thead><tr><th>Metric</th><th>Latest</th><th>Change</th><th>Entries</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="panel"><div class="panel-head"><h2>Recent entries</h2></div>
      ${entries ? `<table><thead><tr><th>Date</th><th>Metric</th><th>Value</th><th>Method</th></tr></thead>
        <tbody>${entries}</tbody></table>` : "<p class='empty'>No measurements yet.</p>"}</div>`;
}

$("#measure-filter").addEventListener("change", () => {
  if (lastMeasurements) renderMeasurements(lastMeasurements);
});

async function loadMeasurements() {
  try {
    const data = await api("/api/measurements");
    renderMeasurements(data);
  } catch (error) {
    $("#measure-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

$("#measure-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#measure-form button[type='submit']");
  button.disabled = true;
  try {
    const data = await api("/api/measurements", {
      method: "POST",
      body: JSON.stringify({
        metric: $("#measure-metric").value,
        date: $("#measure-date").value || null,
        value: $("#measure-value").value,
        method: $("#measure-method").value || null,
        note: $("#measure-note").value || null,
      }),
    });
    renderMeasurements(data);
    $("#measure-value").value = "";
    $("#measure-note").value = "";
  } catch (error) {
    $("#measure-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  } finally {
    button.disabled = false;
  }
});

/* --- terminal ----------------------------------------------------------- */
const terminalHistory = [];
let terminalCursor = -1;

async function runTerminal(command) {
  const value = command.trim();
  if (!value) return;
  $("#terminal-output").textContent = "$ " + value + "\n\nRunning…";
  try {
    const data = await api("/api/terminal", { method: "POST", body: JSON.stringify({ command: value }) });
    $("#terminal-output").textContent = "$ " + value + "\n\n" + data.output +
      (data.returncode ? "\n[exit " + data.returncode + "]" : "");
  } catch (error) {
    $("#terminal-output").textContent = "$ " + value + "\n\n" + error.message;
  }
}

$("#programme-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runProgramme();
});
$("#terminal-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const command = $("#terminal-command").value;
  if (command.trim()) {
    terminalHistory.push(command.trim());
    terminalCursor = terminalHistory.length;
    $("#terminal-command").value = "";
    runTerminal(command);
  }
});
$("#terminal-command").addEventListener("keydown", (event) => {
  if (event.key === "ArrowUp" && terminalHistory.length) {
    terminalCursor = Math.max(0, terminalCursor - 1);
    $("#terminal-command").value = terminalHistory[terminalCursor];
    event.preventDefault();
  } else if (event.key === "ArrowDown") {
    terminalCursor = Math.min(terminalHistory.length, terminalCursor + 1);
    $("#terminal-command").value = terminalHistory[terminalCursor] || "";
    event.preventDefault();
  }
});

/* --- settings ----------------------------------------------------------- */
const SETTINGS_TARGET_KEY = "strength-coach.minimumTarget";
const SETTINGS_CLASS_C_KEY = "strength-coach.showClassC";
const SETTINGS_THEME_KEY = "strength-coach.theme";

function storedThemeMode() {
  const mode = localStorage.getItem(SETTINGS_THEME_KEY) || "system";
  return ["system", "light", "dark"].includes(mode) ? mode : "system";
}

function resolvedTheme(mode) {
  if (mode === "system") {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }
  return mode;
}

function applyTheme(mode) {
  const resolved = resolvedTheme(mode);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
  const select = $("#settings-theme");
  if (select) select.value = mode;
}

function setTheme(mode) {
  localStorage.setItem(SETTINGS_THEME_KEY, mode);
  applyTheme(mode);
  notify("Theme set to " + mode + ".");
}

if (window.matchMedia) {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => { if (storedThemeMode() === "system") applyTheme("system"); };
  if (media.addEventListener) media.addEventListener("change", onChange);
  else if (media.addListener) media.addListener(onChange);
}

function storedUiDefaults() {
  const target = localStorage.getItem(SETTINGS_TARGET_KEY) || "45";
  return {
    target: ["30", "45", "60"].includes(target) ? target : "45",
    classC: localStorage.getItem(SETTINGS_CLASS_C_KEY) === "1",
  };
}

function applyStoredUiDefaults() {
  const defaults = storedUiDefaults();
  const target = $("#prescribe-target");
  if (target) target.value = defaults.target;
  const classC = $("#selection-include-different");
  if (classC) classC.checked = defaults.classC;
  const settingsTarget = $("#settings-default-target");
  if (settingsTarget) settingsTarget.value = defaults.target;
  const settingsClassC = $("#settings-default-class-c");
  if (settingsClassC) settingsClassC.checked = defaults.classC;
}

function syncLlmFields() {
  const on = $("#settings-llm-enabled").checked;
  ["#settings-llm-model", "#settings-llm-base-url", "#settings-llm-api-key",
   "#settings-llm-clear-key", "#settings-llm-temperature", "#settings-llm-max-tokens",
   "#settings-llm-timeout", "#settings-llm-test"]
    .forEach((selector) => { const node = $(selector); if (node) node.disabled = !on; });
}

function renderModalities(data) {
  window.__modalities = data || {};
  const box = $("#settings-modalities");
  if (!box) return;
  box.innerHTML = (data.modules || []).map((module) => {
    const deps = (module.dependencies || []).map((dep) => {
      const ok = module.dependency_state?.[dep];
      return '<span class="badge ' + (ok ? "" : "warn") + '">' + esc(dep) + (ok ? "" : " (off)") + "</span>";
    }).join(" ") || '<span class="muted">no dependencies</span>';
    const factors = (module.factors || []).map((factor) =>
      '<code>' + esc(factor.key) + "</code>").join(" ") || '<span class="muted">no factors</span>';
    const cls = module.class === "hard_safety" ? "badge" :
      module.class === "guarded_safety" ? "badge warn" : "badge";
    const toggle = module.toggleable
      ? '<button type="button" data-modality-toggle="' + esc(module.id) + '">' +
        (module.enabled ? "Turn off" : "Turn on") + "</button>"
      : '<span class="muted">' + (module.class === "hard_safety" ? "read-only" : "always on") + "</span>";
    return '<div class="panel" style="margin:0 0 10px"><div class="panel-head"><h3>' +
      esc(module.label) + '</h3><span class="' + cls + '">' + esc(module.class) + "</span></div>" +
      '<div class="form-row"><span><strong>' + (module.enabled ? "on" : "off") +
      "</strong> · " + esc(module.enabled_source) + "</span>" + toggle + "</div>" +
      "<p class='muted'>Dependencies: " + deps + "</p>" +
      "<p class='muted'>Factors: " + factors + "</p>" +
      (module.citations?.length ? "<p class='muted'>Citations: " + esc(module.citations.join(", ")) + "</p>" : "") +
      "</div>";
  }).join("");
}

async function updateModality(moduleId) {
  const data = window.__modalities || {};
  const module = (data.modules || []).find((row) => row.id === moduleId);
  if (!module) return;
  try {
    const guarded = module.class === "guarded_safety";
    if (guarded) {
      if (!$("#settings-profile-guard").checked ||
          $("#settings-profile-guard-text").value.trim() !== "SPINAL" ||
          !$("#settings-profile-reason").value.trim()) {
        throw new Error("Guarded modules need the confirmation tick, SPINAL and a reason.");
      }
    }
    await api("/api/modalities/" + encodeURIComponent(moduleId), {
      method: "POST",
      body: JSON.stringify({
        enabled: !module.enabled,
        guard_confirmed: $("#settings-profile-guard").checked,
        reason: $("#settings-profile-reason").value.trim() || null,
      }),
    });
    $("#settings-profile-msg").textContent = "Module updated: " + moduleId;
    await loadSettings();
  } catch (error) {
    $("#settings-profile-msg").textContent = error.message;
  }
}

function renderSettings(data) {
  const llm = data.llm || {};
  window.__llmSettings = llm;
  $("#settings-llm-enabled").checked = !!llm.enabled;
  $("#settings-llm-model").value = llm.model || "";
  $("#settings-llm-base-url").value = llm.base_url || "";
  $("#settings-llm-temperature").value = llm.temperature ?? 0.2;
  $("#settings-llm-max-tokens").value = llm.max_tokens ?? 700;
  $("#settings-llm-timeout").value = llm.timeout_s ?? 30;
  $("#settings-llm-api-key").value = "";
  $("#settings-llm-api-key").placeholder = llm.api_key
    ? "stored: " + llm.api_key + " (leave blank to keep)"
    : "not set";
  $("#settings-llm-clear-key").checked = false;
  const status = $("#settings-llm-status");
  status.textContent = llm.enabled ? "enabled" : "off";
  status.className = "badge " + (llm.enabled ? "" : "warn");
  $("#settings-llm-source").textContent = "Source: " + (llm.source || "unknown")
    + (llm.enabled ? "" : " · deterministic mode; no model calls");
  $("#settings-version").textContent = data.version || "—";
  $("#settings-database").textContent = data.database || "—";
  $("#settings-config-path").textContent = data.llm_config_path || "—";
  applyStoredUiDefaults();
  applyTheme(storedThemeMode());
  syncLlmFields();
  renderDropSettings(data.drop || {});
}

function renderDropSettings(drop) {
  $("#settings-drop-enabled").checked = !!drop.enabled;
  $("#settings-drop-days").value = drop.competition_confirm_days ?? 7;
  $("#settings-drop-max").value = drop.max_slots_per_group ?? 1;
  $("#settings-drop-technique").value = drop.technique_minutes ?? 30;
  $("#settings-drop-tolerance").value = drop.tolerance ?? 0.1;
  $("#settings-drop-high").textContent = drop.high_band ?? "—";
  $("#settings-drop-slots").value = JSON.stringify(drop.slots || {}, null, 2);
  $("#settings-drop-msg").textContent = "source: " + (drop.source || "—");
}

function renderProfileSettings(registry, profile) {
  window.__profileSettings = profile || {};
  window.__settingsRegistry = registry || [];
  const fields = $("#settings-profile-fields");
  if (!fields) return;
  const groups = {};
  (registry || []).forEach((setting) => {
    (groups[setting.group] = groups[setting.group] || []).push(setting);
  });
  const resolved = window.__profileSettings.resolved || {};
  const overrides = window.__profileSettings.overrides || {};
  fields.innerHTML = Object.entries(groups).map(([group, settings]) => {
    const rows = settings.map((setting) => {
      const value = Object.prototype.hasOwnProperty.call(overrides, setting.key)
        ? overrides[setting.key] : resolved[setting.key];
      const id = "profile-" + setting.key.replace(/[^a-zA-Z0-9_-]/g, "-");
      let control;
      if (setting.kind === "bool") {
        control = '<input type="checkbox" data-profile-key="' + esc(setting.key) + '" id="' + id + '">';
      } else if (setting.kind === "int" || setting.kind === "float") {
        const step = setting.kind === "int" ? "1" : "0.01";
        const min = setting.minimum == null ? "" : ' min="' + setting.minimum + '"';
        const max = setting.maximum == null ? "" : ' max="' + setting.maximum + '"';
        control = '<input type="number" step="' + step + '"' + min + max + ' data-profile-key="' + esc(setting.key) + '" id="' + id + '">';
      } else if (setting.kind === "table") {
        control = '<textarea rows="3" spellcheck="false" data-profile-key="' + esc(setting.key) + '" id="' + id + '"></textarea>';
      } else if ((setting.choices || []).length) {
        control = '<select data-profile-key="' + esc(setting.key) + '" id="' + id + '">' +
          setting.choices.map((choice) => '<option value="' + esc(choice) + '">' + esc(choice) + '</option>').join("") + "</select>";
      } else {
        control = '<input type="text" data-profile-key="' + esc(setting.key) + '" id="' + id + '">';
      }
      const badge = setting.classification === "guarded_safety"
        ? ' <span class="badge warn">guarded</span>' : "";
      return '<label class="grow">' + esc(setting.label) + badge + control +
        '<span class="muted">' + esc(setting.key) + " · " + esc(setting.source) + "</span></label>";
    }).join("");
    return '<div class="panel" style="margin:0 0 10px"><div class="panel-head"><h3>' + esc(group) +
      '</h3><span class="muted">profile > config > default</span></div><div class="form-row">' + rows + "</div></div>";
  }).join("");
  (registry || []).forEach((setting) => {
    const node = document.getElementById("profile-" + setting.key.replace(/[^a-zA-Z0-9_-]/g, "-"));
    if (!node) return;
    const value = Object.prototype.hasOwnProperty.call(overrides, setting.key)
      ? overrides[setting.key] : resolved[setting.key];
    if (setting.kind === "bool") node.checked = !!value;
    else if (setting.kind === "table") node.value = JSON.stringify(value ?? {}, null, 2);
    else node.value = value ?? "";
    node.dataset.original = JSON.stringify(value ?? null);
    node.dataset.classification = setting.classification;
    node.addEventListener("input", updateProfileDiff);
    node.addEventListener("change", updateProfileDiff);
  });
  const meta = $("#settings-profile-meta");
  if (meta) {
    meta.textContent = window.__profileSettings.profile_id == null
      ? "config only" : "profile " + window.__profileSettings.profile_id +
        " · effective " + window.__profileSettings.effective_from;
    meta.className = "badge";
  }
  updateProfileDiff();
}

function profileNodeValue(node, setting) {
  if (setting.kind === "bool") return node.checked;
  if (setting.kind === "int") return Number(node.value);
  if (setting.kind === "float") return Number(node.value);
  if (setting.kind === "table") {
    try { return JSON.parse(node.value || "{}"); }
    catch (error) { throw new Error(setting.key + ": invalid JSON — " + error.message); }
  }
  return node.value;
}

function updateProfileDiff() {
  const registry = window.__settingsRegistry || [];
  const changes = [];
  try {
    registry.forEach((setting) => {
      const node = document.getElementById("profile-" + setting.key.replace(/[^a-zA-Z0-9_-]/g, "-"));
      if (!node) return;
      const value = profileNodeValue(node, setting);
      const original = JSON.parse(node.dataset.original || "null");
      if (JSON.stringify(value) !== JSON.stringify(original)) changes.push({ setting, value, original });
    });
  } catch (error) {
    $("#settings-profile-diff").textContent = error.message;
    return;
  }
  const box = $("#settings-profile-diff");
  if (!box) return;
  if (!changes.length) { box.textContent = "No changes."; return; }
  box.innerHTML = changes.map(({ setting, value, original }) =>
    '<div><code>' + esc(setting.key) + '</code>: ' + esc(JSON.stringify(original)) +
    " → " + esc(JSON.stringify(value)) + "</div>").join("");
}

function profileDraft() {
  const registry = window.__settingsRegistry || [];
  const set = {};
  const guarded = [];
  registry.forEach((setting) => {
    const node = document.getElementById("profile-" + setting.key.replace(/[^a-zA-Z0-9_-]/g, "-"));
    if (!node) return;
    const value = profileNodeValue(node, setting);
    const original = JSON.parse(node.dataset.original || "null");
    if (JSON.stringify(value) !== JSON.stringify(original)) {
      set[setting.key] = value;
      if (setting.classification === "guarded_safety") guarded.push(setting.key);
    }
  });
  return { set, guarded };
}

async function saveProfileDraft() {
  try {
    const { set, guarded } = profileDraft();
    if (!Object.keys(set).length) {
      $("#settings-profile-msg").textContent = "No changes to save.";
      return;
    }
    const reason = $("#settings-profile-reason").value.trim();
    if (guarded.length) {
      if (!$("#settings-profile-guard").checked ||
          $("#settings-profile-guard-text").value.trim() !== "SPINAL" || !reason) {
        throw new Error("Guarded changes need the confirmation tick, SPINAL and a reason.");
      }
    }
    await api("/api/settings/profile", {
      method: "POST",
      body: JSON.stringify({
        set, reason: reason || null, guard_confirmed: $("#settings-profile-guard").checked,
      }),
    });
    $("#settings-profile-msg").textContent = "Saved a new profile version.";
    $("#settings-profile-guard").checked = false;
    $("#settings-profile-guard-text").value = "";
    $("#settings-profile-reason").value = "";
    await loadSettings();
  } catch (error) {
    $("#settings-profile-msg").textContent = error.message;
  }
}

async function loadSettings() {
  try {
    const data = await api("/api/settings");
    const profile = await api("/api/settings/profile");
    const modalityData = await api("/api/modalities");
    renderSettings(data);
    renderProfileSettings(data.registry || [], profile);
    renderModalities(modalityData);
  } catch (error) {
    $("#settings-llm-status").textContent = "error";
    $("#settings-llm-msg").textContent = error.message;
  }
}

const moduleBox = $("#settings-modalities");
if (moduleBox) moduleBox.addEventListener("click", (event) => {
  const button = event.target.closest("[data-modality-toggle]");
  if (button) updateModality(button.dataset.modalityToggle);
});
const profileSave = $("#settings-profile-save");
if (profileSave) profileSave.addEventListener("click", saveProfileDraft);
const profileReset = $("#settings-profile-reset");
if (profileReset) profileReset.addEventListener("click", () => loadSettings());

function llmPayload() {
  return {
    enabled: $("#settings-llm-enabled").checked,
    model: $("#settings-llm-model").value.trim(),
    base_url: $("#settings-llm-base-url").value.trim(),
    api_key: $("#settings-llm-api-key").value,
    clear_api_key: $("#settings-llm-clear-key").checked,
    temperature: Number($("#settings-llm-temperature").value || 0.2),
    max_tokens: Number($("#settings-llm-max-tokens").value || 700),
    timeout_s: Number($("#settings-llm-timeout").value || 30),
  };
}

$("#settings-llm-enabled").addEventListener("change", syncLlmFields);
$("#settings-llm-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#settings-llm-msg").textContent = "Saving…";
  try {
    renderSettings(await api("/api/settings/llm", {
      method: "POST", body: JSON.stringify(llmPayload()),
    }));
    $("#settings-llm-msg").textContent = "Saved.";
    notify("LLM settings saved.");
  } catch (error) {
    $("#settings-llm-msg").textContent = error.message;
  }
});
$("#settings-llm-test").addEventListener("click", async () => {
  $("#settings-llm-msg").textContent = "Testing…";
  try {
    const result = await api("/api/settings/llm/test", { method: "POST", body: "{}" });
    $("#settings-llm-msg").textContent = "OK: " + result.model
      + (result.tokens == null ? "" : " · " + result.tokens + " tokens");
  } catch (error) {
    $("#settings-llm-msg").textContent = "Test failed: " + error.message;
  }
});
$("#settings-theme").addEventListener("change", () => {
  setTheme($("#settings-theme").value);
});

$("#settings-defaults-save").addEventListener("click", () => {
  const target = $("#settings-default-target").value;
  localStorage.setItem(SETTINGS_TARGET_KEY, target);
  localStorage.setItem(SETTINGS_CLASS_C_KEY, $("#settings-default-class-c").checked ? "1" : "0");
  applyStoredUiDefaults();
  $("#settings-defaults-msg").textContent = "Saved in this browser.";
  notify("Prescribe defaults saved in this browser.");
});

/* --- boot --------------------------------------------------------------- */
applyTheme(storedThemeMode());
applyStoredUiDefaults();
fillSessionSelect();
loadExercises();
loadOverview();
applyHashRoute();
