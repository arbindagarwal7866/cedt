"""
prechecks.py - CEDT's own static checks for classic beginner bugs that the
compiler does NOT report (or only reports with special options).

They work on the token stream, bracket report and symbol table built by
source.py, i.e. they are small semantic / data-flow analyses:

  T001  ;  right after if / while / for            (empty body)
  T002  integer division stored in a float          (sum / n)
  T003  #define ending with ;
  T004  constant array index out of bounds          (a[5] for int a[5])
  T005  off-by-one loop  i <= N  over an array of N
  T006  ^ used as "power"                           (x^2 is XOR)
  T007  switch case without break                   (fall-through)
  T008  variable read before it gets a value        (int sum; sum += i)
  T009  invisible / non-ASCII character in code
  T010  fflush(stdin)
  T011  == with a decimal constant                  (x == 0.1)
  T012  non-standard <conio.h>
  T013  scanf format traps                          ("%d\\n", "%c" after scanf)
  T014  loop counter moving the wrong way           (i < n; i--)
  T015  missing ; the compiler has not reported yet (only when the build failed)
Every check is conservative: when unsure it stays silent.
"""
import re

from .models import Explanation, Location

PRIMITIVE = {"int", "char", "float", "double", "long", "short", "unsigned", "signed", "bool", "_Bool",
             "long long", "unsigned int", "long int", "unsigned long", "long double", "size_t",
             "unsigned char", "short int", "long long int", "unsigned long long", "signed char"}
INT_TYPES = {"int", "long", "short", "char", "unsigned", "signed", "long long", "unsigned int", "long int",
             "unsigned long", "short int", "long long int", "unsigned long long", "unsigned char",
             "signed char", "size_t", "bool", "_Bool"}
FLOAT_TYPES = {"float", "double", "long double"}


def _tip(src, rule_id, title, phase, line, col, what, why=None, fix=None, hints=None,
         fixed_line=None, fixed_no=None, kind="replace", example=None):
    e = Explanation(rule_id=rule_id, title=title, phase=phase, level="tip", what=what,
                    why=why or [], fix=fix or [], hints=hints or [],
                    location=Location(src.path, line, col),
                    compiler_message="(the compiler reports nothing here - CEDT's own beginner check)",
                    source="precheck", confidence="medium")
    if fixed_line is not None:
        e.fixed_line = fixed_line
        e.fixed_line_no = fixed_no or line
        e.fixed_kind = kind
    if example:
        e.example_wrong, e.example_right = example
    return e


def _match(src, i):
    return src.brackets.match.get(i)


def _lookup(src, name, idx):
    return src.symbols.lookup(name, idx)


# ------------------------------------------------------------------ T001
def check_empty_body(src, lang):
    out = []
    toks = src.tokens
    for i, t in enumerate(toks):
        if t.kind != "kw" or t.text not in ("if", "while", "for"):
            continue
        op = src.tok(i + 1)
        if op is None or not op.is_op("("):
            continue
        close = _match(src, op.index)
        if close is None:
            continue
        semi = src.tok(close + 1)
        if semi is None or not semi.is_op(";"):
            continue
        if t.text == "while":
            prev = src.tok(i - 1)
            if prev is not None and prev.is_op("}"):
                o = _match(src, prev.index)
                if o is not None and src.tok(o - 1) is not None and src.tok(o - 1).is_kw("do"):
                    continue
        line = src.line(semi.line)
        fixed = line[:semi.col - 1].rstrip() + line[semi.col:]
        if t.text == "if":
            what = ("The `;` right after `if (...)` on line %d ends the if statement immediately. The code below it "
                    "is NOT controlled by the condition - it always runs." % semi.line)
        elif t.text == "while":
            what = ("The `;` right after `while (...)` on line %d makes an EMPTY loop. If the condition is true it "
                    "loops forever doing nothing; the block below is not part of the loop." % semi.line)
        else:
            what = ("The `;` right after `for (...)` on line %d makes the loop body EMPTY. The loop just counts, "
                    "and the block below runs only ONCE, after the loop ends." % semi.line)
        out.append(_tip(src, "T001", "Semicolon right after %s (...)" % t.text, "flow", semi.line, semi.col, what,
                        why=["A habit of ending every line with `;` - but lines like `if (...)` must not end with one."],
                        fix=["Remove the `;` after the closing `)`."], fixed_line=fixed,
                        example=("for (i = 0; i < 5; i++);\n{\n    printf(\"%d\", i);\n}",
                                 "for (i = 0; i < 5; i++)\n{\n    printf(\"%d\", i);\n}")))
    return out


# ------------------------------------------------------------------ T002
def _type_of(src, tok):
    s = _lookup(src, tok.text, tok.index)
    if s is None or s.pointer or s.is_array:
        return None
    return s.type.replace("const ", "").strip()


def check_int_division(src, lang):
    out = []
    toks = src.tokens
    for i, t in enumerate(toks):
        if not t.is_op("="):
            continue
        target = src.tok(i - 1)
        if target is None or target.kind != "id":
            continue
        ttype = _type_of(src, target)
        if ttype not in FLOAT_TYPES:
            continue
        # right-hand side up to ; at depth 0
        j = i + 1
        depth = 0
        rhs = []
        while j < len(toks):
            x = toks[j]
            if x.is_op("(", "["):
                depth += 1
            elif x.is_op(")", "]"):
                depth -= 1
            if (x.is_op(";", ",") and depth <= 0) or depth < 0:
                break
            rhs.append(x)
            j += 1
        if not any(x.is_op("/") for x in rhs):
            continue
        ok = True
        for k, x in enumerate(rhs):
            if x.kind == "float":
                ok = False
            elif x.kind == "kw" and x.text in ("float", "double"):
                ok = False
            elif x.kind == "id":
                nx = rhs[k + 1] if k + 1 < len(rhs) else None
                if nx is not None and nx.is_op("("):
                    ok = False                      # function call: return type unknown
                    break
                ty = _type_of(src, x)
                if ty is None or ty not in INT_TYPES:
                    ok = False
            elif x.kind not in ("int", "op"):
                ok = False
        if not ok:
            continue
        div = next(x for x in rhs if x.is_op("/"))
        k = rhs.index(div)
        left = rhs[k - 1] if k > 0 else None
        right = rhs[k + 1] if k + 1 < len(rhs) else None
        if left is None or right is None:
            continue
        expr = "%s / %s" % (left.text, right.text)
        line = src.line(left.line)
        fixed = None
        if left.kind == "int" and left.text.isdigit() and left.line == div.line:
            fixed = line[:left.col - 1] + left.text + ".0" + line[left.col - 1 + len(left.text):]
        elif left.kind == "id" and left.line == div.line:
            fixed = line[:left.col - 1] + "(%s)" % ttype + line[left.col - 1:]
        out.append(_tip(src, "T002", "Integer division stored in a %s" % ttype, "semantic", div.line, div.col,
                        "`%s` divides two whole numbers, so C throws the decimal part away BEFORE the result is "
                        "stored in the %s `%s` (for example 7 / 2 gives 3, not 3.5)." % (expr, ttype, target.text),
                        why=["When both sides of `/` are integers, the result is an integer."],
                        fix=["Make one side a decimal number: `(%s)%s / %s`, or divide by `2.0` instead of `2`." % (
                            ttype, left.text, right.text)],
                        fixed_line=fixed,
                        example=("float avg = sum / n;", "float avg = (float)sum / n;")))
    out.extend(_int_division_inside(src, set(o.location.line for o in out)))
    return out


def _is_int_operand(src, x):
    if x.kind == "int":
        return True
    return x.kind == "id" and _type_of(src, x) in INT_TYPES


def _int_division_inside(src, done_lines):
    """`f = (9/5) * c + 32;` - an int / int part inside a bigger calculation stored in a float."""
    out = []
    toks = src.tokens
    for i, div in enumerate(toks):
        if not div.is_op("/") or div.line in done_lines:
            continue
        left, right = src.tok(i - 1), src.tok(i + 1)
        before, after = src.tok(i - 2), src.tok(i + 2)
        if left is None or right is None:
            continue
        # one-token operands only; `(float)a / b` and `x * a / b` are left alone
        if before is not None and before.is_op("*", "/", "%", ")", ".", "->"):
            continue
        if after is not None and after.is_op("[", "(", ".", "->"):
            continue
        if not (_is_int_operand(src, left) and _is_int_operand(src, right)):
            continue
        if left.kind == "int" and right.kind == "int":
            if not (left.text.isdigit() and right.text.isdigit()):
                continue
            a, b = int(left.text), int(right.text)
            if b == 0 or a % b == 0:
                continue
        stmt = src.statement_tokens(div)
        target = None
        for k, x in enumerate(stmt):
            if x.index >= div.index:
                break
            if x.is_op("=") and k > 0:
                t = stmt[k - 1]
                if t.is_op("]"):
                    o = _match(src, t.index)
                    t = src.tok(o - 1) if o is not None else None
                if t is not None and t.kind == "id":
                    target = t
        if target is None:
            continue
        s = _lookup(src, target.text, target.index)
        ttype = s.type.replace("const ", "").strip() if s is not None else None
        if ttype not in FLOAT_TYPES:
            continue
        expr = "%s / %s" % (left.text, right.text)
        line = src.line(div.line)
        if left.kind == "int":
            a, b = int(left.text), int(right.text)
            result = "`%s` gives %d, not %s" % (expr, a // b, ("%.4f" % (a / b)).rstrip("0").rstrip("."))
            better = "%s.0 / %s" % (left.text, right.text)
            fixed = line[:left.col - 1] + left.text + ".0" + line[left.col - 1 + len(left.text):] \
                if left.line == div.line else None
        else:
            result = "`%s` loses its decimal part (7 / 2 gives 3, not 3.5)" % expr
            better = "(%s)%s / %s" % (ttype, left.text, right.text)
            fixed = line[:left.col - 1] + "(%s)" % ttype + line[left.col - 1:] if left.line == div.line else None
        out.append(_tip(src, "T002", "Integer division inside a %s calculation" % ttype, "semantic", div.line,
                        div.col,
                        "%s: both sides of `/` are whole numbers, so C does an INTEGER division and throws the "
                        "decimal part away - even though the final result is stored in the %s `%s`. The rest of "
                        "the calculation then uses the wrong value." % (result[0].upper() + result[1:], ttype,
                                                                       target.text),
                        why=["The type of the variable on the left of `=` does not matter: each `/` is calculated "
                             "with the types of its own two sides."],
                        fix=["Make one side a decimal number: `%s`." % better],
                        fixed_line=fixed,
                        example=("f = (9 / 5) * c + 32;     /* 9/5 is 1 */",
                                 "f = (9.0 / 5) * c + 32;   /* 9.0/5 is 1.8 */")))
    return out


# ------------------------------------------------------------------ T003
def check_define_semicolon(src, lang):
    out = []
    for t in src.tokens:
        if t.kind != "pp":
            continue
        m = re.match(r"#\s*define\s+([A-Za-z_]\w*)\s+(.*?);\s*(?://.*|/\*.*\*/)?\s*$", t.text)
        if not m:
            continue
        value = m.group(2).strip()
        if not value or "(" in m.group(1) or re.search(r"\b(printf|scanf|puts|return)\b|[{}]", value):
            continue
        line = src.line(t.line)
        fixed = re.sub(r";(\s*(?://.*|/\*.*\*/)?\s*)$", r"\1", line).rstrip()
        out.append(_tip(src, "T003", "Semicolon at the end of a #define", "preprocessor", t.line, t.col,
                        "`#define %s %s;` - the `;` becomes part of `%s`. Wherever you write `%s` the preprocessor "
                        "pastes `%s;`, which breaks expressions like `int a[%s];` or `x = %s + 1;`." % (
                            m.group(1), value, m.group(1), m.group(1), value, m.group(1), m.group(1)),
                        fix=["Remove the `;` from the #define line."], fixed_line=fixed))
    return out


# ------------------------------------------------------------------ T004
def check_const_index(src, lang):
    out = []
    toks = src.tokens
    for i, t in enumerate(toks):
        if t.kind != "id":
            continue
        ob = src.tok(i + 1)
        num = src.tok(i + 2)
        cb = src.tok(i + 3)
        if ob is None or not ob.is_op("[") or num is None or num.kind != "int" or cb is None or not cb.is_op("]"):
            continue
        s = _lookup(src, t.text, i)
        if s is None or not s.array_sizes or not s.array_sizes[0] or s.tok == i:
            continue
        if s.line == t.line and s.tok > i - 3:
            continue
        try:
            idx = int(num.text.rstrip("uUlL"), 0)
        except ValueError:
            continue
        n = s.array_sizes[0]
        if 0 <= idx < n:
            continue
        out.append(_tip(src, "T004", "Array index out of bounds", "flow", t.line, t.col,
                        "`%s` has %d elements, so its valid indexes are 0 to %d - but line %d uses `%s[%d]`. "
                        "That reads or writes memory outside the array: the program may print garbage, "
                        "change other variables or crash." % (t.text, n, n - 1, t.line, t.text, idx),
                        why=["Arrays in C/C++ start at index 0, so the LAST element of `%s[%d]` is `%s[%d]`." % (
                            t.text, n, t.text, n - 1)],
                        fix=["Use an index between 0 and %d." % (n - 1)]))
    return out


# ------------------------------------------------------------------ T005
def _for_clauses(src, for_tok):
    op = src.tok(for_tok.index + 1)
    if op is None or not op.is_op("("):
        return None
    close = _match(src, op.index)
    if close is None:
        return None
    parts, cur, depth = [], [], 0
    for x in src.tokens[op.index + 1:close]:
        if x.is_op("(", "["):
            depth += 1
        elif x.is_op(")", "]"):
            depth -= 1
        if x.is_op(";") and depth == 0:
            parts.append(cur)
            cur = []
        else:
            cur.append(x)
    parts.append(cur)
    if len(parts) != 3:
        return None
    body_start = close + 1
    b = src.tok(body_start)
    if b is None:
        return None
    if b.is_op("{"):
        body_end = _match(src, b.index) or body_start
    else:
        body_end = body_start
        while body_end < len(src.tokens) and not src.tokens[body_end].is_op(";"):
            body_end += 1
    return parts, (body_start, body_end), close


def _const_value(src, tok):
    if tok.kind == "int":
        try:
            return int(tok.text.rstrip("uUlL"), 0)
        except ValueError:
            return None
    if tok.kind == "id" and tok.text in src.symbols.macros:
        v = src.symbols.macros[tok.text].value.strip().rstrip(";").strip()
        if re.fullmatch(r"\d+", v):
            return int(v)
    return None


def check_off_by_one(src, lang):
    out = []
    for t in src.tokens:
        if not t.is_kw("for"):
            continue
        info = _for_clauses(src, t)
        if info is None:
            continue
        (init, cond, upd), (bs, be), close = info
        rev = _reverse_off_by_one(src, init, cond, bs, be)
        if rev is not None:
            out.append(rev)
            continue
        if len(cond) != 3 or cond[0].kind != "id" or not cond[1].is_op("<="):
            continue
        var = cond[0].text
        bound = _const_value(src, cond[2])
        if bound is None:
            continue
        init_txt = " ".join(x.text for x in init)
        if not re.search(r"\b%s\s*=\s*0\b" % re.escape(var), init_txt):
            continue
        body = src.tokens[bs:be + 1]
        for k, x in enumerate(body[:-3]):
            if x.kind == "id" and body[k + 1].is_op("[") and body[k + 2].text == var and body[k + 3].is_op("]"):
                s = _lookup(src, x.text, x.index)
                if s is not None and s.array_sizes and s.array_sizes[0] == bound:
                    line = src.line(cond[1].line)
                    fixed = line[:cond[1].col - 1] + "<" + line[cond[1].col + 1:]
                    out.append(_tip(src, "T005", "Loop runs one step too far (off-by-one)", "flow",
                                    cond[1].line, cond[1].col,
                                    "The loop continues while `%s <= %d`, so its last pass uses `%s = %d`. But `%s` "
                                    "has only %d elements (indexes 0 to %d), so `%s[%d]` is outside the array." % (
                                        var, bound, var, bound, x.text, bound, bound - 1, x.text, bound),
                                    fix=["Use `%s < %d` instead of `%s <= %d`." % (var, bound, var, bound)],
                                    fixed_line=fixed,
                                    example=("for (i = 0; i <= 5; i++)\n    sum += a[i];",
                                             "for (i = 0; i < 5; i++)\n    sum += a[i];")))
                    break
    return out


def _reverse_off_by_one(src, init, cond, bs, be):
    """for (i = 5; i >= 0; i--) over int a[5]  ->  the first pass uses a[5]."""
    if len(init) < 3 or len(cond) != 3 or cond[0].kind != "id" or not cond[1].is_op(">=", ">"):
        return None
    var = cond[0].text
    if not ((cond[1].is_op(">=") and cond[2].text == "0") or (cond[1].is_op(">") and cond[2].text in ("-1", "0"))):
        return None
    k = next((j for j, x in enumerate(init) if x.text == var), None)
    if k is None or k + 2 >= len(init) or not init[k + 1].is_op("=") or (k + 3 < len(init) and not init[k + 3].is_op(",")):
        return None
    start_tok = init[k + 2]
    start = _const_value(src, start_tok)
    if start is None:
        return None
    body = src.tokens[bs:be + 1]
    for j, x in enumerate(body[:-3]):
        if x.kind == "id" and body[j + 1].is_op("[") and body[j + 2].text == var and body[j + 3].is_op("]"):
            s = _lookup(src, x.text, x.index)
            if s is not None and s.array_sizes and s.array_sizes[0] == start:
                line = src.line(start_tok.line)
                better = str(start - 1) if start_tok.kind == "int" else "%s - 1" % start_tok.text
                fixed = line[:start_tok.col - 1] + better + line[start_tok.col - 1 + len(start_tok.text):]
                return _tip(src, "T005", "Loop starts one step too far (off-by-one)", "flow",
                            start_tok.line, start_tok.col,
                            "The loop starts with `%s = %d`, so its first pass uses `%s[%d]`. But `%s` has only %d "
                            "elements (indexes 0 to %d) - the last element is `%s[%d]`." % (
                                var, start, x.text, start, x.text, start, start - 1, x.text, start - 1),
                            fix=["Start at `%s = %d` (that is, size - 1)." % (var, start - 1)],
                            fixed_line=fixed,
                            example=("for (i = 5; i >= 0; i--)\n    printf(\"%d\", a[i]);",
                                     "for (i = 4; i >= 0; i--)\n    printf(\"%d\", a[i]);"))
    return None


# ------------------------------------------------------------------ T006
def check_xor_power(src, lang):
    out = []
    toks = src.tokens
    for i, t in enumerate(toks):
        if not t.is_op("^"):
            continue
        left, right = src.tok(i - 1), src.tok(i + 1)
        if left is None or right is None or right.kind != "int" or right.text not in ("2", "3"):
            continue
        if left.kind == "int" and left.text.lower().startswith("0x"):
            continue
        stmt = src.statement_tokens(t)
        if any(x.is_op("&", "|", "<<", ">>", "~", "&=", "|=", "^=") for x in stmt):
            continue
        if left.kind not in ("id", "int") and not left.is_op(")"):
            continue
        line = src.line(t.line)
        fixed = None
        if left.kind in ("id", "int") and left.line == t.line == right.line:
            rep = ("%s * %s" % (left.text, left.text)) if right.text == "2" else "%s * %s * %s" % ((left.text,) * 3)
            fixed = line[:left.col - 1] + rep + line[right.col - 1 + len(right.text):]
        out.append(_tip(src, "T006", "^ is not 'to the power of'", "semantic", t.line, t.col,
                        "In C/C++ `^` means bitwise XOR, not power. `%s^%s` does NOT compute %s to the power %s "
                        "(for example 3^2 gives 1, not 9)." % (left.text, right.text, left.text, right.text),
                        fix=["Multiply instead (`x * x`), or use `pow(x, 2)` from <math.h> / <cmath>."],
                        fixed_line=fixed, example=("int sq = x^2;", "int sq = x * x;")))
    return out


# ------------------------------------------------------------------ T007
def check_fallthrough(src, lang):
    out = []
    toks = src.tokens
    comments = [c for c in src.all_tokens if c.kind == "comment"]
    for t in toks:
        if not t.is_kw("switch"):
            continue
        op = src.tok(t.index + 1)
        if op is None or not op.is_op("("):
            continue
        close = _match(src, op.index)
        body = src.tok(close + 1) if close is not None else None
        if body is None or not body.is_op("{"):
            continue
        end = _match(src, body.index)
        if end is None:
            continue
        labels = []
        depth = 0
        k = body.index + 1
        while k < end:
            x = toks[k]
            if x.is_op("{"):
                depth += 1
            elif x.is_op("}"):
                depth -= 1
            elif depth == 0 and x.kind == "kw" and x.text in ("case", "default"):
                c = k
                while c < end and not toks[c].is_op(":"):
                    c += 1
                labels.append((k, c))
            elif depth == 0 and x.is_kw("switch"):
                # skip nested switch body
                o2 = src.tok(k + 1)
                c2 = _match(src, o2.index) if o2 is not None else None
                b2 = src.tok(c2 + 1) if c2 is not None else None
                if b2 is not None and b2.is_op("{"):
                    k = _match(src, b2.index) or k
            k += 1
        for n, (lab, colon) in enumerate(labels[:-1]):
            seg = toks[colon + 1:labels[n + 1][0]]
            if not seg:
                continue
            # last statement of the segment (look inside a final block)
            last_tokens = seg
            if seg[-1].is_op("}") and _match(src, seg[-1].index) is not None:
                inner_start = _match(src, seg[-1].index)
                last_tokens = toks[inner_start + 1:seg[-1].index] or seg
            stmts, cur = [], []
            depth = 0
            for x in last_tokens:
                if x.is_op("{", "("):
                    depth += 1
                elif x.is_op("}", ")"):
                    depth -= 1
                cur.append(x)
                if x.is_op(";") and depth == 0:
                    stmts.append(cur)
                    cur = []
            if not stmts:
                continue
            first = stmts[-1][0]
            if first.kind == "kw" and first.text in ("break", "return", "continue", "goto", "throw"):
                continue
            if first.kind == "id" and first.text in ("exit", "abort", "_Exit"):
                continue
            seg_start, seg_end = seg[0].pos, labels[n + 1][0]
            nxt_lab = toks[labels[n + 1][0]]
            if any(seg[0].pos <= c.pos <= nxt_lab.pos and re.search(r"fall", c.text, re.I) for c in comments):
                continue
            last = stmts[-1][-1]
            lab_txt = " ".join(x.text for x in toks[lab:colon])
            nxt_txt = " ".join(x.text for x in toks[labels[n + 1][0]:labels[n + 1][1]])
            line = src.line(last.line)
            out.append(_tip(src, "T007", "case without break (falls through)", "flow", toks[lab].line, toks[lab].col,
                            "`%s:` has no `break`. After its code runs, execution continues straight into `%s:` "
                            "as well - so both blocks run." % (lab_txt, nxt_txt),
                            fix=["End the case with `break;` (unless running into the next case is intended)."],
                            fixed_line=line.rstrip() + " break;", fixed_no=last.line,
                            example=("case 1: printf(\"one\");\ncase 2: printf(\"two\"); break;",
                                     "case 1: printf(\"one\"); break;\ncase 2: printf(\"two\"); break;")))
    return out


# ------------------------------------------------------------------ T008
def _inside_call(src, idx):
    depth = 0
    k = idx - 1
    while k >= 0:
        t = src.tokens[k]
        if t.is_op(")"):
            depth += 1
        elif t.is_op("("):
            if depth == 0:
                head = src.tok(k - 1)
                return head is not None and head.kind == "id"
            depth -= 1
        elif t.is_op(";", "{", "}"):
            return False
        k -= 1
    return False


READ_AFTER = (";", ")", ",", "+", "-", "*", "/", "%", "<", ">", "<=", ">=", "==", "!=", "&&", "||", "]", "?", ":")


def _array_never_filled(src, s):
    """First READ of a local array that is never written, passed anywhere or initialised."""
    toks = src.tokens
    sc = src.symbols.scopes[s.scope]
    first_read = None
    for i in range(s.tok + 1, min(sc.end, len(toks) - 1) + 1):
        t = toks[i]
        if t.kind != "id" or t.text != s.name or _lookup(src, t.text, t.index) is not s:
            continue
        p = src.tok(i - 1)
        n = src.tok(i + 1)
        if n is None or not n.is_op("["):
            return None                     # whole array used: passed to scanf/a function, sizeof ...
        k = i + 1
        while src.tok(k) is not None and src.tok(k).is_op("["):
            close = _match(src, k)
            if close is None:
                return None
            k = close + 1
        after = src.tok(k)
        if (p is not None and p.is_op("&", "++", "--")) or after is None or not after.is_op(*READ_AFTER):
            return None                     # a[i] = ..., &a[i], a[i]++ ...: it gets values somewhere
        if first_read is None:
            first_read = t
    return first_read


def check_uninitialized(src, lang):
    out = []
    syms = src.symbols
    for s in syms.symbols:
        if s.kind != "var" or s.initialized or not s.is_array or s.tok < 0 or s.pointer:
            continue
        if syms.scopes[s.scope].kind in ("file", "struct", "class", "namespace") or \
                re.search(r"\bstatic\b", src.line(s.line)):
            continue
        nxt = src.tok(s.tok + 1)
        k = s.tok + 1
        while src.tok(k) is not None and src.tok(k).is_op("["):
            close = _match(src, k)
            k = close + 1 if close is not None else k + 1
            if close is None:
                break
        if src.tok(k) is None or src.tok(k).is_op("=", "{") or nxt is None:
            continue
        rd = _array_never_filled(src, s)
        if rd is None:
            continue
        out.append(_tip(src, "T008", "Array used before it gets values", "flow", rd.line, rd.col,
                        "`%s` (declared on line %d) is read on line %d, but no value is ever stored in it. A local "
                        "array starts with GARBAGE values (whatever was in that memory before), so the result is "
                        "random." % (s.name, s.line, rd.line),
                        why=["The loop that reads the values (scanf) or sets them was forgotten.",
                             "The array was meant to start with zeros: `int a[5];` is NOT zero - `int a[5] = {0};` is."],
                        fix=["Fill it first (e.g. with scanf in a loop), or start it with zeros: `%s %s%s = {0};`." % (
                            s.type, s.name, "".join("[%s]" % ("" if d is None else d) for d in s.array_sizes))],
                        example=("int a[5];\nfor (i = 0; i < 5; i++) sum += a[i];",
                                 "int a[5] = {0};   /* or read the values with scanf first */")))
    out.extend(_check_uninitialized_scalars(src, lang))
    return out


def _check_uninitialized_scalars(src, lang):
    out = []
    syms = src.symbols
    for s in syms.symbols:
        if s.kind != "var" or s.initialized or s.is_array or s.tok < 0:
            continue
        if syms.scopes[s.scope].kind in ("file", "struct", "class", "namespace"):
            continue
        base = s.type.replace("const ", "").replace("static ", "").strip()
        decl_line = src.line(s.line)
        if re.search(r"\bstatic\b", decl_line):
            continue
        if base not in PRIMITIVE and not s.pointer:
            continue
        scope = syms.scopes[s.scope]
        uses = [u for u in syms.uses if u.name == s.name and s.tok < u.tok <= scope.end and not u.is_member]
        uses = [u for u in uses if syms.lookup(u.name, u.tok) is s]
        if not uses:
            continue
        u = uses[0]
        if u.is_write and len(uses) > 1 and src.tok(u.tok + 1) is not None and src.tok(u.tok + 1).is_op("="):
            # sum = sum + a[i];  -> the right-hand side reads sum before it ever had a value
            stmt = {x.index for x in src.statement_tokens(src.tok(u.tok))}
            if uses[1].tok in stmt and not uses[1].is_write and not uses[1].address_taken:
                u = uses[1]
        if u.is_write or u.address_taken:
            continue
        nxt = src.tok(u.tok + 1)
        prev = src.tok(u.tok - 1)
        if prev is not None and (prev.is_kw("sizeof") or prev.is_op(">>")):
            continue                      # sizeof x  /  cin >> x  (input writes x)
        if lang in ("c++", "cpp") and _inside_call(src, u.tok):
            continue                      # may be passed by reference
        if nxt is not None and nxt.is_op("=") and prev is not None and prev.is_op("&"):
            continue
        # passed by value to scanf without & is reported by the compiler already
        line_txt = src.line(u.line)
        if re.search(r"\bscanf\s*\(", line_txt):
            continue
        fixed = re.sub(r"\b(%s)\b(\s*)(?=[,;])" % re.escape(s.name), r"\1 = 0\2", decl_line, count=1)
        if s.pointer:
            what = ("The pointer `%s` is used on line %d before it points to anything. An uninitialised pointer "
                    "holds a random address, so `*%s` reads/writes a random memory location (usually a crash)."
                    % (s.name, u.line, s.name))
            fix = ["Point it at a variable first (`%s = &x;`), allocate memory with malloc, or set it to NULL." % s.name]
            fixed = re.sub(r"\b(%s)\b(\s*)(?=[,;])" % re.escape(s.name), r"\1 = NULL\2", decl_line, count=1)
        else:
            what = ("`%s` is used on line %d before any value was stored in it. Local variables start with a "
                    "GARBAGE value (whatever was left in memory), not with 0." % (s.name, u.line))
            fix = ["Give it a starting value where it is declared: `%s %s = 0;`." % (base, s.name)]
        out.append(_tip(src, "T008", "Variable used before it gets a value", "flow", u.line, u.col, what,
                        fix=fix, fixed_line=fixed if fixed != decl_line else None, fixed_no=s.line,
                        hints=["`%s` is declared on line %d without a starting value." % (s.name, s.line)],
                        example=("int sum;\nfor (i = 1; i <= 10; i++)\n    sum += i;",
                                 "int sum = 0;\nfor (i = 1; i <= 10; i++)\n    sum += i;")))
    return out


# ------------------------------------------------------------------ T009
def check_nonascii(src, lang):
    out = []
    lines = {}
    for t in src.tokens:
        if t.kind == "nonascii":
            lines.setdefault(t.line, []).append(t)
    from .handlers.preproc_lex import HOMOGLYPHS
    for ln, toks in lines.items():
        line = src.line(ln)
        names = []
        for t in toks:
            desc = HOMOGLYPHS.get(t.text, (None, "the character %s (U+%04X)" % (t.text, ord(t.text))))[1]
            if desc not in names:
                names.append(desc)
        fixed = "".join(HOMOGLYPHS[c][0] if c in HOMOGLYPHS else c for c in line)
        out.append(_tip(src, "T009", "Special character copied into the code", "lexical", ln, toks[0].col,
                        "Line %d contains %s, which is not part of C/C++ code. This usually comes from copying "
                        "code out of a PDF, Word file or website." % (ln, ", ".join(names)),
                        fix=["Retype the characters with your keyboard."],
                        fixed_line=fixed if fixed != line else None))
    return out


# ------------------------------------------------------------------ T010 / T013
def check_io_traps(src, lang):
    out = []
    toks = src.tokens
    scanf_seen_in_func = {}
    for i, t in enumerate(toks):
        if t.kind != "id":
            continue
        nx = src.tok(i + 1)
        if nx is None or not nx.is_op("("):
            continue
        if t.text == "fflush":
            a = src.tok(i + 2)
            if a is not None and a.text == "stdin":
                out.append(_tip(src, "T010", "fflush(stdin) does not work everywhere", "semantic", t.line, t.col,
                                "`fflush(stdin)` is undefined in standard C: it worked in Turbo C / Windows, but on "
                                "Linux and macOS it does nothing, so leftover input (like the Enter key) stays.",
                                fix=["To skip a leftover newline before reading a char, use a space: `scanf(\" %c\", &ch);`",
                                     "Or clear the rest of the line: `while (getchar() != '\\n');`"]))
        if t.text == "scanf":
            fmt = src.tok(i + 2)
            if fmt is None or fmt.kind != "str":
                continue
            body = fmt.text[1:-1]
            func = src.enclosing_function(t.line) or ""
            if re.search(r"(\\n|\s)$", body) and "%" in body:
                line = src.line(fmt.line)
                new_body = re.sub(r"(?:\\n|\s)+$", "", body)
                out.append(_tip(src, "T013", "Space or \\n at the end of a scanf format", "semantic", fmt.line, fmt.col,
                                "`scanf(\"%s\", ...)` ends with white space. That tells scanf to keep reading until it "
                                "sees a NON-space character, so the program seems to hang after you press Enter." % body,
                                fix=["Remove the trailing `\\n` / space: `scanf(\"%s\", ...)`." % new_body],
                                fixed_line=line[:fmt.col] + new_body + line[fmt.col - 1 + len(fmt.text) - 1:]))
            elif re.match(r"^%c$", body) and scanf_seen_in_func.get(func):
                line = src.line(fmt.line)
                out.append(_tip(src, "T013", "scanf(\"%c\") right after another scanf", "semantic", fmt.line, fmt.col,
                                "The previous scanf left the Enter key (`\\n`) in the input. `%c` reads THAT newline "
                                "instead of waiting for your character.",
                                fix=["Put a space before %c: `scanf(\" %c\", &ch);` - the space skips white space."],
                                fixed_line=line[:fmt.col] + " %c" + line[fmt.col + 2:]))
            scanf_seen_in_func[func] = True
    return out


# ------------------------------------------------------------------ T011
def check_float_equality(src, lang):
    out = []
    for i, t in enumerate(src.tokens):
        if not t.is_op("==", "!="):
            continue
        l, r = src.tok(i - 1), src.tok(i + 1)
        if l is None or r is None:
            continue
        lit, var = (r, l) if r.kind == "float" else (l, r) if l.kind == "float" else (None, None)
        if lit is None or var.kind != "id":
            continue
        ty = _type_of(src, var)
        if ty not in FLOAT_TYPES:
            continue
        out.append(_tip(src, "T011", "Comparing decimal numbers with %s" % t.text, "semantic", t.line, t.col,
                        "Decimal numbers are stored only approximately (0.1 cannot be stored exactly), so `%s %s %s` "
                        "can be false even when you expect it to be true." % (var.text, t.text, lit.text),
                        fix=["Compare with a small tolerance: `fabs(%s - %s) < 1e-9` (needs <math.h>)." % (var.text, lit.text)]))
    return out


# ------------------------------------------------------------------ T012
def check_conio(src, lang):
    out = []
    for h, line, _ in src.includes():
        if h.lower() in ("conio.h", "graphics.h", "dos.h"):
            out.append(_tip(src, "T012", "Non-standard header <%s>" % h, "preprocessor", line, 1,
                            "`<%s>` only exists in old Turbo C / some Windows compilers. Your program will not "
                            "compile with GCC/Clang on Linux or macOS, or on most online judges." % h,
                            fix=["Use only standard headers; replace getch() with getchar() and remove clrscr()."]))
    return out


# ------------------------------------------------------------------ T015
END_OF_STATEMENT = ("id", "int", "float", "str", "char")
CONTROL = ("if", "for", "while", "switch", "else", "do")


def check_missing_semicolons(src, lang):
    """Lines that end a statement without `;` which the compiler has not reported (yet).

    After the first syntax/semantic error GCC/Clang often skip the rest of a statement or
    block, so a second or third forgotten `;` only shows up after the first fix.  A line is
    reported when its last token can end a statement, the next line starts a new statement,
    and we are not inside ( ) / [ ] or an initializer / enum list { }.
    """
    out = []
    toks = src.tokens
    paren = 0
    braces = []                 # "block" or "init"
    info = []                   # (paren depth, innermost brace kind) after each token
    for i, t in enumerate(toks):
        if t.is_op("(", "["):
            paren += 1
        elif t.is_op(")", "]"):
            paren = max(0, paren - 1)
        elif t.is_op("{"):
            p = src.tok(i - 1)
            near = [src.tok(i - k) for k in (1, 2, 3)]
            init = (p is not None and (p.is_op("=", ",", "{", "(") or p.is_kw("return"))) or \
                any(x is not None and x.is_kw("enum") for x in near)
            braces.append("init" if init else "block")
        elif t.is_op("}"):
            if braces:
                braces.pop()
        info.append((paren, braces[-1] if braces else "top"))
    for i, t in enumerate(toks[:-1]):
        n = toks[i + 1]
        if n.line == t.line or t.kind == "pp" or n.kind == "pp":
            continue
        if not (t.kind in END_OF_STATEMENT or t.is_op(")", "]", "++", "--")):
            continue
        if not (n.kind == "id" or (n.kind == "kw" and n.text != "else") or n.is_op("}")):
            continue
        depth, kind = info[i]
        if depth != 0 or kind == "init":
            continue
        # first token of this statement: start of the line, or of an earlier line when this
        # line continues it (previous line ended with an operator, a comma or an open bracket)
        k = src.first_token_on_line(t.line).index
        while k > 0 and (info[k - 1][0] > 0 or (toks[k - 1].kind == "op"
                                                 and not toks[k - 1].is_op(";", "{", "}", ")", "]", "++", "--"))):
            k = src.first_token_on_line(toks[k - 1].line).index
        start = toks[k]
        if start.text.lower() in CONTROL or start.kind == "pp" or (start.is_op("}") and src.tok(k + 1) is not None
                                                                   and src.tok(k + 1).is_kw("while")):
            continue
        if kind == "top" and t.is_op(")"):
            continue            # function header: a missing { or ; there is reported by the compiler
        line = src.line(t.line)
        end = t.col - 1 + len(t.text)
        if t.end_line and t.end_line != t.line:
            continue
        e = _tip(src, "T015", "Missing semicolon", "syntax", t.line, end + 1,
                 "Line %d (`%s`) does not end with `;`. The compiler has not complained about it YET - after an "
                 "earlier error it skipped this part - but it will as soon as the other problems are fixed."
                 % (t.line, line.strip()),
                 why=["The `;` at the end of the line was forgotten."],
                 fix=["Add `;` at the end of line %d." % t.line],
                 fixed_line=line[:end] + ";" + line[end:])
        e.level = "error"
        e.compiler_message = "(not reported by the compiler yet - found by CEDT's own check)"
        out.append(e)
    return out


# ------------------------------------------------------------------ T014
def check_loop_direction(src, lang):
    out = []
    for t in src.tokens:
        if not t.is_kw("for"):
            continue
        info = _for_clauses(src, t)
        if info is None:
            continue
        (init, cond, upd), _, _ = info
        if len(cond) < 3 or cond[0].kind != "id" or not cond[1].is_op("<", "<=", ">", ">="):
            continue
        var = cond[0].text
        u = " ".join(x.text for x in upd)
        up = re.search(r"(?:\b%s\s*\+\+|\+\+\s*%s\b|\b%s\s*\+=)" % ((re.escape(var),) * 3), u)
        down = re.search(r"(?:\b%s\s*--|--\s*%s\b|\b%s\s*-=)" % ((re.escape(var),) * 3), u)
        wrong = (cond[1].text in ("<", "<=") and down) or (cond[1].text in (">", ">=") and up)
        if not wrong:
            continue
        out.append(_tip(src, "T014", "Loop counter moves the wrong way", "flow", t.line, t.col,
                        "The loop runs while `%s %s ...` but `%s` is changed with `%s`, which moves it AWAY from the "
                        "limit. The loop never ends (or ends only when the number wraps around)." % (
                            var, cond[1].text, var, u.strip()),
                        fix=["Use `%s++` with `<`/`<=`, or `%s--` with `>`/`>=`." % (var, var)]))
    return out


CHECKS = [check_empty_body, check_int_division, check_define_semicolon, check_const_index, check_off_by_one,
          check_xor_power, check_fallthrough, check_uninitialized, check_nonascii, check_io_traps,
          check_float_equality, check_conio, check_loop_direction, check_missing_semicolons]

# compiler rules that already cover a precheck
COVERED_BY = {
    "T001": {"W011", "W012", "S005", "M026"},
    "T003": {"P005"},
    "T004": {"W015"},
    "T005": {"W015"},
    "T007": {"W016"},
    "T008": {"W002"},
    "T009": {"L001"},
    "T011": {"W025"},
    "T012": {"P001"},
    "T015": {"S001", "S008", "S007", "S013", "S014"},
}


def run(src, lang, exps, kb=None):
    if src is None:
        return []
    lines_any = {}
    for e in exps:
        for ln in (e.location.line if e.location else None, e.real_line, e.fixed_line_no):
            if ln:
                lines_any.setdefault(ln, set()).add(e.rule_id)
    has_errors = any(e.level == "error" for e in exps)
    tips = []
    for check in CHECKS:
        try:
            found = check(src, lang)
        except Exception:          # a check must never break the explanation of real errors
            continue
        for t in found:
            ln = t.location.line
            near = lines_any.get(ln, set()) | lines_any.get(t.fixed_line_no or -1, set())
            if near & COVERED_BY.get(t.rule_id, set()):
                continue
            if near and t.rule_id not in ("T002", "T006", "T011", "T014", "T015"):
                continue
            if t.rule_id == "T015" and not has_errors:
                continue
            if t.rule_id == "T012" and has_errors:
                continue
            tips.append(t)
    return tips
