"""
runtime.py - optional RUN step: execute the compiled program and explain
crashes in plain language (segmentation fault, division by zero, stack
smashing, infinite loops, sanitizer reports ...).

This goes one step beyond compile-time diagnostics: many beginner programs
compile fine and then crash, and the operating system's message
("Segmentation fault (core dumped)") is even less helpful than GCC's.
"""
import os
import re
import signal
import subprocess
import time

from .models import Explanation, Location, RunResult

MAX_OUTPUT = 20000
WINDOWS_CODES = {
    0xC0000005: "ACCESS_VIOLATION",
    0xC0000094: "INT_DIVIDE_BY_ZERO",
    0xC00000FD: "STACK_OVERFLOW",
    0xC0000409: "STACK_BUFFER_OVERRUN",
    0xC000008E: "FLT_DIVIDE_BY_ZERO",
    0xC0000374: "HEAP_CORRUPTION",
}


def run_program(exe, stdin_text="", timeout=5.0, cwd=None, env=None):
    r = RunResult(ran=True)
    t0 = time.perf_counter()
    try:
        p = subprocess.run([exe], input=stdin_text or "", capture_output=True, text=True,
                           timeout=timeout, errors="replace", cwd=cwd, env=env)
        r.exit_code = p.returncode
        r.stdout = (p.stdout or "")[:MAX_OUTPUT]
        r.stderr = (p.stderr or "")[:MAX_OUTPUT]
    except subprocess.TimeoutExpired as e:
        r.timed_out = True
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        r.stdout = out[:MAX_OUTPUT]
    except OSError as e:
        r.ran = False
        r.note = "Could not run the program: %s" % e
    r.duration_ms = (time.perf_counter() - t0) * 1000
    if r.exit_code is not None:
        if r.exit_code < 0:
            try:
                r.signal_name = signal.Signals(-r.exit_code).name
            except ValueError:
                r.signal_name = "SIGNAL %d" % -r.exit_code
        elif r.exit_code > 128 and r.exit_code < 160 and os.name != "nt":
            try:
                r.signal_name = signal.Signals(r.exit_code - 128).name
            except ValueError:
                pass
        elif os.name == "nt" or r.exit_code > 0xC0000000:
            code = r.exit_code & 0xFFFFFFFF
            if code in WINDOWS_CODES:
                r.signal_name = WINDOWS_CODES[code]
    return r


def _uses_input(src):
    if src is None:
        return False
    return any(t.kind == "id" and t.text in ("scanf", "getchar", "gets", "fgets", "cin", "getline", "getch")
               for t in src.tokens)


def _recursive_functions(src):
    out = []
    if src is None:
        return out
    for s in src.symbols.scopes:
        if s.kind != "function":
            continue
        for t in src.tokens[s.start:s.end]:
            n = src.next_token(t)
            if t.kind == "id" and t.text == s.name and n is not None and n.is_op("("):
                out.append(s.name)
                break
    return out


def _hints_from_exps(exps, rule_ids):
    hints = []
    for e in exps:
        if e.rule_id in rule_ids or any(e.title.startswith(x) for x in rule_ids):
            ln = e.real_line or (e.location.line if e.location else None)
            hints.append("Likely cause - line %s: %s" % (ln, e.title))
    return hints


def _sanitizer(stderr, src_path):
    """Parse the first UBSan / ASan report into (kind, line, message)."""
    m = re.search(r"^(?P<file>[^\s:]+):(?P<line>\d+):(?P<col>\d+): runtime error: (?P<msg>.+)$", stderr, re.M)
    if m:
        return "ubsan", int(m.group("line")), m.group("msg").strip()
    m = re.search(r"ERROR: AddressSanitizer: (?P<kind>[\w-]+)", stderr)
    if m:
        kind = m.group("kind")
        line = None
        base = os.path.basename(src_path) if src_path else None
        for fm in re.finditer(r"#\d+ 0x[0-9a-f]+ in (?P<func>\S+) (?P<file>\S+?):(?P<line>\d+)", stderr):
            if base and os.path.basename(fm.group("file")) == base:
                line = int(fm.group("line"))
                break
        return "asan", line, kind
    if "LeakSanitizer: detected memory leaks" in stderr:
        return "leak", None, "memory leak"
    return None


SAN_TEXT = {
    "stack-buffer-overflow": "the program read/wrote past the end of a local array",
    "heap-buffer-overflow": "the program read/wrote past the end of memory allocated with malloc/new",
    "global-buffer-overflow": "the program read/wrote past the end of a global array",
    "stack-use-after-return": "the program used a pointer to a local variable of a function that already returned",
    "heap-use-after-free": "the program used memory after it was freed",
    "attempting double-free": "the same memory was freed twice",
    "SEGV": "the program accessed an invalid memory address (often a NULL or garbage pointer)",
    "FPE": "an arithmetic error such as integer division by zero",
    "stack-overflow": "the call stack ran out of space (usually endless recursion)",
}


def explain_run(run, src=None, exps=None, src_path=None, stdin_text=""):
    """Turn a RunResult into a list of Explanation objects (empty if all OK)."""
    exps = exps or []
    out = []
    path = src_path or (src.path if src is not None else "program")

    def mk(rule, title, what, why=None, fix=None, hints=None, line=None, level="error"):
        e = Explanation(rule_id=rule, title=title, phase="runtime", level=level, what=what,
                        why=why or [], fix=fix or [], hints=hints or [],
                        location=Location(path, line or 0, None) if line else None,
                        compiler_message=("(program crashed while running - %s)" % (
                            run.signal_name or ("timeout" if run.timed_out else "exit code %s" % run.exit_code))
                            if run.signal_name or run.timed_out or run.exit_code
                            else "(found by a run-time check while the program was running)"),
                        source="runtime", confidence="medium")
        out.append(e)
        return e

    san = _sanitizer(run.stderr or "", path) if run.stderr else None
    if san:
        kind, line, msg = san
        if kind == "ubsan":
            m = re.search(r"index (-?\d+) out of bounds for type '([^']+)'", msg)
            if m:
                mk("R010", "Array index out of bounds (detected at run time)",
                   "On line %s the program used index %s on an array of type `%s` - outside the array." % (
                       line, m.group(1), m.group(2)),
                   fix=["Valid indexes are 0 to size-1. Check loop conditions (`<` not `<=`)."], line=line)
            elif "division by zero" in msg:
                mk("R010", "Division by zero (detected at run time)",
                   "Line %s divided by zero. The divisor came from your input or a calculation." % line,
                   fix=["Check the divisor before dividing: `if (b != 0) ...`."], line=line)
            elif "signed integer overflow" in msg:
                mk("R010", "Integer overflow", "Line %s produced a number too large for its type (%s)." % (line, msg),
                   fix=["Use a bigger type such as `long long`."], line=line)
            elif "null pointer" in msg:
                mk("R010", "NULL pointer used", "Line %s used a NULL pointer (%s)." % (line, msg),
                   fix=["Make sure the pointer points to valid memory before using it."], line=line)
            else:
                mk("R010", "Undefined behaviour detected", "Line %s: %s." % (line, msg), line=line)
            return out
        if kind == "asan":
            desc = SAN_TEXT.get(msg, msg)
            mk("R011", "Memory error: %s" % msg,
               "AddressSanitizer stopped the program%s: %s." % (" at line %s" % line if line else "", desc),
               fix=["Check array sizes, loop bounds and pointer use around that line."], line=line)
            return out
    if run.timed_out:
        if _uses_input(src) and not (stdin_text or "").strip():
            mk("R006", "Program is waiting for input",
               "The program did not finish because it is waiting for you to type input (it calls scanf/cin), but "
               "no input was given.",
               fix=["Type the input values in the input box (or pass them with --input \"5 10\") and run again."],
               level="info")
        else:
            hints = _hints_from_exps(exps, ("T014", "T001"))
            mk("R006", "Program never finishes (infinite loop?)",
               "The program was stopped after running too long. Most often a loop condition never becomes false.",
               why=["The loop variable is never changed inside a while loop.",
                    "The counter moves away from the limit (i-- with i < n).",
                    "A `;` right after `while (...)` makes an empty endless loop."],
               fix=["Check every loop: what makes its condition false, and does that happen?"], hints=hints)
        return out
    sig = run.signal_name or ""
    if sig in ("SIGSEGV", "ACCESS_VIOLATION"):
        hints = _hints_from_exps(exps, ("Missing & in scanf", "T004", "T005", "T008", "W015", "W005"))
        rec = _recursive_functions(src)
        if rec:
            hints.append("`%s()` calls itself - if it has no stopping condition (base case) the recursion never "
                         "ends and the stack overflows." % rec[0])
        mk("R001", "Segmentation fault - invalid memory access",
           "The program tried to read or write memory that does not belong to it, so the operating system "
           "stopped it (\"Segmentation fault (core dumped)\").",
           why=["scanf without `&` (scanf(\"%d\", x) instead of scanf(\"%d\", &x)).",
                "Array index outside the array (a[n] for an array of size n, or a negative index).",
                "Using a pointer that was never set, or is NULL.",
                "Endless recursion (a function that keeps calling itself).",
                "A very large local array, e.g. int a[10000000]; inside main (make it global or use malloc)."],
           fix=["Check the hints below first; compile with sanitizers (`--sanitize`) to get the exact line."],
           hints=hints)
    elif sig in ("SIGFPE", "INT_DIVIDE_BY_ZERO", "FLT_DIVIDE_BY_ZERO"):
        mk("R002", "Division by zero (\"Floating point exception\")",
           "The program divided an integer by 0 (or used % with 0). Despite the name, \"Floating point exception\" "
           "on Linux/macOS means an INTEGER arithmetic error.",
           fix=["Check the divisor first: `if (b != 0) result = a / b;`"],
           hints=["Your input was: %r" % stdin_text] if stdin_text else [])
    elif sig in ("SIGABRT",) or run.exit_code == 3 and os.name == "nt":
        err = run.stderr or ""
        if "stack smashing" in err:
            mk("R004", "Stack smashing - array overflow",
               "The program wrote past the end of a local array (for example copying a long string into "
               "`char name[5]`). The protection code noticed the damage and stopped the program.",
               fix=["Make the array large enough, and use bounded functions: `fgets`, `strncpy`, `scanf(\"%19s\", name)`."])
        elif re.search(r"double free|free\(\): invalid|corrupted|malloc\(\)", err):
            mk("R005", "Memory corruption (malloc/free)",
               "The program freed memory twice, freed something that was not allocated, or wrote outside an "
               "allocated block.", fix=["Free each malloc'd block exactly once and stay inside its size."])
        elif "Assertion" in err:
            mk("R003", "assert() failed", "An `assert(...)` condition in the program was false: %s" % err.strip()[:200])
        elif "terminate called" in err:
            m = re.search(r"what\(\):\s*(.+)", err)
            mk("R003", "Uncaught C++ exception",
               "The program threw an exception that nobody caught%s." % (": " + m.group(1).strip() if m else ""),
               why=["vector.at(i) / string.at(i) with an index out of range.", "stoi() on text that is not a number."])
        else:
            mk("R003", "Program aborted", "The program stopped itself with abort(). %s" % err.strip()[:200])
    elif sig in ("STACK_OVERFLOW",):
        mk("R007", "Stack overflow", "The program used up its call stack - usually endless recursion or a huge local array.")
    elif sig in ("SIGBUS",):
        mk("R008", "Bus error", "The program wrote to read-only or invalid memory. On macOS this often means modifying "
           "a string literal: `char *s = \"hi\"; s[0] = 'H';`.", fix=["Use an array instead: `char s[] = \"hi\";`."])
    elif sig:
        mk("R009", "Program stopped by %s" % sig, "The operating system stopped the program with signal %s." % sig)
    elif run.exit_code not in (0, None):
        mk("R009", "Program ended with exit code %s" % run.exit_code,
           "The program finished, but returned %s instead of 0. That is fine if your code does `return %s;` on "
           "purpose; 0 normally means success." % (run.exit_code, run.exit_code), level="info")
    return out
