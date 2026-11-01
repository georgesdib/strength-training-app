/* Settings panels: LLM, profile, volume, modalities and monitoring inventory. */

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
        <span class="muted">Session target comes from the Athlete profile (fallback 90 min); this panel does not set a competing value.</span>
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
