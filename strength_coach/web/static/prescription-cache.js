/* Browser-only cache for the latest previewed prescription.
 * It never writes to the server and never replaces the frozen workout snapshot. */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.PrescriptionCache = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var KEY = "strength-coach.prescription.v1";
  var MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

  function validPlan(plan) {
    return Boolean(plan && typeof plan === "object"
      && typeof plan.for_date === "string" && plan.for_date
      && Array.isArray(plan.items));
  }

  function save(storage, plan, now) {
    if (!storage || !validPlan(plan)) return false;
    try {
      storage.setItem(KEY, JSON.stringify({
        version: 1,
        saved_at: new Date(now == null ? Date.now() : now).toISOString(),
        for_date: plan.for_date,
        session_type: plan.session_type || "",
        plan: plan
      }));
      return true;
    } catch (error) {
      return false;
    }
  }

  function read(storage, now) {
    if (!storage) return null;
    var current = now == null ? Date.now() : Number(now);
    try {
      var raw = storage.getItem(KEY);
      if (!raw) return null;
      var data = JSON.parse(raw);
      if (!data || data.version !== 1 || !validPlan(data.plan)
          || typeof data.saved_at !== "string") {
        clear(storage);
        return null;
      }
      var savedAt = Date.parse(data.saved_at);
      // A future or unparseable timestamp is corrupt, not a fresh cache.
      if (!Number.isFinite(savedAt) || savedAt > current) {
        clear(storage);
        return null;
      }
      if (current - savedAt > MAX_AGE_MS) {
        clear(storage);
        return null;
      }
      return data;
    } catch (error) {
      clear(storage);
      return null;
    }
  }

  function clear(storage) {
    if (!storage) return;
    try { storage.removeItem(KEY); } catch (error) { /* ignore */ }
  }

  function selectionDiffers(plan, selection) {
    if (!validPlan(plan) || !selection || !selection.date) return true;
    if (String(plan.for_date) !== String(selection.date)) return true;
    var type = selection.session_type || "auto";
    // "auto" means the current form does not pin a concrete session type.
    return type !== "auto" && String(plan.session_type || "") !== type;
  }

  return {
    KEY: KEY,
    MAX_AGE_MS: MAX_AGE_MS,
    save: save,
    read: read,
    clear: clear,
    selectionDiffers: selectionDiffers
  };
});
