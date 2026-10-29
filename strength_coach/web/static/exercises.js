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
  setPatternSelect("#exercise-pattern", props.pattern || "");
  setVbtFamily("#exercise-vbt", "#exercise-vbt-new", "#exercise-vbt-new-wrap", props.vbt_family || "");
  $("#exercise-log-names").value = (props.log_names || []).join("\n");
  setMuscleChoices("#exercise-muscles", props.primary_muscles || []);
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
  setPatternSelect("#exercise-detail-pattern", props.pattern || row.pattern || "");
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
  $("#exercise-details-msg").textContent = "source: " + row.source;
  const demands = row.demands || { rated: 0, dimensions: {} };
  const meta = window.__exerciseCatalog?.demand_catalogue || {};
  const scope = (meta.in_scope || []).length || 4;
  $("#exercise-detail-demands").innerHTML = Object.entries(demands.dimensions)
    .map(([dimension, claim]) => `<tr>
      <td><code>${esc(dimension)}</code></td>
      <td>${esc(claim.level)}</td>
      <td>${esc(claim.confidence || "—")}</td>
      <td class="muted">${esc(claim.reason || "—")}</td></tr>`)
    .join("");
  $("#exercise-detail-demands-note").textContent =
    `${demands.rated}/${scope} in-scope dimensions rated · catalogue ${meta.digest || "none"}`
    + ` · reviewed ${meta.reviewed_on || "never"}`
    + (meta.overlay ? " · local overlay active" : "");
  $("#exercise-demand-dimension").innerHTML = Object.keys(demands.dimensions)
    .map((dimension) => `<option>${esc(dimension)}</option>`).join("");
  $("#exercise-demand-msg").textContent =
    "Writes config/exercises/demands.local.yaml; the reviewed file is untouched.";
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
      loadExerciseCatalog();
      loadExercises();
    })
    .catch((error) => applyFieldErrors(error, $("#exercise-details-msg"), {
      id: "#exercise-id",
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
        <button class="ghost" data-details-exercise="${esc(row.id)}">Details</button>
        <button class="ghost" data-edit-exercise="${esc(row.id)}">Edit</button>
        <button class="ghost" data-e1rm-exercise="${esc(row.id)}" title="Append an e1RM override for this lift">e1RM</button>
        <details><summary class="muted">all fields</summary>
        <pre class="props">${esc(JSON.stringify(p, null, 2))}</pre></details>
      </div></td>
    </tr>`;
  }).join("");
  $("#exercise-catalog").innerHTML = `<div class="table-scroll"><table class="exercise-table">
    <thead><tr><th>Exercise</th><th>Pattern</th><th>Primary muscles</th><th>Flags</th>
    <th>Log names</th><th>Demands</th><th></th></tr></thead><tbody>${body}</tbody></table></div>`;
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
    loadTemplateStatus().catch(() => {});
  } catch (error) {
    $("#exercise-catalog").innerHTML = `<p class="warnbox">${esc(error.message)}</p>`;
  }
}

$("#exercise-vbt").addEventListener("change", function () {
  syncVbtFamily("#exercise-vbt", "#exercise-vbt-new", "#exercise-vbt-new-wrap");
});
$("#exercise-detail-vbt").addEventListener("change", function () {
  syncVbtFamily("#exercise-detail-vbt", "#exercise-detail-vbt-new", "#exercise-detail-vbt-new-wrap");
});
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
  const vbt = readVbtFamily("#exercise-vbt", "#exercise-vbt-new");
  if ($("#exercise-vbt").value === VBT_NEW_VALUE && !vbt) {
    $("#exercise-msg").textContent = "Enter a name for the new VBT family, or choose an existing one.";
    $("#exercise-vbt-new").focus();
    return;
  }
  const props = Object.assign({}, extra, {
    display: $("#exercise-display").value.trim(),
    log_names: $("#exercise-log-names").value.split("\n").filter((line) => line.length > 0),
    pattern: $("#exercise-pattern").value.trim(),
    primary_muscles: selectedMusclesIn("#exercise-muscles"),
    primary_compound: $("#exercise-compound").checked,
    loadable: $("#exercise-loadable").checked,
    bodyweight_type: $("#exercise-bodyweight").checked,
    time_based: $("#exercise-timed").checked,
    e1rm_applicable: $("#exercise-e1rm").checked,
    vbt_family: vbt || null,
    main_lift: $("#exercise-main").checked,
    high_fatigue_spinal: $("#exercise-spinal").checked,
    erector_family: $("#exercise-erector").checked,
    direct_erector: $("#exercise-direct-erector").checked,
  });
  $("#exercise-msg").textContent = "Saving…";
  try {
    const data = await api("/api/exercises", { method: "POST", body: JSON.stringify({ id, props }) });
    window.__exerciseCatalog = data;
    $("#exercise-editor").hidden = true;
    notify("Exercise saved.");
    await loadExerciseCatalog();
    await loadExercises();
  } catch (error) {
    applyFieldErrors(error, $("#exercise-msg"), {
      id: "#exercise-id",
      display: "#exercise-display",
      pattern: "#exercise-pattern",
      primary_muscles: "#exercise-muscles input",
      log_names: "#exercise-log-names",
      vbt_family: "#exercise-vbt",
      spinal_cost: "#exercise-extra",
      props: "#exercise-extra",
    });
  }
});
