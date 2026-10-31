"""
kb.py - loads and queries the error KNOWLEDGE BASE.

The knowledge base is pure data (cedt/data/rules/*.json), organised by
compiler phase.  Each rule says:
    patterns   - regular expressions for the GCC *and* Clang wording
    phase      - which compiler phase detects the problem
    what/why/fix/example - the beginner-friendly explanation (templates)
    handler    - optional Python function that reads the student's source
                 code to make the explanation specific (see handlers/)
New rules can be added without touching any Python code.
"""
import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RULES_DIR = os.path.join(DATA_DIR, "rules")
VALID_PHASES = {"preprocessor", "lexical", "syntax", "semantic", "flow", "linker", "runtime"}


@dataclass
class Rule:
    id: str
    title: str
    phase: str
    what: str
    patterns: List[str] = field(default_factory=list)
    why: List[str] = field(default_factory=list)
    fix: List[str] = field(default_factory=list)
    example: Dict[str, str] = field(default_factory=dict)
    tip: str = ""
    handler: Optional[str] = None
    lang: str = "both"
    priority: int = 50
    origin: str = "any"          # compiler | linker | driver | any
    level: Optional[str] = None  # force a level (e.g. info for summaries)
    samples: List[str] = field(default_factory=list)
    file: str = ""
    compiled: list = field(default_factory=list, repr=False)

    def matches(self, message):
        for rx in self.compiled:
            m = rx.search(message)
            if m:
                return {k: v for k, v in m.groupdict().items() if v is not None}
        return None

    def applies_to(self, lang, origin):
        if self.lang != "both":
            is_cpp = lang in ("c++", "cpp")
            if (self.lang == "c++") != is_cpp:
                return False
        if self.origin != "any" and self.origin != origin:
            return False
        return True


class KnowledgeBase:
    def __init__(self, rules_dir=RULES_DIR):
        self.rules: List[Rule] = []
        self.by_id: Dict[str, Rule] = {}
        self.problems: List[str] = []
        for name in sorted(os.listdir(rules_dir)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(rules_dir, name), encoding="utf-8") as fh:
                data = json.load(fh)
            for entry in data["rules"]:
                self._add(entry, name)
        # stable sort: higher priority first, file order otherwise
        self.rules.sort(key=lambda r: -r.priority)
        self.data = {}
        for extra in ("stdlib.json", "glossary.json"):
            p = os.path.join(DATA_DIR, extra)
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    self.data[extra.split(".")[0]] = json.load(fh)

    def _add(self, entry, fname):
        known = set(Rule.__dataclass_fields__) - {"compiled", "file"}
        unknown = set(entry) - known
        if unknown:
            self.problems.append("%s: unknown keys %s" % (entry.get("id"), sorted(unknown)))
        rule = Rule(**{k: v for k, v in entry.items() if k in known})
        rule.file = fname
        if rule.phase not in VALID_PHASES:
            self.problems.append("%s: bad phase %s" % (rule.id, rule.phase))
        if rule.id in self.by_id:
            self.problems.append("duplicate rule id %s" % rule.id)
        for p in rule.patterns:
            try:
                rule.compiled.append(re.compile(p))
            except re.error as e:
                self.problems.append("%s: bad regex %r (%s)" % (rule.id, p, e))
        self.rules.append(rule)
        self.by_id[rule.id] = rule

    def candidates(self, message, lang, origin):
        """All rules matching a message, best (highest priority) first."""
        out = []
        for r in self.rules:
            if not r.applies_to(lang, origin):
                continue
            g = r.matches(message)
            if g is not None:
                out.append((r, g))
        return out

    def get(self, rule_id):
        return self.by_id.get(rule_id)

    def stats(self):
        per_phase = {}
        for r in self.rules:
            per_phase[r.phase] = per_phase.get(r.phase, 0) + 1
        return {"rules": len(self.rules),
                "patterns": sum(len(r.patterns) for r in self.rules),
                "with_handler": sum(1 for r in self.rules if r.handler),
                "per_phase": per_phase}


_KB = None


def load():
    global _KB
    if _KB is None:
        _KB = KnowledgeBase()
    return _KB
