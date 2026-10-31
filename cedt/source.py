"""
source.py - everything CEDT knows about one source file.

SourceFile bundles the three analyses of the student's own code
(tokens from source_lexer, bracket report from brackets, symbol table
from symbols) and offers small query helpers used by the rule handlers.
"""
from . import brackets as B
from . import symbols as S
from .source_lexer import SourceLexer
from .textutil import byte_col_to_index, display_col_to_index


class SourceFile:
    def __init__(self, path, text, lang="c"):
        self.path = path
        self.text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.lang = lang
        self.lines = self.text.split("\n")
        lex = SourceLexer(self.text, lang).tokenize()
        self.tokens = lex.tokens
        self.all_tokens = lex.all_tokens
        self.lex_errors = lex.errors
        self.brackets = B.analyze(self.tokens, self.lines)
        self.symbols = S.build(self.tokens, self.brackets.match, lang)
        self._by_line = {}
        for t in self.tokens:
            self._by_line.setdefault(t.line, []).append(t)

    # -------------------------------------------------------------- lines
    def line(self, n):
        if n is None or n < 1 or n > len(self.lines):
            return ""
        return self.lines[n - 1]

    def tokens_on_line(self, n):
        return self._by_line.get(n, [])

    def first_token_on_line(self, n):
        toks = self.tokens_on_line(n)
        return toks[0] if toks else None

    def last_token_on_line(self, n):
        toks = [t for t in self.tokens if t.line <= n <= t.end_line]
        return toks[-1] if toks else None

    def prev_nonblank_line(self, n):
        k = n - 1
        while k >= 1:
            if self.tokens_on_line(k):
                return k
            k -= 1
        return None

    # -------------------------------------------------------------- columns
    def col_to_index(self, line_no, col, unit="byte"):
        """Convert a compiler column to a 0-based index into the line."""
        text = self.line(line_no)
        if col is None:
            return None
        if unit == "display":
            return display_col_to_index(text, col)
        if unit == "char":
            return max(0, col - 1)
        if unit == "auto":
            b = byte_col_to_index(text, col)
            d = display_col_to_index(text, col)
            if b == d:
                return b
            # prefer the candidate that lands on a non-blank character
            b_ok = b < len(text) and not text[b].isspace()
            d_ok = d < len(text) and not text[d].isspace()
            if d_ok and not b_ok:
                return d
            return b
        return byte_col_to_index(text, col)

    def token_at(self, line_no, col, unit="byte"):
        """Token covering (line, col), else the first token after it."""
        idx = self.col_to_index(line_no, col, unit)
        toks = self.tokens_on_line(line_no)
        if idx is None:
            return toks[0] if toks else None
        c1 = idx + 1
        for t in toks:
            if t.col <= c1 < t.col + len(t.text) and t.line == line_no:
                return t
        for t in toks:
            if t.col >= c1:
                return t
        # nothing at/after the column on this line -> first token of a later line
        for t in self.tokens:
            if t.line > line_no:
                return t
        return None

    def prev_token(self, tok):
        if tok is None or tok.index <= 0:
            return None
        return self.tokens[tok.index - 1]

    def next_token(self, tok):
        if tok is None or tok.index + 1 >= len(self.tokens):
            return None
        return self.tokens[tok.index + 1]

    def tok(self, i):
        if 0 <= i < len(self.tokens):
            return self.tokens[i]
        return None

    def brace_depth_at(self, tok):
        if tok is None or tok.index >= len(self.brackets.depth):
            return 0
        return self.brackets.depth[tok.index]

    def statement_tokens(self, tok):
        """Tokens of the statement that contains tok (from previous ; { } to next ;)."""
        i = tok.index
        start = i
        while start > 0 and not self.tokens[start - 1].is_op(";", "{", "}") and self.tokens[start - 1].kind != "pp":
            start -= 1
        end = i
        depth = 0
        while end < len(self.tokens):
            t = self.tokens[end]
            if t.is_op("(", "["):
                depth += 1
            elif t.is_op(")", "]"):
                depth -= 1
            if t.is_op(";") and depth <= 0:
                break
            if t.is_op("{", "}") and end > i:
                break
            end += 1
        return self.tokens[start:end + 1]

    def enclosing_function(self, line_no):
        s = self.symbols.function_scope_at_line(line_no)
        return s.name if s else None

    def identifier_count(self, name):
        return sum(1 for t in self.tokens if t.kind == "id" and t.text == name)

    def includes(self):
        import re
        out = []
        for t in self.tokens:
            if t.kind == "pp":
                m = re.match(r"#\s*include\s*([<\"])([^>\"]+)[>\"]", t.text)
                if m:
                    out.append((m.group(2).strip(), t.line, m.group(1) == "<"))
        return out


def virtual_source(path, snippet_lines, lang="c"):
    """Rebuild a partial source file from compiler snippet lines.

    Used when only the compiler output is available (log mode).  Missing
    lines are left empty so line numbers stay correct.
    """
    if not snippet_lines:
        return None
    last = max(snippet_lines)
    lines = [snippet_lines.get(i, "") for i in range(1, last + 1)]
    sf = SourceFile(path, "\n".join(lines) + "\n", lang)
    sf.partial = True      # only the lines the compiler quoted are known
    return sf
