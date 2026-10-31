"""
diag_lexer.py - LEXICAL ANALYSIS of compiler output.

The raw text printed by GCC / Clang / the linker is turned into a stream of
tokens - one token per output line - exactly like a Lex scanner:

  * every token class is described by a regular expression;
  * the rules are tried in a fixed priority order (first match wins, as in
    Lex when two rules match the same length);
  * the scanner has START CONDITIONS (Lex's %x states): after a diagnostic
    line we are in SNIPPET state, where otherwise-unknown lines are source
    snippet / caret lines; after "Undefined symbols for architecture ..." we
    are in MACLINK state, etc.

Token types are the TERMINALS of the LL(1) grammar in diag_parser.py.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List

from .textutil import clean_line

# ---------------------------------------------------------------- terminals
ERROR = "ERROR"          # file:line:col: error: ...
FATAL = "FATAL"          # file:line:col: fatal error: ...
WARNING = "WARNING"      # file:line:col: warning: ...
NOTE = "NOTE"            # file:line:col: note: ...
SNIP = "SNIP"            # source snippet / caret / fix-it line
CTX = "CTX"              # file: In function 'main':
LD_CTX = "LD_CTX"        # /usr/bin/ld: x.o: in function `main':
LD_ERR = "LD_ERR"        # x.c:(.text+0x1e): undefined reference to `foo'
LLD_REF = "LLD_REF"      # >>> referenced by x.c   (LLVM lld)
LD_SUMMARY = "LD_SUMMARY"  # collect2: error: ld returned 1 exit status
MAC_HDR = "MAC_HDR"      # Undefined symbols for architecture arm64:
MAC_DUP = "MAC_DUP"      # duplicate symbol '_x' in:
MAC_SYM = "MAC_SYM"      #   "_foo", referenced from:
MAC_REF = "MAC_REF"      #       _main in prog.o
DRIVER = "DRIVER"        # gcc: error: prog.c: No such file or directory
SUMMARY = "SUMMARY"      # 2 errors generated. / compilation terminated.
TEXT = "TEXT"            # anything else
EOF = "$"

TERMINALS = [ERROR, FATAL, WARNING, NOTE, SNIP, CTX, LD_CTX, LD_ERR, LLD_REF,
             LD_SUMMARY, MAC_HDR, MAC_DUP, MAC_SYM, MAC_REF, DRIVER, SUMMARY,
             TEXT]

# ---------------------------------------------------------- start conditions
INITIAL, SNIPPET, MACLINK, LLDREF = "INITIAL", "SNIPPET", "MACLINK", "LLDREF"

# --------------------------------------------------------- regular patterns
# A file name: optional Windows drive ("C:") followed by anything but ':'
FILE = r"(?P<file>(?:[A-Za-z]:)?[^:\n]+?)"

RE_INC_START = re.compile(
    r"^In file included from " + FILE + r":(?P<line>\d+)(?::(?P<col>\d+))?[,:]$")
RE_INC_CONT = re.compile(
    r"^\s+from " + FILE + r":(?P<line>\d+)(?::(?P<col>\d+))?[,:]$")
RE_INST = re.compile(
    r"^" + FILE + r":(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<what>(?:recursively )?required (?:from|by) .+)$")
RE_DIAG = re.compile(
    r"^" + FILE + r":(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
    r"(?P<sev>fatal error|error|warning|note|remark|Error|Warning):\s?(?P<msg>.*)$")
RE_FLAG = re.compile(r"\s\[(?P<flag>-(?:W|f|pedantic)[^\]]*)\]$")
RE_CTX = re.compile(
    r"^" + FILE + r": (?P<what>(?:In (?:function|member function|static member function|"
    r"constructor|destructor|copy constructor|lambda function|instantiation of|"
    r"substitution of|function template|static function|"
    r"member function template|requirements)\b.*|At (?:global scope|top level))):$")
RE_LD_PREFIX = re.compile(
    r"^(?P<ld>(?:[A-Za-z]:)?(?:[^:]*[/\\])?(?:ld|ld\.exe|ld\.bfd|ld\.gold|ld\.lld|"
    r"ld64\.lld|ld64|lld|lld-link|ld-classic)): (?P<rest>.*)$")
RE_LD_IN_FUNCTION = re.compile(r"^(?P<obj>.+): in function '(?P<func>.+)':$")
RE_LD_SECTION = re.compile(
    r"^(?P<obj>.*?)\((?P<section>\.[^)+\s]+)(?:\+0x[0-9a-fA-F]+)?\): (?P<msg>.+)$")
RE_LD_SUMMARY = [
    re.compile(r"^collect2(?:\.exe)?: error: ld returned (?P<code>\d+) exit status$"),
    re.compile(r"^(?P<prog>\S*?(?:clang|clang\+\+|gcc|g\+\+|cc|c\+\+)(?:-[\d.]+)?(?:\.exe)?):"
               r" error: linker command failed with exit code (?P<code>\d+).*$"),
]
RE_LD_REST_SUMMARY = [
    re.compile(r"^symbol\(s\) not found for architecture (?P<arch>\S+)$"),
    re.compile(r"^(?P<n>\d+) duplicate symbols?(?: for architecture (?P<arch>\S+))?$"),
]
RE_LLD_ERR = re.compile(r"^error: (?P<msg>(?:undefined|duplicate) symbol: (?P<sym>.+))$")
RE_MAC_HDR = re.compile(r"^Undefined symbols for architecture (?P<arch>\S+):$")
RE_MAC_DUP = re.compile(r"^duplicate symbol '?(?P<sym>.+?)'? in:$")
RE_MAC_SYM = re.compile(r'^\s+"(?P<sym>.+)", referenced from:$')
RE_MAC_REF = re.compile(r"^\s+(?P<ref>\S.*)$")
RE_DRIVER = re.compile(
    r"^(?P<prog>(?:[A-Za-z]:)?(?:[^:\s]*[/\\])?(?:gcc|g\+\+|cc|c\+\+|clang|clang\+\+|"
    r"cc1|cc1plus|collect2|[\w.-]+-gcc|[\w.-]+-g\+\+)(?:-[\d.]+)?(?:\.exe)?):"
    r" (?P<sev>fatal error|error|warning|note): (?P<msg>.*)$")
RE_SUMMARY = re.compile(
    r"^(?:\d+ (?:error|warning)s? (?:and \d+ (?:error|warning)s? )?generated\.|"
    r"compilation terminated\.|"
    r"cc1(?:plus)?(?:\.exe)?: (?:some|all) warnings being treated as errors)$")
RE_LLD_REF = re.compile(r"^>>> (?P<ref>.*)$")

# message fragments inside linker lines
RE_UNDEF = re.compile(r"undefined reference to '(?P<sym>.+?)'")
RE_MULTI = re.compile(r"multiple definition of '(?P<sym>.+?)'")

SEVERITY_TOKEN = {
    "error": ERROR, "Error": ERROR, "fatal error": FATAL,
    "warning": WARNING, "Warning": WARNING, "note": NOTE, "remark": NOTE,
}


@dataclass
class DToken:
    type: str
    text: str
    lineno: int
    attrs: Dict = field(default_factory=dict)
    raw: str = ""

    def __repr__(self):
        return "<%s line %d: %s>" % (self.type, self.lineno, self.text[:60])


def _int(v):
    return int(v) if v not in (None, "") else None


def _classify_linker_message(msg):
    """Extract kind / symbol / severity from a linker message body."""
    attrs = {"severity": "error"}
    body = msg
    if body.startswith("warning: "):
        attrs["severity"] = "warning"
        body = body[len("warning: "):]
    elif body.startswith("error: "):
        body = body[len("error: "):]
    attrs["msg"] = body
    m = RE_UNDEF.search(body)
    if m:
        attrs["kind"] = "undefined"
        attrs["symbol"] = m.group("sym")
        return attrs
    m = RE_MULTI.search(body)
    if m:
        attrs["kind"] = "multiple"
        attrs["symbol"] = m.group("sym")
        return attrs
    m = re.match(r"(?:undefined|duplicate) symbol: (?P<sym>.+)$", body)
    if m:
        attrs["kind"] = "undefined" if body.startswith("undefined") else "multiple"
        attrs["symbol"] = m.group("sym")
        return attrs
    if "cannot find -l" in body or "library not found for -l" in body \
            or "unable to find library -l" in body:
        attrs["kind"] = "missing_library"
    elif "cannot open output file" in body or "unable to open output file" in body:
        attrs["kind"] = "output_locked"
    elif "relocation truncated to fit" in body:
        attrs["kind"] = "relocation"
    else:
        attrs["kind"] = "other"
    return attrs


class DiagnosticLexer:
    """Line-oriented scanner for compiler / linker output."""

    def __init__(self):
        self.state = INITIAL

    def tokenize(self, text):
        tokens: List[DToken] = []
        self.state = INITIAL
        pending_inc = []      # "In file included from" locations
        pending_inst = []     # "required from here" lines
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = clean_line(raw)
            if not line.strip():
                continue
            tok = self._scan_line(line, lineno, pending_inc, pending_inst)
            if tok is None:
                continue
            tok.raw = raw
            if tok.type in (ERROR, FATAL, WARNING, NOTE):
                tok.attrs["include_trace"] = pending_inc[:]
                tok.attrs["instantiation_trace"] = pending_inst[:]
                pending_inc.clear()
                pending_inst.clear()
            tokens.append(tok)
        tokens.append(DToken(EOF, "", len(text.splitlines()) + 1))
        return tokens

    # ------------------------------------------------------------------
    def _scan_line(self, line, n, pending_inc, pending_inst):
        # --- rule 1: include trace (buffered, attached to next diagnostic)
        m = RE_INC_START.match(line)
        if m or (pending_inc and RE_INC_CONT.match(line)):
            m = m or RE_INC_CONT.match(line)
            pending_inc.append((m.group("file"), int(m.group("line"))))
            self.state = INITIAL
            return None
        # --- rule 2: template instantiation trace (GCC "required from")
        m = RE_INST.match(line)
        if m:
            pending_inst.append(line.strip())
            self.state = INITIAL
            return None
        # --- rule 3: a diagnostic  file:line:col: severity: message
        m = RE_DIAG.match(line)
        if m:
            msg = m.group("msg").strip()
            flag = None
            fm = RE_FLAG.search(msg)
            if fm:
                flag = fm.group("flag")
                msg = msg[: fm.start()].rstrip()
            sev = m.group("sev").lower()
            if sev == "remark":
                sev = "note"
            self.state = SNIPPET
            return DToken(SEVERITY_TOKEN[m.group("sev")], line, n, {
                "file": m.group("file"), "line": int(m.group("line")),
                "col": _int(m.group("col")), "severity": sev,
                "message": msg, "flag": flag})
        # --- rule 4: function context line
        m = RE_CTX.match(line)
        if m:
            self.state = INITIAL
            return DToken(CTX, line, n, {"file": m.group("file"), "what": m.group("what")})
        # --- rule 5: linker summary lines
        for rx in RE_LD_SUMMARY:
            m = rx.match(line)
            if m:
                self.state = INITIAL
                return DToken(LD_SUMMARY, line, n, {"code": m.group("code"), "msg": line})
        # --- rule 6: Apple ld64 blocks
        m = RE_MAC_HDR.match(line)
        if m:
            self.state = MACLINK
            return DToken(MAC_HDR, line, n, {"arch": m.group("arch")})
        m = RE_MAC_DUP.match(line)
        if m:
            self.state = MACLINK
            return DToken(MAC_DUP, line, n, {"symbol": m.group("sym")})
        if self.state == MACLINK:
            m = RE_MAC_SYM.match(line)
            if m:
                return DToken(MAC_SYM, line, n, {"symbol": m.group("sym")})
            m = RE_MAC_REF.match(line)
            if m:
                return DToken(MAC_REF, line, n, {"ref": m.group("ref")})
            self.state = INITIAL
        # --- rule 7: lines starting with the linker's own name
        m = RE_LD_PREFIX.match(line)
        if m:
            rest = m.group("rest")
            self.state = INITIAL
            mm = RE_LD_IN_FUNCTION.match(rest)
            if mm:
                return DToken(LD_CTX, line, n, {"obj": mm.group("obj"), "func": mm.group("func")})
            for rx in RE_LD_REST_SUMMARY:
                if rx.match(rest):
                    return DToken(LD_SUMMARY, line, n, {"msg": rest})
            mm = RE_LLD_ERR.match(rest)
            if mm:
                self.state = LLDREF
                attrs = _classify_linker_message(mm.group("msg"))
                return DToken(LD_ERR, line, n, attrs)
            mm = RE_LD_SECTION.match(rest)
            body = mm.group("msg") if mm else rest
            attrs = _classify_linker_message(body)
            if mm:
                attrs["obj"] = mm.group("obj").rstrip(":")
            return DToken(LD_ERR, line, n, attrs)
        # --- rule 8: GNU ld "object:(section+offset): message"
        # (linker lines never start with white space; snippet lines usually do)
        m = RE_LD_SECTION.match(line)
        if m and not line[0].isspace():
            self.state = INITIAL
            attrs = _classify_linker_message(m.group("msg"))
            attrs["obj"] = m.group("obj").rstrip(":")
            return DToken(LD_ERR, line, n, attrs)
        if "undefined reference to '" in line and not line[0].isspace():
            self.state = INITIAL
            return DToken(LD_ERR, line, n, _classify_linker_message(line))
        # --- rule 9: LLVM lld reference lines
        if self.state == LLDREF:
            m = RE_LLD_REF.match(line)
            if m:
                return DToken(LLD_REF, line, n, {"ref": m.group("ref")})
            self.state = INITIAL
        # --- rule 10: compiler driver messages
        m = RE_DRIVER.match(line)
        if m:
            self.state = INITIAL
            return DToken(DRIVER, line, n, {"prog": m.group("prog"),
                                            "severity": m.group("sev"),
                                            "message": m.group("msg")})
        # --- rule 11: summaries
        if RE_SUMMARY.match(line):
            self.state = INITIAL
            return DToken(SUMMARY, line, n, {"msg": line})
        # --- rule 12: anything else
        if self.state == SNIPPET:
            return DToken(SNIP, line, n, {})
        return DToken(TEXT, line, n, {})


def tokenize(text):
    return DiagnosticLexer().tokenize(text)
