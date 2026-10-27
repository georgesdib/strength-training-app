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
