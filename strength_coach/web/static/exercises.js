/* Exercise catalogue, editor and e1RM override feature module. */
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
      <td><button class="ghost" data-details-exercise="${esc(row.id)}">Details</button>
        <button class="ghost" data-edit-exercise="${esc(row.id)}">Edit</button>
        <button class="ghost" data-e1rm-exercise="${esc(row.id)}" title="Append an e1RM override for this lift">e1RM</button>
        <details><summary class="muted">all fields</summary>
        <pre class="props">${esc(JSON.stringify(p, null, 2))}</pre></details></td>
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
