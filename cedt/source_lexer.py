"""
source_lexer.py - our own LEXICAL ANALYZER for C / C++ source code.

CEDT reads the student's program itself (not just the compiler's messages)
so that it can say *which* brace is missing, *which* declared name was
meant, whether a variable is out of scope, and so on.

Design (as taught in the lexical-analysis unit):
  * maximal munch - always take the longest possible token;
  * numbers are recognised by an explicit TABLE-DRIVEN DFA (NUMBER_DFA below),
    which also explains lexical errors such as 08 (invalid octal digit) or
    2x (invalid suffix);
  * identifiers follow  letter (letter | digit)*  ;
  * strings, character constants and comments are scanned with error
    detection (unterminated string / comment, empty character constant);
  * anything that is not a legal C character becomes an 'unknown' or
    'nonascii' token - these are the "stray characters" GCC complains about
    (very often curly quotes copied from a PDF or Word document).
"""
from dataclasses import dataclass, field
from typing import List, Optional

C_KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if", "inline",
    "int", "long", "register", "restrict", "return", "short", "signed",
    "sizeof", "static", "struct", "switch", "typedef", "union", "unsigned",
    "void", "volatile", "while", "_Bool", "_Complex", "_Imaginary", "_Alignas",
    "_Alignof", "_Atomic", "_Generic", "_Noreturn", "_Static_assert",
    "_Thread_local",
}
CPP_KEYWORDS = C_KEYWORDS | {
    "alignas", "alignof", "and", "and_eq", "asm", "bitand", "bitor", "bool",
    "catch", "char8_t", "char16_t", "char32_t", "class", "compl", "concept",
    "consteval", "constexpr", "constinit", "const_cast", "co_await",
    "co_return", "co_yield", "decltype", "delete", "dynamic_cast", "explicit",
    "export", "false", "friend", "mutable", "namespace", "new", "noexcept",
    "not", "not_eq", "nullptr", "operator", "or", "or_eq", "private",
    "protected", "public", "reinterpret_cast", "requires", "static_assert",
    "static_cast", "template", "this", "thread_local", "throw", "true", "try",
    "typeid", "typename", "using", "virtual", "wchar_t", "xor", "xor_eq",
}
C_KEYWORDS_ALL = C_KEYWORDS  # alias used by suggestion code

# punctuators, longest first (maximal munch)
OPERATORS = sorted("""
>>= <<= ... ->* <=> -> ++ -- << >> <= >= == != && || += -= *= /= %= &= |= ^= :: ## .*
+ - * / % = < > ! & | ^ ~ ? : ; , . ( ) [ ] { } #
""".split(), key=len, reverse=True)

# ------------------------------------------------------------- number DFA
# character classes
def _num_class(ch):
    if ch == "0":
        return "0"
    if ch == "1":
        return "1"
    if "2" <= ch <= "7":
        return "2-7"
    if ch in "89":
        return "8-9"
    if ch in "xX":
        return "x"
    if ch in "bB":
        return "b"
    if ch in "eE":
        return "e"
    if ch in "pP":
        return "p"
    if ch in "acdfACDF":
        return "hexalpha"
    if ch == ".":
        return "."
    if ch in "+-":
        return "+-"
    if ch == "'":            # C++14 digit separator 1'000'000
        return "sep"
    return "other"


_DIG = ("0", "1", "2-7", "8-9")
_HEX = _DIG + ("b", "e", "hexalpha")


def _row(**kw):
    return kw


NUMBER_DFA = {
    "START":   dict({"0": "ZERO", ".": "DOT"}, **{c: "DEC" for c in ("1", "2-7", "8-9")}),
    "ZERO":    dict({"x": "HEX_PRE", "b": "BIN_PRE", ".": "FRAC", "e": "EXP", "sep": "OCT"},
                    **{"0": "OCT", "1": "OCT", "2-7": "OCT", "8-9": "OCT_BAD"}),
    "DEC":     dict({".": "FRAC", "e": "EXP", "sep": "DEC"}, **{c: "DEC" for c in _DIG}),
    "OCT":     dict({".": "FRAC", "e": "EXP", "8-9": "OCT_BAD", "sep": "OCT"},
                    **{c: "OCT" for c in ("0", "1", "2-7")}),
    "OCT_BAD": dict({".": "FRAC", "e": "EXP"}, **{c: "OCT_BAD" for c in _DIG}),
    "HEX_PRE": {c: "HEX" for c in _HEX},
    "HEX":     dict({"sep": "HEX", ".": "HEX_FRAC", "p": "EXP"}, **{c: "HEX" for c in _HEX}),
    "HEX_FRAC": dict({"p": "EXP"}, **{c: "HEX_FRAC" for c in _HEX}),
    "BIN_PRE": {"0": "BIN", "1": "BIN"},
    "BIN":     {"0": "BIN", "1": "BIN", "sep": "BIN"},
    "DOT":     {c: "FRAC" for c in _DIG},
    "FRAC":    dict({"e": "EXP"}, **{c: "FRAC" for c in _DIG}),
    "EXP":     dict({"+-": "EXP_SIGN"}, **{c: "EXP_DIG" for c in _DIG}),
    "EXP_SIGN": {c: "EXP_DIG" for c in _DIG},
    "EXP_DIG": {c: "EXP_DIG" for c in _DIG},
}
# accepting states -> literal kind
NUMBER_ACCEPT = {
    "ZERO": "int", "DEC": "int", "OCT": "int", "HEX": "int", "BIN": "int",
    "FRAC": "float", "EXP_DIG": "float", "OCT_BAD": "bad_octal",
}
INT_SUFFIXES = {"", "u", "l", "ul", "lu", "ll", "ull", "llu", "z", "uz", "zu"}
FLOAT_SUFFIXES = {"", "f", "l", "f16", "f32", "f64", "f128", "bf16", "d", "df", "dd", "dl"}


def classify_number(text):
    """Run the number DFA over a pp-number.  Returns (kind, error)."""
    state = "START"
    i = 0
    while i < len(text):
        cls = _num_class(text[i])
        nxt = NUMBER_DFA.get(state, {}).get(cls)
        if nxt is None:
            break
        state = nxt
        i += 1
    kind = NUMBER_ACCEPT.get(state)
    suffix = text[i:]
    if kind is None:
        return "bad", "malformed number '%s'" % text
    if kind == "bad_octal":
        bad = next(c for c in text if c in "89")
        return "bad", "invalid digit '%s' in octal constant" % bad
    if kind == "int" and suffix.lower() not in INT_SUFFIXES:
        return "bad", "invalid suffix '%s' on integer constant" % suffix
    if kind == "float" and suffix.lower() not in FLOAT_SUFFIXES:
        return "bad", "invalid suffix '%s' on floating constant" % suffix
    return kind, None


@dataclass
class Token:
    kind: str           # kw id int float char str op pp comment unknown nonascii bad_*
    text: str
    line: int
    col: int            # 1-based character column
    pos: int            # absolute offset in source
    end: int            # offset after last char
    end_line: int = 0
    error: Optional[str] = None
    index: int = -1     # index in the significant-token list

    def is_op(self, *ops):
        return self.kind == "op" and self.text in ops

    def is_kw(self, *kws):
        return self.kind == "kw" and (not kws or self.text in kws)

    def __repr__(self):
        return "%s(%r @%d:%d)" % (self.kind, self.text, self.line, self.col)


@dataclass
class LexResult:
    tokens: List[Token]                     # significant tokens (no comments)
    all_tokens: List[Token]                 # including comments
    errors: List[Token] = field(default_factory=list)
    line_starts: List[int] = field(default_factory=list)


def _is_ident_start(ch):
    return ch == "_" or ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _is_ident_char(ch):
    return _is_ident_start(ch) or ("0" <= ch <= "9")


class SourceLexer:
    def __init__(self, text, lang="c"):
        self.text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.lang = lang
        self.keywords = CPP_KEYWORDS if lang in ("c++", "cpp") else C_KEYWORDS
        self.line_starts = [0]
        for i, ch in enumerate(self.text):
            if ch == "\n":
                self.line_starts.append(i + 1)

    def pos_to_linecol(self, pos):
        lo, hi = 0, len(self.line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, pos - self.line_starts[lo] + 1

    def _tok(self, kind, start, end, error=None):
        line, col = self.pos_to_linecol(start)
        end_line, _ = self.pos_to_linecol(max(start, end - 1))
        return Token(kind, self.text[start:end], line, col, start, end, end_line, error)

    def tokenize(self):
        t = self.text
        n = len(t)
        i = 0
        out = []
        at_line_start = True
        while i < n:
            ch = t[i]
            # ---------------- white space
            if ch == "\n":
                at_line_start = True
                i += 1
                continue
            if ch in " \t\f\v":
                i += 1
                continue
            if ch == "\\" and i + 1 < n and t[i + 1] == "\n":      # line splice
                i += 2
                continue
            # ---------------- preprocessor directive (# first on its line)
            if ch == "#" and at_line_start:
                j = i
                while j < n:
                    if t[j] == "\n":
                        if j > 0 and t[j - 1] == "\\":
                            j += 1
                            continue
                        break
                    j += 1
                out.append(self._tok("pp", i, j))
                i = j
                continue
            at_line_start = False
            # ---------------- comments
            if t.startswith("//", i):
                j = t.find("\n", i)
                j = n if j == -1 else j
                out.append(self._tok("comment", i, j))
                i = j
                continue
            if t.startswith("/*", i):
                j = t.find("*/", i + 2)
                if j == -1:
                    out.append(self._tok("bad_comment", i, n, "unterminated comment"))
                    i = n
                else:
                    out.append(self._tok("comment", i, j + 2))
                    i = j + 2
                continue
            # ---------------- string / char literals (with prefixes)
            m = self._literal_prefix(i)
            if m is not None:
                start, q = m
                if self.lang in ("c++", "cpp") and t[q - 1] == "R" and t[q] == '"':
                    i = self._raw_string(start, q, out)
                    continue
                i = self._quoted(start, q, out)
                continue
            # ---------------- numbers (pp-number, then DFA classification)
            if ch.isdigit() or (ch == "." and i + 1 < n and t[i + 1].isdigit()):
                j = i + 1
                while j < n:
                    c = t[j]
                    if _is_ident_char(c) or c == ".":
                        j += 1
                    elif c in "+-" and t[j - 1] in "eEpP":
                        j += 1
                    elif c == "'" and self.lang in ("c++", "cpp") and j + 1 < n and t[j + 1].isalnum():
                        j += 1
                    else:
                        break
                kind, err = classify_number(t[i:j])
                out.append(self._tok("bad_number" if kind == "bad" else kind, i, j, err))
                i = j
                continue
            # ---------------- identifiers / keywords
            if _is_ident_start(ch):
                j = i + 1
                while j < n and _is_ident_char(t[j]):
                    j += 1
                word = t[i:j]
                out.append(self._tok("kw" if word in self.keywords else "id", i, j))
                i = j
                continue
            # ---------------- operators (maximal munch)
            for op in OPERATORS:
                if t.startswith(op, i):
                    out.append(self._tok("op", i, i + len(op)))
                    i += len(op)
                    break
            else:
                if ord(ch) > 127:
                    out.append(self._tok("nonascii", i, i + 1, "non-ASCII character"))
                else:
                    out.append(self._tok("unknown", i, i + 1, "stray character"))
                i += 1
        significant = [tk for tk in out if tk.kind not in ("comment",)]
        for idx, tk in enumerate(significant):
            tk.index = idx
        errors = [tk for tk in out if tk.error]
        return LexResult(significant, out, errors, self.line_starts)

    # ------------------------------------------------------------------
    def _literal_prefix(self, i):
        t = self.text
        for pre in ("u8R", "uR", "UR", "LR", "R", "u8", "u", "U", "L", ""):
            q = i + len(pre)
            if t.startswith(pre, i) and q < len(t) and t[q] in "\"'":
                if pre and (i > 0 and _is_ident_char(t[i - 1])):
                    continue
                if "R" in pre and t[q] != '"':
                    continue
                return i, q
        return None

    def _quoted(self, start, q, out):
        t = self.text
        quote = t[q]
        j = q + 1
        n = len(t)
        while j < n:
            c = t[j]
            if c == "\\" and j + 1 < n:
                j += 2
                continue
            if c == quote:
                j += 1
                kind = "str" if quote == '"' else "char"
                err = None
                if quote == "'":
                    body = t[q + 1:j - 1]
                    if body == "":
                        err = "empty character constant"
                    elif len(body) > 1 and not body.startswith("\\"):
                        err = "multi-character character constant"
                out.append(self._tok(kind, start, j, err))
                return j
            if c == "\n":
                break
            j += 1
        kind = "bad_str" if quote == '"' else "bad_char"
        out.append(self._tok(kind, start, j, "missing terminating %s character" % quote))
        return j

    def _raw_string(self, start, q, out):
        t = self.text
        p = t.find("(", q)
        if p == -1:
            out.append(self._tok("bad_str", start, q + 1, "bad raw string"))
            return q + 1
        delim = t[q + 1:p]
        close = ")" + delim + '"'
        e = t.find(close, p)
        if e == -1:
            out.append(self._tok("bad_str", start, len(t), "unterminated raw string"))
            return len(t)
        out.append(self._tok("str", start, e + len(close)))
        return e + len(close)


def tokenize(text, lang="c"):
    return SourceLexer(text, lang).tokenize()
