"""Regression: `int a[10]; a = x + y;` must be explained as an array, never as a string or a typo."""
import shutil
import unittest

from cedt import core

HAVE = [c for c in ("gcc", "clang") if shutil.which(c)]


@unittest.skipUnless(HAVE, "no C compiler")
class ArrayAssignTests(unittest.TestCase):
    def roots(self, code, comp):
        return [e for e in core.analyze_code(code, "c", compiler=comp).explanations if e.is_root]

    def test_value_into_int_array(self):
        code = "int main() {\n    int a[10];\n    int x=5 , y=10;\n    a=x+y;\n}\n"
        for comp in HAVE:
            e = self.roots(code, comp)[0]
            self.assertEqual(e.rule_id, "M007")
            text = " ".join([e.title, e.what] + e.fix)
            self.assertNotIn("strcpy", text)
            self.assertNotIn("did you mean", text.lower())
            self.assertEqual(e.fixed_line.strip(), "a[0] = x+y;")

    def test_colon_instead_of_semicolon(self):
        code = "int main() {\n    int a[10];\n    int x = 5, y = 10;\n    a = x + y:\n    return 0;\n}\n"
        for comp in HAVE:
            self.assertEqual(self.roots(code, comp)[0].fixed_line.strip(), "a[0] = x + y;")

    def test_string_still_uses_strcpy(self):
        code = "#include <string.h>\nint main() {\n    char name[20];\n    name = \"Ram\";\n    return 0;\n}\n"
        for comp in HAVE:
            self.assertEqual(self.roots(code, comp)[0].fixed_line.strip(), 'strcpy(name, "Ram");')


if __name__ == "__main__":
    unittest.main()
