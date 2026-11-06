/* Shared client helpers: API, escaping, formatting, notices and local dates. */
const $ = (sel) => document.querySelector(sel);

function pad2(value) {
  return String(value).padStart(2, "0");
}

/* Local calendar date in YYYY-MM-DD; never use a UTC slice for a date default. */
function formatLocalDate(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "";
  return date.getFullYear() + "-" + pad2(date.getMonth() + 1) + "-" + pad2(date.getDate());
}

function today() {
  return formatLocalDate(new Date());
}

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
  if (text === "accessory") return "Accessory only";
  return text;
}

const READINESS_SCALE_ENDS = {
  sleep: ["very poor", "excellent"],
  energy: ["exhausted", "excellent"],
  mood: ["very low", "excellent"],
  soreness: ["severe", "none"],
  stress: ["extreme", "none"],
};

function readinessScaleOptions(field) {
  const ends = READINESS_SCALE_ENDS[field] || ["low", "high"];
  return ['<option value="">—</option>'].concat([1, 2, 3, 4, 5].map((n) =>
    `<option value="${n}">${n}${n === 1 ? " — " + ends[0] : n === 5 ? " — " + ends[1] : ""}</option>`
  )).join("");
}

function fmt(value, digits = 1) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits).replace(/\.0+$/, "") : esc(value);
}

/* Filter a native select by rebuilding its option list: browsers do not reliably hide
 * option elements, so display:none is not a filter. The constrained select remains the control. */
function optionSignature(select) {
  return [...select.options].map((option) => option.value + "\u0000" + option.textContent).join("\u0001");
}

function filterNativeSelect(filter) {
  const wrapper = filter.closest(".search-select");
  const select = wrapper ? wrapper.querySelector("select") : null;
  if (!select) return;
  const signature = optionSignature(select);
  // Cache the full list once. An external innerHTML replacement is detected even while a
  // previous query is active, so the next filter starts from the new source list.
  const sourceChanged = !select._filterAll ||
    (!select._filtered && select._sourceSignature !== signature) ||
    (select._filtered && select._filteredSignature !== signature);
  if (sourceChanged) {
    select._filterAll = [...select.options].map((option) => ({
      value: option.value,
      text: option.textContent,
    }));
    select._sourceSignature = signature;
  }
  const query = filter.value.trim().toLowerCase();
  const current = select.value;
  const entries = select._filterAll.filter((entry) =>
    !entry.value || !query ||
    entry.value.toLowerCase().includes(query) ||
    entry.text.toLowerCase().includes(query) ||
    entry.value === current
  );
  select.innerHTML = entries.map((entry) =>
    '<option value="' + esc(entry.value) + '">' + esc(entry.text) + "</option>"
  ).join("");
  if ([...select.options].some((option) => option.value === current)) {
    select.value = current;
  }
  select._filtered = Boolean(query);
  select._filteredSignature = optionSignature(select);
}

document.addEventListener("input", (event) => {
  if (event.target.matches?.(".search-select-filter")) filterNativeSelect(event.target);
});
document.addEventListener("change", (event) => {
  if (!event.target.matches?.(".search-select select")) return;
  const filter = event.target.closest(".search-select")?.querySelector(".search-select-filter");
  if (!filter) return;
  filter.value = "";
  filterNativeSelect(filter);
});

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
  if (!response.ok) {
    // 411/413 are transport failures with technical server wording; give the browser a
    // next action instead of making the user interpret HTTP framing.
    const transportCopy = {
      411: "The request was missing its size. Reload the page and try again.",
      413: "That file is too large to import. Split or compress it and try again.",
    };
    const error = new Error(
      transportCopy[response.status] || data.error || response.statusText
    );
    error.status = response.status;
    error.fields = data.fields || {};
    throw error;
  }
  return data;
}

function applyFieldErrors(error, target, mapping) {
  const fields = error.fields || {};
  const message = error.message || "Request failed.";
  if (target) {
    target.innerHTML = '<p class="warnbox">' + esc(message) + "</p>";
    target.setAttribute("role", "alert");
  }
  let first = null;
  Object.entries(fields).forEach(([field]) => {
    const selector = typeof mapping === "function" ? mapping(field) : mapping[field];
    if (!selector) return;
    const input = document.querySelector(selector);
    if (!input) return;
    input.setAttribute("aria-invalid", "true");
    if (target && target.id) input.setAttribute("aria-describedby", target.id);
    if (!first) first = input;
  });
  if (first && typeof first.focus === "function") first.focus();
}

document.addEventListener("input", (event) => {
  if (event.target.matches?.('[aria-invalid="true"]')) {
    event.target.removeAttribute("aria-invalid");
  }
});

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
