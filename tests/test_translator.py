"""Tests for the knowledge base, the handlers, the root-cause analysis and the prechecks."""
import json
import os
import re
import unittest

from cedt import kb as kbmod
from cedt.handlers import REGISTRY
from cedt.render_html import ordered_roots
from cedt.translator import Translator
from cedt.models import Report

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
with open(os.path.join(FIX, "expected.json"), encoding="utf-8") as fh:
    EXPECTED = json.load(fh)["probes"]

TR = Translator()


def explain(name, compiler):
    ext = ".cpp" if name[0] == "c" and name[1].isdigit() else ".c"
    with open(os.path.join(FIX, "probe_sources", name + ext), encoding="utf-8") as fh:
        src = fh.read()
    with open(os.path.join(FIX, "probe_outputs", "%s.%s.txt" % (name, compiler)), encoding="utf-8") as fh:
        out = fh.read()
    exps, parse = TR.explain(out, {name + ext: src}, "c++" if ext == ".cpp" else "c",
                             unit="display" if compiler == "gcc" else "byte")
    rep = Report(files=[name + ext], language="c", compiler={}, command=[], exit_code=None, raw_output=out,
                 explanations=exps, sources={name + ext: src})
    return rep


class KnowledgeBaseTests(unittest.TestCase):
    def test_loads_without_problems(self):
        k = kbmod.load()
        self.assertEqual(k.problems, [])
        self.assertGreaterEqual(len(k.rules), 100)

    def test_every_rule_is_complete(self):
        for r in kbmod.load().rules:
            self.assertTrue(r.title and r.what and r.patterns, r.id)
            self.assertIn(r.phase, kbmod.VALID_PHASES, r.id)
            if r.handler:
                self.assertIn(r.handler, REGISTRY, r.id)

    def test_samples_match_their_rule(self):
        for r in kbmod.load().rules:
            for s in r.samples:
                msg = re.sub(r"\s\[-W[^\]]*\]$", "", s)
                self.assertIsNotNone(r.matches(msg), "%s does not match its sample %r" % (r.id, s))


class ProbeTests(unittest.TestCase):
    def test_root_cause_and_line_for_every_probe(self):
        failures = []
        for name, (rules, line) in EXPECTED.items():
            for comp in ("gcc", "clang"):
                path = os.path.join(FIX, "probe_outputs", "%s.%s.txt" % (name, comp))
                if not os.path.exists(path):
                    continue
                rep = explain(name, comp)
                roots = ordered_roots(rep)
                if not roots:
                    failures.append("%s/%s: no explanation" % (name, comp))
                    continue
                first = roots[0]
                if first.rule_id not in rules:
                    failures.append("%s/%s: got %s, expected %s" % (name, comp, first.rule_id, rules))
                    continue
                got_line = first.real_line or (first.location.line if first.location else None)
                if line is not None and got_line != line:
                    failures.append("%s/%s: line %s, expected %s" % (name, comp, got_line, line))
        self.assertEqual(failures, [])

    def test_no_generic_or_unfilled_explanations(self):
        for name in EXPECTED:
            for comp in ("gcc", "clang"):
                path = os.path.join(FIX, "probe_outputs", "%s.%s.txt" % (name, comp))
                if not os.path.exists(path):
                    continue
                for e in explain(name, comp).explanations:
                    self.assertNotEqual(e.rule_id, "G000", "%s/%s: %s" % (name, comp, e.compiler_message))
                    text = " ".join([e.title, e.what] + e.fix + e.why + e.hints)
                    self.assertIsNone(re.search(r"\{[a-z_]+\}|`\?`| \? ", text), "%s/%s: %s" % (name, comp, text))

    def test_cascade_reduces_noise(self):
        rep = explain("l01_smart_quotes", "gcc")
        self.assertEqual(len([e for e in rep.explanations if e.is_root]), 1)
        self.assertGreaterEqual(len(rep.explanations), 4)
        rep = explain("s14_missing_open_brace", "gcc")
        self.assertEqual(len([e for e in rep.explanations if e.is_root]), 1)

    def test_real_line_correction(self):
        e = ordered_roots(explain("s02_missing_semicolon_decl", "gcc"))[0]
        self.assertEqual((e.location.line, e.real_line), (4, 3))
        self.assertEqual(e.fixed_line, "    int count = 5;")

    def test_fixed_lines(self):
        cases = {
            ("m01_undeclared", "gcc"): '    printf("%d\\n", count);',
            ("m13_scanf_no_amp", "clang"): '    scanf("%d", &age);',
            ("m17_assign_in_if", "gcc"): "    if (x == 5)",
            ("c03_cin_wrong_dir", "gcc"): "    cin >> x;",
            ("l01_smart_quotes", "clang"): '    printf("Hello World");',
            ("l03_invalid_suffix", "gcc"): "    int y = 2 * x + 1;",
            ("s07_for_commas", "gcc"): "    for (i = 0; i < 5; i++) {",
            ("p01_header_typo", "clang"): "#include <stdio.h>",
            ("m20_ptr_dot", "clang"): '    printf("%d\\n", p->x);',
        }
        for (name, comp), want in cases.items():
            e = ordered_roots(explain(name, comp))[0]
            self.assertEqual(e.fixed_line, want, name)

    def test_scope_explanation(self):
        e = ordered_roots(explain("m02_scope", "clang"))[0]
        self.assertIn("for loop", e.what)
        self.assertEqual(e.title, "Variable used outside its block (scope)")


class ManualFixtureTests(unittest.TestCase):
    def test_mac_and_windows_linker(self):
        src = {"prog.c": "#include <stdio.h>\nint add(int a, int b);\nint main() {\n    return add(2, 3);\n}\n"}
        with open(os.path.join(FIX, "manual", "mac_undefined.txt"), encoding="utf-8") as fh:
            exps, _ = TR.explain(fh.read(), src, "c")
        root = [e for e in exps if e.is_root][0]
        self.assertEqual(root.rule_id, "K001")
        self.assertEqual(root.title, "Function declared but never defined")
        with open(os.path.join(FIX, "manual", "mingw_winmain.txt"), encoding="utf-8") as fh:
            exps, _ = TR.explain(fh.read(), {"prog.c": "int mian() { return 0; }\n"}, "c")
        root = [e for e in exps if e.is_root][0]
        self.assertEqual(root.title, "No main() function")
        self.assertEqual(root.fixed_line, "int main() { return 0; }")

    def test_old_gcc_without_gutter(self):
        src = {"C:\\Users\\Arbind\\Desktop\\lab\\prog.c":
               '#include <stdio.h>\nint main() {\n    printf("hi")\n\n    return 0;\n}\n'}
        with open(os.path.join(FIX, "manual", "mingw_old_gcc_semicolon.txt"), encoding="utf-8") as fh:
            exps, _ = TR.explain(fh.read(), src, "c")
        self.assertEqual(exps[0].rule_id, "S001")
        self.assertEqual(exps[0].real_line, 3)

    def test_log_without_source_uses_snippet(self):
        with open(os.path.join(FIX, "probe_outputs", "m01_undeclared.gcc.txt"), encoding="utf-8") as fh:
            exps, _ = TR.explain(fh.read(), {}, "c", unit="auto")
        self.assertEqual(exps[0].rule_id, "M001")
        self.assertIn("count", exps[0].what)


if __name__ == "__main__":
    unittest.main()
