"""
render_text.py - terminal output for the command-line tool.

ASCII-only layout (safe in Windows cmd, macOS Terminal, VS Code), optional
ANSI colours.
"""
import os
import re
import sys
import textwrap

from .models import PHASES, PHASE_NAMES
from .render_html import ordered_roots, phase_counts, source_lines

WIDTH = 92


class Style:
    def __init__(self, color):
        self.color = color

    def _w(self, code, s):
        return "\x1b[%sm%s\x1b[0m" % (code, s) if self.color else s

    def bold(self, s): return self._w("1", s)
    def dim(self, s): return self._w("2", s)
    def red(self, s): return self._w("1;31", s)
    def yellow(self, s): return self._w("1;33", s)
    def green(self, s): return self._w("1;32", s)
    def cyan(self, s): return self._w("36", s)
    def magenta(self, s): return self._w("35", s)
    def blue(self, s): return self._w("1;34", s)
    def inverse(self, s): return self._w("7", s)

    def level(self, lvl, s):
        return {"error": self.red, "warning": self.yellow, "tip": self.green}.get(lvl, self.blue)(s)

    def code(self, text):
        """Render `code` spans: coloured without backticks, or keep backticks."""
        if not self.color:
            return text
        return re.sub(r"`([^`\n]+)`", lambda m: self.cyan(m.group(1)), text)


def enable_windows_ansi():
    if os.name != "nt":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)
            return True
    except Exception:
        pass
    return False


def wrap(text, indent, width=WIDTH):
    out = []
    for para in (text or "").split("\n"):
        lines = textwrap.wrap(para, width=width - len(indent), break_long_words=False, break_on_hyphens=False) or [""]
        out.extend(indent + l for l in lines)
    return "\n".join(out)


def bullet(items, indent, st):
    out = []
    for it in items:
        lines = textwrap.wrap(it, width=WIDTH - len(indent) - 2, break_long_words=False) or [""]
        out.append(indent + "- " + st.code(lines[0]))
        out.extend(indent + "  " + st.code(l) for l in lines[1:])
    return "\n".join(out)


def pipeline_line(report, st):
    counts = phase_counts(report)
    parts = []
    for key, _ in PHASES:
        c = counts[key]
        n = c["error"] + c["warning"] + c["tip"]
        name = {"preprocessor": "Preproc", "lexical": "Lexer", "syntax": "Parser", "semantic": "Semantic",
                "flow": "Flow", "linker": "Linker", "runtime": "Run"}[key]
        if n:
            lvl = "error" if c["error"] else "warning" if c["warning"] else "tip"
            parts.append(st.level(lvl, "[%s:%d]" % (name, n)))
        else:
            parts.append(st.dim(name))
    end = st.green("[built]") if report.build_ok else st.red("[not built]")
    return " - ".join(parts) + " => " + end


def render(report, color=False, show_raw=False, brief=False, show_followers=True):
    st = Style(color)
    out = []
    bar = "=" * WIDTH
    files = ", ".join(os.path.basename(f) for f in report.files) or "(compiler output)"
    comp = report.compiler.get("name") or "?"
    out.append(st.bold(bar))
    out.append(st.bold(" CEDT - Compiler Error Diagnostic Translator"))
    out.append(" File: %s   Language: %s   Compiler: %s" % (files, report.language.upper(), comp))
    c = report.counts()
    stx = report.stats or {}
    bits = []
    if c["error"]:
        bits.append(st.red("%d problem%s to fix" % (c["error"], "" if c["error"] == 1 else "s")))
    if c["warning"]:
        bits.append(st.yellow("%d warning%s" % (c["warning"], "" if c["warning"] == 1 else "s")))
    if c["tip"]:
        bits.append(st.green("%d tip%s" % (c["tip"], "" if c["tip"] == 1 else "s")))
    status = st.green("BUILD OK") if report.build_ok else st.red("BUILD FAILED")
    out.append(" Result: %s - %s" % (status, ", ".join(bits) if bits else "nothing to fix"))
    if stx.get("compiler_messages"):
        out.append(st.dim(" The compiler printed %d message(s); CEDT traced them to %d root problem(s)." % (
            stx["compiler_messages"], stx.get("root_problems", 0))))
    out.append(" Phases: " + pipeline_line(report, st))
    out.append(st.bold(bar))
    for p in report.parse_errors:
        if p.startswith("line "):
            continue
        out.append(st.yellow(" ! ") + p)
    if show_raw and report.raw_output.strip():
        out.append("")
        out.append(st.bold(" What the compiler printed:"))
        for l in report.raw_output.rstrip("\n").split("\n"):
            out.append("   " + st.dim(l))
    roots = ordered_roots(report)
    for i, e in enumerate(roots, 1):
        out.append("")
        lvl = {"error": "ERROR", "warning": "WARNING", "tip": "TIP", "info": "NOTE"}.get(e.level, e.level.upper())
        head = "[%d] %s  %s" % (i, lvl, re.sub(r"`", "", e.title))
        phase = PHASE_NAMES.get(e.phase, e.phase)
        pad = max(1, WIDTH - len(head) - len(phase) - 2)
        out.append(st.level(e.level, "[%d] %s" % (i, lvl)) + "  " + st.bold(re.sub(r"`", "", e.title)) + " " * pad + st.dim(phase))
        loc = ""
        if e.location and e.location.line:
            f = os.path.basename(e.location.file.replace("\\", "/"))
            if e.real_line and e.real_line != e.location.line:
                loc = "%s line %d   (the compiler pointed at line %d)" % (f, e.real_line, e.location.line)
            else:
                loc = "%s line %d" % (f, e.location.line)
        elif e.source == "runtime":
            loc = "while the program was running"
        if loc:
            out.append("    " + st.dim(loc))
        lines = source_lines(report, e)
        focus = e.real_line or (e.location.line if e.location else None)
        if focus and lines and 0 < focus <= len(lines) and not brief:
            lo = max(1, focus - 1)
            hi = min(len(lines), focus + 1)
            for n in range(lo, hi + 1):
                mark = st.level(e.level, ">") if n == focus else " "
                out.append("    %s %4d | %s" % (mark, n, lines[n - 1].rstrip()))
        out.append("")
        out.append(st.code(wrap(e.what, "    ")))
        for h in e.hints:
            out.append(st.code(wrap("* " + h, "    ")))
        if e.fix:
            out.append(st.bold("    How to fix:"))
            out.append(bullet(e.fix, "      ", st))
        if e.fixed_line is not None and e.fixed_line_no:
            n = e.fixed_line_no
            old = lines[n - 1] if lines and 0 < n <= len(lines) else None
            if e.fixed_kind == "insert_before":
                out.append(st.bold("    Add before line %d:" % n))
                out.append("      " + st.green("+ " + e.fixed_line))
            elif e.fixed_kind == "delete":
                out.append(st.bold("    Delete line %d:" % n))
                out.append("      " + st.red("- " + (old or "").rstrip()))
            else:
                out.append(st.bold("    Corrected line %d:" % n))
                if old is not None:
                    out.append("      " + st.red("- " + old.rstrip()))
                out.append("      " + st.green("+ " + e.fixed_line.rstrip()))
        if not brief:
            if e.why:
                out.append(st.bold("    Why this happens:"))
                out.append(bullet(e.why, "      ", st))
            if e.tip:
                out.append(st.code(wrap("Good to know: " + e.tip, "    ")))
            if e.jargon:
                out.append(st.dim("    Words used by the compiler:"))
                for j in e.jargon[:3]:
                    out.append(st.dim(wrap("%s = %s" % (j["term"], j["meaning"]), "      ")))
            out.append(st.dim("    Compiler said: ") + st.magenta(e.compiler_message[:WIDTH * 2]))
            if e.followers and show_followers:
                fol = [report.explanations[k] for k in e.followers]
                out.append(st.dim("    + %d more compiler message(s) caused by this problem (they should disappear "
                                  "after the fix):" % len(fol)))
                for f in fol[:8]:
                    out.append(st.dim("        . %s" % f.compiler_message[:WIDTH - 10]))
                if len(fol) > 8:
                    out.append(st.dim("        . ... and %d more" % (len(fol) - 8)))
    if report.run is not None and report.run.ran:
        r = report.run
        out.append("")
        out.append(st.bold(" Program output") + st.dim(" (%.0f ms, %s)" % (
            r.duration_ms, "timed out" if r.timed_out else r.signal_name or "exit code %s" % r.exit_code)))
        text = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        for l in (text.rstrip("\n").split("\n") if text.strip() else ["(no output)"])[:60]:
            out.append("   | " + l)
    if not roots:
        out.append("")
        out.append("  " + (st.green("No problems found - well done!") if report.build_ok else
                           "Nothing to explain."))
    if roots and any(e.level == "error" for e in roots):
        out.append("")
        out.append(st.dim(" Fix problem 1 first and compile again - later messages often change after the first fix."))
    out.append("")
    return "\n".join(out)
