"""Handlers for linker errors."""
import re

from ..textutil import closest
from .base import Result, code, handler, replace_word

MATH_FUNCS = {"sqrt", "pow", "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "exp", "log", "log10",
              "log2", "floor", "ceil", "fabs", "fmod", "round", "hypot", "cbrt", "trunc", "sinh", "cosh",
              "tanh", "fmin", "fmax", "lround", "rint", "exp2", "sqrtf", "powf", "floorf", "ceilf", "roundf"}
MAIN_NAMES = {"main", "WinMain", "WinMain@16", "wWinMain", "_main", "wmain"}


@handler("undefined_reference")
def undefined_reference(ctx):
    sym = ctx.groups.get("symbol", "")
    base = sym.split("(")[0].strip()
    short = base.split("::")[-1]
    r = Result(vars={"symbol": sym})
    src = ctx.src
    funcs = [s for s in src.symbols.symbols if s.kind in ("func", "method")] if src is not None else []
    if short in MAIN_NAMES:
        r.title = "No main() function"
        r.what = ("Every C/C++ program needs exactly one function called `main` - that is where the program "
                  "starts. The linker could not find it.")
        names = [f.name for f in funcs]
        close = closest("main", names, max_results=1)
        if close:
            f = [x for x in funcs if x.name == close[0]][0]
            r.what += " Your program has `%s()` on line %d, which looks like a misspelling of `main`." % (f.name, f.line)
            r.fix = ["Rename `%s` to `main` (all lowercase)." % f.name]
            fixed = replace_word(src.line(f.line), f.name, "main")
            if fixed:
                r.fixed_line = fixed
                r.fixed_line_no = f.line
                r.real_line = f.line
        else:
            r.fix = ["Add `int main() { ... return 0; }` to your program."]
        if "WinMain" in short:
            r.hints.append("On Windows (MinGW) this error mentions WinMain, but it means the same: main() is missing or "
                           "misspelled. It also happens when the file was not saved before building, or when a "
                           "'GUI application' project was created instead of a 'Console application'.")
        return r
    implicit = ctx.other_diags(r"implicit declaration of function '%s'" % re.escape(short))
    if implicit:
        d, _ = implicit[0]
        cands = ctx.known_functions()
        sug = closest(short, cands, max_results=1)
        r.title = "Follow-on error: %s() does not exist" % short
        r.what = ("This is a consequence of the warning on line %s: `%s()` was never declared, and it does not "
                  "exist anywhere, so the linker cannot find it." % (d.location.line if d.location else "?", short))
        if sug:
            r.what += " Did you mean `%s()`?" % sug[0]
            r.fix = ["Fix the spelling to `%s` (line %s)." % (sug[0], d.location.line if d.location else "?")]
        if short in MATH_FUNCS:
            r.fix = ["Add `#include <math.h>` - and on Linux compile with `-lm`."]
        r.real_line = d.location.line if d.location else None
        return r
    if short in MATH_FUNCS and not ctx.cpp:
        r.title = "Maths library not linked (-lm)"
        r.what = ("`%s` lives in the C maths library (libm). On Linux, GCC does not link that library automatically, "
                  "so the linker cannot find `%s`." % (short, short))
        r.fix = ["Add `-lm` at the END of the compile command: `gcc prog.c -o prog -lm`.",
                 "In CEDT: `python cedt.py prog.c -- -lm`."]
        r.why = ["The maths functions are in a separate library file that must be named when linking."]
        return r
    if src is not None:
        defs = [s for s in src.symbols.symbols if s.kind in ("func", "method") and s.defined]
        protos = [s for s in src.symbols.symbols if s.kind in ("proto", "method") and not s.defined and
                  s.name.split("::")[-1] == short]
        owner = base.split("::")[0] if "::" in base else None
        if protos:
            p = protos[0]
            close = closest(short, [d.name.split("::")[-1] for d in defs], max_results=1)
            if owner or p.kind == "method":
                cls = owner or p.owner
                r.title = "Method %s::%s() declared but never defined" % (cls, short)
                r.what = ("The class `%s` declares the member function `%s()` (line %d), but its body is never "
                          "written." % (cls, short, p.line))
                r.fix = ["Write the body, either inside the class or outside it: `%s %s::%s(...) { ... }`." % (
                    p.type or "void", cls, short)]
                r.real_line = p.line
                return r
            if close:
                d = [x for x in defs if x.name.split("::")[-1] == close[0]][0]
                r.title = "Prototype and definition have different names"
                r.what = ("You declared `%s()` (line %d), but the function you actually wrote is called `%s()` "
                          "(line %d). The names must match exactly." % (short, p.line, d.name, d.line))
                r.fix = ["Rename `%s` to `%s` (or the other way round)." % (d.name, short)]
                fixed = replace_word(src.line(d.line), d.name, short)
                if fixed:
                    r.fixed_line = fixed
                    r.fixed_line_no = d.line
                r.real_line = d.line
                return r
            r.title = "Function declared but never defined"
            r.what = ("You declared `%s()` on line %d (a prototype), but never wrote its body. A prototype only "
                      "PROMISES the function exists - the linker still needs the real code." % (short, p.line))
            r.fix = ["Write the function body: `%s {\n    ...\n}`" % src.line(p.line).strip().rstrip(";")]
            r.real_line = p.line
            return r
        if not any(d.name.split("::")[-1] == short for d in defs):
            r.hints.append("If `%s` is written in another .c/.cpp file, compile all files together, e.g. "
                           "`gcc main.c other.c -o prog`." % short)
    return r


@handler("multiple_definition")
def multiple_definition(ctx):
    sym = ctx.groups.get("symbol", "")
    r = Result(vars={"symbol": sym})
    if sym in MAIN_NAMES:
        r.title = "Two main() functions"
        r.what = ("Two of the files being linked both contain `main()`. A program can only have one starting point.")
        r.fix = ["Keep one main() per program. In Code::Blocks / VS Code, remove the other program file from the "
                 "project or build files separately."]
    return r
