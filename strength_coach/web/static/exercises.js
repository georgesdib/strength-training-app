/* Exercise catalogue, editor and e1RM override feature module. */
/* --- exercise catalogue -------------------------------------------------- */
const EXERCISE_KNOWN = [
  "display", "log_names", "pattern", "primary_muscles", "primary_compound",
  "loadable", "bodyweight_type", "time_based", "e1rm_applicable", "vbt_family",
  "main_lift", "high_fatigue_spinal", "erector_family", "direct_erector",
  "day_roles",
];

function patternSelectHtml(selected) {
  const patterns = (window.__exerciseCatalog?.patterns || []);
  const values = new Set(patterns.map(String));
  let options = patterns.map((value) =>
    `<option value="${esc(value)}"${String(selected ?? "") === String(value) ? " selected" : ""}>${esc(value)}</option>`
  ).join("");
  if (selected && !values.has(String(selected))) {
    options += `<option value="${esc(selected)}" selected>${esc(selected)} (legacy — not in current list)</option>`;
  }
  return `<option value="">choose…</option>${options}`;
}

function setPatternSelect(selector, selected) {
  const node = $(selector);
  if (!node) return;
  node.innerHTML = patternSelectHtml(selected);
  node.value = selected || "";
}

const VBT_NEW_VALUE = "__new__";

function vbtFamilyOptions(selected) {
  const families = (window.__exerciseCatalog?.vbt_families || []).map(String);
  const values = new Set(families);
  let markup = '<option value="">— none —</option>' + families.map((value) =>
    `<option value="${esc(value)}"${String(selected ?? "") === value ? " selected" : ""}>${esc(value)}</option>`
  ).join("");
  if (selected && !values.has(String(selected))) {
    markup += `<option value="${esc(selected)}" selected>${esc(selected)} (legacy — not in current list)</option>`;
  }
  markup += `<option value="${VBT_NEW_VALUE}">Add new family…</option>`;
  return markup;
}

function setVbtFamily(selectSelector, newSelector, wrapSelector, value) {
  const select = $(selectSelector);
  const wrap = $(wrapSelector);
  const input = $(newSelector);
  if (!select) return;
  select.innerHTML = vbtFamilyOptions(value);
  select.value = value || "";
  if (input) input.value = "";
  if (wrap) wrap.hidden = true;
}

function syncVbtFamily(selectSelector, newSelector, wrapSelector) {
  const select = $(selectSelector);
  const wrap = $(wrapSelector);
  const input = $(newSelector);
  if (!select || !wrap) return;
  const adding = select.value === VBT_NEW_VALUE;
  wrap.hidden = !adding;
  if (adding && input) input.focus();
}

function readVbtFamily(selectSelector, newSelector) {
  const select = $(selectSelector);
  const input = $(newSelector);
  if (!select) return "";
  if (select.value === VBT_NEW_VALUE) return input ? input.value.trim() : "";
  return select.value.trim();
}

function muscleChoicesHtml(selected) {
  const muscles = (window.__exerciseCatalog?.muscles || []);
  const chosen = new Set((selected || []).map(String));
  const values = new Set(muscles.map(String));
  let markup = muscles.map((value) => `<label class="choice">
    <input type="checkbox" data-muscle value="${esc(value)}"${chosen.has(String(value)) ? " checked" : ""}>
    <span>${esc(value)}</span></label>`).join("");
  for (const legacy of chosen) {
    if (!values.has(legacy)) {
      markup += `<label class="choice">
        <input type="checkbox" data-muscle value="${esc(legacy)}" checked>
        <span>${esc(legacy)} (legacy — not in current list)</span></label>`;
    }
  }
  return markup;
}

function setMuscleChoices(selector, selected) {
  const node = $(selector);
  if (node) node.innerHTML = muscleChoicesHtml(selected);
}

function selectedMusclesIn(selector) {
  return [...document.querySelectorAll(`${selector} [data-muscle]:checked`)]
    .map((input) => input.value);
}

let exerciseTrendsGeneration = 0;
let exerciseHistoryState = null;
let exerciseHistoryLoading = false;
const EXERCISE_HISTORY_PAGE_SIZE = 50;

function exerciseDefaultHistoryStart() {
  const date = new Date(today() + "T12:00:00");
  date.setDate(date.getDate() - 364);
  return formatLocalDate(date);
}

function exerciseHistoryUrl(exerciseId, state, offset, includeAnalytics) {
  const params = new URLSearchParams();
  params.set("exercise_id", exerciseId);
  params.set("limit", String(EXERCISE_HISTORY_PAGE_SIZE));
  params.set("offset", String(offset));
  if (state.start) params.set("start", state.start);
  if (state.end) params.set("end", state.end);
  if (includeAnalytics) params.set("include_analytics", "true");
  return "/api/exercise-history?" + params.toString();
}

function exerciseE1rmUrl(exerciseId, start, end) {
  const params = new URLSearchParams({ exercise_id: exerciseId, quality: "degraded" });
  if (start) params.set("from", start);
  if (end) params.set("to", end);
  return "/api/performance/e1rm?" + params.toString();
}

function exerciseMetricCell(value, suffix) {
  return value == null ? "<span class='muted'>not recorded</span>" : esc(value) + (suffix || "");
}

function renderExerciseE1rmHistory(data, exerciseId) {
  const target = $("#exercise-trend-e1rm");
  const summary = data.summary || {};
  const points = data.points || [];
  const rows = points.map((point) => `<tr><td>${esc(point.date)}</td><td>${fmt(point.kg)} kg</td>
    <td>${exerciseMetricCell(point.rolling_median_kg, " kg")}</td><td>${esc(point.n_window)}</td></tr>`).join("");
  const degraded = data.degraded || [];
  target.innerHTML = `<div class="cards compact-cards">
    <div class="card"><div class="label">Best eligible</div><div class="value">${summary.best ? fmt(summary.best.kg) + " kg" : "unknown"}</div><div class="sub">${esc(summary.best && summary.best.date || "no eligible observation")}</div></div>
    <div class="card"><div class="label">Latest eligible</div><div class="value">${summary.latest ? fmt(summary.latest.kg) + " kg" : "unknown"}</div><div class="sub">${esc(summary.latest && summary.latest.date || "no eligible observation")}</div></div>
    <div class="card"><div class="label">Eligible observations</div><div class="value">${Number(summary.n || 0)}</div><div class="sub">${esc(summary.status || "unavailable")}</div></div></div>` +
    (points.length ? performanceSvg(points, exerciseId + " eligible e1RM") : "<p class='empty'>No eligible e1RM observations in this range.</p>") +
    (rows ? `<details class="exercise-data-table"><summary>Exact eligible daily observations (${points.length})</summary>
      <div class="table-scroll"><table><thead><tr><th>Date</th><th>Raw e1RM</th><th>Trailing median</th><th>Window n</th></tr></thead><tbody>${rows}</tbody></table></div></details>` : "") +
    ((data.breaks || []).length ? `<p class="muted">Series breaks: ${data.breaks.map((item) => esc(item.date + " — " + item.reason)).join("; ")}</p>` : "") +
    (degraded.length ? `<details class="exercise-data-table"><summary>Degraded observations excluded from the eligible trend (${degraded.length})</summary>
      <div class="table-scroll"><table><thead><tr><th>Date</th><th>e1RM</th><th>Quality</th></tr></thead><tbody>${degraded.map((point) => `<tr><td>${esc(point.date)}</td><td>${fmt(point.kg)} kg</td><td>${esc(point.quality)}</td></tr>`).join("")}</tbody></table></div></details>` : "") +
    `<p class="muted">${esc(data.basis || "raw_formula_epley_rir")} · decay/calibration not applied · equipment changes are not stored.</p>`;
}

function renderExerciseHistoryRecords() {
  const state = exerciseHistoryState;
  const host = $("#exercise-detail-records");
  const more = $("#exercise-history-more");
  const pageStatus = $("#exercise-history-page-status");
  if (!state || !host) return;
  if (!state.sessions.length) {
    host.innerHTML = "<p class='empty'>No completed working-set records in this selected date range.</p>";
  } else {
    host.innerHTML = state.sessions.map((session) => {
      const sets = (session.sets || []).map((set) => `<tr><td>${esc(set.set_index)}</td>
        <td>${exerciseMetricCell(set.load_kg, " kg")} · ${esc(set.load_basis || "unspecified basis")}</td>
        <td>${exerciseMetricCell(set.reps, " " + (set.reps_unit || "unit"))}</td>
        <td>${exerciseMetricCell(set.rir, " RIR")}</td>
        <td>${exerciseMetricCell(set.tonnage_kg, " kg")}</td></tr>`).join("");
      return `<details class="exercise-session-record"><summary>${esc(session.occurred_on)} · ${esc(session.session_type || "session")} · ${(session.sets || []).length} working sets · <code>${esc(session.session_id)}</code></summary>
        <div class="table-scroll"><table><thead><tr><th>Set</th><th>Recorded load</th><th>Recorded reps/unit</th><th>RIR</th><th>Stored physical tonnage</th></tr></thead><tbody>${sets}</tbody></table></div></details>`;
    }).join("");
  }
  if (more) {
    more.hidden = !state.hasMore;
    more.disabled = exerciseHistoryLoading;
    more.textContent = exerciseHistoryLoading ? "Loading…" : "Load 50 older sessions";
  }
  if (pageStatus) pageStatus.textContent = state.total === 0 ? "0 sessions in selected range."
    : `Showing ${state.sessions.length} of ${state.total} sessions. Analytics above cover the complete selected date range.`;
}

function compareExerciseSessions(a, b) {
  const dateOrder = String(b.occurred_on).localeCompare(String(a.occurred_on));
  return dateOrder || String(b.session_id).localeCompare(String(a.session_id));
}

async function loadExerciseHistoryPage(generation) {
  const state = exerciseHistoryState;
  if (!state || generation !== exerciseTrendsGeneration || exerciseHistoryLoading) return;
  exerciseHistoryLoading = true;
  const more = $("#exercise-history-more");
  if (more) more.disabled = true;
  const status = $("#exercise-history-status");
  if (status) status.textContent = `Loading session records ${state.offset + 1}–${Math.min(state.offset + EXERCISE_HISTORY_PAGE_SIZE, state.total || EXERCISE_HISTORY_PAGE_SIZE)}…`;
  try {
    const firstPage = state.offset === 0;
    const page = await api(exerciseHistoryUrl(state.exerciseId, state, state.offset, firstPage));
    if (generation !== exerciseTrendsGeneration || window.__exerciseDetailsId !== state.exerciseId) return;
    if (!Array.isArray(page.sessions) || !Number.isInteger(Number(page.total)) || typeof page.has_more !== "boolean") {
      throw new Error("Exercise-history API returned an invalid pagination response.");
    }
    if (page.start !== state.start && (page.start || state.start) || page.end !== state.end && (page.end || state.end)) {
      throw new Error("Exercise-history API returned a different date range; retry the selection.");
    }
    if (state.total != null && Number(page.total) !== state.total) {
      throw new Error("History changed while pages were loading; reapply the date range to retry safely.");
    }
    if (firstPage) {
      if (!page.analytics || Number(page.analytics.session_count) !== Number(page.total)) {
        throw new Error("Complete-range analytics are unavailable or inconsistent with the session count.");
      }
      state.analytics = page.analytics;
      state.total = Number(page.total);
      state.includedExercises = page.included_exercises || [];
      $("#exercise-detail-dose").innerHTML = exerciseHistoryAnalyticsCharts(
        state.analytics, state.display
      );
      const equivalents = state.includedExercises.filter((item) => item.id !== state.exerciseId);
      if (equivalents.length) $("#exercise-detail-dose").insertAdjacentHTML("beforeend",
        `<p class="muted">Declared history equivalents included: ${equivalents.map((item) => esc(item.display || item.id)).join(", ")}.</p>`);
    }
    if (page.sessions.length === 0 && page.has_more) {
      throw new Error("The API returned an empty page while reporting more history. Results are incomplete; retry or narrow the range.");
    }
    if (state.offset + page.sessions.length > Number(page.total) ||
        page.has_more !== (state.offset + page.sessions.length < Number(page.total))) {
      throw new Error("Exercise-history pagination totals are inconsistent; results are marked incomplete.");
    }
    const seen = new Set(state.sessions.map((session) => session.session_id));
    if (page.sessions.some((session) => !session.session_id || seen.has(session.session_id))) {
      throw new Error("Duplicate or missing session id detected across history pages; refresh the range before using the table.");
    }
    const combined = state.sessions.concat(page.sessions);
    if (combined.some((session, index) => index > 0 && compareExerciseSessions(combined[index - 1], session) > 0)) {
      throw new Error("History page ordering changed between requests; refresh the selected range.");
    }
    state.sessions = combined;
    state.offset += page.sessions.length;
    state.hasMore = page.has_more;
    state.complete = !page.has_more && state.sessions.length === state.total;
    renderExerciseHistoryRecords();
    if (status) status.textContent = state.complete
      ? `Complete: ${state.total} session records and all date-range analytics loaded.`
      : `Loaded ${state.sessions.length} of ${state.total} session records; complete-range charts are already loaded.`;
  } catch (error) {
    if (generation !== exerciseTrendsGeneration) return;
    if (status) status.textContent = "History records incomplete: " + error.message;
    const pageStatus = $("#exercise-history-page-status");
    if (pageStatus) pageStatus.textContent = "Retry loading this page or reapply the date range. Complete-range analytics are separate.";
  } finally {
    if (generation === exerciseTrendsGeneration) {
      exerciseHistoryLoading = false;
      renderExerciseHistoryRecords();
    }
  }
}

function openExerciseDetails(row) {
  const isNew = !row;
  const props = row ? JSON.parse(JSON.stringify(row.props || {})) : {
    display: "", log_names: [], pattern: "", primary_muscles: [],
    primary_compound: false, loadable: true, bodyweight_type: false,
    time_based: false, e1rm_applicable: true,
  };
  window.__exerciseDetailsId = row ? row.id : "";
  window.__exerciseDetailsRow = row || null;
  exerciseHistoryState = null;
  exerciseHistoryLoading = false;
  exerciseTrendsGeneration++;
  $("#exercise-details-title").textContent = row
    ? row.id + " · " + (row.display || "") : "Add exercise";
  $("#exercise-detail-profile").textContent = row
    ? `${row.display || row.id} · immutable id ${row.id} · source ${row.source || "unknown"} · pattern ${row.pattern || props.pattern || "unspecified"} · primary muscles ${(props.primary_muscles || []).join(", ") || "unspecified"}`
    : "Save the new exercise before loading historical analytics.";
  $("#exercise-detail-id").value = row ? row.id : "";
  $("#exercise-detail-id").readOnly = !isNew;
  $("#exercise-detail-display").value = props.display || (row && row.display) || "";
  setPatternSelect("#exercise-detail-pattern", props.pattern || (row && row.pattern) || "");
  setVbtFamily("#exercise-detail-vbt", "#exercise-detail-vbt-new",
    "#exercise-detail-vbt-new-wrap", props.vbt_family || "");
  $("#exercise-detail-spinal-cost").value = props.spinal_cost == null ? "" : props.spinal_cost;
  $("#exercise-detail-log-names").value = (props.log_names || []).join("\n");
  setMuscleChoices("#exercise-detail-muscles", props.primary_muscles || []);
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
  $("#exercise-details-msg").textContent = row ? "source: " + row.source : "New local override entity";
  const demands = (row && row.demands) || { rated: 0, dimensions: {} };
  const meta = window.__exerciseCatalog?.demand_catalogue || {};
  const scope = (meta.in_scope || []).length || 4;
  $("#exercise-detail-demands").innerHTML = Object.entries(demands.dimensions)
    .map(([dimension, claim]) => `<tr><td><code>${esc(dimension)}</code></td><td>${esc(claim.level)}</td><td>${esc(claim.confidence || "—")}</td><td class="muted">${esc(claim.reason || "—")}</td><td class="muted">${esc((claim.evidence || []).join(", ") || "—")}</td></tr>`)
    .join("");
  $("#exercise-detail-demands-note").textContent = `${demands.rated}/${scope} in-scope dimensions rated · catalogue ${meta.digest || "none"} · reviewed ${meta.reviewed_on || "never"}` + (meta.overlay ? " · local overlay active" : "");
  const demandDimensionSelect = $("#exercise-demand-dimension");
  // Keep the dimension being edited across the re-render that follows a save, but never carry
  // one exercise's dimension over to another.
  const sameExercise = demandDimensionSelect.dataset.exerciseId === (row ? row.id : "");
  const previousDimension = sameExercise ? demandDimensionSelect.value : "";
  demandDimensionSelect.innerHTML = Object.keys(demands.dimensions)
    .map((dimension) => `<option>${esc(dimension)}</option>`).join("");
  if (previousDimension && previousDimension in demands.dimensions) {
    demandDimensionSelect.value = previousDimension;
  }
  demandDimensionSelect.dataset.exerciseId = row ? row.id : "";
  // Only ids the reviewed file already defines can be cited, so the form offers exactly those.
  // A <select multiple> renders as "0 items" on iOS Safari whatever is ticked, so evidence is a
  // checkbox list (the same .choice-list pattern the muscle picker uses).
  const evidence = meta.evidence || [];
  const evidenceBox = $("#exercise-demand-evidence");
  evidenceBox.innerHTML = evidence.length
    ? evidence.map((entry) => `<label class="choice" title="${esc(entry.citation)}"><input type="checkbox" value="${esc(entry.id)}"${isNew ? " disabled" : ""}> <span><code>${esc(entry.id)}</code> — ${esc(entry.citation)}</span></label>`).join("")
    : '<span class="muted">No evidence ids in the reviewed catalogue.</span>';
  // Show the saved claim, including its evidence, instead of an empty form: a saved citation
  // that is not preselected reads as lost and would be dropped by the next provisional edit.
  evidenceBox._claims = demands.dimensions || {};
  syncDemandForm();
  $("#exercise-demand-msg").textContent = isNew
    ? "Save the exercise before adding a local demand rating."
    : "Writes config/exercises/demands.local.yaml; the reviewed file is untouched.";
  $("#exercise-demand-save").disabled = isNew;
  $("#exercise-demand-clear").disabled = isNew;
  $("#exercise-demand-dimension").disabled = isNew;
  const start = $("#exercise-history-start");
  const end = $("#exercise-history-end");
  start.value = exerciseDefaultHistoryStart();
  end.value = today();
  start.disabled = isNew;
  end.disabled = isNew;
  $("#exercise-history-range-form").querySelector("button[type='submit']").disabled = isNew;
  $("#exercise-history-all").disabled = isNew;
  $("#exercise-history-more").hidden = true;
  $("#exercise-history-page-status").textContent = "";
  $("#exercise-history-status").textContent = isNew ? "Save this exercise before viewing history." : "Ready to load the selected date range.";
  $("#exercise-detail-e1rm").innerHTML = row
    ? "<p class='empty'>Loading strength observations…</p>" : "<p class='empty'>Save the exercise before viewing its trend.</p>";
  $("#exercise-detail-dose").innerHTML = row
    ? "<p class='empty'>Loading complete-range analytics…</p>" : "<p class='empty'>Save the exercise before viewing analytics.</p>";
  $("#exercise-detail-records").innerHTML = "<p class='empty'>No historical records loaded.</p>";
  $("#exercise-details-dialog").showModal();
  if (row) loadExerciseTrends(row);
}

async function loadExerciseTrends(row) {
  const id = row.id;
  const generation = ++exerciseTrendsGeneration;
  const start = $("#exercise-history-start").value || "";
  const end = $("#exercise-history-end").value || "";
  exerciseHistoryState = {exerciseId: id, display: row.display || id, start: start, end: end,
    offset: 0, total: null, sessions: [], hasMore: false, complete: false, analytics: null};
  $("#exercise-trend-e1rm").innerHTML = "<p class='empty'>Loading eligible strength observations…</p>";
  $("#exercise-detail-dose").innerHTML = "<p class='empty'>Loading complete-range Python analytics…</p>";
  $("#exercise-detail-records").innerHTML = "<p class='empty'>Loading session records…</p>";
  $("#exercise-history-status").textContent = "Loading selected date range…";
  try {
    if (row.props?.e1rm_applicable === false) {
      $("#exercise-trend-e1rm").innerHTML = "<p class='empty'>This exercise is not marked e1RM-applicable; eligible strength estimates are unavailable.</p>";
    } else {
      const e1rm = await api(exerciseE1rmUrl(id, start, end));
      if (generation !== exerciseTrendsGeneration || window.__exerciseDetailsId !== id) return;
      renderExerciseE1rmHistory(e1rm, id);
    }
  } catch (error) {
    if (generation === exerciseTrendsGeneration) $("#exercise-trend-e1rm").innerHTML = `<p class='warnbox'>Strength history unavailable: ${esc(error.message)}</p>`;
  }
  if (generation === exerciseTrendsGeneration) await loadExerciseHistoryPage(generation);
}

function saveExerciseDetails(event) {
  event.preventDefault();
  const id = $("#exercise-detail-id").value.trim();
  window.__exerciseDetailsId = id;
  if (!id) return;
  let extra;
  try {
    extra = JSON.parse($("#exercise-detail-extra").value.trim() || "{}");
  } catch (error) {
    $("#exercise-details-msg").textContent = "Additional properties must be valid JSON.";
    return;
  }
  if (!extra || Array.isArray(extra) || typeof extra !== "object") {
    $("#exercise-details-msg").textContent = "Additional properties must be a JSON object.";
    return;
  }
  const props = Object.assign({}, extra, {
    display: $("#exercise-detail-display").value.trim(),
    log_names: $("#exercise-detail-log-names").value.split("\n").filter((line) => line.length > 0),
    pattern: $("#exercise-detail-pattern").value.trim(),
    primary_muscles: selectedMusclesIn("#exercise-detail-muscles"),
    primary_compound: $("#exercise-detail-compound").checked,
    loadable: $("#exercise-detail-loadable").checked,
    bodyweight_type: $("#exercise-detail-bodyweight").checked,
    time_based: $("#exercise-detail-timed").checked,
    e1rm_applicable: $("#exercise-detail-e1rm").checked,
    main_lift: $("#exercise-detail-main").checked,
    high_fatigue_spinal: $("#exercise-detail-spinal").checked,
    erector_family: $("#exercise-detail-erector").checked,
    direct_erector: $("#exercise-detail-direct-erector").checked,
  });
  props.spinal_cost = $("#exercise-detail-spinal-cost").value === ""
    ? null : Number($("#exercise-detail-spinal-cost").value);
  const detailVbt = readVbtFamily("#exercise-detail-vbt", "#exercise-detail-vbt-new");
  if ($("#exercise-detail-vbt").value === VBT_NEW_VALUE && !detailVbt) {
    $("#exercise-details-msg").textContent = "Enter a name for the new VBT family, or choose an existing one.";
    $("#exercise-detail-vbt-new").focus();
    return;
  }
  props.vbt_family = detailVbt || null;
  if ($("#exercise-detail-spinal-cost").value !== "") {
    props.spinal_cost = Number($("#exercise-detail-spinal-cost").value);
  } else {
    props.spinal_cost = null;
  }
  // day_roles are derived from the session templates by the server; never send or
  // reconstruct them here.
  delete props.day_roles;
  $("#exercise-details-msg").textContent = "Saving…";
  api("/api/exercises", { method: "POST", body: JSON.stringify({ id, props }) })
    .then((data) => {
      window.__exerciseCatalog = data;
      $("#exercise-details-dialog").close();
      notify("Exercise saved.");
      loadExerciseCatalog();
      loadExercises();
    })
    .catch((error) => applyFieldErrors(error, $("#exercise-details-msg"), {
      id: "#exercise-detail-id",
      display: "#exercise-detail-display",
      pattern: "#exercise-detail-pattern",
      primary_muscles: "#exercise-detail-muscles input",
      log_names: "#exercise-detail-log-names",
      vbt_family: "#exercise-detail-vbt",
      spinal_cost: "#exercise-detail-spinal-cost",
      props: "#exercise-detail-extra",
    }));
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
    const scope = (window.__exerciseCatalog?.demand_catalogue?.in_scope || []).length || 4;
    const demands = row.demands
      ? `<span title="${esc(Object.entries(row.demands.dimensions)
            .map(([dim, claim]) => dim + ": " + claim.level).join(", "))}">${row.demands.rated}/${scope}</span>`
      : "—";
    return `<tr>
      <td><strong>${esc(row.display)}</strong><div class="muted"><code>${esc(row.id)}</code>
        · ${esc(row.source)}</div></td>
      <td><code>${esc(row.pattern || "—")}</code></td>
      <td>${(p.primary_muscles || []).map((m) => `<span class="pill">${esc(m)}</span>`).join("") || "—"}</td>
      <td>${flags || "—"}</td>
      <td>${names || "—"}</td>
      <td>${demands}</td>
      <td><div class="row-actions">
        <button class="ghost" data-details-exercise="${esc(row.id)}">Open</button>
        <button class="ghost" data-e1rm-exercise="${esc(row.id)}" title="Append an e1RM override for this lift">e1RM</button>
        <details><summary class="muted">all fields</summary>
        <pre class="props">${esc(JSON.stringify(p, null, 2))}</pre></details>
      </div></td>
    </tr>`;
  }).join("");
  $("#exercise-catalog").innerHTML = `<div class="table-scroll"><table class="exercise-table">
    <thead><tr><th>Exercise</th><th>Pattern</th><th>Primary muscles</th><th>Flags</th>
    <th>Log names</th><th>Demands</th><th></th></tr></thead><tbody>${body}</tbody></table></div>`;
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

function demandClaims() {
  return $("#exercise-demand-evidence")?._claims || {};
}

function syncDemandEvidenceCount() {
  const box = $("#exercise-demand-evidence");
  const count = box
    ? box.querySelectorAll('input[type="checkbox"]:checked').length : 0;
  const label = $("#exercise-demand-evidence-count");
  if (label) label.textContent = count + " selected";
}

function syncDemandForm() {
  const dimension = $("#exercise-demand-dimension").value;
  const claim = demandClaims()[dimension] || {};
  $("#exercise-demand-level").value = claim.level || "unknown";
  $("#exercise-demand-confidence").value = claim.confidence || "provisional";
  $("#exercise-demand-reason").value = claim.reason || "";
  const ids = new Set(claim.evidence || []);
  const box = $("#exercise-demand-evidence");
  if (box) {
    box.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.checked = ids.has(input.value);
    });
  }
  syncDemandEvidenceCount();
}

async function saveDemandRating(clear) {
  const exerciseId = window.__exerciseDetailsId;
  if (!exerciseId) return;
  const payload = {
    exercise_id: exerciseId,
    dimension: $("#exercise-demand-dimension").value,
    clear: !!clear,
    level: $("#exercise-demand-level").value,
    confidence: $("#exercise-demand-confidence").value,
    reason: $("#exercise-demand-reason").value,
    evidence: [...$("#exercise-demand-evidence").querySelectorAll('input[type="checkbox"]:checked')]
      .map((input) => input.value),
  };
  try {
    const data = await api("/api/exercises/demands", {
      method: "POST", body: JSON.stringify(payload),
    });
    const catalogue = window.__exerciseCatalog;
    if (catalogue) {
      catalogue.demand_catalogue.digest = data.digest;
      catalogue.demand_catalogue.overlay = data.overlay;
      const row = catalogue.entities.find((item) => item.id === exerciseId);
      if (row) {
        row.demands = data.demands;
        openExerciseDetails(row);
      }
    }
    loadExerciseCatalog();
    $("#exercise-demand-msg").textContent =
      (clear ? "local rating cleared · " : "rating saved locally · ")
      + "catalogue " + data.digest;
  } catch (error) {
    $("#exercise-demand-msg").innerHTML = `<span class="warnbox">${esc(error.message)}</span>`;
  }
}

$("#exercise-demand-save").addEventListener("click", () => saveDemandRating(false));
$("#exercise-demand-clear").addEventListener("click", () => saveDemandRating(true));
$("#exercise-demand-dimension").addEventListener("change", syncDemandForm);
$("#exercise-demand-evidence").addEventListener("change", syncDemandEvidenceCount);

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
    if (typeof populateThrottlePatterns === "function") populateThrottlePatterns(data.patterns);
    renderExerciseCatalog();
    loadTemplateStatus().catch(() => {});
  } catch (error) {
    $("#exercise-catalog").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

$("#exercise-detail-vbt").addEventListener("change", function () {
  syncVbtFamily("#exercise-detail-vbt", "#exercise-detail-vbt-new", "#exercise-detail-vbt-new-wrap");
});
$("#exercise-history-range-form").addEventListener("submit", function (event) {
  event.preventDefault();
  const row = window.__exerciseDetailsRow;
  if (row) loadExerciseTrends(row);
});
$("#exercise-history-all").addEventListener("click", function () {
  $("#exercise-history-start").value = "";
  $("#exercise-history-end").value = "";
  const row = window.__exerciseDetailsRow;
  if (row) loadExerciseTrends(row);
});
$("#exercise-history-more").addEventListener("click", function () {
  if (!exerciseHistoryState || !exerciseHistoryState.hasMore) return;
  loadExerciseHistoryPage(exerciseTrendsGeneration);
});
$("#exercise-search").addEventListener("input", renderExerciseCatalog);
$("#exercise-filter").addEventListener("change", renderExerciseCatalog);
$("#exercise-refresh").addEventListener("click", loadExerciseCatalog);
$("#exercise-add").addEventListener("click", () => openExerciseDetails(null));
