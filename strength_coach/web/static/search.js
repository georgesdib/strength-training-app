/* --- Global search palette (Ctrl/Cmd+K) -------------------------------- */
(function () {
  "use strict";

  const dialog = document.getElementById("search-palette");
  const input = document.getElementById("search-input");
  const resultsBox = document.getElementById("search-results");
  const openButton = document.getElementById("global-search-open");
  const askButton = document.getElementById("search-ask");
  const askMsg = document.getElementById("search-ask-msg");
  if (!dialog || !input || !resultsBox) return;

  const GROUPS = [
    ["view", "Views"],
    ["panel", "Panels"],
    ["setting", "Settings"],
    ["doc", "Docs"],
  ];
  const EXAMPLES = ["dwell", "symptoms", "readiness presets"];
  const HINT = "Type to search, or try: " + EXAMPLES.join(", ") + ".";

  let rows = [];
  let items = [];
  let active = -1;
  let seq = 0;
  let timer = null;
  let answerMarkup = "";

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, function (ch) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[ch];
    });
  }

  function hint(message) {
    rows = [];
    items = [];
    active = -1;
    answerMarkup = "";
    resultsBox.innerHTML = '<p class="search-empty">' + escapeHtml(message) + "</p>";
  }

  function render(results) {
    rows = [];
    if (!results.length) {
      items = [];
      active = -1;
      resultsBox.innerHTML = answerMarkup +
        '<p class="search-empty">No match. Try a view name, a setting label or a doc topic.</p>';
      return;
    }
    let markup = "";
    GROUPS.forEach(function (group) {
      const kind = group[0];
      const matching = results.filter(function (row) { return row.kind === kind; });
      if (!matching.length) return;
      markup += '<p class="search-group">' + escapeHtml(group[1]) + "</p>";
      matching.forEach(function (row) {
        const index = rows.length;
        rows.push(row);
        markup += '<button type="button" class="search-item" role="option" aria-selected="false" data-index="' +
          index + '"><span class="search-item-title">' + escapeHtml(row.title) +
          '</span><span class="search-item-sub">' + escapeHtml(row.subtitle || "") +
          "</span></button>";
      });
    });
    resultsBox.innerHTML = answerMarkup + markup;
    items = Array.prototype.slice.call(resultsBox.querySelectorAll(".search-item"));
    items.forEach(function (node) {
      node.addEventListener("click", function () {
        activate(rows[Number(node.dataset.index)]);
      });
    });
    active = -1;
  }

  function select(index) {
    if (!items.length) return;
    active = (index + items.length) % items.length;
    items.forEach(function (node, position) {
      node.setAttribute("aria-selected", position === active ? "true" : "false");
    });
    items[active].scrollIntoView({block: "nearest"});
  }

  function search(query) {
    const mine = ++seq;
    if (!query) {
      hint(HINT);
      return;
    }
    fetch("/api/search?limit=20&q=" + encodeURIComponent(query))
      .then(function (response) {
        return response.json().then(function (body) {
          return {ok: response.ok, body: body};
        });
      })
      .then(function (result) {
        if (mine !== seq) return;
        if (!result.ok) {
          hint(result.body.error || "Search failed.");
          return;
        }
        render(result.body.results || []);
      })
      .catch(function () {
        if (mine !== seq) return;
        hint("Search is unavailable right now.");
      });
  }

  function whenPresent(id, callback) {
    const started = Date.now();
    (function poll() {
      const element = document.getElementById(id);
      if (element) {
        callback(element);
        return;
      }
      if (Date.now() - started > 5000) return;
      setTimeout(poll, 60);
    })();
  }

  function reveal(element) {
    element.scrollIntoView({block: "start", behavior: "smooth"});
    element.classList.add("search-highlight");
    setTimeout(function () { element.classList.remove("search-highlight"); }, 1800);
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(element.tagName)) element.focus();
  }

  function activate(row) {
    if (!row) return;
    close();
    if (row.kind === "doc") {
      if (!row.doc) return;
      location.hash = "#docs?doc=" + encodeURIComponent(row.doc) +
        (row.anchor ? "&anchor=" + encodeURIComponent(row.anchor) : "");
      return;
    }
    if (!row.view) return;
    if (typeof setView === "function") setView(row.view, {fromHash: true});
    if (!row.target) {
      location.hash = "#" + row.view;
      return;
    }
    whenPresent(row.target, reveal);
    history.replaceState(null, "", "#" + row.view + "?panel=" + encodeURIComponent(row.target));
  }

  function open() {
    if (dialog.open) return;
    input.value = "";
    hint(HINT);
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    input.focus();
  }

  function close() {
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }

  input.addEventListener("input", function () {
    const query = input.value.trim();
    answerMarkup = "";
    if (askMsg) askMsg.textContent = "";
    clearTimeout(timer);
    timer = setTimeout(function () { search(query); }, 120);
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      select(active + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      select(active <= 0 ? items.length - 1 : active - 1);
    } else if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      ask();
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (active >= 0 && rows[active]) activate(rows[active]);
      else if (rows.length) activate(rows[0]);
    }
  });

  function ask() {
    const query = input.value.trim();
    if (!query) return;
    if (askButton) askButton.disabled = true;
    if (askMsg) askMsg.textContent = "Thinking…";
    seq += 1;
    fetch("/api/intelligence/locate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({query: query}),
    })
      .then(function (response) {
        return response.json().then(function (body) {
          return {ok: response.ok, body: body};
        });
      })
      .then(function (result) {
        if (!result.ok) {
          if (askMsg) askMsg.textContent = result.body.error || "The assistant is unavailable.";
          return;
        }
        const body = result.body;
        const badge = body.verified ? "verified" : "unverified";
        answerMarkup = '<div class="search-answer">' +
          '<div class="search-answer-head"><strong>Assistant</strong><span class="search-badge' +
          (body.verified ? "" : " search-badge-warn") + '">' + badge + "</span></div>" +
          "<p>" + escapeHtml(body.answer).replace(/\n/g, "<br>") + "</p>" +
          (body.verified ? "" :
            '<p class="search-item-sub">The answer named a place that is not in the results.' +
            " Use the results below.</p>") +
          '<p class="search-item-sub">These results come from the index; the answer cannot' +
          " create links.</p></div>";
        if (askMsg) askMsg.textContent = "";
        render(body.results || []);
      })
      .catch(function () {
        if (askMsg) askMsg.textContent = "The assistant is unavailable.";
      })
      .then(function () {
        if (askButton) askButton.disabled = false;
      });
  }

  if (askButton) askButton.addEventListener("click", ask);
  if (openButton) openButton.addEventListener("click", open);
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) close();
  });
  document.addEventListener("keydown", function (event) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      open();
    }
  });

  function applyPanelRoute() {
    const raw = location.hash.replace(/^#/, "");
    const parts = raw.split("?");
    const name = parts[0];
    const panel = new URLSearchParams(parts[1] || "").get("panel");
    if (!name || !panel) return;
    const section = document.getElementById("view-" + name);
    if (!section || !section.classList.contains("active")) {
      if (typeof setView === "function") setView(name, {fromHash: true});
    }
    whenPresent(panel, reveal);
  }

  window.addEventListener("hashchange", applyPanelRoute);
  if (location.hash.indexOf("panel=") !== -1) applyPanelRoute();
})();
