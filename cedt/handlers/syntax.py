"""Handlers for syntax-analysis (parser) rules."""
import re

from .. import brackets as B
from ..source_lexer import C_KEYWORDS, CPP_KEYWORDS
from ..symbols import C_TYPEDEFS, CPP_TYPES, TYPE_KEYWORDS
from ..textutil import closest
from .base import Result, code, handler, insert_at, replace_word, text_of, veto

STATEMENT_KEYWORDS = {"return", "if", "for", "while", "do", "switch", "break", "continue", "goto", "else"}


def _end_index(tok):
    return tok.col - 1 + len(tok.text) if tok.line == tok.end_line else None


def _semicolon_fix(src, prev):
    line = src.line(prev.end_line)
    idx = _end_index(prev)
    if idx is None:
        idx = len(line.rstrip())
    return insert_at(line, idx, ";")


def _is_virtual(ctx):
    return ctx.src is not None and ctx.src.path in ctx.files and ctx.src is ctx.files.get(ctx.src.path) \
        and not any(f is ctx.src for k, f in ctx.files.items() if k != ctx.src.path)


def _missing_semicolon(ctx):
    msg = ctx.diag.message
    after = ctx.groups.get("after", "")
    before = ctx.groups.get("before", "")
    if after in ("struct", "class", "union", "enum"):
        return Result(redirect="S007", vars={"kind": after})
    if after == "namespace name":
        r = Result(title="Missing ; after using namespace std",
                   what="`using namespace std` is a statement, so it must end with a semicolon.")
        r.vars["real_line"] = ctx.line_no
        r.fixed_line = (ctx.line_text() or "").rstrip() + ";"
        return r
    src = ctx.src
    r = Result()
    if src is None:
        r.vars["real_line"] = "%s (or the line before it)" % ctx.line_no
        r.hints.append("If line %s looks correct, check the END of the previous line." % ctx.line_no)
        return r
    tok = ctx.tok
    if tok is None:
        r.vars["real_line"] = ctx.line_no
        return r
    if tok.kind in ("unknown", "nonascii"):
        return Result(redirect="L001", vars={"char": tok.text})
    if "','" in msg and "')'" in msg:
        # expected ';', ',' or ')' before ...  -> usually a missing comma in a parameter list
        prev = ctx.prev(tok)
        depth_paren = 0
        k = tok.index - 1
        while k >= 0 and not src.tokens[k].is_op(";", "{", "}"):
            if src.tokens[k].is_op(")"):
                depth_paren -= 1
            elif src.tokens[k].is_op("("):
                depth_paren += 1
            k -= 1
        if depth_paren > 0 and prev is not None:
            r.title = "Missing comma between parameters"
            r.what = "Inside the brackets, parameters/arguments must be separated by commas."
            r.fix = ["Put a `,` between `%s` and `%s`." % (prev.text, tok.text)]
            r.vars["real_line"] = tok.line
            r.fixed_line = insert_at(src.line(prev.end_line), _end_index(prev) or 0, ",")
            r.real_line = prev.end_line
            return r
    if after:
        idx = ctx.col_index() or 0
        line = src.line(ctx.line_no)
        prev = None
        for t in src.tokens_on_line(ctx.line_no):
            if t.col - 1 < idx:
                prev = t
        r.vars["real_line"] = ctx.line_no
        r.real_line = ctx.line_no
        r.fixed_line = insert_at(line, idx, ";")
        if prev is not None and prev.kind in ("unknown", "nonascii"):
            return Result(redirect="L001", vars={"char": prev.text})
        nxt_on_line = [t for t in src.tokens_on_line(ctx.line_no) if t.col - 1 >= idx]
        if nxt_on_line and nxt_on_line[0].kind in ("unknown",):
            return Result(redirect="L001", vars={"char": nxt_on_line[0].text})
        return r
    prev = ctx.prev(tok)
    if prev is None:
        r.vars["real_line"] = ctx.line_no
        return r
    if prev.is_op(";", "{", "}"):
        open_parens = [i for i in src.brackets.unclosed if src.tokens[i].is_op("(") and i < tok.index]
        if open_parens:
            return Result(redirect="S004")
        r.vars["real_line"] = ctx.line_no
        r.what = ("The parser asked for a `;` here although the previous statement already ends with one - it is "
                  "still confused by an earlier error. Fix the errors above first.")
        r.no_fix = True
        r.confidence = "low"
        return r
    real = prev.end_line
    r.vars["real_line"] = real
    r.real_line = real
    r.fixed_line = _semicolon_fix(src, prev)
    r.fixed_line_no = real
    stmt_line = src.line(real).strip()
    if real != tok.line:
        r.what = ("Line %d (`%s`) does not end with a semicolon. The compiler only noticed the problem when it "
                  "reached `%s` on line %d, so it reported line %d." % (real, stmt_line, tok.text, tok.line, tok.line))
    elif tok.is_op("}"):
        r.what = "The last statement before the `}` on line %d is missing its semicolon." % tok.line
    else:
        r.what = "Something is missing between `%s` and `%s` on line %d - most likely a `;`." % (
            prev.text, tok.text, tok.line)
    if re.match(r"^\s*using\s+namespace\s+\w+\s*$", src.line(real)):
        r.title = "Missing ; after using namespace std"
    return r


@handler("brace_eof")
def brace_eof(ctx):
    src = ctx.src
    if src is None:
        return Result(vars={"real_line": ctx.line_no})
    rep = src.brackets
    g = B.guess_missing_close(src.tokens, src.lines, rep)
    if g is None:
        if ctx.diag.message.startswith("expected '}' before"):
            return Result(vars={"real_line": ctx.line_no},
                          what="A `}` is missing before %s on line %s." % (ctx.groups.get("before", "this point"), ctx.line_no))
        return veto()
    opener = src.tokens[g]
    desc = B.describe_opener(src.tokens, g, src.lines)
    r = Result(vars={"open_line": opener.line, "desc": desc, "real_line": opener.line})
    r.real_line = opener.line
    r.what = ("The `{` on line %d that opens %s is never closed with a matching `}`. The compiler only noticed when "
              "it reached the end of the file." % (opener.line, desc))
    indent = re.match(r"\s*", src.line(opener.line)).group(0)
    insert_line = None
    if g in rep.suspicious_open and g in rep.match:
        closer = src.tokens[rep.match[g]]
        insert_line = closer.line
        r.hints.append("The `}` on line %d is indented like the OUTER block, so it probably belongs to that block - "
                       "the `}` for line %d is missing just before it." % (closer.line, opener.line))
    else:
        base = B.indent_width(src.line(opener.line))
        for n in range(opener.line + 1, len(src.lines) + 1):
            text = src.line(n)
            if text.strip() and B.indent_width(text) <= base and not text.strip().startswith("}"):
                insert_line = n
                break
        if insert_line is None:
            insert_line = len(src.lines) + 1
    r.fix = ["Add `}` to close %s - just before line %d." % (desc, insert_line)]
    r.fixed_line = indent + "}"
    r.fixed_line_no = insert_line
    r.fixed_kind = "insert_before"
    return r


@handler("extra_brace")
def extra_brace(ctx):
    src = ctx.src
    if src is None:
        return Result(vars={"real_line": ctx.line_no})
    rep = src.brackets
    g = B.guess_extra_close(src.tokens, src.lines, rep)
    if g is None:
        return veto()
    closer = src.tokens[g]
    r = Result(vars={"real_line": closer.line})
    r.real_line = closer.line
    if g in rep.match:
        opener = rep.match[g]
        desc = B.describe_opener(src.tokens, opener, src.lines)
        r.what = ("The `}` on line %d closes %s (opened on line %d) too early. Everything after it is now outside "
                  "the function, so the compiler complains about the next lines." % (
                      closer.line, desc, src.tokens[opener].line))
    else:
        r.what = "The `}` on line %d has no matching `{`." % closer.line
    r.fixed_line = ""
    r.fixed_line_no = closer.line
    r.fixed_kind = "delete"
    return r


@handler("array_parens")
def array_parens(ctx):
    line = ctx.line_text() or ""
    m = re.search(r"\b((?:unsigned\s+|long\s+)*(?:int|float|double|char|long|short))\s+([A-Za-z_]\w*)\s*\(\s*(\d+|[A-Z_][A-Z0-9_]*)\s*\)", line)
    if not m:
        return veto()
    r = Result()
    r.what = ("`%s %s(%s)` on line %s uses round brackets. Array sizes go in SQUARE brackets: `%s %s[%s]`. "
              "(With `( )` the compiler thinks you are declaring a function.)" % (
                  m.group(1), m.group(2), m.group(3), ctx.line_no, m.group(1), m.group(2), m.group(3)))
    r.fixed_line = line[:m.start()] + "%s %s[%s]" % (m.group(1), m.group(2), m.group(3)) + line[m.end():]
    return r


@handler("missing_paren")
def missing_paren(ctx):
    src = ctx.src
    r = Result(vars={"before": ctx.groups.get("before", "this point")})
    if src is None:
        return r
    # printf("%d" x)  -> the comma between the arguments is missing
    t = ctx.tok
    pv = ctx.prev(t) if t is not None else None
    if t is not None and pv is not None and t.kind in ("id", "int", "float", "str", "char") \
            and (pv.kind in ("str", "id", "int", "float", "char") or pv.is_op(")", "]")) and pv.line == t.line:
        line = src.line(t.line)
        r.title = "Missing comma between values"
        r.what = ("On line %d there is no comma between `%s` and `%s`. The values given to a function must be "
                  "separated by commas." % (t.line, pv.text, t.text))
        r.fix = ["Put a `,` between them: `%s, %s`." % (pv.text, t.text)]
        r.why = ["The comma after the format string (or between two values) was forgotten."]
        end = pv.col - 1 + len(pv.text)
        r.fixed_line = line[:end] + ("," if line[end:end + 1] == " " else ", ") + line[end:]
        r.fixed_line_no = t.line
        r.example = {"wrong": "printf(\"%d\" x);", "right": "printf(\"%d\", x);"}
        return r
    rep = src.brackets
    line_no = ctx.line_no
    cands = [i for i in rep.unclosed if src.tokens[i].is_op("(") and src.tokens[i].line <= line_no]
    if not cands and ctx.tok is not None:
        stmt = src.statement_tokens(ctx.tok)
        opens = [t for t in stmt if t.is_op("(")]
        closes = [t for t in stmt if t.is_op(")")]
        if len(opens) > len(closes) and opens:
            cands = [opens[0].index]
    if cands:
        o = src.tokens[cands[-1]]
        head = src.prev_token(o)
        what_for = ""
        if head is not None and head.kind == "kw" and head.text in ("if", "while", "for", "switch"):
            what_for = " (the condition of `%s`)" % head.text
        elif head is not None and head.kind == "id":
            what_for = " (the call to `%s`)" % head.text
        r.what = "The `(` at column %d of line %d%s is never closed with `)`." % (o.col, o.line, what_for)
        r.real_line = o.line
    if not cands:
        r.what = ("The parser expected a `)` here, but the brackets on line %s look balanced - this message is "
                  "probably a side effect of an earlier error on or before this line." % line_no)
        r.no_fix = True
        r.confidence = "low"
        return r
    if not (ctx.diag.extra.get("snippet_info") or {}).get("fixit") and line_no:
        line = src.line(line_no)
        idx = ctx.col_index()
        if idx is not None:
            if idx > 0 and idx <= len(line) and line[idx - 1:idx] == " ":
                r.fixed_line = insert_at(line, idx - 1, ")")
            else:
                r.fixed_line = insert_at(line, idx, ")")
            r.fixed_line_no = line_no
    return r


@handler("else_without_if")
def else_without_if(ctx):
    src = ctx.src
    r = Result()
    if src is None or ctx.tok is None:
        return r
    else_tok = ctx.tok
    if not else_tok.is_kw("else"):
        for t in src.tokens_on_line(ctx.line_no):
            if t.is_kw("else"):
                else_tok = t
                break
    depth = src.brace_depth_at(else_tok)
    k = else_tok.index - 1
    if_tok = None
    while k >= 0:
        t = src.tokens[k]
        if t.is_kw("if") and src.brace_depth_at(t) == depth:
            if_tok = t
            break
        k -= 1
    if if_tok is None:
        # if (...) {  ...  else {   -> the } of the if-block is missing, so else is INSIDE it
        k, d = else_tok.index - 1, 0
        while k >= 0:
            t = src.tokens[k]
            if t.is_op("}"):
                d += 1
            elif t.is_op("{"):
                if d == 0:
                    break
                d -= 1
            k -= 1
        brace = src.tok(k) if k >= 0 else None
        head = src.tok(k - 1) if brace is not None else None
        open_p = src.tok(src.brackets.match.get(head.index)) if head is not None and head.is_op(")") \
            and src.brackets.match.get(head.index) is not None else None
        outer_if = src.prev_token(open_p) if open_p is not None else None
        if outer_if is not None and outer_if.is_kw("if"):
            r.title = "Missing } before else"
            r.what = ("The `{` of the if-block on line %d is not closed before the `else` on line %d, so the `else` "
                      "ends up INSIDE the if-block - where there is no if for it to belong to." % (
                          brace.line, else_tok.line))
            r.fix = ["Close the if-block with `}` just before `else`: `} else {`."]
            r.why = ["The `}` of the if-part was forgotten. With correct indentation, `}` and `else` line up "
                     "under the `if`."]
            line = src.line(else_tok.line)
            r.fixed_line = line[:else_tok.col - 1] + "} " + line[else_tok.col - 1:]
            r.fixed_line_no = else_tok.line
            r.real_line = else_tok.line
            r.example = {"wrong": "if (x > 0) {\n    pos++;\nelse {\n    neg++;\n}",
                         "right": "if (x > 0) {\n    pos++;\n} else {\n    neg++;\n}"}
            return r
        r.what = "There is no `if` before this `else` in the same block."
        return r
    open_p = src.next_token(if_tok)
    close = src.brackets.match.get(open_p.index) if open_p is not None else None
    if close is not None:
        after = src.tok(close + 1)
        if after is not None and after.is_op(";"):
            r.title = "Semicolon right after if (...)"
            r.what = ("The `;` right after `if (...)` on line %d ends the if-statement immediately (it becomes an "
                      "empty if). The block after it always runs, and the `else` on line %d is left without an if."
                      % (after.line, else_tok.line))
            r.real_line = after.line
            line = src.line(after.line)
            r.fixed_line = line[:after.col - 1].rstrip() + line[after.col:]
            r.fixed_line_no = after.line
            r.fix = ["Remove the `;` after `if (...)` on line %d." % after.line]
            return r
        body = src.tok(close + 1)
        if body is not None and not body.is_op("{"):
            # count statements between the end of the first statement and else
            k = close + 1
            d = 0
            first_end = None
            while k < else_tok.index:
                t = src.tokens[k]
                if t.is_op("(", "[", "{"):
                    d += 1
                elif t.is_op(")", "]", "}"):
                    d -= 1
                elif t.is_op(";") and d == 0:
                    first_end = k
                    break
                k += 1
            if first_end is not None and first_end + 1 < else_tok.index:
                r.title = "if with several statements but no braces"
                r.what = ("Without `{ }`, only ONE statement belongs to the `if` on line %d. The next statement "
                          "(line %d) ends the if, so the `else` on line %d has no if any more." % (
                              if_tok.line, src.tokens[first_end + 1].line, else_tok.line))
                r.real_line = if_tok.line
                r.fix = ["Wrap the statements of the if-part in braces: `if (...) { ...; ...; } else ...`"]
    return r


def _for_parts(src, line_no):
    for t in src.tokens_on_line(line_no):
        if t.is_kw("for"):
            op = src.next_token(t)
            if op is None or not op.is_op("("):
                continue
            close = src.brackets.match.get(op.index)
            end = close if close is not None else len(src.tokens)
            inner = src.tokens[op.index + 1:end]
            return t, op, inner
    return None


@handler("for_commas")
def for_commas(ctx):
    src = ctx.src
    if src is None or not ctx.line_no:
        line = ctx.line_text() or ""
        if re.search(r"\bfor\s*\([^;]*,[^;]*,[^;]*\)", line):
            return Result(fixed_line=re.sub(r"\bfor\s*\(([^,;]*),([^,;]*),", r"for (\1;\2;", line, count=1))
        return veto()
    found = _for_parts(src, ctx.line_no)
    if found is None:
        return veto()
    for_tok, op, inner = found
    depth = 0
    semis, commas = [], []
    for t in inner:
        if t.is_op("(", "[", "{"):
            depth += 1
        elif t.is_op(")", "]", "}"):
            depth -= 1
        elif depth == 0 and t.is_op(";"):
            semis.append(t)
        elif depth == 0 and t.is_op(","):
            commas.append(t)
    if len(semis) == 1 and not commas:
        # for (int i = 0; i < 5)  -> the update part is missing
        r = Result(title="for loop with only two parts")
        r.what = ("A `for` loop needs THREE parts separated by two semicolons: `for (start; condition; update)`. "
                  "The loop on line %d has only two parts - the update (e.g. `i++`) is missing." % for_tok.line)
        r.fix = ["Add the update part: `for (int i = 0; i < 5; i++)`.",
                 "If you really want no update, still write both semicolons: `for (i = 0; i < 5; )`."]
        r.why = ["The `i++` part was forgotten, or written inside the loop body instead."]
        last = inner[-1] if inner else None
        if last is not None and last.line == for_tok.line:
            line = src.line(for_tok.line)
            cond = [t for t in inner if t.pos > semis[0].pos]
            var = next((t.text for t in cond if t.kind == "id"), None)
            if var:
                end = last.col - 1 + len(last.text)
                r.fixed_line = line[:end] + "; %s++" % var + line[end:]
        r.real_line = for_tok.line
        r.example = {"wrong": "for (int i = 0; i < 5)", "right": "for (int i = 0; i < 5; i++)"}
        return r
    if len(semis) >= 2 or not commas:
        return veto()
    need = 2 - len(semis)
    if semis:
        cands = [c for c in commas if c.pos > semis[-1].pos]
    else:
        cands = commas
    if len(cands) < need:
        return veto()
    replace = cands[:need] if not semis else cands[-need:]
    line = src.line(for_tok.line)
    chars = list(line)
    for c in replace:
        if c.line == for_tok.line:
            chars[c.col - 1] = ";"
    r = Result()
    r.fixed_line = "".join(chars)
    r.real_line = for_tok.line
    return r


def _struct_before(src, tok):
    """If the token before tok is the '}' of a struct/class/union/enum, return (kind, name, close_tok)."""
    prev = src.prev_token(tok)
    if prev is None or not prev.is_op("}"):
        return None
    open_i = src.brackets.match.get(prev.index)
    if open_i is None:
        return None
    k = open_i - 1
    name = ""
    t = src.tok(k)
    if t is not None and t.kind == "id":
        name = t.text
        k -= 1
        t = src.tok(k)
    # skip C++ base-class list  class A : public B {
    while t is not None and not (t.kind == "kw" and t.text in ("struct", "class", "union", "enum")) \
            and not t.is_op(";", "}", "{") and k > open_i - 12:
        k -= 1
        t = src.tok(k)
        if t is not None and t.kind == "id" and not name:
            name = t.text
    if t is not None and t.kind == "kw" and t.text in ("struct", "class", "union", "enum"):
        return t.text, name, prev
    return None


@handler("struct_semicolon")
def struct_semicolon(ctx):
    src = ctx.src
    m = re.match(r"^expected ';' after (struct|class|union|enum)", ctx.diag.message)
    if m:
        r = Result(vars={"kind": m.group(1), "real_line": ctx.line_no})
        line = ctx.line_text() or ""
        idx = ctx.col_index()
        if idx is not None:
            r.fixed_line = insert_at(line, idx, ";")
        return r
    if src is None or ctx.tok is None:
        return veto()
    info = _struct_before(src, ctx.tok)
    if info is None:
        # GCC sometimes points one token later (e.g. at 'main' in 'int main')
        p = ctx.prev()
        info = _struct_before(src, p) if p is not None else None
        if info is None:
            return veto()
    kind, name, close_tok = info
    r = Result(vars={"kind": kind, "name": name, "real_line": close_tok.line})
    r.real_line = close_tok.line
    line = src.line(close_tok.line)
    r.fixed_line = insert_at(line, close_tok.col, ";")
    r.fixed_line_no = close_tok.line
    if name:
        r.what = ("The definition of `%s %s` must end with `};` - the semicolon after its closing brace on line %d is "
                  "missing, so the compiler thinks the next declaration belongs to it." % (kind, name, close_tok.line))
    return r


@handler("semicolon_after_header")
def semicolon_after_header(ctx):
    src = ctx.src
    if src is None or ctx.tok is None:
        return veto()
    tok = ctx.tok
    if not tok.is_op("{"):
        # clang points at '{' too; GCC "before '{' token"
        cand = [t for t in src.tokens_on_line(ctx.line_no) if t.is_op("{")]
        if not cand:
            return veto()
        tok = cand[0]
    semi = src.prev_token(tok)
    rpar = src.prev_token(semi) if semi is not None else None
    if semi is None or not semi.is_op(";") or rpar is None or not rpar.is_op(")"):
        return veto()
    r = Result(vars={"real_line": semi.line})
    r.real_line = semi.line
    line = src.line(semi.line)
    r.fixed_line = line[:semi.col - 1].rstrip() + line[semi.col:]
    r.fixed_line_no = semi.line
    return r


def _looks_like_code(src, first):
    if first is None:
        return False
    nxt = src.next_token(first)
    if first.kind == "kw" and first.text in STATEMENT_KEYWORDS:
        return True
    if first.kind == "id" and nxt is not None:
        if nxt.is_op("("):
            # a call - unless it is a function header followed by { or ;
            close = src.brackets.match.get(nxt.index)
            after = src.tok(close + 1) if close is not None else None
            if after is not None and after.is_op("{"):
                return False
            before = src.prev_token(first)
            if before is not None and before.kind in ("kw", "id") and not before.is_op(";"):
                return False
            return True
        if nxt.is_op("=", "<<", ">>", "++", "--", "+=", "-=", "*=", "/=", ".", "->", "["):
            return True
    return False


@handler("code_outside_function")
def code_outside_function(ctx):
    src = ctx.src
    if src is None or ctx.tok is None:
        return veto()
    tok = ctx.tok
    if src.brace_depth_at(tok) != 0:
        return veto()
    stmt = src.statement_tokens(tok)
    first = stmt[0] if stmt else tok
    if first.kind == "pp":
        return veto()
    if not _looks_like_code(src, first):
        return veto()
    r = Result(vars={"real_line": first.line}, no_fix=True)
    r.vars["line"] = first.line
    rep = src.brackets
    g = B.guess_extra_close(src.tokens, src.lines, rep)
    if g is not None and src.tokens[g].line < first.line:
        closer = src.tokens[g]
        r.title = "Extra } closed the function too early"
        r.what = ("Line %d is outside of every function because the `}` on line %d closed the function early. "
                  "That brace is extra." % (first.line, closer.line))
        r.real_line = closer.line
        r.fix = ["Delete the extra `}` on line %d." % closer.line]
        r.fixed_line = ""
        r.fixed_line_no = closer.line
        r.fixed_kind = "delete"
        return r
    # statement written above main?
    funcs = [s for s in src.symbols.scopes if s.kind == "function"]
    if funcs:
        target = funcs[0]
        for s in funcs:
            if s.name == "main":
                target = s
        r.fix = ["Move line %d inside `%s()`, between its `{` and `}` (lines %d-%d)." % (
            first.line, target.name, target.start_line, target.end_line)]
    return r


TYPE_WORDS = sorted(TYPE_KEYWORDS | {"struct", "union", "enum", "const", "static"})


@handler("unknown_type_or_semicolon")
def unknown_type_or_semicolon(ctx):
    src = ctx.src
    if src is None or ctx.tok is None:
        return Result()
    tok = ctx.tok
    prev = ctx.prev(tok)
    if prev is None:
        return Result()
    pp = src.prev_token(prev)
    starts_stmt = pp is None or pp.is_op(";", "{", "}") or pp.kind == "pp"
    if prev.kind == "id" and starts_stmt and prev.line == tok.line:
        return Result(redirect="M004", vars={"name": prev.text, "tname_line": prev.line})
    if prev.end_line < tok.line:
        return Result(redirect="S001")
    return Result()


@handler("expected_expression")
def expected_expression(ctx):
    src = ctx.src
    before = ctx.groups.get("before", "")
    r = Result(vars={"before": before or "something else"})
    if src is None or ctx.tok is None:
        return r
    tok = ctx.tok
    if tok.is_kw("else"):
        return Result(redirect="S005")
    prev = ctx.prev(tok)
    line = src.line(tok.line)
    if not before:
        r.vars["before"] = code(tok.text)
    if tok.is_op("[") and prev is not None and prev.is_op("="):
        close = src.brackets.match.get(tok.index)
        r.title = "Array values written in [ ] instead of { }"
        r.what = ("The starting values of an array go inside CURLY braces `{ }`, not square brackets. Square "
                  "brackets are only for the size (`int a[5]`) and for one element (`a[0]`).")
        r.fix = ["Write `= {1, 2, 3}` instead of `= [1, 2, 3]`."]
        r.why = ["Python / JavaScript style lists `[1, 2, 3]` - C uses `{1, 2, 3}`."]
        if close is not None and src.tokens[close].line == tok.line:
            c = src.tokens[close]
            r.fixed_line = line[:tok.col - 1] + "{" + line[tok.col:c.col - 1] + "}" + line[c.col:]
        r.example = {"wrong": "int a[5] = [1, 2, 3, 4, 5];", "right": "int a[5] = {1, 2, 3, 4, 5};"}
        return r
    if tok.is_op("]") and prev is not None and prev.is_op("[") and src.prev_token(prev) is not None \
            and src.prev_token(prev).kind == "id":
        name = src.prev_token(prev).text
        r.title = "Empty [ ] when using an array"
        r.what = ("`%s[]` with empty brackets is only allowed when DECLARING an array or parameter. To pass the "
                  "whole array to a function, write just its name `%s`; to use one element write `%s[i]`." % (
                      name, name, name))
        r.fix = ["Write `%s` (whole array) or `%s[0]` (one element)." % (name, name)]
        r.why = ["Copying the parameter style `int a[]` into the call - a call passes only the name."]
        r.fixed_line = line[:prev.col - 1] + line[tok.col:]
        r.example = {"wrong": "total = sum(a[], 5);", "right": "total = sum(a, 5);"}
        return r
    if tok.kind == "kw" and tok.text in TYPE_KEYWORDS and ctx.nxt(tok) is not None and ctx.nxt(tok).is_op("(") \
            and not ctx.cpp and (prev is None or not prev.is_op("(")):
        op = ctx.nxt(tok)
        close = src.brackets.match.get(op.index)
        r.title = "C++ style cast in a C program"
        r.what = ("`%s(...)` is the C++ way to convert a value. In C the type goes in brackets BEFORE the value: "
                  "`(%s)value`." % (tok.text, tok.text))
        r.fix = ["Write `(%s)x` instead of `%s(x)`." % (tok.text, tok.text)]
        r.why = ["`int(x)` works in C++ (and Python), but C only knows the `(int)x` form."]
        if close is not None and src.tokens[close].line == tok.line:
            inner = line[op.col:src.tokens[close].col - 1]
            r.fixed_line = line[:tok.col - 1] + "(%s)%s" % (tok.text, inner.strip() if re.fullmatch(r"\s*\w+\s*", inner)
                                                             else "(%s)" % inner) + line[src.tokens[close].col:]
        r.example = {"wrong": "int x = int(f);", "right": "int x = (int)f;"}
        return r
    if tok.kind == "kw" and tok.text in TYPE_KEYWORDS and prev is not None and prev.is_op("(") \
            and ctx.nxt(tok) is not None and ctx.nxt(tok).kind == "id":
        nx = ctx.nxt(tok)
        after = ctx.nxt(nx)
        if after is not None and after.is_op(")") and src.prev_token(prev) is not None \
                and src.prev_token(prev).is_op("=", "(", ","):
            r.title = "Cast written without its own brackets"
            r.what = ("To convert a value, the TYPE alone goes in brackets and the value comes after it: "
                      "`(%s)%s`, not `(%s %s)`." % (tok.text, nx.text, tok.text, nx.text))
            r.fix = ["Write `(%s)%s`." % (tok.text, nx.text)]
            r.why = ["Type and value both put inside the brackets."]
            r.fixed_line = line[:prev.col - 1] + "(%s)%s" % (tok.text, nx.text) + line[after.col:]
            r.example = {"wrong": "int y = (int f);", "right": "int y = (int)f;"}
            return r
    if tok.is_op(")"):
        if prev is not None and prev.is_op("("):
            r.title = "Empty brackets where a value is needed"
            head = src.prev_token(prev)
            r.what = "The brackets `()` after `%s` are empty, but a value or condition is required inside them." % (
                head.text if head is not None else "")
        elif prev is not None and prev.is_op(","):
            r.title = "Missing value after a comma"
            r.what = "There is a comma `,` with nothing after it before `)` on line %d." % tok.line
            r.fixed_line = line[:prev.col - 1] + line[prev.col:]
        elif prev is not None and prev.kind == "op":
            r.what = "The operator `%s` has nothing on its right side before `)`." % prev.text
    elif tok.is_op(";", "}"):
        if prev is not None and prev.is_op("="):
            r.title = "Nothing after ="
            r.what = "Line %d has `=` but no value after it. Give the variable a value." % tok.line
            r.fixed_line = insert_at(line, tok.col - 1, "0") if tok.line == prev.line else None
        elif prev is not None and prev.kind == "op" and prev.text not in (")", "]", "++", "--", ";", "{", "}"):
            r.what = "The operator `%s` on line %d has nothing on its right side." % (prev.text, prev.line)
    elif tok.kind == "kw" and tok.text in TYPE_KEYWORDS:
        call = None
        k = tok.index - 1
        depth = 0
        while k >= 0:
            t = src.tokens[k]
            if t.is_op(")"):
                depth += 1
            elif t.is_op("("):
                if depth == 0:
                    call = src.tok(k - 1)
                    break
                depth -= 1
            elif t.is_op(";", "{", "}"):
                break
            k -= 1
        if call is not None and call.kind == "id":
            r.title = "Type name written inside a function call"
            r.what = ("When you CALL a function you pass only values, not types. `%s(...)` on line %d contains the "
                      "type `%s`." % (call.text, tok.line, tok.text))
            r.fix = ["Remove the type names from the call: write `%s(a, b)`, not `%s(int a, int b)`." % (call.text, call.text)]
            fixed = re.sub(r"\b(?:unsigned\s+|signed\s+|long\s+|short\s+|const\s+)*(?:int|char|float|double|long|short|void|bool)\s*\*?\s*(?=[A-Za-z_])", "", line)
            if fixed != line:
                r.fixed_line = fixed
        else:
            r.what = "A type name `%s` appears where a value was expected on line %d." % (tok.text, tok.line)
    elif tok.is_op("=") and prev is not None and prev.kind == "op" and prev.text in ("+", "-", "*", "/", "%", "=", "!", "<", ">"):
        r.title = "Space inside an operator"
        r.what = "`%s =` with a space is not the same as `%s=`. Operators like `+=`, `==`, `<=` must be written without spaces." % (
            prev.text, prev.text)
        if prev.line == tok.line:
            r.fixed_line = line[:prev.col] + line[tok.col - 1:] if line[prev.col:tok.col - 1].strip() == "" else None
    return r


@handler("expected_identifier")
def expected_identifier(ctx):
    src = ctx.src
    r = Result(vars={"before": ctx.groups.get("before", "something else")})
    if src is None or ctx.tok is None:
        return r
    tok = ctx.tok
    prev = ctx.prev(tok)
    before_comma = ctx.prev(prev) if prev is not None else None
    if tok.kind in ("int", "float") and prev is not None and prev.is_op(",") and before_comma is not None \
            and before_comma.kind in ("int", "float") and before_comma.line == tok.line:
        # float pi = 3,14;   int big = 1,000,000;
        line = src.line(tok.line)
        k = tok
        while ctx.nxt(k) is not None and ctx.nxt(k).is_op(",") and ctx.nxt(ctx.nxt(k)) is not None \
                and ctx.nxt(ctx.nxt(k)).kind == "int":
            k = ctx.nxt(ctx.nxt(k))
        written = line[before_comma.col - 1:k.col - 1 + len(k.text)]
        parts = written.replace(" ", "").split(",")
        if len(parts) == 2 and len(parts[1]) != 3:
            meant = "%s.%s" % (parts[0], parts[1])
            r.title = "Comma used as a decimal point"
            r.what = ("`%s` uses a comma, but C writes decimal numbers with a DOT: `%s`. A comma separates two "
                      "different things, so the compiler sees `%s` and then an unexpected `%s`." % (
                          written, meant, parts[0], parts[1]))
        else:
            meant = "".join(parts)
            r.title = "Commas inside a number"
            r.what = ("`%s` contains commas. In C, numbers are written without any separators: `%s`. A comma "
                      "separates two different things, so the compiler sees `%s` and then an unexpected `%s`." % (
                          written, meant, parts[0], parts[1]))
        r.fix = ["Write `%s`." % meant]
        r.why = ["In C the comma is an operator / separator, so it can never be part of a number."]
        r.fixed_line = line[:before_comma.col - 1] + meant + line[k.col - 1 + len(k.text):]
        r.fixed_line_no = tok.line
        return r
    if tok.kind in ("int", "float", "bad_number"):
        r.title = "Name starting with a digit"
        r.what = "`%s` cannot be used as a name: names must start with a letter or `_`." % tok.text
        return r
    if tok.kind == "kw" and prev is not None and (prev.kind == "kw" and prev.text in TYPE_KEYWORDS or prev.is_op("*", ",")):
        r.title = "Keyword used as a variable name"
        r.what = "`%s` is a reserved keyword in C/C++, so it cannot be used as a variable or function name." % tok.text
        r.fix = ["Choose another name, e.g. `%s_value` or `my%s`." % (tok.text, tok.text.capitalize())]
        return r
    return r


@handler("do_while")
def do_while(ctx):
    src = ctx.src
    r = Result()
    if src is None or ctx.tok is None:
        return r
    prev = ctx.prev()
    if prev is not None and prev.is_op("}"):
        line = src.line(prev.line)
        r.fixed_line = insert_at(line, prev.col, " while (condition);")
        r.fixed_line_no = prev.line
        r.real_line = prev.line
    return r


@handler("missing_open_brace")
def missing_open_brace(ctx):
    src = ctx.src
    r = Result(vars={"real_line": ctx.line_no})
    if src is None:
        return r
    # find the last function header before the error line:  ... name ( ... ) <newline>
    n = ctx.line_no or 1
    for ln in range(n, 0, -1):
        text = src.line(ln)
        if re.match(r"^\s*[A-Za-z_][\w\s\*]*\b\w+\s*\([^;{}]*\)\s*$", text):
            r.vars["real_line"] = ln
            r.real_line = ln
            r.fixed_line = text.rstrip() + " {"
            r.fixed_line_no = ln
            return r
    if "expected declaration specifiers" in ctx.diag.message:
        return veto()
    return r


@handler("case_colon")
def case_colon(ctx):
    line = ctx.line_text() or ""
    r = Result()
    m = re.search(r"\b(case\s+[^:;]+?|default)\s*;", line)
    if m:
        r.fixed_line = line[:m.end() - 1] + ":" + line[m.end():]
        return r
    if not re.search(r"\b(case|default)\b", line):
        return veto()
    return r


@handler("missing_condition_parens")
def missing_condition_parens(ctx):
    line = ctx.line_text() or ""
    r = Result()
    m = re.match(r"^(\s*(?:if|while|switch))\s+(?!\()(.+?)(\s*\{?\s*)$", line)
    if m:
        r.fixed_line = "%s (%s)%s" % (m.group(1), m.group(2).rstrip(), " {" if "{" in m.group(3) else "")
        return r
    if not re.search(r"\b(if|while|for|switch)\b", line):
        return veto()
    return r


@handler("missing_semicolon")
def missing_semicolon(ctx):
    r = _missing_semicolon(ctx)
    if r is None or r.redirect:
        return r
    fixed = r.fixed_line
    if fixed and re.search(r";\s*:\s*$", fixed):
        r.fixed_line = re.sub(r";\s*:\s*$", ";", fixed)
        r.title = "Colon : typed instead of semicolon ;"
        r.what = ("The statement ends with `:` (colon). C statements end with `;` (semicolon) - the two keys are "
                  "next to each other on the keyboard.")
        r.fix = ["Replace the `:` with `;`."]
    return r


@handler("generic_syntax")
def generic_syntax(ctx):
    """Catch-all parser error: first look for a keyword typed with a capital letter (For, While, If)."""
    src = ctx.src
    if src is None or not ctx.line_no:
        return Result()
    from .semantic import STATEMENT_KEYWORDS, _keyword_typo
    for t in src.tokens_on_line(ctx.line_no):
        low = t.text.lower()
        if t.kind == "id" and low != t.text and low in STATEMENT_KEYWORDS:
            return _keyword_typo(Result(), t.text, low, src.line(t.line), t)
    return Result()
