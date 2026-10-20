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
  if (name === "docs" && !$("#docs-list").dataset.loaded) loadDocs();
  if (name === "state") loadState();
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
      ["Unreviewed", data.unreviewed.length, data.unreviewed.length ? "run review to catch up" : "all caught up"],
    ];
    $("#cards").innerHTML = cards.map(([label, value, sub]) => `
      <div class="card"><div class="label">${esc(label)}</div>
      <div class="value">${esc(value)}</div><div class="sub">${esc(sub)}</div></div>`).join("");
    renderRecent(data.sessions);
    fillSessionSelect();
  } catch (error) {
    $("#today-title").textContent = "Could not load";
    $("#today-sub").textContent = error.message;
  }
}

function renderRecent(sessions) {
  if (!sessions.length) { $("#recent").innerHTML = "<p class='empty'>No sessions.</p>"; return; }
  $("#recent").innerHTML = `<table><thead><tr><th>Date</th><th>Day</th><th>Sets</th>
    <th>Main lifts</th><th>Marks</th><th></th></tr></thead><tbody>` +
    sessions.map((s) => `<tr><td>${esc(s.occurred_on)}</td><td>${esc(s.day_guess)}</td>
      <td>${s.working_set_count}/${s.set_count}</td>
      <td>${esc((s.main_lifts || []).join(", "))}</td>
      <td>${s.marks ? '<span class="badge">' + s.marks + "</span>" : '<span class="badge warn">none</span>'}</td>
      <td><button class="ghost" onclick="openReview('${esc(s.session_id)}')">Review</button></td></tr>`).join("")
    + "</tbody></table>";
}

function openReview(session) {
  setView("review");
  $("#review-session").value = session;
  loadReview(session);
}

/* --- prescribe ---------------------------------------------------------- */
$("#prescribe-date").value = today();
$("#prescribe-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const date = $("#prescribe-date").value;
  const day = $("#prescribe-day").value;
  $("#prescribe-result").innerHTML = "<p class='empty'>Building…</p>";
  try {
    const data = await api("/api/prescribe", { method: "POST", body: JSON.stringify({ date, day }) });
    renderPrescription(data);
  } catch (error) {
    $("#prescribe-result").innerHTML = `<div class="panel warnbox">${esc(error.message)}</div>`;
  }
});

function renderPrescription(p) {
  const rows = p.items.map((item) => `<tr>
    <td><strong>${esc(item.exercise_id)}</strong>${item.essential ? ' <span class="badge">essential</span>' : ""}
      ${item.unknown_load_reason ? '<div class="muted">' + esc(item.unknown_load_reason) + "</div>" : ""}</td>
    <td>${item.sets}</td><td>${item.reps_low}–${item.reps_high}</td>
    <td>${fmt(item.load_kg)}</td><td>${item.rir_target}</td>
    <td class="muted">${esc(item.refs.slice(-2).join(", "))}</td></tr>`).join("");
  const warnings = p.warnings.length
    ? '<div class="warnbox"><strong>Warnings</strong><ul class="list">' +
      p.warnings.map((w) => "<li>" + esc(w) + "</li>").join("") + "</ul></div>" : "";
  const signal = p.notes?.injury_signal;
  const signalBox = signal ? `<p class="muted">Injury signal: <strong>${esc(signal.status)}</strong>
    — ${esc(signal.summary)}</p>` : "";
  $("#prescribe-result").innerHTML = `<div class="panel">
    <div class="panel-head"><h2>${esc(p.for_date)} · Day ${esc(p.session_day)}</h2>
      <span class="badge ${p.executable ? "" : "bad"}">${p.executable ? "executable" : "not executable"}</span></div>
    ${warnings}${signalBox}
    <table><thead><tr><th>Exercise</th><th>Sets</th><th>Reps</th><th>kg</th><th>RIR</th><th>refs</th></tr></thead>
    <tbody>${rows}</tbody></table>
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
    ${esc(s.occurred_on)} · ${esc(s.day_guess)} · ${s.marks ? s.marks + " marks" : "unreviewed"}</option>`).join("");
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
      <div class="panel-head"><h2>${esc(data.session)} · Day ${esc(data.day)}</h2>
        <span class="badge">composite ${fmt(data.composite, 2)}</span></div>
      <p class="muted">Week ${esc(data.week)} · spinal cost ${fmt(data.week_cost, 2)}</p>
      <table><thead><tr><th>Item</th><th>engine</th><th>your score</th><th>why</th></tr></thead>
      <tbody>${items}</tbody></table>
      <div class="form-row">
        <label>Remembrance <select id="review-confidence">
          <option value="high" ${data.confidence === "high" ? "selected" : ""}>high</option>
          <option value="low" ${data.confidence === "low" ? "selected" : ""}>low</option>
          <option value="unknown" ${data.confidence === "unknown" ? "selected" : ""}>unknown</option>
        </select></label>
        <label class="grow">Note <input id="review-note" placeholder="optional"></label>
        <button class="primary" id="save-review">Save marks</button>
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
  };
  try {
    const data = await api("/api/review/" + encodeURIComponent(session), {
      method: "POST", body: JSON.stringify(payload),
    });
    $("#review-calibration").innerHTML = `<div class="warnbox"><strong>Saved ${data.written} marks</strong>
      <pre>${esc(data.calibration.text)}</pre></div>`;
    loadOverview();
  } catch (error) {
    $("#review-calibration").innerHTML = `<div class="warnbox">${esc(error.message)}</div>`;
  }
}

/* --- readiness ---------------------------------------------------------- */
const SCORE_FIELDS = ["sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration"];
const DEVICE_FIELDS = ["hrv_ms", "rhr_bpm", "bodyweight_kg", "fat_pct", "grip_strength_kg"];
const LABELS = { sleep: "Sleep", energy: "Energy", mood: "Mood", soreness: "Soreness",
  stress: "Stress", nutrition: "Nutrition", hydration: "Hydration",
  hrv_ms: "HRV (ms)", rhr_bpm: "Resting HR (bpm)",
  bodyweight_kg: "Bodyweight (kg)", fat_pct: "Body fat (%)", grip_strength_kg: "Grip strength (kg)" };

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
    renderReadiness(data);
  } catch (error) {
    $("#readiness-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

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
    ${components ? `<table><thead><tr><th>Input</th><th>value</th><th>normalised</th></tr></thead><tbody>${components}</tbody></table>` : ""}
    ${categories ? `<h3>Categories</h3><table><thead><tr><th>Category</th><th>score</th></tr></thead><tbody>${categories}</tbody></table>` : ""}
    ${overrides ? `<h3>Overrides</h3><table><thead><tr><th>Scope</th><th>value</th><th>reason</th></tr></thead><tbody>${overrides}</tbody></table>` : ""}
  </div>`;
}

/* --- state -------------------------------------------------------------- */
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
    const injuryRows = regions.length ? `<table><thead><tr><th>Region</th><th>Status</th>
      <th>Tolerated</th><th>Window</th></tr></thead><tbody>` + regions.map((r) => `
      <tr><td><strong>${esc(r.label)}</strong><div class="muted">${esc(r.summary)}</div></td>
      <td>${esc(r.status)}</td><td>${r.tolerated_sessions}/${r.required_tolerated_sessions}
      <div class="muted">of ${r.loaded_sessions} loaded (${r.unverified_sessions} unverified)</div></td>
      <td>${r.window_days} d</td></tr>`).join("") + "</tbody></table>"
      : "<p class='empty'>no regions configured</p>";
    renderStateForms(data);
    $("#state-result").innerHTML = `
      <div class="panel"><div class="panel-head"><h2>Profile</h2></div>
        <table><tbody>${profileRows}</tbody></table></div>
      <div class="panel"><div class="panel-head"><h2>Constraints</h2></div><ul class="list">${constraints}</ul></div>
      <div class="panel"><div class="panel-head"><h2>Suitability</h2></div>
        ${suitability ? `<table><thead><tr><th>Exercise</th><th>can-do</th><th>will-do</th><th>feels bad</th></tr></thead><tbody>${suitability}</tbody></table>` : "<p class='empty'>none recorded</p>"}</div>
      <div class="panel"><div class="panel-head"><h2>Injury signal</h2></div>
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

    <div class="panel"><div class="panel-head"><h2>Strength test</h2><span class="muted">records a measured e1RM</span></div>
      <form id="test-form" class="grid-fields">
        <label>Exercise<input data-test="exercise_id" list="exercise-options" placeholder="canonical id"></label>
        <label>kg<input data-test="kg" type="number" step="0.5"></label>
        <label>Reps<input data-test="reps" type="number" min="1" max="10"></label>
        <label>Date<input data-test="date" type="date"></label>
        <label><input data-test="max" type="checkbox"> confirm true 1RM</label>
        <label class="grow">Reason<input data-test="reason"></label>
        <button class="primary" type="submit">Record test</button>
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


/* --- programme ---------------------------------------------------------- */
function programmeStatus(entry) {
  if (entry.deload_reason) return "deload";
  if (!entry.prescription.executable) return "not executable";
  return entry.prescription.fallback_level || "forecast";
}

function renderProgramme(entries) {
  if (!entries.length) {
    $("#programme-result").innerHTML = "<p class='warnbox'>No sessions in that horizon.</p>";
    return;
  }
  const rows = entries.map((entry) => {
    const items = entry.prescription.items.map((item) =>
      `<li>${esc(item.exercise_id)} — ${item.sets}×${item.reps_low}-${item.reps_high}
       @ ${fmt(item.load_kg)} kg, RIR ${esc(item.rir_target)}</li>`).join("");
    const warn = entry.prescription.warnings.length
      ? `<details><summary>${entry.prescription.warnings.length} warning(s)</summary><ul>${entry.prescription.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></details>`
      : "<span class='empty'>none</span>";
    return `<tr>
      <td>${esc(entry.date)}</td>
      <td><strong>${esc(entry.day)}</strong></td>
      <td>${esc(programmeStatus(entry))}</td>
      <td><ul class="plain">${items}</ul>
        ${entry.deload_reason ? `<p class="warnbox">reactive deload: ${esc(entry.deload_reason)}</p>` : ""}
        ${warn}</td>
    </tr>`;
  }).join("");
  $("#programme-result").innerHTML = `<div class="panel"><table>
    <thead><tr><th>Date</th><th>Day</th><th>Status</th><th>Session</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

async function runProgramme() {
  const payload = {
    weeks: Number($("#programme-weeks").value || 4),
    remaining: $("#programme-remaining").checked,
    start: $("#programme-start").value || null,
    sessions_per_week: Number($("#programme-per-week").value || 3),
    start_day: $("#programme-day").value || null,
  };
  $("#programme-result").innerHTML = "<p class='empty'>Building forecast…</p>";
  try {
    const data = await api("/api/programme", { method: "POST", body: JSON.stringify(payload) });
    renderProgramme(data.entries);
  } catch (error) {
    $("#programme-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

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

/* --- boot --------------------------------------------------------------- */
fillSessionSelect();
loadExercises();
loadOverview();
const initial = location.hash.replace("#", "") || "dashboard";
if (document.getElementById("view-" + initial)) setView(initial);
