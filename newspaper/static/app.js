(function () {
  "use strict";

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) {
      return null;
    }
  }

  // Theme toggle
  var root = document.documentElement;
  var savedTheme = store("theme");
  if (savedTheme) root.setAttribute("data-theme", savedTheme);
  var toggle = document.querySelector(".theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var current = root.getAttribute("data-theme") ||
        (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      var next = current === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      store("theme", next);
    });
  }

  // Daily quiz
  var score = 0;
  var scoreEl = document.querySelector(".quiz-score");
  var quizItems = document.querySelectorAll(".quiz-item");
  quizItems.forEach(function (item) {
    var answer = Number(item.dataset.answer);
    item.querySelectorAll(".option").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (item.classList.contains("answered")) return;
        item.classList.add("answered");
        var chosen = Number(btn.dataset.index);
        item.querySelectorAll(".option").forEach(function (b) {
          b.disabled = true;
          if (Number(b.dataset.index) === answer) b.classList.add("correct");
        });
        if (chosen === answer) score += 1;
        else btn.classList.add("wrong");
        item.querySelector(".explanation").hidden = false;
        if (scoreEl) scoreEl.textContent = score + " / " + quizItems.length;
      });
    });
  });

  // Interview prep notebook
  var dataEl = document.getElementById("prep-data");
  if (!dataEl) return;
  var items = JSON.parse(dataEl.textContent);
  var list = document.getElementById("prep-list");
  var search = document.getElementById("prep-search");
  var topic = document.getElementById("prep-topic");
  var kind = document.getElementById("prep-kind");
  var hideKnown = document.getElementById("prep-hide-known");
  var countEl = document.getElementById("prep-count");
  var known = {};
  try { known = JSON.parse(store("known") || "{}"); } catch (e) { known = {}; }

  function keyOf(it) { return it.kind + "|" + it.prompt; }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function render() {
    var q = search.value.trim().toLowerCase();
    var shown = items.filter(function (it) {
      if (topic.value && it.topic !== topic.value) return false;
      if (kind.value && it.kind !== kind.value) return false;
      if (hideKnown.checked && known[keyOf(it)]) return false;
      if (q && (it.prompt + " " + it.answer + " " + it.context).toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
    list.textContent = "";
    shown.forEach(function (it) {
      var li = el("li", "prep-card" + (known[keyOf(it)] ? " known" : ""));
      var meta = el("div", "prep-meta");
      meta.appendChild(el("span", "chip", it.kind));
      meta.appendChild(el("span", null, it.topic + " · " + it.date));
      li.appendChild(meta);
      li.appendChild(el("p", "prep-prompt", it.prompt));
      if (it.context) li.appendChild(el("p", "prep-context", it.context));
      var details = el("details", "qa");
      details.appendChild(el("summary", null, "Reveal"));
      details.appendChild(el("p", null, it.answer));
      if (it.link) {
        var a = el("a", null, "Read the source →");
        a.href = it.link; a.target = "_blank"; a.rel = "noopener";
        details.appendChild(a);
      }
      li.appendChild(details);
      var btn = el("button", "know", known[keyOf(it)] ? "✓ Known" : "I know this");
      btn.type = "button";
      btn.addEventListener("click", function () {
        if (known[keyOf(it)]) delete known[keyOf(it)];
        else known[keyOf(it)] = 1;
        store("known", JSON.stringify(known));
        render();
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
    countEl.textContent = shown.length + " of " + items.length + " shown";
  }

  [search, topic, kind, hideKnown].forEach(function (c) { c.addEventListener("input", render); });
  document.getElementById("prep-shuffle").addEventListener("click", function () {
    for (var i = items.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = items[i]; items[i] = items[j]; items[j] = t;
    }
    render();
  });
  render();
})();
