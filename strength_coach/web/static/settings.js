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

function renderIosSettings(data) {
  window.__iosSettings = data || {};
  const effective = data.effective || {};
  const ranges = data.ranges || {};
  $("#settings-ios-mutations").checked = !!effective.mutations_enabled;
  $("#settings-ios-issued-ttl").value = effective.issued_plan_ttl_seconds ?? "";
  $("#settings-ios-request-ttl").value = effective.plan_request_ttl_seconds ?? "";
  $("#settings-ios-receipt-days").value = effective.receipt_retention_days ?? "";
  [["#settings-ios-issued-ttl", "issued_plan_ttl_seconds"],
   ["#settings-ios-request-ttl", "plan_request_ttl_seconds"],
   ["#settings-ios-receipt-days", "receipt_retention_days"]].forEach(([selector, key]) => {
    const node = $(selector);
    const range = ranges[key] || {};
    if (range.min != null) node.min = String(range.min);
    if (range.max != null) node.max = String(range.max);
  });
  const status = $("#settings-ios-status");
  status.textContent = effective.mutations_enabled ? "mutations on" : "mutations off";
  status.className = "badge " + (effective.mutations_enabled ? "" : "warn");
  $("#settings-ios-source").textContent = "Effective values below · source: " +
    (data.source || "unknown") + " · reload: " + (data.reload || "per request") +
    (data.restart_required ? " · restart required" : " · no restart required");
}

async function saveIosSettings(event) {
  event.preventDefault();
  const msg = $("#settings-ios-msg");
  const values = {
    mutations_enabled: $("#settings-ios-mutations").checked,
    issued_plan_ttl_seconds: Number($("#settings-ios-issued-ttl").value),
    plan_request_ttl_seconds: Number($("#settings-ios-request-ttl").value),
    receipt_retention_days: Number($("#settings-ios-receipt-days").value),
  };
  const ranges = window.__iosSettings?.ranges || {};
  for (const [key, selector] of [
    ["issued_plan_ttl_seconds", "#settings-ios-issued-ttl"],
    ["plan_request_ttl_seconds", "#settings-ios-request-ttl"],
    ["receipt_retention_days", "#settings-ios-receipt-days"],
  ]) {
    const range = ranges[key] || {};
    const value = values[key];
    if (!Number.isInteger(value) || (range.min != null && value < range.min) ||
        (range.max != null && value > range.max)) {
      applyFieldErrors(new Error("Enter a whole number within the shown range."), msg, {
        [key]: selector,
      });
      return;
    }
  }
  msg.textContent = "Saving…";
  try {
    const data = await api("/api/settings/ios", {
      method: "POST",
      body: JSON.stringify({ values }),
    });
    renderIosSettings(data);
    msg.textContent = "Saved. Effective immediately; no restart required.";
    notify("iOS settings saved.");
  } catch (error) {
    applyFieldErrors(error, msg, {
      mutations_enabled: "#settings-ios-mutations",
      issued_plan_ttl_seconds: "#settings-ios-issued-ttl",
      plan_request_ttl_seconds: "#settings-ios-request-ttl",
      receipt_retention_days: "#settings-ios-receipt-days",
      settings: "#settings-ios-form",
    });
  }
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

/* --- resolver ---------------------------------------------------------- */
function resolverSettingId(key) {
  return "resolver-" + String(key).replace(/[^a-zA-Z0-9_-]/g, "-");
}

function resolverControl(setting, id) {
  if (setting.kind === "bool") {
    return '<input type="checkbox" data-resolver-key="' + esc(setting.key) + '" id="' + id + '">';
  }
  if (setting.kind === "int" || setting.kind === "float") {
    const step = setting.kind === "int" ? "1" : "0.01";
    const min = setting.minimum == null ? "" : ' min="' + setting.minimum + '"';
    const max = setting.maximum == null ? "" : ' max="' + setting.maximum + '"';
    return '<input type="number" step="' + step + '"' + min + max +
      ' data-resolver-key="' + esc(setting.key) + '" id="' + id + '">';
  }
  if (setting.kind === "table" || setting.kind === "list") {
    return '<textarea rows="3" spellcheck="false" data-resolver-key="' + esc(setting.key) +
      '" id="' + id + '"></textarea>';
  }
  if ((setting.choices || []).length) {
    return '<select data-resolver-key="' + esc(setting.key) + '" id="' + id + '">' +
      setting.choices.map((choice) => '<option value="' + esc(choice) + '">' +
        esc(choice) + "</option>").join("") + "</select>";
  }
  return '<input type="text" data-resolver-key="' + esc(setting.key) + '" id="' + id + '">';
}

function renderResolverSettings(registry, profile) {
  window.__resolverRegistry = (registry || []).filter(
    (setting) => setting.group === "Resolver"
  );
  window.__resolverProfile = profile || {};
  const box = $("#settings-resolver-fields");
  if (!box) return;
  const resolved = window.__resolverProfile.resolved || {};
  const overrides = window.__resolverProfile.overrides || {};
  box.innerHTML = window.__resolverRegistry.map((setting) => {
    const value = Object.prototype.hasOwnProperty.call(overrides, setting.key)
      ? overrides[setting.key] : resolved[setting.key];
    const id = resolverSettingId(setting.key);
    const badge = setting.classification === "guarded_safety"
      ? ' <span class="badge warn">guarded</span>' : "";
    return '<label class="grow">' + esc(setting.label) + badge +
      resolverControl(setting, id) +
      '<span class="muted">' + esc(setting.key) + " · " + esc(setting.source) +
      "</span></label>";
  }).join("");
  window.__resolverRegistry.forEach((setting) => {
    const node = document.getElementById(resolverSettingId(setting.key));
    if (!node) return;
    const value = Object.prototype.hasOwnProperty.call(overrides, setting.key)
      ? overrides[setting.key] : resolved[setting.key];
    if (setting.kind === "bool") node.checked = !!value;
    else if (setting.kind === "table" || setting.kind === "list") {
      node.value = JSON.stringify(value ?? (setting.kind === "list" ? [] : {}), null, 2);
    } else node.value = value ?? "";
    node.dataset.original = JSON.stringify(value ?? null);
    node.dataset.classification = setting.classification;
    node.addEventListener("input", updateResolverDiff);
    node.addEventListener("change", updateResolverDiff);
  });
  const previewDate = $("#settings-resolver-preview-date");
  if (previewDate && !previewDate.value) previewDate.value = today();
  const status = $("#resolver-status");
  if (status) {
    const enabled = !!resolved["resolver.enabled"];
    status.textContent = enabled ? "enabled" : "off";
    status.className = "badge " + (enabled ? "" : "warn");
  }
  const warning = $("#settings-resolver-warning");
  if (warning) warning.hidden = !resolved["resolver.enabled"];
  updateResolverDiff();
}

function resolverNodeValue(node, setting) {
  if (setting.kind === "bool") return node.checked;
  if (setting.kind === "int") return Number(node.value);
  if (setting.kind === "float") return Number(node.value);
  if (setting.kind === "table" || setting.kind === "list") {
    try { return JSON.parse(node.value || (setting.kind === "list" ? "[]" : "{}")); }
    catch (error) { throw new Error(setting.key + ": invalid JSON — " + error.message); }
  }
  return node.value;
}

function resolverChanges() {
  const changes = [];
  (window.__resolverRegistry || []).forEach((setting) => {
    const node = document.getElementById(resolverSettingId(setting.key));
    if (!node) return;
    const value = resolverNodeValue(node, setting);
    const original = JSON.parse(node.dataset.original || "null");
    if (JSON.stringify(value) !== JSON.stringify(original)) {
      changes.push({ setting, value, original });
    }
  });
  return changes;
}

function updateResolverDiff() {
  const box = $("#settings-resolver-diff");
  if (!box) return;
  try {
    const changes = resolverChanges();
    box.innerHTML = changes.length
      ? changes.map(({ setting, value, original }) =>
          "<div><code>" + esc(setting.key) + "</code>: " +
          esc(JSON.stringify(original)) + " → " + esc(JSON.stringify(value)) +
          "</div>").join("")
      : "No changes.";
    const warning = $("#settings-resolver-warning");
    const enabledNode = document.getElementById(resolverSettingId("resolver.enabled"));
    if (warning) warning.hidden = !(enabledNode && enabledNode.checked);
    const status = $("#resolver-status");
    if (status && enabledNode) {
      status.textContent = enabledNode.checked ? "enabled" : "off";
      status.className = "badge " + (enabledNode.checked ? "" : "warn");
    }
  } catch (error) {
    box.textContent = error.message;
  }
}

async function saveResolverDraft() {
  const msg = $("#settings-resolver-msg");
  try {
    const changes = resolverChanges();
    if (!changes.length) {
      msg.textContent = "No changes to save.";
      return;
    }
    const set = {};
    const guarded = [];
    changes.forEach(({ setting, value, original }) => {
      set[setting.key] = value;
      if (setting.classification === "guarded_safety") guarded.push(setting.key);
      if (setting.key === "resolver.enabled" && value && !original &&
          !$("#settings-resolver-enable-confirm").checked) {
        throw new Error("Tick 'Confirm resolver enable' before enabling resolver mode.");
      }
    });
    const reason = $("#settings-resolver-reason").value.trim();
    if (guarded.length) {
      if (!$("#settings-resolver-guard").checked ||
          $("#settings-resolver-guard-text").value.trim() !== "SPINAL" || !reason) {
        throw new Error("Guarded resolver changes need the confirmation tick, SPINAL and a reason.");
      }
    }
    await api("/api/settings/profile", {
      method: "POST",
      body: JSON.stringify({
        set,
        reason: reason || null,
        guard_confirmed: $("#settings-resolver-guard").checked,
        resolver_enable_confirmed: $("#settings-resolver-enable-confirm").checked,
      }),
    });
    msg.textContent = "Saved a new profile version.";
    $("#settings-resolver-enable-confirm").checked = false;
    $("#settings-resolver-guard").checked = false;
    $("#settings-resolver-guard-text").value = "";
    $("#settings-resolver-reason").value = "";
    await loadSettings();
  } catch (error) {
    msg.textContent = error.message;
    applyFieldErrors(error, msg, (field) => {
      if (field === "guard_confirmed") return "#settings-resolver-guard";
      if (field === "reason") return "#settings-resolver-reason";
      if (field === "settings") return "#settings-resolver-fields";
      return "#" + resolverSettingId(field);
    });
  }
}

function renderResolverPolicy(policy) {
  window.__resolverPolicy = policy || {};
  const yaml = $("#settings-resolver-policy-yaml");
  if (yaml) yaml.value = policy?.yaml || "";
  const meta = $("#settings-resolver-policy-meta");
  if (meta) {
    meta.textContent = policy
      ? "path " + policy.path + " · digest " + String(policy.digest || "").slice(0, 12) +
        "… · backups " + (policy.backups || []).length + "/" + (policy.backup_keep || 20)
      : "Policy unavailable.";
  }
  const box = $("#settings-resolver-backups");
  if (box) {
    box.innerHTML = (policy?.backups || []).slice(0, 20).map((row) =>
      "<div><code>" + esc(row.name) + "</code> · " + esc(String(row.digest).slice(0, 12)) +
      "…</div>").join("") || "<span>No backups yet.</span>";
  }
}

async function saveResolverPolicy() {
  const msg = $("#settings-resolver-policy-msg");
  const text = $("#settings-resolver-policy-yaml").value;
  if (!text.trim()) {
    msg.textContent = "Policy YAML is empty.";
    return;
  }
  if (!window.confirm("Validate and save the resolver policy? The current file is backed up first.")) {
    return;
  }
  msg.textContent = "Validating…";
  try {
    const data = await api("/api/resolver/policy", {
      method: "POST", body: JSON.stringify({ yaml: text }),
    });
    renderResolverPolicy(data);
    msg.textContent = "Policy validated and saved.";
    notify("Resolver policy saved.");
  } catch (error) {
    msg.textContent = error.message;
  }
}

async function restoreResolverPolicy() {
  const msg = $("#settings-resolver-policy-msg");
  if (!window.confirm("Restore the latest resolver policy backup? The current file is backed up first.")) {
    return;
  }
  msg.textContent = "Restoring…";
  try {
    const data = await api("/api/resolver/policy/restore", { method: "POST", body: "{}" });
    renderResolverPolicy(data);
    const source = data.restored_from?.name || "the latest backup";
    const previous = data.pre_restore_backup?.name;
    msg.textContent = "Restored " + source +
      (previous ? "; previous policy saved as " + previous + "." : ".");
    notify("Resolver policy restored.");
  } catch (error) {
    msg.textContent = error.message;
  }
}

function resolverPreviewFormPayload() {
  const value = $("#settings-resolver-preview-top-set").value;
  return {
    date: $("#settings-resolver-preview-date").value,
    session_type: $("#settings-resolver-preview-session").value,
    top_set: value === "on" ? true : value === "off" ? false : null,
    allow_unknown_readiness: $("#settings-resolver-preview-allow-unknown").checked,
  };
}

function resolverPreviewChoicesHtml(data) {
  return (data.choices || []).map((choice) => {
    const alternatives = (choice.alternatives || []).length
      ? choice.alternatives.map((item) => "<code>" + esc(item) + "</code>").join(" ")
      : "<span class='muted'>none</span>";
    const suggestions = (choice.suggestions || []).length
      ? choice.suggestions.map((item) =>
          "<span class='badge warn'>" + esc(item) + "</span> " +
          "<button type='button' class='ghost' data-resolver-rate='" + esc(item) +
          "' data-resolver-rate-kind='auto' data-resolver-rate-date='" +
          esc($("#settings-resolver-preview-date").value) + "'>Can do</button>" +
          "<button type='button' class='ghost' data-resolver-rate='" + esc(item) +
          "' data-resolver-rate-kind='will_no' data-resolver-rate-date='" +
          esc($("#settings-resolver-preview-date").value) + "'>Won\'t do</button>" +
          "<button type='button' class='ghost' data-resolver-rate='" + esc(item) +
          "' data-resolver-rate-kind='feels_bad' data-resolver-rate-date='" +
          esc($("#settings-resolver-preview-date").value) + "'>Feels bad</button>"
        ).join("<br>")
      : "<span class='muted'>none</span>";
    return "<tr><td><strong>" + esc(choice.slot_id) + "</strong></td><td><strong>" +
      esc(choice.chosen) + "</strong><div class='muted'>" +
      esc(choice.pattern || "—") + "</div></td><td>" +
      (choice.rank == null ? "—" : choice.rank + "/" + choice.pool_size) +
      "</td><td>" + alternatives + "</td><td>" + suggestions + "</td></tr>";
  }).join("");
}

function renderResolverPreview(data) {
  window.__resolverPreview = data;
  const box = $("#settings-resolver-preview");
  if (!box) return;
  if (!data.ok) {
    const beam = data.beam ? "<details><summary>Search diagnostics</summary><pre>" +
      esc(JSON.stringify(data.beam, null, 2)) + "</pre></details>" : "";
    box.innerHTML = "<div class='warnbox'><strong>Resolver preview failed at " +
      esc(data.stage || "resolver") + "</strong><p>" + esc(data.message) + "</p>" + beam +
      "</div>";
    return;
  }
  const pending = data.pending_ratings || [];
  const pendingBox = pending.length
    ? "<div class='warnbox'><strong>Suitability ratings needed.</strong> Rate the suggested " +
      "exercise(s) below before starting: " +
      pending.map((item) => "<code>" + esc(item) + "</code>").join(", ") +
      "</div>" : "";
  const topSet = data.top_set
    ? "<details><summary>Top-set structure</summary><pre>" +
      esc(JSON.stringify(data.top_set, null, 2)) + "</pre></details>" : "";
  const projected = data.projected_week
    ? "<details><summary>Projected week</summary><pre>" +
      esc(JSON.stringify(data.projected_week, null, 2)) + "</pre></details>" : "";
  box.innerHTML = "<div class='panel'><div class='panel-head'><h3>" +
    esc(data.for_date) + " · " + esc(data.session_label || data.session_type) +
    "</h3><span class='badge'>preview</span></div>" + pendingBox +
    "<div class='table-scroll'><table><thead><tr><th>Slot</th><th>Chosen</th>" +
    "<th>Rank</th><th>Alternatives</th><th>Suggestion-only</th></tr></thead><tbody>" +
    resolverPreviewChoicesHtml(data) + "</tbody></table></div>" +
    "<div class='form-row'><button type='button' class='primary' " +
    (pending.length ? "disabled " : "") +
    "data-resolver-start>" + (pending.length ? "Rate suggestions to start" : "Start this preview") +
    "</button><span class='muted'>" +
    (pending.length
      ? "The shown exercise(s) are suggestion-only until rated."
      : "Freezes the shown session; nothing is saved until the start form is submitted.") +
    "</span></div>" +
    topSet + projected +
    "<details><summary>Warnings and beam diagnostics</summary><pre>" +
    esc(JSON.stringify({warnings: data.warnings, beam: data.beam}, null, 2)) +
    "</pre></details></div>";
}

function resolverDiffValue(key, value) {
  if (value === null || value === undefined) return "—";
  if (key === "load_kg") return fmt(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function resolverItemKey(item, index) {
  return item.order_index != null ? "order:" + item.order_index :
    item.exercise_id ? "exercise:" + item.exercise_id : "index:" + index;
}

function renderResolverPreviewDiff(previous, current) {
  const box = $("#settings-resolver-preview-diff");
  if (!box) return;
  if (!previous || !previous.ok || !current || !current.ok) {
    box.textContent = "";
    return;
  }
  // The toolbar response is the prescription payload itself; it is not nested under a
  // `prescription` key.
  const before = previous;
  const after = current;
  const changes = [];
  const oldItems = {};
  (before.items || []).forEach((item, index) => {
    oldItems[resolverItemKey(item, index)] = item;
  });
  const currentKeys = new Set();
  (after.items || []).forEach((item, index) => {
    const key = resolverItemKey(item, index);
    currentKeys.add(key);
    const prior = oldItems[key];
    const name = item.exercise_id || key;
    if (!prior) {
      changes.push("<div><strong>" + esc(name) + "</strong>: added to the prescription</div>");
      return;
    }
    const fieldLabels = [
      ["sets", "sets"], ["reps_low", "reps low"], ["reps_high", "reps high"],
      ["load_kg", "load"], ["load_basis", "load basis"],
      ["rir_target", "RIR"], ["rest_s", "rest"],
      ["effort_model", "effort model"], ["quality_stop", "quality stop"],
      ["time_cap_s", "time cap"], ["essential", "essential"],
    ];
    fieldLabels.forEach(([field, label]) => {
      const left = prior[field];
      const right = item[field];
      if (JSON.stringify(left ?? null) !== JSON.stringify(right ?? null)) {
        changes.push("<div><code>" + esc(name) + "</code> " + label + ": " +
          esc(resolverDiffValue(field, left)) + " → " +
          esc(resolverDiffValue(field, right)) + "</div>");
      }
    });
    if (JSON.stringify(prior.warmup || []) !== JSON.stringify(item.warmup || [])) {
      changes.push("<div><code>" + esc(name) + "</code>: warm-ups changed</div>");
    }
    if (JSON.stringify(prior.set_groups || []) !== JSON.stringify(item.set_groups || [])) {
      changes.push("<div><code>" + esc(name) + "</code>: set groups changed</div>");
    }
  });
  (before.items || []).forEach((item, index) => {
    const key = resolverItemKey(item, index);
    if (!currentKeys.has(key)) {
      changes.push("<div><strong>" + esc(item.exercise_id || key) +
        "</strong>: removed from the prescription</div>");
    }
  });
  const timeBefore = before.notes?.session_time?.estimated_minutes;
  const timeAfter = after.notes?.session_time?.estimated_minutes;
  if (JSON.stringify(timeBefore ?? null) !== JSON.stringify(timeAfter ?? null)) {
    changes.push("<div><strong>Estimated session time</strong>: " +
      esc(resolverDiffValue("estimated_minutes", timeBefore)) + " → " +
      esc(resolverDiffValue("estimated_minutes", timeAfter)) + "</div>");
  }
  if (JSON.stringify(previous.projected_week ?? null) !==
      JSON.stringify(current.projected_week ?? null)) {
    changes.push("<div><strong>Projected volume/week</strong> changed</div>");
  }
  ["session_type", "fallback_level", "rule_document_version", "time_cap_s",
    "executable"].forEach((field) => {
    if (JSON.stringify(before[field] ?? null) !== JSON.stringify(after[field] ?? null)) {
      changes.push("<div><strong>Session " + esc(field.replaceAll("_", " ")) +
        "</strong>: " + esc(resolverDiffValue(field, before[field])) + " → " +
        esc(resolverDiffValue(field, after[field])) + "</div>");
    }
  });
  if (JSON.stringify(before.issues || []) !== JSON.stringify(after.issues || [])) {
    changes.push("<div><strong>Validation/constraint issues</strong> changed</div>");
  }
  if (JSON.stringify(before.warnings || []) !== JSON.stringify(after.warnings || [])) {
    changes.push("<div><strong>Warnings</strong> changed</div>");
  }
  if (JSON.stringify(before.notes ?? null) !== JSON.stringify(after.notes ?? null)) {
    changes.push("<div><strong>Session notes/volume context</strong> changed</div>");
  }
  if (JSON.stringify(previous.top_set ?? null) !== JSON.stringify(current.top_set ?? null)) {
    changes.push("<div><strong>Top set</strong> changed</div>");
  }
  box.innerHTML = changes.length
    ? "<strong>Prescription changes since previous preview</strong>" + changes.join("")
    : "No prescription changes since the previous preview.";
}


let resolverPreviewRunning = false;

async function runResolverPreview() {
  const box = $("#settings-resolver-preview");
  if (resolverPreviewRunning) return;
  resolverPreviewRunning = true;
  if (box) box.innerHTML = "<p class='empty'>Building resolver preview…</p>";
  const previous = window.__resolverPreview;
  try {
    const started = await api("/api/resolver/preview/jobs", {
      method: "POST",
      body: JSON.stringify(resolverPreviewFormPayload()),
    });
    const startedAt = Date.now();
    let job = started;
    while (job.status === "running") {
      if (box) {
        const seconds = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
        box.innerHTML = "<p class='empty'>Building resolver preview… " + seconds + "s</p>";
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
      try {
        job = await api("/api/resolver/preview/jobs/" + encodeURIComponent(job.job_id));
      } catch (error) {
        throw new Error("resolver preview job was lost: " + error.message);
      }
    }
    if (job.status === "error") throw new Error(job.error || "resolver preview failed");
    const data = job.result;
    if (!data) throw new Error("resolver preview returned no result");
    renderResolverPreview(data);
    renderResolverPreviewDiff(previous, data);
  } catch (error) {
    if (box) box.innerHTML = "<div class='warnbox'>" + esc(error.message) + "</div>";
    const diff = $("#settings-resolver-preview-diff");
    if (diff) diff.textContent = "";
  } finally {
    resolverPreviewRunning = false;
  }
}

async function rateResolverSuggestion(button) {
  const exerciseId = button.dataset.resolverRate;
  const kind = button.dataset.resolverRateKind;
  const date = button.dataset.resolverRateDate;
  const payload = {
    exercise_id: exerciseId,
    rated_on: date,
    can_do: true,
    will_do: kind !== "will_no",
    feels_bad: kind === "feels_bad",
    note: "resolver preview inline rating",
  };
  try {
    await api("/api/state/suitability", { method: "POST", body: JSON.stringify(payload) });
    notify("Suitability recorded. Rebuilding preview…");
    await runResolverPreview();
  } catch (error) {
    notify(error.message, "error");
  }
}

async function openResolverPreviewStart() {
  const data = window.__resolverPreview;
  if (!data || !data.ok) return;
  if ((data.pending_ratings || []).length) {
    notify("Rate the suggested exercise(s) before starting this preview.", "error");
    return;
  }
  // The response is the exact prescription payload. Remove preview-only metadata so the
  // frozen plan contains the displayed prescription, not UI/diff controls.
  const plan = { ...data };
  ["ok", "stage", "message", "choices", "beam", "top_set", "projected_week",
    "session_time", "policy_digest", "catalogue_digest", "template_digest",
    "input_hash", "scheduled_suggestion"].forEach((key) => { delete plan[key]; });
  window.__lastPrescription = plan;
  if (typeof cachePrescription === "function") cachePrescription(plan);
  if (typeof openWorkoutStart === "function") openWorkoutStart();
  else notify("Open Workflow to start this preview.", "error");
}

const resolverSave = $("#settings-resolver-save");
if (resolverSave) resolverSave.addEventListener("click", saveResolverDraft);
const resolverReset = $("#settings-resolver-reset");
if (resolverReset) resolverReset.addEventListener("click", () => loadSettings());
const resolverPolicySave = $("#settings-resolver-policy-save");
if (resolverPolicySave) resolverPolicySave.addEventListener("click", saveResolverPolicy);
const resolverPolicyRestore = $("#settings-resolver-policy-restore");
if (resolverPolicyRestore) resolverPolicyRestore.addEventListener("click", restoreResolverPolicy);
const resolverPreviewForm = $("#settings-resolver-preview-form");
if (resolverPreviewForm) resolverPreviewForm.addEventListener("submit", (event) => {
  event.preventDefault();
  runResolverPreview();
});
const resolverPreviewBox = $("#settings-resolver-preview");
if (resolverPreviewBox) resolverPreviewBox.addEventListener("click", (event) => {
  const rate = event.target.closest("[data-resolver-rate]");
  if (rate) { rateResolverSuggestion(rate); return; }
  if (event.target.closest("[data-resolver-start]")) openResolverPreviewStart();
});

/* --- profile settings --------------------------------------------------- */
function renderProfileSettings(registry, profile) {
  window.__profileSettings = profile || {};
  window.__settingsRegistry = registry || [];
  const fields = $("#settings-profile-fields");
  if (!fields) return;
  const groups = {};
  (registry || []).forEach((setting) => {
    // Volume and Resolver settings have dedicated panels, not the generic profile list.
    if (setting.group === "Volume" || setting.group === "Resolver") return;
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
    renderResolverSettings(data.registry || [], profile);
  } catch (error) {
    $("#settings-profile-msg").textContent = "Profile settings failed: " + error.message;
    $("#settings-resolver-msg").textContent = "Resolver settings failed: " + error.message;
  }
  try {
    renderResolverPolicy(await api("/api/resolver/policy"));
  } catch (error) {
    $("#settings-resolver-policy-msg").textContent = "Resolver policy failed: " + error.message;
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
    renderIosSettings(await api("/api/settings/ios"));
  } catch (error) {
    $("#settings-ios-status").textContent = "error";
    $("#settings-ios-msg").textContent = "iOS settings failed: " + error.message;
  }
  try {
    const modalityData = await api("/api/modalities");
    renderModalities(modalityData);
  } catch (error) {
    $("#settings-profile-msg").textContent = "Modality settings failed: " + error.message;
  }
}

const iosForm = $("#settings-ios-form");
if (iosForm) iosForm.addEventListener("submit", saveIosSettings);

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
