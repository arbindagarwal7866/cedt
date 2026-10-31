"""
render_html.py - HTML output (used by the web interface and `--html report.html`).

Design idea: the compiler's text is shown in a terminal-style monospace pane
("compiler language"), the explanations in a serif text face ("human
language"), and suggested fixes are drawn like a teacher's red-pen
proofreading marks - the proofreader's caret mirrors the compiler's caret.
"""
import difflib
import html
import os
import re

from .models import LEVEL_ORDER, PHASE_DESCRIPTIONS, PHASES, PHASE_NAMES

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "static")
LEVEL_LABEL = {"error": "Error", "warning": "Warning", "tip": "Tip", "info": "Note"}
PHASE_SHORT = {"preprocessor": "Preprocessor", "lexical": "Lexer", "syntax": "Parser", "semantic": "Semantic",
               "flow": "Flow analysis", "linker": "Linker", "runtime": "Run"}


def esc(s):
    return html.escape(s or "", quote=True)


def inline(text):
    """Escape, then turn `code` into <code> and newlines into <br>."""
    out = []
    parts = re.split(r"(`[^`\n]+`)", text or "")
    for p in parts:
        if len(p) >= 2 and p.startswith("`") and p.endswith("`"):
            out.append("<code>%s</code>" % esc(p[1:-1]))
        else:
            out.append(esc(p).replace("\n", "<br>"))
    return "".join(out)


def ordered_roots(report):
    roots = [e for e in report.explanations if e.is_root]

    def key(e):
        ln = e.real_line or (e.location.line if e.location and e.location.line else 10 ** 6)
        return (LEVEL_ORDER.get(e.level, 9), ln, e.id)
    return sorted(roots, key=key)


def phase_counts(report):
    counts = {k: {"error": 0, "warning": 0, "tip": 0, "info": 0} for k, _ in PHASES}
    for e in report.explanations:
        if e.is_root and e.phase in counts:
            counts[e.phase][e.level] = counts[e.phase].get(e.level, 0) + 1
    return counts


# --------------------------------------------------------------- pieces
def source_lines(report, e):
    if not e.location:
        return []
    f = e.location.file
    text = report.sources.get(f)
    if text is None:
        b = os.path.basename(f.replace("\\", "/"))
        for k, v in report.sources.items():
            if os.path.basename(k.replace("\\", "/")) == b:
                text = v
                break
    if text is None:
        info = (e.diagnostic.extra.get("snippet_info") if e.diagnostic else None) or {}
        src = info.get("src") or {}
        if not src:
            return []
        last = max(src)
        return [src.get(i, "") for i in range(1, last + 1)]
    return text.replace("\r\n", "\n").split("\n")


def excerpt(lines, focus, reported=None, before=1, after=1):
    if not lines or not focus or focus < 1 or focus > len(lines):
        return ""
    show = set()
    for c in [focus] + ([reported] if reported and 0 < reported <= len(lines) else []):
        show.update(range(max(1, c - before), min(len(lines), c + after) + 1))
    rows = []
    prev = None
    for n in sorted(show):
        if prev is not None and n > prev + 1:
            rows.append('<span class="ln gap"><span class="no">&#8942;</span><span class="src"></span></span>')
        prev = n
        cls = "ln"
        label = ""
        if n == focus:
            cls += " focus"
            if reported and reported != focus:
                label = "mistake is here"
        elif n == reported:
            cls += " reported"
            label = "compiler pointed here"
        rows.append('<span class="%s" data-line="%d"><span class="no">%d</span><span class="src">%s</span>%s</span>'
                    % (cls, n, n, esc(lines[n - 1]) or " ",
                       '<span class="mark">%s</span>' % label if label else ""))
    return '<pre class="excerpt">%s</pre>' % "".join(rows)


def proofread(old, new):
    """Inline red-pen view of the change from old to new."""
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    out = []
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == "equal":
            out.append(esc(old[a1:a2]))
        elif op == "delete":
            out.append('<del>%s</del>' % esc(old[a1:a2]))
        elif op == "insert":
            out.append('<ins>%s</ins>' % esc(new[b1:b2]))
        else:
            out.append('<del>%s</del><ins>%s</ins>' % (esc(old[a1:a2]), esc(new[b1:b2])))
    return "".join(out)


def fix_block(e, lines):
    if e.fixed_line is None or not e.fixed_line_no:
        return ""
    n = e.fixed_line_no
    old = lines[n - 1] if lines and 0 < n <= len(lines) else None
    if e.fixed_kind == "insert_before":
        lead = len(e.fixed_line) - len(e.fixed_line.lstrip())
        body = '<span class="pf-line"><span class="no">+</span><span class="src">%s<ins>%s</ins></span></span>' % (
            esc(e.fixed_line[:lead]), esc(e.fixed_line[lead:]))
        caption = "Add this line before line %d" % n
    elif e.fixed_kind == "delete":
        body = '<span class="pf-line"><span class="no">%d</span><span class="src"><del>%s</del></span></span>' % (
            n, esc(old or ""))
        caption = "Delete line %d" % n
    elif old is None:
        body = '<span class="pf-line"><span class="no">%d</span><span class="src">%s</span></span>' % (n, esc(e.fixed_line))
        caption = "Corrected line %d" % n
    else:
        body = '<span class="pf-line"><span class="no">%d</span><span class="src">%s</span></span>' % (
            n, proofread(old, e.fixed_line))
        caption = "Correction for line %d" % n
    copy = esc(e.fixed_line)
    return ('<figure class="proof"><figcaption>%s</figcaption><pre>%s</pre>'
            '<button type="button" class="copy" data-copy="%s">Copy corrected line</button></figure>'
            % (caption, body, copy)) if e.fixed_kind != "delete" else (
        '<figure class="proof"><figcaption>%s</figcaption><pre>%s</pre></figure>' % (caption, body))


def where(e):
    if e.source == "runtime" and not e.location:
        return "while the program was running"
    if not e.location:
        return "no line number (reported after compilation)"
    f = os.path.basename((e.location.file or "").replace("\\", "/"))
    if not e.location.line:
        return f
    if e.real_line and e.real_line != e.location.line:
        return '%s, line %d <span class="moved">(the compiler pointed at line %d)</span>' % (
            esc(f), e.real_line, e.location.line)
    return "%s, line %d" % (esc(f), e.location.line)


def card(e, report, number):
    lines = source_lines(report, e)
    focus = e.real_line or (e.location.line if e.location else None)
    reported = e.location.line if e.location and e.real_line and e.real_line != e.location.line else None
    parts = []
    parts.append('<article class="problem lvl-%s" id="problem-%d" data-line="%s" data-id="%d">' % (
        e.level, e.id, focus or "", e.id))
    parts.append('<div class="margin"><span class="numeral">%d</span></div><div class="body">' % number)
    parts.append('<header><h3>%s</h3><p class="meta"><span class="level">%s</span> <span class="sep">/</span> '
                 '<span class="phase" title="%s">%s</span> <span class="sep">/</span> <span class="where">%s</span></p>'
                 '</header>' % (inline(e.title), LEVEL_LABEL.get(e.level, e.level),
                                esc(PHASE_DESCRIPTIONS.get(e.phase, "")), esc(PHASE_NAMES.get(e.phase, e.phase)),
                                where(e)))
    if focus:
        parts.append(excerpt(lines, focus, reported))
    parts.append('<p class="what">%s</p>' % inline(e.what))
    for h in e.hints:
        parts.append('<p class="hint">%s</p>' % inline(h))
    fx = fix_block(e, lines)
    if e.fix or fx:
        parts.append('<section class="fix"><h4>How to fix it</h4>')
        if e.fix:
            parts.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(x) for x in e.fix))
        parts.append(fx)
        parts.append("</section>")
    more = []
    if e.why:
        more.append('<details><summary>Why this happens</summary><ul>%s</ul></details>' % "".join(
            "<li>%s</li>" % inline(x) for x in e.why))
    if e.example_wrong or e.example_right:
        more.append('<details><summary>Example</summary><div class="example">'
                    '<div><span class="tag">Wrong</span><pre>%s</pre></div>'
                    '<div><span class="tag">Right</span><pre>%s</pre></div></div></details>' % (
                        esc(e.example_wrong or ""), esc(e.example_right or "")))
    if e.tip:
        more.append('<details><summary>Good to know</summary><p>%s</p></details>' % inline(e.tip))
    if e.jargon:
        more.append('<details><summary>Words in the compiler message</summary><dl class="jargon">%s</dl></details>'
                    % "".join("<dt>%s</dt><dd>%s</dd>" % (esc(j["term"]), esc(j["meaning"])) for j in e.jargon))
    raw = e.diagnostic.raw_lines if e.diagnostic is not None else []
    raw_txt = "\n".join(raw[:14]) + ("\n..." if len(raw) > 14 else "") if raw else e.compiler_message
    more.append('<details class="said"><summary>What the compiler said</summary><pre class="term">%s</pre></details>'
                % colorize(raw_txt))
    fol = [report.explanations[i] for i in e.followers if i < len(report.explanations)]
    if fol:
        items = []
        for f in fol:
            items.append('<li><code>%s</code><span class="reason">%s</span></li>' % (
                esc(f.compiler_message[:160]), esc(f.follower_reason or "")))
        more.append('<details class="followers"><summary>%d more compiler message%s caused by this problem</summary>'
                    '<p class="small">These will most likely disappear once this problem is fixed.</p><ul>%s</ul></details>'
                    % (len(fol), "" if len(fol) == 1 else "s", "".join(items)))
    parts.append('<div class="more">%s</div>' % "".join(more))
    if e.confidence == "low":
        parts.append('<p class="small">This is a general explanation; the exact cause could not be pinned down.</p>')
    parts.append("</div></article>")
    return "".join(parts)


_TERM_RULES = [
    (re.compile(r"(\b(?:fatal )?error:)"), "t-err"),
    (re.compile(r"(\bwarning:)"), "t-warn"),
    (re.compile(r"(\bnote:)"), "t-note"),
]


def colorize(raw):
    """GCC-style colouring of raw compiler output (escaped)."""
    out = []
    for line in (raw or "").split("\n"):
        t = esc(line)
        t = re.sub(r"^([^\s:][^:]*:\d+(?::\d+)?:)", r'<span class="t-loc">\1</span>', t)
        for rx, cls in _TERM_RULES:
            t = rx.sub(r'<span class="%s">\1</span>' % cls, t, count=1)
        if re.match(r"^\s*\|?\s*[~^ ]*\^[~^ ]*$", line.split("|")[-1] if "|" in line else line):
            t = '<span class="t-caret">%s</span>' % t
        out.append(t)
    return "\n".join(out)


def pipeline(report):
    counts = phase_counts(report)
    stations = []
    for key, name in PHASES:
        c = counts[key]
        total = c["error"] + c["warning"] + c["tip"] + c["info"]
        state = "error" if c["error"] else "warning" if c["warning"] else "tip" if c["tip"] else "info" if c["info"] else "clear"
        label = []
        if c["error"]:
            label.append("%d error%s" % (c["error"], "" if c["error"] == 1 else "s"))
        if c["warning"]:
            label.append("%d warning%s" % (c["warning"], "" if c["warning"] == 1 else "s"))
        if c["tip"]:
            label.append("%d tip%s" % (c["tip"], "" if c["tip"] == 1 else "s"))
        stations.append('<li class="station st-%s" title="%s"><span class="dot">%s</span><span class="name">%s</span>'
                        '<span class="count">%s</span></li>' % (
                            state, esc(PHASE_DESCRIPTIONS.get(key, "")), total or "", esc(PHASE_SHORT[key]),
                            esc(", ".join(label)) if label else ""))
    end = "built" if report.build_ok else "not built"
    stations.append('<li class="station st-end %s"><span class="dot"></span><span class="name">Program</span>'
                    '<span class="count">%s</span></li>' % ("ok" if report.build_ok else "fail", end))
    return '<ol class="pipeline" aria-label="Phases of compilation">%s</ol>' % "".join(stations)


def summary(report):
    c = report.counts()
    st = report.stats or {}
    bits = []
    if c["error"]:
        bits.append("%d problem%s to fix" % (c["error"], "" if c["error"] == 1 else "s"))
    if c["warning"]:
        bits.append("%d warning%s" % (c["warning"], "" if c["warning"] == 1 else "s"))
    if c["tip"]:
        bits.append("%d tip%s" % (c["tip"], "" if c["tip"] == 1 else "s"))
    if not bits:
        head = "No problems found." if report.build_ok else "Nothing to explain."
    else:
        head = ", ".join(bits) + "."
    sub = ""
    n = st.get("compiler_messages", 0)
    if n:
        sub = "The compiler printed %d message%s (%d lines of output); CEDT traced them to %d root problem%s." % (
            n, "" if n == 1 else "s", st.get("output_lines", 0), st.get("root_problems", 0),
            "" if st.get("root_problems", 0) == 1 else "s")
    elif report.build_ok:
        sub = "The program compiled without any compiler messages."
    run = ""
    if report.run is not None and report.run.ran:
        r = report.run
        status = ("stopped after %.1f s (time limit)" % (r.duration_ms / 1000) if r.timed_out else
                  "crashed (%s)" % r.signal_name if r.signal_name else "finished with exit code %s" % r.exit_code)
        run = ('<section class="run"><h4>Program run - %s</h4><pre class="term">%s</pre></section>'
               % (esc(status), esc((r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")) or "(no output)"))
    return ('<div class="summary"><p class="headline">%s</p><p class="sub">%s</p>%s</div>' % (esc(head), esc(sub), run))


def render_cards(report):
    roots = ordered_roots(report)
    return "".join(card(e, report, i + 1) for i, e in enumerate(roots))


def side_by_side(report):
    rows = []
    for e in report.explanations:
        if e.source != "compiler":
            continue
        raw = e.compiler_message
        right = '<strong>%s</strong><br>%s' % (inline(e.title), inline(e.what))
        if not e.is_root:
            right = '<em class="folded">Follow-on message: %s</em>' % esc(e.follower_reason or "")
        rows.append('<tr class="%s"><td class="raw"><pre class="term">%s</pre></td><td class="plain">%s</td></tr>' % (
            "root" if e.is_root else "follower", colorize(raw), right))
    if not rows:
        return '<p class="small">The compiler printed no messages.</p>'
    return ('<table class="sbs"><thead><tr><th>Compiler language</th><th>Plain language</th></tr></thead>'
            '<tbody>%s</tbody></table>' % "".join(rows))


def _first_sentence(text):
    m = re.match(r"(.+?[.!?])(\s+[A-Z(`]|$)", text or "", re.S)
    return m.group(1) if m else (text or "")


def short_paths(raw, report):
    """/var/folders/.../main.c:4:5: -> main.c:4:5: (the temporary folder only confuses)."""
    for f in report.files or []:
        base = os.path.basename(f.replace("\\", "/"))
        if f and f != base:
            raw = raw.replace(f, base)
    return re.sub(r"(?m)^(?:[A-Za-z]:)?[^\s:]*[/\\]([^/\\\s:]+\.(?:c|cc|cpp|cxx|h|hpp)):", r"\1:", raw)


def compact(e, report, number):
    """One problem in a few lines: title, real line, one sentence, corrected line."""
    lines = source_lines(report, e)
    focus = e.real_line or (e.location.line if e.location else None)
    loc = ""
    if focus:
        loc = "Line %d" % focus
        if e.real_line and e.location and e.location.line and e.real_line != e.location.line:
            loc += ' <span class="moved">(compiler said line %d)</span>' % e.location.line
    elif e.source == "runtime":
        loc = "While running"
    fol = len(e.followers)
    note = ""
    if fol:
        note = '<p class="c-fold">+ %d more compiler message%s caused by this same mistake</p>' % (
            fol, "" if fol == 1 else "s")
    elif e.source == "precheck":
        note = '<p class="c-fold">The compiler said nothing about this - CEDT found it.</p>'
    return ('<article class="c-item lvl-%s" data-line="%s"><p class="c-head"><span class="c-num">%d</span>'
            '<span class="c-title">%s</span><span class="c-loc">%s</span></p><p class="c-what">%s</p>%s%s</article>'
            % (e.level, focus or "", number, inline(e.title), loc, inline(_first_sentence(e.what)),
               fix_block(e, lines), note))


def compare(report):
    """The two outputs next to each other: the normal compiler's and CEDT's."""
    name = (report.compiler or {}).get("name") or "compiler"
    raw = short_paths(report.raw_output or "", report).strip()
    n = (report.stats or {}).get("compiler_messages", 0)
    if raw:
        left = '<pre class="term c-raw">%s</pre>' % colorize(raw)
        left_sub = "%d message%s" % (n, "" if n == 1 else "s") if n else ""
    else:
        left = '<p class="c-empty">(printed nothing)</p>'
        left_sub = ""
    roots = ordered_roots(report)
    if roots:
        right = "".join(compact(e, report, i + 1) for i, e in enumerate(roots))
        right_sub = "%d problem%s" % (len(roots), "" if len(roots) == 1 else "s")
    else:
        right = '<p class="c-empty c-ok">%s</p>' % (
            "No problems found - the program is correct." if report.build_ok else "Nothing to explain.")
        right_sub = ""
    run = ""
    if report.run is not None and report.run.ran:
        r = report.run
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        run = ('<section class="c-run"><h4>Program output</h4><pre class="term">%s</pre></section>'
               % (esc(short_paths(out, report).strip()) or "(no output)"))
    return ('<div class="compare">'
            '<section class="c-col c-compiler"><h3>Normal compiler <span>%s</span></h3><p class="c-sub">%s</p>%s</section>'
            '<section class="c-col c-cedt"><h3>CEDT</h3><p class="c-sub">%s</p>%s</section>'
            '</div>%s' % (esc(name), esc(left_sub), left, esc(right_sub), right, run))


def render_fragment(report):
    return {
        "compare": compare(report),
        "summary": summary(report),
        "pipeline": pipeline(report),
        "cards": render_cards(report),
        "side_by_side": side_by_side(report),
        "raw": colorize(report.raw_output or ""),
    }


def render_report(report, title=None):
    """A complete stand-alone HTML page (for `cedt prog.c --html report.html`)."""
    with open(os.path.join(STATIC, "cedt.css"), encoding="utf-8") as fh:
        css = fh.read()
    frag = render_fragment(report)
    files = ", ".join(os.path.basename(f) for f in report.files) or "compiler output"
    title = title or "CEDT report - %s" % files
    comp = report.compiler.get("name") or ""
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title><style>%s</style></head>
<body class="report-page">
<header class="report-head"><h1>%s</h1><p class="meta">%s %s</p></header>
<main class="report-main">%s%s<div class="problems">%s</div>
<details class="rawbox"><summary>Full compiler output</summary><pre class="term">%s</pre></details>
</main>
<footer class="report-foot">Generated by CEDT - Compiler Error Diagnostic Translator</footer>
</body></html>""" % (esc(title), css, esc(files), esc(report.language.upper()), esc(comp),
                     frag["pipeline"], frag["summary"], frag["cards"] or "", frag["raw"] or "(empty)")
