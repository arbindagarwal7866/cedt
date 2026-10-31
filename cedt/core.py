"""
core.py - the public API of CEDT.

    analyze_files(["prog.c"])          compile with GCC/Clang, then explain
    analyze_code(code_text, lang="c")  same, for code typed in the web UI
    analyze_log(output_text, sources)  explain compiler output produced elsewhere
"""
import os
import shutil
import tempfile
import time

from . import driver, runtime
from .models import Report
from .translator import Translator

_TR = None


def translator():
    global _TR
    if _TR is None:
        _TR = Translator()
    return _TR


def _stats(exps, parse):
    raw = [d for d in parse.diagnostics if d.severity in ("error", "fatal error", "warning")
           and d.extra.get("kind") != "summary"]
    notes = sum(len(d.notes) for d in parse.diagnostics)
    roots = [e for e in exps if e.is_root and e.source == "compiler" and e.level in ("error", "warning")]
    return {
        "compiler_messages": len(raw),
        "compiler_errors": sum(1 for d in raw if d.severity != "warning"),
        "compiler_warnings": sum(1 for d in raw if d.severity == "warning"),
        "compiler_notes": notes,
        "output_lines": len(parse.tokens) - 1,
        "root_problems": len(roots),
        "cascade_folded": sum(1 for e in exps if not e.is_root),
        "tips": sum(1 for e in exps if e.source == "precheck"),
        "matched_by_rule": sum(1 for e in exps if e.source == "compiler" and not e.rule_id.startswith("G")),
        "generic": sum(1 for e in exps if e.rule_id == "G000"),
    }


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def analyze_files(paths, lang=None, compiler=None, std=None, warnings="all", extra=None, run=False,
                  stdin_text="", sanitize=False, timeout=5.0, cwd=None, prechecks=True):
    paths = list(paths)
    lang = driver.language_of(paths[0], lang)
    info = driver.detect(compiler)
    sources = {}
    for p in paths:
        try:
            sources[p] = _read(os.path.join(cwd, p) if cwd and not os.path.isabs(p) else p)
        except OSError:
            pass
    if info is None:
        rep = analyze_log("", sources, lang, prechecks=prechecks)
        rep.compiler = {"family": None, "name": "no compiler found"}
        rep.parse_errors.append("No C/C++ compiler (gcc or clang) was found on this computer, so only CEDT's own "
                                "checks were run. Install GCC (Windows: MSYS2/MinGW, macOS: xcode-select --install, "
                                "Linux: sudo apt install build-essential).")
        return rep
    t0 = time.perf_counter()
    div_check = [driver.DIV_ZERO_FLAG] if run and not sanitize and driver.DIV_ZERO_SILENT else []
    res = driver.compile_files(paths, lang, info, std=std, warnings=warnings, extra=list(extra or []) + div_check,
                               sanitize=sanitize, cwd=cwd)
    if div_check and not res.ok and "sanitize" in res.output:
        res = driver.compile_files(paths, lang, info, std=std, warnings=warnings, extra=extra,
                                   sanitize=sanitize, cwd=cwd)
    t1 = time.perf_counter()
    tr = translator()
    exps, parse = tr.explain(res.output, sources, lang, unit="byte", run_prechecks=prechecks)
    rep = Report(files=paths, language=lang, compiler=info.to_dict(), command=res.command,
                 exit_code=res.returncode, raw_output=res.output, explanations=exps,
                 parse_errors=list(parse.errors), sources=sources)
    if res.error:
        rep.parse_errors.append(res.error)
    if res.extra.get("sanitizer_unavailable"):
        rep.parse_errors.append("Sanitizers are not available with this compiler; compiled without them.")
    rep.build_ok = res.ok
    rep.timings_ms = {"compile_ms": (t1 - t0) * 1000}
    rep.timings_ms.update(tr.timings)
    rep.stats = _stats(exps, parse)
    if run and res.ok:
        env = dict(os.environ, UBSAN_OPTIONS=driver.DIV_ZERO_ENV) if div_check else None
        rr = runtime.run_program(res.exe, stdin_text, timeout, cwd=cwd, env=env)
        rep.run = rr
        src = tr.files.get(paths[0])
        rex = runtime.explain_run(rr, src, exps, paths[0], stdin_text)
        base = len(rep.explanations)
        for i, e in enumerate(rex):
            e.id = base + i
        rep.explanations.extend(rex)
    shutil.rmtree(res.workdir, ignore_errors=True)
    return rep


def analyze_code(code, lang="c", filename=None, **kw):
    """Analyze source text (used by the web interface)."""
    lang = "c++" if lang in ("c++", "cpp", "cxx") else "c"
    filename = filename or ("main.cpp" if lang == "c++" else "main.c")
    d = tempfile.mkdtemp(prefix="cedt_src_")
    try:
        with open(os.path.join(d, filename), "w", encoding="utf-8") as fh:
            fh.write(code)
        return analyze_files([filename], lang=lang, cwd=d, **kw)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def analyze_log(output, sources=None, lang="c", unit="auto", prechecks=True):
    """Explain compiler output that was produced elsewhere (e.g. in an IDE)."""
    tr = translator()
    exps, parse = tr.explain(output or "", sources or {}, lang, unit=unit, run_prechecks=prechecks)
    from .diag_parser import detect_compiler_family
    rep = Report(files=list((sources or {}).keys()), language=lang,
                 compiler={"family": detect_compiler_family(output or ""), "name": "from log"},
                 command=[], exit_code=None, raw_output=output or "", explanations=exps,
                 parse_errors=list(parse.errors), sources=sources or {})
    rep.build_ok = not any(d.is_error for d in parse.diagnostics)
    rep.timings_ms = dict(tr.timings)
    rep.stats = _stats(exps, parse)
    return rep
