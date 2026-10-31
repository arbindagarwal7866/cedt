#!/usr/bin/env python3
"""
make_heldout.py - writes the HELD-OUT test set (tests/heldout/).

These 30 programs were written AFTER the knowledge base was finished and were
never used to write or tune rules.  Each contains exactly one beginner mistake.
The line of the mistake is marked with '@@' below; the marker is removed when
the file is written and its line number becomes the ground truth.

    python tools/make_heldout.py      # (re)creates tests/heldout/src + expected.json
    python tools/evaluate.py --heldout
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "heldout")

# name: (acceptable rule ids, line known? (or extra acceptable lines), source with @@ on the bug line)
PROGRAMS = {
# h14: the real mistake is the missing `return` on line 7, so line 7 is accepted as well as the closing brace
"h01_bubble_sort.c": (["S001"], True, r"""
#include <stdio.h>

int main() {
    int a[6] = {42, 7, 19, 3, 88, 25};
    int n = 6, i, j, temp;
    for (i = 0; i < n - 1; i++) {
        for (j = 0; j < n - 1 - i; j++) {
            if (a[j] > a[j + 1]) {
@@                temp = a[j]
                a[j] = a[j + 1];
                a[j + 1] = temp;
            }
        }
    }
    for (i = 0; i < n; i++)
        printf("%d ", a[i]);
    printf("\n");
    return 0;
}
"""),
"h02_matrix_multiply.c": (["S002"], True, r"""
#include <stdio.h>

int main() {
    int a[2][2] = {{1, 2}, {3, 4}};
    int b[2][2] = {{5, 6}, {7, 8}};
    int c[2][2];
    for (int i = 0; i < 2; i++) {
        for (int j = 0; j < 2; j++) {
            c[i][j] = 0;
@@            for (int k = 0; k < 2; k++) {
                c[i][j] += a[i][k] * b[k][j];
        }
    }
    for (int i = 0; i < 2; i++) {
        printf("%d %d\n", c[i][0], c[i][1]);
    }
    return 0;
}
"""),
"h03_factorial_after_main.c": (["M002", "M009"], False, r"""
#include <stdio.h>

int main() {
    int n;
    printf("Enter n: ");
    scanf("%d", &n);
@@    printf("%d! = %ld\n", n, fact(n));
    return 0;
}

long fact(int n) {
    if (n <= 1)
        return 1;
    return n * fact(n - 1);
}
"""),
"h04_student_records.c": (["M019"], True, r"""
#include <stdio.h>

struct Student {
    char name[30];
    int marks;
};

void print_student(struct Student *s) {
@@    printf("%s scored %d\n", s.name, s->marks);
}

int main() {
    struct Student st = {"Riya", 91};
    print_student(&st);
    return 0;
}
"""),
"h05_reverse_string.c": (["M002"], True, r"""
#include <stdio.h>

int main() {
    char word[50] = "compiler";
@@    int len = strlen(word);
    for (int i = len - 1; i >= 0; i--)
        putchar(word[i]);
    putchar('\n');
    return 0;
}
"""),
"h06_prime_check.c": (["M006"], True, r"""
#include <stdio.h>

int main() {
    int n = 29, i, is_prime = 1;
    for (i = 2; i * i <= n; i++) {
@@        if (n % i = 0) {
            is_prime = 0;
            break;
        }
    }
    printf("%d is %s\n", n, is_prime ? "prime" : "not prime");
    return 0;
}
"""),
"h07_grade_switch.c": (["M023"], True, r"""
#include <stdio.h>

int main() {
    char grade[3] = "A";
@@    switch (grade) {
        case 'A': printf("Excellent\n"); break;
        case 'B': printf("Good\n"); break;
        default:  printf("Keep going\n");
    }
    return 0;
}
"""),
"h08_average_marks.c": (["T002"], True, r"""
#include <stdio.h>

int main() {
    int marks[4] = {78, 85, 91, 66};
    int sum = 0;
    for (int i = 0; i < 4; i++)
        sum += marks[i];
@@    float avg = sum / 4;
    printf("Average = %.2f\n", avg);
    return 0;
}
"""),
"h09_temperature.c": (["W006"], True, r"""
#include <stdio.h>

int main() {
    double celsius;
    printf("Temperature in C: ");
@@    scanf("%f", &celsius);
    printf("In F: %.1f\n", celsius * 9 / 5 + 32);
    return 0;
}
"""),
"h10_array_total.c": (["W002", "T008"], False, r"""
#include <stdio.h>

int main() {
    int prices[5] = {120, 45, 300, 80, 15};
@@    int total;
    for (int i = 0; i < 5; i++) {
        total += prices[i];
    }
    printf("Total = %d\n", total);
    return 0;
}
"""),
"h11_menu_switch.c": (["T007", "W016"], True, r"""
#include <stdio.h>

int main() {
    int choice = 2;
    switch (choice) {
        case 1:
            printf("Add\n");
            break;
@@        case 2:
            printf("Delete\n");
        case 3:
            printf("Exit\n");
            break;
    }
    return 0;
}
"""),
"h12_square_area.c": (["T006"], True, r"""
#include <stdio.h>

int main() {
    int side = 7;
@@    int area = side ^ 2;
    printf("Area = %d\n", area);
    return 0;
}
"""),
"h13_linked_list.c": (["M002"], True, r"""
#include <stdio.h>

struct Node {
    int data;
    struct Node *next;
};

int main() {
@@    struct Node *head = malloc(sizeof(struct Node));
    head->data = 10;
    head->next = NULL;
    printf("%d\n", head->data);
    return 0;
}
"""),
"h14_gcd.c": (["W004"], [7], r"""
#include <stdio.h>

int gcd(int a, int b) {
    if (b == 0)
        return a;
    else if (a > 0)
        gcd(b, a % b);
@@}

int main() {
    printf("gcd = %d\n", gcd(48, 18));
    return 0;
}
"""),
"h15_palindrome.c": (["W009"], True, r"""
#include <stdio.h>
#include <string.h>

int main() {
    char word[20] = "level", rev[20];
    int n = strlen(word);
    for (int i = 0; i < n; i++)
        rev[i] = word[n - 1 - i];
    rev[n] = '\0';
@@    if (word == rev)
        printf("Palindrome\n");
    else
        printf("Not a palindrome\n");
    return 0;
}
"""),
"h16_count_digits.c": (["T001", "W012", "W011"], True, r"""
#include <stdio.h>

int main() {
    int n = 90210, digits = 0;
@@    while (n > 0);
    {
        n = n / 10;
        digits++;
    }
    printf("Digits: %d\n", digits);
    return 0;
}
"""),
"h17_name_quotes.c": (["L007", "M034"], True, r"""
#include <stdio.h>

int main() {
@@    char name[20] = 'Arbind';
    printf("Hello %s\n", name);
    return 0;
}
"""),
"h18_return_local.c": (["W005"], True, r"""
#include <stdio.h>

char *make_greeting(void) {
    char text[32] = "Good morning";
@@    return text;
}

int main() {
    printf("%s\n", make_greeting());
    return 0;
}
"""),
"h19_dowhile_menu.c": (["S001", "S013"], True, r"""
#include <stdio.h>

int main() {
    int choice;
    do {
        printf("1. Play  2. Quit\n");
        scanf("%d", &choice);
@@    } while (choice != 2)
    printf("Bye\n");
    return 0;
}
"""),
"h20_printf_typo.c": (["M002", "K001"], True, r"""
#include <stdio.h>

int main() {
    int roll = 2640;
@@    prinft("Roll number: %d\n", roll);
    return 0;
}
"""),
"h21_function_header_semicolon.c": (["S008"], True, r"""
#include <stdio.h>

@@int add(int a, int b);
{
    return a + b;
}

int main() {
    printf("%d\n", add(2, 3));
    return 0;
}
"""),
"h22_circle_area.c": (["W006"], True, r"""
#include <stdio.h>

int main() {
    float r = 2.5f;
@@    printf("Area = %d\n", 3.14159 * r * r);
    return 0;
}
"""),
"h23_endl_no_std.cpp": (["M001"], True, r"""
#include <iostream>

int main() {
    int marks = 92;
@@    std::cout << "Marks: " << marks << endl;
    return 0;
}
"""),
"h24_size_without_parens.cpp": (["C008"], True, r"""
#include <iostream>
#include <string>
using namespace std;

int main() {
    string course = "Compiler Design";
@@    cout << "Length: " << course.size << endl;
    return 0;
}
"""),
"h25_bank_private.cpp": (["C004"], True, r"""
#include <iostream>
using namespace std;

class Account {
    double balance;
public:
    Account() { balance = 0; }
    void show() { cout << balance << endl; }
};

int main() {
    Account a;
@@    a.balance = 500;
    a.show();
    return 0;
}
"""),
"h26_vector_push.cpp": (["M021"], True, r"""
#include <iostream>
#include <vector>
using namespace std;

int main() {
    vector<int> v;
@@    v.push(5);
    cout << v.size() << endl;
    return 0;
}
"""),
"h27_string_to_int.cpp": (["C003", "M027"], True, r"""
#include <iostream>
using namespace std;

int main() {
@@    int age = "19";
    cout << age + 1 << endl;
    return 0;
}
"""),
"h28_method_no_type.cpp": (["M003"], True, r"""
#include <iostream>
using namespace std;

class Shape {
public:
@@    display() {
        cout << "Shape" << endl;
    }
};

int main() {
    Shape s;
    s.display();
    return 0;
}
"""),
"h29_cin_extraction.cpp": (["C001"], True, r"""
#include <iostream>
using namespace std;

int main() {
    int a, b;
    cout << "Enter two numbers: ";
@@    cin << a << b;
    cout << a + b << endl;
    return 0;
}
"""),
"h30_class_semicolon.cpp": (["S007"], True, r"""
#include <iostream>
using namespace std;

class Point {
public:
    int x, y;
@@}

int main() {
    Point p;
    p.x = 1; p.y = 2;
    cout << p.x + p.y << endl;
    return 0;
}
"""),
}


def main():
    src_dir = os.path.join(OUT, "src")
    os.makedirs(src_dir, exist_ok=True)
    truth = {}
    for name, (rules, line_known, text) in PROGRAMS.items():
        lines = text.lstrip("\n").split("\n")
        bug = [i + 1 for i, ln in enumerate(lines) if ln.startswith("@@")]
        assert len(bug) == 1, name
        lines = [ln[2:] if ln.startswith("@@") else ln for ln in lines]
        with open(os.path.join(src_dir, name), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        line = bug[0] if line_known else None
        if isinstance(line_known, list):
            line = sorted(set([bug[0]] + line_known))
        truth[name] = {"rules": rules, "line": line}
    with open(os.path.join(OUT, "expected.json"), "w", encoding="utf-8") as fh:
        json.dump({"_comment": "Held-out set: written after the rules were finished, never used for tuning. "
                               "line = line of the mistake (null = compiler dependent).",
                   "programs": truth}, fh, indent=1)
    print("wrote %d programs to %s" % (len(truth), src_dir))


if __name__ == "__main__":
    main()
