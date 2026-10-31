"""Handlers for preprocessor and lexical-analysis rules."""
import re

from ..textutil import closest
from .base import Result, code, handler, replace_word, veto

HOMOGLYPHS = {
    "\u201c": ('"', "curly opening quote \u201c"),
    "\u201d": ('"', "curly closing quote \u201d"),
    "\u201e": ('"', "low double quote \u201e"),
    "\u2033": ('"', "double prime \u2033"),
    "\u00ab": ('"', "angle quote \u00ab"),
    "\u00bb": ('"', "angle quote \u00bb"),
    "\u2018": ("'", "curly opening apostrophe \u2018"),
    "\u2019": ("'", "curly closing apostrophe \u2019"),
    "\u201a": ("'", "low single quote \u201a"),
    "\u2032": ("'", "prime \u2032"),
    "\u00b4": ("'", "acute accent \u00b4"),
    "\u2013": ("-", "en dash \u2013"),
    "\u2014": ("-", "em dash \u2014"),
    "\u2212": ("-", "minus sign \u2212"),
    "\u00a0": (" ", "invisible non-breaking space"),
    "\u2009": (" ", "thin space"),
    "\u202f": (" ", "narrow non-breaking space"),
    "\u3000": (" ", "full-width space"),
    "\u200b": ("", "invisible zero-width space"),
    "\u200c": ("", "invisible zero-width character"),
    "\u200d": ("", "invisible zero-width character"),
    "\ufeff": ("", "invisible byte-order mark"),
    "\uff1b": (";", "full-width semicolon \uff1b"),
    "\uff0c": (",", "full-width comma \uff0c"),
    "\uff08": ("(", "full-width bracket \uff08"),
    "\uff09": (")", "full-width bracket \uff09"),
    "\u00d7": ("*", "multiplication sign \u00d7"),
    "\u00f7": ("/", "division sign \u00f7"),
    "\u2264": ("<=", "less-or-equal sign \u2264"),
    "\u2265": (">=", "greater-or-equal sign \u2265"),
    "\u2260": ("!=", "not-equal sign \u2260"),
    "\u2026": ("...", "ellipsis \u2026"),
}
ASCII_STRAY = {
    "@": "`@` - C/C++ has no @ operator",
    "$": "`$` - not a C operator",
    "`": "a backtick ` (not a quote in C)",
    "\\": "a backslash `\\` outside a string",
    "#": "`#` in the middle of a line (# may only start a preprocessor line such as #include)",
}


def _line_has_code_char(line, ch):
    """True if ch appears outside string/char literals."""
    inside = None
    i = 0
    while i < len(line):
        c = line[i]
        if inside:
            if c == "\\":
                i += 2
                continue
            if c == inside:
                inside = None
        elif c in "\"'":
            inside = c
        elif c == ch:
            return True
        i += 1
    return False


@handler("missing_header")
def missing_header(ctx):
    h = ctx.groups.get("header", "").strip()
    std = ctx.data.get("stdlib", {})
    legacy = std.get("legacy_headers", {})
    line = ctx.line_text()
    r = Result(vars={"header": h})
    low = h.lower()
    if low in legacy:
        info = legacy[low]
        r.title = "Old / non-standard header <%s>" % h
        r.what = info["what"]
        r.fix = list(info["fix"])
        r.why = ["Many textbooks and older lab machines use Turbo C / Turbo C++, which had headers that modern compilers (GCC, Clang) do not provide."]
        if low == "bits/stdc++.h" and ctx.src is not None:
            used = set()
            for t in ctx.src.tokens:
                if t.kind == "id":
                    hh = ctx.data.get("stdlib", {}).get("cpp_std", {}).get(t.text)
                    if hh and hh != "bits/stdc++.h":
                        used.add(hh)
            if used:
                incs = "\n".join("#include <%s>" % u for u in sorted(used))
                r.hints.append("Your program uses names from these headers, so replace the line with:\n" + incs)
                r.fixed_line = incs
        elif low == "conio.h" and ctx.src is not None:
            calls = sorted({t.text for t in ctx.src.tokens if t.kind == "id" and t.text in ("clrscr", "getch", "getche", "kbhit", "gotoxy")})
            if calls:
                r.hints.append("Your code also calls %s - remove or replace these too." % ", ".join(code(c + "()") for c in calls))
            r.fixed_line = ""
        elif low in ("iostream.h", "fstream.h", "iomanip.h"):
            r.fixed_line = line.replace(h, h[:-2]) if line else None
        return r
    c_h = std.get("c_headers", [])
    cpp_h = std.get("cpp_headers", [])
    if not ctx.cpp and h in cpp_h:
        r.title = "C++ header used in a C program"
        r.what = ("`<%s>` is a C++ header, but your file is compiled as a C program (.c). "
                  "C does not have cout/cin or <%s>." % (h, h))
        r.why = ["The file is saved with a .c extension (or compiled with gcc instead of g++) but contains C++ code."]
        r.fix = ["If you are writing C: use `#include <stdio.h>` with printf/scanf.",
                 "If you are writing C++: rename the file to .cpp and compile with g++ (or clang++)."]
        return r
    quoted = bool(re.search(r'#\s*include\s*"', line or ""))
    pool = (cpp_h + c_h) if ctx.cpp else (c_h + [x for x in cpp_h if x.startswith("c")])
    best = closest(h, pool, limit=3, max_results=1)
    if quoted and not best:
        r.title = "Your own header file was not found"
        r.what = ("The file `%s` (included with quotes) could not be found next to your program." % h)
        r.fix = ["Make sure `%s` is saved in the same folder as your .c/.cpp file." % h,
                 "Check that the file name and extension match exactly (names can be case-sensitive)."]
        return r
    if best:
        r.vars["suggest"] = best[0]
        r.title = "Misspelled header name"
        r.what = "There is no standard header called `%s`. You probably meant `%s`." % (h, best[0])
        r.fix = ["Change it to `#include <%s>`." % best[0]]
        if line:
            fixed = line.replace(h, best[0], 1)
            if fixed != line:
                r.fixed_line = fixed
        return r
    r.hints.append("If `%s` belongs to an extra library, that library is not installed for this compiler." % h)
    return r


@handler("invalid_directive")
def invalid_directive(ctx):
    line = ctx.line_text()
    d = ctx.groups.get("directive")
    if not d and line:
        m = re.match(r"\s*#\s*(\w+)", line)
        d = m.group(1) if m else "?"
    sug = ctx.groups.get("suggest")
    if not sug:
        found = closest(d or "", ctx.data.get("stdlib", {}).get("directives", []), limit=3, max_results=1)
        sug = found[0] if found else "include"
    r = Result(vars={"directive": d, "suggest": sug})
    if line and d:
        fixed = re.sub(r"#(\s*)%s\b" % re.escape(d), "#\\g<1>" + sug, line, count=1)
        if fixed != line:
            r.fixed_line = fixed
    return r


@handler("extra_tokens")
def extra_tokens(ctx):
    line = ctx.line_text()
    r = Result(vars={"directive": ctx.groups.get("directive", "include")})
    if line:
        m = re.match(r"^(\s*#\s*\w+\s*(?:<[^>]*>|\"[^\"]*\"|\S+)?)(.*)$", line)
        if m and m.group(2).strip():
            extra = m.group(2).strip()
            if not extra.startswith("//") and not extra.startswith("/*"):
                r.fixed_line = m.group(1).rstrip()
                if extra != ";":
                    r.what = "There is extra text `%s` after your `#%s` line." % (extra, r.vars["directive"])
    return r


@handler("macro_semicolon")
def macro_semicolon(ctx):
    n, m = ctx.note(r"(?:in expansion of macro|expanded from macro) '(?P<m>\w+)'")
    if n is None or ctx.src is None:
        return veto()
    name = m.group("m")
    sym = ctx.src.symbols.macros.get(name)
    if sym is None or not sym.value.rstrip().endswith(";"):
        return veto()
    r = Result(vars={"macro": name, "value": sym.value, "macro_line": str(sym.line)})
    r.real_line = sym.line
    r.fixed_line_no = sym.line
    r.fixed_line = ctx.src.line(sym.line).rstrip().rstrip(";").rstrip()
    lines = [x for x in (ctx.line_no, n.location.line if n.location else None) if x and x != sym.line]
    use_line = lines[0] if lines else ctx.line_no
    used = ctx.src.line(use_line).strip()
    if used:
        r.hints.append("After replacement, line %d really reads: `%s`" % (
            use_line, re.sub(r"\b%s\b" % re.escape(name), sym.value, used)))
    return r


@handler("stray_char")
def stray_char(ctx):
    line = ctx.line_text() or ""
    r = Result()
    found = []
    for ch in line:
        if ord(ch) > 127 and ch not in [c for c, _ in found]:
            found.append((ch, HOMOGLYPHS.get(ch, (None, "the non-ASCII character %s (U+%04X)" % (ch, ord(ch))))[1]))
    if found:
        r.vars["shown"] = ", ".join(desc for _, desc in found)
        fixed = "".join(HOMOGLYPHS[c][0] if c in HOMOGLYPHS else c for c in line)
        if fixed != line:
            r.fixed_line = fixed
        if any(c in "\u201c\u201d\u2018\u2019" for c, _ in found):
            r.title = "Curly \u201csmart\u201d quotes instead of normal quotes"
        elif any(c in "\u00a0\u200b\u2009\u202f\ufeff" for c, _ in found):
            r.title = "Invisible special space character"
        return r
    ch = ctx.groups.get("char", "")
    if ch in ASCII_STRAY and (not line or _line_has_code_char(line, ch)):
        r.vars["shown"] = ASCII_STRAY[ch]
        if ch == "\\":
            r.hints.append("A backslash is only meaningful inside strings (`\"\\n\"`) or at the very end of a #define line.")
        if ch == "@":
            r.hints.append("Did you mean an operator such as `*`, `+` or `%`?")
        return r
    if re.match(r"\\\d{3}$", ch):
        r.vars["shown"] = "a non-ASCII byte (%s) - usually a curly quote, long dash or special space" % ch
        return r
    r.vars["shown"] = code(ch) if ch else "an unexpected symbol"
    return r


FORMAT_SPEC = re.compile(r"%(?!%)[-+ #0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|L|z|j|t)?[diouxXfFeEgGcspaA]")
ARG_LIST = re.compile(r"\s*[\w&*\[\]().+\-/%<>!~?:]+(?:\s*[-+*/%<>=!&|]+\s*[\w&*\[\]().]+)*"
                      r"(?:\s*,\s*[\w&*\[\]().+\-/%<>!~?:]+(?:\s*[-+*/%<>=!&|]+\s*[\w&*\[\]().]+)*)*\s*")


def _close_format_string(line, idx):
    """printf("Sum is %d\\n, a + b);  ->  printf("Sum is %d\\n", a + b);

    When the unclosed string is a format string and the text after one of its
    commas looks like the argument list, the quote belongs before that comma.
    """
    m = re.search(r"\)\s*;\s*$", line)
    if not m:
        return None
    open_i = idx if line[idx:idx + 1] == '"' else line.rfind('"', 0, m.start())
    if open_i < 0:
        return None
    body = line[open_i + 1:m.start()]
    specs = list(FORMAT_SPEC.finditer(body))
    if not specs:
        return None
    for c in [i for i, ch in enumerate(body) if ch == "," and i >= specs[-1].end()]:
        rest = body[c + 1:]
        if rest.strip() and ARG_LIST.fullmatch(rest) and not re.search(r"\w\s+\w", rest):
            pos = open_i + 1 + c
            return line[:pos] + '"' + line[pos:], rest.strip()
    return None


@handler("unterminated_literal")
def unterminated_literal(ctx):
    q = ctx.groups.get("q1") or ctx.groups.get("q2") or '"'
    line = ctx.line_text() or ""
    r = Result(vars={"quote": q, "kind": "string" if q == '"' else "character constant"})
    if q == '"':
        idx = ctx.col_index() or 0
        smart = _close_format_string(line, idx) if line.count('"') % 2 == 1 else None
        if smart:
            r.fixed_line, args = smart
            r.fix = ['Put the closing `"` at the end of the format text, BEFORE the comma. '
                     'What comes after the comma (`%s`) is the value to print, not part of the text.' % args]
        elif line.count('"') % 2 == 1:
            m = re.search(r"\)\s*;\s*$", line)
            if m:
                r.fixed_line = line[:m.start()] + '"' + line[m.start():]
            elif line.rstrip().endswith(";"):
                s = line.rstrip()
                r.fixed_line = s[:-1] + '";'
            else:
                r.fixed_line = line.rstrip() + '"'
        inner = line[idx + 1:]
        if '"' in inner[:-1]:
            r.hints.append('If the text itself contains a double quote, write it as \\" inside the string.')
    else:
        r.what = ("A character constant starts with `'` on line %s but the closing `'` is missing." % ctx.line_no)
        r.fix = ["Close it: `'a'`. Remember a character constant holds ONE character; text needs double quotes."]
        m = re.search(r"'(\w+)'(\w+)'", line)
        if m:
            r.hints.append("An apostrophe inside text (like it's) only works in double quotes: \"it's\".")
    return r


@handler("invalid_suffix")
def invalid_suffix(ctx):
    suffix = ctx.groups.get("suffix", "")
    line = ctx.line_text() or ""
    if ctx.groups.get("kind") == "exponent":
        r = Result(title="Number with an empty exponent (e)")
        m = re.search(r"\b(\d+\.?\d*)[eE](?![\d+-])", line) or re.search(r"\b(\d+\.?\d*)[eE][+-](?!\d)", line)
        number = m.group(0) if m else "1e"
        r.what = ("`%s` on line %s is not a complete number. In C, `e` inside a number means \"times 10 to the "
                  "power\" (`1e3` = 1000, `2.5e-2` = 0.025), so digits must follow the `e`." % (number, ctx.line_no))
        r.fix = ["Add the power after `e` (`1e3`), or remove the `e` if you did not mean scientific notation."]
        r.why = ["The digits after `e` were forgotten, or a variable named `e` was written right after a number."]
        r.example = {"wrong": "float z = 1e;", "right": "float z = 1e3;   /* 1000.0 */"}
        return r
    number = None
    if ctx.src is not None:
        for t in ctx.src.tokens_on_line(ctx.line_no):
            if t.kind == "bad_number" and t.text.endswith(suffix):
                number = t.text
                break
    if number is None:
        m = re.search(r"\b(\d[\w.]*%s)\b" % re.escape(suffix), line)
        number = m.group(1) if m else suffix
    digits = number[: len(number) - len(suffix)] if number.endswith(suffix) else number
    r = Result(vars={"number": number, "suffix": suffix})
    if suffix.startswith("."):
        r.title = "Number with two decimal points"
        r.what = ("`%s` has more than one decimal point. A number can contain only ONE `.` (like `2.5`)."
                  % number)
        r.fix = ["Keep one decimal point, e.g. `%s`." % digits]
        r.why = ["A typing mistake, or a version number / date like `2.5.1` written as a number."]
        r.example = {"wrong": "float x = 2.5.1;", "right": "float x = 2.51;"}
        return r
    if suffix in ("f", "F") and re.fullmatch(r"\d+", digits):
        r.title = "f written after a whole number"
        r.what = ("`%s`: the `f` ending (float) is only allowed on numbers that have a decimal point. "
                  "Write `%s.0f` (or simply `%s`)." % (number, digits, digits))
        r.fix = ["Write `%s.0f`." % digits]
        r.why = ["The float suffix `f` needs a decimal point before it (`3.0f`, `2.5f`)."]
        r.fixed_line = replace_word(line, number, digits + ".0f")
        r.example = {"wrong": "float y = 3f;", "right": "float y = 3.0f;"}
        return r
    if re.fullmatch(r"[A-Za-z_]\w?", suffix):
        r.title = "Missing * in multiplication"
        r.what = ("In maths `%s` means %s times %s, but C needs an explicit `*`. The scanner read `%s` as one "
                  "(invalid) number." % (number, digits, suffix, number))
        r.fixed_line = replace_word(line, number, "%s * %s" % (digits, suffix))
        r.fix = ["Write `%s * %s`." % (digits, suffix)]
    elif re.fullmatch(r"[A-Za-z_]\w+", suffix):
        r.title = "Name that starts with a digit"
        r.what = ("`%s` looks like a variable name, but names in C/C++ cannot start with a digit." % number)
        r.fix = ["Rename it so it starts with a letter or `_`, e.g. `%s%s`." % (suffix, digits)]
    return r


@handler("octal_digit")
def octal_digit(ctx):
    digit = ctx.groups.get("digit", "8")
    line = ctx.line_text() or ""
    number = None
    if ctx.src is not None:
        for t in ctx.src.tokens_on_line(ctx.line_no):
            if t.kind == "bad_number" and t.text.startswith("0"):
                number = t.text
                break
    if number is None:
        m = re.search(r"\b(0\d+)\b", line)
        number = m.group(1) if m else "0" + digit
    fixed_number = number.lstrip("0") or "0"
    r = Result(vars={"number": number, "fixed_number": fixed_number, "digit": digit})
    f = replace_word(line, number, fixed_number)
    if f:
        r.fixed_line = f
    return r


@handler("unknown_escape")
def unknown_escape(ctx):
    esc = ctx.groups.get("esc", "?")
    line = ctx.line_text() or ""
    r = Result(vars={"esc": esc})
    strings = list(re.finditer(r'"((?:[^"\\]|\\.)*)"', line))
    target = None
    for m in strings:
        if "\\" + esc in m.group(1):
            target = m
            break
    if target is not None:
        body = target.group(1)
        if re.search(r"[A-Za-z]:\\|\\\w+\\", body):
            keep_nl = body.endswith("\\n")
            core = body[:-2] if keep_nl else body
            new_body = re.sub(r"\\(?![\\\"])", r"\\\\", core) + ("\\n" if keep_nl else "")
            r.hints.append("This looks like a Windows path. Every single backslash must be doubled (or use /).")
            if re.search(r"\\[ntr0]", body):
                r.hints.append("Careful: `\\n`, `\\t` or `\\r` inside your path are valid codes (new line / tab), "
                               "so they silently print wrong text - double those backslashes too.")
        else:
            new_body = body.replace("\\" + esc, "\\\\" + esc)
        r.fixed_line = line[:target.start(1)] + new_body + line[target.end(1):]
    return r


@handler("unterminated_comment")
def unterminated_comment(ctx):
    line = ctx.line_text() or ""
    r = Result()
    if line:
        r.fixed_line = line.rstrip() + " */"
    if ctx.src is not None:
        total = len(ctx.src.lines)
        if ctx.line_no and total > ctx.line_no:
            r.hints.append("Lines %d to %d were all treated as comment text." % (ctx.line_no, total))
    return r


@handler("multichar")
def multichar(ctx):
    line = ctx.line_text() or ""
    r = Result()
    lit = None
    idx = ctx.col_index() or 0
    for m in re.finditer(r"'((?:[^'\\]|\\.)*)'", line):
        if len(m.group(1)) > 1 and not re.fullmatch(r"\\(?:[0-7]{1,3}|x[0-9a-fA-F]+|.)", m.group(1)):
            if lit is None or abs(m.start() - idx) < abs(lit.start() - idx):
                lit = m
    if lit is None:
        r.vars["literal"] = "the character constant"
        return r
    body = lit.group(1)
    r.vars["literal"] = lit.group(0)
    if body in ("/n", "/t", "/0", "/r"):
        r.title = "Slash instead of backslash in an escape code"
        r.what = "`'%s'` uses a forward slash. Special characters use a BACKSLASH: `'\\%s'`." % (body, body[1])
        r.fixed_line = line[:lit.start()] + "'\\" + body[1] + "'" + line[lit.end():]
        r.fix = ["Write `'\\%s'`." % body[1]]
        return r
    before = line[:lit.start()]
    if re.search(r"\b(printf|puts|strcpy|strcmp|strcat|fputs|cout\s*<<)\s*\(?\s*$|<<\s*$", before) or \
            re.search(r"char\s*\*\s*\w+\s*=\s*$|\w+\s*\[\s*\d*\s*\]\s*=\s*$", before):
        r.fixed_line = line[:lit.start()] + '"' + body.replace('"', '\\"') + '"' + line[lit.end():]
        r.fix = ["Text needs double quotes: `\"%s\"`." % body]
    elif re.search(r"char\s+\w+\s*=\s*$", before):
        r.fix = ["A `char` variable stores one character - keep one character, e.g. `'%s'`, or use a char array "
                 "`char s[] = \"%s\";` for text." % (body[0], body)]
    return r


@handler("empty_char")
def empty_char(ctx):
    line = ctx.line_text() or ""
    r = Result()
    if "''" in line:
        r.fixed_line = line.replace("''", "' '", 1)
    return r
