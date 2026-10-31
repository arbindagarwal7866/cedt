"""
textutil.py - small text helpers shared by every CEDT module.

Contents
  * strip_ansi / normalize_quotes  - clean raw compiler output
  * osa_distance / closest          - "did you mean ...?" suggestions
                                      (Optimal String Alignment edit distance,
                                       i.e. Levenshtein + adjacent transposition)
  * column helpers                  - convert compiler column numbers
                                      (byte / display / char units) to Python
                                      string indexes
"""
import re
import unicodedata

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# GCC prints quotes as Unicode ‘ ’ in UTF-8 locales and GNU ld uses `name'.
# Everything is normalised to plain ASCII quotes before pattern matching.
_QUOTE_TABLE = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "`": "'",
})


def strip_ansi(text):
    """Remove terminal colour escape sequences."""
    return ANSI_RE.sub("", text)


def normalize_quotes(text):
    """Convert typographic / backtick quotes to ASCII quotes."""
    return text.translate(_QUOTE_TABLE)


def clean_line(line):
    """Prepare one raw output line for the diagnostic lexer."""
    return normalize_quotes(strip_ansi(line)).rstrip("\r\n").rstrip()


# --------------------------------------------------------------------------
# Edit distance (used for typo suggestions)
# --------------------------------------------------------------------------
def osa_distance(a, b, limit=None):
    """Optimal-string-alignment distance between two strings.

    Counts insertions, deletions, substitutions and swaps of two adjacent
    characters (so 'conut' -> 'count' has distance 1).  If *limit* is given
    the function may stop early and return limit + 1.
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if limit is not None and abs(la - lb) > limit:
        return limit + 1
    prev2 = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            val = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (i > 1 and j > 1 and a[i - 1] == b[j - 2]
                    and a[i - 2] == b[j - 1] and prev2 is not None):
                val = min(val, prev2[j - 2] + 1)
            cur[j] = val
            row_min = min(row_min, val)
        if limit is not None and row_min > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[lb]


def default_threshold(word):
    n = len(word)
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    return 3


def closest(word, candidates, limit=None, max_results=3):
    """Return candidate names that look like *word* (best first).

    A candidate that differs only in upper/lower case is always the best
    match (C is case sensitive, beginners often type Printf or Int).
    """
    if not word:
        return []
    limit = default_threshold(word) if limit is None else limit
    scored = []
    lw = word.lower()
    for cand in set(candidates):
        if not cand or cand == word:
            continue
        if cand.lower() == lw:
            scored.append((0, cand))
            continue
        d = osa_distance(lw, cand.lower(), limit)
        if d <= limit:
            # small preference for same first letter
            bonus = 0 if cand[0].lower() == lw[0] else 0.5
            scored.append((d + bonus, cand))
    scored.sort(key=lambda x: (x[0], abs(len(x[1]) - len(word)), x[1]))
    return [c for _, c in scored[:max_results]]


def case_only_difference(a, b):
    return a != b and a.lower() == b.lower()


# --------------------------------------------------------------------------
# Column helpers
# --------------------------------------------------------------------------
def expand_tabs(line, tabstop=8):
    return line.expandtabs(tabstop)


def _char_display_width(ch):
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    if unicodedata.combining(ch):
        return 0
    return 1


def display_col_to_index(line, col, tabstop=8):
    """GCC >= 11 reports *display* columns (tabs expanded, wide chars = 2)."""
    if col is None:
        return None
    target = col - 1
    width = 0
    for idx, ch in enumerate(line):
        if width >= target:
            return idx
        if ch == "\t":
            width += tabstop - (width % tabstop)
        else:
            width += _char_display_width(ch)
    return len(line)


def byte_col_to_index(line, col):
    """Clang (and GCC with -fdiagnostics-column-unit=byte) count UTF-8 bytes."""
    if col is None:
        return None
    target = col - 1
    count = 0
    for idx, ch in enumerate(line):
        if count >= target:
            return idx
        count += len(ch.encode("utf-8", errors="replace"))
    return len(line)


def index_to_display_col(line, index, tabstop=8):
    width = 0
    for ch in line[:index]:
        if ch == "\t":
            width += tabstop - (width % tabstop)
        else:
            width += _char_display_width(ch)
    return width + 1


def plural(n, word, plural_word=None):
    if n == 1:
        return "1 " + word
    return "%d %s" % (n, plural_word or word + "s")


def shorten(text, width=90):
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 3] + "..."
