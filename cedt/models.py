"""
models.py - the data structures that flow through the CEDT pipeline.

    compiler output --(diag_lexer)--> DToken list
                    --(diag_parser)--> Diagnostic tree
                    --(translator)--> Explanation list --> Report
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# Compiler phases in pipeline order.  Every explanation is tagged with the
# phase that *detected* the problem - this is the "phase of compilation"
# concept from the compiler-design syllabus made visible to students.
PHASES = [
    ("preprocessor", "Preprocessor"),
    ("lexical", "Lexical Analysis"),
    ("syntax", "Syntax Analysis"),
    ("semantic", "Semantic Analysis"),
    ("flow", "Flow Analysis"),
    ("linker", "Linker"),
    ("runtime", "Runtime"),
]
PHASE_NAMES = dict(PHASES)
PHASE_ORDER = {key: i for i, (key, _) in enumerate(PHASES)}

PHASE_DESCRIPTIONS = {
    "preprocessor": "Handles #include and #define before real compilation starts.",
    "lexical": "The scanner breaks your text into tokens (words, numbers, symbols, strings).",
    "syntax": "The parser checks that tokens follow C/C++ grammar (semicolons, brackets, statement shapes).",
    "semantic": "The type checker checks meaning: declared names, matching types, correct argument counts.",
    "flow": "Control/data-flow analysis looks at all paths through your code (missing return, uninitialised use).",
    "linker": "The linker joins your compiled code with libraries and must find every function you call.",
    "runtime": "The program compiled, but something went wrong while it was running.",
}

# Levels shown to students
LEVEL_ERROR = "error"      # program cannot be built
LEVEL_WARNING = "warning"  # program builds but probably has a bug
LEVEL_TIP = "tip"          # compiler is silent; CEDT's own beginner check
LEVEL_INFO = "info"
LEVEL_ORDER = {LEVEL_ERROR: 0, LEVEL_WARNING: 1, LEVEL_TIP: 2, LEVEL_INFO: 3}


@dataclass
class Location:
    file: str
    line: int
    column: Optional[int] = None

    def short(self):
        if self.column:
            return "%s:%d:%d" % (self.file, self.line, self.column)
        return "%s:%d" % (self.file, self.line)


@dataclass
class Diagnostic:
    """One message produced by the compiler, linker or driver."""
    severity: str                       # error | warning | fatal error | note
    message: str                        # message text without the [-Wflag]
    location: Optional[Location] = None
    flag: Optional[str] = None          # e.g. -Wformat=
    origin: str = "compiler"            # compiler | linker | driver | precheck
    context: Optional[str] = None       # e.g. "In function 'main'"
    include_trace: List[Location] = field(default_factory=list)
    instantiation_trace: List[str] = field(default_factory=list)
    notes: List["Diagnostic"] = field(default_factory=list)
    snippet: List[str] = field(default_factory=list)
    raw_lines: List[str] = field(default_factory=list)
    symbol: Optional[str] = None        # linker symbol
    extra: Dict[str, Any] = field(default_factory=dict)
    index: int = 0                      # order of appearance

    @property
    def is_error(self):
        return self.severity in ("error", "fatal error")

    def to_dict(self):
        d = asdict(self)
        return d


@dataclass
class Explanation:
    """A beginner-friendly explanation of one problem."""
    rule_id: str
    title: str
    phase: str
    level: str
    what: str                                   # what happened (plain words)
    why: List[str] = field(default_factory=list)  # common causes
    fix: List[str] = field(default_factory=list)  # how to fix (steps)
    hints: List[str] = field(default_factory=list)  # context-aware hints
    tip: str = ""                                 # general "good to know"
    example_wrong: Optional[str] = None
    example_right: Optional[str] = None
    location: Optional[Location] = None          # where the compiler pointed
    real_line: Optional[int] = None              # where the mistake really is
    fixed_line: Optional[str] = None             # suggested corrected source line
    fixed_line_no: Optional[int] = None
    fixed_kind: str = "replace"                  # replace | insert_before | delete
    diagnostic: Optional[Diagnostic] = None
    compiler_message: str = ""
    confidence: str = "high"                     # high | medium | low
    jargon: List[Dict[str, str]] = field(default_factory=list)
    is_root: bool = True
    root_id: Optional[int] = None
    follower_reason: Optional[str] = None
    followers: List[int] = field(default_factory=list)
    id: int = 0
    source: str = "compiler"                     # compiler | precheck | runtime
    subject: Optional[str] = None                # main name the problem is about (for grouping)

    def to_dict(self):
        d = asdict(self)
        d["phase_name"] = PHASE_NAMES.get(self.phase, self.phase)
        return d


@dataclass
class RunResult:
    ran: bool = False
    exit_code: Optional[int] = None
    signal_name: Optional[str] = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    note: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Report:
    files: List[str]
    language: str
    compiler: Dict[str, Any]
    command: List[str]
    exit_code: Optional[int]
    raw_output: str
    explanations: List[Explanation]
    parse_errors: List[str] = field(default_factory=list)
    timings_ms: Dict[str, float] = field(default_factory=dict)
    run: Optional[RunResult] = None
    build_ok: bool = False
    sources: Dict[str, str] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)

    def roots(self):
        return [e for e in self.explanations if e.is_root]

    def counts(self):
        c = {"error": 0, "warning": 0, "tip": 0, "info": 0}
        for e in self.explanations:
            if e.is_root:
                c[e.level] = c.get(e.level, 0) + 1
        c["followers"] = sum(1 for e in self.explanations if not e.is_root)
        return c

    def to_dict(self):
        return {
            "files": self.files,
            "language": self.language,
            "compiler": self.compiler,
            "command": self.command,
            "exit_code": self.exit_code,
            "build_ok": self.build_ok,
            "raw_output": self.raw_output,
            "explanations": [e.to_dict() for e in self.explanations],
            "parse_errors": self.parse_errors,
            "timings_ms": self.timings_ms,
            "run": self.run.to_dict() if self.run else None,
            "counts": self.counts(),
            "stats": self.stats,
        }
