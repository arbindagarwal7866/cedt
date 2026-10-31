/* CEDT web interface */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
  };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inline = (s) => esc(s).replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\n/g, "<br>");

  const code = $("#code"), gutter = $("#gutter");
  let lang = "c", samples = [], last = null, grammar = null, rulesLoaded = false;

  const STARTER = [
    "#include <stdio.h>",
    "",
    "int main() {",
    "    int count = 5",
    "    printf(\"Count is %d\\n\", conut);",
    "    return 0;",
    "}",
    "",
  ].join("\n");

  /* ------------------------------------------------------------ theme */
  const savedTheme = store.get("cedt-theme");
  if (savedTheme) document.documentElement.setAttribute("data-theme", savedTheme);
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    store.set("cedt-theme", next);
  });

  /* ------------------------------------------------------------ editor */
  let markers = {};
  function renderGutter() {
    const n = code.value.split("\n").length;
    let html = "";
    for (let i = 1; i <= n; i++) {
      const m = markers[i];
      html += m ? `<div class="m-${m.level}" data-id="${m.id}" title="Problem on line ${i}">${i}</div>` : `<div>${i}</div>`;
    }
    gutter.innerHTML = html;
    gutter.scrollTop = code.scrollTop;
  }
  code.addEventListener("input", () => { markers = {}; renderGutter(); store.set("cedt-code-" + lang, code.value); });
  code.addEventListener("scroll", () => { gutter.scrollTop = code.scrollTop; });
  code.addEventListener("keydown", (ev) => {
    if (ev.key === "Tab" && !ev.shiftKey) {
      ev.preventDefault();
      const s = code.selectionStart, e = code.selectionEnd;
      code.setRangeText("    ", s, e, "end");
      code.dispatchEvent(new Event("input"));
    }
  });
  document.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") { ev.preventDefault(); compile(); }
  });
  gutter.addEventListener("click", (ev) => {
    const d = ev.target.closest("div[data-id]");
    if (!d) return;
    focusCard(d.dataset.id, true);
  });

  function selectLine(line) {
    const lines = code.value.split("\n");
    if (!line || line > lines.length) return;
    let start = 0;
    for (let i = 0; i < line - 1; i++) start += lines[i].length + 1;
    code.focus({ preventScroll: true });
    code.setSelectionRange(start, start + lines[line - 1].length);
    const lh = 21;
    code.scrollTop = Math.max(0, (line - 4) * lh);
  }

  function focusCard(id, scroll) {
    $$(".problem.selected, .c-item.selected").forEach((c) => c.classList.remove("selected"));
    const big = document.getElementById("problem-" + id);
    const line = big ? big.dataset.line : "";
    const card = (line && $('#compare .c-item[data-line="' + line + '"]')) || big;
    if (!card) return;
    card.classList.add("selected");
    if (scroll) card.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }

  /* ------------------------------------------------------------ language, samples */
  function setLang(l, keepCode) {
    lang = l;
    $$(".seg button").forEach((b) => {
      const on = b.dataset.lang === l;
      b.classList.toggle("on", on);
      b.setAttribute("aria-checked", on ? "true" : "false");
    });
    if (!keepCode) {
      const saved = store.get("cedt-code-" + l);
      if (saved) code.value = saved;
    }
    renderGutter();
  }
  $$(".seg button").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));

  $("#sample").addEventListener("change", (ev) => {
    const s = samples.find((x) => x.id === ev.target.value);
    if (!s) return;
    setLang(s.lang, true);
    code.value = s.code;
    markers = {};
    renderGutter();
    store.set("cedt-code-" + s.lang, s.code);
    if (/scanf|cin\s*>>|getchar/.test(s.code) && $("#run").checked) $("#stdin").focus();
  });

  $("#run").addEventListener("change", () => { $("#stdin-box").hidden = !$("#run").checked; });

  /* ------------------------------------------------------------ tabs and views */
  function showView(v) {
    $$(".views button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
    ["translator", "rules", "inside"].forEach((x) => { $("#view-" + x).hidden = x !== v; });
    if (v === "rules") loadRules();
    if (v === "inside") renderInside();
    window.scrollTo(0, 0);
  }
  $$(".views button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

  /* ------------------------------------------------------------ compile */
  function setStatus(msg, isErr) {
    const s = $("#status");
    if (!msg) { s.hidden = true; return; }
    s.hidden = false;
    s.className = "status" + (isErr ? " err" : "");
    s.textContent = msg;
  }

  async function post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({ error: "The server sent an unreadable reply." }));
    if (!r.ok || data.error) throw new Error(data.error || ("HTTP " + r.status));
    return data;
  }

  async function compile() {
    const btn = $("#go");
    btn.disabled = true;
    setStatus("Compiling with " + ($("#compiler").value === "auto" ? "the default compiler" : $("#compiler").value) + "...");
    try {
      const data = await post("/api/explain", {
        code: code.value, lang, compiler: $("#compiler").value, run: $("#run").checked,
        stdin: $("#stdin").value, sanitize: $("#sanitize").checked,
      });
      show(data);
    } catch (e) {
      setStatus("Could not compile: " + e.message, true);
    } finally {
      btn.disabled = false;
    }
  }
  $("#go").addEventListener("click", compile);

  $("#go-log").addEventListener("click", async () => {
    const log = $("#log").value;
    if (!log.trim()) { $("#log").focus(); return; }
    try {
      setStatus("Explaining the pasted output...");
      show(await post("/api/explain-log", { log, code: code.value, lang }));
    } catch (e) { setStatus("Could not explain: " + e.message, true); }
  });

  function show(data) {
    last = data;
    setStatus("");
    (data.parse_errors || []).filter((p) => !/^line \d+:/.test(p)).forEach((p) => setStatus(p, true));
    $("#empty").hidden = true;
    $("#result").hidden = false;
    $("#compare").innerHTML = data.fragments.compare;
    $("#tab-cards").innerHTML = data.fragments.cards ||
      '<p class="what">' + (data.build_ok ? "The program compiled without any problems." : "Nothing to explain.") + "</p>";
    $(".detailed").hidden = !data.fragments.cards;
    $(".detailed").open = false;
    $$("#compare .c-item").forEach((c) => c.addEventListener("click", (ev) => {
      if (ev.target.closest("button")) return;
      if (c.dataset.line) selectLine(parseInt(c.dataset.line, 10));
    }));
    markers = {};
    (data.markers || []).forEach((m) => {
      const order = { error: 0, warning: 1, tip: 2, info: 3 };
      if (!markers[m.line] || order[m.level] < order[markers[m.line].level]) markers[m.line] = m;
    });
    renderGutter();
    $$("#tab-cards .problem").forEach((c) => {
      c.addEventListener("click", (ev) => {
        if (ev.target.closest("summary, button, a")) return;
        focusCard(c.dataset.id, false);
        if (c.dataset.line) selectLine(parseInt(c.dataset.line, 10));
      });
    });
    $$("#result .copy").forEach((b) => b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; }
      catch (e) { b.textContent = "Select and copy manually"; }
      setTimeout(() => { b.textContent = "Copy corrected line"; }, 1600);
    }));
    if (!$("#view-inside").hidden) renderInside();
  }

  /* ------------------------------------------------------------ encyclopedia */
  let rules = [], phaseFilter = "all";
  const PHASE_NAMES = { preprocessor: "Preprocessor", lexical: "Lexical", syntax: "Syntax", semantic: "Semantic",
    flow: "Flow analysis", linker: "Linker", runtime: "Runtime" };
  async function loadRules() {
    if (rulesLoaded) return;
    rulesLoaded = true;
    const data = await (await fetch("/api/rules")).json();
    rules = data.rules;
    const st = data.stats;
    $("#rules-stats").textContent = `${st.rules} explanations covering ${st.patterns} different GCC and Clang message ` +
      `patterns. Search for the message your compiler printed, or browse by compiler phase.`;
    const phases = ["all"].concat(Object.keys(PHASE_NAMES).filter((p) => st.per_phase[p]));
    $("#phase-chips").innerHTML = phases.map((p) =>
      `<button type="button" data-p="${p}" class="${p === "all" ? "on" : ""}">${p === "all" ? "All" : PHASE_NAMES[p]}` +
      `${p === "all" ? "" : " " + st.per_phase[p]}</button>`).join("");
    $$("#phase-chips button").forEach((b) => b.addEventListener("click", () => {
      phaseFilter = b.dataset.p;
      $$("#phase-chips button").forEach((x) => x.classList.toggle("on", x === b));
      renderRules();
    }));
    renderRules();
  }
  $("#rule-search").addEventListener("input", renderRules);
  function renderRules() {
    const q = $("#rule-search").value.trim().toLowerCase();
    const list = rules.filter((r) => (phaseFilter === "all" || r.phase === phaseFilter) &&
      (!q || (r.id + " " + r.title + " " + r.what + " " + r.samples.join(" ")).toLowerCase().includes(q)));
    $("#rule-list").innerHTML = list.map((r) => `
      <details class="rule"><summary><span class="rid">${esc(r.id)}</span><span class="rtitle">${inline(r.title)}</span>
        <span class="rphase">${esc(PHASE_NAMES[r.phase] || r.phase)}${r.lang !== "both" ? " / " + esc(r.lang.toUpperCase()) + " only" : ""}</span></summary>
        <div class="rbody"><p>${inline(r.what.replace(/\{(\w+)\}/g, "…"))}</p>
          ${r.why.length ? "<h4>Common causes</h4><ul>" + r.why.map((x) => "<li>" + inline(x.replace(/\{(\w+)\}/g, "…")) + "</li>").join("") + "</ul>" : ""}
          ${r.fix.length ? "<h4>How to fix</h4><ul>" + r.fix.map((x) => "<li>" + inline(x.replace(/\{(\w+)\}/g, "…")) + "</li>").join("") + "</ul>" : ""}
          ${r.example && (r.example.wrong || r.example.right) ? `<div class="example"><div><span class="tag">Wrong</span><pre>${esc(r.example.wrong || "")}</pre></div><div><span class="tag">Right</span><pre>${esc(r.example.right || "")}</pre></div></div>` : ""}
          <h4>Compiler messages it explains</h4><div class="samples">${r.samples.map((s) => "<code>" + esc(s) + "</code>").join("")}</div>
        </div></details>`).join("") || '<p class="lead">No rule matches that search.</p>';
  }

  /* ------------------------------------------------------------ inside CEDT */
  async function renderInside() {
    if (!grammar) grammar = await (await fetch("/api/grammar")).json();
    $("#g-grammar").textContent = grammar.grammar;
    $("#ll1-note").textContent = "The grammar below describes compiler output. CEDT computes FIRST/FOLLOW sets and the " +
      "predictive parsing table itself; " + (grammar.ll1 ? "there are no conflicts, so the grammar is LL(1)." :
      "conflicts: " + grammar.conflicts.join("; ")) + " Action symbols (@name) build the error tree while parsing; " +
      "unknown lines are skipped with panic-mode recovery using FOLLOW sets.";
    $("#t-ff tbody").innerHTML = grammar.nonterminals.map((n) =>
      `<tr><td>${esc(n)}</td><td>{ ${esc(grammar.first[n].join(", "))} }</td><td>{ ${esc(grammar.follow[n].join(", "))} }</td></tr>`).join("");
    const I = last && last.internals;
    if (!I || I.error) {
      ["#t-dtok", "#t-trace", "#t-stok", "#t-scopes", "#t-syms"].forEach((t) => {
        $(t + " tbody").innerHTML = '<tr><td colspan="6">Run "Compile and explain" in the Translator first.</td></tr>';
      });
      return;
    }
    $("#t-dtok tbody").innerHTML = I.diag_tokens.map((t) =>
      `<tr><td>${t.line}</td><td class="tk tok-${esc(t.type)}">${esc(t.type)}</td><td>${esc(t.text)}</td></tr>`).join("");
    $("#t-trace tbody").innerHTML = I.parse_trace.map((s) =>
      `<tr><td>${esc(s.stack)}</td><td>${esc(s.lookahead)}</td><td>${esc(s.action)}</td></tr>`).join("");
    $("#t-stok tbody").innerHTML = I.source_tokens.map((t) =>
      `<tr><td>${t.line}:${t.col}</td><td>${esc(t.kind)}</td><td>${esc(t.text)}</td><td class="err">${esc(t.error || "")}</td></tr>`).join("");
    $("#t-scopes tbody").innerHTML = I.scopes.map((s) =>
      `<tr><td>${s.id}</td><td>${esc(s.kind)}</td><td>${esc(s.name)}</td><td>${s.from}-${s.to == null ? "end" : s.to}</td></tr>`).join("");
    $("#t-syms tbody").innerHTML = I.symbols.map((s) => {
      const det = [];
      if (s.params.length) det.push("params: " + s.params.join(", "));
      if (s.members.length) det.push("members: " + s.members.join(", "));
      if (s.kind === "var" && !s.initialized) det.push("no starting value");
      if (s.value) det.push("= " + s.value);
      return `<tr><td>${esc(s.name)}</td><td>${esc(s.kind)}</td><td>${esc(s.type)}</td><td>${s.line}</td><td>#${s.scope}</td><td>${esc(det.join("; "))}</td></tr>`;
    }).join("");
  }

  /* ------------------------------------------------------------ start-up */
  async function init() {
    code.value = store.get("cedt-code-c") || STARTER;
    renderGutter();
    try {
      const info = await (await fetch("/api/info")).json();
      const sel = $("#compiler");
      (info.compilers || []).forEach((c) => {
        const o = document.createElement("option");
        o.value = c.command; o.textContent = c.name;
        sel.appendChild(o);
      });
      if (!info.compilers || !info.compilers.length) {
        setStatus("No gcc or clang was found on this computer. CEDT will only run its own checks. " +
          "Install GCC (Windows: MSYS2/MinGW, macOS: xcode-select --install, Linux: build-essential).", true);
      }
      samples = await (await fetch("/api/samples")).json();
      const groups = { c: "C programs", "c++": "C++ programs" };
      const sel2 = $("#sample");
      Object.keys(groups).forEach((g) => {
        const og = document.createElement("optgroup");
        og.label = groups[g];
        samples.filter((s) => s.lang === g).forEach((s) => {
          const o = document.createElement("option");
          o.value = s.id; o.textContent = s.title;
          og.appendChild(o);
        });
        if (og.children.length) sel2.appendChild(og);
      });
    } catch (e) {
      setStatus("The CEDT server is not reachable. Start it with: python cedt.py --web", true);
    }
  }
  init();
})();
