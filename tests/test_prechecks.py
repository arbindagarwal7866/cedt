"""Tests for CEDT's own beginner checks (no compiler involved)."""
import unittest

from cedt import prechecks
from cedt.source import SourceFile


def tips(code, lang="c"):
    sf = SourceFile("t.cpp" if lang == "c++" else "t.c", code, lang)
    return [t.rule_id for t in prechecks.run(sf, lang, [])]


CLEAN_PROGRAMS = [
    # bubble sort
    """#include <stdio.h>
int main() {
    int a[5] = {5, 1, 4, 2, 8}, n = 5;
    for (int i = 0; i < n - 1; i++)
        for (int j = 0; j < n - i - 1; j++)
            if (a[j] > a[j + 1]) {
                int t = a[j];
                a[j] = a[j + 1];
                a[j + 1] = t;
            }
    for (int i = 0; i < n; i++)
        printf("%d ", a[i]);
    return 0;
}
""",
    # factorial with recursion and scanf
    """#include <stdio.h>
long fact(int n) {
    if (n <= 1)
        return 1;
    return n * fact(n - 1);
}
int main() {
    int n;
    scanf("%d", &n);
    printf("%ld\\n", fact(n));
    return 0;
}
""",
    # average with a cast, do-while, switch with breaks
    """#include <stdio.h>
#define SIZE 3
int main() {
    int marks[SIZE] = {70, 80, 90};
    int sum = 0, i = 0, choice = 1;
    do {
        sum += marks[i];
        i++;
    } while (i < SIZE);
    float avg = (float)sum / SIZE;
    switch (choice) {
        case 1: printf("%.2f\\n", avg); break;
        case 2:
        case 3: printf("other\\n"); break;
        default: break;
    }
    return 0;
}
""",
]


class PrecheckTests(unittest.TestCase):
    def test_clean_programs_have_no_tips(self):
        for code in CLEAN_PROGRAMS:
            self.assertEqual(tips(code), [], code)

    def test_empty_body(self):
        self.assertIn("T001", tips("int main(){ int i; for (i = 0; i < 3; i++); { i = 1; } return 0; }"))
        self.assertNotIn("T001", tips("int main(){ int i = 0; do { i++; } while (i < 3); return 0; }"))

    def test_integer_division(self):
        self.assertIn("T002", tips("int main(){ int s = 7, n = 2; float a = s / n; return 0; }"))
        self.assertNotIn("T002", tips("int main(){ int s = 7, n = 2; float a = (float)s / n; return 0; }"))
        self.assertNotIn("T002", tips("int main(){ int s = 7; float a = s / 2.0; return 0; }"))

    def test_define_semicolon(self):
        self.assertIn("T003", tips("#define N 10;\nint main(){ return 0; }"))

    def test_constant_index(self):
        self.assertIn("T004", tips("int main(){ int a[5]; a[5] = 1; return 0; }"))
        self.assertNotIn("T004", tips("int main(){ int a[5]; a[4] = 1; return 0; }"))

    def test_off_by_one(self):
        self.assertIn("T005", tips("int main(){ int a[5], s = 0; for (int i = 0; i <= 5; i++) s += a[i]; return s; }"))
        self.assertNotIn("T005", tips("int main(){ int a[5], s = 0; for (int i = 0; i < 5; i++) s += a[i]; return s; }"))

    def test_xor_power(self):
        self.assertIn("T006", tips("int main(){ int x = 3; int y = x^2; return y; }"))
        self.assertNotIn("T006", tips("int main(){ int x = 3; int y = (x & 1) ^ 2; return y; }"))

    def test_fallthrough(self):
        code = "int f(int x){ switch (x) { case 1: x++; case 2: x--; break; } return x; }"
        self.assertIn("T007", tips(code))
        self.assertNotIn("T007", tips("int f(int x){ switch (x) { case 1: case 2: x--; break; } return x; }"))
        self.assertNotIn("T007", tips("int f(int x){ switch (x) { case 1: x++; /* fallthrough */ case 2: x--; break; } return x; }"))

    def test_uninitialized(self):
        self.assertIn("T008", tips("int main(){ int sum; for (int i = 0; i < 3; i++) sum += i; return sum; }"))
        self.assertNotIn("T008", tips("int main(){ int x; scanf(\"%d\", &x); return x; }"))
        self.assertIn("T008", tips("int main(){ int *p; *p = 5; return 0; }"))
        self.assertNotIn("T008", tips("#include <iostream>\nint main(){ int x; std::cin >> x; return x; }", "c++"))

    def test_nonascii(self):
        self.assertIn("T009", tips("int main(){ int x = 1; return x; }"))

    def test_io_traps(self):
        self.assertIn("T010", tips("#include <stdio.h>\nint main(){ fflush(stdin); return 0; }"))
        self.assertIn("T013", tips("#include <stdio.h>\nint main(){ int x; scanf(\"%d\\n\", &x); return x; }"))
        self.assertIn("T013", tips("#include <stdio.h>\nint main(){ int x; char c; scanf(\"%d\", &x); scanf(\"%c\", &c); return 0; }"))

    def test_float_equality_and_loop_direction(self):
        self.assertIn("T011", tips("int main(){ double d = 0.3; if (d == 0.3) return 1; return 0; }"))
        self.assertIn("T014", tips("int main(){ int s = 0; for (int i = 0; i < 10; i--) s++; return s; }"))


if __name__ == "__main__":
    unittest.main()
