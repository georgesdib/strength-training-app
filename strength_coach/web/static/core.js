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
  return text;
}

const READINESS_SCALE_ENDS = {
  sleep: ["very poor", "excellent"],
  energy: ["exhausted", "excellent"],
  mood: ["very low", "excellent"],
  soreness: ["severe", "none"],
  stress: ["extreme", "none"],
  nutrition: ["very poor", "excellent"],
  hydration: ["very poor", "excellent"],
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

/* Filter a native select without replacing it: the select stays the constrained control. */
function filterNativeSelect(filter) {
  const wrapper = filter.closest(".search-select");
  const select = wrapper ? wrapper.querySelector("select") : null;
  if (!select) return;
  const query = filter.value.trim().toLowerCase();
  [...select.options].forEach((option) => {
    if (!option.value) return;
    const match = option.selected || !query ||
      option.textContent.toLowerCase().includes(query) ||
      String(option.value).toLowerCase().includes(query);
    option.hidden = !match;
    option.disabled = !match && !option.selected;
    option.style.display = match ? "" : "none";
  });
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
    const error = new Error(data.error || response.statusText);
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
