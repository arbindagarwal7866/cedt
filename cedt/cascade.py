"""
cascade.py - ROOT-CAUSE analysis.

Why compilers print avalanches of errors: after a syntax error the parser
uses error RECOVERY (GCC/Clang use a form of panic mode - skip tokens until a
synchronising token such as ';' or '}'), and then continues.  The skipped
code leaves holes: variables that were never declared, statements that are
now outside a function, and so on.  Each hole becomes another message.

This module groups the explanations so that a student sees the few REAL
problems first and the follow-on (cascade) messages folded underneath them.

Heuristics, in order:
  A. summary lines (collect2/ld) and messages inside library headers
  B. duplicates  - same suggested fix, or same rule about the same name
  C. same line   - one line rarely contains two independent mistakes
  D. syntax window - syntax errors shortly after a syntax/lexical error
  E. broken declarations - "x undeclared" when x's declaration line failed
  F. implicit declaration -> linker 'undefined reference' / conflicting types
  G. missing header - several functions from the same missing #include
  H. warnings caused by errors - "unused variable" that is in fact used
"""
import re

SYNTAX_WINDOW = 6


def _line(e):
    if e.real_line:
        return e.real_line
    if e.location and e.location.line:
        return e.location.line
    return None


def _loc_line(e):
    return e.location.line if e.location and e.location.line else None


def _name_of(e):
    if e.subject:
        return e.subject
    d = e.diagnostic
    if d is not None and d.symbol:
        return d.symbol
    return None


_ALL = []


def _ultimate(e):
    seen = set()
    while not e.is_root and e.root_id is not None and e.id not in seen:
        seen.add(e.id)
        e = _ALL[e.root_id]
    return e


def _follow(f, root, reason):
    root = _ultimate(root)
    if f is root or not f.is_root:
        return
    f.is_root = False
    f.root_id = root.id
    f.follower_reason = reason
    root.followers.append(f.id)
    # re-attach f's own followers to the new root
    for fid in list(f.followers):
        child = _ALL[fid]
        child.root_id = root.id
        root.followers.append(fid)
    f.followers = []


def analyze(exps, files):
    global _ALL
    _ALL = exps
    for i, e in enumerate(exps):
        e.id = i
        e.is_root = True
        e.root_id = None
        e.followers = []
    compiler = [e for e in exps if e.source == "compiler"]
    errors_first = lambda e: 0 if e.level == "error" else 1  # noqa: E731

    # ---- A. summaries and library-internal messages ------------------------
    last_link = None
    last_user_error = None
    for e in compiler:
        d = e.diagnostic
        if d is not None and d.origin == "linker" and e.level != "info":
            last_link = e
        if e.rule_id in ("K005", "D002") and e.level == "info":
            target = last_link or last_user_error
            if target is not None:
                _follow(e, target, "summary line of the linker error above")
            continue
        if e.rule_id == "G001":
            if last_user_error is not None:
                _follow(e, last_user_error, "inside the standard library, caused by this error")
            continue
        if e.level == "error" and e.is_root:
            last_user_error = e

    # ---- B. duplicates --------------------------------------------------------
    seen_fix = {}
    seen_key = {}
    for e in compiler:
        if not e.is_root:
            continue
        keys = []
        if e.fixed_line is not None and e.fixed_line_no and e.fixed_kind != "delete" or \
                (e.fixed_kind == "delete" and e.fixed_line_no):
            keys.append(("fix", e.fixed_line_no, e.fixed_line, e.fixed_kind))
        nm = None
        if e.rule_id not in ("G000",):
            nm = _name_of(e)
        if nm:
            keys.append(("rule", e.rule_id, nm))
        keys.append(("same", e.rule_id, e.title, _line(e)))
        hit = None
        for k in keys:
            if k in seen_fix:
                hit = seen_fix[k]
                break
        if hit is not None:
            # keep the more severe one as the root
            if errors_first(e) < errors_first(hit) and hit.is_root:
                for k2, v in list(seen_fix.items()):
                    if v is hit:
                        seen_fix[k2] = e
                _follow(hit, e, "the same problem reported again")
            else:
                _follow(e, hit, "the same problem reported again")
            continue
        for k in keys:
            seen_fix[k] = e

    # ---- C/D. same line and syntax window --------------------------------------
    anchor = None
    for e in compiler:
        if not e.is_root:
            continue
        ln = _loc_line(e)
        if anchor is not None and ln is not None:
            al, ar = _loc_line(anchor), _line(anchor)
            if ln in (al, ar):
                independent = (e.rule_id == anchor.rule_id and e.phase == "semantic"
                               and _name_of(e) != _name_of(anchor))
                if not independent:
                    _follow(e, anchor, "same line as an earlier error")
                    continue
            if anchor.phase in ("syntax", "lexical") and e.phase == "syntax" and al is not None \
                    and 0 <= ln - al <= SYNTAX_WINDOW:
                _follow(e, anchor, "parser still confused by the error on line %d" % (ar or al))
                continue
            if anchor.rule_id in ("S002", "S014", "L006", "L002") and e.phase == "syntax":
                _follow(e, anchor, "caused by the error on line %d" % (ar or al))
                continue
            if anchor.rule_id in ("L002", "L006") and al is not None and 0 <= ln - al <= SYNTAX_WINDOW:
                _follow(e, anchor, "the unclosed %s on line %d swallowed the following code" % (
                    "comment" if anchor.rule_id == "L006" else "string", al))
                continue
        if e.level == "error" or (e.phase == "lexical" and e.level == "warning"):
            anchor = e

    # ---- E. broken declarations -------------------------------------------------
    root_errors = [e for e in compiler if e.is_root and e.level == "error"]
    for e in compiler:
        if not e.is_root or e.diagnostic is None:
            continue
        sf = _source_for(e, files)
        if sf is None:
            continue
        names = []
        nm = _name_of(e)
        if nm and re.match(r"^[A-Za-z_]\w*$", nm):
            names.append(nm)
        if e.level != "error" and _loc_line(e):
            names += [t.text for t in sf.tokens_on_line(_loc_line(e)) if t.kind == "id"]
        done = False
        for name in names:
            decl_lines = _declaration_lines(sf, name)
            for r in root_errors:
                if r is e or not r.is_root:
                    continue
                rl = {x for x in (_loc_line(r), _line(r)) if x}
                if r.rule_id == "P005" and r.diagnostic is not None:
                    rl |= {n.location.line for n in r.diagnostic.notes
                           if n.location and n.location.line and "macro" in n.message}
                    rl |= {x for x in [_loc_line(r)] if x}
                if rl and decl_lines & rl and (_loc_line(e) or 0) >= min(rl) and (_loc_line(e) not in rl or e.level != "error"):
                    _follow(e, r, "'%s' is declared on a line that has an error" % name)
                    done = True
                    break
            if done:
                break

    # ---- F. implicit declaration -> linker / conflicting types ------------------
    implicit = {}
    for e in compiler:
        if e.rule_id == "M002" and e.diagnostic is not None:
            m = re.search(r"function '([^']+)'", e.diagnostic.message)
            if m:
                implicit.setdefault(m.group(1), e)
    for e in compiler:
        if not e.is_root or e.diagnostic is None:
            continue
        sym = e.diagnostic.symbol
        if not sym:
            m = re.search(r"(?:conflicting types for|built-in function|function) '([^']+)'", e.diagnostic.message)
            sym = m.group(1) if m else None
        if e.rule_id == "K007":
            sym = "gets"
        if sym and sym in implicit and implicit[sym] is not e:
            _follow(e, implicit[sym], "consequence of calling %s() before it was declared" % sym)
    # other messages on the line of an implicit call (e.g. wrong printf format because the
    # compiler guessed the function returns int)
    for name, imp in implicit.items():
        ln = _loc_line(imp)
        sf = _source_for(imp, files)
        for e in compiler:
            if e is imp or not e.is_root or _loc_line(e) != ln or e.rule_id == "M002":
                continue
            if sf is not None and re.search(r"\b%s\s*\(" % re.escape(name), sf.line(ln)):
                _follow(e, imp, "caused by calling %s() before it was declared" % name)

    # ---- G. same missing header / same missing std:: --------------------------
    by_header = {}
    first_std = None
    for e in compiler:
        if not e.is_root:
            continue
        if re.search(r"needs std::", e.title or ""):
            if first_std is None:
                first_std = e
            else:
                _follow(e, first_std, "same cause: a std:: name used without std::")
            continue
        m = re.match(r"Missing #include <([^>]+)>", e.title or "")
        if m:
            h = m.group(1)
            if h in by_header:
                _follow(e, by_header[h], "same missing #include <%s>" % h)
            else:
                by_header[h] = e

    # broken #include line -> "missing #include" messages for that header
    for e in compiler:
        if e.is_root and e.rule_id in ("P001", "P002") and e.diagnostic is not None:
            sf = _source_for(e, files)
            text = sf.line(_loc_line(e)) if sf is not None and _loc_line(e) else ""
            for h, other in by_header.items():
                if other.is_root and h in text and other is not e:
                    _follow(other, e, "the #include line for <%s> is broken" % h)

    # ---- H. warnings that are side effects of errors ---------------------------
    errors = [e for e in compiler if e.is_root and e.level == "error"]
    if errors:
        for e in compiler:
            if not e.is_root or e.rule_id != "W003":
                continue
            nm = _name_of(e)
            sf = _source_for(e, files)
            if sf is None or not nm or sf.identifier_count(nm) <= 1:
                continue
            ln = _loc_line(e) or 0
            before_use = [r for r in errors if (_loc_line(r) or 0) >= ln]
            target = before_use[0] if before_use else errors[0]
            _follow(e, target, "'%s' is used later, but that code was skipped because of this error" % nm)
        for e in compiler:
            if not e.is_root or e.rule_id != "W003":
                continue
            nm = _name_of(e)
            for r in errors:
                if not r.is_root:
                    continue
                fixed = r.fixed_line or ""
                sf = _source_for(r, files)
                orig = sf.line(r.fixed_line_no) if sf is not None and r.fixed_line_no else ""
                sug = r.title.endswith("`%s`?" % nm) if nm else False
                if nm and (sug or (re.search(r"\b%s\b" % re.escape(nm), fixed) and
                                   not re.search(r"\b%s\b" % re.escape(nm), orig))):
                    _follow(e, r, "after fixing this error, '%s' will be used" % nm)
                    break

    # ---- I. a warning on the same line as an error is usually the same problem --
    err_lines = {}
    for e in compiler:
        if e.is_root and e.level == "error":
            for x in (_line(e), _loc_line(e)):
                if x:
                    err_lines.setdefault(x, e)
    for e in compiler:
        if e.is_root and e.level == "warning":
            x = _line(e)
            if x in err_lines and err_lines[x] is not e:
                _follow(e, err_lines[x], "same line as the error")

    # ---- J. two warnings on one line that CEDT traced to the same mistake ------
    seen = {}
    for e in compiler:
        if e.is_root and e.level == "warning":
            key = (e.title, _line(e))
            if key in seen:
                _follow(e, seen[key], "the same problem reported again")
            else:
                seen[key] = e
    return exps


def _source_for(e, files):
    d = e.diagnostic
    if d is None or d.location is None:
        return None
    import os
    f = d.location.file
    return files.get(f) or files.get(os.path.basename(f.replace("\\", "/")))


def _declaration_lines(sf, name):
    """Lines where `name` appears right after a type-like word (int x, bool done, string s)."""
    lines = set()
    toks = sf.tokens
    for i, t in enumerate(toks):
        if t.kind == "id" and t.text == name and i > 0:
            p = toks[i - 1]
            if p.kind in ("kw", "id") or p.is_op("*", ">"):
                nx = toks[i + 1] if i + 1 < len(toks) else None
                if nx is not None and (nx.is_op("=", ";", ",", "[", "(") or nx.kind in ("id",)):
                    lines.add(t.line)
    for s in sf.symbols.declarations(name):
        if s.line:
            lines.add(s.line)
    return lines
