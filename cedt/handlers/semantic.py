"""Handlers for semantic-analysis rules (C and C++)."""
import re

from ..source_lexer import C_KEYWORDS, CPP_KEYWORDS
from ..symbols import C_TYPEDEFS, CPP_TYPES, TYPE_KEYWORDS
from ..textutil import case_only_difference, closest
from .base import Result, call_args, code, handler, insert_at, replace_word, text_of, veto

COMMON_KEYWORDS = ["return", "while", "for", "if", "else", "int", "char", "float", "double", "break",
                   "continue", "switch", "case", "default", "struct", "void", "sizeof", "const",
                   "unsigned", "long", "short", "static", "do", "printf", "scanf", "main"]
TYPE_ALIASES = {"integer": "int", "Integer": "int", "INT": "int", "boolean": "bool", "Boolean": "bool",
                "real": "float", "Real": "float", "String": "string", "character": "char",
                "Character": "char", "Double": "double", "Float": "float", "Char": "char", "Int": "int",
                "Void": "void", "Long": "long", "Bool": "bool"}
STRING_METHODS = ["length", "size", "substr", "find", "rfind", "append", "c_str", "at", "empty", "clear",
                  "push_back", "pop_back", "insert", "erase", "replace", "compare", "begin", "end",
                  "front", "back", "resize", "data", "find_first_of", "find_last_of"]
VECTOR_METHODS = ["size", "push_back", "pop_back", "at", "front", "back", "begin", "end", "empty", "clear",
                  "insert", "erase", "resize", "reserve", "emplace_back", "data", "capacity", "assign"]


# --------------------------------------------------------------------- helpers
def _name_token(ctx, name):
    src = ctx.src
    if src is None or not ctx.line_no:
        return None
    t = ctx.tok
    if t is not None and t.text == name:
        return t
    best = None
    idx = ctx.col_index() or 0
    for tk in src.tokens_on_line(ctx.line_no):
        if tk.text == name and (best is None or abs(tk.col - 1 - idx) < abs(best.col - 1 - idx)):
            best = tk
    return best


def include_fix(ctx, header):
    """(line_no, text, kind) that adds #include <header> to the file."""
    src = ctx.src
    text = "#include <%s>" % header
    if src is None:
        return None
    incs = src.includes()
    if incs:
        last = max(l for _, l, _ in incs)
        return last + 1, text, "insert_before"
    return 1, text, "insert_before"


def _has_include(ctx, header):
    if ctx.src is None:
        return False
    names = [h for h, _, _ in ctx.src.includes()]
    return header in names or "bits/stdc++.h" in names


def _function_header_text(src, sym):
    """'float area(float r)' from the definition line of a function symbol."""
    if src is None or sym is None or sym.tok < 0:
        return None
    name_tok = src.tokens[sym.tok]
    open_p = src.next_token(name_tok)
    if open_p is None or not open_p.is_op("("):
        return None
    close = src.brackets.match.get(open_p.index)
    if close is None:
        return None
    # start of the declaration: walk back over type words
    k = sym.tok - 1
    while k >= 0 and (src.tokens[k].kind in ("kw", "id") or src.tokens[k].is_op("*", "&", "::")) \
            and src.tokens[k].line >= name_tok.line - 1:
        k -= 1
    toks = src.tokens[k + 1:close + 1]
    return text_of(toks)


def _enclosing_function_sym(ctx, line):
    if ctx.symbols is None:
        return None
    scope = ctx.symbols.function_scope_at_line(line)
    if scope is None:
        return None
    for s in ctx.symbols.symbols:
        if s.kind in ("func", "method") and (s.name == scope.name):
            return s
    return None


# --------------------------------------------------------------------- M001
@handler("undeclared")
def undeclared(ctx):
    name = ctx.groups.get("name", "")
    if name.startswith("std::"):
        name = name[5:]
    suggest = ctx.groups.get("suggest")
    r = Result(vars={"name": name})
    src = ctx.src
    tok = _name_token(ctx, name)
    line = ctx.line_text() or ""
    is_call = tok is not None and src.next_token(tok) is not None and src.next_token(tok).is_op("(")
    if is_call:
        kw = _statement_keyword(ctx, name, tok)
        if kw:
            return _keyword_typo(r, name, kw, line, tok)
    if not ctx.cpp and name in ("cin", "cout", "endl", "cerr"):
        r.title = "C++ code in a C program"
        r.what = ("`%s` is part of C++, but this file is compiled as C (a `.c` file). C has no `%s`." % (name, name))
        r.what += " In C, input/output is done with `scanf` and `printf` from <stdio.h>."
        r.fix = ["Either save the file as `.cpp` (choose C++) and add `#include <iostream>` and "
                 "`using namespace std;`,",
                 "or write it in C: `scanf(\"%d\", &x);` instead of `cin >> x;` and "
                 "`printf(\"%d\\n\", x);` instead of `cout << x << endl;`."]
        r.why = ["C++ code (cin/cout) written in a file that is compiled as C."]
        r.no_fix = True
        return r

    # 1. names from the C / C++ standard library
    if ctx.cpp and ctx.is_cpp_std_name(name):
        header = ctx.header_for(name)
        if header and not _has_include(ctx, header):
            r.title = "Missing #include <%s>" % header
            r.what = "`%s` belongs to the C++ standard library header `<%s>`, which this program does not include." % (name, header)
            r.fix = ["Add `#include <%s>` at the top of the file." % header,
                     "Then write `std::%s` (or add `using namespace std;` once, below the includes)." % name]
            fx = include_fix(ctx, header)
            if fx:
                r.fixed_line_no, r.fixed_line, r.fixed_kind = fx
            return r
        r.title = "`%s` needs std:: (or using namespace std)" % name
        r.what = ("`%s` lives inside the `std` namespace of the C++ library. Its full name is `std::%s`."
                  % (name, name))
        r.fix = ["Write `std::%s`, or add `using namespace std;` once below the #include lines." % name]
        if line and tok is not None:
            fixed = replace_word(line, name, "std::" + name, near=tok.col - 1)
            if fixed:
                r.fixed_line = fixed
        return r
    if not ctx.cpp and name in ("true", "false", "bool"):
        r.title = "`%s` needs <stdbool.h> in C" % name
        r.what = "In C (before C23) `bool`, `true` and `false` are not built in - they come from the header `<stdbool.h>`."
        r.fix = ["Add `#include <stdbool.h>` at the top (or use int with 1 / 0)."]
        fx = include_fix(ctx, "stdbool.h")
        if fx:
            r.fixed_line_no, r.fixed_line, r.fixed_kind = fx
        return r
    header = None if ctx.cpp else ctx.data.get("stdlib", {}).get("c_names", {}).get(name)
    if ctx.cpp and not header:
        cn = ctx.data.get("stdlib", {}).get("c_names", {}).get(name)
        if cn and not ctx.is_cpp_std_name(name):
            header = cn
    if header and not _has_include(ctx, header):
        r.title = "Missing #include <%s>" % header
        r.what = "`%s` is defined in the standard header `<%s>`, which this program does not include." % (name, header)
        r.fix = ["Add `#include <%s>` at the top of the file." % header]
        if name == "M_PI":
            r.hints.append("M_PI is not strictly standard: on Windows/MinGW write `#define _USE_MATH_DEFINES` "
                           "before `#include <math.h>`, or define it yourself: `#define PI 3.14159265358979`.")
        fx = include_fix(ctx, header)
        if fx:
            r.fixed_line_no, r.fixed_line, r.fixed_kind = fx
        return r

    # 1b. undeclared name used like a type:  string name = ...;  bool done;
    if src is not None and tok is not None:
        nx = src.next_token(tok)
        pv = src.prev_token(tok)
        if nx is not None and nx.kind == "id" and (pv is None or pv.is_op(";", "{", "}", "(", ",") or pv.kind == "pp"):
            return Result(redirect="M004", vars={"name": name})

    # 2. misspelled keyword (retrun 0;  whlie (...))
    kw = closest(name, COMMON_KEYWORDS, limit=2, max_results=1)
    declared_anywhere = src is not None and bool(src.symbols.declarations(name))
    if kw and kw[0] in (C_KEYWORDS | CPP_KEYWORDS) and not declared_anywhere and not is_call:
        k = kw[0]
        nxt = src.next_token(tok) if (src is not None and tok is not None) else None
        if k in ("return", "break", "continue") or (nxt is not None and nxt.kind in ("int", "float", "id", "char", "str")) \
                or case_only_difference(name, k) or (nxt is not None and nxt.is_op("(") and k in ("while", "for", "if", "switch")):
            r.title = "Misspelled keyword `%s`" % k
            r.what = "`%s` is not a C/C++ word. It looks like the keyword `%s` with a typing mistake." % (name, k)
            if case_only_difference(name, k):
                r.what += " Keywords are always lowercase."
            r.fix = ["Write `%s`." % k]
            if line:
                fixed = replace_word(line, name, k)
                if fixed:
                    r.fixed_line = fixed
            return r

    # 3. declared somewhere else -> scope analysis
    if src is not None and tok is not None:
        decls = [s for s in src.symbols.declarations(name)
                 if s.kind in ("var", "param", "enum_const", "func", "proto") and s.tok >= 0]
        if decls:
            use_i = tok.index
            chain = src.symbols.scope_chain(src.symbols.scope_at(use_i))
            same_chain_later = [d for d in decls if d.scope in chain and d.tok > use_i]
            if same_chain_later:
                d = same_chain_later[0]
                r.title = "Variable used before it is declared"
                r.what = ("`%s` is declared on line %d, but it is used earlier, on line %d. In C/C++ a name must be "
                          "declared before its first use." % (name, d.line, ctx.line_no))
                r.fix = ["Move the declaration `%s` above line %d." % (src.line(d.line).strip(), ctx.line_no)]
                r.real_line = d.line
                return r
            visible_before = [d for d in decls if d.scope in chain and d.tok < use_i and d.kind in ("var", "param")]
            if visible_before:
                d = visible_before[0]
                r.title = "Declaration of `%s` failed earlier" % name
                r.what = ("`%s` IS declared on line %d, but that line has its own error, so the compiler ignored the "
                          "declaration. Fix line %d first - this message will then disappear." % (name, d.line, d.line))
                r.fix = ["Fix the error on line %d (the declaration of `%s`)." % (d.line, name)]
                r.real_line = d.line
                r.confidence = "medium"
                r.no_fix = True
                r.vars["decl_line"] = d.line
                return r
            other = [d for d in decls if d.scope not in chain]
            if other:
                d = other[0]
                sc = src.symbols.scopes[d.scope]
                desc = src.symbols.scope_description(d.scope, src.tokens)
                if sc.kind == "function":
                    r.title = "Variable belongs to another function"
                    r.what = ("`%s` is a local variable of %s (declared on line %d). Each function has its own "
                              "local variables; they cannot be seen from another function." % (name, desc, d.line))
                    r.fix = ["Pass `%s` as a parameter, return it, or declare it here as well." % name]
                else:
                    r.title = "Variable used outside its block (scope)"
                    r.what = ("`%s` was declared on line %d inside %s. A variable only exists inside the block "
                              "where it is declared, so it no longer exists on line %d." % (
                                  name, d.line, desc, ctx.line_no))
                    r.fix =["Declare `%s` BEFORE that block (e.g. `%s %s;` above it), so both places can use it." % (
                        name, d.type or "int", name)]
                r.real_line = d.line
                r.no_fix = True
                r.vars["decl_line"] = d.line
                return r

    # 3b. a loop counter that was never declared:  for (i = 1; i <= n; i++)
    if src is not None and tok is not None and not declared_anywhere:
        for t in src.tokens_on_line(ctx.line_no):
            op = src.next_token(t) if t.is_kw("for") else None
            first = src.next_token(op) if op is not None and op.is_op("(") else None
            eq = src.next_token(first) if first is not None else None
            if first is not None and first.text == name and eq is not None and eq.is_op("="):
                r.title = "Loop counter `%s` is not declared" % name
                r.what = ("The `for` loop on line %d uses `%s` as its counter, but `%s` was never declared. Every "
                          "variable - also a loop counter - must be created with a type first." % (
                              t.line, name, name))
                r.fix = ["Declare it inside the loop: `for (int %s = ...; ...)`," % name,
                         "or at the top of the function: `int %s;`." % name]
                r.why = ["The counter was used without `int` - in C/C++ even `i` must be declared."]
                line_t = src.line(t.line)
                r.fixed_line = line_t[:first.col - 1] + "int " + line_t[first.col - 1:]
                r.fixed_line_no = t.line
                r.real_line = t.line
                r.example = {"wrong": "for (i = 0; i < 5; i++)", "right": "for (int i = 0; i < 5; i++)"}
                return r

    # 4. a typing mistake of a visible name
    cands = []
    if src is not None and tok is not None:
        cands = [s.name for s in src.symbols.visible_at(tok.index)]
        cands += [s.name for s in src.symbols.symbols if s.kind in ("func", "proto", "macro", "enum_const")]
    sug = suggest.replace("std::", "") if suggest else None
    partial = src is None or getattr(src, "partial", False)
    if sug and partial:
        pass            # log mode: we cannot see the declarations, so trust the compiler's own suggestion
    elif not sug or sug not in cands:
        found = closest(name, cands)
        if found:
            sug = found[0]
        elif sug and (sug in COMMON_KEYWORDS or (is_call and sug in ctx.known_functions())):
            pass
        else:
            sug = None
    if sug and len(name) == 1 and not partial and not case_only_difference(name, sug):
        sug = None      # every one-letter name is "one typo" away from every other (i -> n)
    if sug:
        r.title = "Misspelled name - did you mean `%s`?" % sug
        if case_only_difference(name, sug):
            r.what = ("`%s` is not declared, but `%s` is. C/C++ is case-sensitive: `%s` and `%s` are different "
                      "names." % (name, sug, name, sug))
        else:
            r.what = "`%s` is not declared, but `%s` is - this looks like a typing mistake." % (name, sug)
        r.fix = ["Change `%s` to `%s` on line %s." % (name, sug, ctx.line_no)]
        if line:
            fixed = replace_word(line, name, sug, near=(tok.col - 1) if tok is not None else None)
            if fixed:
                r.fixed_line = fixed
        r.vars["suggest"] = sug
        return r

    # 5. a function defined further down (C++ has no implicit declarations)
    if src is not None and is_call:
        fdef, proto = src.symbols.function_named(name)
        if fdef is not None and fdef.line > (ctx.line_no or 0):
            hdr = _function_header_text(src, fdef)
            r.title = "Function used before it is declared"
            r.what = ("`%s()` is defined on line %d, below the line that calls it (%d). A function must be declared "
                      "before it is called." % (name, fdef.line, ctx.line_no))
            r.fix = ["Add the prototype `%s;` above main(), or move the whole function above main()." % (hdr or name + "(...)")]
            if hdr:
                main = [s for s in src.symbols.symbols if s.kind == "func" and s.name == "main"]
                r.fixed_line = hdr + ";"
                r.fixed_line_no = main[0].line if main else 1
                r.fixed_kind = "insert_before"
            return r

    r.title = "Name used but never declared"
    r.no_fix = True
    r.what = "`%s` is used on line %s but it is not declared anywhere in your program." % (name, ctx.line_no)
    r.fix = ["Declare it before use, with a type: `int %s = 0;` (or the type you need)." % name]
    return r


STATEMENT_KEYWORDS = ("for", "while", "if", "switch", "return", "do", "else", "sizeof")


def _statement_keyword(ctx, name, tok):
    """`For (...)`, `WHILE (...)`, `whlie (...)` look like calls to an unknown function -> the keyword meant."""
    if ctx.src is not None and tok is not None:
        pv = ctx.src.prev_token(tok)
        if pv is not None and not (pv.is_op(";", "{", "}", ")") or pv.is_kw("else") or pv.kind == "pp"):
            return None             # not at the start of a statement
        if ctx.src.symbols.function_named(name)[0] is not None:
            return None
    for k in STATEMENT_KEYWORDS:
        if case_only_difference(name, k):
            return k
    if len(name) >= 4 and name not in ctx.known_functions():
        found = closest(name, STATEMENT_KEYWORDS, limit=1, max_results=1)
        if found and found[0] not in ("do", "if"):
            return found[0]
    return None


def _keyword_typo(r, name, kw, line, tok):
    r.title = "Misspelled keyword `%s`" % kw
    if case_only_difference(name, kw):
        r.title = "Keyword `%s` written with a capital letter" % kw
        r.what = ("`%s` is not the keyword `%s`: C/C++ is case-sensitive and all keywords are lowercase. Because "
                  "`%s (...)` looks like a function call, the compiler thinks you are calling an unknown function "
                  "named `%s`." % (name, kw, name, name))
    else:
        r.what = ("`%s` is not a C/C++ word - it looks like the keyword `%s` with a typing mistake. Because "
                  "`%s (...)` looks like a function call, the compiler thinks you are calling an unknown function."
                  % (name, kw, name))
    r.fix = ["Write `%s` (all lowercase)." % kw]
    r.why = ["C/C++ is case-sensitive: `for`, `For` and `FOR` are three different words, and only `for` is the keyword."]
    fixed = replace_word(line, name, kw, near=(tok.col - 1) if tok is not None else None)
    if fixed:
        r.fixed_line = fixed
    r.example = {"wrong": "For (i = 0; i < 5; i++)", "right": "for (i = 0; i < 5; i++)"}
    return r


# --------------------------------------------------------------------- M002
NONSTD_FIX = {
    "getch": "Use `getchar();` from <stdio.h> to wait for a key (press Enter).",
    "getche": "Use `getchar();` from <stdio.h>.",
    "clrscr": "Simply delete it - the screen does not need clearing. (Windows: `system(\"cls\");`, Linux/macOS: `system(\"clear\");`)",
    "kbhit": "There is no portable replacement; restructure the program to read input with getchar()/scanf().",
    "gotoxy": "Not available in standard C; print spaces/newlines instead.",
    "strrev": "Write a small loop that swaps characters from both ends of the string.",
    "strupr": "Loop over the string and use `toupper()` from <ctype.h> on each character.",
    "strlwr": "Loop over the string and use `tolower()` from <ctype.h> on each character.",
    "itoa": "Use `sprintf(buffer, \"%d\", number);`.",
    "delay": "Use `sleep(seconds)` from <unistd.h> (Linux/macOS) or `Sleep(ms)` from <windows.h>.",
}


@handler("implicit_function")
def implicit_function(ctx):
    name = ctx.groups.get("name", "")
    suggest = ctx.groups.get("suggest")
    r = Result(vars={"name": name})
    src = ctx.src
    line = ctx.line_text() or ""
    tok = _name_token(ctx, name)
    kw = _statement_keyword(ctx, name, tok)
    if kw:
        return _keyword_typo(r, name, kw, line, tok)
    nonstd = ctx.nonstandard(name)
    if nonstd:
        r.title = "Non-standard function %s()" % name
        r.what = ("`%s()` is not part of standard C. It only existed in Turbo C / Windows compilers (%s)."
                  % (name, nonstd))
        r.fix = [NONSTD_FIX.get(name, "Replace it with a standard function.")]
        if name in ("getch", "getche"):
            fixed = replace_word(line, name, "getchar")
            if fixed:
                r.fixed_line = fixed
        elif name == "clrscr" and re.match(r"^\s*clrscr\s*\(\s*\)\s*;\s*$", line):
            r.fixed_line = ""
            r.fixed_kind = "delete"
        return r
    if name == "gets":
        r.title = "gets() was removed from C"
        r.what = ("`gets()` was removed from the C language (C11) because it cannot check the array size - "
                  "long input overflows the array.")
        r.fix = ["Use `fgets(array, sizeof array, stdin);` instead."]
        m = re.search(r"\bgets\s*\(\s*(\w+)\s*\)", line)
        if m:
            r.fixed_line = line[:m.start()] + "fgets(%s, sizeof %s, stdin)" % (m.group(1), m.group(1)) + line[m.end():]
        return r
    header = ctx.data.get("stdlib", {}).get("c_functions", {}).get(name)
    if ctx.cpp and header:
        header = "c" + header[:-2] if header.endswith(".h") else header
    if header:
        r.title = "Missing #include <%s>" % header
        r.what = ("`%s()` is a library function declared in `<%s>`, but the program does not `#include` it, "
                  "so the compiler does not know its type." % (name, header))
        r.fix = ["Add `#include <%s>` at the top of the file." % header]
        if header in ("math.h", "cmath") and not ctx.cpp:
            r.hints.append("On Linux, maths functions also need the maths library at link time: "
                           "`gcc prog.c -o prog -lm`.")
        fx = include_fix(ctx, header)
        if fx:
            r.fixed_line_no, r.fixed_line, r.fixed_kind = fx
        r.vars["header"] = header
        return r
    if src is not None:
        fdef, proto = src.symbols.function_named(name)
        if fdef is not None and fdef.line >= (ctx.line_no or 0):
            hdr = _function_header_text(src, fdef)
            r.title = "Function used before it is declared"
            r.what = ("`%s()` is defined on line %d, BELOW the line that calls it (line %d). C reads the file from "
                      "top to bottom, so at line %d it does not know `%s` yet and has to guess its type."
                      % (name, fdef.line, ctx.line_no, ctx.line_no, name))
            r.fix = ["Add a prototype above main(): `%s;`" % (hdr or name + "(...)"),
                     "Or move the whole function `%s` above main()." % name]
            if hdr:
                main = [s for s in src.symbols.symbols if s.kind == "func" and s.name == "main"]
                r.fixed_line = hdr + ";"
                r.fixed_line_no = main[0].line if main else 1
                r.fixed_kind = "insert_before"
            return r
    cands = ctx.known_functions()
    sug = suggest or (closest(name, cands, max_results=1) or [None])[0]
    if sug:
        r.title = "Misspelled function name - did you mean %s()?" % sug
        r.what = "There is no function called `%s`. You probably meant `%s`." % (name, sug)
        r.fix = ["Change `%s` to `%s`." % (name, sug)]
        fixed = replace_word(line, name, sug, near=(tok.col - 1) if tok is not None else None)
        if fixed:
            r.fixed_line = fixed
        return r
    r.title = "Function is not defined anywhere"
    r.what = "`%s()` is called on line %s, but it is not defined in your program and is not a standard library function." % (
        name, ctx.line_no)
    r.fix = ["Write the function `%s` (above main), or correct the name." % name]
    return r


@handler("implicit_int")
def implicit_int(ctx):
    line = ctx.line_text() or ""
    r = Result()
    m = re.match(r"^(\s*)(main\s*\(.*)$", line)
    if m:
        r.fixed_line = m.group(1) + "int " + m.group(2)
        return r
    idx = ctx.col_index()
    if idx is not None and line:
        kind = "int "
        if ctx.src is not None and ctx.line_no and "(" in line:
            # look at the body: a function that never returns a value should be void
            depth, body, started = 0, [], False
            for n in range(ctx.line_no, min(ctx.line_no + 200, len(ctx.src.lines) + 1)):
                t = ctx.src.line(n) or ""
                body.append(t)
                depth += t.count("{") - t.count("}")
                started = started or "{" in t
                if started and depth <= 0:
                    break
            if started and not re.search(r"\breturn\s+[^;\s]", "\n".join(body)):
                kind = "void "
                r.fix = ["This function never returns a value, so write `void` in front of it: `void %s`."
                         % line.strip().rstrip("{").strip()]
        r.fixed_line = insert_at(line, idx, kind)
    return r


# --------------------------------------------------------------------- M004
@handler("unknown_type")
def unknown_type(ctx):
    name = ctx.groups.get("name", "")
    suggest = ctx.groups.get("suggest")
    r = Result(vars={"name": name})
    line = ctx.line_text() or ""
    src = ctx.src
    if not ctx.cpp and name == "bool":
        r.title = "bool needs <stdbool.h> in C"
        r.what = "In C (before C23) the type `bool` is not built in - it comes from `<stdbool.h>`."
        r.fix = ["Add `#include <stdbool.h>` at the top (or use `int` with 1 / 0)."]
        fx = include_fix(ctx, "stdbool.h")
        if fx:
            r.fixed_line_no, r.fixed_line, r.fixed_kind = fx
        return r
    if not ctx.cpp and name in ("string", "String"):
        r.title = "C has no string type"
        r.what = ("C has no `string` type (that is C++). In C a string is an ARRAY of characters ending with "
                  "`\\0`.")
        r.fix = ["Declare a char array: `char name[50];` and fill it with `strcpy`, `scanf(\"%49s\", name)` or `fgets`."]
        m = re.search(r"\b%s\s+(\w+)\s*(=\s*\"[^\"]*\")?" % name, line)
        if m:
            size = "" if m.group(2) else "100"
            r.fixed_line = line[:m.start()] + "char %s[%s]%s" % (m.group(1), size, (" " + m.group(2)) if m.group(2) else "") + line[m.end():]
        return r
    if ctx.cpp and (name in CPP_TYPES or ctx.is_cpp_std_name(name)):
        header = ctx.header_for(name) or "string"
        if not _has_include(ctx, header):
            r.title = "Missing #include <%s>" % header
            r.what = "`%s` is a C++ library type from `<%s>`, which this program does not include." % (name, header)
            r.fix = ["Add `#include <%s>` and use `std::%s` (or `using namespace std;`)." % (header, name)]
            fx = include_fix(ctx, header)
            if fx:
                r.fixed_line_no, r.fixed_line, r.fixed_kind = fx
            return r
        r.title = "`%s` needs std::" % name
        r.what = "`%s` is in the `std` namespace: write `std::%s`, or add `using namespace std;` below the includes." % (name, name)
        r.fix = ["Write `std::%s`." % name]
        fixed = replace_word(line, name, "std::" + name)
        if fixed:
            r.fixed_line = fixed
        return r
    if src is not None and not ctx.cpp:
        st = src.symbols.struct_named(name)
        if st is not None:
            r.title = "Missing the word struct"
            r.what = ("`%s` is a structure. In C you must write the keyword `struct` in front of its name: "
                      "`struct %s`." % (name, name))
            r.fix = ["Write `struct %s`, or create a short name once: `typedef struct %s %s;`." % (name, name, name)]
            fixed = replace_word(line, name, "struct " + name)
            if fixed:
                r.fixed_line = fixed
            return r
    pool = set(TYPE_KEYWORDS) | {"int", "char", "float", "double", "void", "long", "short", "unsigned"}
    pool |= set(C_TYPEDEFS) - {"bool"} if not ctx.cpp else set(C_TYPEDEFS) | set(CPP_TYPES)
    if src is not None:
        pool |= set(src.symbols.type_names) | set(src.symbols.struct_names())
    alias = TYPE_ALIASES.get(name)
    sug = suggest or alias
    if not sug:
        found = closest(name, pool, max_results=1)
        sug = found[0] if found else None
    if sug == "string" and not ctx.cpp:
        sug = "char[]"
    if sug:
        r.title = "Unknown type `%s` - did you mean `%s`?" % (name, sug)
        if case_only_difference(name, sug):
            r.what = "`%s` is not a type. C/C++ is case-sensitive and type names are lowercase: `%s`." % (name, sug)
        elif name in TYPE_ALIASES:
            r.what = "`%s` is not a C/C++ type name (it is used in other languages or pseudo-code). The C/C++ type is `%s`." % (name, sug)
        else:
            r.what = "There is no type called `%s`. You probably meant `%s`." % (name, sug)
        r.fix = ["Write `%s`." % sug]
        if sug != "char[]":
            fixed = replace_word(line, name, sug)
            if fixed:
                r.fixed_line = fixed
        r.vars["suggest"] = sug
        return r
    r.what = ("There is no type called `%s`. If it is your own struct/class, it must be defined above this line; "
              "if it is a library type, check its #include." % name)
    return r


# --------------------------------------------------------------------- M005
def _find_call_at(ctx):
    """(name_token, args) of the function call around the error position."""
    src = ctx.src
    if src is None or not ctx.line_no:
        return None, None
    func = ctx.groups.get("func")
    if func:
        func = func.split("(")[0].split("::")[-1].strip()
    idx = ctx.col_index() or 0
    best = None
    for t in src.tokens_on_line(ctx.line_no):
        if t.kind != "id":
            continue
        nx = src.next_token(t)
        if nx is None or not nx.is_op("("):
            continue
        if func and t.text != func:
            continue
        close = src.brackets.match.get(nx.index)
        end_col = src.tokens[close].col if close is not None else 10 ** 6
        if func or (t.col - 1 <= idx <= end_col):
            if best is None or t.col > best.col:
                best = t
    if best is None:
        return None, None
    return best, call_args(src, best)


@handler("arg_count")
def arg_count(ctx):
    r = Result()
    amount = ctx.groups.get("amount", "few")
    name_tok, args = _find_call_at(ctx)
    func = (ctx.groups.get("func") or (name_tok.text if name_tok is not None else "the function"))
    func = func.split("(")[0].strip()
    r.vars["func"] = func
    have = ctx.groups.get("have")
    if have is None and args is not None:
        have = str(len(args))
    expected = ctx.groups.get("expected")
    signature = None
    src = ctx.src
    if src is not None:
        fdef, proto = src.symbols.function_named(func)
        sym = fdef or proto
        if sym is not None:
            if expected is None:
                expected = str(len(sym.params)) + (" or more" if sym.variadic else "")
            signature = _function_header_text(src, sym)
    n, _ = ctx.note(r"declared here")
    if signature is None and n is not None and n.location:
        info = (n.extra.get("snippet_info") or {}).get("src") or {}
        signature = (info.get(n.location.line) or "").strip().rstrip("{").strip()
    r.vars["have"] = have or "a different number of"
    r.vars["expected"] = expected or "a different number"
    r.vars["signature"] = signature or func + "(...)"
    if func in ("printf", "scanf") and (have in (None, "0")):
        r.title = "%s() called without a format string" % func
        r.what = "`%s` needs at least a format string in double quotes, e.g. `%s(\"%%d\", x)`." % (func, func)
        r.fix = ["Write `%s(\"...\")` with the text/placeholders inside the brackets." % func]
        return r
    if have and expected:
        r.what = "The call to `%s` on line %s passes %s argument(s), but `%s` expects %s." % (
            func, ctx.line_no, have, func, expected)
    r.title = "Too %s arguments in the call to %s()" % (amount, func)
    return r


# --------------------------------------------------------------------- M006
@handler("lvalue")
def lvalue(ctx):
    r = Result()
    src = ctx.src
    line = ctx.line_text() or ""
    if src is None or not line:
        return r
    eq = None
    idx = ctx.col_index() or 0
    for t in src.tokens_on_line(ctx.line_no):
        if t.is_op("=") and (eq is None or abs(t.col - 1 - idx) < abs(eq.col - 1 - idx)):
            eq = t
    if ctx.groups.get("op") in ("increment", "decrement"):
        r.what = "`++` and `--` can only be applied to a variable, not to a value or calculation (line %s)." % ctx.line_no
        return r
    if eq is None:
        return r
    # inside an if/while condition?
    k = eq.index
    depth = 0
    head = None
    while k >= 0:
        t = src.tokens[k]
        if t.is_op(")"):
            depth += 1
        elif t.is_op("("):
            if depth == 0:
                head = src.tok(k - 1)
                break
            depth -= 1
        elif t.is_op(";", "{", "}"):
            break
        k -= 1
    if head is not None and head.kind == "kw" and head.text in ("if", "while", "for"):
        r.title = "= used instead of == in a condition"
        r.what = ("Inside the `%s` condition on line %s you wrote `=` (STORE a value). To COMPARE two values "
                  "use `==`." % (head.text, ctx.line_no))
        r.fix = ["Change `=` to `==`."]
        r.fixed_line = line[:eq.col - 1] + "==" + line[eq.col:]
        return r
    left = src.tok(eq.index - 1)
    stmt = src.statement_tokens(eq)
    lhs = [t for t in stmt if t.pos < eq.pos]
    if lhs and lhs[0].kind in ("int", "float", "char", "str"):
        r.title = "Value and variable swapped"
        r.what = "The left side of `=` is a constant (`%s`). The variable must be on the LEFT: `variable = value;`." % text_of(lhs)
        rhs = [t for t in stmt if t.pos > eq.pos and not t.is_op(";")]
        if rhs:
            r.fixed_line = line[:lhs[0].col - 1] + text_of(rhs) + " = " + text_of(lhs) + ";"
        return r
    if lhs:
        r.what = ("`%s` is a calculation, not a variable, so nothing can be stored into it. Put a single variable "
                  "on the left of `=`." % text_of(lhs))
    return r


# --------------------------------------------------------------------- M007
@handler("array_assign")
def array_assign(ctx):
    r = Result()
    line = ctx.line_text() or ""
    m = re.match(r"^(\s*)(\w+)\s*=\s*(.+?)\s*[;:]?\s*$", line)
    if not m:
        return r
    indent, name, rhs = m.group(1), m.group(2), m.group(3)
    src = ctx.src
    sym = None
    if src is not None:
        sym = src.symbols.lookup(name, ctx.tok.index if ctx.tok is not None else 10 ** 6)
    base = (sym.type if sym is not None else "").replace("const ", "").strip()
    size = sym.array_sizes[0] if sym is not None and sym.array_sizes else None
    r.vars["name"] = name
    # (a) text into a char array:  name = "Ram";
    if rhs.startswith('"') and rhs.endswith('"'):
        r.title = "Strings cannot be copied with ="
        r.what = ("`%s` is a char array. In C a string cannot be copied into an array with `=`; the text must be "
                  "COPIED with strcpy." % name)
        r.fix = ["Write `strcpy(%s, %s);` (needs `#include <string.h>`)." % (name, rhs),
                 "Or give the text when the array is created: `char %s[%s] = %s;`" % (name, size or 20, rhs)]
        r.example = {"wrong": "char name[20];\nname = \"Ram\";", "right": "char name[20];\nstrcpy(name, \"Ram\");"}
        r.fixed_line = "%sstrcpy(%s, %s);" % (indent, name, rhs)
        if not _has_include(ctx, "string.h"):
            r.hints.append("strcpy() needs `#include <string.h>` at the top of the file.")
        return r
    # (b) one array into another:  a = b;
    other = src.symbols.lookup(rhs, ctx.tok.index if ctx.tok is not None else 10 ** 6) \
        if (src is not None and re.fullmatch(r"\w+", rhs)) else None
    if other is not None and other.is_array:
        r.title = "Arrays cannot be copied with ="
        r.what = ("`%s` and `%s` are both arrays. C cannot copy a whole array with `=`; copy it element by element."
                  % (name, rhs))
        r.fix = ["Use a loop: `for (int i = 0; i < %s; i++) %s[i] = %s[i];`" % (size or "N", name, rhs),
                 "Or `memcpy(%s, %s, sizeof %s);` (needs `#include <string.h>`)." % (name, rhs, name)]
        if base.startswith("char"):
            r.fix.append("For strings: `strcpy(%s, %s);`" % (name, rhs))
        r.no_fix = True
        return r
    # (c) one value into a whole array:  int a[10];  a = x + y;
    kind = ("%d `%s`s" % (size, base)) if (size and base) else ("`%s` values" % base if base else "values")
    decl = (" (declared on line %d)" % sym.line) if sym is not None and sym.line else ""
    r.title = "One value stored into a whole array"
    r.what = ("`%s` is an ARRAY of %s%s, not a single variable. `%s` is ONE value, and C does not let you "
              "assign anything to a whole array with `=`." % (name, kind, decl, rhs))
    r.fix = ["Store the value in one element: `%s[0] = %s;` (use the index you need%s)."
             % (name, rhs, (", 0 to %d" % (size - 1)) if size else ""),
             "If you only need one number, declare it as a plain variable instead: `%s %s;`" % (base or "int", name)]
    r.why = ["`%s %s[%s];` creates %s separate boxes; `=` can fill only one box at a time."
             % (base or "int", name, size or "N", size or "N")]
    r.example = {"wrong": "int a[10];\na = x + y;", "right": "int a[10];\na[0] = x + y;"}
    r.fixed_line = "%s%s[0] = %s;" % (indent, name, rhs)
    if line.rstrip().endswith(":"):
        r.hints.append("Also: this line ends with `:` - a statement must end with `;` (the corrected line fixes both).")
    return r


# --------------------------------------------------------------------- M008
@handler("redefinition")
def redefinition(ctx):
    name = ctx.groups.get("name", "")
    r = Result(vars={"name": name})
    n, _ = ctx.note(r"previous (?:definition|declaration)|previously declared|first defined")
    prev_line = n.location.line if n is not None and n.location else None
    if prev_line:
        r.vars["prev_line"] = prev_line
        r.what = ("`%s` is declared again on line %s, but it was already declared on line %d. In one scope each "
                  "name can only be created once." % (name, ctx.line_no, prev_line))
    line = ctx.line_text() or ""
    m = re.match(r"^(\s*)(?:const\s+|static\s+|unsigned\s+|signed\s+|long\s+|short\s+)*"
                 r"(?:int|char|float|double|long|short|bool|_Bool|unsigned|string|auto)\s*\**\s*(%s\b\s*=.*)$" % re.escape(name), line)
    if m:
        r.fixed_line = m.group(1) + m.group(2)
    return r


# --------------------------------------------------------------------- M009
@handler("conflicting_types")
def conflicting_types(ctx):
    name = ctx.groups.get("name", "")
    r = Result(vars={"name": name})
    src = ctx.src
    n, _ = ctx.note(r"implicit declaration")
    if n is not None:
        use_line = n.location.line if n.location else "?"
        r.title = "Function used before it is declared (conflicting types)"
        r.what = ("`%s` was called on line %s before C had seen any declaration, so C guessed it is "
                  "`int %s()`. The real definition on line %s has a different type, so the two do not match."
                  % (name, use_line, name, ctx.line_no))
        r.fix = ["Add a prototype of `%s` above main()." % name, "Or move the function definition above main()."]
        if src is not None:
            fdef, proto = src.symbols.function_named(name)
            hdr = _function_header_text(src, fdef) if fdef is not None else None
            if hdr:
                main = [s for s in src.symbols.symbols if s.kind == "func" and s.name == "main"]
                r.fixed_line = hdr + ";"
                r.fixed_line_no = main[0].line if main else 1
                r.fixed_kind = "insert_before"
        return r
    if src is not None and ctx.line_no:
        cur_line = ctx.line_text() or ""
        decls = [s for s in src.symbols.declarations(name) if s.kind == "var"]
        at_file_scope = ctx.tok is not None and src.symbols.scope_at(ctx.tok.index) == 0
        if decls and at_file_scope and re.match(r"^\s*\w+\s*(\[[^\]]*\])?\s*[-+*/%]?=", cur_line):
            r.title = "Statement written outside main()"
            r.what = ("Line %s (`%s`) is a statement, but it is outside every function. Outside a function C only "
                      "allows declarations, so it read `%s` as a NEW variable (of type int) - which clashes with "
                      "the `%s` declared on line %d." % (ctx.line_no, cur_line.strip(), name, name, decls[0].line))
            r.fix = ["Move this line inside `int main() { ... }`."]
            r.why = ["Code that does work (assignments, printf, loops) must be inside a function."]
            r.real_line = ctx.line_no
            r.no_fix = True
            return r
    n, _ = ctx.note(r"previous (?:declaration|definition)")
    if n is not None and n.location:
        info = (n.extra.get("snippet_info") or {}).get("src") or {}
        prev = (ctx.src.line(n.location.line) if ctx.src is not None else info.get(n.location.line, "")).strip()
        cur = (ctx.line_text() or "").strip().rstrip("{").strip()
        r.what = ("`%s` is declared in two different ways:\n  line %d: `%s`\n  line %s: `%s`\nThe return type and "
                  "parameter types must be exactly the same." % (name, n.location.line, prev, ctx.line_no, cur))
        if cur and prev:
            r.fixed_line = cur + ";"
            r.fixed_line_no = n.location.line
    return r


@handler("void_main")
def void_main(ctx):
    r = Result()
    line = ctx.line_text() or ""
    fixed = re.sub(r"\bvoid(\s+main\s*\()", r"int\1", line, count=1)
    if fixed != line:
        r.fixed_line = fixed
        r.hints.append("Also add `return 0;` as the last line of main.")
    return r


@handler("return_mismatch")
def return_mismatch(ctx):
    r = Result()
    func = ctx.groups.get("func")
    sym = _enclosing_function_sym(ctx, ctx.line_no or 0)
    if not func:
        func = sym.name if sym is not None else "this function"
    r.vars["func"] = func
    if sym is not None and ctx.src is not None and "with a value" in ctx.diag.message or "should not return" in ctx.diag.message:
        if sym is not None and ctx.src is not None:
            hdr_line = ctx.src.line(sym.line)
            fixed = re.sub(r"\bvoid\b", "int", hdr_line, count=1)
            if fixed != hdr_line:
                r.fixed_line = fixed
                r.fixed_line_no = sym.line
    return r


@handler("void_value")
def void_value(ctx):
    r = Result()
    src = ctx.src
    if src is None:
        return r
    for t in src.tokens_on_line(ctx.line_no or 0):
        if t.kind == "id" and src.next_token(t) is not None and src.next_token(t).is_op("("):
            fdef, proto = src.symbols.function_named(t.text)
            sym = fdef or proto
            if sym is not None and sym.type.strip() == "void":
                r.what = ("`%s()` is declared `void`, so it returns nothing - but line %s tries to use its result."
                          % (t.text, ctx.line_no))
                r.vars["func"] = t.text
                break
    return r


@handler("not_a_function")
def not_a_function(ctx):
    r = Result()
    src = ctx.src
    line = ctx.line_text() or ""
    m = re.search(r"(\b\d+(?:\.\d+)?)\s*\(", line)
    if m:
        r.title = "Missing * (maths-style multiplication)"
        r.what = ("`%s(...)` means multiplication in maths, but in C/C++ a number followed by `(` looks like a "
                  "function call. Write the `*`." % m.group(1))
        r.fixed_line = line[:m.end(1)] + " * " + line[m.end(1):].lstrip()
        return r
    m = re.search(r"\)\s*\(", line)
    if m:
        r.what = "`(...)(...)` - two bracket groups next to each other. If you meant multiplication, put `*` between them."
        r.fixed_line = line[:m.start() + 1] + " * " + line[m.end() - 1:]
        return r
    if src is not None and ctx.tok is not None:
        for t in src.tokens_on_line(ctx.line_no or 0):
            if t.kind == "id" and src.next_token(t) is not None and src.next_token(t).is_op("("):
                fdef, proto = src.symbols.function_named(t.text)
                local = src.symbols.lookup(t.text, t.index)
                if (fdef or proto) and local is not None and local.kind in ("var", "param"):
                    r.title = "A variable hides the function %s()" % t.text
                    r.what = ("The local variable `%s` (line %d) has the same name as the function `%s()`, so inside "
                              "this block `%s` means the variable." % (t.text, local.line, t.text, t.text))
                    r.fix = ["Rename the variable (e.g. `%sValue`)." % t.text]
                    return r
    return r


@handler("subscript")
def subscript(ctx):
    r = Result(vars={"name": "x"})
    src = ctx.src
    if src is None:
        return r
    for t in src.tokens_on_line(ctx.line_no or 0):
        nx = src.next_token(t)
        if t.kind == "id" and nx is not None and nx.is_op("["):
            r.vars["name"] = t.text
            sym = src.symbols.lookup(t.text, t.index)
            if sym is not None and not sym.is_array and not sym.pointer and sym.kind == "param":
                _param_should_be_array(r, src, sym)
            elif sym is not None and not sym.is_array and not sym.pointer:
                r.what = ("`%s` is declared on line %d as a single `%s`, not as an array, so `%s[...]` is not "
                          "allowed." % (t.text, sym.line, sym.type, t.text))
            elif sym is not None and sym.is_array:
                # count the [..] groups that follow the name:  m[1][1][0]
                used, k = 0, nx
                while k is not None and k.is_op("["):
                    close = src.brackets.match.get(k.index)
                    if close is None:
                        break
                    used += 1
                    k = src.tok(close + 1)
                dims = len(sym.array_sizes) + sym.pointer
                if used > dims:
                    r.title = "Too many indexes for this array"
                    r.what = ("`%s` is declared on line %d as `%s %s%s` - it has %d dimension%s, so it takes %d "
                              "index%s, but line %d uses %d (`[ ]` written %d times)." % (
                                  t.text, sym.line, sym.type, t.text,
                                  "".join("[%s]" % ("" if d is None else d) for d in sym.array_sizes),
                                  dims, "" if dims == 1 else "s", dims, "" if dims == 1 else "es",
                                  ctx.line_no, used, used))
                    r.fix = ["Use exactly %d index%s, e.g. `%s%s`." % (
                        dims, "" if dims == 1 else "es", t.text, "[0]" * dims)]
                    r.example = {"wrong": "int m[2][2];\nprintf(\"%d\", m[1][1][0]);",
                                 "right": "int m[2][2];\nprintf(\"%d\", m[1][1]);"}
            break
    return r


def _param_should_be_array(r, src, sym):
    """void print(int arr, int n)  used as  arr[i]  /  called as print(a, 3)."""
    r.title = "Array parameter declared as a single %s" % sym.type
    r.what = ("The parameter `%s` (line %d) is declared as ONE `%s`, but the function uses it as an array. To "
              "receive an array, the parameter needs `[ ]`: `%s %s[]`." % (sym.name, sym.line, sym.type, sym.type,
                                                                        sym.name))
    r.fix = ["Change the parameter to `%s %s[]` (or `%s *%s`)." % (sym.type, sym.name, sym.type, sym.name)]
    r.why = ["`[ ]` was forgotten in the function header - the call passes an array, so the parameter must be one."]
    decl = src.line(sym.line)
    m = re.search(r"\b%s\s+%s\b(?!\s*\[)" % (re.escape(sym.type), re.escape(sym.name)), decl)
    if m:
        r.fixed_line = decl[:m.end()] + "[]" + decl[m.end():]
        r.fixed_line_no = sym.line
    r.real_line = sym.line
    r.example = {"wrong": "void print(int arr, int n)", "right": "void print(int arr[], int n)"}


@handler("subscript_function")
def subscript_function(ctx):
    r = Result()
    src = ctx.src
    if src is None:
        return r
    for t in src.tokens_on_line(ctx.line_no or 0):
        nx = src.next_token(t)
        if t.kind == "id" and nx is not None and nx.is_op("["):
            for s in src.symbols.declarations(t.text):
                decl = src.line(s.line)
                m = re.search(r"\b(\w+)\s+%s\s*\(\s*(\w+)\s*\)" % re.escape(t.text), decl)
                if m and (m.group(2).isdigit() or m.group(2).isupper()):
                    r.title = "Array declared with ( ) instead of [ ]"
                    r.what = ("`%s` was declared on line %d as `%s %s(%s)` - with round brackets that declares a "
                              "FUNCTION, not an array. So `%s[...]` on line %d is not allowed." % (
                                  t.text, s.line, m.group(1), t.text, m.group(2), t.text, ctx.line_no))
                    r.fix = ["Change line %d to `%s %s[%s];`." % (s.line, m.group(1), t.text, m.group(2))]
                    r.fixed_line = decl[:m.start()] + "%s %s[%s]" % (m.group(1), t.text, m.group(2)) + decl[m.end():]
                    r.fixed_line_no = s.line
                    r.real_line = s.line
                    return r
            break
    return r


KEYWORD_NAMES = {"int", "float", "double", "char", "long", "short", "void", "unsigned", "signed", "bool", "_Bool"}


@handler("two_types")
def two_types(ctx):
    r = Result()
    src = ctx.src
    if src is None or not ctx.line_no:
        return r
    toks = src.tokens_on_line(ctx.line_no)
    line = src.line(ctx.line_no)
    modifiers = ("long", "short", "unsigned", "signed")
    for k, t in enumerate(toks[:-1]):
        nx = toks[k + 1]
        after = toks[k + 2] if k + 2 < len(toks) else None
        if t.text not in KEYWORD_NAMES or nx.text not in KEYWORD_NAMES:
            continue
        used_as_name = after is not None and after.is_op("=", ";", ",", "[", ")")
        if used_as_name or (t.text not in modifiers and nx.text not in modifiers):
            if used_as_name:
                new = "%s_value" % nx.text if nx.text != t.text else "value"
                r.title = "Keyword `%s` used as a variable name" % nx.text
                r.what = ("On line %d `%s` is used as the NAME of a variable. `%s` is a reserved keyword (a type), "
                          "so the compiler reads `%s %s` as two types and finds no name." % (
                              ctx.line_no, nx.text, nx.text, t.text, nx.text))
                r.fix = ["Choose a normal name, e.g. `%s %s`." % (t.text, new),
                         "Reserved words such as int, float, char, for, while, if, return can never be names."]
                r.fixed_line = line[:nx.col - 1] + new + line[nx.col - 1 + len(nx.text):]
            else:
                r.title = "Two types in one declaration"
                r.what = ("Line %d says `%s %s` - two types for one variable. A variable has exactly ONE type." % (
                    ctx.line_no, t.text, nx.text))
                r.fix = ["Keep only the type you need: `%s ...` or `%s ...`." % (t.text, nx.text)]
            return r
    return r


@handler("pointer_cast")
def pointer_cast(ctx):
    r = Result()
    src = ctx.src
    if src is None or not ctx.line_no:
        return r
    line = src.line(ctx.line_no)
    to = ctx.groups.get("to", "")
    for m in re.finditer(r"\(\s*(int|long|float|double|short|char|long long|unsigned)\s*\)\s*(\w+)\b(?!\s*\[)", line):
        name = m.group(2)
        sym = src.symbols.lookup(name, src.tokens_on_line(ctx.line_no)[0].index) if src.tokens_on_line(ctx.line_no) else None
        if sym is None or not (sym.is_array or sym.pointer):
            continue
        typ = m.group(1)
        if sym.type == "char":
            conv = "atof" if typ in ("float", "double") else "atoi"
            r.title = "Cast cannot turn text into a number"
            r.what = ("`%s` is a string (char array). `(%s)%s` does NOT read the digits in it - it converts the "
                      "ADDRESS of the string to a number, which is meaningless." % (name, typ, name))
            r.fix = ["Use `%s(%s)` to convert text to a number (add `#include <stdlib.h>`)." % (conv, name),
                     "To convert one character digit, use `%s[0] - '0'`." % name]
            r.fixed_line = line[:m.start()] + "%s(%s)" % (conv, name) + line[m.end():]
            r.example = {"wrong": "char s[] = \"123\";\nint x = (int)s;", "right": "char s[] = \"123\";\nint x = atoi(s);   /* 123 */"}
        else:
            r.title = "Whole array cast to a number"
            r.what = ("`%s` is an array, and an array name stands for its ADDRESS. `(%s)%s` converts that address, "
                      "not the values stored in the array." % (name, typ, name))
            r.fix = ["Use one element: `(%s)%s[0]` (or `%s[i]` inside a loop)." % (typ, name, name)]
            r.fixed_line = line[:m.start()] + "(%s)%s[0]" % (typ, name) + line[m.end():]
        return r
    return r


@handler("string_to_number")
def string_to_number(ctx):
    r = Result()
    src = ctx.src
    line = ctx.line_text() or ""
    m = re.search(r"=\s*\"\s*([-+]?\d+(?:\.\d*)?)\s*\"", line)
    if m:
        r.fixed_line = line[:m.start()] + "= " + m.group(1) + line[m.end():]
        r.what = ("On line %s the number is written inside double quotes, `\"%s\"`. Anything in `\" \"` is a "
                  "STRING (text), not a number - remove the quotes." % (ctx.line_no, m.group(1)))
    return r


@handler("invalid_operands")
def invalid_operands(ctx):
    r = Result()
    t1 = ctx.groups.get("t1", "")
    t2 = ctx.groups.get("t2", "")
    op = ctx.groups.get("op")
    src = ctx.src
    if ctx.cpp and re.search(r"[io]stream", t1):
        return Result(redirect="C001", vars={"t1": t1, "t2": t2})
    if not op and src is not None and ctx.tok is not None and ctx.tok.kind == "op":
        op = ctx.tok.text
    op = op or "?"
    r.vars["op"] = op
    line = ctx.line_text() or ""
    floats = ("double", "float", "long double")
    if op == "%" and (t1 in floats or t2 in floats):
        r.title = "% used with decimal numbers"
        r.what = ("`%` (remainder) only works with whole numbers (int, long). Here one side is a `" +
                  (t1 if t1 in floats else t2) + "`.")
        r.fix = ["Use `fmod(a, b)` from <math.h> for decimal numbers, or make both values integers."]
        m = re.search(r"([\w.\[\]]+)\s*%\s*([\w.\[\]]+)", line)
        if m:
            r.fixed_line = line[:m.start()] + "fmod(%s, %s)" % (m.group(1), m.group(2)) + line[m.end():]
        return r
    if ("struct" in t1 or "struct" in t2) or (t1 == t2 and not re.search(r"int|char|float|double|long|short|\*", t1)):
        if op in ("==", "!=", "<", ">", "<=", ">="):
            r.title = "Structures cannot be compared with %s" % op
            r.what = ("C cannot compare whole structures with `%s`. Compare their members one by one, e.g. "
                      "`a.x == b.x && a.y == b.y`." % op)
            return r
    if "[" in t1 and "[" in t2 and op in ("+", "-", "*", "/"):
        dims = t1.count("[")
        idx = "".join("[%s]" % v for v in "ijk"[:dims])
        loops = " ".join("for (%s...)" % v for v in "ijk"[:dims])
        r.title = "Whole arrays cannot be %s with %s" % (
            {"+": "added", "-": "subtracted", "*": "multiplied", "/": "divided"}[op], op)
        r.what = ("Both sides of `%s` on line %s are ARRAYS (`%s`). C has no maths on whole arrays or matrices: "
                  "each element must be calculated separately, inside %s." % (
                      op, ctx.line_no, t1, "a loop" if dims == 1 else "nested loops"))
        m = re.search(r"(\w+)\s*=\s*(\w+)\s*([-+*/])\s*(\w+)", line)
        if m:
            c, a, o, b = m.groups()
            r.fix = ["Use %s: `%s %s%s = %s%s %s %s%s;`" % (
                "a loop" if dims == 1 else "nested loops", loops, c, idx, a, idx, o, b, idx)]
            if op == "*" and dims == 2:
                r.hints.append("For MATRIX multiplication `*` per element is not enough - each c[i][j] is the sum of "
                               "a[i][k] * b[k][j] over k (three nested loops).")
        r.why = ["Expecting C to work on whole arrays like maths notation or Python's numpy."]
        r.example = {"wrong": "c = a + b;",
                     "right": "for (i = 0; i < 2; i++)\n    for (j = 0; j < 2; j++)\n        c[i][j] = a[i][j] + b[i][j];"}
        return r
    if op == "+" and "*" in t1 and "*" in t2:
        r.title = "Two pointers/strings added with +"
        r.what = ("In C, `+` cannot join two strings (char pointers). Use `strcat(dest, src)` (dest must be big "
                  "enough), or build the result with `sprintf`.")
        return r
    return r


@handler("member_access")
def member_access(ctx):
    r = Result()
    src = ctx.src
    line = ctx.line_text() or ""
    want_arrow = "->'" in ctx.diag.message and "did you mean to use '->'" in ctx.diag.message or "is a pointer" in ctx.diag.message
    r.vars.setdefault("type", ctx.groups.get("type", "structure"))
    if src is None or ctx.tok is None:
        r.vars.setdefault("name", ctx.groups.get("name", "the variable"))
        return r
    idx = ctx.col_index() or 0
    target = None
    for t in src.tokens_on_line(ctx.line_no):
        if t.is_op(".", "->") and (target is None or abs(t.col - 1 - idx) < abs(target.col - 1 - idx)):
            target = t
    if target is None:
        r.vars.setdefault("name", ctx.groups.get("name", "the variable"))
        return r
    owner = src.prev_token(target)
    r.vars.setdefault("name", owner.text if owner is not None else "the variable")
    if want_arrow and target.text == "." and owner is not None:
        # fix EVERY `ptr.member` on this line, not only the one the compiler pointed at
        dots = [t for t in src.tokens_on_line(ctx.line_no) if t.is_op(".")
                and src.prev_token(t) is not None and src.prev_token(t).text == owner.text]
        fixed = line
        for t in sorted(dots, key=lambda t: -t.col):
            fixed = fixed[:t.col - 1] + "->" + fixed[t.col:]
        r.fixed_line = fixed
        if len(dots) > 1:
            r.hints.append("`%s` is used with `.` %d times on this line - all of them need `->`." % (owner.text, len(dots)))
    elif not want_arrow and target.text == "->":
        r.fixed_line = line[:target.col - 1] + "." + line[target.col + 1:]
    return r


def _struct_name_from_type(t):
    t = re.sub(r"\{aka.*", "", t or "").strip()
    t = t.replace("const ", "").replace("*", "").strip()
    m = re.match(r"(?:struct|union|class)\s+(\w+)", t)
    if m:
        return m.group(1)
    return t.split("::")[-1].strip()


@handler("no_member")
def no_member(ctx):
    member = ctx.groups.get("member", "")
    typ = ctx.groups.get("type", "this structure")
    suggest = ctx.groups.get("suggest")
    r = Result(vars={"member": member, "type": typ, "members": "(see the struct definition)"})
    src = ctx.src
    names = []
    if "basic_string" in typ or "std::string" in typ or typ == "string":
        names = STRING_METHODS
        r.vars["type"] = "std::string"
    elif "vector" in typ:
        names = VECTOR_METHODS
        r.vars["type"] = "std::vector"
    elif src is not None:
        st = src.symbols.struct_named(_struct_name_from_type(typ))
        if st is not None:
            names = [m.name for m in st.members]
            r.vars["members"] = ", ".join(code(n) for n in names) or "(none)"
            r.hints.append("`%s` is defined on line %d." % (typ, st.line))
    if "something not a structure" in ctx.diag.message or "non-class type" in ctx.diag.message:
        r.title = "Using . on a variable that is not a structure"
        r.what = "`.%s` is used on a variable that is not a struct/class (it is a plain value), so it has no members." % member
        return r
    sug = suggest or (closest(member, names, max_results=1) or [None])[0]
    if sug:
        r.title = "No member `%s` - did you mean `%s`?" % (member, sug)
        r.what = "`%s` has no member called `%s`, but it has `%s` - probably a typing mistake." % (r.vars["type"], member, sug)
        line = ctx.line_text() or ""
        idx = ctx.col_index()
        fixed = replace_word(line, member, sug, near=idx)
        if fixed:
            r.fixed_line = fixed
        r.fix = ["Write `%s`." % sug]
    return r


@handler("incomplete_type")
def incomplete_type(ctx):
    r = Result()
    src = ctx.src
    typ = ctx.groups.get("type")
    var = ctx.groups.get("name")
    if not typ and var and src is not None:
        for s in src.symbols.declarations(var):
            if s.type:
                typ = s.type
                break
    if not typ:
        m = re.search(r"\b(struct|union)\s+(\w+)", ctx.line_text() or "")
        typ = m.group(0) if m else None
    if not typ or src is None:
        return r
    sname = _struct_name_from_type(typ)
    defined = [s for s in src.symbols.symbols if s.kind in ("struct", "union", "class") and s.name != "<anonymous>"]
    names = [s.name for s in defined]
    if sname in names:
        st = [s for s in defined if s.name == sname][0]
        if st.line > (ctx.line_no or 0):
            r.what = "`%s` is defined on line %d, below its first use on line %s. Move the definition above." % (
                typ, st.line, ctx.line_no)
            return r
    sug = closest(sname, names, max_results=1)
    if sug:
        r.title = "Misspelled struct name - did you mean %s?" % sug[0]
        r.what = "There is no `%s`. The structure you defined is called `%s`." % (typ, sug[0])
        fixed = replace_word(ctx.line_text() or "", sname, sug[0])
        if fixed:
            r.fixed_line = fixed
        return r
    r.what = "`%s` is never defined in this program. Define it before use: `struct %s { ... };`." % (typ, sname)
    return r


@handler("switch_type")
def switch_type(ctx):
    r = Result()
    src = ctx.src
    if src is None:
        return r
    m = re.search(r"switch\s*\(\s*(\w+)\s*\)", ctx.line_text() or "")
    if m:
        sym = src.symbols.lookup(m.group(1), ctx.tok.index if ctx.tok is not None else 10 ** 6)
        if sym is not None:
            if "char" in sym.type and (sym.pointer or sym.is_array):
                r.what = ("`%s` is a string (declared on line %d). `switch` cannot compare strings - use "
                          "`if (strcmp(%s, \"...\") == 0) ... else if (...)`." % (sym.name, sym.line, sym.name))
            elif sym.type in ("float", "double"):
                r.what = "`%s` is a `%s`. switch only works with whole numbers - use if / else-if instead." % (sym.name, sym.type)
    return r


@handler("break_outside")
def break_outside(ctx):
    kw = ctx.groups.get("kw", "break")
    r = Result(vars={"kw": kw, "switch_text": " or switch" if kw == "break" else ""})
    src = ctx.src
    if src is None or ctx.tok is None:
        return r
    for t in src.tokens:
        if t.index >= ctx.tok.index:
            break
        if t.kind == "kw" and t.text in ("for", "while"):
            op = src.next_token(t)
            close = src.brackets.match.get(op.index) if op is not None and op.is_op("(") else None
            after = src.tok(close + 1) if close is not None else None
            if after is not None and after.is_op(";"):
                prev = src.prev_token(t)
                if prev is not None and prev.is_op("}"):
                    continue          # do { } while (...);
                r.title = "Semicolon ended the loop early"
                r.what = ("The `;` right after `%s (...)` on line %d ends the loop there, so the block below it - "
                          "including this `%s` - is not inside any loop." % (t.text, after.line, kw))
                r.real_line = after.line
                line = src.line(after.line)
                r.fixed_line = line[:after.col - 1].rstrip() + line[after.col:]
                r.fixed_line_no = after.line
                return r
    return r


@handler("int_conversion")
def int_conversion(ctx):
    r = Result()
    msg = ctx.diag.message
    src = ctx.src
    line = ctx.line_text() or ""
    kind = ctx.groups.get("kind", "")
    m = re.search(r"passing argument (\d+) of '([^']+)'", msg)
    func, argn = (m.group(2), int(m.group(1))) if m else (None, None)
    if func is None:
        m2 = re.search(r"passing '([^']+)' to parameter of type '([^']+)'", msg)
        if m2 and src is not None and ctx.tok is not None:
            name_tok, args = _find_call_at(ctx)
            if name_tok is not None and args:
                func = name_tok.text
                idx = ctx.col_index() or 0
                for i, a in enumerate(args):
                    if a and a[0].col - 1 <= idx <= a[-1].col + len(a[-1].text):
                        argn = i + 1
    if func and argn and src is not None:
        r.vars["func"] = func
        call = None
        for t in src.tokens_on_line(ctx.line_no or 0):
            if t.kind == "id" and t.text == func and src.next_token(t) is not None and src.next_token(t).is_op("("):
                call = t
        args = call_args(src, call) if call is not None else None
        if args and argn <= len(args):
            arg = args[argn - 1]
            atext = text_of(arg)
            if ("integer from pointer" in kind or "pointer to integer" in kind) and len(arg) == 1 \
                    and arg[0].kind == "id":
                asym = src.symbols.lookup(arg[0].text, arg[0].index)
                fdef = src.symbols.function_named(func)[0]
                params = fdef.params if fdef is not None else []
                if asym is not None and asym.is_array and argn <= len(params) and not params[argn - 1].is_array \
                        and not params[argn - 1].pointer:
                    _param_should_be_array(r, src, params[argn - 1])
                    r.what = ("`%s` is an array, but parameter %d of `%s` (`%s`, line %d) is declared as ONE `%s`. "
                              "To receive an array, the parameter needs `[ ]`: `%s %s[]`." % (
                                  arg[0].text, argn, func, params[argn - 1].name, params[argn - 1].line,
                                  params[argn - 1].type, params[argn - 1].type, params[argn - 1].name))
                    return r
            if "pointer from integer" in kind or "integer to pointer" in kind:
                if len(arg) == 4 and arg[0].kind == "id" and arg[1].is_op("[") and arg[3].is_op("]"):
                    sym = src.symbols.lookup(arg[0].text, arg[0].index)
                    if sym is not None and sym.type != "char":
                        r.title = "One element passed where the whole array is needed"
                        r.what = ("`%s` is ONE element (a single `%s`), but `%s` needs the whole array. To pass an "
                                  "array to a function, write only its name: `%s`." % (
                                      atext, sym.type, func, arg[0].text))
                        if arg[2].text.isdigit() and sym.array_sizes and sym.array_sizes[0] is not None \
                                and int(arg[2].text) >= sym.array_sizes[0]:
                            r.hints.append("Also, `%s` is outside the array: `%s` has %d elements, numbered 0 to %d."
                                           % (atext, arg[0].text, sym.array_sizes[0], sym.array_sizes[0] - 1))
                        r.fix = ["Pass only the array name: `%s(%s, ...)`." % (func, arg[0].text)]
                        r.why = ["Writing `a[5]` to mean \"the array a with 5 elements\" - but `a[5]` means "
                                 "\"element number 5 of a\"."]
                        r.fixed_line = line[:arg[0].col - 1] + arg[0].text + line[arg[3].col:]
                        return r
                    r.title = "Single character passed where a string is needed"
                    r.what = ("`%s` is ONE character, but `%s` needs the whole string (its address). Pass `%s` "
                              "instead." % (atext, func, arg[0].text))
                    r.fixed_line = line[:arg[0].col - 1] + arg[0].text + line[arg[3].col:]
                    return r
                if len(arg) == 1 and arg[0].kind == "id":
                    r.title = "Address (&) missing in the call to %s()" % func
                    r.what = ("Parameter %d of `%s` is a pointer, so it needs the ADDRESS of a variable. You passed "
                              "the value of `%s`; pass `&%s` instead." % (argn, func, atext, atext))
                    r.fixed_line = line[:arg[0].col - 1] + "&" + line[arg[0].col - 1:]
                    return r
                if len(arg) == 1 and arg[0].kind == "char":
                    r.title = "Single quotes used for text"
                    r.what = "`%s` is a single character (an integer). `%s` needs a string in double quotes." % (atext, func)
                    body = arg[0].text[1:-1]
                    r.fixed_line = line[:arg[0].col - 1] + '"' + body + '"' + line[arg[0].col - 1 + len(arg[0].text):]
                    return r
    m = re.search(r"'\s*=\s*\"(.)\"", line) or re.search(r"=\s*\"(.)\"\s*;", line)
    if ("integer from pointer" in kind or "pointer to integer" in kind) and m:
        r.title = "Double quotes used for a single character"
        r.what = ("`\"%s\"` in double quotes is a STRING (an address). A `char` holds a single character, written "
                  "with single quotes: `'%s'`." % (m.group(1), m.group(1)))
        r.fixed_line = line.replace('"%s"' % m.group(1), "'%s'" % m.group(1), 1)
        return r
    if ("pointer from integer" in kind or "integer to pointer" in kind) and re.search(r"\*\s*\w+\s*=\s*-?\d+\s*;", line):
        r.title = "Number stored in a pointer"
        r.what = ("A pointer must hold an ADDRESS (like `&x`), not a plain number. Did you mean `int *p = &x;` "
                  "(point to a variable) or `int p = 5;` (a normal variable)?")
        return r
    return r


@handler("excess_init")
def excess_init(ctx):
    r = Result()
    line = ctx.line_text() or ""
    m = re.search(r"\b(\w+)\s*\[\s*(\d+)\s*\]\s*=\s*\"((?:[^\"\\]|\\.)*)\"", line)
    if m:
        need = len(re.sub(r"\\.", "x", m.group(3))) + 1
        r.what = ("The text \"%s\" needs %d places (%d letters + the hidden `\\0` that ends every string), but the "
                  "array has only %s." % (m.group(3), need, need - 1, m.group(2)))
        r.fixed_line = line[:m.start(2)] + str(need) + line[m.end(2):]
        return r
    m = re.search(r"\b(\w+)\s*\[\s*(\d+)\s*\]\s*=\s*\{([^}]*)\}", line)
    if m:
        count = len([x for x in m.group(3).split(",") if x.strip()])
        r.what = "The array `%s` has room for %s values, but %d values are given." % (m.group(1), m.group(2), count)
        r.fixed_line = line[:m.start(2)] + line[m.end(2):]
        r.fix = ["Leave the size empty and let the compiler count: `%s[] = {...}`, or make it `[%d]`." % (m.group(1), count)]
    return r


# ===================================================================== C++
@handler("stream_operator")
def stream_operator(ctx):
    t1 = ctx.groups.get("t1", "")
    t2 = ctx.groups.get("t2", "")
    op = ctx.groups.get("op")
    src = ctx.src
    if not op and src is not None and ctx.tok is not None and ctx.tok.kind == "op":
        op = ctx.tok.text
    is_in = "istream" in t1
    is_out = "ostream" in t1
    if not (is_in or is_out):
        return veto()
    r = Result(vars={"op": op or "<<"})
    line = ctx.line_text() or ""
    if is_in and op == "<<":
        r.title = "cin used with << (should be >>)"
        r.fixed_line = re.sub(r"(\bcin\b.*)", lambda m: m.group(1).replace("<<", ">>"), line, count=1)
        return r
    if is_out and op == ">>":
        r.title = "cout used with >> (should be <<)"
        r.fixed_line = re.sub(r"(\bcout\b.*)", lambda m: m.group(1).replace(">>", "<<"), line, count=1)
        return r
    clean = re.sub(r"\s*\{aka.*", "", t2)
    r.title = "%s cannot %s a %s directly" % ("cout" if is_out else "cin", "print" if is_out else "read", clean)
    r.what = ("`%s` knows how to %s numbers, characters and strings, but not a whole `%s`." % (
        "cout <<" if is_out else "cin >>", "print" if is_out else "read", clean))
    if "vector" in t2:
        r.fix = ["Use a loop: `for (int x : v) cout << x << \" \";`"]
    else:
        r.fix = ["Print/read the members one by one, or write an `operator%s` overload for this type." % (op or "<<")]
    r.why = ["Containers and structs have no built-in printing in C++."]
    return r


@handler("no_matching_function")
def no_matching_function(ctx):
    call = ctx.groups.get("call", "")
    name = call.split("(")[0].split("::")[-1].strip()
    r = Result(vars={"call": call})
    reasons = []
    for n in ctx.diag.notes:
        m = re.search(r"no known conversion (?:for argument (\d+) )?from '([^']+)' to '([^']+)'(?: for (\d+)\w* argument)?", n.message)
        if m:
            argn = m.group(1) or m.group(4) or "?"
            reasons.append("argument %s is a `%s` but the function needs a `%s`" % (argn, m.group(2), m.group(3)))
        m = re.search(r"candidate expects (\d+) arguments?, (\d+) provided", n.message)
        if m:
            reasons.append("it expects %s argument(s) but %s were given" % (m.group(1), m.group(2)))
    if reasons:
        r.hints.append("Why it does not match: " + "; ".join(sorted(set(reasons))[:3]) + ".")
    line = ctx.line_text() or ""
    m = re.search(r"\b%s\s*\(\s*\"(\d+(?:\.\d+)?)\"\s*\)" % re.escape(name), line) if name else None
    if m:
        r.title = "Number written as a string"
        r.what = "`\"%s\"` in double quotes is TEXT, not a number. `%s` needs a number." % (m.group(1), name)
        r.fixed_line = line[:m.start()] + "%s(%s)" % (name, m.group(1)) + line[m.end():]
    return r


@handler("cpp_conversion")
def cpp_conversion(ctx):
    frm = ctx.groups.get("from", "")
    to = ctx.groups.get("to", "")
    r = Result(vars={"from": frm or "value", "to": to or "another type"})
    line = ctx.line_text() or ""
    if "(" in frm and ")" in frm and "()" in frm.replace(" ", ""):
        return Result(redirect="C008")
    if "comparison" in ctx.diag.message:
        return Result(redirect="W010")
    if ("const char" in frm or frm.startswith("char[")) and to in ("char", "int", "double", "float", "long"):
        m = re.search(r"\"(-?\d+(?:\.\d+)?)\"", line)
        if m and to != "char":
            r.title = "Number written as a string"
            r.what = "`\"%s\"` in double quotes is TEXT, not a number. A `%s` is needed here, so write `%s` without quotes." % (
                m.group(1), to, m.group(1))
            r.fixed_line = line.replace('"%s"' % m.group(1), m.group(1), 1)
            return r
        m = re.search(r"\"(.)\"", line)
        if m:
            r.title = "Double quotes used for a single character"
            r.what = "`\"%s\"` is a string. A single `char` is written with single quotes: `'%s'`." % (m.group(1), m.group(1))
            r.fixed_line = line.replace('"%s"' % m.group(1), "'%s'" % m.group(1), 1)
        return r
    if to.rstrip().endswith("*") and frm in ("int", "char", "float", "double"):
        m = re.search(r"(\*\s*\w+\s*=\s*)(\w+)\s*;", line)
        if m and not m.group(2).isdigit():
            r.title = "Address (&) missing"
            r.what = "A pointer (`%s`) must store an ADDRESS. Use `&%s` to get the address of `%s`." % (to, m.group(2), m.group(2))
            r.fixed_line = line[:m.start(2)] + "&" + line[m.start(2):]
            return r
    if "string" in to and frm in ("int", "double", "float", "long", "char"):
        r.title = "Number assigned to a string"
        r.what = "A `std::string` cannot be created from a plain number. Use `to_string(...)` to convert it, or put the text in quotes."
        m = re.search(r"=\s*(-?\d+(?:\.\d+)?)\s*;", line)
        if m:
            fn = "std::to_string" if "std::" in line else "to_string"
            r.fixed_line = line[:m.start(1)] + "%s(%s)" % (fn, m.group(1)) + line[m.end(1):]
    return r


@handler("private_access")
def private_access(ctx):
    r = Result()
    decl = ctx.groups.get("decl")
    member = ctx.groups.get("member")
    cls = ctx.groups.get("cls")
    access = ctx.groups.get("access", "private")
    if decl and not member:
        m = re.search(r"(\w+)::(\w+)(?:\(|$)", decl)
        if m:
            cls, member = m.group(1), m.group(2)
    r.vars.update({"member": member or "this member", "cls": cls or "the class", "access": access})
    src = ctx.src
    if src is not None and cls:
        st = src.symbols.struct_named(cls)
        if st is not None:
            text = src.line(st.line)
            if "class" in text and not any("public" in src.line(n) for n in range(st.line, st.line + 30) if n <= len(src.lines)):
                r.hints.append("Class `%s` (line %d) has no `public:` section at all, so everything inside it is private." % (cls, st.line))
    return r


@handler("ambiguous")
def ambiguous(ctx):
    name = ctx.groups.get("name", "")
    r = Result(vars={"name": name})
    src = ctx.src
    if src is not None:
        mine = [s for s in src.symbols.declarations(name) if s.kind in ("var", "func")]
        if mine:
            r.hints.append("You declared `%s` yourself on line %d; the C++ library also has `std::%s`." % (name, mine[0].line, name))
    return r


@handler("write_strings")
def write_strings(ctx):
    r = Result()
    line = ctx.line_text() or ""
    fixed = re.sub(r"(?<!const )\bchar\s*\*", "const char *", line, count=1)
    if fixed != line:
        r.fixed_line = fixed
    return r


@handler("missing_call_parens")
def missing_call_parens(ctx):
    r = Result(vars={"member": "the member function"})
    src = ctx.src
    if src is None or ctx.tok is None:
        return r
    tok = ctx.tok
    if tok.is_op(".", "->"):
        tok = src.next_token(tok)
    if tok is not None and tok.kind == "id":
        r.vars["member"] = tok.text
        line = src.line(tok.line)
        r.fixed_line = line[:tok.col - 1 + len(tok.text)] + "()" + line[tok.col - 1 + len(tok.text):]
    return r
