/* Shared chart geometry for descriptive analytics. Data definitions and filtering stay in their
 * existing feature/API owners; this file only normalizes finite points and renders SVG. */
function chartNumber(value, digits) {
  var rounded = Number(value).toFixed(digits == null ? 1 : digits);
  return rounded.replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
}

function chartSeriesControls(series) {
  if (!Array.isArray(series) || series.length < 2) return "";
  return "<div class='chart-series-controls' aria-label='Toggle chart series'>" + series.map(function (item, index) {
    var id = String(item.id || "series-" + index);
    return "<button type='button' class='chart-series-toggle' data-chart-series-toggle='" + esc(id) +
      "' aria-pressed='true'><span class='chart-series-swatch chart-series-" + index +
      "' aria-hidden='true'></span>" + esc(item.label || id) + "</button>";
  }).join("") + "</div>";
}

function chartResult(title, svg, note, series) {
  return "<div class='shared-chart'>" + chartFrame(title, svg, note) + chartSeriesControls(series) + "</div>";
}

function chartTickValues(min, max, count) {
  var steps = Math.max(2, count || 4);
  return Array.from({length: steps}, function (_, index) {
    return min + ((max - min) * index / (steps - 1));
  });
}

function dateSeriesChart(spec) {
  spec = spec || {};
  var title = spec.title || "Training trend";
  var source = Array.isArray(spec.series) ? spec.series : [];
  var series = source.map(function (item, index) {
    var points = (Array.isArray(item.points) ? item.points : []).map(function (point) {
      var date = String(point.date || "");
      return {date: date, time: Date.parse(date + "T00:00:00Z"), value: Number(point.value),
        label: point.label == null ? "" : String(point.label)};
    }).filter(function (point) {
      return point.date && Number.isFinite(point.time) && Number.isFinite(point.value);
    }).sort(function (a, b) { return a.time - b.time; });
    var requestedClass = String(item.className || "chart-series-" + index);
    var className = /^[a-zA-Z0-9_-]+$/.test(requestedClass) ? requestedClass : "chart-series-" + index;
    return {id: String(item.id || "series-" + index), label: String(item.label || item.id || "Series " + (index + 1)),
      className: className, points: points};
  }).filter(function (item) { return item.points.length > 0; });
  var allPoints = series.reduce(function (out, item) { return out.concat(item.points); }, []);
  if (!allPoints.length) return "<p class='empty'>" + esc(spec.emptyMessage || "No eligible observations in this period.") + "</p>";

  var width = 640, height = 250;
  var plot = {left: 68, right: width - 18, top: 18, bottom: height - 44};
  var xMin = Math.min.apply(null, allPoints.map(function (point) { return point.time; }));
  var xMax = Math.max.apply(null, allPoints.map(function (point) { return point.time; }));
  var xSpan = Math.max(86400000, xMax - xMin);
  var references = Array.isArray(spec.referenceLines) ? spec.referenceLines : [];
  var bands = Array.isArray(spec.referenceBands) ? spec.referenceBands : [];
  var ys = allPoints.map(function (point) { return point.value; });
  references.forEach(function (item) { if (Number.isFinite(Number(item.value))) ys.push(Number(item.value)); });
  bands.forEach(function (item) {
    if (Number.isFinite(Number(item.from))) ys.push(Number(item.from));
    if (Number.isFinite(Number(item.to))) ys.push(Number(item.to));
  });
  var rawMin = spec.yMin == null ? Math.min.apply(null, ys) : Number(spec.yMin);
  var rawMax = spec.yMax == null ? Math.max.apply(null, ys) : Number(spec.yMax);
  var span = Math.max(1e-9, rawMax - rawMin);
  var pad = spec.zeroBaseline ? 0 : span * 0.12;
  var yMin = spec.yMin == null ? Math.max(0, rawMin - pad) : Number(spec.yMin);
  var yMax = spec.yMax == null ? rawMax + (spec.zeroBaseline ? Math.max(0.5, span * 0.08) : pad) : Number(spec.yMax);
  if (yMax <= yMin) yMax = yMin + Math.max(1, Math.abs(yMin) * 0.05);
  var ySpan = yMax - yMin;
  var xFor = function (time) { return xMax === xMin ? (plot.left + plot.right) / 2 : plot.left + ((time - xMin) / xSpan) * (plot.right - plot.left); };
  var yFor = function (value) { return plot.bottom - ((value - yMin) / ySpan) * (plot.bottom - plot.top); };
  var formatY = typeof spec.formatY === "function" ? spec.formatY : function (value) { return chartNumber(value, 1); };
  var yTicks = chartTickValues(yMin, yMax, 4).map(function (value) { return {y: yFor(value), label: formatY(value)}; });
  var dates = Array.from(new Set(allPoints.map(function (point) { return point.date; }))).sort();
  var xIndices = dates.length === 1 ? [0] : [0, Math.floor((dates.length - 1) / 2), dates.length - 1];
  xIndices = Array.from(new Set(xIndices));
  var xTicks = xIndices.map(function (index) {
    var date = dates[index];
    return {x: xFor(Date.parse(date + "T00:00:00Z")), label: date};
  });
  var svg = "<svg class='performance-chart' style='width:100%;height:auto' viewBox='0 0 " + width + " " + height +
    "' role='img' aria-label='" + esc(title) + "'><title>" + esc(title) + "</title>";
  bands.forEach(function (band) {
    var y1 = yFor(Number(band.to)), y0 = yFor(Number(band.from));
    var top = Math.max(plot.top, Math.min(y1, y0));
    var bottom = Math.min(plot.bottom, Math.max(y1, y0));
    if (bottom > top) svg += "<rect class='chart-reference-band' x='" + plot.left + "' y='" + top.toFixed(1) +
      "' width='" + (plot.right - plot.left) + "' height='" + (bottom - top).toFixed(1) + "'><title>" +
      esc(band.label || "Reference range") + "</title></rect>";
  });
  svg += chartAxes(spec.xTitle || "Date", spec.yTitle || "Value", xTicks, yTicks, plot, width, height);
  references.forEach(function (item) {
    var y = yFor(Number(item.value));
    svg += "<line class='chart-reference' x1='" + plot.left + "' y1='" + y.toFixed(1) + "' x2='" + plot.right +
      "' y2='" + y.toFixed(1) + "'><title>" + esc(item.label || ("Reference: " + formatY(item.value))) + "</title></line>";
  });
  series.forEach(function (item) {
    var coords = item.points.map(function (point) { return [xFor(point.time), yFor(point.value)]; });
    var polyline = coords.length > 1 ? "<polyline class='" + item.className + "' points='" +
      coords.map(function (coord) { return coord[0].toFixed(1) + "," + coord[1].toFixed(1); }).join(" ") + "'></polyline>" : "";
    var circles = item.points.map(function (point) {
      var tooltip = typeof spec.tooltip === "function" ? spec.tooltip(point, item) :
        point.date + ": " + item.label + " " + formatY(point.value) + (point.label ? " · " + point.label : "");
      return "<circle class='" + item.className + "-point' cx='" + xFor(point.time).toFixed(1) + "' cy='" +
        yFor(point.value).toFixed(1) + "' r='4'><title>" + esc(tooltip) + "</title></circle>";
    }).join("");
    svg += "<g data-chart-series='" + esc(item.id) + "'>" + polyline + circles + "</g>";
  });
  svg += "</svg>";
  return chartResult(title, svg, spec.note || "Points are recorded observations; gaps are not imputed.", series);
}

function groupedBarChart(spec) {
  spec = spec || {};
  var title = spec.title || "Weekly comparison";
  var categories = Array.isArray(spec.categories) ? spec.categories : [];
  var series = (Array.isArray(spec.series) ? spec.series : []).map(function (item, index) {
    return {id: String(item.id || "series-" + index), label: String(item.label || item.id || "Series " + (index + 1)),
      values: categories.map(function (_, i) {
        var raw = Array.isArray(item.values) ? item.values[i] : null;
        var value = raw == null ? NaN : Number(raw);
        return Number.isFinite(value) ? value : null;
      }), className: "chart-series-" + index};
  }).filter(function (item) { return item.values.some(function (value) { return value != null; }); });
  if (!categories.length || !series.length) return "<p class='empty'>" + esc(spec.emptyMessage || "No observations in this period.") + "</p>";
  var allValues = series.reduce(function (out, item) { return out.concat(item.values.filter(function (v) { return v != null; })); }, []);
  var max = Math.max(0, Math.max.apply(null, allValues));
  var references = Array.isArray(spec.referenceLines) ? spec.referenceLines : [];
  references.forEach(function (item) { max = Math.max(max, Number(item.value) || 0); });
  max = max > 0 ? max * 1.12 : 1;
  var width = 640, height = 250;
  var plot = {left: 68, right: width - 18, top: 18, bottom: height - 44};
  var yFor = function (value) { return plot.bottom - (value / max) * (plot.bottom - plot.top); };
  var groupWidth = (plot.right - plot.left) / categories.length;
  var inner = groupWidth * 0.76;
  var barWidth = inner / series.length;
  var yTicks = chartTickValues(0, max, 4).map(function (value) { return {y: yFor(value), label: (spec.formatY || chartNumber)(value)}; });
  var visibleTicks = categories.map(function (category, index) { return index; }).filter(function (index) {
    return categories.length <= 6 || index === 0 || index === categories.length - 1 || index % Math.ceil(categories.length / 5) === 0;
  });
  var xTicks = visibleTicks.map(function (index) {
    return {x: plot.left + groupWidth * (index + 0.5), label: categories[index].label};
  });
  var svg = "<svg class='performance-chart' style='width:100%;height:auto' viewBox='0 0 " + width + " " + height +
    "' role='img' aria-label='" + esc(title) + "'><title>" + esc(title) + "</title>" +
    chartAxes(spec.xTitle || "Period", spec.yTitle || "Value", xTicks, yTicks, plot, width, height);
  references.forEach(function (item) {
    var y = yFor(Number(item.value));
    svg += "<line class='chart-reference' x1='" + plot.left + "' y1='" + y.toFixed(1) + "' x2='" + plot.right +
      "' y2='" + y.toFixed(1) + "'><title>" + esc(item.label || "Reference") + "</title></line>";
  });
  series.forEach(function (item, seriesIndex) {
    var bars = categories.map(function (category, categoryIndex) {
      var value = item.values[categoryIndex];
      if (value == null) return "";
      var x = plot.left + groupWidth * categoryIndex + (groupWidth - inner) / 2 + barWidth * seriesIndex;
      var y = yFor(value);
      var period = category.start && category.end ? category.start + " to " + category.end + " · " : "";
      return "<rect class='" + item.className + "' x='" + x.toFixed(1) + "' y='" + y.toFixed(1) +
        "' width='" + Math.max(1, barWidth - 2).toFixed(1) + "' height='" + Math.max(0, plot.bottom - y).toFixed(1) +
        "'><title>" + esc(period + category.label + ": " + item.label + " " + chartNumber(value, 1)) + "</title></rect>";
    }).join("");
    svg += "<g data-chart-series='" + esc(item.id) + "'>" + bars + "</g>";
  });
  svg += "</svg>";
  return chartResult(title, svg, spec.note || "Bars represent recorded values; unavailable values are not plotted.", series);
}

if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-chart-series-toggle]");
    if (!button) return;
    var chart = button.closest(".shared-chart");
    if (!chart) return;
    var id = button.getAttribute("data-chart-series-toggle");
    var group = Array.from(chart.querySelectorAll("[data-chart-series]"))
      .find(function (node) { return node.getAttribute("data-chart-series") === id; });
    if (!group) return;
    var show = button.getAttribute("aria-pressed") !== "true";
    button.setAttribute("aria-pressed", String(show));
    group.style.display = show ? "" : "none";
  });
}
