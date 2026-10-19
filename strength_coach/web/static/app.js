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
    const signal = data.back_signal;
    const cards = [
      ["Readiness today", readiness?.sleep != null || readiness?.energy != null
        ? `sleep ${readiness.sleep ?? "—"} · energy ${readiness.energy ?? "—"}`
        : "unknown", readiness?.sources ? "source: " + Object.entries(readiness.sources)
          .filter(([k]) => ["sleep", "energy"].includes(k)).map(([k, v]) => k + "=" + v).join(", ") : "no entry"],
      ["Block week", data.block_week ?? "unknown", "erector ramp / DUP"],
      ["Back signal", signal?.status ?? "unknown", signal?.summary ?? ""],
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
  const signal = p.notes?.back_signal;
  const signalBox = signal ? `<p class="muted">Back signal: <strong>${esc(signal.status)}</strong>
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
const SCORE_FIELDS = ["sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration",
  "squat_readiness", "bench_readiness", "deadlift_readiness"];
const DEVICE_FIELDS = ["hrv_ms", "rhr_bpm", "bodyweight_kg", "fat_pct", "grip_strength_kg"];
const LABELS = { sleep: "Sleep", energy: "Energy", mood: "Mood", soreness: "Soreness",
  stress: "Stress", nutrition: "Nutrition", hydration: "Hydration",
  squat_readiness: "Squat readiness", bench_readiness: "Bench readiness",
  deadlift_readiness: "Deadlift readiness", hrv_ms: "HRV (ms)", rhr_bpm: "Resting HR (bpm)",
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
        <tr><td>Raw rows inserted</td><td>${data.raw_rows_inserted}</td></tr>
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
    $("#state-result").innerHTML = `
      <div class="panel"><div class="panel-head"><h2>Profile</h2></div>
        <table><tbody>${profileRows}</tbody></table></div>
      <div class="panel"><div class="panel-head"><h2>Constraints</h2></div><ul class="list">${constraints}</ul></div>
      <div class="panel"><div class="panel-head"><h2>Suitability</h2></div>
        ${suitability ? `<table><thead><tr><th>Exercise</th><th>can-do</th><th>will-do</th><th>feels bad</th></tr></thead><tbody>${suitability}</tbody></table>` : "<p class='empty'>none recorded</p>"}</div>
      <div class="panel"><div class="panel-head"><h2>Back signal</h2></div>
        <p>${esc(data.back_signal?.summary || "")}</p>
        <p class="muted">${esc(data.back_signal?.disclaimer || "")}</p></div>`;
  } catch (error) {
    $("#state-result").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
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

/* --- boot --------------------------------------------------------------- */
fillSessionSelect();
loadOverview();
const initial = location.hash.replace("#", "") || "dashboard";
if (document.getElementById("view-" + initial)) setView(initial);
