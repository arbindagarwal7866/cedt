"""
handlers/base.py - the interface between the knowledge base and the
student's source code.

A rule in the knowledge base may name a *handler*.  The handler receives a
Context (the diagnostic, the regex groups, the analysed SourceFile ...)
and returns a Result that can:
    * add template variables      (vars)
    * add context-aware hints     (hints)
    * override the explanation    (title / what / why / fix)
    * point to the REAL line of the mistake (real_line)
    * propose a corrected line    (fixed_line)
    * veto the rule               (VETO -> the next matching rule is tried)
    * redirect to another rule    (redirect="S005")
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

REGISTRY = {}


def handler(name):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


@dataclass
class Result:
    vars: Dict[str, str] = field(default_factory=dict)
    hints: List[str] = field(default_factory=list)
    title: Optional[str] = None
    what: Optional[str] = None
    why: Optional[List[str]] = None
    fix: Optional[List[str]] = None
    example: Optional[Dict[str, str]] = None
    real_line: Optional[int] = None
    fixed_line: Optional[str] = None
    fixed_line_no: Optional[int] = None
    fixed_kind: Optional[str] = None
    confidence: Optional[str] = None
    veto: bool = False
    no_fix: bool = False          # suppress the compiler's own fix-it suggestion
    redirect: Optional[str] = None
    level: Optional[str] = None


def veto():
    return Result(veto=True)


class Context:
    def __init__(self, diag, groups, rule, src, lang, unit, all_diags, kbdata, files=None):
        self.diag = diag
        self.groups = dict(groups or {})
        self.rule = rule
        self.src = src
        self.lang = lang
        self.unit = unit
        self.all = all_diags or []
        self.data = kbdata or {}
        self.files = files or {}
        self._tok = "unset"

    # ----------------------------------------------------------- basics
    @property
    def cpp(self):
        return self.lang in ("c++", "cpp")

    @property
    def line_no(self):
        loc = self.diag.location
        return loc.line if loc and loc.line else None

    @property
    def col(self):
        loc = self.diag.location
        return loc.column if loc else None

    def line_text(self, n=None):
        n = self.line_no if n is None else n
        if self.src is not None:
            return self.src.line(n)
        info = self.diag.extra.get("snippet_info") or {}
        return (info.get("src") or {}).get(n, "")

    @property
    def tok(self):
        if self._tok == "unset":
            self._tok = None
            if self.src is not None and self.line_no:
                self._tok = self.src.token_at(self.line_no, self.col, self.unit)
        return self._tok

    def col_index(self):
        if self.src is None or not self.line_no:
            return (self.col or 1) - 1
        return self.src.col_to_index(self.line_no, self.col, self.unit)

    def prev(self, tok=None):
        tok = self.tok if tok is None else tok
        return self.src.prev_token(tok) if self.src is not None and tok is not None else None

    def nxt(self, tok=None):
        tok = self.tok if tok is None else tok
        return self.src.next_token(tok) if self.src is not None and tok is not None else None

    def note(self, regex):
        rx = re.compile(regex)
        for n in self.diag.notes:
            m = rx.search(n.message)
            if m:
                return n, m
        return None, None

    @property
    def symbols(self):
        return self.src.symbols if self.src is not None else None

    def other_diags(self, regex, origin=None):
        rx = re.compile(regex)
        out = []
        for d in self.all:
            if d is self.diag:
                continue
            if origin and d.origin != origin:
                continue
            m = rx.search(d.message)
            if m:
                out.append((d, m))
        return out

    # --------------------------------------------------------- knowledge
    def header_for(self, name):
        """Standard header that declares a C/C++ name (or None)."""
        d = self.data.get("stdlib", {})
        if self.cpp:
            h = d.get("cpp_std", {}).get(name)
            if h:
                return h
            h = d.get("c_functions", {}).get(name) or d.get("c_names", {}).get(name)
            if h:
                return "c" + h[:-2] if h.endswith(".h") and h.count("/") == 0 else h
            return None
        return d.get("c_functions", {}).get(name) or d.get("c_names", {}).get(name)

    def is_cpp_std_name(self, name):
        return name in self.data.get("stdlib", {}).get("cpp_std", {})

    def nonstandard(self, name):
        return self.data.get("stdlib", {}).get("nonstandard_functions", {}).get(name)

    def known_functions(self):
        d = self.data.get("stdlib", {})
        names = set(d.get("c_functions", {}))
        if self.cpp:
            names |= set(d.get("cpp_std", {}))
        if self.symbols is not None:
            names |= {s.name for s in self.symbols.functions()}
        return names


# ------------------------------------------------------------- helpers
def code(s):
    return "`%s`" % s


def insert_at(line, idx, text):
    idx = max(0, min(len(line), idx))
    return line[:idx] + text + line[idx:]


def replace_span(line, start, end, text):
    return line[:start] + text + line[end:]


def replace_word(line, old, new, near=None):
    """Replace one whole-word occurrence of old (closest to index near)."""
    spots = [m.start() for m in re.finditer(r"(?<![\w])%s(?![\w])" % re.escape(old), line)]
    if not spots:
        return None
    if near is not None:
        spots.sort(key=lambda s: abs(s - near))
    s = spots[0]
    return line[:s] + new + line[s + len(old):]


def call_args(src, name_tok):
    """Argument token lists of the call name_tok( ... )."""
    if src is None or name_tok is None:
        return None
    op = src.next_token(name_tok)
    if op is None or not op.is_op("("):
        return None
    close = src.brackets.match.get(op.index)
    if close is None:
        return None
    args, cur, depth = [], [], 0
    for t in src.tokens[op.index + 1:close]:
        if t.is_op("(", "[", "{"):
            depth += 1
        elif t.is_op(")", "]", "}"):
            depth -= 1
        if t.is_op(",") and depth == 0:
            args.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur or args:
        args.append(cur)
    return args


def find_call(src, line_no, names, near_col=None):
    """Token of a call to one of `names` on a line (closest to near_col)."""
    if src is None:
        return None
    best = None
    for t in src.tokens_on_line(line_no):
        if t.kind == "id" and t.text in names:
            n = src.next_token(t)
            if n is not None and n.is_op("("):
                if best is None or (near_col is not None and abs(t.col - near_col) < abs(best.col - near_col)):
                    best = t
    if best is None:
        # the call may have started on an earlier line
        for t in reversed([x for x in src.tokens if x.line < line_no][-40:]):
            if t.kind == "id" and t.text in names and src.next_token(t) is not None \
                    and src.next_token(t).is_op("("):
                close = src.brackets.match.get(t.index + 1)
                if close is not None and src.tokens[close].line >= line_no:
                    return t
    return best


def text_of(tokens):
    out = ""
    prev = None
    for t in tokens:
        if prev is not None and (t.pos > prev.end):
            out += " "
        out += t.text
        prev = t
    return out
