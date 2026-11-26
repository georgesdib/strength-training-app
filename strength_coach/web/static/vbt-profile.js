/* Read-only VBT load-velocity profile for the exercise details dialog.
   Display only: it renders stored mean velocity against load and a display-only
   implied 1RM. Nothing here feeds a prescription. */

async function loadExerciseVbt(row, rep) {
  var id = row.id;
  document.getElementById("exercise-vbt-status").textContent = "Loading profile…";
  try {
    var url = "/api/exercises/" + encodeURIComponent(id) + "/vbt-profile" +
      (rep ? "?rep=" + encodeURIComponent(rep) : "");
    var data = await api(url);
    if (window.__exerciseDetailsId !== id) return;
    renderExerciseVbt(data);
  } catch (error) {
    if (window.__exerciseDetailsId !== id) return;
    document.getElementById("exercise-vbt-status").textContent = "";
    document.getElementById("exercise-vbt-e1rm").textContent = "";
    document.getElementById("exercise-vbt-chart").innerHTML =
      "<p class='warnbox'>VBT profile unavailable: " + esc(error.message) + "</p>";
  }
}

function e1rmFlagText(flag) {
  if (flag === "below_heaviest_load") {
    return "flagged: the implied load is below the heaviest fitted load, so the line is inconsistent with the heavy sets";
  }
  if (flag === "beyond_extrapolation_limit") {
    return "flagged: beyond 2.5× the heaviest fitted load";
  }
  return "";
}

function renderExerciseVbt(data) {
  var host = document.getElementById("exercise-vbt-chart");
  var select = document.getElementById("exercise-vbt-reps");
  var status = document.getElementById("exercise-vbt-status");
  var e1rm = document.getElementById("exercise-vbt-e1rm");
  e1rm.textContent = "";
  var available = (data && data.available_reps) || [];
  var previous = select.value;
  if (available.length) {
    select.innerHTML = available.map(function (r) {
      return "<option value='" + r.reps + "'>" + r.reps + " rep" + (r.reps === 1 ? "" : "s") +
        " · " + r.n_sets + " sets" + (r.fitted ? "" : " (no fit)") + "</option>";
    }).join("");
  } else {
    select.innerHTML = "<option value=''>—</option>";
  }
  var keep = previous && available.some(function (r) { return String(r.reps) === previous; });
  if (keep) select.value = previous;
  else if (data && data.rep_count) select.value = String(data.rep_count);

  if (!data || data.status === "no_data") {
    status.textContent = "";
    host.innerHTML = "<p class='empty'>" + esc((data && data.reason) || "No stored mean velocity for this exercise.") + "</p>";
    return;
  }
  if (data.status === "insufficient") {
    status.textContent = "";
    var note = "<p class='empty'>" + esc(data.reason) + "</p>";
    if (data.pooled_status === "fitted") {
      note += renderPooledChart(data, 2.5, data.rep_count);
      e1rm.textContent = data.pooled_e1rm_kg
        ? "Pooled e1RM " + fmt(data.pooled_e1rm_kg) + " kg at 1 rep" +
          (data.pooled_e1rm_extrapolated ? " (extrapolated)" : "") + " — display only"
        : "No implied e1RM from the pooled model";
    } else {
      e1rm.textContent = "";
    }
    host.innerHTML = note;
    return;
  }

  var pts = data.points || [];
  var rirs = pts.map(function (p) { return p.rir; }).sort(function (a, b) { return a - b; });
  var refRir = rirs.length ? rirs[Math.floor(rirs.length / 2)] : 0;
  function lineAt(load) {
    return data.intercept + data.slope * load + (data.rir_coef || 0) * refRir;
  }

  var W = 680, H = 300, ml = 58, mr = 24, mt = 18, mb = 46;
  var xs = pts.map(function (p) { return p.load_kg; });
  var ys = pts.map(function (p) { return p.velocity_mps; });
  var x0 = Math.min.apply(null, xs.concat([data.load_min]));
  var x1 = Math.max.apply(null, xs.concat([data.load_max]));
  if (data.e1rm_kg) x1 = Math.max(x1, data.e1rm_kg);
  var xPad = Math.max((x1 - x0) * 0.06, 1);
  x0 -= xPad; x1 += xPad;
  var yLine = [lineAt(x0), lineAt(x1)];
  if (data.pooled_status === "fitted") {
    yLine.push(pooledLineAt(data, data.rep_count, x0, refRir));
    yLine.push(pooledLineAt(data, data.rep_count, x1, refRir));
  }
  var y0 = Math.min.apply(null, ys.concat(yLine));
  var y1 = Math.max.apply(null, ys.concat(yLine));
  if (data.e1rm_mvt_mps) y0 = Math.min(y0, data.e1rm_mvt_mps);
  var yPad = Math.max((y1 - y0) * 0.12, 0.02);
  y0 = Math.max(0, y0 - yPad); y1 += yPad;

  function sx(v) { return ml + ((v - x0) / (x1 - x0)) * (W - ml - mr); }
  function sy(v) { return H - mb - ((v - y0) / (y1 - y0)) * (H - mt - mb); }
  function ticks(lo, hi, n) {
    var out = [];
    for (var i = 0; i <= n; i += 1) out.push(lo + ((hi - lo) * i) / n);
    return out;
  }

  var grid = ticks(y0, y1, 4).map(function (v) {
    return "<line x1='" + ml + "' y1='" + sy(v).toFixed(1) + "' x2='" + (W - mr) + "' y2='" + sy(v).toFixed(1) + "' class='vbt-grid'/>" +
      "<text x='" + (ml - 8) + "' y='" + (sy(v) + 3).toFixed(1) + "' text-anchor='end' class='vbt-tick'>" + v.toFixed(2) + "</text>";
  }).join("") + ticks(x0, x1, 4).map(function (v) {
    return "<text x='" + sx(v).toFixed(1) + "' y='" + (H - mb + 16) + "' text-anchor='middle' class='vbt-tick'>" + v.toFixed(0) + "</text>";
  }).join("");

  var line = "<line x1='" + sx(x0).toFixed(1) + "' y1='" + sy(lineAt(x0)).toFixed(1) +
    "' x2='" + sx(x1).toFixed(1) + "' y2='" + sy(lineAt(x1)).toFixed(1) + "' class='vbt-line'/>";
  var pooledOverlay = "";
  if (data.pooled_status === "fitted") {
    pooledOverlay = "<line x1='" + sx(x0).toFixed(1) + "' y1='" +
      sy(pooledLineAt(data, data.rep_count, x0, refRir)).toFixed(1) +
      "' x2='" + sx(x1).toFixed(1) + "' y2='" +
      sy(pooledLineAt(data, data.rep_count, x1, refRir)).toFixed(1) +
      "' style='stroke:#b45309' class='vbt-line vbt-line-pooled'/>";
  }
  var dots = pts.map(function (p) {
    return "<circle cx='" + sx(p.load_kg).toFixed(1) + "' cy='" + sy(p.velocity_mps).toFixed(1) +
      "' r='2.6' class='vbt-dot'><title>" + esc(p.date) + " · " + fmt(p.load_kg) + " kg · " +
      p.velocity_mps.toFixed(2) + " m/s · RIR " + p.rir + "</title></circle>";
  }).join("");
  var marker = "";
  if (data.e1rm_kg) {
    marker = "<line x1='" + sx(data.e1rm_kg).toFixed(1) + "' y1='" + mt + "' x2='" + sx(data.e1rm_kg).toFixed(1) +
      "' y2='" + (H - mb) + "' class='vbt-e1rm-line'/>" +
      "<text x='" + sx(data.e1rm_kg).toFixed(1) + "' y='" + (mt + 10) +
      "' text-anchor='middle' class='vbt-e1rm-label'>VBT e1RM " + fmt(data.e1rm_kg) + " kg</text>";
  }

  var legend = data.pooled_status === "fitted"
    ? "<p class='muted vbt-legend'>Solid: per-rep fit at " + data.rep_count +
      " reps. Dashed: pooled model at the same reps.</p>"
    : "";
  var chart = legend + "<svg class='vbt-chart' viewBox='0 0 " + W + " " + H + "' role='img' aria-label='Load-velocity profile for " + esc(data.exercise_id) + "'>" +
    grid +
    "<line x1='" + ml + "' y1='" + (H - mb) + "' x2='" + (W - mr) + "' y2='" + (H - mb) + "' class='vbt-axis'/>" +
    "<line x1='" + ml + "' y1='" + mt + "' x2='" + ml + "' y2='" + (H - mb) + "' class='vbt-axis'/>" +
    line + pooledOverlay + dots + marker +
    "<text x='" + ((ml + W - mr) / 2) + "' y='" + (H - 8) + "' text-anchor='middle' class='vbt-tick'>load (kg)</text>" +
    "<text x='14' y='" + ((mt + H - mb) / 2) + "' text-anchor='middle' transform='rotate(-90 14 " + ((mt + H - mb) / 2) + ")' class='vbt-tick'>mean velocity (m/s)</text>" +
    "</svg>";
  host.innerHTML = chart + renderPooledChart(data, refRir, data.rep_count) +
    renderE1rmSeries(data.e1rm_series, data.rir_e1rm_series, data.pooled_e1rm_series);

  status.textContent = data.n_sets + " sets · " + data.n_sessions + " sessions · " +
    data.n_loads + " loads · R² " + (data.r2 == null ? "—" : data.r2.toFixed(2));
  var e1rmBits = [];
  if (data.e1rm_kg) {
    e1rmBits.push("Per-rep e1RM " + fmt(data.e1rm_kg) + " kg at " + data.e1rm_mvt_mps +
      " m/s (display only; line at RIR " + refRir + ")" +
      (data.e1rm_note ? " — " + e1rmFlagText(data.e1rm_note) : ""));
  }
  if (data.pooled_e1rm_kg) {
    e1rmBits.push("pooled " + fmt(data.pooled_e1rm_kg) + " kg at 1 rep" +
      (data.pooled_e1rm_extrapolated ? " (extrapolated)" : "") +
      (data.pooled_e1rm_note ? " — " + e1rmFlagText(data.pooled_e1rm_note) : ""));
  }
  e1rm.textContent = e1rmBits.length
    ? e1rmBits.join(" · ")
    : "No implied e1RM (display only; line at RIR " + refRir + ")";
}

function pooledLineAt(data, rep, load, rir) {
  return data.pooled_intercept + data.pooled_slope * load +
    (data.pooled_rep_coef || 0) * rep + (data.pooled_rir_coef || 0) * rir;
}

function renderPooledChart(data, refRir, highlightRep) {
  if (!data || data.pooled_status !== "fitted") return "";
  var observed = (data.pooled_observed_reps || []).map(function (r) { return r.reps; });
  var reps = observed.slice();
  var highlighted = highlightRep != null;
  var extrapolated = highlighted && (
    data.pooled_reps_min == null || data.pooled_reps_max == null ||
    highlightRep < data.pooled_reps_min || highlightRep > data.pooled_reps_max
  );
  if (highlighted && reps.indexOf(highlightRep) === -1) reps.push(highlightRep);
  reps.sort(function (a, b) { return a - b; });
  if (!reps.length) return "";

  var W = 680, H = 280, ml = 58, mr = 58, mt = 18, mb = 46;
  var x0 = data.pooled_load_min;
  var x1 = data.pooled_load_max;
  if (data.pooled_e1rm_kg) x1 = Math.max(x1, data.pooled_e1rm_kg);
  var pad = Math.max((x1 - x0) * 0.06, 1);
  x0 -= pad; x1 += pad;
  var values = [];
  reps.forEach(function (rep) {
    values.push(pooledLineAt(data, rep, x0, refRir));
    values.push(pooledLineAt(data, rep, x1, refRir));
  });
  var y0 = Math.min.apply(null, values);
  var y1 = Math.max.apply(null, values);
  var yPad = Math.max((y1 - y0) * 0.12, 0.02);
  y0 = Math.max(0, y0 - yPad); y1 += yPad;
  function sx(v) { return ml + ((v - x0) / (x1 - x0)) * (W - ml - mr); }
  function sy(v) { return H - mb - ((v - y0) / (y1 - y0)) * (H - mt - mb); }
  var colours = ["#2f6f4f", "#1d4ed8", "#b45309", "#7c3aed", "#0f766e", "#be123c"];

  var grid = [y0, (y0 + y1) / 2, y1].map(function (v) {
    return "<line x1='" + ml + "' y1='" + sy(v).toFixed(1) + "' x2='" + (W - mr) + "' y2='" + sy(v).toFixed(1) + "' class='vbt-grid'/>" +
      "<text x='" + (ml - 8) + "' y='" + (sy(v) + 3).toFixed(1) + "' text-anchor='end' class='vbt-tick'>" + v.toFixed(2) + "</text>";
  }).join("") + [x0, (x0 + x1) / 2, x1].map(function (v) {
    return "<text x='" + sx(v).toFixed(1) + "' y='" + (H - mb + 16) + "' text-anchor='middle' class='vbt-tick'>" + v.toFixed(0) + "</text>";
  }).join("");

  var lines = reps.map(function (rep, index) {
    var isHighlight = highlighted && rep === highlightRep;
    var colour = colours[index % colours.length];
    var dashed = isHighlight && extrapolated;
    var label = rep + " rep" + (rep === 1 ? "" : "s") + (dashed ? " (extrapolated)" : "");
    var yStart = pooledLineAt(data, rep, x0, refRir);
    var yEnd = pooledLineAt(data, rep, x1, refRir);
    return "<line x1='" + sx(x0).toFixed(1) + "' y1='" + sy(yStart).toFixed(1) + "' x2='" +
      sx(x1).toFixed(1) + "' y2='" + sy(yEnd).toFixed(1) + "' style='stroke:" + colour + "' class='vbt-line" +
      (dashed ? " vbt-line-pooled" : "") + "'/>" +
      "<text x='" + (W - mr + 4) + "' y='" + (sy(yEnd) + 3).toFixed(1) + "' class='vbt-tick'>" + label + "</text>";
  }).join("");

  var marker = "";
  if (data.pooled_e1rm_kg) {
    marker = "<line x1='" + sx(data.pooled_e1rm_kg).toFixed(1) + "' y1='" + mt +
      "' x2='" + sx(data.pooled_e1rm_kg).toFixed(1) + "' y2='" + (H - mb) +
      "' class='vbt-e1rm-line'/>" +
      "<text x='" + sx(data.pooled_e1rm_kg).toFixed(1) + "' y='" + (mt + 10) +
      "' text-anchor='middle' class='vbt-e1rm-label'>pooled e1RM " +
      fmt(data.pooled_e1rm_kg) + " kg" +
      (data.pooled_e1rm_extrapolated ? " (extrapolated)" : "") + "</text>";
  }
  return "<h4 class='vbt-series-title'>Pooled model <span class='muted'>(velocity ~ load + reps + RIR; " +
    data.pooled_n_sets + " sets, reps " + data.pooled_reps_min + "–" + data.pooled_reps_max +
    ")</span></h4>" +
    "<svg class='vbt-chart vbt-pooled' viewBox='0 0 " + W + " " + H + "' role='img' aria-label='Pooled load-velocity model across rep counts'>" +
    grid +
    "<line x1='" + ml + "' y1='" + (H - mb) + "' x2='" + (W - mr) + "' y2='" + (H - mb) + "' class='vbt-axis'/>" +
    "<line x1='" + ml + "' y1='" + mt + "' x2='" + ml + "' y2='" + (H - mb) + "' class='vbt-axis'/>" +
    lines + marker +
    "<text x='" + ((ml + W - mr) / 2) + "' y='" + (H - 8) + "' text-anchor='middle' class='vbt-tick'>load (kg)</text>" +
    "</svg>";
}

function renderE1rmSeries(series, rirSeries, pooledSeries) {
  if (!series || series.length < 2) return "";
  var rir = (rirSeries && rirSeries.length === series.length) ? rirSeries : [];
  var pooled = (pooledSeries && pooledSeries.length === series.length) ? pooledSeries : [];
  var values = series.map(function (p) { return p.e1rm_kg; });
  rir.forEach(function (p) { if (p && p.e1rm_kg != null) values.push(p.e1rm_kg); });
  pooled.forEach(function (p) { if (p && p.e1rm_kg != null) values.push(p.e1rm_kg); });
  var W = 680, H = 180, ml = 58, mr = 24, mt = 16, mb = 34;
  var y0 = Math.min.apply(null, values);
  var y1 = Math.max.apply(null, values);
  var pad = Math.max((y1 - y0) * 0.15, 1);
  y0 -= pad; y1 += pad;
  function sx(i) { return ml + (i / (series.length - 1)) * (W - ml - mr); }
  function sy(v) { return H - mb - ((v - y0) / (y1 - y0)) * (H - mt - mb); }

  var vbt = series.map(function (p, i) {
    return sx(i).toFixed(1) + "," + sy(p.e1rm_kg).toFixed(1);
  }).join(" ");
  var dots = series.map(function (p, i) {
    return "<circle cx='" + sx(i).toFixed(1) + "' cy='" + sy(p.e1rm_kg).toFixed(1) +
      "' r='2.4' class='vbt-dot'><title>" + esc(p.date) + " · VBT " + fmt(p.e1rm_kg) +
      " kg · " + p.n_sets + " sets</title></circle>";
  }).join("");

  function linesFor(list, colour) {
    var segments = [];
    var current = [];
    list.forEach(function (p, i) {
      if (p && p.e1rm_kg != null) {
        current.push(sx(i).toFixed(1) + "," + sy(p.e1rm_kg).toFixed(1));
      } else if (current.length) {
        segments.push(current.join(" "));
        current = [];
      }
    });
    if (current.length) segments.push(current.join(" "));
    return segments.map(function (segment) {
      return "<polyline points='" + segment + "' class='vbt-line' fill='none' style='stroke:" +
        colour + "'/>";
    }).join("");
  }
  var rirLines = linesFor(rir, "#1d4ed8");
  var pooledLines = linesFor(pooled, "#b45309");

  var grid = [y0, (y0 + y1) / 2, y1].map(function (v) {
    return "<line x1='" + ml + "' y1='" + sy(v).toFixed(1) + "' x2='" + (W - mr) + "' y2='" + sy(v).toFixed(1) + "' class='vbt-grid'/>" +
      "<text x='" + (ml - 8) + "' y='" + (sy(v) + 3).toFixed(1) + "' text-anchor='end' class='vbt-tick'>" + v.toFixed(0) + "</text>";
  }).join("");
  var first = series[0];
  var last = series[series.length - 1];
  var flagged = series.concat(pooled).some(function (p) { return p && p.flag; });
  var legend = "<p class='muted vbt-legend'>Green: VBT e1RM (per-rep line)." +
    (pooledLines ? " Orange: VBT e1RM (pooled model)." : "") +
    (rirLines ? " Blue: e1RM from RIR (Epley, eligible session best)." : "") +
    (flagged ? " Flagged points fall outside the fitted load range." : "") + "</p>";
  return "<h4 class='vbt-series-title'>VBT e1RM over time <span class='muted'>(" +
    esc(first.date) + " → " + esc(last.date) + ")</span></h4>" + legend +
    "<svg class='vbt-chart vbt-series' viewBox='0 0 " + W + " " + H + "' role='img' aria-label='VBT e1RM and RIR e1RM over time'>" +
    grid +
    "<line x1='" + ml + "' y1='" + (H - mb) + "' x2='" + (W - mr) + "' y2='" + (H - mb) + "' class='vbt-axis'/>" +
    "<polyline points='" + vbt + "' class='vbt-line' fill='none'/>" +
    dots + pooledLines + rirLines +
    "<text x='" + ml + "' y='" + (H - 12) + "' class='vbt-tick'>" + esc(first.date) + "</text>" +
    "<text x='" + (W - mr) + "' y='" + (H - 12) + "' text-anchor='end' class='vbt-tick'>" + esc(last.date) + "</text>" +
    "</svg>";
}

document.getElementById("exercise-vbt-reps").addEventListener("change", function () {
  var id = window.__exerciseDetailsId;
  if (!id) return;
  loadExerciseVbt({ id: id }, this.value);
});
