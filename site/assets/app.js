/* D.J.U.A.C. League Archives: theme toggle, tabs, sortable tables, command-palette search. No dependencies. */
(function () {
  "use strict";
  var doc = document.documentElement;
  var ROOT = doc.getAttribute("data-root") || "";

  /* theme ---------------------------------------------------------------- */
  var themeBtn = document.getElementById("theme-toggle");
  function currentTheme() {
    var t = doc.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function syncThemeLabel() {
    if (themeBtn) themeBtn.setAttribute("aria-label", currentTheme() === "dark" ? "Switch to light theme" : "Switch to dark theme");
  }
  if (themeBtn) {
    syncThemeLabel();
    themeBtn.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      doc.setAttribute("data-theme", next);
      try { localStorage.setItem("djuac-theme", next); } catch (e) {}
      syncThemeLabel();
    });
  }

  /* tabs (WAI-ARIA tabs pattern, hash-linked) ---------------------------- */
  Array.prototype.forEach.call(document.querySelectorAll("[data-tabs]"), function (root) {
    var tabs = Array.prototype.slice.call(root.querySelectorAll('[role="tab"]'));
    function select(tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
        var panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
    }
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () {
        select(tab);
        history.replaceState(null, "", "#" + tab.getAttribute("aria-controls"));
      });
      tab.addEventListener("keydown", function (e) {
        var j = null;
        if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
        if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
        if (e.key === "Home") j = 0;
        if (e.key === "End") j = tabs.length - 1;
        if (j !== null) { e.preventDefault(); select(tabs[j], true); }
      });
    });
    var fromHash = tabs.filter(function (t) { return "#" + t.getAttribute("aria-controls") === location.hash; })[0];
    select(fromHash || tabs[0]);
  });

  /* sortable tables ------------------------------------------------------ */
  Array.prototype.forEach.call(document.querySelectorAll("table.sortable"), function (table) {
    var heads = table.querySelectorAll("th[data-sort]");
    Array.prototype.forEach.call(heads, function (th) {
      var label = th.innerHTML;
      th.innerHTML = "<button type=\"button\">" + label + "</button>";
      th.firstChild.addEventListener("click", function () {
        var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
        var asc = th.getAttribute("aria-sort") !== "ascending";
        Array.prototype.forEach.call(heads, function (h) { h.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        var numeric = th.getAttribute("data-sort") === "num";
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) {
          var x = a.children[idx], y = b.children[idx];
          var xv = x ? (x.getAttribute("data-v") || x.textContent) : "";
          var yv = y ? (y.getAttribute("data-v") || y.textContent) : "";
          var r;
          if (numeric) {
            var xn = parseFloat(String(xv).replace(/[^0-9.\-]/g, "")), yn = parseFloat(String(yv).replace(/[^0-9.\-]/g, ""));
            if (isNaN(xn)) xn = -Infinity; if (isNaN(yn)) yn = -Infinity;
            r = xn - yn;
          } else r = String(xv).localeCompare(String(yv));
          return asc ? r : -r;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });

  /* head-to-head toggle -------------------------------------------------- */
  var coreToggle = document.getElementById("core-toggle");
  if (coreToggle) {
    var matrix = document.querySelector(".matrix");
    coreToggle.addEventListener("change", function () { matrix.classList.toggle("core-only", !coreToggle.checked); });
  }

  /* search: command palette + /search page ------------------------------- */
  var index = null, loading = null;
  function loadIndex(cb) {
    if (index) return cb(index);
    if (!loading) {
      loading = [];
      var s = document.createElement("script");
      s.src = ROOT + "assets/search-index.js";
      s.onload = function () { index = window.DJUAC_SEARCH || []; loading.forEach(function (f) { f(index); }); };
      document.head.appendChild(s);
    }
    loading.push(cb);
  }
  function norm(s) { return String(s).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
  function search(q) {
    q = norm(q.trim());
    if (!q) return [];
    var terms = q.split(/\s+/);
    var out = [];
    for (var i = 0; i < index.length; i++) {
      var it = index[i], hay = it._h || (it._h = norm(it.l + " " + (it.s || "") + " " + (it.k || "")));
      var ok = true, score = 0;
      for (var t = 0; t < terms.length; t++) {
        var p = hay.indexOf(terms[t]);
        if (p < 0) { ok = false; break; }
        score += p === 0 ? 3 : (hay.charAt(p - 1) === " " ? 2 : 1);
      }
      if (ok) { if (norm(it.l).indexOf(q) === 0) score += 5; out.push([score + (it.w || 0), it]); }
    }
    out.sort(function (a, b) { return b[0] - a[0]; });
    return out.slice(0, 40).map(function (x) { return x[1]; });
  }
  var GROUPS = { owner: "Owners", season: "Seasons", team: "Team names", player: "Players", page: "Pages" };
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function wire(input, list, onNavigate) {
    var active = -1, items = [];
    function render() {
      var res = search(input.value);
      items = res;
      active = res.length ? 0 : -1;
      if (!input.value.trim()) { list.innerHTML = '<li class="cmdk-empty">Owners, team names, seasons and drafted players.</li>'; input.setAttribute("aria-activedescendant", ""); return; }
      if (!res.length) { list.innerHTML = '<li class="cmdk-empty" role="status">No results found.</li>'; return; }
      var html = "", last = null;
      res.forEach(function (it, i) {
        if (it.t !== last) { html += '<li class="cmdk-group" role="presentation">' + (GROUPS[it.t] || it.t) + "</li>"; last = it.t; }
        html += '<li class="cmdk-item" role="option" id="' + list.id + "-o" + i + '" aria-selected="' + (i === 0) + '"><a tabindex="-1" href="' + esc(ROOT + it.u) + '"><span>' + esc(it.l) + '</span><span class="sub">' + esc(it.s || "") + "</span></a></li>";
      });
      list.innerHTML = html;
      highlight();
    }
    function highlight() {
      var opts = list.querySelectorAll('[role="option"]');
      Array.prototype.forEach.call(opts, function (o, i) { o.setAttribute("aria-selected", i === active ? "true" : "false"); });
      if (opts[active]) { input.setAttribute("aria-activedescendant", opts[active].id); opts[active].scrollIntoView({ block: "nearest" }); }
    }
    input.addEventListener("input", function () { loadIndex(render); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" && items.length) { e.preventDefault(); active = (active + 1) % items.length; highlight(); }
      else if (e.key === "ArrowUp" && items.length) { e.preventDefault(); active = (active - 1 + items.length) % items.length; highlight(); }
      else if (e.key === "Enter" && items[active]) { e.preventDefault(); if (onNavigate) onNavigate(); location.href = ROOT + items[active].u; }
    });
    return render;
  }

  var dialog = document.getElementById("cmdk");
  var opener = null;
  if (dialog && typeof dialog.showModal === "function") {
    var input = document.getElementById("cmdk-input");
    var render = wire(input, document.getElementById("cmdk-list"), function () { dialog.close(); });
    function open() {
      opener = document.activeElement;
      if (!dialog.open) dialog.showModal();
      input.select();
      loadIndex(render);
    }
    Array.prototype.forEach.call(document.querySelectorAll("[data-open-search]"), function (b) {
      b.addEventListener("click", function (e) { e.preventDefault(); open(); });
    });
    document.addEventListener("keydown", function (e) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); dialog.open ? dialog.close() : open(); }
      else if (e.key === "/" && !dialog.open && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); open(); }
    });
    dialog.addEventListener("click", function (e) { if (e.target === dialog) dialog.close(); });
    dialog.addEventListener("close", function () { if (opener && opener.focus) opener.focus(); });
  }

  var pageInput = document.getElementById("search-page-input");
  if (pageInput) {
    var renderPage = wire(pageInput, document.getElementById("search-page-list"));
    var q = new URLSearchParams(location.search).get("q");
    if (q) pageInput.value = q;
    loadIndex(renderPage);
  }
})();

// Expandable leaderboards: top 5 <-> top 25
document.addEventListener('click', function (ev) {
  var btn = ev.target.closest('[data-expand]');
  if (!btn) return;
  var box = btn.closest('.expandable');
  var open = box.classList.toggle('is-expanded');
  btn.setAttribute('aria-expanded', open);
  btn.textContent = open ? btn.getAttribute('data-less') : btn.getAttribute('data-more');
});
