"""
symbols.py - a scope-aware SYMBOL TABLE (the core data structure of the
semantic-analysis phase).

The builder walks the token stream once, keeping a stack of scopes:

    file scope
      └── function scope  (int main() { ... })   - parameters live here
            ├── block scope   ({ ... } after if/while/else)
            └── for scope     (for (int i = 0; ...) - i lives only here)

Every declaration is recorded with its type, line, scope and (for arrays)
its size; every use of a name is recorded too.  CEDT uses the table for:
  * "did you mean ...?"   - names visible at the error position
  * scope explanations    - "i was declared inside the for loop on line 3,
                              it does not exist on line 6"
  * use-before-declaration, uninitialised variables, integer division,
    array-bound checks and parameter-count explanations.

The parser is deliberately forgiving: it must keep going on code that
contains errors, because that is exactly the code students give us.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

TYPE_KEYWORDS = {
    "void", "char", "short", "int", "long", "float", "double", "signed",
    "unsigned", "_Bool", "bool", "wchar_t", "char8_t", "char16_t", "char32_t",
    "_Complex",
}
QUALIFIERS = {
    "const", "volatile", "static", "extern", "register", "inline", "typedef",
    "restrict", "_Thread_local", "thread_local", "constexpr", "mutable",
    "_Noreturn", "virtual", "explicit", "friend", "consteval", "constinit",
    "__inline", "__restrict",
}
C_TYPEDEFS = {
    "size_t", "ssize_t", "FILE", "ptrdiff_t", "int8_t", "int16_t", "int32_t",
    "int64_t", "uint8_t", "uint16_t", "uint32_t", "uint64_t", "intptr_t",
    "uintptr_t", "time_t", "clock_t", "va_list", "off_t", "pid_t", "DIR",
    "intmax_t", "uintmax_t", "fpos_t", "div_t", "ldiv_t", "jmp_buf", "errno_t",
    "wint_t", "mbstate_t", "sig_atomic_t", "bool",
}
CPP_TYPES = {
    "string", "vector", "map", "set", "unordered_map", "unordered_set", "pair",
    "queue", "stack", "deque", "list", "priority_queue", "array", "tuple",
    "istream", "ostream", "ifstream", "ofstream", "fstream", "stringstream",
    "istringstream", "ostringstream", "string_view", "optional", "multiset",
    "multimap", "bitset", "complex", "function", "unique_ptr", "shared_ptr",
    "size_t", "iterator", "wstring", "forward_list", "variant", "any",
}
INT_LIKE = {"int", "long", "short", "char", "unsigned", "signed", "size_t",
            "bool", "_Bool", "int8_t", "int16_t", "int32_t", "int64_t",
            "uint8_t", "uint16_t", "uint32_t", "uint64_t", "long long",
            "unsigned int", "unsigned long", "long int", "unsigned char",
            "short int", "unsigned short", "long long int", "unsigned long long"}
FLOAT_LIKE = {"float", "double", "long double"}


@dataclass
class Scope:
    id: int
    kind: str                 # file function block for struct class enum namespace
    parent: Optional[int]
    start: int                # token index
    end: int = 10 ** 9        # token index (inclusive)
    name: str = ""
    start_line: int = 1
    end_line: int = 10 ** 9


@dataclass
class Symbol:
    name: str
    kind: str                 # var param func proto struct union enum class typedef macro enum_const member method
    type: str = ""
    line: int = 0
    col: int = 0
    tok: int = -1
    scope: int = 0
    initialized: bool = False
    pointer: int = 0
    array_sizes: List[Optional[int]] = field(default_factory=list)
    params: List["Symbol"] = field(default_factory=list)
    variadic: bool = False
    defined: bool = False
    members: List["Symbol"] = field(default_factory=list)
    owner: str = ""           # struct/class name for members
    value: str = ""           # macro value

    @property
    def is_array(self):
        return bool(self.array_sizes)

    def type_str(self):
        s = self.type + ("*" * self.pointer)
        for d in self.array_sizes:
            s += "[%s]" % ("" if d is None else d)
        return s


@dataclass
class Use:
    name: str
    tok: int
    line: int
    col: int
    scope: int
    is_call: bool = False
    is_member: bool = False
    is_write: bool = False        # plain assignment target  x = ...
    address_taken: bool = False   # &x


class SymbolTable:
    def __init__(self):
        self.scopes: List[Scope] = []
        self.symbols: List[Symbol] = []
        self.uses: List[Use] = []
        self.type_names = set()
        self.using_std = False
        self.macros: Dict[str, Symbol] = {}

    # ---------------------------------------------------------- queries
    def scope_chain(self, scope_id):
        chain = []
        while scope_id is not None:
            chain.append(scope_id)
            scope_id = self.scopes[scope_id].parent
        return chain

    def scope_at(self, tok_index):
        """Innermost scope containing a token index."""
        best = 0
        for s in self.scopes:
            if s.start <= tok_index <= s.end and s.kind not in ("struct", "class", "enum"):
                if self.scopes[best].start <= s.start:
                    best = s.id
        return best

    def declarations(self, name):
        return [s for s in self.symbols if s.name == name or s.name.split("::")[-1] == name]

    def visible_at(self, tok_index, kinds=None):
        """Symbols visible at a token position (declared earlier, in scope)."""
        chain = set(self.scope_chain(self.scope_at(tok_index)))
        out = []
        for s in self.symbols:
            if kinds and s.kind not in kinds:
                continue
            if s.kind in ("member", "method"):
                continue
            if s.scope in chain and (s.tok <= tok_index or self.scopes[s.scope].kind == "file"
                                     and s.kind in ("func", "proto", "macro", "struct", "typedef")):
                out.append(s)
        return out

    def lookup(self, name, tok_index):
        best = None
        for s in self.visible_at(tok_index):
            if s.name == name:
                if best is None or s.scope >= best.scope:
                    best = s
        return best

    def functions(self):
        return [s for s in self.symbols if s.kind in ("func", "proto", "method")]

    def function_named(self, name):
        defs = [s for s in self.symbols if s.kind in ("func", "method") and
                (s.name == name or s.name.split("::")[-1] == name)]
        protos = [s for s in self.symbols if s.kind == "proto" and s.name == name]
        return (defs[0] if defs else None), (protos[0] if protos else None)

    def function_scope_at_line(self, line):
        best = None
        for s in self.scopes:
            if s.kind == "function" and s.start_line <= line <= s.end_line:
                if best is None or s.start_line >= best.start_line:
                    best = s
        return best

    def struct_named(self, name):
        for s in self.symbols:
            if s.kind in ("struct", "union", "class") and s.name == name:
                return s
        return None

    def struct_names(self):
        return [s.name for s in self.symbols if s.kind in ("struct", "union", "class", "enum")]

    def scope_description(self, scope_id, tokens):
        s = self.scopes[scope_id]
        if s.kind == "for":
            return "the for loop on line %d" % s.start_line
        if s.kind == "function":
            return "function '%s'" % s.name
        if s.kind == "block":
            head = ""
            k = s.start - 1
            if k >= 0 and tokens[k].is_op(")"):
                depth = 0
                while k >= 0:
                    if tokens[k].is_op(")"):
                        depth += 1
                    elif tokens[k].is_op("("):
                        depth -= 1
                        if depth == 0:
                            break
                    k -= 1
                if k > 0 and tokens[k - 1].kind == "kw":
                    head = tokens[k - 1].text
            elif k >= 0 and tokens[k].kind == "kw":
                head = tokens[k].text
            if head:
                return "the '%s' block that starts on line %d" % (head, s.start_line)
            return "the { } block that starts on line %d" % s.start_line
        return "the %s scope" % s.kind


class SymbolTableBuilder:
    def __init__(self, tokens, match, lang="c"):
        self.toks = [t for t in tokens]
        self.match = match
        self.lang = lang
        self.cpp = lang in ("c++", "cpp")
        self.t = SymbolTable()
        self.t.type_names = set(C_TYPEDEFS) | (CPP_TYPES if self.cpp else set())
        self.stack = []
        self.pending_func = None
        self.pending_struct = None    # (kind, name) for the next '{'
        self.after_struct = None      # type string for declarators after '}'
        self.consumed = set()         # token indexes that are declared names

    # ---------------------------------------------------------- helpers
    def tok(self, i):
        if 0 <= i < len(self.toks):
            return self.toks[i]
        return None

    def cur_scope(self):
        return self.stack[-1]

    def push(self, kind, start, end=10 ** 9, name=""):
        s = Scope(len(self.t.scopes), kind, self.stack[-1] if self.stack else None, start, end, name)
        tk = self.tok(start)
        s.start_line = tk.line if tk else 1
        if end < len(self.toks):
            s.end_line = self.toks[end].line
        self.t.scopes.append(s)
        self.stack.append(s.id)
        return s

    def pop(self, end_index):
        sid = self.stack.pop()
        s = self.t.scopes[sid]
        s.end = end_index
        tk = self.tok(end_index)
        s.end_line = tk.line if tk else s.end_line
        return s

    def add(self, sym):
        sym.scope = self.cur_scope()
        scope = self.t.scopes[sym.scope]
        if scope.kind in ("struct", "class") and sym.kind in ("var", "func", "proto"):
            sym.owner = scope.name
            sym.kind = "member" if sym.kind == "var" else "method"
            owner = self.t.struct_named(scope.name)
            if owner is not None:
                owner.members.append(sym)
        self.t.symbols.append(sym)
        if sym.tok >= 0:
            self.consumed.add(sym.tok)
        return sym

    def is_type_start(self, i):
        t = self.tok(i)
        if t is None:
            return False
        if t.kind == "kw" and (t.text in TYPE_KEYWORDS or t.text in ("struct", "union", "enum", "class", "auto" if self.cpp else "")):
            return True
        if t.kind == "id":
            if t.text == "std" and self.tok(i + 1) is not None and self.tok(i + 1).is_op("::"):
                return self.is_type_start(i + 2)
            if t.text in self.t.type_names:
                nxt = self.tok(i + 1)
                # 'Name x', 'Name *x', 'Name<...>' or 'Name &x' looks like a declaration
                if nxt is not None and (nxt.kind == "id" or nxt.is_op("*", "&", "<", "&&", "::")):
                    return True
        return False

    def skip_angles(self, i):
        """i points at '<'; return index after the matching '>'."""
        depth = 0
        while i < len(self.toks):
            t = self.toks[i]
            if t.is_op("<"):
                depth += 1
            elif t.is_op(">"):
                depth -= 1
            elif t.is_op(">>"):
                depth -= 2
            elif t.is_op(";", "{", "}"):
                return i
            i += 1
            if depth <= 0:
                return i
        return i

    # ---------------------------------------------------------- uses
    def record_use(self, i):
        t = self.toks[i]
        if t.kind != "id" or i in self.consumed:
            return
        prev = self.tok(i - 1)
        nxt = self.tok(i + 1)
        if nxt is not None and nxt.is_op("::"):
            return
        u = Use(t.text, i, t.line, t.col, self.cur_scope())
        u.is_call = nxt is not None and nxt.is_op("(")
        u.is_member = prev is not None and prev.is_op(".", "->")
        u.is_write = (nxt is not None and nxt.is_op("=") and not u.is_member
                      and not (prev is not None and prev.is_op("*", ".", "->")))
        if prev is not None and prev.is_op("&"):
            before = self.tok(i - 2)
            if before is None or before.kind == "op" and not before.is_op(")", "]"):
                u.address_taken = True
        self.t.uses.append(u)

    # ---------------------------------------------------------- main loop
    def build(self):
        self.push("file", 0, len(self.toks))
        i = 0
        stmt_start = True
        n = len(self.toks)
        while i < n:
            # close scopes that ended (for statements without braces)
            while len(self.stack) > 1 and self.t.scopes[self.stack[-1]].end < i:
                self.pop(self.t.scopes[self.stack[-1]].end)
            t = self.toks[i]
            if t.kind == "pp":
                self.directive(t)
                stmt_start = True
                i += 1
                continue
            if t.is_op("{"):
                if self.pending_func is not None:
                    f = self.pending_func
                    s = self.push("function", i, self.match.get(i, 10 ** 9), f.name)
                    for p in f.params:
                        p.scope = s.id
                        self.t.symbols.append(p)
                        if p.tok >= 0:
                            self.consumed.add(p.tok)
                    self.pending_func = None
                elif self.pending_struct is not None:
                    kind, name = self.pending_struct
                    self.push(kind, i, self.match.get(i, 10 ** 9), name)
                    self.pending_struct = None
                else:
                    self.push("block", i, self.match.get(i, 10 ** 9))
                stmt_start = True
                i += 1
                continue
            if t.is_op("}"):
                if len(self.stack) > 1:
                    s = self.pop(i)
                    if s.kind in ("struct", "class", "union"):
                        prefix = "" if self.cpp else ("struct " if s.kind == "struct" else s.kind + " ")
                        self.after_struct = (prefix + s.name).strip()
                stmt_start = True
                i += 1
                if self.after_struct:
                    typ = self.after_struct
                    self.after_struct = None
                    if self.tok(i) is not None and (self.tok(i).kind == "id" or self.tok(i).is_op("*")):
                        j = self.declarators(i, typ, explicit=True)
                        if j is not None:
                            i = j
                continue
            if t.is_op(";"):
                stmt_start = True
                i += 1
                continue
            if t.is_kw("for") and self.tok(i + 1) is not None and self.tok(i + 1).is_op("("):
                close = self.match.get(i + 1)
                end = self._for_end(close)
                self.push("for", i, end)
                i += 2
                stmt_start = True
                continue
            if t.is_kw("using") and self.tok(i + 1) is not None and self.tok(i + 1).is_kw("namespace"):
                nm = self.tok(i + 2)
                if nm is not None and nm.text == "std":
                    self.t.using_std = True
                i += 3
                continue
            if t.is_kw("namespace") and self.tok(i + 1) is not None:
                if self.tok(i + 1).kind == "id" and self.tok(i + 2) is not None and self.tok(i + 2).is_op("{"):
                    self.pending_struct = ("namespace", self.tok(i + 1).text)
                    i += 2
                    continue
            if t.kind == "kw" and t.text in ("public", "private", "protected") and \
                    self.tok(i + 1) is not None and self.tok(i + 1).is_op(":"):
                i += 2
                stmt_start = True
                continue
            if t.is_kw("template"):
                if self.tok(i + 1) is not None and self.tok(i + 1).is_op("<"):
                    i = self.skip_angles(i + 1)
                    stmt_start = True
                    continue
            if stmt_start:
                j = None
                try:
                    j = self.declaration(i)
                except Exception:          # never crash on broken code
                    j = None
                if j is not None and j > i:
                    i = j
                    stmt_start = self.tok(i - 1) is not None and self.tok(i - 1).is_op(";", "}")
                    continue
            if t.is_op(":"):
                stmt_start = True
                i += 1
                continue
            self.record_use(i)
            stmt_start = False
            i += 1
        while len(self.stack) > 1:
            self.pop(len(self.toks) - 1)
        self.t.scopes[0].end = len(self.toks)
        return self.t

    def _for_end(self, close):
        if close is None:
            return 10 ** 9
        k = close + 1
        t = self.tok(k)
        if t is None:
            return close
        if t.is_op("{"):
            return self.match.get(k, 10 ** 9)
        depth = 0
        while k < len(self.toks):
            tk = self.toks[k]
            if tk.is_op("(", "[", "{"):
                depth += 1
            elif tk.is_op(")", "]", "}"):
                depth -= 1
                if depth < 0:
                    return k - 1
            elif tk.is_op(";") and depth == 0:
                return k
            k += 1
        return k

    # ---------------------------------------------------------- directives
    def directive(self, t):
        m = re.match(r"#\s*define\s+([A-Za-z_]\w*)(\([^)]*\))?\s*(.*)$", t.text, re.S)
        if m:
            name = m.group(1)
            sym = Symbol(name, "macro", "", t.line, t.col, -1)
            sym.value = re.sub(r"\s*\\\n\s*", " ", m.group(3)).strip()
            sym.scope = 0
            sym.initialized = True
            self.t.symbols.append(sym)
            self.t.macros[name] = sym
            return
        m = re.match(r"#\s*include\s*[<\"]stdbool\.h[>\"]", t.text)
        if m:
            self.t.type_names.add("bool")

    # ---------------------------------------------------------- declarations
    def declaration(self, i):
        j = i
        is_typedef = False
        while self.tok(j) is not None and self.tok(j).kind == "kw" and self.tok(j).text in QUALIFIERS:
            if self.tok(j).text == "typedef":
                is_typedef = True
            j += 1
        t = self.tok(j)
        if t is None:
            return None
        # ---- struct / union / enum / class
        if t.kind == "kw" and t.text in ("struct", "union", "enum", "class"):
            kind = t.text
            j += 1
            name = ""
            if self.tok(j) is not None and self.tok(j).kind == "id":
                name = self.tok(j).text
                j += 1
            if self.cpp and kind in ("class", "struct") and self.tok(j) is not None and self.tok(j).is_op(":"):
                while self.tok(j) is not None and not self.tok(j).is_op("{", ";"):
                    j += 1
            nxt = self.tok(j)
            typ = name if self.cpp else ("%s %s" % (kind, name)).strip()
            if name:
                self.t.type_names.add(name)
            if nxt is not None and nxt.is_op("{"):
                if kind == "enum":
                    if name:
                        self.add(Symbol(name, "enum", typ, self.toks[j - 1].line, self.toks[j - 1].col, j - 1))
                    close = self.match.get(j)
                    k = j + 1
                    expect_name = True
                    while close is not None and k < close:
                        tk = self.toks[k]
                        if expect_name and tk.kind == "id":
                            self.add(Symbol(tk.text, "enum_const", "int", tk.line, tk.col, k, initialized=True))
                            expect_name = False
                        elif tk.is_op(","):
                            expect_name = True
                        k += 1
                    if close is None:
                        return None
                    k = close + 1
                    if self.tok(k) is not None and self.tok(k).is_op(";"):
                        return k + 1
                    return self.declarators(k, typ or "int")
                sym = Symbol(name or "<anonymous>", kind if kind != "class" else "class", typ,
                             self.toks[j - 1].line, self.toks[j - 1].col, j - 1 if name else -1)
                self.add(sym)
                self.pending_struct = (kind if kind in ("struct", "union", "class") else "struct", name or "<anonymous>")
                if is_typedef:
                    # typedef struct {...} Name;  - the name comes after '}'
                    close = self.match.get(j)
                    if close is not None:
                        k = close + 1
                        if self.tok(k) is not None and self.tok(k).kind == "id":
                            self.t.type_names.add(self.tok(k).text)
                            self.consumed.add(k)
                            self.t.symbols.append(Symbol(self.tok(k).text, "typedef", typ,
                                                         self.tok(k).line, self.tok(k).col, k, scope=0))
                return j            # main loop pushes the struct scope at '{'
            # plain use of a struct type:  struct Student s;
            if not name:
                return None
            return self.declarators(j, typ, is_typedef=is_typedef, explicit=True)
        # ---- ordinary type
        if not self.is_type_start(j):
            return None
        type_parts = []
        while True:
            t = self.tok(j)
            if t is None:
                break
            if t.kind == "kw" and (t.text in TYPE_KEYWORDS or (self.cpp and t.text == "auto")):
                type_parts.append(t.text)
                j += 1
                continue
            if t.kind == "kw" and t.text in ("const", "volatile"):
                j += 1
                continue
            if t.kind == "id" and t.text == "std" and self.tok(j + 1) is not None and self.tok(j + 1).is_op("::"):
                j += 2
                continue
            if t.kind == "id" and not type_parts and t.text in self.t.type_names:
                type_parts.append(t.text)
                j += 1
                if self.tok(j) is not None and self.tok(j).is_op("<"):
                    start = j
                    j = self.skip_angles(j)
                    type_parts[-1] += "".join(tk.text for tk in self.toks[start:j])
                # nested names like vector<int>::iterator
                while self.tok(j) is not None and self.tok(j).is_op("::") and self.tok(j + 1) is not None \
                        and self.tok(j + 1).kind == "id":
                    type_parts[-1] += "::" + self.tok(j + 1).text
                    j += 2
                continue
            break
        if not type_parts:
            return None
        typ = " ".join(type_parts)
        return self.declarators(j, typ, is_typedef=is_typedef)

    def declarators(self, j, typ, is_typedef=False, explicit=False):
        recorded = 0
        while True:
            ptr = 0
            while self.tok(j) is not None and (self.tok(j).is_op("*", "&", "&&") or self.tok(j).is_kw("const")):
                if self.tok(j).is_op("*"):
                    ptr += 1
                j += 1
            t = self.tok(j)
            if t is None:
                return None if not recorded else j
            if t.is_op("(") and self.tok(j + 1) is not None and self.tok(j + 1).is_op("*"):
                # function pointer: int (*fp)(int);  record the name, skip the rest
                close = self.match.get(j)
                name_tok = self.tok(j + 2)
                if name_tok is not None and name_tok.kind == "id":
                    self.add(Symbol(name_tok.text, "var", typ + " (*)()", name_tok.line, name_tok.col, j + 2,
                                    pointer=1))
                k = (close or j) + 1
                if self.tok(k) is not None and self.tok(k).is_op("("):
                    k = self.match.get(k, k) + 1
                return self._skip_to_end(k)
            if t.kind != "id" and not (t.kind == "kw" and t.text == "operator"):
                return None if not recorded else j
            name_i = j
            name = t.text
            j += 1
            while self.cpp and self.tok(j) is not None and self.tok(j).is_op("::") and \
                    self.tok(j + 1) is not None and self.tok(j + 1).kind in ("id",):
                name += "::" + self.tok(j + 1).text
                j += 2
            nxt = self.tok(j)
            if nxt is not None and nxt.is_op("("):
                close = self.match.get(j)
                if close is None:
                    return None
                params_toks = self.toks[j + 1:close]
                k = close + 1
                while self.tok(k) is not None and (self.tok(k).kind == "kw" and self.tok(k).text in (
                        "const", "noexcept", "override", "final", "volatile") or
                        (self.tok(k).kind == "id" and self.tok(k).text in ("override", "final"))):
                    k += 1
                after = self.tok(k)
                looks_like_params = self._looks_like_params(params_toks)
                if after is not None and (after.is_op("{") or (self.cpp and after.is_op(":") and
                                                                 "::" in name)):
                    sym = Symbol(name, "func", typ + "*" * ptr, t.line, t.col, name_i, defined=True)
                    sym.params, sym.variadic = self._params(params_toks, j + 1)
                    self.add(sym)
                    self.pending_func = sym
                    if after.is_op(":"):
                        while self.tok(k) is not None and not self.tok(k).is_op("{"):
                            k += 1
                    return k
                if after is not None and after.is_op(";", ",") and (looks_like_params or not self.cpp):
                    sym = Symbol(name, "proto", typ + "*" * ptr, t.line, t.col, name_i)
                    sym.params, sym.variadic = self._params(params_toks, j + 1)
                    self.add(sym)
                    recorded += 1
                    if after.is_op(";"):
                        return k + 1
                    j = k + 1
                    continue
                # C++ direct initialisation  string s("hi");
                sym = Symbol(name, "var", typ, t.line, t.col, name_i, initialized=True, pointer=ptr)
                self.add(sym)
                for q in range(j + 1, close):
                    self.record_use(q)
                recorded += 1
                j = close + 1
            else:
                sizes = []
                while self.tok(j) is not None and self.tok(j).is_op("["):
                    close = self.match.get(j)
                    if close is None:
                        break
                    inner = self.toks[j + 1:close]
                    sizes.append(self._const_value(inner))
                    for q in range(j + 1, close):
                        self.record_use(q)
                    j = close + 1
                kind = "typedef" if is_typedef else "var"
                sym = Symbol(name, kind, typ, t.line, t.col, name_i, pointer=ptr, array_sizes=sizes)
                if is_typedef:
                    self.t.type_names.add(name)
                nxt = self.tok(j)
                if nxt is not None and nxt.is_op(":") and self.cpp:
                    sym.initialized = True          # range-based for:  for (int x : v)
                if nxt is not None and nxt.is_op("="):
                    sym.initialized = True
                    j = self._skip_initializer(j + 1)
                elif nxt is not None and nxt.is_op("{"):
                    sym.initialized = True
                    j = self.match.get(j, j) + 1
                self.add(sym)
                recorded += 1
            t = self.tok(j)
            if t is None:
                return j
            if t.is_op(","):
                j += 1
                continue
            if t.is_op(";"):
                return j + 1
            if t.is_op(":") and not self.cpp:
                return self._skip_to_end(j)
            return j

    def _skip_initializer(self, j):
        depth = 0
        while j < len(self.toks):
            t = self.toks[j]
            if t.is_op("(", "[", "{"):
                depth += 1
            elif t.is_op(")", "]", "}"):
                if depth == 0:
                    return j
                depth -= 1
            elif t.is_op(",", ";") and depth == 0:
                return j
            else:
                self.record_use(j)
            j += 1
        return j

    def _skip_to_end(self, j):
        while j < len(self.toks) and not self.toks[j].is_op(";", "{", "}"):
            j += 1
        if j < len(self.toks) and self.toks[j].is_op(";"):
            return j + 1
        return j

    def _looks_like_params(self, toks):
        if not toks:
            return True
        first = toks[0]
        if first.is_op("..."):
            return True
        if first.kind == "kw" and (first.text in TYPE_KEYWORDS or first.text in QUALIFIERS or
                                   first.text in ("struct", "union", "enum", "class")):
            return True
        if first.kind == "id" and first.text in self.t.type_names:
            return True
        return False

    def _params(self, toks, base):
        params = []
        variadic = False
        if not toks or (len(toks) == 1 and toks[0].is_kw("void")):
            return params, variadic
        parts = []
        cur = []
        depth = 0
        for k, t in enumerate(toks):
            if t.is_op("(", "[", "<"):
                depth += 1
            elif t.is_op(")", "]", ">"):
                depth -= 1
            if t.is_op(",") and depth == 0:
                parts.append(cur)
                cur = []
            else:
                cur.append((base + k, t))
        if cur:
            parts.append(cur)
        for part in parts:
            if len(part) == 1 and part[0][1].is_op("..."):
                variadic = True
                continue
            name_idx, name_tok = None, None
            for idx, t in reversed(part):
                if t.kind == "id" and t.text not in self.t.type_names:
                    name_idx, name_tok = idx, t
                    break
            typ_toks = [t.text for idx, t in part if idx != name_idx and t.text not in ("[", "]")]
            pointer = sum(1 for idx, t in part if t.is_op("*"))
            arrays = [None] if any(t.is_op("[") for idx, t in part) else []
            typ = " ".join(x for x in typ_toks if x not in ("*", "&", "const"))
            if name_tok is not None:
                params.append(Symbol(name_tok.text, "param", typ, name_tok.line, name_tok.col, name_idx,
                                     initialized=True, pointer=pointer + len(arrays)))
            else:
                params.append(Symbol("", "param", typ, 0, 0, -1, initialized=True, pointer=pointer))
        return params, variadic

    def _const_value(self, toks):
        if len(toks) == 1:
            t = toks[0]
            if t.kind == "int":
                try:
                    return int(t.text.rstrip("uUlL"), 0)
                except ValueError:
                    return None
            if t.kind == "id" and t.text in self.t.macros:
                v = self.t.macros[t.text].value.strip().rstrip(";").strip()
                if re.fullmatch(r"\d+", v):
                    return int(v)
            if t.kind == "id":
                for s in reversed(self.t.symbols):
                    if s.name == t.text and s.kind == "var" and s.initialized and getattr(s, "_const", None):
                        return s._const
        return None


def build(tokens, match, lang="c"):
    return SymbolTableBuilder(tokens, match, lang).build()
