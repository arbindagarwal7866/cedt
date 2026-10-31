"""
ll1.py - a small, general LL(1) parser generator + table-driven parser.

This is the textbook algorithm (Aho, Lam, Sethi, Ullman - "Compilers",
section 4.4) implemented directly:

  1. FIRST sets          - fixed-point iteration over all productions
  2. FOLLOW sets         - fixed-point iteration, FOLLOW(start) = { $ }
  3. Predictive table M  - for A -> alpha:
                             M[A, a] = A -> alpha   for every a in FIRST(alpha)
                             M[A, b] = A -> alpha   for every b in FOLLOW(A)
                                                    when epsilon in FIRST(alpha)
                           two productions in one cell = LL(1) conflict
  4. Predictive parsing  - explicit stack, one token of look-ahead
  5. Panic-mode recovery - synchronising set = FOLLOW(A):
                             if M[A, a] is blank and a is in FOLLOW(A): pop A
                             otherwise skip the input token a
  6. Syntax-directed translation - grammar symbols beginning with '@' are
     ACTION SYMBOLS.  When one reaches the top of the stack the matching
     Python function runs (with the token matched just before it).
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

EPS = "ε"
END = "$"


@dataclass
class Production:
    index: int
    lhs: str
    rhs: List[str]

    def body(self, with_actions=True):
        syms = self.rhs if with_actions else [s for s in self.rhs if not s.startswith("@")]
        return " ".join(syms) if syms else EPS

    def __str__(self):
        return "%s -> %s" % (self.lhs, self.body(with_actions=False))


class Grammar:
    def __init__(self, start, rules):
        """rules: list of (lhs, rhs-string) e.g. ("Item", "CTX @ctx")."""
        self.start = start
        self.productions: List[Production] = []
        for lhs, rhs in rules:
            syms = rhs.split() if rhs.strip() not in ("", EPS) else []
            self.productions.append(Production(len(self.productions), lhs, syms))
        self.nonterminals = []
        for p in self.productions:
            if p.lhs not in self.nonterminals:
                self.nonterminals.append(p.lhs)
        nts = set(self.nonterminals)
        self.terminals = []
        for p in self.productions:
            for s in p.rhs:
                if s not in nts and not self.is_action(s) and s not in self.terminals:
                    self.terminals.append(s)
        self.first: Dict[str, set] = {}
        self.follow: Dict[str, set] = {}
        self.table: Dict[str, Dict[str, Production]] = {}
        self.conflicts: List[str] = []
        self._compute_first()
        self._compute_follow()
        self._build_table()

    @staticmethod
    def is_action(sym):
        return sym.startswith("@")

    def is_nonterminal(self, sym):
        return sym in self.first and sym in self.nonterminals

    # ------------------------------------------------------------ FIRST
    def first_of(self, symbols):
        """FIRST of a sequence of grammar symbols (actions are ignored)."""
        out = set()
        for s in symbols:
            if self.is_action(s):
                continue
            if s not in self.nonterminals:          # terminal
                out.add(s)
                return out
            f = self.first[s]
            out |= (f - {EPS})
            if EPS not in f:
                return out
        out.add(EPS)
        return out

    def _compute_first(self):
        for a in self.nonterminals:
            self.first[a] = set()
        changed = True
        while changed:
            changed = False
            for p in self.productions:
                f = self.first_of(p.rhs)
                if not f <= self.first[p.lhs]:
                    self.first[p.lhs] |= f
                    changed = True

    # ------------------------------------------------------------ FOLLOW
    def _compute_follow(self):
        for a in self.nonterminals:
            self.follow[a] = set()
        self.follow[self.start].add(END)
        changed = True
        while changed:
            changed = False
            for p in self.productions:
                syms = [s for s in p.rhs if not self.is_action(s)]
                for i, b in enumerate(syms):
                    if b not in self.nonterminals:
                        continue
                    f = self.first_of(syms[i + 1:])
                    add = f - {EPS}
                    if EPS in f:
                        add |= self.follow[p.lhs]
                    if not add <= self.follow[b]:
                        self.follow[b] |= add
                        changed = True

    # ------------------------------------------------------------ TABLE
    def _build_table(self):
        for a in self.nonterminals:
            self.table[a] = {}
        for p in self.productions:
            f = self.first_of(p.rhs)
            targets = f - {EPS}
            if EPS in f:
                targets |= self.follow[p.lhs]
            for t in targets:
                if t in self.table[p.lhs] and self.table[p.lhs][t] is not p:
                    self.conflicts.append("M[%s, %s]: '%s' vs '%s'" % (
                        p.lhs, t, self.table[p.lhs][t], p))
                else:
                    self.table[p.lhs][t] = p

    def is_ll1(self):
        return not self.conflicts

    # ------------------------------------------------------------ printing
    def format_grammar(self, with_actions=False):
        lines = []
        width = max(len(a) for a in self.nonterminals)
        for a in self.nonterminals:
            bodies = [p.body(with_actions) for p in self.productions if p.lhs == a]
            lines.append("%-*s -> %s" % (width, a, bodies[0]))
            for b in bodies[1:]:
                lines.append("%-*s  | %s" % (width, "", b))
        return "\n".join(lines)

    def format_sets(self):
        def fmt(s):
            order = self.terminals + [END, EPS]
            return "{ " + ", ".join(sorted(s, key=lambda x: order.index(x) if x in order else 99)) + " }"
        width = max(len(a) for a in self.nonterminals)
        lines = ["%-*s  %-60s %s" % (width, "", "FIRST", "FOLLOW")]
        for a in self.nonterminals:
            lines.append("%-*s  %-60s %s" % (width, a, fmt(self.first[a]), fmt(self.follow[a])))
        return "\n".join(lines)

    def format_table(self):
        cols = self.terminals + [END]
        lines = []
        for a in self.nonterminals:
            row = self.table[a]
            entries = ["%s: %s" % (t, row[t].body(False)) for t in cols if t in row]
            lines.append("M[%s]" % a)
            for e in entries:
                lines.append("    " + e)
        return "\n".join(lines)


@dataclass
class TraceStep:
    stack: str
    lookahead: str
    action: str


@dataclass
class ParseOutcome:
    accepted: bool
    errors: List[str] = field(default_factory=list)
    skipped: List[object] = field(default_factory=list)
    trace: List[TraceStep] = field(default_factory=list)
    steps: int = 0


class LL1Parser:
    """Table-driven predictive parser with action symbols and panic mode."""

    def __init__(self, grammar: Grammar, actions: Dict[str, Callable],
                 on_skip: Optional[Callable] = None):
        self.g = grammar
        self.actions = actions
        self.on_skip = on_skip

    def parse(self, tokens, trace=False, max_trace=400):
        g = self.g
        stack = [END, g.start]
        i = 0
        last = None
        out = ParseOutcome(accepted=False)

        def record(action):
            if trace and len(out.trace) < max_trace:
                visible = [s for s in stack if not g.is_action(s)]
                out.trace.append(TraceStep(" ".join(visible), tokens[i].type, action))

        while stack:
            out.steps += 1
            top = stack[-1]
            tok = tokens[i]
            if g.is_action(top):
                stack.pop()
                fn = self.actions.get(top)
                if fn:
                    fn(last)
                continue
            if top == END:
                if tok.type == END:
                    record("accept")
                    out.accepted = not out.errors
                    stack.pop()
                    break
                # extra input after the start symbol finished: skip it
                out.errors.append("line %d: unexpected %s after end" % (tok.lineno, tok.type))
                record("error: skip %s" % tok.type)
                self._skip(tok, out)
                i += 1
                continue
            if top not in g.nonterminals:            # terminal on top
                if top == tok.type:
                    record("match %s" % tok.type)
                    stack.pop()
                    last = tok
                    i += 1
                else:
                    out.errors.append("line %d: expected %s, found %s" % (tok.lineno, top, tok.type))
                    record("error: pop %s" % top)
                    stack.pop()                       # pretend it was inserted
                continue
            prod = g.table[top].get(tok.type)
            if prod is not None:
                record("%s" % prod)
                stack.pop()
                for sym in reversed(prod.rhs):
                    stack.append(sym)
                continue
            # ---- panic-mode error recovery (synchronising set = FOLLOW(top))
            out.errors.append("line %d: no rule for %s on %s" % (tok.lineno, top, tok.type))
            if tok.type in g.follow[top] or tok.type == END:
                record("error: pop %s (synch)" % top)
                stack.pop()
            else:
                record("error: skip %s" % tok.type)
                self._skip(tok, out)
                i += 1
        return out

    def _skip(self, tok, out):
        out.skipped.append(tok)
        if self.on_skip:
            self.on_skip(tok)
