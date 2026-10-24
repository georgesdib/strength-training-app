/* Local UI over the strength-coach HTTP API. No framework, no external assets. */
const $ = (sel) => document.querySelector(sel);
const today = () => new Date().toLocaleDateString("en-CA");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
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

function setView(name) {
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
  if (name === "prescribe") { loadFatigue(); loadContinuity(); loadVolume(); }
  if (name === "docs" && !$("#docs-list").dataset.loaded) loadDocs();
  if (name === "state") loadState();
  if (name === "settings") loadSettings();
  if (name === "outcomes") loadOutcomes();
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
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
window.addEventListener("hashchange", () => {
  const name = location.hash.replace("#", "") || "dashboard";
  if (document.getElementById("view-" + name)) setView(name);
});

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
    const cards = [
      ["Readiness today", data.readiness_score?.score != null
        ? data.readiness_score.score.toFixed(2) : "unknown",
        data.readiness_score?.status + (data.readiness_score?.basis ? " · " + data.readiness_score.basis : "")],
      ["Block week", data.block_week ?? "unknown", "erector ramp / DUP"],
      ["Injury signal", signal?.status ?? "unknown", signal?.summary ?? ""],
      ["Cardio (4 wk avg)", data.cardio ? data.cardio.average_weekly_minutes + " min/wk" : "unknown",
        data.cardio ? "reference " + data.cardio.reference_min + "-" + data.cardio.reference_max
          + " · " + data.cardio.sessions + " session(s)" : "no entry"],
      ["Unreviewed", data.unreviewed.length, data.unreviewed.length ? "run review to catch up" : "all caught up"],
    ];
    $("#cards").innerHTML = cards.map(([label, value, sub]) => `
      <div class="card"><div class="label">${esc(label)}</div>
      <div class="value">${esc(value)}</div><div class="sub">${esc(sub)}</div></div>`).join("");
    renderRecent(data.sessions);
    fillSessionSelect();
    loadProgress();
    loadReviews();
  } catch (error) {
    $("#today-title").textContent = "Could not load";
    $("#today-sub").textContent = error.message;
  }
}

async function loadProgress() {
  try {
    const data = await api("/api/progress");
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
      <p class="muted">sRPE coverage: ${data.coverage.with_srpe}/${data.coverage.sessions}
        (${data.coverage.pct}%). Performance ratio: <strong>${esc(latest)}</strong>;
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
      const doc = task.doc ? `<a href="#docs" data-view-link="docs">${esc(task.doc)}</a>` : "";
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
    await loadReviews();
  } catch (error) {
    $("#reviews").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function snoozeReview(taskKey) {
  try {
    await api("/api/reviews", { method: "POST", body: JSON.stringify({
      task_key: taskKey, action: "snoozed",
    }) });
    await loadReviews();
  } catch (error) {
    $("#reviews").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

function renderRecent(sessions) {
  if (!sessions.length) { $("#recent").innerHTML = "<p class='empty'>No sessions.</p>"; return; }
  $("#recent").innerHTML = `<table><thead><tr><th>Date</th><th>Day</th><th>Sets</th>
    <th>Main lifts</th><th>Marks</th><th></th></tr></thead><tbody>` +
    sessions.map((s) => `<tr><td>${esc(s.occurred_on)}</td><td>${esc(s.session_type)}</td>
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
    const data = await api("/api/outcomes?" + query.toString());
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
      <p class="muted">${esc(data.window.from)} to ${esc(data.window.to)} · ${data.window.weeks} weeks</p>
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
      <h3>Longevity context</h3>
      <p class="muted">Captured, not prescribed. ${esc(longevity.note || "")}</p>
      <p>Cardio: ${cardio.average_weekly_minutes ?? "unknown"} min/week average;
        last four weeks ${cardio.rolling_4w_average ?? "unknown"} min/week
        (${cardio.sessions ?? 0} sessions, ${cardio.weeks_with_data ?? 0} week(s) with data).
        Reference: ${cardio.reference_min}–${cardio.reference_max} min/week, general context only.</p>
      <table><thead><tr><th>Week</th><th>aerobic minutes</th></tr></thead>
      <tbody>${cardioWeeks || "<tr><td colspan='2' class='muted'>no cardio entries</td></tr>"}</tbody></table>
      <table><thead><tr><th>Modality</th><th>sessions</th></tr></thead>
      <tbody>${modalities || "<tr><td colspan='2' class='muted'>none</td></tr>"}</tbody></table>
      <table><thead><tr><th>Readiness field</th><th>n</th><th>average</th><th>first → last</th></tr></thead>
      <tbody>${readinessFields || "<tr><td colspan='4' class='muted'>no readiness fields</td></tr>"}</tbody></table>
      <table><thead><tr><th>Measurement</th><th>latest</th><th>change</th><th>date</th></tr></thead>
      <tbody>${metrics || "<tr><td colspan='4' class='muted'>none measured in this catalogue</td></tr>"}</tbody></table>
      <h3>Symptoms</h3>
      <table><thead><tr><th>Region</th><th>flares</th><th>readings</th><th>latest</th></tr></thead>
      <tbody>${symptomRows || "<tr><td colspan='4' class='muted'>no symptom entries — unknown, not “no flare”</td></tr>"}</tbody></table>
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

async function loadProspective(weeks, day) {
  const target = $("#prospective-result");
  if (!target) return;
  try {
    const query = new URLSearchParams({ weeks });
    if (day) query.set("date", day);
    const data = await api("/api/prospective?" + query.toString());
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
      <p class="muted">${esc(data.window.current_from)} to ${esc(data.window.current_to)}
        · baseline ${esc(data.window.baseline_from)} to ${esc(data.window.baseline_to)}</p>
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
function syncMinimumSession() {
  const on = $("#prescribe-minimum").checked;
  $("#prescribe-minimum-options").hidden = !on;
  $("#prescribe-target").disabled = !on;
  $("#prescribe-minimum-main").disabled = !on;
  if (!on) $("#prescribe-minimum-main").checked = false;
}
$("#prescribe-minimum").addEventListener("change", syncMinimumSession);
syncMinimumSession();

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
});

let lastPrescribePayload = null;

$("#prescribe-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const date = $("#prescribe-date").value;
  const sessionType = $("#prescribe-session-type").value;
  $("#prescribe-result").innerHTML = "<p class='empty'>Building…</p>";
  const applySelection = $("#prescribe-apply-selection").checked;
  const selectionLlm = applySelection && $("#prescribe-selection-llm").checked;
  const selectionConfirmed = applySelection && $("#prescribe-selection-confirm").checked;
  lastPrescribePayload = {
    date, session_type: sessionType,
    apply_selection: applySelection, selection_llm: selectionLlm,
    selection_confirmed: selectionConfirmed,
    minimum_session: $("#prescribe-minimum").checked,
    target_minutes: Number($("#prescribe-target").value),
    minimum_include_main: $("#prescribe-minimum-main").checked,
  };
  try {
    const data = await api("/api/prescribe", { method: "POST", body: JSON.stringify(lastPrescribePayload) });
    renderPrescription(data);
  } catch (error) {
    $("#prescribe-result").innerHTML = `<div class="panel warnbox">${esc(error.message)}</div>`;
  }
});

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
    <div class="panel-head"><h2>${esc(p.for_date)} · ${esc(p.session_type || "unknown")}</h2>
      <span class="badge ${p.executable ? "" : "bad"}">${p.executable ? "executable" : "not executable"}</span></div>
    ${warnings}${spinalBox}${minimumBox}${deloadBox}${suggestionBox}${selectionBox}${signalBox}${cadenceBox}
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
    ${esc(s.occurred_on)} · ${esc(s.session_type)} · ${s.marks ? s.marks + " marks" : "unreviewed"}</option>`).join("");
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
    $("#review-result").innerHTML = `<div class="panel">
      <div class="panel-head"><h2>${esc(data.session)} · ${esc(data.session_type)}</h2>
        <span class="badge">composite ${fmt(data.composite, 2)}</span></div>
      <p class="muted">Week ${esc(data.week)} · spinal cost ${fmt(data.week_cost, 2)}</p>
      ${reviewWorkoutSummary(data.workout)}
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
    loadOverview();
  } catch (error) {
    $("#review-calibration").innerHTML = `<div class="warnbox">${esc(error.message)}</div>`;
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

$("#readiness-date").value = today();
$("#readiness-fields").innerHTML = SCORE_FIELDS.map((f) => fieldInput(f)).join("");
$("#readiness-device").innerHTML = DEVICE_FIELDS.map((f) => fieldInput(f, true)).join("");
$("#readiness-date").addEventListener("change", () => loadReadiness($("#readiness-date").value));

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
    loadOverview();
  } catch (error) {
    $("#readiness-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
});

function renderReadiness(data) {
  if (!data || data.known === false || Object.keys(data).length === 0) {
    $("#readiness-result").innerHTML = "<p class='empty'>No readiness for this date.</p>";
    return;
  }
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
    renderStateForms(data);
    loadExposureStatus();
    $("#state-result").innerHTML = `
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
        <button class="primary" type="submit">Save profile version</button>
      </form>
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
      <form id="symptom-form" class="grid-fields">
        <label>Date<input data-symptom="date" type="date"></label>
        <label>Region<select data-symptom="region">${regionOptions}</select></label>
        <label>Level<select data-symptom="level"><option>0</option><option>1</option><option>2</option><option>3</option></select></label>
        <label>Settled<select data-symptom="settled"><option>unknown</option><option>yes</option><option>no</option></select></label>
        <label class="grow">Note<input data-symptom="note"></label>
        <button class="primary" type="submit">Append symptom</button>
      </form>
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
}

/* --- docs --------------------------------------------------------------- */
async function loadDocs() {
  try {
    const docs = await api("/api/docs");
    $("#docs-list").dataset.loaded = "1";
    $("#docs-list").innerHTML = docs.map((doc) => `<a href="#docs" data-doc="${esc(doc.name)}">
      ${esc(doc.title)}</a>`).join("");
    document.querySelectorAll("[data-doc]").forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        loadDoc(link.dataset.doc);
      });
    });
    if (docs.length) loadDoc(docs[0].name);
  } catch (error) {
    $("#docs-list").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

async function loadDoc(name) {
  try {
    const doc = await api("/api/docs/" + encodeURIComponent(name));
    $("#doc-body").innerHTML = `<p class="muted">${esc(doc.name)}</p>` + doc.html;
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
}

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
      <td><strong>${esc(entry.session_type)}</strong></td>
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

async function runProgramme() {
  const payload = {
    weeks: Number($("#programme-weeks").value || 4),
    remaining: $("#programme-remaining").checked,
    start: $("#programme-start").value || null,
    sessions_per_week: Number($("#programme-per-week").value || 3),
    start_session_type: $("#programme-session-type").value || "auto",
  };
  const button = $("#programme-form button[type='submit']");
  $("#programme-result").innerHTML = "<p class='empty'>Building forecast… each week is three prescriptions, so this takes a few seconds.</p>";
  button.disabled = true;
  try {
    const data = await api("/api/programme", { method: "POST", body: JSON.stringify(payload) });
    renderProgramme(data.entries);
  } catch (error) {
    $("#programme-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  } finally {
    button.disabled = false;
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
  syncLlmFields();
}

async function loadSettings() {
  try {
    renderSettings(await api("/api/settings"));
  } catch (error) {
    $("#settings-llm-status").textContent = "error";
    $("#settings-llm-msg").textContent = error.message;
  }
}

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
$("#settings-defaults-save").addEventListener("click", () => {
  const target = $("#settings-default-target").value;
  localStorage.setItem(SETTINGS_TARGET_KEY, target);
  localStorage.setItem(SETTINGS_CLASS_C_KEY, $("#settings-default-class-c").checked ? "1" : "0");
  applyStoredUiDefaults();
  $("#settings-defaults-msg").textContent = "Saved in this browser.";
});

/* --- boot --------------------------------------------------------------- */
applyStoredUiDefaults();
fillSessionSelect();
loadExercises();
loadOverview();
const initial = location.hash.replace("#", "") || "dashboard";
if (document.getElementById("view-" + initial)) setView(initial);
