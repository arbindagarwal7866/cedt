# CEDT — Review & Viva Guide

Project 16 · BCSE307L Compiler Design · Review 21.10.2026
Every number here comes from `python tools/evaluate.py --heldout --live` (see `docs/evaluation.md`).

---

## 1. The 60-second pitch

> "When a beginner forgets one semicolon, GCC prints five messages, all on the wrong line, and two of them
> complain about a correct `for` loop. Our project, CEDT, sits on top of the real GCC or Clang — we don't modify
> the compiler. CEDT treats the compiler's output as a language: it tokenizes it with a Lex-style lexer, parses it
> with an LL(1) grammar we built, and then does semantic analysis by matching each diagnostic against 132 rules
> while reading the student's code with a DFA lexer, a bracket stack and a symbol table. The student gets the real
> line, the root cause, a plain explanation and a corrected line. On 30 programs it had never seen, CEDT pointed at
> the right line every time — the compiler only 82% of the time — and it adds about one millisecond per build."

## 2. Suggested split for presenting (edit to match who built what)

**Simple deck — "CEDT – Review Presentation" (20 slides):**

| Part | Slides | Presenter |
|---|---|---|
| Title, introduction, example, problem, objectives, literature survey | 1–7 | [name] |
| Proposed solution, architecture, compiler design concepts, before/after | 8–11 | [name] |
| Features, implementation, demo, testing | 12–15 | [name] |
| Results, limitations, conclusion, references | 16–20 | [name] |

**Detailed deck — "CEDT — Project Review Deck" (21 slides):**

| Part | Slides | Presenter |
|---|---|---|
| Problem, related work, objectives | 1–5 | [name] |
| Key idea, architecture, syllabus mapping, LL(1) | 6–9 | [name] |
| Source analysis, knowledge base, cascade, silent bugs | 10–13 | [name] |
| Demo, evaluation, results, limitations | 14–21 | [name] |

## 3. Live demo script (about 4 minutes)

Start: `python3 cedt.py --web` (Mac/Linux) or `python cedt.py --web` (Windows). Opens http://127.0.0.1:8000.
No internet needed. If the browser does not open, type the address.

| Step | Do this | Point out |
|---|---|---|
| 1 | Sample **"Missing semicolon - compiler blames the wrong line"** → *Compile and explain* | "the compiler pointed at line 7" — CEDT says line 6; corrected line; "4 more messages caused by this problem" |
| 2 | Sample **"One mistake, many compiler messages"** | 6 compiler messages → 1 root problem, caught by the **Lexer** phase; the quote goes before the comma |
| 3 | Sample **"Missing } - which brace?"** | GCC says line 16 (end of file); CEDT finds the unclosed `else {` on line 8 |
| 4 | Switch to **C++**, sample **"cin << instead of cin >> (a 120-line C++ error)"** | jargon `no match for 'operator<<'` becomes "cin used with << (should be >>)" |
| 5 | Sample **"Bugs the compiler does not report"** | compiler prints **nothing**; CEDT shows tips |
| 6 | Sample **"Division by zero at run time"**, tick *Run the program*, input `10 0` | "Floating point exception" explained as integer ÷ 0; tick *sanitizers* for the exact line |
| 7 | Tab **Inside CEDT** | tokens of the compiler output, LL(1) parse trace, FIRST/FOLLOW, symbol table |
| 8 | Terminal: `python3 cedt.py --grammar` | grammar, FIRST/FOLLOW sets, parsing table, "no conflicts" |

**Backup if the laptop has no gcc/clang:** explain recorded compiler output instead:
```
python3 cedt.py --log tests/fixtures/probe_outputs/s02_missing_semicolon_decl.gcc.txt --source tests/fixtures/probe_sources/s02_missing_semicolon_decl.c
```

---

## 4. Likely questions — with answers

### A. The idea

**Q1. Explain your project in one line.**
A layer on top of GCC/Clang that parses the compiler's error output like a program and explains each error in plain
language, with the real line, the root cause and a corrected line.

**Q2. Why not modify GCC, or just tell students to use Clang?**
Students use whatever their lab or IDE ships — usually GCC via Code::Blocks/MinGW. Changing a compiler means
maintaining a fork. Clang's messages are better formatted but still jargon, and on our tests Clang's first message
was on the wrong line just as often as GCC's (85.9% right for both on the development set). CEDT works with both,
unchanged.

**Q3. Where exactly is the compiler design in this project?**

| Syllabus topic | In CEDT |
|---|---|
| Phases of a compiler | Every explanation names the phase that caught the error (preprocessor → lexer → parser → semantic → flow → linker → run) |
| Regular expressions, Lex | Diagnostic lexer: prioritised regex classes, first match wins, start conditions |
| DFA | C/C++ source lexer; numbers recognised by a table-driven DFA |
| CFG, FIRST/FOLLOW, LL(1) | Our own LL(1) parser generator (`ll1.py`) parses compiler output |
| Syntax-directed translation | Action symbols (`@diag`, `@snip`, `@note`) build the diagnostic tree while parsing |
| Error recovery | Panic mode in our parser; and the cascade analysis explains GCC's own panic-mode avalanches |
| Pushdown automaton | Bracket matcher (stack) |
| Symbol table, scopes | Scope-aware symbol table for "did you mean", scope and use-before-declaration |
| Type checking, data flow | Handlers and prechecks (`%d` vs double, uninitialised variable, missing `break`) |

### B. Lexing and parsing the compiler's output

**Q4. Why do you need a parser? Isn't regex on each line enough?**
Compiler output is nested: an error is followed by its source snippet, caret line, fix-it line and its notes, and
each note has its own snippet; linker errors come as multi-line blocks (macOS: "Undefined symbols" + symbol +
references). A regex sees one line; the grammar groups lines into a tree, so a note is attached to the right error.
It also gives us error recovery for lines we have never seen.

**Q5. What are start conditions in your lexer?**
Like Lex's `%x` states. After an error line the lexer enters `SNIPPET` state, where an otherwise unknown line
(source line, `^~~~` caret line, fix-it) becomes a `SNIP` token. After macOS's "Undefined symbols for architecture"
it enters `MACLINK`; `LLDREF` handles LLVM lld's `>>> referenced by` lines. Same text, different token,
depending on the state — exactly what start conditions are for.

**Q6. Show your grammar. Why is it LL(1)?**
```
Output    -> Item Output | ε
Item      -> Diag | CTX | LD_CTX | LD_ERR LldRefs | LD_SUMMARY | MAC_HDR MacSyms | MAC_DUP MacRefs | DRIVER | SUMMARY | TEXT
Diag      -> Head Snip Followers
Head      -> ERROR | FATAL | WARNING
Snip      -> SNIP Snip | ε
Followers -> NOTE Snip Followers | ε
```
17 terminals, 9 nonterminals, 26 productions. `ll1.py` builds the table and finds **0 conflicts**.
The only places a conflict could happen are the ε-productions:

| Nonterminal | FIRST of the non-ε choice | FOLLOW (used for the ε choice) | Overlap? |
|---|---|---|---|
| Snip | { SNIP } | { NOTE, ERROR, FATAL, WARNING, CTX, LD_*, MAC_*, DRIVER, SUMMARY, TEXT, $ } | none — SNIP is not in FOLLOW |
| Followers | { NOTE } | { ERROR, FATAL, WARNING, CTX, LD_*, MAC_*, DRIVER, SUMMARY, TEXT, $ } | none — NOTE is not in FOLLOW |

Simple mein: *SNIP aaye toh snippet continue, NOTE aaye toh note — warna ε lo. Dono cases kabhi same token pe nahi
takraate, isliye LL(1).*

**Q7. How does your parser recover from an unexpected token?**
Panic mode with FOLLOW sets as the synchronising set (Dragon Book §4.4): if `M[A, a]` is blank and `a` is in
FOLLOW(A), pop A (as if A derived ε); otherwise skip the input token `a`. Unknown lines are already `TEXT` tokens,
so recovery is needed only for genuinely broken output — e.g. a log copied from the middle, starting with a note
whose error was cut off. Try `python3 cedt.py --trace tests/fixtures/manual/orphan_note.txt`: it prints
"recovered syntax error: line 1: no rule for Output on NOTE", and the note is still kept (as an orphan) and explained.

**Q8. What is syntax-directed translation here?**
Symbols starting with `@` in the grammar are action symbols. When one reaches the top of the stack, a Python
function runs with the token just matched: `@diag` creates a Diagnostic, `@snip` attaches a snippet line to it,
`@note` attaches a note. The parse tree is never stored — the actions build the Diagnostic tree directly.

**Q9. Show a parse trace.** `python3 cedt.py --trace errors.txt`
```
STACK (top at right)           LOOKAHEAD    ACTION
$ Output                       CTX          Output -> Item Output
$ Output Item                  CTX          Item -> CTX
$ Output CTX                   CTX          match CTX
$ Output                       ERROR        Output -> Item Output
$ Output Item                  ERROR        Item -> Diag
$ Output Diag                  ERROR        Diag -> Head Snip Followers
$ Output Followers Snip Head   ERROR        Head -> ERROR
$ Output Followers Snip ERROR  ERROR        match ERROR
$ Output Followers Snip        SNIP         Snip -> SNIP Snip
...
$                              $            accept
```

### C. Reading the student's code

**Q10. Why does GCC report a missing semicolon on the next line? How do you find the real line?**
The parser can only know a `;` is missing when it reads the next token — `int total = 0` followed by `for`. The
error position is that next token. CEDT's handler takes the token the compiler pointed at, looks at the token
just before it in our own token stream, and puts the `;` right after that token — so the real line is the line
where the previous token ends.
Simple mein: *compiler ek token aage padh ke hi samajhta hai ki `;` missing hai, isliye agli line batata hai —
hum ek token peeche jaake asli line nikaalte hain.*

**Q11. How do you find which brace is missing?**
A stack: push every `(`, `[`, `{`; pop on the matching closer. Left on the stack = unclosed; a closer on an empty
stack = extra; wrong kind = mismatch. That is a pushdown automaton for balanced brackets. Then an indentation
heuristic: a `}` indented like an OUTER block probably belongs to that outer block, so the inner `{` it popped is
the one really missing its partner. GCC can only say "expected declaration or statement at end of input" (last
line); CEDT names the unclosed `{` (sample 02: line 8 instead of line 16).

**Q12. How does the symbol table work?**
One pass over the tokens with a stack of scopes: file → function (parameters live here) → block → `for` scope.
Every declaration is stored with type, line, scope and array size; every use is recorded. Lookup walks the scope
chain outwards. When GCC says "`i` undeclared", CEDT can see that `i` exists but in a `for` scope that ended on
line 8 → "Variable used outside its block".

**Q13. How do "did you mean" suggestions work?**
Optimal String Alignment distance (Levenshtein plus swapping two adjacent letters, so `mian` → `main` costs 1)
against the names visible at that point. Allowed distance grows with length: 1 for names up to 3 letters,
2 up to 6, 3 beyond. A difference only in upper/lower case always wins (`Printf` → `printf`).

**Q14. Explain the number DFA.**
States: START, ZERO, DEC, OCT, OCT_BAD, HEX_PRE, HEX, HEX_FRAC, BIN_PRE, BIN, DOT, FRAC, EXP, EXP_SIGN, EXP_DIG.
Accepting: ZERO/DEC/OCT/HEX/BIN = integer, FRAC/EXP_DIG = float, OCT_BAD = "invalid octal". After the DFA stops,
the rest must be a legal suffix (`u`, `l`, `ll`, `f`, …).
- `08` → ZERO → OCT_BAD → "invalid digit 8 in octal constant — remove the leading 0".
- `2x` → DEC, then `x` has no transition, suffix `x` is illegal → "In maths 2x means 2 × x; C needs `2 * x`".

### D. Knowledge base, cascade, silent bugs, runtime

**Q15. How is a compiler message matched to an explanation?**
132 rules in JSON, one file per phase, 412 regex patterns (GCC and Clang word the same error differently). Rules are
tried in priority order; regex named groups become template variables. 76 rules have a handler — a Python
function that reads the source and can set the real line, write a corrected line, override the text, **veto**
the rule (try the next one) or **redirect** to another rule. Templates are then filled
(`Add ; at the end of line {real_line}` → `line 6`). A new rule needs no Python code.

**Q16. GCC 9 vs GCC 13 vs Clang vs MinGW — how do you cope?**
Several patterns per rule; the lexer normalises colours, Unicode quotes, Windows paths, CRLF, and column units
(GCC counts display columns, Clang counts bytes); the test suite stores real outputs of both compilers plus
manual fixtures for MinGW, macOS and old GCC without the `|` gutter.

**Q17. What happens when no rule matches?**
A generic explanation (rule G000): if the message is "expected X before Y" it is decomposed into plain words, the
compiler's own fix-it hint is applied to the line, and the student is told to fix the first error first. On the
held-out set that happened for 1.5% of messages.

**Q18. What is cascade analysis? Why do compilers print so many errors?**
After an error, GCC/Clang recover in panic mode — skip tokens to a `;` or `}` and continue. The skipped code
leaves holes (undeclared names, statements outside functions), and each hole is a new message. CEDT applies 8
heuristics in order: linker summaries and library-header messages; duplicates; same line as an earlier root;
syntax errors just after a syntax/lexical error; "x undeclared" when x's declaration failed; implicit declaration →
undefined reference; several functions from one missing header; warnings caused by an earlier error. Result:
27.9% fewer messages to read.

**Q19. Which bugs do you catch that the compiler doesn't? Can these checks be wrong?**
15 checks: `;` after `if/while/for`, integer division into a float, `;` after `#define`, constant index out of
bounds, off-by-one `i <= N`, `^` used as power, `case` without `break`, read before assignment, invisible
characters, `fflush(stdin)`, `==` with decimals, `<conio.h>`, `scanf` traps, loop counter moving the wrong way, and a missing `;` the compiler has not reported yet.
They are heuristics, so they are shown as **tips**, and each one stays silent when unsure. Caught 17 of 17 silent
bugs in our tests.

**Q20. How does the crash explanation work?**
With `--run`, CEDT runs the program with the given input and a timeout. On Linux/macOS a crash shows up as a
negative return code = the signal (SIGSEGV, SIGFPE, SIGABRT…); on Windows as a status code (0xC0000005 access
violation, 0xC0000094 integer divide by zero). A timeout means an infinite loop or a program waiting for input.
`--sanitize` recompiles with AddressSanitizer/UBSan, whose report gives the exact line.

### E. Evaluation and honesty

**Q21. How did you evaluate it?**
Two sets of real GCC 13.3 + Clang 18.1 output. Development: 138 programs × 2 compilers = 276 cases, one planted
mistake each. Held-out: 30 new lab-style programs × 2 = 60 cases, written after the rules were frozen, with the
correct answer fixed before running CEDT. Baseline = the compiler's own first message.

**Q22. 100% accuracy — isn't that suspicious?**
Yes, which is why we built a held-out set. On the development set the rules were written while looking at the
programs, so 100% shows coverage, not generalisation. On the blind held-out run CEDT found the root cause in
**95.0%** of cases: two messages had no rule (array comparison with `==`, and Clang 18's "a type specifier is
required for all declarations"). We added those rules afterwards and report both numbers; the blind result is
frozen in `docs/evaluation_heldout_blind_run.md`. Also: planted single mistakes are easier than real code, and we
measured accuracy, not learning — that needs a classroom study.

**Q23. Why rule-based and not ML / an LLM?**
Deterministic, explainable (every explanation traces to one rule), works offline, ~1 ms per program, and cannot
invent a wrong fix. An LLM fallback for the 1.5% unmatched messages, constrained by our rules, is future work.

**Q24. Complexity / performance?**
Lexing and LL(1) parsing are linear in the number of output lines. Rule matching is (diagnostics × patterns) regex
tests — a handful of diagnostics × 412 patterns. Source analysis is linear in tokens. Measured: ~1 ms per program,
while the compiler itself takes ~140 ms.

**Q25. Limitations?**
Rule-based coverage; long C++ template errors are only summarised; silent-bug checks can false-alarm; English only;
evaluated on planted mistakes, not with real students. Next: lab study, VS Code / Code::Blocks integration,
Hindi/Hinglish explanations, LLM fallback.

---

## 5. Cheat sheet

| Number | Meaning |
|---|---|
| 82.1% → **100%** | right line, held-out (compiler vs CEDT) |
| 85.9% → **100%** | right line, development set |
| 61.1% | compiler's right-line rate for **syntax** errors (39% wrong) |
| **48 / 48** | wrong-line reports corrected (38 dev + 10 held-out) |
| 377 → **272** (−27.9%) | messages → problems to read, development set (held-out −16.9%) |
| **17 / 17** | silent bugs found (compiler: 0) |
| **95.0%** blind → 100% | held-out root-cause accuracy before/after adding 2 rules |
| 93.9% → 98.5% | held-out rule coverage before/after |
| 54.4 → **84.4** | Flesch Reading Ease (dev); held-out 57.8 → 85.1 |
| **~1 ms** vs ~140 ms | CEDT time vs compiler time per program |
| 132 / 412 / 83 | rules / regex patterns / handlers |
| 14 / 11 | silent-bug checks / run-time explanations |
| 17 / 9 / 26 / 0 | grammar terminals / nonterminals / productions / conflicts |
| 138×2, 30×2, 36×2 | development, held-out, demo cases |
| 73 | unit tests (pass on Python 3.8, 3.9, 3.13) |

| Module | One line |
|---|---|
| `diag_lexer.py` | compiler output → tokens (regex + start conditions) |
| `ll1.py` | FIRST, FOLLOW, table, predictive parser, panic mode |
| `diag_parser.py` | grammar + action symbols → Diagnostic tree |
| `source_lexer.py` | C/C++ tokens, number DFA |
| `brackets.py` | bracket stack + indentation heuristic |
| `symbols.py` | scope-aware symbol table |
| `kb.py` + `data/rules/` | 132 rules as JSON |
| `handlers/` | rule logic that reads the source |
| `prechecks.py` | 14 silent-bug checks |
| `cascade.py` | root cause vs follow-on |
| `runtime.py` | run + crash explanations |
| `translator.py` / `core.py` | the pipeline / public API |
| `cli.py`, `web/` | command line, web UI |
