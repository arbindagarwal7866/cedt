"""
diag_parser.py - SYNTAX ANALYSIS of compiler output.

The tokens produced by diag_lexer are parsed with the LL(1) grammar below.
Action symbols (@name) are executed during parsing (syntax-directed
translation) and build a tree of Diagnostic objects:

    error  ──┬── snippet lines (source / caret / fix-it)
             ├── note ── snippet lines
             └── note ── snippet lines

Run  `python cedt.py --grammar`  to print FIRST/FOLLOW sets and the
predictive parsing table that ll1.Grammar computes from this grammar.
"""
import re

from . import diag_lexer as L
from .ll1 import Grammar, LL1Parser
from .models import Diagnostic, Location

# ---------------------------------------------------------------------------
# The grammar of compiler output (terminals are diag_lexer token types).
# ---------------------------------------------------------------------------
GRAMMAR_RULES = [
    ("Output",    "Item Output"),
    ("Output",    "ε"),
    ("Item",      "Diag"),
    ("Item",      "CTX @ctx"),
    ("Item",      "LD_CTX @ld_ctx"),
    ("Item",      "LD_ERR @ld_err LldRefs"),
    ("Item",      "LD_SUMMARY @ld_sum"),
    ("Item",      "MAC_HDR @mac_hdr MacSyms"),
    ("Item",      "MAC_DUP @mac_dup MacRefs"),
    ("Item",      "DRIVER @driver"),
    ("Item",      "SUMMARY @summary"),
    ("Item",      "TEXT @text"),
    ("Diag",      "Head Snip Followers"),
    ("Head",      "ERROR @diag"),
    ("Head",      "FATAL @diag"),
    ("Head",      "WARNING @diag"),
    ("Snip",      "SNIP @snip Snip"),
    ("Snip",      "ε"),
    ("Followers", "NOTE @note Snip Followers"),
    ("Followers", "ε"),
    ("LldRefs",   "LLD_REF @lld_ref LldRefs"),
    ("LldRefs",   "ε"),
    ("MacSyms",   "MAC_SYM @mac_sym MacRefs MacSyms"),
    ("MacSyms",   "ε"),
    ("MacRefs",   "MAC_REF @mac_ref MacRefs"),
    ("MacRefs",   "ε"),
]

_GRAMMAR = None


def grammar():
    global _GRAMMAR
    if _GRAMMAR is None:
        _GRAMMAR = Grammar("Output", GRAMMAR_RULES)
    return _GRAMMAR


# ---------------------------------------------------------------------------
# Snippet analysis: GCC >= 9 / Clang >= 15 print a "gutter"
#     4 |     printf("hi")
#       |                 ^
#       |                 ;
# older compilers print the bare source line and a caret line.
# ---------------------------------------------------------------------------
RE_GUTTER_SRC = re.compile(r"^\s*(?P<num>\d+) \|(?: (?P<code>.*))?$")
RE_GUTTER_ANN = re.compile(r"^\s*\|(?: ?(?P<code>.*))?$")
RE_GUTTER_INS = re.compile(r"^\s*\+\+\+ \|\+(?P<code>.*)$")
RE_CARET = re.compile(r"^[ \t~^]*\^[ \t~^]*$")


def _caret_span(code):
    col0 = code.index("^")
    start = col0
    while start > 0 and code[start - 1] in "~^":
        start -= 1
    end = col0
    while end < len(code) and code[end] in "~^":
        end += 1
    return col0, start, end - start


def analyze_snippet(lines, diag_line=None):
    info = {"src": {}, "caret": None, "fixit": None, "inserts": []}
    if not lines:
        return info
    gutter = any(RE_GUTTER_SRC.match(l) or RE_GUTTER_ANN.match(l) for l in lines)
    prev = None
    if gutter:
        for l in lines:
            m = RE_GUTTER_INS.match(l)
            if m:
                info["inserts"].append(m.group("code"))
                prev = "ins"
                continue
            m = RE_GUTTER_SRC.match(l)
            if m:
                info["src"][int(m.group("num"))] = m.group("code") or ""
                prev = "src"
                continue
            m = RE_GUTTER_ANN.match(l)
            if not m:
                prev = None
                continue
            code = m.group("code") or ""
            if info["caret"] is None and RE_CARET.match(code):
                col0, start, length = _caret_span(code)
                info["caret"] = {"col": col0 + 1, "start": start + 1, "len": length}
                prev = "caret"
                continue
            if (prev == "caret" and info["fixit"] is None and code.strip()
                    and "|" not in code and "^" not in code
                    and not set(code.strip()) <= set("~ ")):
                info["fixit"] = {"col": len(code) - len(code.lstrip()) + 1,
                                 "text": code.strip()}
            prev = "ann"
    else:
        # classic style: source line, caret line, optional fix-it line
        if diag_line is not None and not RE_CARET.match(lines[0]):
            info["src"][diag_line] = lines[0]
        for i, l in enumerate(lines):
            if info["caret"] is None and RE_CARET.match(l):
                col0, start, length = _caret_span(l)
                info["caret"] = {"col": col0 + 1, "start": start + 1, "len": length}
                if i + 1 < len(lines):
                    nxt = lines[i + 1]
                    if (nxt.strip() and "^" not in nxt
                            and not set(nxt.strip()) <= set("~ ")):
                        info["fixit"] = {"col": len(nxt) - len(nxt.lstrip()) + 1,
                                         "text": nxt.strip()}
                break
    return info


# ---------------------------------------------------------------------------
# Semantic actions (syntax-directed translation)
# ---------------------------------------------------------------------------
def _strip_mac_underscore(sym):
    # Apple's linker shows C symbols with a leading underscore: _main -> main
    if re.match(r"^_[A-Za-z_]\w*$", sym):
        return sym[1:]
    return sym


class DiagnosticBuilder:
    def __init__(self):
        self.diagnostics = []
        self.current = None        # top-level diagnostic receiving notes
        self.snip_target = None    # diagnostic or note receiving snippet lines
        self.context = None
        self.ld_context = None
        self.mac_target = None
        self.mac_arch = None
        self.ld_current = None
        self.summaries = []
        self.other_lines = []
        self._index = 0

    # helpers -----------------------------------------------------------
    def _new(self, **kw):
        d = Diagnostic(**kw)
        d.index = self._index
        self._index += 1
        return d

    def _from_token(self, tok):
        a = tok.attrs
        d = self._new(severity=a["severity"], message=a["message"],
                      location=Location(a["file"], a["line"], a["col"]),
                      flag=a.get("flag"), origin="compiler")
        d.include_trace = [Location(f, ln) for f, ln in a.get("include_trace", [])]
        d.instantiation_trace = list(a.get("instantiation_trace", []))
        d.raw_lines.append(tok.raw or tok.text)
        return d

    # actions -----------------------------------------------------------
    def a_diag(self, tok):
        d = self._from_token(tok)
        if self.context and self.context[0] == d.location.file:
            d.context = self.context[1]
        self.diagnostics.append(d)
        self.current = d
        self.snip_target = d

    def a_note(self, tok):
        n = self._from_token(tok)
        if self.current is None:          # cannot happen with this grammar
            self.diagnostics.append(n)
            self.current = n
        else:
            self.current.notes.append(n)
            self.current.raw_lines.extend(n.raw_lines)
        self.snip_target = n

    def a_snip(self, tok):
        if self.snip_target is not None:
            self.snip_target.snippet.append(tok.text)
            if self.current is not None:
                self.current.raw_lines.append(tok.raw or tok.text)

    def a_ctx(self, tok):
        what = tok.attrs["what"]
        if what.startswith("At "):
            self.context = None
        else:
            self.context = (tok.attrs["file"], what)
        self.current = None

    def a_ld_ctx(self, tok):
        self.ld_context = tok.attrs
        self.current = None

    def a_ld_err(self, tok):
        a = tok.attrs
        msg = a.get("msg", tok.text)
        if a.get("kind") == "undefined" and a.get("symbol"):
            msg = "undefined reference to '%s'" % a["symbol"]
        elif a.get("kind") == "multiple" and a.get("symbol"):
            msg = "multiple definition of '%s'" % a["symbol"]
        loc = None
        obj = a.get("obj") or ""
        m = re.search(r"(?P<file>[^:\\/]+\.(?:c|cc|cpp|cxx|C|h|hpp))(?::(?P<line>\d+))?:?$",
                      obj.strip())
        if m:
            loc = Location(m.group("file"), int(m.group("line") or 0), None)
        d = self._new(severity=a.get("severity", "error"), message=msg, location=loc,
                      origin="linker", symbol=a.get("symbol"))
        d.extra["kind"] = a.get("kind")
        d.extra["refs"] = []
        if self.ld_context:
            d.context = "in function '%s'" % self.ld_context["func"]
            d.extra["caller"] = self.ld_context["func"]
            d.raw_lines.append(self.ld_context.get("_raw", ""))
        d.raw_lines.append(tok.raw or tok.text)
        d.raw_lines = [r for r in d.raw_lines if r]
        self.diagnostics.append(d)
        self.ld_current = d
        self.current = None

    def a_lld_ref(self, tok):
        if self.ld_current is not None:
            ref = tok.attrs["ref"]
            self.ld_current.extra["refs"].append(ref)
            self.ld_current.raw_lines.append(tok.raw or tok.text)
            m = re.match(r"referenced by (?P<file>[^:]+):(?P<line>\d+)", ref)
            if m and self.ld_current.location is None:
                self.ld_current.location = Location(m.group("file"), int(m.group("line")))

    def a_ld_sum(self, tok):
        d = self._new(severity="error", message=tok.attrs.get("msg", tok.text),
                      origin="linker")
        d.extra["kind"] = "summary"
        d.raw_lines.append(tok.raw or tok.text)
        self.diagnostics.append(d)
        self.current = None

    def a_mac_hdr(self, tok):
        self.mac_arch = tok.attrs["arch"]
        self.mac_target = None
        self.current = None

    def a_mac_sym(self, tok):
        sym = _strip_mac_underscore(tok.attrs["symbol"])
        d = self._new(severity="error", message="undefined reference to '%s'" % sym,
                      origin="linker", symbol=sym)
        d.extra["kind"] = "undefined"
        d.extra["refs"] = []
        d.extra["arch"] = self.mac_arch
        d.raw_lines.append(tok.raw or tok.text)
        self.diagnostics.append(d)
        self.mac_target = d

    def a_mac_dup(self, tok):
        sym = _strip_mac_underscore(tok.attrs["symbol"])
        d = self._new(severity="error", message="multiple definition of '%s'" % sym,
                      origin="linker", symbol=sym)
        d.extra["kind"] = "multiple"
        d.extra["refs"] = []
        d.raw_lines.append(tok.raw or tok.text)
        self.diagnostics.append(d)
        self.mac_target = d
        self.current = None

    def a_mac_ref(self, tok):
        if self.mac_target is not None:
            ref = tok.attrs["ref"]
            self.mac_target.extra["refs"].append(ref)
            self.mac_target.raw_lines.append(tok.raw or tok.text)
            m = re.match(r"^_?(?P<func>\w+) in ", ref)
            if m and "caller" not in self.mac_target.extra:
                self.mac_target.extra["caller"] = m.group("func")

    def a_driver(self, tok):
        a = tok.attrs
        d = self._new(severity=a["severity"], message=a["message"], origin="driver")
        d.extra["prog"] = a["prog"]
        d.raw_lines.append(tok.raw or tok.text)
        self.diagnostics.append(d)
        self.current = None

    def a_summary(self, tok):
        self.summaries.append(tok.text)
        self.current = None

    def a_text(self, tok):
        self.other_lines.append(tok.text)

    # panic-mode recovery hook: keep information from skipped tokens
    def on_skip(self, tok):
        if tok.type == L.NOTE:
            n = self._from_token(tok)
            n.extra["orphan"] = True
            self.diagnostics.append(n)
            self.current = n
            self.snip_target = n
        elif tok.type == L.SNIP and self.snip_target is not None:
            self.snip_target.snippet.append(tok.text)
        elif tok.type in (L.MAC_SYM, L.MAC_REF, L.LLD_REF):
            self.other_lines.append(tok.text)

    def actions(self):
        return {
            "@diag": self.a_diag, "@note": self.a_note, "@snip": self.a_snip,
            "@ctx": self.a_ctx, "@ld_ctx": self.a_ld_ctx, "@ld_err": self.a_ld_err,
            "@lld_ref": self.a_lld_ref, "@ld_sum": self.a_ld_sum,
            "@mac_hdr": self.a_mac_hdr, "@mac_sym": self.a_mac_sym,
            "@mac_dup": self.a_mac_dup, "@mac_ref": self.a_mac_ref,
            "@driver": self.a_driver, "@summary": self.a_summary, "@text": self.a_text,
        }


class ParseResult:
    def __init__(self, diagnostics, tokens, outcome, builder):
        self.diagnostics = diagnostics
        self.tokens = tokens
        self.outcome = outcome
        self.errors = outcome.errors
        self.summaries = builder.summaries
        self.other_lines = builder.other_lines

    def flat(self):
        """All top-level diagnostics (notes stay nested)."""
        return list(self.diagnostics)


def detect_compiler_family(text):
    if re.search(r"^\d+ (?:error|warning)s?.* generated\.$", text, re.M) or \
            "linker command failed" in text or "Undefined symbols for architecture" in text \
            or "use of undeclared identifier" in text:
        return "clang"
    if re.search(r": In function '|compilation terminated\.|collect2|was not declared in this scope|"
                 r"undeclared \(first use", text):
        return "gcc"
    return "unknown"


def parse_compiler_output(text, trace=False):
    """Lex + parse compiler output.  Returns a ParseResult."""
    tokens = L.tokenize(text)
    builder = DiagnosticBuilder()
    # remember the raw line of each linker context so it can be shown later
    for t in tokens:
        if t.type == L.LD_CTX:
            t.attrs["_raw"] = t.raw or t.text
    parser = LL1Parser(grammar(), builder.actions(), on_skip=builder.on_skip)
    outcome = parser.parse(tokens, trace=trace)
    for d in builder.diagnostics:
        _post_process(d)
    return ParseResult(builder.diagnostics, tokens, outcome, builder)


def _post_process(d):
    line = d.location.line if d.location else None
    d.extra["snippet_info"] = analyze_snippet(d.snippet, line)
    for n in d.notes:
        n.extra["snippet_info"] = analyze_snippet(n.snippet, n.location.line if n.location else None)
