"""End-to-end tests with the real compilers (skipped when gcc / clang are not installed)."""
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from cedt import cli, core
from cedt.render_html import ordered_roots, render_report

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAMPLES = os.path.join(ROOT, "samples")
with open(os.path.join(SAMPLES, "expected.json"), encoding="utf-8") as fh:
    EXPECTED = json.load(fh)["samples"]


def compilers():
    return [c for c in ("gcc", "clang") if shutil.which(c)]


@unittest.skipUnless(compilers(), "no C compiler installed")
class SampleTests(unittest.TestCase):
    def test_samples_with_every_compiler(self):
        failures = []
        for rel, exp in EXPECTED.items():
            if not exp["rules"]:
                continue
            for comp in compilers():
                rep = core.analyze_files([os.path.join(SAMPLES, rel)], compiler=comp)
                roots = ordered_roots(rep)
                if not roots:
                    failures.append("%s/%s: nothing explained" % (rel, comp))
                    continue
                first = roots[0]
                line = first.real_line or (first.location.line if first.location else None)
                if first.rule_id not in exp["rules"]:
                    failures.append("%s/%s: %s not in %s" % (rel, comp, first.rule_id, exp["rules"]))
                elif exp["line"] is not None and line != exp["line"]:
                    failures.append("%s/%s: line %s != %s" % (rel, comp, line, exp["line"]))
        self.assertEqual(failures, [])

    def test_code_api_and_html(self):
        rep = core.analyze_code('#include <stdio.h>\nint main() {\n    printf("hi")\n    return 0;\n}\n')
        self.assertFalse(rep.build_ok)
        self.assertEqual(ordered_roots(rep)[0].rule_id, "S001")
        html = render_report(rep)
        self.assertIn("Missing semicolon", html)
        self.assertIn("<ins>;</ins>", html)

    def test_clean_program_builds(self):
        rep = core.analyze_code('#include <stdio.h>\nint main() {\n    printf("hi\\n");\n    return 0;\n}\n',
                                run=True)
        self.assertTrue(rep.build_ok)
        self.assertEqual([e for e in rep.explanations if e.is_root], [])
        self.assertEqual(rep.run.stdout, "hi\n")


@unittest.skipUnless(compilers() and os.name != "nt", "needs gcc/clang on Linux or macOS")
class RuntimeTests(unittest.TestCase):
    def run_code(self, code, stdin="", **kw):
        rep = core.analyze_code(code, run=True, stdin_text=stdin, **kw)
        return [e.rule_id for e in rep.explanations if e.source == "runtime"]

    def test_segfault_from_scanf(self):
        code = '#include <stdio.h>\nint main() {\n    int a;\n    scanf("%d", a);\n    printf("%d", a);\n    return 0;\n}\n'
        self.assertEqual(self.run_code(code, "5\n"), ["R001"])

    def test_division_by_zero(self):
        code = '#include <stdio.h>\nint main() {\n    int a, b;\n    scanf("%d %d", &a, &b);\n    printf("%d", a / b);\n    return 0;\n}\n'
        # x86: the CPU traps (SIGFPE -> R002); ARM: it does not, so CEDT's run-time check reports it (R010)
        self.assertIn(self.run_code(code, "10 0\n"), (["R002"], ["R010"]))

    def test_infinite_loop(self):
        code = '#include <stdio.h>\nint main() {\n    int i = 0;\n    while (i < 10) { }\n    return 0;\n}\n'
        self.assertEqual(self.run_code(code, timeout=1.0), ["R006"])


class CliTests(unittest.TestCase):
    def capture(self, args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(args)
        return code, buf.getvalue()

    def test_grammar(self):
        code, out = self.capture(["--grammar"])
        self.assertEqual(code, 0)
        self.assertIn("the grammar is LL(1)", out)

    def test_tokens_and_symbols(self):
        f = os.path.join(SAMPLES, "c", "05_scope.c")
        code, out = self.capture(["--tokens", f])
        self.assertIn("kw", out)
        code, out = self.capture(["--symbols", f])
        self.assertIn("for", out)

    def test_rules(self):
        code, out = self.capture(["--explain", "S001"])
        self.assertIn("Missing semicolon", out)
        code, out = self.capture(["--list-rules"])
        self.assertIn("K001", out)

    def test_log_mode_json(self):
        log = os.path.join(HERE, "fixtures", "probe_outputs", "s02_missing_semicolon_decl.gcc.txt")
        src = os.path.join(HERE, "fixtures", "probe_sources", "s02_missing_semicolon_decl.c")
        code, out = self.capture(["--log", log, "--source", src, "--json"])
        data = json.loads(out)
        roots = [e for e in data["explanations"] if e["is_root"]]
        self.assertEqual(roots[0]["rule_id"], "S001")
        self.assertEqual(roots[0]["real_line"], 3)

    @unittest.skipUnless(compilers(), "no compiler")
    def test_compile_and_html(self):
        tmp = tempfile.mkdtemp()
        try:
            out_html = os.path.join(tmp, "r.html")
            code, out = self.capture([os.path.join(SAMPLES, "c", "12_for_commas.c"), "--no-color", "--html", out_html])
            self.assertEqual(code, 1)
            self.assertIn("Commas instead of semicolons", out)
            self.assertTrue(os.path.getsize(out_html) > 1000)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
