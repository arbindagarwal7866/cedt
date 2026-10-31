"""
driver.py - finds and runs the REAL compiler (GCC or Clang).

CEDT does not replace the compiler; it runs gcc / g++ / clang / clang++ with
sensible beginner settings (-Wall, no colours, C locale so quotes are plain
ASCII) and hands the captured output to the translator.

Works with: GCC on Linux, MinGW-w64 GCC on Windows (Code::Blocks, MSYS2,
Dev-C++), Apple clang on macOS (where `gcc` is really clang), LLVM clang.
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import List, Optional

IS_WINDOWS = os.name == "nt"
# On ARM processors (Apple Silicon, Raspberry Pi ...) integer division by zero does NOT crash -
# it silently gives 0.  When the program is run we add UBSan's divide-by-zero check so the
# student still learns about it.
DIV_ZERO_SILENT = platform.machine().lower() in ("arm64", "aarch64")
DIV_ZERO_FLAG = "-fsanitize=integer-divide-by-zero"
# ... but leave crashes (segfault, stack overflow) to the operating system, as without the check
DIV_ZERO_ENV = "handle_segv=0:handle_sigbus=0:handle_sigfpe=0:handle_sigill=0:handle_abort=0"


@dataclass
class CompilerInfo:
    family: str              # gcc | clang
    name: str                # human readable, e.g. "Apple clang 15.0.0"
    c_cmd: str
    cpp_cmd: str
    version: str = ""
    major: int = 0
    path: str = ""

    def to_dict(self):
        return {"family": self.family, "name": self.name, "c": self.c_cmd, "cpp": self.cpp_cmd,
                "version": self.version, "major": self.major}


@dataclass
class CompileResult:
    command: List[str]
    returncode: int
    output: str
    exe: Optional[str]
    duration_ms: float
    error: str = ""
    workdir: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def ok(self):
        return self.returncode == 0 and self.exe is not None and os.path.exists(self.exe)


def _version_info(cmd):
    try:
        p = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=15,
                           errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    text = (p.stdout or "") + (p.stderr or "")
    first = text.strip().splitlines()[0] if text.strip() else ""
    if "clang" in text.lower():
        m = re.search(r"clang version (\d+)\.(\d+)(?:\.(\d+))?", text)
        fam = "clang"
        name = ("Apple clang" if "Apple" in text else "clang")
    else:
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", first) or re.search(r"(\d+)\.(\d+)", first)
        fam = "gcc"
        name = "MinGW gcc" if "mingw" in text.lower() or "MinGW" in text else "gcc"
    if not m:
        return fam, name, "", 0
    ver = ".".join(g for g in m.groups() if g)
    return fam, "%s %s" % (name, ver), ver, int(m.group(1))


def _cpp_counterpart(cmd):
    base = os.path.basename(cmd)
    pairs = [("clang", "clang++"), ("gcc", "g++"), ("cc", "c++")]
    for c, cpp in pairs:
        m = re.match(r"^(.*?)%s(-[\d.]+)?(\.exe)?$" % re.escape(c), base)
        if m:
            return os.path.join(os.path.dirname(cmd), m.group(1) + cpp + (m.group(2) or "") + (m.group(3) or ""))
    return cmd


def detect(preferred=None):
    """Return CompilerInfo for the preferred or first available compiler."""
    order = [preferred] if preferred and preferred != "auto" else []
    order += ["gcc", "clang", "cc"]
    for cmd in order:
        if not cmd:
            continue
        path = shutil.which(cmd)
        if not path:
            continue
        info = _version_info(path)
        if info is None:
            continue
        fam, name, ver, major = info
        cpp = _cpp_counterpart(cmd)
        if not shutil.which(cpp):
            cpp = "clang++" if fam == "clang" and shutil.which("clang++") else ("g++" if shutil.which("g++") else cpp)
        return CompilerInfo(fam, name, cmd, cpp, ver, major, path)
    return None


def available():
    out = []
    for cmd in ("gcc", "clang"):
        p = shutil.which(cmd)
        if p:
            info = _version_info(p)
            if info:
                out.append({"command": cmd, "family": info[0], "name": info[1]})
    return out


def language_of(path, forced=None):
    if forced and forced != "auto":
        return "c++" if forced in ("c++", "cpp", "cxx") else "c"
    return "c++" if os.path.splitext(path)[1].lower() in (".cpp", ".cc", ".cxx", ".c++", ".cp", ".C") else "c"


def build_flags(info, lang, std=None, warnings="all", sanitize=False):
    flags = []
    if info.family == "gcc":
        flags.append("-fdiagnostics-color=never")
        if info.major >= 11:
            flags.append("-fdiagnostics-column-unit=byte")
    else:
        flags.append("-fno-color-diagnostics")
    if warnings in ("all", "extra"):
        flags.append("-Wall")
    if warnings == "extra":
        flags.append("-Wextra")
    if std:
        flags.append("-std=" + std)
    if sanitize:
        flags += ["-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    return flags


def compile_files(files, lang, info, std=None, warnings="all", extra=None, sanitize=False,
                  workdir=None, timeout=60, cwd=None):
    """Compile and link; returns CompileResult with the combined output."""
    workdir = workdir or tempfile.mkdtemp(prefix="cedt_")
    exe = os.path.join(workdir, "program.exe" if IS_WINDOWS else "program")
    cmd_name = info.cpp_cmd if lang == "c++" else info.c_cmd
    cmd = [cmd_name] + build_flags(info, lang, std, warnings, sanitize) + list(files) + ["-o", exe] + list(extra or [])
    env = dict(os.environ)
    if not IS_WINDOWS:
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                           errors="replace", cwd=cwd)
        out = (p.stderr or "") + (p.stdout or "")
        rc = p.returncode
        err = ""
    except subprocess.TimeoutExpired:
        out, rc, err = "", -1, "The compiler did not finish within %d seconds." % timeout
    except OSError as e:
        out, rc, err = "", -1, "Could not start the compiler: %s" % e
    dt = (time.perf_counter() - t0) * 1000
    if sanitize and rc != 0 and re.search(r"cannot find -l(?:asan|ubsan)|unsupported option.*-fsanitize|"
                                          r"sanitizer.*not supported", out):
        r = compile_files(files, lang, info, std, warnings, extra, False, workdir, timeout, cwd)
        r.extra["sanitizer_unavailable"] = True
        return r
    return CompileResult(cmd, rc, out, exe if rc == 0 and os.path.exists(exe) else None, dt, err, workdir)
