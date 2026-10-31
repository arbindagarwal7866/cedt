"""
translator.py - the INTERPRETATION LAYER itself.

    raw compiler output
        -> diag_parser   (lexical + LL(1) syntax analysis of the output)
        -> for every diagnostic:
               knowledge-base lookup (regex rules, GCC + Clang wording)
               handler: context analysis of the student's source code
               template filling -> Explanation
        -> prechecks      (beginner mistakes the compiler is silent about)
        -> cascade        (root cause vs. follow-on errors)
"""
import os
import re
import time

from . import kb as kbmod
from .diag_parser import parse_compiler_output
from .handlers import REGISTRY, Context, Result
from .models import Explanation, Location
from .source import SourceFile, virtual_source

PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
SYSTEM_PREFIXES = ("/usr/", "/Library/", "/Applications/Xcode", "/opt/", "C:/msys", "C:/Program",
                   "C:\\Program", "C:\\msys", "/nix/", "<built-in>", "<command-line>")


def fill(template, values):
    if template is None:
        return None

    def rep(m):
        key = m.group(1)
        if key in values and values[key] is not None:
            return str(values[key])
        return "?"
    return PLACEHOLDER.sub(rep, template)


ARTICLE_RE = re.compile(r"\b([Aa]) (`(?:int|unsigned|unsigned int|array|int \*|long unsigned|enum)\b)")


def fix_articles(e):
    """'a `int`' -> 'an `int`' in all text fields of an explanation."""
    def f(t):
        return ARTICLE_RE.sub(lambda m: ("An " if m.group(1) == "A" else "an ") + m.group(2), t) if t else t
    e.title = f(e.title)
    e.what = f(e.what)
    e.why = [f(x) for x in e.why]
    e.fix = [f(x) for x in e.fix]
    e.hints = [f(x) for x in e.hints]


def level_for(diag):
    if diag.severity in ("error", "fatal error"):
        return "error"
    if diag.severity == "warning":
        return "warning"
    return "info"


def guess_phase(diag):
    m = diag.message
    if diag.origin == "linker":
        return "linker"
    if diag.origin == "driver":
        return "preprocessor"
    if re.search(r"#\w+|header|include|macro", m):
        return "preprocessor"
    if re.search(r"stray|escape|terminat|constant|suffix|character", m):
        return "lexical"
    if re.search(r"^expected |before .* token|at end of input|syntax", m):
        return "syntax"
    if re.search(r"uninitiali|reaches end|fall through|unused|never|always", m):
        return "flow"
    return "semantic"


def is_system_path(path):
    if not path:
        return False
    p = path.replace("\\", "/")
    return p.startswith(tuple(s.replace("\\", "/") for s in SYSTEM_PREFIXES)) or "/include/" in p and p.startswith("/")


def apply_compiler_fixit(src_line, info, message):
    """Turn the compiler's visual fix-it hint into a corrected source line."""
    if not src_line or not info:
        return None
    caret, fix = info.get("caret"), info.get("fixit")
    if not caret or not fix:
        return None
    text = fix["text"]
    if "  " in text or len(text) > 40:
        return None
    disp = src_line.expandtabs(8)
    fcol = fix["col"] - 1
    start = caret["start"] - 1
    length = caret["len"]
    replace = ("did you mean" in message or "suggested alternative" in message
               or text.startswith("%") or "did you mean to use" in message)
    if replace:
        s = min(fcol, start)
        if s > len(disp):
            return None
        new = disp[:s] + text + disp[s + length:]
    else:
        if fcol > len(disp):
            fcol = len(disp)
        before, after = disp[:fcol], disp[fcol:]
        if text[-1:].isalnum() and after[:1].isalnum():
            text = text + " "
        if text[:1].isalnum() and before[-1:].isalnum():
            text = " " + text
        new = before + text + after
    if new == disp:
        return None
    return new


class Translator:
    def __init__(self, knowledge_base=None):
        self.kb = knowledge_base or kbmod.load()
        terms = self.kb.data.get("glossary", {}).get("terms", [])
        self.glossary = [(t, re.compile(t["match"], re.I)) for t in terms]

    # ------------------------------------------------------------------
    def explain(self, raw_output, sources=None, lang="c", unit="byte", run_prechecks=True):
        t0 = time.perf_counter()
        parse = parse_compiler_output(raw_output)
        t1 = time.perf_counter()
        self.lang = lang
        self.unit = unit
        self.files = {}
        for path, text in (sources or {}).items():
            sf = SourceFile(path, text, lang)
            self.files[path] = sf
            self.files.setdefault(os.path.basename(path), sf)
        t2 = time.perf_counter()
        self.all_diags = parse.diagnostics
        exps = []
        for d in parse.diagnostics:
            if d.severity == "note" and not d.extra.get("orphan"):
                continue
            if d.location and is_system_path(d.location.file) and self.find_source(d) is None:
                d.extra["system"] = True
            exps.append(self.explain_diag(d))
        t3 = time.perf_counter()
        if run_prechecks:
            from . import prechecks
            for path, sf in (sources or {}).items():
                exps.extend(prechecks.run(self.files[path], lang, exps, self.kb))
        from . import cascade
        cascade.analyze(exps, self.files)
        for i, e in enumerate(exps):
            e.id = i
        t4 = time.perf_counter()
        self.timings = {"parse_ms": (t1 - t0) * 1000, "source_analysis_ms": (t2 - t1) * 1000,
                        "rules_ms": (t3 - t2) * 1000, "prechecks_cascade_ms": (t4 - t3) * 1000}
        return exps, parse

    # ------------------------------------------------------------------
    def find_source(self, d):
        if not d.location or not d.location.file:
            if len(self.files) >= 1 and d.origin == "linker":
                return next(iter(self.files.values()))
            return None
        f = d.location.file
        if f in self.files:
            return self.files[f]
        b = os.path.basename(f.replace("\\", "/"))
        if b in self.files:
            return self.files[b]
        if d.origin == "linker" and self.files:
            # e.g. MinGW: "crtexewin.c:67: undefined reference to `WinMain'" points into the C runtime,
            # but the mistake (missing / misspelled main) is in the student's own file
            return next(iter(self.files.values()))
        return None

    def source_for(self, d):
        sf = self.find_source(d)
        if sf is not None or d.location is None:
            return sf
        if d.extra.get("system"):
            return None
        info = d.extra.get("snippet_info") or {}
        lines = dict(info.get("src") or {})
        for n in d.notes:
            if n.location and n.location.file == d.location.file:
                lines.update((n.extra.get("snippet_info") or {}).get("src") or {})
        if lines:
            vs = virtual_source(d.location.file, lines, self.lang)
            self.files[d.location.file] = vs
            return vs
        return None

    def explain_diag(self, d):
        src = self.source_for(d)
        if d.extra.get("system") and d.origin == "compiler":
            return self.library_internal(d)
        cands = self.kb.candidates(d.message, self.lang, d.origin)
        for rule, groups in cands:
            res = self.run_handler(rule, groups, d, src)
            if res is None or res.veto:
                continue
            if res.redirect:
                target = self.kb.get(res.redirect)
                if target is not None:
                    res2 = self.run_handler(target, dict(groups, **res.vars), d, src)
                    if res2 is not None and not res2.veto:
                        res2.vars = dict(res.vars, **res2.vars)
                        res2.hints = res.hints + res2.hints
                        return self.build(target, dict(groups), res2, d, src)
                continue
            return self.build(rule, groups, res, d, src)
        return self.generic(d, src)

    def run_handler(self, rule, groups, d, src):
        if not rule.handler:
            return Result()
        fn = REGISTRY.get(rule.handler)
        if fn is None:
            return Result(confidence="medium")
        ctx = Context(d, groups, rule, src, self.lang, self.unit, self.all_diags, self.kb.data, self.files)
        try:
            return fn(ctx)
        except Exception as exc:          # a handler bug must never hide an explanation
            r = Result(confidence="medium")
            r.vars["_handler_error"] = repr(exc)
            return r

    def base_vars(self, d):
        loc = d.location
        return {"line": loc.line if loc and loc.line else "?",
                "col": loc.column if loc and loc.column else "?",
                "file": loc.file if loc else "?",
                "message": d.message, "flag": d.flag or ""}

    def build(self, rule, groups, res, d, src):
        values = self.base_vars(d)
        values.update(groups)
        values.update({k: v for k, v in res.vars.items() if v is not None})
        ex = res.example or rule.example or {}
        e = Explanation(
            rule_id=rule.id,
            title=fill(res.title or rule.title, values),
            phase=rule.phase,
            level=res.level or rule.level or level_for(d),
            what=fill(res.what or rule.what, values),
            why=[fill(x, values) for x in (res.why if res.why is not None else rule.why)],
            fix=[fill(x, values) for x in (res.fix if res.fix is not None else rule.fix)],
            hints=[fill(h, values) for h in res.hints],
            tip=fill(rule.tip, values) if rule.tip else "",
            example_wrong=ex.get("wrong"),
            example_right=ex.get("right"),
            location=d.location,
            diagnostic=d,
            compiler_message=self.compiler_text(d),
            confidence=res.confidence or "high",
        )
        subj = res.vars.get("name") or groups.get("name") or groups.get("symbol") or res.vars.get("symbol") \
            or groups.get("member") or res.vars.get("macro")
        e.subject = str(subj) if subj else None
        loc_line = d.location.line if d.location and d.location.line else None
        if res.real_line and res.real_line != loc_line:
            e.real_line = res.real_line
        if res.fixed_line is not None:
            e.fixed_line = res.fixed_line
            e.fixed_line_no = res.fixed_line_no or res.real_line or loc_line
            e.fixed_kind = res.fixed_kind or "replace"
        elif src is not None and loc_line and d.origin == "compiler" and not res.no_fix:
            fixed = apply_compiler_fixit(src.line(loc_line), d.extra.get("snippet_info"), d.message)
            if fixed is not None:
                e.fixed_line = fixed
                e.fixed_line_no = loc_line
        e.jargon = self.jargon(d.message)
        fix_articles(e)
        return e

    def generic(self, d, src):
        phase = guess_phase(d)
        values = self.base_vars(d)
        m = re.match(r"expected (?P<exp>.+?) before (?P<got>.+)$", d.message)
        fix = ["Look at line {line}, column {col}: the problem is at that position or just before it.",
               "Fix the FIRST error in the list first - later errors are often side effects of it."]
        what = "The compiler reported: \"{message}\". There is no specific explanation for this message yet, so here is how to read it."
        if m:
            values["exp"] = m.group("exp")
            values["got"] = m.group("got")
            what = ("The parser expected {exp} but found {got} instead. Something just before this point is missing "
                    "or written in the wrong order.")
        e = Explanation(
            rule_id="G000", title="Compiler message: " + d.message[:70],
            phase=phase, level=level_for(d),
            what=fill(what, values), fix=[fill(x, values) for x in fix],
            location=d.location, diagnostic=d, compiler_message=self.compiler_text(d),
            confidence="low")
        if src is not None and d.location and d.location.line:
            fixed = apply_compiler_fixit(src.line(d.location.line), d.extra.get("snippet_info"), d.message)
            if fixed:
                e.fixed_line = fixed
                e.fixed_line_no = d.location.line
        e.jargon = self.jargon(d.message)
        return e

    def library_internal(self, d):
        values = self.base_vars(d)
        e = Explanation(
            rule_id="G001", title="Message from inside the standard library",
            phase="semantic", level=level_for(d),
            what=("This message points into the compiler's own library files (`%s`), not into your program. "
                  "It is a consequence of a mistake in YOUR code - almost always the error reported just before it."
                  % d.location.file),
            fix=["Fix the error in your own file that comes before this one; this message will then disappear."],
            location=d.location, diagnostic=d, compiler_message=self.compiler_text(d), confidence="medium")
        e.jargon = self.jargon(d.message)
        return e

    def compiler_text(self, d):
        if d.raw_lines:
            first = [r for r in d.raw_lines if r.strip()]
            if first:
                from .textutil import strip_ansi
                return strip_ansi(first[0]).rstrip()
        loc = d.location.short() + ": " if d.location else ""
        return "%s%s: %s" % (loc, d.severity, d.message)

    def jargon(self, message):
        out = []
        for t, rx in self.glossary:
            if rx.search(message):
                out.append({"term": t["term"], "meaning": t["meaning"]})
        return out[:4]
