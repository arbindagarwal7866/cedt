"""Regression test on the held-out programs (tests/heldout) using their recorded GCC/Clang output."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import evaluate  # noqa: E402
from cedt import kb as kbmod  # noqa: E402


class HeldOutTests(unittest.TestCase):
    def test_every_heldout_case(self):
        rows = evaluate.run_corpus(evaluate.heldout_items(), kbmod.load())
        self.assertEqual(len(rows), 60)
        bad = ["%s/%s: got %s@%s, expected %s@%s" % (r["probe"], r["compiler"], r["cedt_rule"], r["cedt_line"],
                                                    r["expected_rules"], r["expected_line"])
               for r in rows if not r["rule_ok"] or r["cedt_line_ok"] is False]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
