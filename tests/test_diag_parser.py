"""Tests for the diagnostic lexer and the LL(1) parser of compiler output."""
import glob
import os
import unittest

from cedt import diag_lexer as L
from cedt.diag_parser import analyze_snippet, detect_compiler_family, grammar, parse_compiler_output

HERE = os.path.dirname(os.path.abspath(__file__))
PROBES = os.path.join(HERE, "fixtures", "probe_outputs")
MANUAL = os.path.join(HERE, "fixtures", "manual")


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


class GrammarTests(unittest.TestCase):
    def test_grammar_is_ll1(self):
        g = grammar()
        self.assertTrue(g.is_ll1(), g.conflicts)

    def test_first_and_follow(self):
        g = grammar()
        self.assertEqual(g.first["Head"], {"ERROR", "FATAL", "WARNING"})
        self.assertIn("ε", g.first["Output"])
        self.assertIn("NOTE", g.first["Followers"])
        self.assertNotIn("NOTE", g.follow["Followers"])     # what makes the grammar LL(1)
        self.assertEqual(g.follow["Output"], {"$"})
        self.assertIn("MAC_SYM", g.follow["MacRefs"])

    def test_table_entries(self):
        g = grammar()
        self.assertEqual(str(g.table["Item"]["CTX"]), "Item -> CTX")
        self.assertEqual(str(g.table["Snip"]["NOTE"]), "Snip -> ε")


class LexerTests(unittest.TestCase):
    def test_token_types(self):
        text = ("prog.c: In function 'main':\n"
                "prog.c:4:5: error: expected ';' before 'return'\n"
                "    4 |     return 0;\n"
                "      |     ^~~~~~\n"
                "prog.c:4:5: note: something\n"
                "/usr/bin/ld: /tmp/x.o: in function `main':\n"
                "prog.c:(.text+0x13): undefined reference to `add'\n"
                "collect2: error: ld returned 1 exit status\n")
        types = [t.type for t in L.tokenize(text)]
        self.assertEqual(types, ["CTX", "ERROR", "SNIP", "SNIP", "NOTE", "LD_CTX", "LD_ERR", "LD_SUMMARY", "$"])

    def test_flag_extraction(self):
        toks = L.tokenize("a.c:3:9: warning: unused variable 'x' [-Wunused-variable]\n")
        self.assertEqual(toks[0].attrs["flag"], "-Wunused-variable")
        self.assertEqual(toks[0].attrs["message"], "unused variable 'x'")

    def test_windows_path(self):
        toks = L.tokenize("C:\\Users\\me\\prog.c:5:5: error: expected ';' before 'return'\n")
        self.assertEqual(toks[0].type, "ERROR")
        self.assertEqual(toks[0].attrs["file"], "C:\\Users\\me\\prog.c")
        self.assertEqual(toks[0].attrs["line"], 5)

    def test_line_without_column(self):
        toks = L.tokenize("prog.c:6: error: expected '{' at end of input\n")
        self.assertEqual(toks[0].attrs["col"], None)

    def test_include_trace_is_attached(self):
        text = ("In file included from prog.c:1:\n"
                "/usr/include/stdio.h:363:12: note: declared here\n")
        toks = L.tokenize(text)
        self.assertEqual(toks[0].type, "NOTE")
        self.assertEqual(toks[0].attrs["include_trace"], [("prog.c", 1)])


class ParserTests(unittest.TestCase):
    def test_all_probe_outputs_parse_cleanly(self):
        files = sorted(glob.glob(os.path.join(PROBES, "*.txt")))
        self.assertGreater(len(files), 200)
        for f in files:
            res = parse_compiler_output(read(f))
            self.assertEqual(res.errors, [], f)
            self.assertEqual(res.other_lines, [], f)
            heads = [t for t in res.tokens if t.type in ("ERROR", "FATAL", "WARNING")]
            compiler = [d for d in res.diagnostics if d.origin == "compiler" and d.severity != "note"]
            self.assertEqual(len(heads), len(compiler), f)

    def test_notes_attach_to_their_error(self):
        res = parse_compiler_output(read(os.path.join(PROBES, "m05_too_few_args.gcc.txt")))
        self.assertEqual(len(res.diagnostics), 1)
        self.assertEqual(res.diagnostics[0].notes[0].message, "declared here")
        self.assertEqual(res.diagnostics[0].context, "In function 'main'")

    def test_snippet_and_fixit(self):
        res = parse_compiler_output(read(os.path.join(PROBES, "m01_undeclared.gcc.txt")))
        info = res.diagnostics[0].extra["snippet_info"]
        self.assertEqual(info["fixit"]["text"], "count")
        self.assertEqual(info["caret"]["col"], 20)
        self.assertIn(5, info["src"])

    def test_classic_snippet_without_gutter(self):
        info = analyze_snippet(["     return 0;", "     ^~~~~~"], 5)
        self.assertEqual(info["src"][5], "     return 0;")
        self.assertEqual(info["caret"]["col"], 6)

    def test_mac_linker(self):
        res = parse_compiler_output(read(os.path.join(MANUAL, "mac_undefined.txt")))
        d = res.diagnostics[0]
        self.assertEqual(d.symbol, "add")
        self.assertEqual(d.message, "undefined reference to 'add'")
        self.assertEqual(d.extra["caller"], "main")

    def test_mac_missing_main(self):
        res = parse_compiler_output(read(os.path.join(MANUAL, "mac_no_main.txt")))
        self.assertEqual(res.diagnostics[0].symbol, "main")

    def test_mingw_formats(self):
        res = parse_compiler_output(read(os.path.join(MANUAL, "mingw_winmain.txt")))
        self.assertEqual(res.diagnostics[0].symbol, "WinMain")
        res = parse_compiler_output(read(os.path.join(MANUAL, "mingw_permission.txt")))
        self.assertEqual(res.diagnostics[0].extra["kind"], "output_locked")
        res = parse_compiler_output(read(os.path.join(MANUAL, "mingw_undefined_oneline.txt")))
        self.assertEqual(res.diagnostics[0].symbol, "add")

    def test_lld(self):
        res = parse_compiler_output(read(os.path.join(MANUAL, "lld_undefined.txt")))
        d = res.diagnostics[0]
        self.assertEqual(d.symbol, "add")
        self.assertEqual(d.location.line, 5)

    def test_colours_and_unicode_quotes(self):
        res = parse_compiler_output(read(os.path.join(MANUAL, "gcc_colored.txt")))
        self.assertEqual(res.diagnostics[0].message, "expected ';' before 'return'")
        res = parse_compiler_output(read(os.path.join(MANUAL, "gcc_utf8_quotes.txt")))
        self.assertIn("'conut' undeclared", res.diagnostics[0].message)

    def test_panic_mode_recovery_keeps_orphan_note(self):
        res = parse_compiler_output(read(os.path.join(MANUAL, "orphan_note.txt")))
        self.assertEqual(len(res.errors), 1)
        self.assertTrue(res.diagnostics[0].extra.get("orphan"))
        self.assertEqual(res.diagnostics[1].severity, "error")

    def test_trace(self):
        res = parse_compiler_output(read(os.path.join(PROBES, "s01_missing_semicolon_stmt.gcc.txt")), trace=True)
        self.assertTrue(res.outcome.accepted)
        self.assertTrue(any(s.action.startswith("match ERROR") for s in res.outcome.trace))
        self.assertEqual(res.outcome.trace[-1].action, "accept")

    def test_compiler_family(self):
        self.assertEqual(detect_compiler_family(read(os.path.join(PROBES, "m01_undeclared.clang.txt"))), "clang")
        self.assertEqual(detect_compiler_family(read(os.path.join(PROBES, "m01_undeclared.gcc.txt"))), "gcc")


if __name__ == "__main__":
    unittest.main()
