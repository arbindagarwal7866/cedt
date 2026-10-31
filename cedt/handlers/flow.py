"""Handlers for flow-analysis warnings (likely bugs in code that compiles)."""
import re

from ..textutil import closest
from .base import Result, call_args, code, find_call, handler, insert_at, replace_word, text_of, veto

PRINTF_FAMILY = {"printf", "fprintf", "sprintf", "snprintf", "dprintf", "vprintf"}
SCANF_FAMILY = {"scanf", "fscanf", "sscanf"}
FMT_INDEX = {"printf": 0, "scanf": 0, "fprintf": 1, "fscanf": 1, "sprintf": 1, "sscanf": 1, "snprintf": 2,
             "dprintf": 1, "vprintf": 0}
SPEC_RE = re.compile(r"%(?:%|[-+ #0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|L|z|j|t|q)?([diouxXfFeEgGaAcspn]|\[[^\]]*\]))")

PRINTF_SPEC = [
    (r"^(?:const )?char ?\*$|^char ?\[\d*\]$|^(?:const )?char\s*\*\s*restrict$", "%s"),
    (r"^(?:signed )?char$", "%c"),
    (r"^(?:unsigned char)$", "%c"),
    (r"^(?:short|short int)$", "%hd"),
    (r"^(?:int|signed int|signed)$", "%d"),
    (r"^(?:unsigned|unsigned int)$", "%u"),
    (r"^(?:long|long int)$", "%ld"),
    (r"^(?:unsigned long|long unsigned int|unsigned long int)$", "%lu"),
    (r"^(?:long long|long long int)$", "%lld"),
    (r"^(?:unsigned long long|long long unsigned int)$", "%llu"),
    (r"^size_t$", "%zu"),
    (r"^(?:float|double)$", "%f"),
    (r"^long double$", "%Lf"),
    (r"\*$", "%p"),
]
SCANF_SPEC = [
    (r"^char ?\*$|^char ?\(\*\)\[\d+\]$", "%s"),
    (r"^int ?\*$", "%d"),
    (r"^unsigned(?: int)? ?\*$", "%u"),
    (r"^(?:long|long int) ?\*$", "%ld"),
    (r"^(?:long long|long long int) ?\*$", "%lld"),
    (r"^short(?: int)? ?\*$", "%hd"),
    (r"^float ?\*$", "%f"),
    (r"^double ?\*$", "%lf"),
    (r"^long double ?\*$", "%Lf"),
]


def _clean_type(t):
    t = re.sub(r"\s*\{aka.*", "", t or "").strip()
    t = re.sub(r"(?<=[\w\]])\s*\*", " *", t)
    return re.sub(r"\s+", " ", t).strip()


def correct_spec(actual, scanf):
    a = _clean_type(actual)
    a2 = a.replace(" *", "*")
    table = SCANF_SPEC if scanf else PRINTF_SPEC
    for rx, spec in table:
        if re.search(rx, a) or re.search(rx, a2):
            return spec
    return None


def _format_call(ctx):
    src = ctx.src
    if src is None or not ctx.line_no:
        return None, None, None
    call = find_call(src, ctx.line_no, PRINTF_FAMILY | SCANF_FAMILY, near_col=ctx.col)
    if call is None:
        return None, None, None
    args = call_args(src, call) or []
    fi = FMT_INDEX.get(call.text, 0)
    fmt = args[fi][0] if len(args) > fi and args[fi] and args[fi][0].kind == "str" else None
    return call, args, fmt


def _arg_at_col(src, args, line_no, idx):
    for i, a in enumerate(args):
        if not a:
            continue
        start = a[0]
        end = a[-1]
        if start.line <= line_no <= end.end_line and start.col - 1 <= idx <= end.col - 1 + len(end.text):
            return i
    return None


COMMA_INDEX_RE = re.compile(r"\b([A-Za-z_]\w*)\[\s*([^\[\],]+?)\s*,\s*([^\[\],]+?)\s*\]")


def comma_index(r, line):
    """m[0,1] (Pascal / maths style) instead of m[0][1]."""
    m = COMMA_INDEX_RE.search(line)
    if not m:
        return False
    name, i, j = m.groups()
    r.title = "Comma inside [ ] - a 2D element is written %s[%s][%s]" % (name, i, j)
    r.what = ("`%s[%s,%s]` does not pick row %s, column %s. In C each index needs its OWN brackets. Inside one "
              "`[ ]` the comma throws away `%s`, so this means `%s[%s]` - a whole ROW, not one number." % (
                  name, i, j, i, j, i, name, j))
    r.fix = ["Write `%s[%s][%s]`." % (name, i, j)]
    r.why = ["Maths / Pascal / Python-numpy style `m[i,j]` - C writes `m[i][j]`."]
    r.fixed_line = line[:m.start()] + "%s[%s][%s]" % (name, i, j) + line[m.end():]
    r.example = {"wrong": "printf(\"%d\", m[0,1]);", "right": "printf(\"%d\", m[0][1]);"}
    return True


@handler("format_mismatch")
def format_mismatch(ctx):
    expected = ctx.groups.get("expected", "")
    actual = ctx.groups.get("actual", "")
    spec = ctx.groups.get("spec")
    argn = ctx.groups.get("argn")
    r = Result(vars={"expected": _clean_type(expected), "actual": _clean_type(actual), "spec": spec or "%?",
                     "func": "printf/scanf"})
    src = ctx.src
    call, args, fmt = _format_call(ctx)
    if call is None:
        r.vars["func"] = "scanf" if expected.strip().endswith("*") and "char" not in expected else "printf"
        return r
    func = call.text
    is_scanf = func in SCANF_FAMILY
    r.vars["func"] = func
    fi = FMT_INDEX.get(func, 0)
    # which argument?
    if argn is not None:
        ai = int(argn) - 1
    else:
        ai = _arg_at_col(src, args, ctx.line_no, ctx.col_index() or 0)
    if ai is None or ai >= len(args):
        return r
    arg = args[ai]
    atext = text_of(arg)
    specs = list(SPEC_RE.finditer(fmt.text)) if fmt is not None else []
    specs = [s for s in specs if s.group(0) != "%%"]
    k = ai - fi - 1
    spec_m = specs[k] if 0 <= k < len(specs) else None
    if spec is None and spec_m is not None:
        spec = spec_m.group(0)
        r.vars["spec"] = spec
    line = src.line(fmt.line) if fmt is not None else (ctx.line_text() or "")
    exp_c, act_c = _clean_type(expected), _clean_type(actual)

    def replace_spec(new):
        if spec_m is None or fmt is None or fmt.line != arg[0].line and fmt.line != ctx.line_no:
            return None
        start = fmt.col - 1 + spec_m.start()
        end = fmt.col - 1 + spec_m.end()
        return line[:start] + new + line[end:]

    plain_var = len(arg) == 1 and arg[0].kind == "id"
    if is_scanf and exp_c.endswith("*") and (act_c == exp_c[:-1].strip()
                                             or (plain_var and not act_c.endswith("*") and "[" not in act_c)):
        # (a float passed to scanf arrives as a double, so the types need not match exactly)
        r.title = "Missing & in scanf"
        r.what = ("scanf needs the ADDRESS of `%s` to store the input in it. Without `&`, scanf receives the "
                  "current (garbage) value of `%s` and writes to a random memory location - the program usually "
                  "crashes with a segmentation fault." % (atext, atext))
        r.fix = ["Write `&%s` in the scanf call." % atext]
        first = arg[0]
        r.fixed_line = src.line(first.line)[:first.col - 1] + "&" + src.line(first.line)[first.col - 1:]
        r.fixed_line_no = first.line
        return r
    if is_scanf and re.search(r"\(\*\)\[\d+\]", act_c) and arg and arg[0].is_op("&"):
        r.title = "No & needed for a string in scanf"
        r.what = ("`%s` is a char array, and an array name is ALREADY an address. Remove the `&`: "
                  "`scanf(\"%%s\", %s);`" % (atext[1:].strip(), atext[1:].strip()))
        first = arg[0]
        l2 = src.line(first.line)
        r.fixed_line = l2[:first.col - 1] + l2[first.col:]
        r.fixed_line_no = first.line
        return r
    if not is_scanf and arg and arg[0].kind == "id":
        if comma_index(r, line):
            return r
        sym = src.symbols.lookup(arg[0].text, arg[0].index)
        depth, used = 0, 0
        for t in arg[1:]:
            if t.is_op("["):
                if depth == 0:
                    used += 1
                depth += 1
            elif t.is_op("]"):
                depth -= 1
        if sym is not None and sym.is_array and used < len(sym.array_sizes) and spec != "%s" \
                and len(arg) == 1 + 3 * used:
            n = sym.array_sizes[used]
            r.title = "printf cannot print a whole array"
            r.what = ("`%s` is a whole ARRAY%s, not one number. `%s` prints ONE value; given an array name, printf "
                      "receives its memory ADDRESS and prints a meaningless number." % (
                          atext, " of %d `%s`s" % (n, sym.type) if n and used == len(sym.array_sizes) - 1 else "",
                          spec or "%d"))
            idx = "i" if used == 0 else "j"
            elem = "%s[%s]" % (atext, idx)
            r.fix = ["Print one element: `%s[0]`, or all of them with a loop:" % atext,
                     "`for (int %s = 0; %s < %s; %s++) printf(\"%s \", %s);`" % (
                         idx, idx, n if n else "N", idx, spec or "%d", elem)]
            r.why = ["In C an array cannot be printed in one go (unlike Python's print(list)); each element is "
                     "printed separately."]
            r.example = {"wrong": "int a[5] = {1, 2, 3, 4, 5};\nprintf(\"%d\", a);",
                         "right": "int a[5] = {1, 2, 3, 4, 5};\nfor (int i = 0; i < 5; i++)\n    printf(\"%d \", a[i]);"}
            r.no_fix = True
            return r
    good = correct_spec(actual, is_scanf)
    if good and spec and good != spec:
        r.vars["good"] = good
        if is_scanf and good == "%lf":
            r.title = "Use %lf (not %f) for double in scanf"
            r.what = ("In scanf, `%f` reads a `float` and `%lf` reads a `double`. `" + atext.lstrip("&") +
                      "` is a double, so it needs `%lf`.")
        else:
            r.title = "Wrong format code %s for a %s" % (spec, act_c)
            r.what = ("`%s` in the format string expects a `%s`, but `%s` is a `%s`. The right code for a `%s` is "
                      "`%s`." % (spec, exp_c, atext, act_c, act_c, good))
        r.fix = ["Change `%s` to `%s`." % (spec, good)]
        fixed = replace_spec(good)
        if fixed:
            r.fixed_line = fixed
            r.fixed_line_no = fmt.line
        return r
    return r


@handler("format_count")
def format_count(ctx):
    r = Result()
    call, args, fmt = _format_call(ctx)
    if call is None or fmt is None:
        return r
    fi = FMT_INDEX.get(call.text, 0)
    specs = [s for s in SPEC_RE.finditer(fmt.text) if s.group(0) != "%%"]
    values = len(args) - fi - 1
    r.vars["func"] = call.text
    r.what = ("The format string of `%s` on line %d has %d placeholder(s) (%s) but %d value(s) are given after it."
              % (call.text, call.line, len(specs), ", ".join(s.group(0) for s in specs) or "none", values))
    return r


@handler("string_compare")
def string_compare(ctx):
    r = Result()
    src = ctx.src
    line = ctx.line_text() or ""
    m = re.search(r"([A-Za-z_]\w*(?:\[[^\]]+\])?)\s*(==|!=)\s*\"((?:[^\"\\]|\\.)*)\"", line) or \
        re.search(r"\"((?:[^\"\\]|\\.)*)\"\s*(==|!=)\s*([A-Za-z_]\w*(?:\[[^\]]+\])?)", line)
    if not m:
        # two char arrays:  if (word == rev)
        a = re.search(r"\b([A-Za-z_]\w*)\s*(==|!=)\s*([A-Za-z_]\w*)\b", line)
        if a:
            x, op, y = a.group(1), a.group(2), a.group(3)
            r.title = "Two strings (char arrays) compared with %s" % op
            r.what = ("`%s %s %s` compares the ADDRESSES of the two arrays, not their letters. Two different arrays "
                      "always have different addresses, so this is always %s - even when they hold the same text."
                      % (x, op, y, "false" if op == "==" else "true"))
            r.fix = ["Use `strcmp(%s, %s) %s 0` (needs `#include <string.h>`)." % (x, y, op)]
            r.fixed_line = line[:a.start()] + "strcmp(%s, %s) %s 0" % (x, y, op) + line[a.end():]
        return r
    if m.group(0).startswith('"'):
        lit, op, var = m.group(1), m.group(2), m.group(3)
    else:
        var, op, lit = m.group(1), m.group(2), m.group(3)
    base = re.match(r"\w+", var).group(0)
    sym = src.symbols.lookup(base, ctx.tok.index if (src is not None and ctx.tok is not None) else 10 ** 6) \
        if src is not None else None
    is_char = sym is not None and sym.type in ("char", "unsigned char", "signed char") and not sym.pointer and \
        (not sym.is_array or "[" in var)
    if len(re.sub(r"\\.", "x", lit)) == 1 and (is_char or sym is None):
        r.title = "Double quotes used for a single character"
        r.what = ("`\"%s\"` (double quotes) is a STRING - an address in memory. A single character is written "
                  "with single quotes: `'%s'`. Comparing `%s` with `\"%s\"` compares a character with an address, "
                  "so it is never true." % (lit, lit, var, lit))
        r.fix = ["Write `'%s'` with single quotes." % lit]
        r.fixed_line = line[:m.start()] + m.group(0).replace('"%s"' % lit, "'%s'" % lit) + line[m.end():]
        return r
    r.title = "Strings compared with %s" % op
    r.what = ("`%s %s \"%s\"` compares the ADDRESS of `%s` with the address of the text \"%s\" - not the letters. "
              "This is (almost) never true." % (var, op, lit, var, lit))
    r.fix = ["Use `strcmp(%s, \"%s\") %s 0` (needs `#include <string.h>`)." % (var, lit, op)]
    r.fixed_line = line[:m.start()] + 'strcmp(%s, "%s") %s 0' % (var, lit, op) + line[m.end():]
    if ctx.cpp:
        r.hints.append("In C++ you can also use `std::string answer;` - then `answer == \"yes\"` really compares the text.")
    return r


@handler("assign_in_condition")
def assign_in_condition(ctx):
    r = Result()
    src = ctx.src
    if src is None or not ctx.line_no:
        return r
    toks = src.tokens_on_line(ctx.line_no)
    eqs = [t for t in toks if t.is_op("=")]
    if not eqs:
        return r
    idx = ctx.col_index() or 0
    eq = min(eqs, key=lambda t: abs(t.col - 1 - idx))
    line = src.line(ctx.line_no)
    r.fixed_line = line[:eq.col - 1] + "==" + line[eq.col:]
    left = src.prev_token(eq)
    right = src.next_token(eq)
    if left is not None and right is not None:
        r.what = ("The condition on line %d is `%s = %s`: it STORES %s into `%s` and then tests the stored value "
                  "(always true unless it is 0). To compare, write `%s == %s`." % (
                      ctx.line_no, left.text, right.text, right.text, left.text, left.text, right.text))
    return r


@handler("uninitialized")
def uninitialized(ctx):
    name = ctx.groups.get("name", "")
    r = Result(vars={"name": name})
    src = ctx.src
    line = ctx.line_text() or ""
    if re.search(r"\bscanf\s*\(.*,\s*%s\b" % re.escape(name), line) and \
            not re.search(r"&\s*%s\b" % re.escape(name), line):
        r.title = "scanf without & leaves the variable empty"
        r.what = ("`%s` is passed to scanf WITHOUT `&`, so scanf cannot store the input in it - and its garbage "
                  "value is used instead." % name)
        r.fix = ["Write `&%s` in the scanf call." % name]
        r.fixed_line = re.sub(r"(,\s*)(%s\b)" % re.escape(name), r"\1&\2", line, count=1)
        return r
    if src is not None:
        decls = [s for s in src.symbols.declarations(name) if s.kind == "var" and s.line <= (ctx.line_no or 10 ** 6)]
        if decls:
            d = decls[-1]
            dl = src.line(d.line)
            r.real_line = d.line
            if not d.is_array:
                fixed = re.sub(r"\b(%s)\b(\s*)(?=[,;])" % re.escape(name), r"\1 = 0\2", dl, count=1)
                if fixed != dl:
                    r.fixed_line = fixed
                    r.fixed_line_no = d.line
            r.hints.append("`%s` is declared on line %d without a starting value." % (name, d.line))
    return r


@handler("unused")
def unused(ctx):
    name = ctx.groups.get("name", "")
    r = Result(vars={"name": name})
    src = ctx.src
    if src is not None:
        uses = src.identifier_count(name)
        has_errors = any(d.is_error for d in ctx.all if d is not ctx.diag)
        if uses > 1 and has_errors:
            r.hints.append("`%s` IS used later in your code, so this warning is probably a side effect of an error "
                           "above: the compiler skipped the broken code that uses it. Fix the errors first." % name)
            r.confidence = "medium"
    if "set but not used" in ctx.diag.message:
        r.what = "Values are stored into `%s`, but it is never read afterwards, so those values are wasted." % name
    if "parameter" in ctx.diag.message:
        r.what = "The parameter `%s` is never used inside the function." % name
    return r


@handler("missing_return")
def missing_return(ctx):
    r = Result(vars={"func": "this function", "rtype": "value"})
    src = ctx.src
    ctxt = ctx.diag.context or ""
    m = re.search(r"In (?:member )?function '(?:[\w:<>*& ]+?\s)?\**([\w:]+)\s*\(?", ctxt)
    func = m.group(1).split("::")[-1] if m else None
    if func is None and src is not None and ctx.line_no:
        func = src.enclosing_function(ctx.line_no) or src.enclosing_function(ctx.line_no - 1)
    if func:
        r.vars["func"] = func
        if src is not None:
            fdef, _ = src.symbols.function_named(func)
            if fdef is not None and fdef.type:
                r.vars["rtype"] = fdef.type
    if src is not None and ctx.line_no:
        line = src.line(ctx.line_no)
        indent = "    "
        prev = src.prev_nonblank_line(ctx.line_no)
        if prev:
            indent = re.match(r"\s*", src.line(prev)).group(0) or "    "
        r.fixed_line = indent + "return 0;   /* or the value that fits this case */"
        r.fixed_line_no = ctx.line_no
        r.fixed_kind = "insert_before"
    return r


@handler("misleading_indentation")
def misleading_indentation(ctx):
    r = Result(vars={"kw": ctx.groups.get("kw", "if")})
    src = ctx.src
    if src is None:
        return r
    # find the if/for/while line: GCC points at it, Clang's note does
    n, _ = ctx.note(r"previous statement is here")
    ln = n.location.line if n is not None and n.location else ctx.line_no
    toks = src.tokens_on_line(ln)
    head = next((t for t in toks if t.kind == "kw" and t.text in ("if", "for", "while", "else")), None)
    if head is None:
        return r
    r.vars["kw"] = head.text
    op = src.next_token(head)
    if op is not None and op.is_op("("):
        close = src.brackets.match.get(op.index)
        after = src.tok(close + 1) if close is not None else None
        if after is not None and after.is_op(";"):
            r.title = "Semicolon right after %s (...)" % head.text
            r.what = ("The `;` directly after `%s (...)` on line %d is an empty statement - it is the whole body of "
                      "the %s. The indented line below runs ALWAYS, no matter what the condition is." % (
                          head.text, ln, head.text))
            r.fix = ["Remove the `;` after the closing `)`."]
            line = src.line(after.line)
            r.fixed_line = line[:after.col - 1].rstrip() + line[after.col:]
            r.fixed_line_no = after.line
            r.real_line = after.line
            return r
    r.real_line = ln
    return r


@handler("empty_body")
def empty_body(ctx):
    r = Result(vars={"kw": ctx.groups.get("kw", "if")})
    src = ctx.src
    line = ctx.line_text() or ""
    idx = ctx.col_index()
    if idx is not None and idx < len(line) and line[idx] == ";":
        r.fixed_line = line[:idx].rstrip() + line[idx + 1:]
    elif src is not None:
        m = re.search(r"\)\s*;", line)
        if m:
            r.fixed_line = line[:m.start() + 1] + line[m.end():]
    return r


@handler("no_effect")
def no_effect(ctx):
    r = Result()
    line = ctx.line_text() or ""
    if re.search(r"\bfor\s*\(", line) and "comma" in ctx.diag.message:
        return Result(redirect="S006")
    if "comma" in ctx.diag.message and comma_index(r, line):
        return r
    m = re.match(r"^(\s*)([\w\[\]\.]+)\s*==\s*(.+);\s*$", line)
    if m:
        r.title = "== used instead of ="
        r.what = ("`%s == %s;` only COMPARES the two values and throws the result away. To store a value use a "
                  "single `=`." % (m.group(2), m.group(3).strip()))
        r.fixed_line = "%s%s = %s;" % (m.group(1), m.group(2), m.group(3).strip())
        return r
    m = re.match(r"^(\s*)(\w+)\s*([+\-*/])\s*(\w+)\s*;\s*$", line)
    if m:
        r.what = ("`%s %s %s;` calculates a value but does not store it anywhere. Did you mean `%s %s= %s;`?" % (
            m.group(2), m.group(3), m.group(4), m.group(2), m.group(3), m.group(4)))
        r.fixed_line = "%s%s %s= %s;" % (m.group(1), m.group(2), m.group(3), m.group(4))
    return r


@handler("array_bounds")
def array_bounds(ctx):
    r = Result()
    src = ctx.src
    if src is None:
        return r
    index = ctx.groups.get("index")
    for t in src.tokens_on_line(ctx.line_no or 0):
        nx = src.next_token(t)
        if t.kind == "id" and nx is not None and nx.is_op("["):
            sym = src.symbols.lookup(t.text, t.index)
            if sym is not None and sym.array_sizes and sym.array_sizes[0]:
                n = sym.array_sizes[0]
                r.what = ("`%s` has %d elements, so its valid indexes are 0 to %d. Index %s is outside the array - "
                          "it reads/writes memory that belongs to something else." % (t.text, n, n - 1, index or "used here"))
                break
    if ctx.groups.get("iter"):
        r.what = ("A loop on line %s runs one time too many and goes past the end of an array (iteration %s). "
                  "Check the loop condition - use `i < N`, not `i <= N`." % (ctx.line_no, ctx.groups["iter"]))
    return r


@handler("address_always_true")
def address_always_true(ctx):
    name = ctx.groups.get("name", "")
    r = Result(vars={"name": name})
    src = ctx.src
    if src is not None:
        fdef, proto = src.symbols.function_named(name)
        sym = fdef or proto
        if sym is not None and sym.params:
            r.vars["name"] = name
            r.fix = ["Call the function with its arguments: `%s(%s)`." % (name, ", ".join(p.name or "?" for p in sym.params))]
    return r


@handler("precedence")
def precedence(ctx):
    r = Result()
    line = ctx.line_text() or ""
    m = re.search(r"(\b[\w.\[\]]+)\s*(<=|<|>=|>)\s*([\w.\[\]]+)\s*(<=|<|>=|>)\s*([\w.\[\]]+)", line)
    if m and ("comparison" in ctx.diag.message or "boolean" in ctx.diag.message):
        a, op1, b, op2, c = m.groups()
        r.title = "Chained comparison like in maths"
        r.what = ("`%s %s %s %s %s` does not mean 'b is between a and c'. C first computes `%s %s %s` (0 or 1) and "
                  "then compares that 0/1 with %s, so the result is almost always true." % (a, op1, b, op2, c, a, op1, b, c))
        r.fix = ["Write it as two comparisons joined with &&: `%s %s %s && %s %s %s`." % (a, op1, b, b, op2, c)]
        r.fixed_line = line[:m.start()] + "%s %s %s && %s %s %s" % (a, op1, b, b, op2, c) + line[m.end():]
        return r
    m = re.search(r"([\w.\[\]]+)\s*([&|^])\s*([\w.\[\]]+)\s*(==|!=)\s*([\w.\[\]]+)", line)
    if m:
        r.title = "Bitwise operator binds weaker than =="
        r.what = ("`%s %s %s %s %s` is computed as `%s %s (%s %s %s)` because `%s` has a higher priority than `%s`." %
                  (m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(1), m.group(2), m.group(3),
                   m.group(4), m.group(5), m.group(4), m.group(2)))
        r.fixed_line = line[:m.start()] + "(%s %s %s) %s %s" % m.groups() + line[m.end():]
        return r
    m = re.search(r"!\s*(\w+)\s*(==|!=)\s*(\w+)", line)
    if m:
        r.what = "`!%s %s %s` is computed as `(!%s) %s %s`. Did you mean `%s != %s`?" % (
            m.group(1), m.group(2), m.group(3), m.group(1), m.group(2), m.group(3), m.group(1), m.group(3))
        r.fixed_line = line[:m.start()] + "%s != %s" % (m.group(1), m.group(3)) + line[m.end():]
    return r


TYPE_LIMITS = {"char": (-128, 127), "signed char": (-128, 127), "unsigned char": (0, 255),
               "short": (-32768, 32767), "unsigned short": (0, 65535),
               "int": (-2147483648, 2147483647), "unsigned int": (0, 4294967295)}
BIGGER = {"char": "int", "signed char": "int", "unsigned char": "int", "short": "int", "unsigned short": "int",
          "int": "long long", "unsigned int": "unsigned long long"}


@handler("value_changes")
def value_changes(ctx):
    """int a = 2147483648;  /  int x = 2.9;  -> say exactly what happens to the value."""
    frm, to = ctx.groups.get("from", ""), ctx.groups.get("to", "")
    v1, v2 = ctx.groups.get("v1"), ctx.groups.get("v2")
    r = Result()
    if not (frm and to and v1 and v2):
        return r
    if frm in ("double", "float", "long double") and to in TYPE_LIMITS:
        r.title = "Decimal part lost: %s becomes %s" % (v1, v2)
        r.what = ("On line %s the decimal number `%s` is stored in an `%s`. An `%s` holds only whole numbers, so the "
                  "part after the decimal point is CUT OFF (not rounded): %s becomes %s." % (
                      ctx.line_no, v1, to, to, v1, v2))
        r.fix = ["If you need the decimals, make the variable `float` or `double`.",
                 "If you want a whole number, say so with a cast: `(%s)%s` - or round it: `(%s)(x + 0.5)`." % (
                     to, v1, to)]
        r.why = ["Storing a decimal value in an int variable (or int array element)."]
        r.example = {"wrong": "int x = 2.9;      /* x is 2 */", "right": "double x = 2.9;   /* x is 2.9 */"}
        return r
    if to in TYPE_LIMITS:
        lo, hi = TYPE_LIMITS[to]
        r.title = "Number too big for %s: %s becomes %s" % (to, v1, v2)
        r.what = ("On line %s the value %s is stored in a `%s`, but a `%s` can only hold %d to %d. The number does "
                  "not fit, so it silently becomes %s (it 'wraps around')." % (ctx.line_no, v1, to, to, lo, hi, v2))
        r.fix = ["Use a bigger type: `%s` (and print it with `%s`)." % (
            BIGGER.get(to, "long long"), "%lld" if BIGGER.get(to, "long long") == "long long" else "%d")]
        r.why = ["Every integer type has a limit: char about 127, short about 32 thousand, int about 2.1 billion."]
        r.example = {"wrong": "int big = 99999999999;", "right": "long long big = 99999999999;"}
    return r
