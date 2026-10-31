/* Local UI over the strength-coach HTTP API. No framework, no external assets. */
/* Dynamic rows carry data-* values; never build executable inline handlers. */
document.addEventListener("click", (event) => {
  const element = event.target instanceof Element
    ? event.target.closest("[data-action]") : null;
  if (!element) return;
  const action = element.dataset.action;
  if (action === "review-complete") completeReview(element.dataset.taskKey);
  else if (action === "review-snooze") snoozeReview(element.dataset.taskKey);
  else if (action === "open-review") openReview(element.dataset.session);
  else if (action === "comp-e1rm") recordCompensationE1rm(element.dataset.exerciseId);
  else if (action === "suggested-deload") applySuggestedDeload();
  else if (action === "open-workout-start") openWorkoutStart();
  else if (action === "readiness-preset") applyReadinessPreset(element.dataset.preset);
  else if (action === "edit-readiness-presets") openReadinessPresetEditor();
});



function setView(name, options = {}) {
  document.querySelectorAll("#nav button").forEach((b) => {
    const active = b.dataset.view === name;
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  document.querySelectorAll(".view").forEach((v) => {
    v.classList.toggle("active", v.id === "view-" + name);
  });
  if (name === "review") fillSessionSelect();
  if (name === "readiness") loadReadiness($("#readiness-date").value);
  if (name === "exercises") loadExerciseCatalog();
  if (name === "cardio") loadCardio();
  if (name === "measures") loadMeasurements();
  if (name === "prescribe") {
    loadFatigue(); loadContinuity(); loadVolume(); loadVolumeBudget(); loadExposure(); loadResidual(); loadShadowReview();
    restoreProgramme();
  }
  if (name === "workout") {
    loadReadiness($("#readiness-date").value);
    loadDropWindow();
    loadThrottlePatterns();
    updateWorkflowStep();
  }
  if (name === "docs") loadDocs(options.doc, options.anchor);
  if (name === "logs") loadLogs();
  if (name === "state") {
    loadState();
    loadSymptomHistory(false);
    loadTestCadence();
  }
  if (name === "settings") loadSettings();
  if (name === "history") loadHistory();
  if (name === "outcomes") loadOutcomes();
  if (name === "performance") loadPerformance();
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
/* Collapsible left menu. The menu is modal on every viewport: focus moves into it,
   the page behind it is inert, Tab is trapped, and Escape returns focus to the toggle. */
let sidebarReturnFocus = null;

function sidebarFocusables() {
  const sidebar = document.querySelector("#sidebar");
  if (!sidebar) return [];
  return [...sidebar.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter((node) => !node.disabled && !node.hidden);
}

function setSidebar(open) {
  const sidebar = document.querySelector("#sidebar");
  const backdrop = document.querySelector("#sidebar-backdrop");
  const toggle = document.querySelector("#menu-toggle");
  const main = document.querySelector("main");
  if (!sidebar || !backdrop || !toggle) return;
  if (open && sidebar.hidden) {
    sidebarReturnFocus = document.activeElement;
    sidebar.hidden = false;
    backdrop.hidden = false;
    sidebar.setAttribute("aria-modal", "true");
    sidebar.setAttribute("role", "dialog");
    if (main) main.inert = true;
    toggle.setAttribute("aria-expanded", "true");
    document.body.classList.add("menu-open");
    const close = document.querySelector("#sidebar-close");
    if (close) close.focus();
  } else if (!open && !sidebar.hidden) {
    sidebar.hidden = true;
    backdrop.hidden = true;
    sidebar.removeAttribute("aria-modal");
    sidebar.removeAttribute("role");
    if (main) main.inert = false;
    toggle.setAttribute("aria-expanded", "false");
    document.body.classList.remove("menu-open");
    const target = sidebarReturnFocus instanceof HTMLElement ? sidebarReturnFocus : toggle;
    sidebarReturnFocus = null;
    if (target && typeof target.focus === "function") target.focus();
  }
}
document.querySelector("#menu-toggle")?.addEventListener("click", () => setSidebar(true));
document.querySelector("#sidebar-close")?.addEventListener("click", () => setSidebar(false));
document.querySelector("#sidebar-backdrop")?.addEventListener("click", () => setSidebar(false));
document.querySelectorAll("#nav button").forEach((button) => {
  button.addEventListener("click", () => setSidebar(false));
});
document.addEventListener("keydown", (event) => {
  const sidebar = document.querySelector("#sidebar");
  if (!sidebar || sidebar.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    setSidebar(false);
    return;
  }
  if (event.key !== "Tab") return;
  const focusables = sidebarFocusables();
  if (!focusables.length) return;
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
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
    loadDropWindow();
    $("#today-title").textContent = data.profile ? "Coach" : "No athlete state yet";
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

function openTodaySession() {
  setView("workout");
  requestAnimationFrame(() => {
    const active = $("#workout-active-panel");
    const start = $("#workout-start-panel");
    const readiness = $("#workflow-readiness");
    const target = active && !active.hidden ? active
      : start && !start.hidden ? start : readiness;
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}
const todaySession = $("#today-session");
if (todaySession) todaySession.addEventListener("click", openTodaySession);

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
      const decisions = task.key === "phase5a_review"
        ? `<option value="changed">Proceed to Phase 5B</option>
           <option value="insufficient">Extend Phase 5A once</option>
           <option value="not_applicable">Close Phase 5A without Phase 5B</option>`
        : `<option value="kept">kept</option><option value="changed">changed</option>
           <option value="insufficient">insufficient</option>
           <option value="not_applicable">not applicable</option>`;
      const actions = task.periodic
        ? `<details><summary>Mark reviewed</summary>
             <div class="form-row">
               <label>Decision <select id="review-decision-${esc(task.key)}">
                 ${decisions}
               </select></label>
               <label class="grow">Note <input id="review-note-${esc(task.key)}" placeholder="optional"></label>
               <button type="button" data-action="review-complete" data-task-key="${esc(task.key)}">Save review</button>
               <button type="button" class="ghost" data-action="review-snooze" data-task-key="${esc(task.key)}">Snooze 2 weeks</button>
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
      <td><button class="ghost" data-action="open-review" data-session="${esc(s.session_id)}">Review</button></td></tr>`).join("")
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
    ? `<h3>Original prescription</h3><div class="table-scroll"><table><thead><tr><th>Exercise</th><th>Status</th>
       <th>Actual / planned</th></tr></thead><tbody>${(workout.original_comparison.items || [])
       .map((row) => `<tr><td>${esc(row.exercise_id)}</td><td>${esc(row.status)}</td>
       <td>${row.actual_sets} / ${row.planned_sets}</td></tr>`).join("")}</tbody></table></div>`
    : "";
  return `<details open><summary><strong>Actual vs planned</strong></summary>
    <div class="table-scroll"><table><thead><tr><th>Exercise</th><th>Status</th><th>Sets actual / planned</th>
    <th>Reps</th><th>kg</th></tr></thead><tbody>${rows}</tbody></table></div>
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
$("#prescribe-date").addEventListener("change", () => {
  loadDropWindow();
  loadVolumeBudget();
});
const volumeDate = $("#volume-date");
const continuityDate = $("#continuity-date");
const fatigueDate = $("#fatigue-date");
if (volumeDate && !volumeDate.value) volumeDate.value = $("#prescribe-date").value;
if (continuityDate && !continuityDate.value) continuityDate.value = $("#prescribe-date").value;
if (fatigueDate && !fatigueDate.value) fatigueDate.value = $("#prescribe-date").value;
if (volumeDate) volumeDate.addEventListener("change", loadVolume);
if ($("#volume-weeks")) $("#volume-weeks").addEventListener("change", loadVolume);
if ($("#volume-run")) $("#volume-run").addEventListener("click", loadVolume);
if (continuityDate) continuityDate.addEventListener("change", loadContinuity);
if ($("#fatigue-run")) $("#fatigue-run").addEventListener("click", loadFatigue);
if ($("#state-e1rm-calibration-run")) $("#state-e1rm-calibration-run").addEventListener("click", function () { loadE1rmPreview("calibration"); });
if ($("#state-e1rm-coverage-run")) $("#state-e1rm-coverage-run").addEventListener("click", function () { loadE1rmPreview("coverage"); });

/* The server owns the competition-window rule. Ask it whether the confirmation applies, rather
   than duplicating the date arithmetic in the browser; hide the control when it is inert and
   never send a stale true after it disappears. */
let dropWindowRequest = 0;
async function loadDropWindow() {
  const date = $("#prescribe-date")?.value;
  const request = ++dropWindowRequest;
  let result = {applies: false};
  if (date) {
    try {
      result = await api("/api/settings/drop/window?date=" + encodeURIComponent(date));
    } catch (error) {
      result = {applies: false};
    }
  }
  if (request !== dropWindowRequest) return;
  window.__dropWindow = result;
  updateDropConfirmVisibility();
}

function updateDropConfirmVisibility() {
  const wrap = $("#prescribe-drop-confirm-wrap");
  const input = $("#prescribe-drop-confirm");
  if (!wrap || !input) return;
  const show = Boolean(window.__dropWindow?.applies);
  wrap.hidden = !show;
  input.disabled = !show;
  if (!show) input.checked = false;
}

function syncMinimumSession() {
  const on = $("#prescribe-minimum").checked;
  $("#prescribe-minimum-options").hidden = !on;
  $("#prescribe-target").disabled = !on;
  $("#prescribe-minimum-main").disabled = !on;
  if (!on) $("#prescribe-minimum-main").checked = false;
}
$("#prescribe-minimum").addEventListener("change", syncMinimumSession);

function populateThrottlePatterns(patterns) {
  const select = $("#prescribe-throttle-pattern");
  if (!select) return;
  const values = [...new Set((patterns || []).map((pattern) =>
    typeof pattern === "string" ? pattern : pattern?.value
  ).filter(Boolean))];
  const chosen = new Set([...select.selectedOptions].map((option) => option.value));
  const mainSelected = !chosen.size || chosen.has("");
  select.innerHTML = `<option value=""${mainSelected ? " selected" : ""}>All lifts (main work)</option>`
    + values.map((value) =>
      `<option value="${esc(value)}"${chosen.has(value) ? " selected" : ""}>${esc(value)}</option>`
    ).join("");
  if (!select.selectedOptions.length) select.options[0].selected = true;
  select.dataset.loaded = "1";
}

async function loadThrottlePatterns() {
  const select = $("#prescribe-throttle-pattern");
  if (!select || select.dataset.loaded === "1") return;
  const cached = window.__exerciseCatalog?.patterns;
  if (cached && cached.length) {
    populateThrottlePatterns(cached);
    return;
  }
  try {
    const data = await api("/api/options");
    populateThrottlePatterns(data.patterns || []);
  } catch (error) {
    // Keep the "all lifts" option; the server still reports no-match for an empty scope.
  }
}

function syncTechniqueThrottle() {
  $("#prescribe-throttle-pattern-wrap").hidden = !$("#prescribe-technique").checked;
}

$("#prescribe-technique").addEventListener("change", () => {
  syncTechniqueThrottle();
  if ($("#prescribe-technique").checked) loadThrottlePatterns();
});
$("#prescribe-throttle-pattern").addEventListener("change", (event) => {
  if (!event.currentTarget.selectedOptions.length) event.currentTarget.options[0].selected = true;
});
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
    technique_throttle_pattern: [...$("#prescribe-throttle-pattern").selectedOptions]
      .map((option) => option.value),
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
        effective_from: lastPrescribePayload?.date || today(),
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

function volumePanelHtml(panel, label = "Weekly volume") {
  if (!panel || panel.target == null) return "";
  const groups = Object.entries(panel.groups || {}).filter(([, row]) => Number(row.target) > 0)
    .map(([key, row]) => "<tr><td>" + esc(key) + "</td><td>" + fmt(row.completed, 1) +
      "</td><td>" + fmt(row.after, 1) + "</td><td>" + fmt(row.target, 1) +
      "</td><td>" + fmt(row.remaining, 1) + "</td></tr>").join("");
  const warn = panel.high_band_reached || panel.feasibility?.reachable === false
    ? "<p class='warnbox'>" + (panel.high_band_reached ? "Week is at or above the high band." : "") +
      (panel.feasibility?.reachable === false ? " Target may be unreachable with the remaining sessions." : "") + "</p>"
    : "";
  return "<div class='panel' style='margin-top:1rem'><div class='panel-head'><h3>" +
    esc(label) + "</h3><span class='badge " + (panel.high_band_reached ? "warn" : "") + "'>" +
    fmt(panel.after, 1) + " / " + fmt(panel.target, 1) + " sets</span></div>" +
    "<p class='muted'>" + fmt(panel.completed, 1) + " completed before this session · " +
    fmt(panel.remaining, 1) + " remaining · sessions " + panel.sessions_done + "/" +
    panel.sessions_target + " · high band " + fmt(panel.band?.high, 1) + ".</p>" +
    warn + (groups ? "<div class='table-scroll'><table><thead><tr><th>Group</th><th>Done</th><th>After</th><th>Target</th><th>Remaining</th></tr></thead><tbody>" + groups + "</tbody></table></div>" : "") +
    "</div>";
}

function renderPrescription(p) {
  window.__lastPrescription = p;
  const sessionTime = p.notes?.session_time || {};
  const timeLine = sessionTime.estimated_minutes == null ? "" :
    `<p class="muted"><strong>Estimated session time:</strong> ~${fmt(sessionTime.estimated_minutes)} min
      <span class="muted">(planning estimate; excludes transitions and idle time)</span></p>`;
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
    <td>${fmt(item.load_kg)}</td><td>${item.effort_model === "quality"
      ? `quality stop<div class="muted">${esc(item.quality_stop || "")}</div>`
      : item.rir_target}</td>
    <td>${stressCell}</td>
    <td>${readyCell}</td>
    <td>${item.e1rm_source_sets == null ? "—" : item.e1rm_source_sets}</td>
    <td class="muted">${esc(item.refs.slice(-2).join(", "))}</td></tr>`;
  }).join("");
  const warnings = p.warnings.length
    ? '<div class="warnbox"><strong>Warnings</strong><ul class="list">' +
      p.warnings.map((w) => "<li>" + esc(w) + "</li>").join("") + "</ul></div>" : "";
  const volumeBox = p.notes?.volume_budget?.enabled
    ? volumePanelHtml(p.notes?.volume_panel) : "";
  const comp = p.notes?.compensation || {};
  const compSelected = comp.status === "refused" ? comp.selection?.selected : null;
  const compBox = compSelected
    ? `<div class="warnbox"><strong>Compensation needs an e1RM</strong>
       <p>${esc(comp.reason || "No usable e1RM")} for <code>${esc(compSelected.exercise_id)}</code>.</p>
       <label>e1RM (kg)<input id="comp-e1rm-kg" type="number" step="0.5" min="0"></label>
       <button type="button" class="primary" data-action="comp-e1rm" data-exercise-id="${esc(compSelected.exercise_id)}">Save e1RM and rebuild</button>
       <span id="comp-e1rm-msg" class="muted"></span></div>`
    : "";
  const selection = p.notes?.selection;
  const selectionSuggestions = (selection?.slots || []).filter(
    (s) => s.trigger && s.trigger !== "none" && s.changed
  );
  const selectionLlmWarning = selection?.llm_unavailable
    ? '<p class="warnbox">LLM requested but not configured; NullLLM fallback was used.</p>'
    : "";
  const selectionBox = selectionLlmWarning + (selection?.applied
    ? `<p class="muted">Selection applied (${esc(selection.llm_used ? "LLM" : "Python")}); substituted slots are cited as <code>MOD-SELECT-001</code>.</p>`
    : selection?.slots?.some((s) => s.blocked_reason)
      ? `<p class="warnbox">Selection skipped: ${esc(selection.slots.filter((s) => s.blocked_reason).map((s) => s.slot_id + " (" + s.blocked_reason + ")").join("; "))}</p>`
      : selectionSuggestions.length
        ? `<p class="warnbox">Substitution suggested: ${esc(selectionSuggestions.map((s) => s.slot_id + " → " + s.suggested + " (" + s.trigger + ")").join("; "))}. Use the selection panel to apply explicitly.</p>`
        : "");
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
    <button type="button" data-action="suggested-deload">Deload this workout</button>
    <span class="muted">Or train as planned; the suggestion will return next workout this week.</span></div>` : "";
  const cards = p.items.map((item) => {
    const st = stress[item.exercise_id];
    const lr = liftReady[item.exercise_id];
    const effort = item.effort_model === "quality"
      ? `quality stop${item.quality_stop ? " · " + esc(item.quality_stop) : ""}`
      : `RIR ${item.rir_target == null ? "—" : item.rir_target}`;
    return `<article class="prescription-card">
      <div class="prescription-card-head"><strong>${esc(item.exercise_id)}</strong>
        ${item.essential ? '<span class="badge">essential</span>' : ""}</div>
      <p class="prescription-dose">${item.sets} × ${item.reps_low}–${item.reps_high} @ ${fmt(item.load_kg)} kg</p>
      <p class="muted">${effort}${item.e1rm_source_sets == null ? "" : " · e1RM n " + item.e1rm_source_sets}</p>
      ${st ? `<p class="muted">stress: ${esc(st.status)} · ${st.decayed_sets} sets · ${st.last_hours}h</p>` : ""}
      ${lr ? `<p class="muted">readiness: ${esc(lr.status)} · ${lr.score}</p>` : ""}
      ${item.unknown_load_reason ? `<p class="muted">${esc(item.unknown_load_reason)}</p>` : ""}
      ${item.warmup && item.warmup.length ? `<p class="muted">warm-up: ${item.warmup.map((w) => `${Math.round(w.percent * 100)}% × ${w.reps} @ ${fmt(w.load_kg)} kg`).join(" · ")}</p>` : ""}
      <p class="muted">${esc(item.refs.slice(-2).join(", "))}</p>
    </article>`;
  }).join("");
  const startAction = `<div class="form-row">
      ${p.executable
        ? '<button class="primary" type="button" data-action="open-workout-start">Start workout</button>'
        : '<button class="primary" type="button" disabled>Start workout</button>'}
      <span class="muted">${p.executable ? "Freezes this plan and opens the start form." : "Fix the warnings above before starting."}</span>
    </div>`;
  $("#prescribe-result").innerHTML = `<div class="panel">
    <div class="panel-head"><h2>${esc(p.for_date)} · ${esc(p.session_label || sessionLabel(p.session_type || "unknown"))}</h2>
      <span class="badge ${p.executable ? "" : "bad"}">${p.executable ? "executable" : "not executable"}</span></div>
    ${timeLine}${volumeBox}${compBox}${warnings}${spinalBox}${minimumBox}${deloadBox}${suggestionBox}${selectionBox}${signalBox}${cadenceBox}
    <div class="table-scroll desktop-table"><table><thead><tr><th>Exercise</th><th>Sets</th><th>Reps</th><th>kg</th><th>RIR</th><th>recent stress</th><th>readiness</th><th>e1RM n</th><th>refs</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <div class="mobile-cards prescription-cards">${cards}</div>
    ${startAction}
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
      <td data-label="Item"><strong>${esc(item.key)}</strong><div class="muted">${esc(item.question)}</div>
        <details class="review-anchors"><summary>Anchors</summary>
          <p class="muted">${esc(item.anchors)}</p></details></td>
      <td data-label="Engine" class="muted">${item.measurable ? fmt(item.score, 2) : "n/a"}</td>
      <td data-label="Your score"><input type="number" min="0" max="1" step="0.05" data-key="${esc(item.key)}"
        aria-label="Your score for ${esc(item.key)}" value="${item.existing ?? ""}" placeholder="skip"></td>
      <td data-label="Why" class="muted"><details class="review-why"><summary>Why</summary>
        <p>${esc(item.detail)}</p></details></td></tr>`).join("");
    const formRows = (data.form_context?.forms || []).map((form) => `
      <tr><td><code>${esc(form.exercise_id)}</code></td><td>${form.rating}/5</td>
      <td>${form.prior_avg ?? "—"} <span class="muted">(n=${form.prior_n})</span></td>
      <td>${form.prior_latest == null ? "—" : form.prior_latest + "/5"}</td></tr>`).join("");
    const formContext = formRows
      ? `<h3>Form context</h3><div class="table-scroll"><table><thead><tr><th>Lift</th><th>this session</th>
         <th>prior average</th><th>prior latest</th></tr></thead><tbody>${formRows}</tbody></table></div>`
      : "";
    $("#review-result").innerHTML = `<div class="panel">
      <div class="panel-head"><h2>${esc(data.session)} · ${esc(sessionLabel(data.session_type))}</h2>
        <span class="badge">composite ${fmt(data.composite, 2)}</span></div>
      <p class="muted">Week ${esc(data.week)} · spinal cost ${fmt(data.week_cost, 2)}</p>
      ${reviewWorkoutSummary(data.workout)}
      ${formContext}
      <div class="table-scroll review-table-wrap"><table class="review-table">
      <thead><tr><th>Item</th><th>engine</th><th>your score</th><th>why</th></tr></thead>
      <tbody>${items}</tbody></table></div>
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
        <label>Productivity
          <select id="review-productivity">
            <option value="">Not recorded</option>
            <option value="1" ${data.feedback && data.feedback.productivity === 1 ? "selected" : ""}>1 — not at all</option>
            <option value="2" ${data.feedback && data.feedback.productivity === 2 ? "selected" : ""}>2 — slightly</option>
            <option value="3" ${data.feedback && data.feedback.productivity === 3 ? "selected" : ""}>3 — moderately</option>
            <option value="4" ${data.feedback && data.feedback.productivity === 4 ? "selected" : ""}>4 — very</option>
            <option value="5" ${data.feedback && data.feedback.productivity === 5 ? "selected" : ""}>5 — extremely</option>
          </select>
        </label>
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
    productivity: $("#review-productivity").value || null,
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
    loadFatigueSuggestion(date, sessionType);
  } catch (error) {
    $("#selection-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadFatigueSuggestion(date, sessionType) {
  const target = $("#selection-fatigue");
  if (!target) return;
  try {
    const data = await api(`/api/substitution?date=${encodeURIComponent(date)}&session_type=${encodeURIComponent(sessionType)}`);
    const suggestion = (data.suggestions || [])[0];
    if (!suggestion) {
      target.innerHTML = `<p class="muted">No fatigue-informed substitution (${esc(data.signal)}): ${esc((data.abstentions || []).join("; ") || "no reason recorded")}.</p>`;
      return;
    }
    target.innerHTML = `<div class="panel-head"><h3>Fatigue-informed suggestion</h3>
        <span class="muted">suggest-only; no prescription change</span></div>
      <p>${esc(suggestion.reason)}</p>
      <p class="muted">${esc(suggestion.current)} → <strong>${esc(suggestion.candidate)}</strong>
        · <code>${esc(suggestion.dimension)}</code>: ${esc(suggestion.current_level)} →
        ${esc(suggestion.candidate_level)} · class ${esc(suggestion.comparison_class)}${suggestion.requires_confirmation ? " (needs confirmation)" : ""}.
        Applying stays the existing explicit action; the load is rebuilt from the candidate's own history.</p>`;
  } catch (error) {
    target.innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

$("#selection-run").addEventListener("click", loadSelection);

$("#validation-run").addEventListener("click", async () => {
  $("#validation-result").innerHTML = "<p class='empty'>Running walk-forward check…</p>";
  try {
    const maxDates = Number($("#validation-max-dates").value || 12);
    if (!Number.isInteger(maxDates) || maxDates < 1 || maxDates > 100) {
      throw new Error("Maximum dates must be an integer from 1 to 100.");
    }
    const data = await api("/api/validation?max_dates=" + encodeURIComponent(maxDates));
    $("#validation-result").innerHTML = `<pre>${esc(data.text)}</pre>`;
  } catch (error) {
    $("#validation-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
});

/* --- strength fatigue model ---------------------------------------------- */
async function loadFatigue() {
  const date = $("#fatigue-date").value || $("#prescribe-date").value;
  try {
    const data = await api("/api/fatigue" + (date ? "?date=" + encodeURIComponent(date) : ""));
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

const READINESS_FIELD_MAP = Object.fromEntries(
  [...SCORE_FIELDS, ...DEVICE_FIELDS].map((field) => [field, `[data-field="${field}"]`])
);
READINESS_FIELD_MAP.date = "#readiness-date";
READINESS_FIELD_MAP.values = "#readiness-fields";

function fieldInput(field, device = false) {
  if (device) return `<label>${esc(LABELS[field])} <input type="number" step="0.1" min="0"
    data-field="${field}" placeholder=""></label>`;
  return `<label>${esc(LABELS[field])} <select data-field="${field}">${readinessScaleOptions(field)}</select></label>`;
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
    const presetHtml = Object.entries(presets).map(([name, preset]) => {
      const values = preset.values || {};
      const compact = [values.sleep, values.energy, values.soreness, values.stress]
        .map((value) => value == null ? "—" : value).join("/");
      const aria = `${preset.label || name}: sleep ${values.sleep}, energy ${values.energy}, ` +
        `soreness ${values.soreness}, stress ${values.stress}`;
      return `<button type="button" class="ghost preset-button"
        data-action="readiness-preset" data-preset="${esc(name)}" aria-label="${esc(aria)}"
        title="${esc(aria)}">${esc(preset.label || name)}
        <span class="preset-values">${esc(compact)}</span></button>`;
    }).join("") +
      '<span class="muted preset-legend">Values: sleep / energy / soreness / stress</span>' +
      '<button type="button" class="ghost" data-action="edit-readiness-presets">Edit preset YAML</button>';
    $("#readiness-presets").innerHTML = presetHtml;
    const workflowPresets = $("#workflow-readiness-presets");
    if (workflowPresets) workflowPresets.innerHTML = presetHtml;
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

async function openReadinessPresetEditor() {
  const dialog = $("#readiness-preset-dialog");
  if (!dialog) return;
  $("#readiness-preset-msg").textContent = "Loading…";
  try {
    const data = await api("/api/readiness/presets");
    $("#readiness-preset-yaml").value = data.yaml || "";
    $("#readiness-preset-path").textContent = data.path || "";
    $("#readiness-preset-msg").textContent = "";
    dialog.showModal();
    $("#readiness-preset-yaml").focus();
  } catch (error) {
    notify(error.message, "error");
    $("#readiness-preset-msg").textContent = error.message;
  }
}

async function saveReadinessPresetEditor(event) {
  event.preventDefault();
  const text = $("#readiness-preset-yaml").value;
  if (!text.trim()) {
    $("#readiness-preset-msg").textContent = "Preset YAML is empty.";
    return;
  }
  $("#readiness-preset-msg").textContent = "Saving…";
  try {
    await api("/api/readiness/presets", {
      method: "POST", body: JSON.stringify({ yaml: text }),
    });
    $("#readiness-preset-dialog").close();
    notify("Readiness presets saved.");
    await loadReadiness($("#readiness-date").value);
  } catch (error) {
    $("#readiness-preset-msg").textContent = error.message;
  }
}

$("#readiness-preset-form")?.addEventListener("submit", saveReadinessPresetEditor);
$("#readiness-preset-cancel")?.addEventListener("click", () => $("#readiness-preset-dialog").close());

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
$("#readiness-context-save")?.addEventListener("click", saveReadinessContext);

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
    applyFieldErrors(error, $("#readiness-result"), READINESS_FIELD_MAP);
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

function renderE1rmPreview(data, kind) {
  const box = $("#state-e1rm-preview");
  if (!box) return;
  if (kind === "coverage") {
    const rows = (data.tests_needed || []).map(function (row) {
      return "<tr><td>" + esc(row.display) + "</td><td>" + row.counted + " / " +
        row.min_tests + "</td><td>" + row.needed + "</td><td>" + esc(row.status) +
        "</td><td>" + esc(row.next_action) + "</td></tr>";
    }).join("");
    box.innerHTML = "<p class='muted'>Coverage preview window " + data.window_days +
      " days. Active coverage remains at its current defaults.</p>" +
      (rows ? "<div class='table-scroll'><table><thead><tr><th>Lift</th><th>tests</th><th>need</th><th>status</th><th>next</th></tr></thead><tbody>" +
        rows + "</tbody></table></div>" : "<p class='empty'>No lifts to report.</p>") +
      "<p class='muted'>" + esc(data.note || "") + "</p>";
    return;
  }
  const rows = (data.calibration || []).map(function (row) {
    const ci = row.ci_low == null ? "—" : row.ci_low + "–" + row.ci_high;
    return "<tr><td>" + esc(row.exercise_id) + "</td><td>" + row.n + "</td><td>" +
      (row.median_ratio == null ? "—" : row.median_ratio) + "</td><td>" + ci +
      "</td><td>" + row.correction_factor + "</td><td>" +
      esc(row.correction_reason || row.status || "") + "</td></tr>";
  }).join("");
  box.innerHTML = "<p class='muted'>Calibration preview window " + data.window_days +
    " days; active window " + data.active_window_days +
    ". Preview only — active calibration unchanged.</p>" +
    (rows ? "<div class='table-scroll'><table><thead><tr><th>Lift</th><th>tests</th><th>median ratio</th><th>95% CI</th><th>factor</th><th>reason</th></tr></thead><tbody>" +
      rows + "</tbody></table></div>" : "<p class='empty'>No measured tests in this window.</p>") +
    "<p class='muted'>" + esc(data.note || "") + "</p>";
}

async function loadE1rmPreview(kind) {
  const input = $("#state-e1rm-" + kind + "-window");
  const windowDays = Number(input.value || 84);
  if (!Number.isInteger(windowDays) || windowDays < 7 || windowDays > 365) {
    $("#state-e1rm-preview").innerHTML = "<p class='warnbox'>Window must be an integer from 7 to 365.</p>";
    return;
  }
  try {
    const endpoint = kind === "coverage" ? "tests-needed" : "calibration";
    const data = await api("/api/e1rm/" + endpoint + "?window_days=" + encodeURIComponent(windowDays));
    renderE1rmPreview(data, kind);
  } catch (error) {
    $("#state-e1rm-preview").innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  }
}

async function loadSymptomHistory(allRows) {
  const box = $("#state-symptom-history");
  if (!box) return;
  box.innerHTML = "<p class='empty'>Loading symptom history…</p>";
  try {
    const data = await api("/api/symptoms/history?limit=10" + (allRows ? "&all=1" : ""));
    const rows = (data.entries || []).map(function (row) {
      return "<tr><td>" + esc(row.logged_on) + "</td><td>" + esc(row.region) +
        "</td><td>" + row.level + "</td><td>" +
        (row.settled_within_48h == null ? "unknown" : (row.settled_within_48h ? "yes" : "no")) +
        "</td><td>" + esc(row.note || "") + "</td></tr>";
    }).join("");
    box.innerHTML = "<p class='muted'>Showing " + data.shown + " of " + data.total +
      " entries, newest first.</p>" +
      (rows ? "<div class='table-scroll'><table><thead><tr><th>Date</th><th>Region</th><th>Level</th><th>Settled 48h</th><th>Note</th></tr></thead><tbody>" +
        rows + "</tbody></table></div>" : "<p class='empty'>No symptom entries recorded.</p>");
    if (data.has_more && !allRows) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ghost";
      button.textContent = "Show all " + data.total + " entries";
      button.addEventListener("click", function () { loadSymptomHistory(true); });
      box.appendChild(button);
    }
  } catch (error) {
    box.innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  }
}

async function loadTestCadence() {
  const box = $("#state-test-cadence");
  if (!box) return;
  try {
    const data = await api("/api/test-cadence");
    box.innerHTML = "<p><strong>" + (data.enabled === false ? "disabled" : (data.due ? "due" : "not due")) +
      "</strong> · last test " + esc(data.last_test || "none") + " · next " +
      esc(data.next_scheme || "—") + " by " + esc(data.next_due || "—") + ".</p>" +
      "<p class='muted'>" + esc(data.reason || "") + ". Read-only; no test or prescription is created.</p>";
  } catch (error) {
    box.innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
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

function choiceOptions(choices, selected) {
  const items = choices || [];
  const values = new Set(items.map((item) => String(item.value)));
  let markup = items.map((item) => {
    const value = esc(item.value);
    const label = esc(item.label || item.value);
    return `<option value="${value}"${String(selected ?? "") === String(item.value) ? " selected" : ""}>${label}</option>`;
  }).join("");
  // Never silently drop an existing value that is no longer in the current list.
  if (selected != null && selected !== "" && !values.has(String(selected))) {
    markup += `<option value="${esc(selected)}" selected>${esc(selected)} (legacy — not in current list)</option>`;
  }
  return markup;
}

function exerciseSelectOptions(selected, choices) {
  return '<option value="">choose…</option>' + (choices || []).map((item) =>
    `<option value="${esc(item.value)}"${String(selected ?? "") === String(item.value) ? " selected" : ""}>${esc(item.label || item.value)}</option>`
  ).join("");
}

function exercisePickerHtml(attrs, choices, selected) {
  return `<div class="search-select">
    <input type="search" class="search-select-filter" placeholder="Filter exercises…"
      aria-label="Filter exercise list" autocomplete="off">
    <select ${attrs} aria-label="Exercise">${exerciseSelectOptions(selected, choices)}</select>
  </div>`;
}

function choiceChecklist(name, choices, selected) {
  const chosen = new Set((selected || []).map(String));
  return `<div class="choice-list" data-choice-group="${esc(name)}">` +
    (choices || []).map((item) => `<label class="choice">
      <input type="checkbox" data-choice-choice value="${esc(item.value)}"${chosen.has(String(item.value)) ? " checked" : ""}>
      <span>${esc(item.label || item.value)}</span></label>`).join("") +
    "</div>";
}

function checkedChoices(name) {
  return [...document.querySelectorAll(`[data-choice-group="${name}"] input[type="checkbox"]:checked`)]
    .map((input) => input.value);
}

function wireChoiceSearch(inputId, groupName) {
  const input = document.getElementById(inputId);
  const group = document.querySelector(`[data-choice-group="${groupName}"]`);
  if (!input || !group) return;
  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    group.querySelectorAll("label.choice").forEach((label) => {
      label.hidden = Boolean(query) && !label.textContent.toLowerCase().includes(query);
    });
  });
}

function renderStateForms(data) {
  const p = data.profile || {};
  const opts = data.options || {};
  const regionChoices = (opts.regions || []).length
    ? opts.regions
    : Object.keys(data.injury_signal?.regions || {}).map((key) => ({ value: key, label: key }));
  const regionOptions = choiceOptions(regionChoices, "");
  const exerciseChoices = (opts.exercises || []).slice();
  // A declared break freezes its weeks; the list is the record, the form appends to it.
  const todayDate = today();
  const breaks = data.declared_breaks || [];
  const breakRows = breaks.length
    ? "<div class='table-scroll'><table><thead><tr><th>From</th><th>To</th><th>Reason</th>" +
      "<th>Days</th><th>Status</th><th></th></tr></thead><tbody>" +
      breaks.map((row) => {
        const status = row.cancelled ? "cancelled"
          : (row.starts_on <= todayDate && todayDate <= row.ends_on) ? "active"
          : row.ends_on < todayDate ? "past" : "future";
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
        ${profileField("competition_date", "Competition date", p.competition_date, "date")}
        ${profileField("sessions_per_week_target", "Sessions/week", p.sessions_per_week_target, "number")}
        ${profileField("max_session_minutes", "Session minutes", p.max_session_minutes, "number")}
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
        <label>Exposure trim
          <select data-profile="exposure_trim_enabled">
            <option value="off" ${p.exposure_trim_enabled ? "" : "selected"}>off</option>
            <option value="on" ${p.exposure_trim_enabled ? "selected" : ""}>on</option>
          </select>
        </label>
        <button class="primary" type="submit">Save profile version</button>
      </form>
      <p class="muted">Budget <strong>on</strong> with <strong>preserve</strong> trims and tops up
        accessories only. <strong>reduce</strong> also trims filled-group main lifts;
        <strong>drop</strong> also removes/relabels the main lift. The main-lift policy is ignored
        while the volume budget is off. <a class="doc-link"
        href="#docs?doc=docs/VOLUME-MODULATION-PLAN.md&amp;anchor=44-what-steps-2-and-2b-actually-do-implemented">Volume budget rules</a></p>
    </div>

    <div class="panel"><div class="panel-head"><h2>Add constraint</h2></div>
      <form id="constraint-form" class="grid-fields">
        <label>Kind<select data-constraint="kind">${choiceOptions(opts.constraint_kinds, "")}</select></label>
        <label>Region<select data-constraint="region">${regionOptions}</select></label>
        <label>Severity<select data-constraint="severity">${choiceOptions(opts.severities, "monitor")}</select></label>
        <label>Since<input data-constraint="since" type="month"></label>
        <label>Settled on<input data-constraint="settled_on" type="month"></label>
        <label class="grow">Evidence<input data-constraint="evidence"></label>
        <details class="advanced choice-details">
          <summary>Forbidden patterns</summary>
          ${choiceChecklist("forbidden_patterns", opts.patterns || [])}
        </details>
        <details class="advanced choice-details">
          <summary>Forbidden exercises</summary>
          <label class="grow">Search exercises
            <input id="constraint-exercise-search" type="search" placeholder="type a name or id">
          </label>
          ${choiceChecklist("forbidden_exercises", exerciseChoices)}
        </details>
        <button class="primary" type="submit">Append constraint</button>
      </form>
    </div>

    <div class="panel"><div class="panel-head"><h2>Rate suitability</h2></div>
      <form id="suitability-form" class="grid-fields">
        <label>Exercise${exercisePickerHtml('data-suit="exercise_id"', exerciseChoices)}</label>
        <label>Can do<select data-suit="can_do"><option>yes</option><option>no</option></select></label>
        <label>Will do<select data-suit="will_do"><option>yes</option><option>no</option></select></label>
        <label>Feels bad<select data-suit="feels_bad"><option>no</option><option>yes</option></select></label>
        <label class="grow">Note<input data-suit="note"></label>
        <button class="primary" type="submit">Append rating</button>
      </form>
    </div>

    <div class="panel"><div class="panel-head"><h2>e1RM override</h2></div>
      <form id="e1rm-form" class="grid-fields">
        <label>Exercise${exercisePickerHtml('data-e1rm="exercise_id"', exerciseChoices)}</label>
        <label>kg<input data-e1rm="e1rm_kg" type="number" step="0.5"></label>
        <label>Effective from<input data-e1rm="effective_from" type="date"></label>
        <label>Expires<input data-e1rm="expires_on" type="date"></label>
        <label class="grow">Reason<input data-e1rm="reason"></label>
        <button class="primary" type="submit">Append override</button>
      </form>
    </div>

    <div class="panel"><div class="panel-head"><h2>Strength test</h2><span class="muted">records a measured e1RM; exposure is automatic</span></div>
      <form id="test-form" class="grid-fields">
        <label>Exercise${exercisePickerHtml('data-test="exercise_id"', exerciseChoices)}</label>
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
        <label>Exercise${exercisePickerHtml('data-exposure="exercise_id"', exerciseChoices)}</label>
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

  wireChoiceSearch("constraint-exercise-search", "forbidden_exercises");

  const collect = (prefix) => Object.fromEntries(
    [...document.querySelectorAll(`[data-${prefix}]`)].map((el) => [el.dataset[prefix], el.value])
  );
  const PROFILE_ERRORS = {
    competition_date: '[data-profile="competition_date"]',
    sessions_per_week_target: '[data-profile="sessions_per_week_target"]',
    max_session_minutes: '[data-profile="max_session_minutes"]',
    block_start_date: '[data-profile="block_start_date"]',
    main_lift_policy: '[data-profile="main_lift_policy"]',
  };
  const CONSTRAINT_ERRORS = {
    kind: '[data-constraint="kind"]',
    region: '[data-constraint="region"]',
    severity: '[data-constraint="severity"]',
    forbidden_patterns: '[data-choice-group="forbidden_patterns"] input',
    forbidden_exercises: '[data-choice-group="forbidden_exercises"] input',
    since: '[data-constraint="since"]',
    settled_on: '[data-constraint="settled_on"]',
    evidence: '[data-constraint="evidence"]',
  };
  const save = async (path, payload, target = "#state-result", message = "Saved.", mapping = {}) => {
    try {
      await api(path, { method: "POST", body: JSON.stringify(payload) });
      notify(message);
      loadState();
      loadOverview();
    } catch (error) {
      applyFieldErrors(error, $(target), mapping);
    }
  };
  $("#profile-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = collect("profile");
    const exposureTrim = values.exposure_trim_enabled === "on";
    save("/api/state/profile", {
      ...values,
      exposure_trim_enabled: exposureTrim,
      sessions_per_week_target: values.sessions_per_week_target || null,
      max_session_minutes: values.max_session_minutes || null,
    }, "#state-result", "Profile saved — new version appended.", PROFILE_ERRORS);
  });
  $("#constraint-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = collect("constraint");
    values.forbidden_patterns = checkedChoices("forbidden_patterns");
    values.forbidden_exercises = checkedChoices("forbidden_exercises");
    save("/api/state/constraint", values, "#state-result", "Constraint appended.", CONSTRAINT_ERRORS);
  });
  $("#suitability-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = collect("suit");
    save("/api/state/suitability", {
      ...values,
      can_do: values.can_do === "yes",
      will_do: values.will_do === "yes",
      feels_bad: values.feels_bad === "yes",
    }, "#state-result", "Suitability appended.", { exercise_id: '[data-suit="exercise_id"]' });
  });
  $("#e1rm-form").addEventListener("submit", (event) => {
    event.preventDefault();
    save("/api/state/e1rm", collect("e1rm"), "#state-result", "e1RM override appended.", {
      exercise_id: '[data-e1rm="exercise_id"]',
      e1rm_kg: '[data-e1rm="e1rm_kg"]',
      effective_from: '[data-e1rm="effective_from"]',
    });
  });
  $("#test-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = collect("test");
    const max = document.querySelector('[data-test="max"]');
    save("/api/state/test", { ...values, max: Boolean(max && max.checked) },
      "#state-result", "Strength test recorded.", {
        exercise_id: '[data-test="exercise_id"]',
        kg: '[data-test="kg"]',
        reps: '[data-test="reps"]',
        date: '[data-test="date"]',
      });
  });
  $("#exposure-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = collect("exposure");
    try {
      await api("/api/exposures", { method: "POST", body: JSON.stringify(values) });
      await loadExposureStatus();
    } catch (error) {
      applyFieldErrors(error, $("#exposure-status"), {
        exercise_id: '[data-exposure="exercise_id"]',
      });
    }
  });
  $("#symptom-form").addEventListener("submit", (event) => {
    event.preventDefault();
    save("/api/state/symptom", collect("symptom"), "#state-result", "Symptom appended.", {
      date: '[data-symptom="date"]',
      region: '[data-symptom="region"]',
      level: '[data-symptom="level"]',
      settled: '[data-symptom="settled"]',
    });
  });
  $("#block-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = collect("block");
    const force = document.querySelector('[data-block="force"]');
    save("/api/state/block", { ...values, force: Boolean(force && force.checked) },
      "#state-result", "Block start recorded.", {
        date: '[data-block="date"]',
        force: '[data-block="force"]',
      });
  });
  $("#break-form").addEventListener("submit", (event) => {
    event.preventDefault();
    save("/api/state/break", collect("break"), "#break-msg", "Declared break recorded.", {
      starts_on: '[data-break="starts_on"]',
      ends_on: '[data-break="ends_on"]',
      reason: '[data-break="reason"]',
    });
  });
  document.querySelectorAll("[data-cancel-break]").forEach((button) => {
    button.addEventListener("click", () => {
      save("/api/state/break/cancel",
        { break_id: Number(button.dataset.cancelBreak) }, "#break-msg");
    });
  });
}

/* --- docs --------------------------------------------------------------- */
async function loadLogs() {
  try {
    const data = await api("/api/logs?limit=200");
    const rows = (data.logs || []).map((row) =>
      "<tr><td>" + esc(row.time) + "</td><td>" + esc(row.level) + "</td><td>" +
      esc(row.logger) + "</td><td>" + esc(row.message) + "</td></tr>").join("");
    $("#logs-output").innerHTML = rows
      ? "<table><thead><tr><th>time</th><th>level</th><th>logger</th><th>message</th></tr></thead><tbody>" + rows + "</tbody></table>"
      : "<p class='empty'>No log entries yet.</p>";
  } catch (error) {
    $("#logs-output").innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  }
}

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
    // Shared by the history editor's canonical exercise selects.
    window.__exerciseList = list;
    return list;
  } catch (error) {
    return [];
  }
}





/* --- weekly volume ledger ------------------------------------------------ */
async function loadVolume() {
  const dateInput = $("#volume-date");
  const date = dateInput.value || $("#prescribe-date").value;
  if (!date) { $("#volume-ledger").innerHTML = "<p class='empty'>Choose a date.</p>"; return; }
  const weeks = Number($("#volume-weeks").value || 4);
  if (!Number.isInteger(weeks) || weeks < 1 || weeks > 52) {
    $("#volume-ledger").innerHTML = "<p class='warnbox'>Weeks must be an integer from 1 to 52.</p>";
    return;
  }
  try {
    const data = await api("/api/volume?date=" + encodeURIComponent(date) + "&weeks=" + weeks);
    if (!data.patterns.length) {
      $("#volume-ledger").innerHTML = "<p class='empty'>No working sets in the window.</p>";
      return;
    }
    const rows = data.patterns.map((row) => `<tr>
      <td><code>${esc(row.pattern)}</code></td>
      <td>${row.raw_average ?? row.average}</td>
      <td>${row.effective_average ?? row.group_average}</td>
      <td>${row.mev ?? "—"}</td>
      <td>${row.mav ? row.mav[0] + "–" + row.mav[1] : "—"}</td>
      <td>${row.mrv ?? "—"}</td>
      <td>${esc(row.status)}</td></tr>`).join("");
    const accounting = data.coverage?.accounting || "hard";
    const heavy = data.heavy_spinal;
    const heavyLine = heavy
      ? `<p class="muted">Heavy spinal sets (RIR ≤ ${heavy.rir_max}): <strong>${heavy.total_sets}</strong>
         in the last ${heavy.window_weeks} weeks. Context only; not load-weighted and not part of the cap.</p>`
      : "";
    $("#volume-ledger").innerHTML = `<p class="muted">${esc(data.from)} to ${esc(data.to)} · accounting <strong>${esc(accounting)}</strong></p>${heavyLine}
      <table><thead><tr><th>pattern</th><th>raw/wk</th><th>effective/wk</th>
      <th>MEV</th><th>MAV</th><th>MRV</th><th>status</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="muted">Effective/wk adds configured indirect work at 0.25; raw/wk is unchanged. MEV/MAV/MRV are configurable coaching landmarks, not measured individual thresholds. <a class="doc-link" href="#docs?doc=docs/VOLUME-MODULATION-PLAN.md&amp;anchor=16-effective-set-audit-and-the-target-decision-step-8-pre-activation">Accounting rules</a></p>`;
  } catch (error) {
    $("#volume-ledger").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadExposure() {
  const date = $("#prescribe-date").value;
  if (!date) { $("#exposure-report").innerHTML = "<p class='empty'>Choose a date.</p>"; return; }
  try {
    const data = await api(`/api/exposure?date=${encodeURIComponent(date)}`);
    $("#exposure-signal").textContent = data.signal +
      (data.ratio == null ? "" : ` (ratio ${data.ratio.toFixed(2)})`);
    const facts = [
      ["acute 7d", `${data.acute_hard_sets} hard sets`],
      ["chronic 28d", `${data.chronic_hard_sets} (${data.baseline.toFixed(2)}/week)`],
      ["coverage", `${Math.round(data.coverage * 100)}% over ${data.sessions} sessions`],
      ["largest gap", `${data.flags.gap_days} days`],
    ].map(([key, value]) => `<tr><th>${esc(key)}</th><td>${esc(value)}</td></tr>`).join("");
    const abstain = data.abstain.length
      ? `<p class="warnbox">Abstained: ${esc(data.abstain.join(", "))}</p>`
      : "";
    const advisories = data.advisories
      .map((text) => `<p class="warnbox">${esc(text)}</p>`).join("");
    const groups = data.groups.length
      ? `<table><thead><tr><th>group</th><th>ratio</th><th>signal</th></tr></thead><tbody>${
          data.groups.map((group) => `<tr><td><code>${esc(group.group)}</code></td>
            <td>${group.ratio == null ? "—" : group.ratio}</td>
            <td>${esc(group.signal)}</td></tr>`).join("")}</tbody></table>`
      : "";
    $("#exposure-report").innerHTML = `<p class="muted">${esc(data.windows.acute.start)} to ${esc(data.windows.acute.end)} acute;
      ${esc(data.windows.chronic.start)} to ${esc(data.windows.chronic.end)} chronic.</p>
      <table><tbody>${facts}</tbody></table>${abstain}${advisories}${groups}
      <p class="muted">Hard set = working set at RIR ≤ ${data.flags.effort_max_rir}, or a max/test
      exposure. Thresholds are config assumptions, not measured cut-points.</p>`;
  } catch (error) {
    $("#exposure-report").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadResidual() {
  const date = $("#prescribe-date").value;
  if (!date) { $("#residual-report").innerHTML = "<p class='empty'>Choose a date.</p>"; return; }
  try {
    const data = await api(`/api/residual?date=${encodeURIComponent(date)}`);
    $("#residual-signal").textContent =
      (data.signal_available ? "signal available" : "no signal")
      + (data.evaluation_ready ? " · evaluation-ready" : "");
    const rows = (data.lifts || []).map((lift) => `<tr>
      <td><code>${esc(lift.exercise_id)}</code></td><td>${lift.reps}</td>
      <td>${lift.n}</td><td>${lift.weeks}</td>
      <td>${lift.mean_residual}</td><td>${lift.spread ?? "—"}</td>
      <td>${esc(lift.calibration_scope)}</td><td>${esc(lift.gate)}</td></tr>`).join("");
    const table = rows
      ? `<table><thead><tr><th>lift</th><th>reps</th><th>n</th><th>weeks</th>
         <th>mean residual (m/s)</th><th>spread</th><th>scope</th><th>gate</th></tr></thead>
         <tbody>${rows}</tbody></table>`
      : "";
    const abstain = (data.abstain || [])
      .map((reason) => `<p class="muted">${esc(reason)}</p>`).join("");
    const advisories = (data.advisories || [])
      .map((text) => `<p class="warnbox">${esc(text)}</p>`).join("");
    $("#residual-report").innerHTML = table + abstain + advisories
      + `<p class="muted">Gates: ${data.gates.min_observations} sets for a signal,
         ${data.gates.evaluation_observations} over ${data.gates.evaluation_weeks} weeks for
         evaluation. Negative means slower than the target.</p>`;
  } catch (error) {
    $("#residual-report").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadShadowReview() {
  const date = $("#prescribe-date").value;
  if (!date) { $("#shadow-report").innerHTML = "<p class='empty'>Choose a date.</p>"; return; }
  try {
    const data = await api(`/api/shadow?date=${encodeURIComponent(date)}`);
    $("#shadow-gate").textContent = data.ready ? "ready to review" : "not ready";
    const checks = (data.checks || []).map((check) => `<tr>
      <td>${esc(check.name)}</td>
      <td>${check.passed ? "pass" : "fail"}</td>
      <td class="muted">${esc(check.detail)}</td></tr>`).join("");
    const actions = Object.entries(data.by_action || {})
      .map(([action, count]) => `<tr><td>${esc(action)}</td><td>${count}</td></tr>`).join("");
    const abstain = (data.abstentions || [])
      .map((reason) => `<p class="muted">${esc(reason)}</p>`).join("");
    $("#shadow-report").innerHTML =
      `<p class="muted">${data.rows} rows over ${data.shadow_days} days · ${data.applied}
        applied · ${data.suggestions} suggestions · ${data.high_signal_days} high-signal
        days.</p>
      <table><thead><tr><th>gate check</th><th>result</th><th>detail</th></tr></thead>
      <tbody>${checks}</tbody></table>
      <table><thead><tr><th>action</th><th>rows</th></tr></thead><tbody>${actions}</tbody></table>
      ${abstain}
      <p class="muted">Activation allowed: <strong>no</strong>. The gate says whether this
        report is substantive enough for a decision; the switch stays off until that decision is
        recorded.</p>`;
  } catch (error) {
    $("#shadow-report").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
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
  const date = $("#continuity-date").value || $("#prescribe-date").value;
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


/* --- programme ---------------------------------------------------------- */
function programmeStatus(entry) {
  if (entry.deload_applied || entry.deload_reason) return "deload";
  if (entry.deload_suggestion) return "suggested deload";
  if (!entry.prescription.executable) return "not executable";
  return entry.prescription.fallback_level || "forecast";
}

function renderProgramme(entries, fromCache = false) {
  if (!entries.length) {
    $("#programme-result").innerHTML = "<p class='warnbox'>No sessions in that horizon.</p>";
    return;
  }
  const llmFallback = entries.some(
    (entry) => entry.prescription.notes?.selection?.llm_unavailable
  );
  const llmWarning = llmFallback
    ? `<p class="warnbox"><strong>LLM requested but not configured.</strong>
       NullLLM fallback was used for exercise selection. Configure an LLM in Settings or untick
       <em>Use LLM</em>.</p>`
    : "";
  const cacheNote = fromCache
    ? `<p class="muted">Loaded from this session's cache for these form options. Switching an
       option back can restore its earlier build without rebuilding.</p>`
    : "";
  const rows = entries.map((entry) => {
    const stress = entry.prescription.notes?.recent_stress || {};
    const items = entry.prescription.items.map((item) => {
      const st = stress[item.exercise_id];
      const lr = (entry.prescription.notes?.per_lift_readiness || {})[item.exercise_id];
      const tag = st && st.status === "high" ? " · high stress" :
        (st && st.status === "normal" ? " · normal stress" : "");
      const rtag = lr && lr.status !== "ready" ? ` · readiness ${lr.score}` : "";
      const effort = item.effort_model === "quality"
        ? "quality stop" : `RIR ${esc(item.rir_target)}`;
      return `<li>${esc(item.exercise_id)} — ${item.sets}×${item.reps_low}-${item.reps_high}
       @ ${fmt(item.load_kg)} kg, ${effort}${tag}${rtag}</li>`;
    }).join("");
    const vp = entry.prescription.notes?.volume_panel;
    const budgetOn = entry.prescription.notes?.volume_budget?.enabled;
    const volumeTag = budgetOn && vp
      ? `<div class="muted">week ${fmt(vp.after, 1)}/${fmt(vp.target, 1)} sets · ${fmt(vp.remaining, 1)} remaining</div>`
      : "";
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
        ${volumeTag}
        ${warn}</td>
    </tr>`;
  }).join("");
  $("#programme-result").innerHTML = `<div class="panel">${llmWarning}${cacheNote}<table>
    <thead><tr><th>Date</th><th>Session type</th><th>Status</th><th>Session</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

let programmeBusy = false;
let programmeQueued = false;
let programmeHasResult = false;
const PROGRAMME_JOB_STORAGE = "strength-coach.programme.job";
const PROGRAMME_CACHE_PREFIX = "strength-coach.programme.cache:";

function clearProgrammeCache() {
  let removed = 0;
  for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
    const key = sessionStorage.key(index);
    if (key && key.startsWith(PROGRAMME_CACHE_PREFIX)) {
      sessionStorage.removeItem(key);
      removed += 1;
    }
  }
  sessionStorage.removeItem(PROGRAMME_JOB_STORAGE);
  programmeHasResult = false;
  $("#programme-result").innerHTML =
    "<p class='muted'>Cached forecasts cleared. Build the forecast to create a new one.</p>";
  $("#settings-clear-programme-cache-msg").textContent =
    `Cleared ${removed} cached forecast${removed === 1 ? "" : "s"}.`;
}
$("#settings-clear-programme-cache")?.addEventListener("click", clearProgrammeCache);

function programmePayload() {
  const applySelection = $("#programme-apply-selection").checked;
  return {
    weeks: Number($("#programme-weeks").value || 4),
    remaining: $("#programme-remaining").checked,
    start: $("#programme-start").value || null,
    sessions_per_week: Number($("#programme-per-week").value || 3),
    start_session_type: $("#programme-session-type").value || "auto",
    apply_selection: applySelection,
    selection_llm: applySelection && $("#programme-selection-llm").checked,
    selection_confirmed: applySelection && $("#programme-selection-confirm").checked,
  };
}

async function programmeKey(payload) {
  const data = await api("/api/programme/key", {
    method: "POST", body: JSON.stringify(payload),
  });
  return data.cache_key;
}

function readProgrammeCache(key) {
  try {
    const raw = sessionStorage.getItem(PROGRAMME_CACHE_PREFIX + key);
    return raw ? JSON.parse(raw) : null;
  } catch (error) {
    return null;
  }
}

function writeProgrammeCache(key, data) {
  try {
    sessionStorage.setItem(PROGRAMME_CACHE_PREFIX + key, JSON.stringify(data));
  } catch (error) {
    // A full sessionStorage must not break the forecast.
  }
}

async function pollProgrammeJob(jobId, key) {
  for (;;) {
    const job = await api("/api/programme/jobs/" + encodeURIComponent(jobId));
    if (job.status === "done") {
      writeProgrammeCache(key, job.result);
      sessionStorage.removeItem(PROGRAMME_JOB_STORAGE);
      return job.result;
    }
    if (job.status === "error") {
      sessionStorage.removeItem(PROGRAMME_JOB_STORAGE);
      throw new Error(job.error || "programme build failed");
    }
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

async function restoreProgramme() {
  if (programmeBusy || programmeHasResult) return;
  const payload = programmePayload();
  if (!payload.start && !payload.remaining) return;
  try {
    const key = await programmeKey(payload);
    const cached = readProgrammeCache(key);
    if (cached) {
      renderProgramme(cached.entries || [], true);
      programmeHasResult = true;
      return;
    }
    const jobId = sessionStorage.getItem(PROGRAMME_JOB_STORAGE);
    if (!jobId) return;
    programmeBusy = true;
    const data = await pollProgrammeJob(jobId, key);
    renderProgramme(data.entries || []);
    programmeHasResult = true;
  } catch (error) {
    sessionStorage.removeItem(PROGRAMME_JOB_STORAGE);
    $("#programme-result").innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
  } finally {
    programmeBusy = false;
  }
}

function programmeSelectionChanged() {
  syncProgrammeSelection();
  if (programmeBusy) {
    programmeQueued = true;
  } else if (programmeHasResult) {
    $("#programme-result").innerHTML =
      "<p class='muted'>Selection options changed. The previous result is hidden; cached builds are kept per option set, so unticking an option can restore its earlier build.</p>";
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

function programmeFormChanged() {
  if (programmeBusy) return;
  $("#programme-result").innerHTML =
    "<p class='muted'>Inputs changed; build the forecast to refresh it.</p>";
  programmeHasResult = false;
}

async function runProgramme() {
  if (programmeBusy) {
    programmeQueued = true;
    return;
  }
  programmeBusy = true;
  programmeQueued = false;
  const payload = programmePayload();
  const button = $("#programme-form button[type='submit']");
  $("#programme-result").innerHTML = "<p class='empty'>Building forecast… this can take a few seconds.</p>";
  button.disabled = true;
  try {
    const key = await programmeKey(payload);
    const cached = readProgrammeCache(key);
    if (cached) {
      renderProgramme(cached.entries || [], true);
      programmeHasResult = true;
      return;
    }
    const job = await api("/api/programme/jobs", {
      method: "POST", body: JSON.stringify(payload),
    });
    sessionStorage.setItem(PROGRAMME_JOB_STORAGE, job.job_id);
    const data = await pollProgrammeJob(job.job_id, key);
    if (!programmeQueued) {
      renderProgramme(data.entries || []);
      programmeHasResult = true;
    }
  } catch (error) {
    sessionStorage.removeItem(PROGRAMME_JOB_STORAGE);
    if (!programmeQueued) {
      $("#programme-result").innerHTML = "<p class='warnbox'>" + esc(error.message) + "</p>";
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
    applyFieldErrors(error, $("#cardio-result"), {
      date: "#cardio-date",
      modality: "#cardio-modality",
      minutes: "#cardio-minutes",
      avg_hr: "#cardio-avg-hr",
      max_hr: "#cardio-max-hr",
      distance_km: "#cardio-distance",
      srpe: "#cardio-srpe",
    });
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
    applyFieldErrors(error, $("#measure-result"), {
      metric: "#measure-metric",
      date: "#measure-date",
      value: "#measure-value",
      method: "#measure-method",
    });
  } finally {
    button.disabled = false;
  }
});

$("#programme-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runProgramme();
});
$("#programme-form").addEventListener("input", programmeFormChanged);
$("#logs-refresh").addEventListener("click", loadLogs);

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
    applyFieldErrors(error, $("#settings-profile-msg"), {
      guard_confirmed: "#settings-profile-guard",
      reason: "#settings-profile-reason",
      factors: "#settings-profile-fields",
      settings: "#settings-profile-fields",
    });
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
}

function volumePolicyValue(node) {
  if (node.type === "checkbox") return node.checked;
  if (node.dataset.kind === "int") return Number(node.value);
  if (node.dataset.kind === "float") return Number(node.value);
  return node.value;
}

function volumeDiff(current, next) {
  if (JSON.stringify(current) === JSON.stringify(next)) return undefined;
  if (!current || typeof current !== "object" || Array.isArray(current)
      || !next || typeof next !== "object" || Array.isArray(next)) {
    return next;
  }
  const patch = {};
  let changed = false;
  Object.keys(next).forEach((key) => {
    const child = volumeDiff(current[key], next[key]);
    if (child !== undefined) {
      patch[key] = child;
      changed = true;
    }
  });
  return changed ? patch : undefined;
}

function volumeNestedValue(value, key) {
  return key.split(".").reduce(
    (current, part) => (current == null ? undefined : current[part]), value
  );
}

function volumeJson(text, label) {
  try {
    return JSON.parse(text || "{}");
  } catch (error) {
    throw new Error(label + ": invalid JSON — " + error.message);
  }
}

function volumeNumber(selector) {
  const node = document.querySelector(selector);
  return node ? Number(node.value) : 0;
}

function updateVolumeTotals() {
  const total = [...document.querySelectorAll("[data-volume-target]")]
    .reduce((sum, node) => sum + Number(node.value || 0), 0);
  const effective = [...document.querySelectorAll("[data-volume-effective]")]
    .reduce((sum, node) => sum + Number(node.value || 0), 0);
  const tolerance = volumeNumber('[data-volume-budget="tolerance"]');
  const totalBox = $("#settings-volume-total");
  const effectiveBox = $("#settings-volume-effective-total");
  const highBox = $("#settings-volume-high");
  const capSumBox = $("#settings-volume-cap-sum");
  const capSum = [...document.querySelectorAll("[data-volume-cap]")]
    .reduce((sum, node) => sum + Number(node.value || 0), 0);
  if (totalBox) totalBox.textContent = fmt(total, 1);
  if (effectiveBox) effectiveBox.textContent = fmt(effective, 1);
  if (highBox) highBox.textContent = fmt(total * (1 + tolerance), 1);
  if (capSumBox) capSumBox.textContent = fmt(capSum, 0);
}

function renderVolumeSettings(data) {
  window.__volumeSettings = data || {};
  const budget = data.budget || {};
  const policy = data.policy || {};
  const athlete = data.athlete || {};
  const profile = data.profile || {};
  const targets = budget.weekly_target || {};
  const effectiveTargets = budget.weekly_target_effective || {};
  const caps = (budget.session_cap || {}).per_pattern || {};
  const drop = budget.drop || {};
  const comp = budget.compensation || {};
  const targetRows = Object.keys(targets).map((key) => `
    <tr><td><code>${esc(key)}</code></td>
      <td><input type="number" step="0.5" min="0" data-volume-target="${esc(key)}"
        aria-label="${esc(key)} weekly target" value="${esc(targets[key])}"></td>
      <td><input type="number" step="0.5" min="0" data-volume-effective="${esc(key)}"
        aria-label="${esc(key)} effective weekly target" value="${esc(effectiveTargets[key] ?? targets[key])}"></td>
    </tr>`).join("");
  const capRows = Object.keys(caps).map((key) => `
    <tr><td><code>${esc(key)}</code></td>
      <td><input type="number" step="1" min="1" data-volume-cap="${esc(key)}"
        aria-label="${esc(key)} session cap" value="${esc(caps[key])}"></td>
    </tr>`).join("");
  const landmarkGroups = [...new Set(Object.keys(policy)
    .filter((key) => key.startsWith("volume.landmarks."))
    .map((key) => key.split(".")[2]))].sort();
  const landmarkRows = landmarkGroups.map((group) => {
    const cells = ["mev", "mav_low", "mav_high", "mrv"].map((name) => {
      const key = "volume.landmarks." + group + "." + name;
      return `<td><input type="number" step="0.5" min="0" data-volume-policy="${esc(key)}"
        data-kind="float" aria-label="${esc(group)} ${name}" value="${esc(policy[key] ?? 0)}"></td>`;
    }).join("");
    return `<tr><td><code>${esc(group)}</code></td>${cells}</tr>`;
  }).join("");
  const budgetValue = (key) => volumeNestedValue(budget, key);
  const budgetField = (key, label, step = "0.01", min = "0", max = "") => `
    <label>${esc(label)}<input type="number" step="${step}" min="${min}"${max ? ` max="${max}"` : ""}
      data-volume-budget="${esc(key)}" value="${esc(budgetValue(key) ?? "")}"></label>`;
  const policyInput = (key, label, kind, step = "1", min = "0") => `
    <label>${esc(label)}<input type="number" step="${step}" min="${min}"
      data-volume-policy="${esc(key)}" data-kind="${kind}" value="${esc(policy[key] ?? 0)}"></label>`;
  const policyCheck = (key, label) => `
    <label><input type="checkbox" data-volume-policy="${esc(key)}" data-kind="bool"
      ${policy[key] ? "checked" : ""}> ${esc(label)}</label>`;
  const policySelect = (key, label, choices) => `
    <label>${esc(label)}<select data-volume-policy="${esc(key)}" data-kind="str">
      ${choices.map((choice) => `<option value="${esc(choice)}"${policy[key] === choice ? " selected" : ""}>${esc(choice)}</option>`).join("")}
    </select></label>`;
  const athleteLine = "Budget " + (athlete.volume_budget_enabled ? "on" : "off")
    + " · main-lift policy " + esc(athlete.main_lift_policy || "preserve")
    + " · sessions/week " + esc(athlete.sessions_per_week_target ?? "—")
    + " · session target " + esc(athlete.max_session_minutes ?? "—") + " min. "
    + 'These athlete decisions stay in <a href="#state" data-view-link="state">State</a>.';
  $("#settings-volume-athlete").innerHTML = athleteLine;
  $("#settings-volume-warnings").innerHTML = (data.warnings || [])
    .map((warning) => `<p class="warnbox">${esc(warning)}</p>`).join("");
  $("#settings-volume-fields").innerHTML = `
    <div class="panel" style="margin:0 0 10px">
      <div class="panel-head"><h3>Targets and caps</h3><span class="muted">weekly and per session</span></div>
      <div class="table-scroll"><table><thead><tr><th>movement group</th><th>weekly target</th>
        <th>effective target</th></tr></thead><tbody>${targetRows}</tbody></table></div>
      <p class="muted">Base total <strong id="settings-volume-total"></strong> ·
        effective total <strong id="settings-volume-effective-total"></strong> ·
        high band <strong id="settings-volume-high"></strong>
        (totals are derived from the rows and tolerance).</p>
      <div class="form-row">
        ${budgetField("session_cap.total", "Session total cap", "1", "1")}
        <span class="muted">Per-pattern cap sum: <code id="settings-volume-cap-sum"></code>
          (diagnostic only; not the session cap)</span>
        ${budgetField("tolerance", "Tolerance", "0.01", "0", "1")}
        ${budgetField("band_min", "Band minimum", "0.5")}
        ${budgetField("main_lift_floor", "Main-lift floor", "1", "1")}
        ${budgetField("min_accessory_sets", "Accessory floor", "1", "1")}
        ${budgetField("top_up_max_sets_per_item", "Top-up max", "1", "1")}
      </div>
      <div class="form-row">
        <label><input type="checkbox" data-volume-budget="trim_enabled" ${budget.trim_enabled ? "checked" : ""}> Trim above target</label>
        <label><input type="checkbox" data-volume-budget="top_up_enabled" ${budget.top_up_enabled ? "checked" : ""}> Top up below target</label>
        ${budgetField("set_seconds", "Seconds per set", "1", "1")}
        ${budgetField("warmup_estimate_minutes", "Warm-up allowance min", "1", "0")}
        ${budgetField("session_time_cap_minutes", "Session time cap min", "1", "1")}
      </div>
      <details class="advanced"><summary>Per-pattern session caps</summary>
        <div class="table-scroll"><table><thead><tr><th>movement group</th><th>cap</th></tr></thead>
          <tbody>${capRows}</tbody></table></div>
      </details>
    </div>
    <div class="panel" style="margin:0 0 10px">
      <div class="panel-head"><h3>Volume policy</h3><span class="muted">ledger, MRV and under-MEV</span></div>
      <div class="form-row">
        ${policyCheck("volume.apply_mrv_cap", "Apply MRV cap")}
        ${policySelect("volume.ledger.coverage", "Ledger coverage", ["unknown", "complete"])}
        ${policySelect("volume.ledger.set_accounting", "Set accounting", ["hard", "effective"])}
      </div>
      <div class="form-row">
        ${policyCheck("volume.under_mev.enabled", "Under-MEV progression")}
        ${policyInput("volume.under_mev.weeks", "Under-MEV weeks", "int", "1", "1")}
        ${policyInput("volume.under_mev.add_sets", "Under-MEV add sets", "int", "1", "1")}
        ${policyInput("volume.under_mev.max_sets_per_item", "Under-MEV per-item max", "int", "1", "1")}
      </div>
      <details class="advanced"><summary>MEV / MAV / MRV landmarks</summary>
        <div class="table-scroll"><table><thead><tr><th>group</th><th>MEV</th><th>MAV low</th>
          <th>MAV high</th><th>MRV</th></tr></thead><tbody>${landmarkRows}</tbody></table></div>
      </details>
    </div>
    <div class="panel" style="margin:0 0 10px">
      <div class="panel-head"><h3>Drop / volume fill</h3><span class="muted">competition and technique branch</span></div>
      <div class="form-row">
        <label><input type="checkbox" data-volume-drop="enabled" ${drop.enabled ? "checked" : ""}> Enable drop</label>
        <label>Competition confirm days<input type="number" min="0" max="28" step="1"
          data-volume-drop="competition_confirm_days" value="${esc(drop.competition_confirm_days ?? 7)}"></label>
        <label>Max slots/group<input type="number" min="1" max="4" step="1"
          data-volume-drop="max_slots_per_group" value="${esc(drop.max_slots_per_group ?? 1)}"></label>
        <label>Technique minutes<input type="number" min="1" max="120" step="1"
          data-volume-drop="technique_minutes" value="${esc(drop.technique_minutes ?? 30)}"></label>
      </div>
      <details class="advanced"><summary>Drop candidate pool JSON</summary>
        <label>Candidate pool<textarea id="settings-volume-drop-slots" rows="12" spellcheck="false"></textarea></label>
      </details>
    </div>
    <div class="panel" style="margin:0 0 10px">
      <div class="panel-head"><h3>Compensation</h3><span class="muted">advanced; cross-group simulation/application</span></div>
      <div class="form-row">
        <label><input type="checkbox" data-volume-comp="enabled" ${comp.enabled ? "checked" : ""}> Enable preview</label>
        <label><input type="checkbox" data-volume-comp="apply" ${comp.apply ? "checked" : ""}> Apply compensation slot</label>
        <label>Floor<input type="number" min="0" max="1" step="0.01" data-volume-comp="floor"
          value="${esc(comp.floor ?? 0.1)}"></label>
      </div>
      <details class="advanced"><summary>Similarity and candidate slots JSON</summary>
        <label>Similarity<textarea id="settings-volume-comp-similarity" rows="8" spellcheck="false"></textarea></label>
        <label>Slots<textarea id="settings-volume-comp-slots" rows="14" spellcheck="false"></textarea></label>
      </details>
    </div>`;
  $("#settings-volume-drop-slots").value = JSON.stringify(drop.slots || {}, null, 2);
  $("#settings-volume-comp-similarity").value = JSON.stringify(comp.similarity || {}, null, 2);
  $("#settings-volume-comp-slots").value = JSON.stringify(comp.slots || {}, null, 2);
  const meta = $("#settings-volume-meta");
  if (meta) {
    meta.textContent = "source " + (data.source || "config") +
      (profile.profile_id == null ? "" : " · profile " + profile.profile_id);
    meta.className = "badge";
  }
  const effectiveInput = $("#settings-volume-effective");
  if (effectiveInput && !effectiveInput.value) effectiveInput.value = today();
  updateVolumeTotals();
  document.querySelectorAll("#settings-volume-fields input, #settings-volume-fields select").forEach((node) => {
    node.addEventListener("input", updateVolumeTotals);
    node.addEventListener("change", updateVolumeTotals);
  });
}

function volumeDraft() {
  const data = window.__volumeSettings || {};
  const current = data.budget || {};
  const budget = JSON.parse(JSON.stringify(current));
  budget.weekly_target = Object.fromEntries([...document.querySelectorAll("[data-volume-target]")]
    .map((node) => [node.dataset.volumeTarget, Number(node.value)]));
  budget.weekly_target_effective = Object.fromEntries([...document.querySelectorAll("[data-volume-effective]")]
    .map((node) => [node.dataset.volumeEffective, Number(node.value)]));
  budget.weekly_total = Object.values(budget.weekly_target).reduce((sum, value) => sum + value, 0);
  budget.weekly_total_effective = Object.values(budget.weekly_target_effective)
    .reduce((sum, value) => sum + value, 0);
  budget.session_cap = {
    total: Number(document.querySelector('[data-volume-budget="session_cap.total"]').value),
    per_pattern: Object.fromEntries([...document.querySelectorAll("[data-volume-cap]")]
      .map((node) => [node.dataset.volumeCap, Number(node.value)])),
  };
  document.querySelectorAll("[data-volume-budget]").forEach((node) => {
    const key = node.dataset.volumeBudget;
    if (key === "session_cap.total") return;
    budget[key] = node.type === "checkbox" ? node.checked : Number(node.value);
  });
  budget.drop = { ...(current.drop || {}) };
  document.querySelectorAll("[data-volume-drop]").forEach((node) => {
    budget.drop[node.dataset.volumeDrop] = node.type === "checkbox" ? node.checked : Number(node.value);
  });
  budget.drop.slots = volumeJson($("#settings-volume-drop-slots").value, "Drop candidate pool");
  budget.compensation = { ...(current.compensation || {}) };
  document.querySelectorAll("[data-volume-comp]").forEach((node) => {
    budget.compensation[node.dataset.volumeComp] = node.type === "checkbox" ? node.checked : Number(node.value);
  });
  budget.compensation.similarity = volumeJson(
    $("#settings-volume-comp-similarity").value, "Compensation similarity"
  );
  budget.compensation.slots = volumeJson(
    $("#settings-volume-comp-slots").value, "Compensation slots"
  );
  const budgetPatch = volumeDiff(current, budget) || {};
  if (budgetPatch.weekly_target) budgetPatch.weekly_total = budget.weekly_total;
  if (budgetPatch.weekly_target_effective) {
    budgetPatch.weekly_total_effective = budget.weekly_total_effective;
  }
  const policy = {};
  document.querySelectorAll("[data-volume-policy]").forEach((node) => {
    policy[node.dataset.volumePolicy] = volumePolicyValue(node);
  });
  const policyPatch = {};
  Object.entries(policy).forEach(([key, value]) => {
    if (JSON.stringify(value) !== JSON.stringify((data.policy || {})[key])) {
      policyPatch[key] = value;
    }
  });
  return { budgetPatch, policyPatch };
}

async function saveVolumeSettings(event) {
  event.preventDefault();
  try {
    const { budgetPatch, policyPatch } = volumeDraft();
    if (!Object.keys(budgetPatch).length && !Object.keys(policyPatch).length) {
      $("#settings-volume-msg").textContent = "No changes to save.";
      return;
    }
    const reason = $("#settings-volume-reason").value.trim();
    if (!reason) throw new Error("A reason is required for a volume settings change.");
    const data = await api("/api/settings/volume", {
      method: "POST",
      body: JSON.stringify({
        budget: budgetPatch,
        policy: policyPatch,
        effective_from: $("#settings-volume-effective").value || today(),
        reason,
        confirm_text: $("#settings-volume-confirm").value.trim(),
      }),
    });
    renderVolumeSettings(data);
    $("#settings-volume-reason").value = "";
    $("#settings-volume-confirm").value = "";
    $("#settings-volume-msg").textContent = "Saved a new profile version.";
    notify("Volume settings saved.");
    loadDropWindow();
    loadOverview();
  } catch (error) {
    applyFieldErrors(error, $("#settings-volume-msg"), {
      reason: "#settings-volume-reason",
      confirm_text: "#settings-volume-confirm",
      effective_from: "#settings-volume-effective",
      budget: "#settings-volume-fields",
      policy: "#settings-volume-fields",
    });
  }
}

$("#settings-volume-form").addEventListener("submit", saveVolumeSettings);

function renderProfileSettings(registry, profile) {
  window.__profileSettings = profile || {};
  window.__settingsRegistry = registry || [];
  const fields = $("#settings-profile-fields");
  if (!fields) return;
  const groups = {};
  (registry || []).forEach((setting) => {
    // Volume settings live in the consolidated Volume budget panel, not here.
    if (setting.group === "Volume") return;
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
      } else if (setting.kind === "table" || setting.kind === "list") {
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
    else if (setting.kind === "table" || setting.kind === "list") {
      node.value = JSON.stringify(value ?? (setting.kind === "list" ? [] : {}), null, 2);
    }
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
  if (setting.kind === "table" || setting.kind === "list") {
    try { return JSON.parse(node.value || (setting.kind === "list" ? "[]" : "{}")); }
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
        const error = new Error("Guarded changes need the confirmation tick, SPINAL and a reason.");
        error.fields = {
          guard_confirmed: "tick the confirmation",
          guard_text: "type SPINAL",
          reason: "give a reason",
        };
        throw error;
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
    applyFieldErrors(error, $("#settings-profile-msg"), (field) => {
      if (field === "guard_confirmed") return "#settings-profile-guard";
      if (field === "guard_text") return "#settings-profile-guard-text";
      if (field === "reason") return "#settings-profile-reason";
      if (field === "settings") return "#settings-profile-fields";
      const id = "profile-" + String(field).replace(/[^a-zA-Z0-9_-]/g, "-");
      return "#" + id;
    });
  }
}

const MONITORING_SOURCE_LABELS = {
  canonical_config: "Canonical config",
  local_override: "Local override",
  python_default: "Python default",
  fixed_code: "Fixed code",
};

const MONITORING_EDIT_LABELS = {
  phase5a_locked: "Phase 5A locked",
  read_only: "Read-only",
  fixed: "Fixed",
  editable: "Editable",
};

function monitoringValue(row) {
  if (row.value === null || row.value === undefined) return "Not configured";
  let text;
  if (typeof row.value === "boolean") text = row.value ? "On" : "Off";
  else text = String(row.value);
  if (row.unit) text += " " + row.unit;
  return esc(text);
}

function renderMonitoringInventory(data) {
  const groupsBox = $("#settings-monitoring-groups");
  if (!groupsBox) return;
  const groups = data.groups || [];
  const select = $("#settings-monitoring-group");
  const previous = select ? select.value : "";
  if (select) {
    select.innerHTML = "<option value=''>All groups</option>" + groups.map(function (group) {
      return "<option value='" + esc(group.key) + "'>" + esc(group.label) + "</option>";
    }).join("");
    select.value = previous;
  }
  const total = groups.reduce(function (sum, group) {
    return sum + (group.parameters || []).length;
  }, 0);
  const summary = $("#settings-monitoring-summary");
  if (summary) summary.textContent = "Show inventory (" + total + " parameters)";
  const meta = $("#settings-monitoring-meta");
  if (meta) {
    meta.textContent = "v" + (data.application_version || "—") + " · " +
      String(data.revision || "").slice(0, 12);
    meta.title = data.revision || "";
  }
  const phase = $("#settings-monitoring-phase");
  if (phase && data.phase) {
    phase.textContent = data.phase.note + " Review due " + data.phase.review_due + ".";
  }
  groupsBox.innerHTML = groups.map(function (group) {
    const firstDoc = (group.parameters || []).find(function (row) { return row.doc; });
    const rows = (group.parameters || []).map(function (row) {
      const search = [
        group.label, group.key, row.key, row.label, row.value, row.unit,
        row.source, row.source_kind, row.editability, row.reason,
      ].join(" ").toLowerCase();
      const editLabel = MONITORING_EDIT_LABELS[row.editability] || row.editability;
      const sourceLabel = MONITORING_SOURCE_LABELS[row.source_kind] || row.source_kind;
      const defaultBadge = row.source_kind === "python_default"
        ? " <span class='badge warn'>default</span>" : "";
      const reason = row.reason
        ? "<details class='monitoring-reason'><summary>Why this setting?</summary><p>" +
          esc(row.reason) + "</p></details>"
        : "";
      return "<tr class='monitoring-row' data-group='" + esc(group.key) +
        "' data-search='" + esc(search) + "'><td><strong>" + esc(row.label) +
        "</strong><div class='monitoring-key'>" + esc(row.key) +
        "</div><span class='badge'>" + esc(editLabel) + "</span>" + reason +
        "</td><td class='monitoring-value'>" +
        monitoringValue(row) + defaultBadge + "</td><td><code>" + esc(row.source) +
        "</code><div><span class='badge'>" + esc(sourceLabel) + "</span></div></td></tr>";
    }).join("");
    return "<section class='monitoring-group' data-group='" + esc(group.key) + "'>" +
      "<h3>" + esc(group.label) + "</h3>" +
      (firstDoc ? "<p class='section-help'><a class='doc-link' href='#docs?doc=" +
        encodeURIComponent(firstDoc.doc) + "'>Reference</a></p>" : "") +
      "<div class='table-scroll'><table class='monitoring-table'><thead><tr>" +
      "<th>Parameter</th><th>Effective value</th><th>Source</th></tr></thead><tbody>" +
      rows + "</tbody></table></div></section>";
  }).join("");
  applyMonitoringFilter();
  const search = $("#settings-monitoring-search");
  if (search && !search.dataset.wired) {
    search.dataset.wired = "1";
    search.addEventListener("input", applyMonitoringFilter);
  }
  if (select && !select.dataset.wired) {
    select.dataset.wired = "1";
    select.addEventListener("change", applyMonitoringFilter);
  }
}

function applyMonitoringFilter() {
  const query = ($("#settings-monitoring-search").value || "").trim().toLowerCase();
  const group = $("#settings-monitoring-group").value || "";
  let totalVisible = 0;
  document.querySelectorAll(".monitoring-group").forEach(function (section) {
    let visible = 0;
    section.querySelectorAll(".monitoring-row").forEach(function (row) {
      const show = (!group || row.dataset.group === group) &&
        (!query || (row.dataset.search || "").includes(query));
      row.hidden = !show;
      if (show) visible += 1;
    });
    section.hidden = visible === 0;
    totalVisible += visible;
  });
  const empty = $("#settings-monitoring-empty");
  if (empty) empty.hidden = totalVisible > 0;
}

async function loadSettings() {
  let data;
  try {
    data = await api("/api/settings");
    renderSettings(data);
  } catch (error) {
    $("#settings-llm-status").textContent = "error";
    $("#settings-llm-msg").textContent = error.message;
    return;
  }
  // The profile and modality panels are secondary. A transient failure there must not leave
  // the main Settings fields (LLM, drop, app facts) blank after the settings response arrived.
  try {
    const profile = await api("/api/settings/profile");
    renderProfileSettings(data.registry || [], profile);
  } catch (error) {
    $("#settings-profile-msg").textContent = "Profile settings failed: " + error.message;
  }
  try {
    renderVolumeSettings(await api("/api/settings/volume"));
  } catch (error) {
    $("#settings-volume-msg").textContent = "Volume settings failed: " + error.message;
  }
  try {
    renderMonitoringInventory(await api("/api/settings/monitoring"));
  } catch (error) {
    $("#settings-monitoring-meta").textContent = "error";
    $("#settings-monitoring-groups").innerHTML =
      "<p class='warnbox'>Monitoring inventory failed: " + esc(error.message) + "</p>";
  }
  try {
    const modalityData = await api("/api/modalities");
    renderModalities(modalityData);
  } catch (error) {
    $("#settings-profile-msg").textContent = "Modality settings failed: " + error.message;
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
    applyFieldErrors(error, $("#settings-llm-msg"), {
      model: "#settings-llm-model",
      base_url: "#settings-llm-base-url",
      temperature: "#settings-llm-temperature",
      max_tokens: "#settings-llm-max-tokens",
      timeout_s: "#settings-llm-timeout",
      settings: "#settings-llm-enabled",
    });
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



async function loadTemplateStatus() {
  const data = await api("/api/templates");
  $("#template-summary-status").textContent = data.summary_stale
    ? "Programme summary is stale; refresh it after a template change."
    : "Programme summary is current.";
  return data;
}

async function openTemplateEditor() {
  try {
    const data = await loadTemplateStatus();
    $("#template-yaml").value = data.yaml || "";
    $("#template-path").textContent = data.path || "";
    $("#template-msg").textContent = "";
    $("#template-dialog").showModal();
  } catch (error) {
    $("#template-msg").textContent = error.message;
  }
}

$("#templates-edit").addEventListener("click", openTemplateEditor);
$("#template-cancel").addEventListener("click", () => $("#template-dialog").close());
$("#template-restore").addEventListener("click", async () => {
  if (!confirm("Restore the last template backup? The current file will be backed up first.")) return;
  try {
    await api("/api/templates/restore", { method: "POST", body: "{}" });
    await loadExerciseCatalog();
    await loadTemplateStatus();
  } catch (error) {
    $("#template-summary-status").textContent = error.message;
  }
});
$("#template-summary-refresh").addEventListener("click", async () => {
  try {
    await api("/api/templates/summary", { method: "POST", body: "{}" });
    await loadTemplateStatus();
  } catch (error) {
    $("#template-summary-status").textContent = error.message;
  }
});
$("#template-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#template-msg").textContent = "Saving…";
  try {
    await api("/api/templates", {
      method: "POST",
      body: JSON.stringify({ yaml: $("#template-yaml").value }),
    });
    $("#template-msg").textContent = "Saved.";
    $("#template-dialog").close();
    await loadExerciseCatalog();
    await loadTemplateStatus();
  } catch (error) {
    $("#template-msg").textContent = error.message;
  }
});

/* --- boot --------------------------------------------------------------- */
/* Defer until every script is loaded: setView reaches history.js/workout.js loaders,
   and this also fixes the #history/#workout deep links. */
document.addEventListener("DOMContentLoaded", () => {
  applyTheme(storedThemeMode());
  applyStoredUiDefaults();
  fillSessionSelect();
  loadExercises();
  loadOverview();
  applyHashRoute();
});
