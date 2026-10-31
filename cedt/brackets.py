"""
brackets.py - bracket matching with a STACK (a pushdown automaton).

Balanced brackets are the classic example of a language that a finite
automaton cannot recognise but a pushdown automaton can.  GCC only notices a
missing '}' when it reaches the end of the file ("expected declaration or
statement at end of input"), which is useless to a beginner.  This module
finds the brace that is actually missing:

  1. push every opener ( [ { on a stack, pop on the matching closer;
  2. anything left on the stack at the end is unclosed, any closer with an
     empty stack is extra, a closer of the wrong kind is a mismatch;
  3. INDENTATION HEURISTIC - a '}' that is indented LESS than the line of
     the '{' it closed probably belonged to an outer block, so the inner '{'
     is the one really missing its '}' (and vice versa for an extra '}').
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

PAIRS = {"(": ")", "[": "]", "{": "}"}
CLOSERS = {v: k for k, v in PAIRS.items()}


def indent_width(line, tabstop=4):
    width = 0
    for ch in line:
        if ch == " ":
            width += 1
        elif ch == "\t":
            width += tabstop - (width % tabstop)
        else:
            break
    return width


@dataclass
class BracketReport:
    match: Dict[int, int] = field(default_factory=dict)   # token index -> partner
    unclosed: List[int] = field(default_factory=list)      # opener token indexes
    extra: List[int] = field(default_factory=list)         # closer token indexes
    mismatched: List[tuple] = field(default_factory=list)  # (opener, closer)
    suspicious_open: List[int] = field(default_factory=list)   # '{' probably missing '}'
    suspicious_close: List[int] = field(default_factory=list)  # '}' probably extra
    depth: List[int] = field(default_factory=list)         # brace depth before token i

    @property
    def balanced(self):
        return not (self.unclosed or self.extra or self.mismatched)


def analyze(tokens, lines):
    rep = BracketReport()
    stack = []
    brace_depth = 0
    for i, t in enumerate(tokens):
        rep.depth.append(brace_depth)
        if t.kind != "op":
            continue
        if t.text in PAIRS:
            stack.append(i)
            if t.text == "{":
                brace_depth += 1
        elif t.text in CLOSERS:
            if t.text == "}":
                brace_depth = max(0, brace_depth - 1)
            if not stack:
                rep.extra.append(i)
                continue
            # find the nearest opener of the right kind
            want = CLOSERS[t.text]
            if tokens[stack[-1]].text == want:
                j = stack.pop()
                rep.match[i] = j
                rep.match[j] = i
            else:
                # mismatch: e.g. ( ... }  - if a matching opener exists deeper,
                # the openers above it were never closed
                k = len(stack) - 1
                while k >= 0 and tokens[stack[k]].text != want:
                    k -= 1
                if k >= 0:
                    for j in stack[k + 1:]:
                        rep.unclosed.append(j)
                    j = stack[k]
                    del stack[k:]
                    rep.match[i] = j
                    rep.match[j] = i
                else:
                    rep.mismatched.append((stack[-1], i))
                    rep.extra.append(i)
    rep.unclosed.extend(stack)
    rep.unclosed.sort()

    # ---- indentation heuristic for curly braces
    def line_indent(tok):
        return indent_width(lines[tok.line - 1]) if 0 < tok.line <= len(lines) else 0

    def first_on_line(idx):
        tok = tokens[idx]
        return idx == 0 or tokens[idx - 1].end_line < tok.line

    for i, t in enumerate(tokens):
        if not t.is_op("}") or i not in rep.match:
            continue
        j = rep.match[i]
        if not first_on_line(i):
            continue
        open_ind = line_indent(tokens[j])
        close_ind = line_indent(t)
        if close_ind < open_ind:
            rep.suspicious_open.append(j)
        elif close_ind > open_ind and tokens[j].line != t.line:
            rep.suspicious_close.append(i)
    return rep


def describe_opener(tokens, idx, lines):
    """A short human description of what an opening brace belongs to."""
    tok = tokens[idx]
    # look back over the header: if (...) {   /  int main() {   /  else {
    k = idx - 1
    if k >= 0 and tokens[k].is_op(")") :
        depth = 0
        while k >= 0:
            if tokens[k].is_op(")"):
                depth += 1
            elif tokens[k].is_op("("):
                depth -= 1
                if depth == 0:
                    break
            k -= 1
        if k > 0:
            head = tokens[k - 1]
            if head.kind == "kw" and head.text in ("if", "for", "while", "switch"):
                return "the '%s' block" % head.text
            if head.kind == "id":
                return "the body of function '%s'" % head.text
    if k >= 0 and tokens[idx - 1].is_kw("else"):
        return "the 'else' block"
    if k >= 0 and tokens[idx - 1].is_kw("do"):
        return "the 'do' block"
    if idx >= 2 and tokens[idx - 2].kind == "kw" and tokens[idx - 2].text in ("struct", "union", "enum", "class"):
        return "the definition of %s %s" % (tokens[idx - 2].text, tokens[idx - 1].text)
    if idx >= 1 and tokens[idx - 1].is_op("="):
        return "an initializer list"
    return "a block"


def guess_missing_close(tokens, lines, rep) -> Optional[int]:
    """Token index of the '{' that most probably lacks its '}'."""
    braces = [j for j in rep.unclosed if tokens[j].is_op("{")]
    if rep.suspicious_open:
        # the innermost suspicious opener (highest index) is the best guess
        return max(rep.suspicious_open)
    if braces:
        return braces[-1]
    return None


def guess_extra_close(tokens, lines, rep) -> Optional[int]:
    """Token index of the '}' that is most probably extra."""
    if rep.suspicious_close:
        return min(rep.suspicious_close)
    extras = [i for i in rep.extra if tokens[i].is_op("}")]
    if extras:
        return extras[0]
    return None
