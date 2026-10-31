"""
cli.py - command-line interface.

    python cedt.py prog.c                     compile with gcc/clang and explain
    python cedt.py prog.c --run --input "5 7" also run the program and explain crashes
    python cedt.py prog.cpp --compiler clang  choose the compiler
    python cedt.py prog.c --html report.html  save an HTML report
    gcc prog.c 2> err.txt; python cedt.py --log err.txt --source prog.c
    python cedt.py --web                      start the web interface

Compiler-design views (for learning / the viva):
    python cedt.py --grammar                  LL(1) grammar, FIRST/FOLLOW, parsing table
    python cedt.py --trace err.txt            LL(1) parse trace of compiler output
    python cedt.py --tokens prog.c            tokens produced by CEDT's C lexer (DFA)
    python cedt.py --symbols prog.c           scope-aware symbol table
    python cedt.py --diag-tokens err.txt      tokens of compiler output (diagnostic lexer)
"""
import argparse
import io
import json
import os
import sys

from . import __version__


def _stdout_utf8():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass


def build_parser():
    p = argparse.ArgumentParser(
        prog="cedt",
        description="CEDT - Compiler Error Diagnostic Translator: beginner-friendly explanations of GCC/Clang "
                    "errors for C and C++.",
        epilog="Anything after -- is passed to the compiler, e.g.  cedt prog.c -- -lm")
    p.add_argument("files", nargs="*", help="C/C++ source file(s) to compile and explain")
    g = p.add_argument_group("compiling")
    g.add_argument("--lang", choices=["auto", "c", "c++"], default="auto", help="language (default: from extension)")
    g.add_argument("--compiler", default="auto", help="gcc, clang, or a compiler command (default: auto-detect)")
    g.add_argument("--std", help="language standard, e.g. c11, c17, c++17")
    g.add_argument("--warnings", choices=["none", "all", "extra"], default="all",
                   help="warning level: all = -Wall (default), extra = -Wall -Wextra")
    g = p.add_argument_group("running the program")
    g.add_argument("--run", action="store_true", help="run the program after a successful build and explain crashes")
    g.add_argument("--input", default=None, help="text to type into the program (stdin) when using --run")
    g.add_argument("--input-file", help="file whose contents are given to the program as input")
    g.add_argument("--timeout", type=float, default=5.0, help="seconds before a running program is stopped (default 5)")
    g.add_argument("--sanitize", action="store_true", help="compile with AddressSanitizer/UBSan for exact crash lines")
    g = p.add_argument_group("explaining existing compiler output")
    g.add_argument("--log", help="file with compiler output to explain ('-' = read from stdin)")
    g.add_argument("--source", action="append", default=[], help="source file belonging to --log (repeatable)")
    g = p.add_argument_group("output")
    g.add_argument("--html", help="also write a stand-alone HTML report to this file")
    g.add_argument("--json", action="store_true", help="print the result as JSON")
    g.add_argument("--raw", action="store_true", help="also show the raw compiler output")
    g.add_argument("--brief", action="store_true", help="shorter explanations")
    g.add_argument("--color", dest="color", action="store_true", default=None, help="force coloured output")
    g.add_argument("--no-color", dest="color", action="store_false", help="disable colours")
    g.add_argument("--no-tips", action="store_true", help="disable CEDT's own beginner checks")
    g = p.add_argument_group("knowledge base and compiler-design views")
    g.add_argument("--explain", metavar="RULE", help="show one knowledge-base rule, e.g. S001")
    g.add_argument("--list-rules", action="store_true", help="list every rule in the knowledge base")
    g.add_argument("--grammar", action="store_true", help="print the LL(1) grammar of compiler output")
    g.add_argument("--trace", metavar="FILE", help="LL(1) parse trace for compiler output in FILE")
    g.add_argument("--tokens", metavar="FILE", help="print the tokens of a C/C++ file")
    g.add_argument("--symbols", metavar="FILE", help="print the symbol table of a C/C++ file")
    g.add_argument("--diag-tokens", metavar="FILE", help="print the tokens of a compiler output file")
    g = p.add_argument_group("web interface")
    g.add_argument("--web", action="store_true", help="start the web interface")
    g.add_argument("--host", default="127.0.0.1")
    g.add_argument("--port", type=int, default=8000)
    g.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    p.add_argument("--version", action="version", version="CEDT %s" % __version__)
    return p


def _read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def cmd_grammar():
    from .diag_parser import grammar
    g = grammar()
    print("LL(1) GRAMMAR OF COMPILER OUTPUT  (terminals = token classes from the diagnostic lexer)\n")
    print(g.format_grammar())
    print("\nFIRST and FOLLOW sets\n")
    print(g.format_sets())
    print("\nPredictive parsing table M[nonterminal, terminal]\n")
    print(g.format_table())
    print("\nLL(1) conflicts: %s" % ("none - the grammar is LL(1)" if g.is_ll1() else "; ".join(g.conflicts)))
    print("\nWith action symbols (syntax-directed translation):\n")
    print(g.format_grammar(with_actions=True))


def cmd_trace(path):
    from .diag_parser import parse_compiler_output
    res = parse_compiler_output(_read(path), trace=True)
    w = max([len(s.stack) for s in res.outcome.trace] + [10])
    w = min(w, 70)
    print("%-*s  %-11s  %s" % (w, "STACK (top at right)", "LOOKAHEAD", "ACTION"))
    print("-" * (w + 40))
    for s in res.outcome.trace:
        stack = s.stack if len(s.stack) <= w else "..." + s.stack[-(w - 3):]
        print("%-*s  %-11s  %s" % (w, stack, s.lookahead, s.action))
    print("\n%d steps, %d diagnostics built, accepted=%s" % (res.outcome.steps, len(res.diagnostics),
                                                            res.outcome.accepted))
    for e in res.errors:
        print("recovered syntax error:", e)


def cmd_tokens(path):
    from .source_lexer import tokenize
    lang = "c++" if os.path.splitext(path)[1].lower() in (".cpp", ".cc", ".cxx") else "c"
    lex = tokenize(_read(path), lang)
    print("%-8s %-11s %s" % ("LINE:COL", "TOKEN", "TEXT"))
    for t in lex.all_tokens:
        text = t.text if len(t.text) < 60 else t.text[:57] + "..."
        print("%-8s %-11s %s%s" % ("%d:%d" % (t.line, t.col), t.kind, text.replace("\n", "\\n"),
                                   ("   <-- " + t.error) if t.error else ""))
    print("\n%d tokens (%d without comments), %d lexical problems" % (
        len(lex.all_tokens), len(lex.tokens), len(lex.errors)))


def cmd_symbols(path):
    from .source import SourceFile
    lang = "c++" if os.path.splitext(path)[1].lower() in (".cpp", ".cc", ".cxx") else "c"
    sf = SourceFile(path, _read(path), lang)
    t = sf.symbols
    print("SCOPES")
    for s in t.scopes:
        depth = len(t.scope_chain(s.id)) - 1
        print("  %s#%d %-9s %-12s lines %s-%s" % ("  " * depth, s.id, s.kind, s.name,
                                                 s.start_line, s.end_line if s.end_line < 10 ** 8 else "end"))
    print("\nSYMBOLS")
    print("  %-14s %-10s %-22s %-6s %-6s %s" % ("NAME", "KIND", "TYPE", "LINE", "SCOPE", "NOTES"))
    for s in t.symbols:
        notes = []
        if s.kind in ("func", "proto", "method") and s.params:
            notes.append("params: " + ", ".join("%s %s" % (p.type, p.name) for p in s.params))
        if s.kind in ("var", "member") and not s.initialized:
            notes.append("not initialised")
        if s.members:
            notes.append("members: " + ", ".join(m.name for m in s.members))
        if s.kind == "macro":
            notes.append("= " + s.value)
        print("  %-14s %-10s %-22s %-6s %-6s %s" % (s.name, s.kind, s.type_str()[:22], s.line, "#%d" % s.scope,
                                                   "; ".join(notes)))
    rep = sf.brackets
    print("\nBRACKETS: %s" % ("balanced" if rep.balanced else "NOT balanced"))
    for i in rep.unclosed:
        print("  unclosed %s at line %d" % (sf.tokens[i].text, sf.tokens[i].line))
    for i in rep.extra:
        print("  extra %s at line %d" % (sf.tokens[i].text, sf.tokens[i].line))


def cmd_diag_tokens(path):
    from .diag_lexer import tokenize
    for t in tokenize(_read(path)):
        extra = {k: v for k, v in t.attrs.items() if k not in ("include_trace", "instantiation_trace") and v}
        print("%-4d %-10s %s" % (t.lineno, t.type, (str(extra) if extra else t.text)[:110]))


def cmd_rules(kbm, rule_id=None):
    if rule_id:
        r = kbm.get(rule_id.upper())
        if r is None:
            print("No rule %s" % rule_id)
            return 2
        print("%s  %s  [%s]" % (r.id, r.title, r.phase))
        print("\nWhat it means:\n  %s" % r.what)
        if r.why:
            print("\nCommon causes:")
            for w in r.why:
                print("  - " + w)
        if r.fix:
            print("\nHow to fix:")
            for w in r.fix:
                print("  - " + w)
        if r.example:
            print("\nWrong:\n" + "\n".join("    " + l for l in r.example.get("wrong", "").split("\n")))
            print("Right:\n" + "\n".join("    " + l for l in r.example.get("right", "").split("\n")))
        print("\nCompiler messages it explains:")
        for s in r.samples:
            print("  " + s)
        return 0
    st = kbm.stats()
    print("Knowledge base: %d rules, %d message patterns (%s)\n" % (
        st["rules"], st["patterns"], ", ".join("%s %d" % kv for kv in sorted(st["per_phase"].items()))))
    for r in sorted(kbm.rules, key=lambda r: r.id):
        print("%-5s %-13s %s" % (r.id, r.phase, r.title))
    return 0


def main(argv=None):
    _stdout_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        k = argv.index("--")
        argv, extra = argv[:k], argv[k + 1:]
    args = build_parser().parse_args(argv)

    if args.web:
        from .web.server import serve
        return serve(args.host, args.port, open_browser=not args.no_browser)
    if args.grammar:
        cmd_grammar()
        return 0
    if args.trace:
        cmd_trace(args.trace)
        return 0
    if args.tokens:
        cmd_tokens(args.tokens)
        return 0
    if args.symbols:
        cmd_symbols(args.symbols)
        return 0
    if args.diag_tokens:
        cmd_diag_tokens(args.diag_tokens)
        return 0
    if args.explain or args.list_rules:
        from . import kb
        return cmd_rules(kb.load(), args.explain)

    from . import core, render_text
    color = args.color
    if color is None:
        color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    if color:
        color = render_text.enable_windows_ansi()

    if args.log:
        sources = {}
        for s in args.source or args.files:
            try:
                sources[s] = _read(s)
            except OSError as e:
                print("cedt: cannot read %s (%s)" % (s, e), file=sys.stderr)
        lang = args.lang if args.lang != "auto" else (
            "c++" if any(os.path.splitext(s)[1].lower() in (".cpp", ".cc", ".cxx") for s in sources) else "c")
        report = core.analyze_log(_read(args.log), sources, lang, prechecks=not args.no_tips)
    else:
        if not args.files:
            build_parser().print_help()
            return 2
        for f in args.files:
            if not os.path.exists(f):
                print("cedt: file not found: %s" % f, file=sys.stderr)
                return 2
        stdin_text = args.input or ""
        if args.input_file:
            stdin_text = _read(args.input_file)
        if args.input is not None:
            stdin_text = stdin_text.replace("\\n", "\n")
            if not stdin_text.endswith("\n"):
                stdin_text += "\n"
        report = core.analyze_files(args.files, lang=args.lang, compiler=args.compiler, std=args.std,
                                    warnings=args.warnings, extra=extra, run=args.run, stdin_text=stdin_text,
                                    sanitize=args.sanitize, timeout=args.timeout, prechecks=not args.no_tips)
    if args.html:
        from .render_html import render_report
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(render_report(report))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(render_text.render(report, color=color, show_raw=args.raw, brief=args.brief))
        if args.html:
            print("HTML report written to %s" % args.html)
    return 0 if report.build_ok else 1


if __name__ == "__main__":
    sys.exit(main())
