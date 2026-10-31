"""Tests for CEDT's own analysis of the student's program: lexer, symbol table, brackets."""
import os
import unittest

from cedt import brackets as B
from cedt.source import SourceFile
from cedt.source_lexer import classify_number, tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "fixtures", "probe_sources")


def load(name):
    lang = "c++" if name.endswith(".cpp") else "c"
    with open(os.path.join(SRC, name), encoding="utf-8") as fh:
        return SourceFile(name, fh.read(), lang)


class NumberDFATests(unittest.TestCase):
    def test_valid_numbers(self):
        for text, kind in [("0", "int"), ("42", "int"), ("0x1F", "int"), ("0b101", "int"), ("017", "int"),
                           ("10UL", "int"), ("3.14", "float"), ("3.14f", "float"), (".5", "float"),
                           ("1e10", "float"), ("2.5e-3", "float"), ("08.5", "float")]:
            self.assertEqual(classify_number(text), (kind, None), text)

    def test_invalid_numbers(self):
        self.assertEqual(classify_number("08")[0], "bad")
        self.assertIn("octal", classify_number("09")[1])
        self.assertIn("suffix 'x'", classify_number("2x")[1])
        self.assertEqual(classify_number("0x")[0], "bad")
        self.assertEqual(classify_number("1e")[0], "bad")


class LexerTests(unittest.TestCase):
    def test_maximal_munch(self):
        toks = [t.text for t in tokenize("a >>= b->c ... x<<=1;").tokens]
        self.assertEqual(toks, ["a", ">>=", "b", "->", "c", "...", "x", "<<=", "1", ";"])

    def test_keywords_identifiers_literals(self):
        lex = tokenize('int main() { char c = \'a\'; printf("%d\\n", c); }')
        kinds = [(t.kind, t.text) for t in lex.tokens[:3]]
        self.assertEqual(kinds, [("kw", "int"), ("id", "main"), ("op", "(")])
        self.assertTrue(any(t.kind == "char" for t in lex.tokens))
        self.assertTrue(any(t.kind == "str" for t in lex.tokens))

    def test_preprocessor_and_comments(self):
        lex = tokenize("#include <stdio.h>\n/* c */ int x; // end\n")
        self.assertEqual(lex.tokens[0].kind, "pp")
        self.assertEqual(sum(1 for t in lex.all_tokens if t.kind == "comment"), 2)
        self.assertNotIn("comment", [t.kind for t in lex.tokens])

    def test_lexical_errors(self):
        lex = tokenize('printf("Hello);\nchar c = \'\';\n/* open')
        kinds = [t.kind for t in lex.errors]
        self.assertIn("bad_str", kinds)
        self.assertIn("bad_comment", kinds)
        self.assertTrue(any(t.error == "empty character constant" for t in lex.errors))

    def test_smart_quotes_are_flagged(self):
        lex = tokenize("printf(“Hi”);")
        self.assertEqual([t.kind for t in lex.errors], ["nonascii", "nonascii"])

    def test_positions(self):
        lex = tokenize("int a;\n  int b;")
        b = [t for t in lex.tokens if t.text == "b"][0]
        self.assertEqual((b.line, b.col), (2, 7))


class SymbolTableTests(unittest.TestCase):
    def test_for_loop_scope(self):
        sf = load("m02_scope.c")
        i = sf.symbols.declarations("i")[0]
        self.assertEqual(sf.symbols.scopes[i.scope].kind, "for")
        use = [u for u in sf.symbols.uses if u.name == "i" and u.line == 6][0]
        self.assertIsNone(sf.symbols.lookup("i", use.tok))

    def test_function_params_and_prototypes(self):
        sf = load("m05_too_few_args.c")
        f, p = sf.symbols.function_named("add")
        self.assertEqual([x.name for x in f.params], ["a", "b"])
        self.assertIsNone(p)
        sf = load("k01_undefined_ref.c")
        f, p = sf.symbols.function_named("add")
        self.assertIsNone(f)
        self.assertEqual(len(p.params), 2)

    def test_struct_members(self):
        sf = load("m22_no_member.c")
        st = sf.symbols.struct_named("Student")
        self.assertEqual([m.name for m in st.members], ["age", "name"])
        self.assertEqual(st.members[1].array_sizes, [20])

    def test_macro_array_size(self):
        sf = load("p05_define_semicolon.c")
        a = sf.symbols.declarations("a")[0]
        self.assertEqual(a.array_sizes, [10])
        self.assertEqual(sf.symbols.macros["SIZE"].value, "10;")

    def test_uses(self):
        sf = SourceFile("t.c", "int main(){ int x; int y; scanf(\"%d\", &x); y = 2; return x + y; }")
        xs = [u for u in sf.symbols.uses if u.name == "x"]
        self.assertTrue(xs[0].address_taken)
        ys = [u for u in sf.symbols.uses if u.name == "y"]
        self.assertTrue(ys[0].is_write)

    def test_cpp_types_and_classes(self):
        sf = load("c07_class_no_semicolon.cpp")
        self.assertEqual([m.name for m in sf.symbols.struct_named("Box").members], ["w"])
        sf = SourceFile("t.cpp", "#include <vector>\nint main(){ std::vector<int> v; for (int x : v) {} }", "c++")
        v = sf.symbols.declarations("v")[0]
        self.assertIn("vector", v.type)
        self.assertTrue(sf.symbols.declarations("x")[0].initialized)


class BracketTests(unittest.TestCase):
    def test_missing_brace_is_located_by_indentation(self):
        sf = load("s03_missing_close_brace.c")
        g = B.guess_missing_close(sf.tokens, sf.lines, sf.brackets)
        self.assertEqual(sf.tokens[g].line, 4)
        self.assertEqual(B.describe_opener(sf.tokens, g, sf.lines), "the 'if' block")

    def test_extra_brace(self):
        sf = load("s04_extra_close_brace.c")
        g = B.guess_extra_close(sf.tokens, sf.lines, sf.brackets)
        self.assertEqual(sf.tokens[g].line, 7)

    def test_balanced(self):
        sf = load("m01_undeclared.c")
        self.assertTrue(sf.brackets.balanced)


if __name__ == "__main__":
    unittest.main()
