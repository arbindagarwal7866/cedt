"""
web/server.py - a small local web interface (Python standard library only).

    python cedt.py --web            then open http://127.0.0.1:8000

Endpoints
    GET  /                     the single-page interface
    GET  /static/<file>        css / js
    GET  /api/info             compilers found, knowledge-base size
    GET  /api/samples          demo programs from samples/
    GET  /api/rules            the knowledge base (error encyclopedia)
    GET  /api/grammar          LL(1) grammar, FIRST/FOLLOW, parsing table
    POST /api/explain          {code, lang, compiler, run, stdin, sanitize} -> explanations
    POST /api/explain-log      {log, code, lang} -> explanations of pasted compiler output

The server compiles and RUNS code, so it only listens on 127.0.0.1 by default.
"""
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .. import __version__, core, driver
from .. import kb as kbmod
from ..diag_lexer import tokenize as diag_tokenize
from ..diag_parser import grammar, parse_compiler_output
from ..render_html import render_fragment
from ..source import SourceFile

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
ROOT = os.path.dirname(os.path.dirname(HERE))
SAMPLES = os.path.join(ROOT, "samples")
MAX_CODE = 200_000
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json"}


def load_samples():
    out = []
    for sub in ("c", "cpp"):
        d = os.path.join(SAMPLES, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith((".c", ".cpp")):
                continue
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                code = fh.read()
            title = name.rsplit(".", 1)[0]
            first = code.split("\n", 1)[0]
            if first.startswith("/*") and "*/" in first:
                title = first[2:first.index("*/")].strip()
            out.append({"id": "%s/%s" % (sub, name), "lang": "c++" if sub == "cpp" else "c",
                        "title": title, "code": code})
    return out


def internals(report, code, lang):
    """Compiler-design views of the run: tokens, parse trace, symbol table."""
    res = parse_compiler_output(report.raw_output or "", trace=True)
    dt = [{"line": t.lineno, "type": t.type, "text": t.text[:160]} for t in res.tokens[:400]]
    trace = [{"stack": s.stack, "lookahead": s.lookahead, "action": s.action} for s in res.outcome.trace[:400]]
    sf = SourceFile("main", code, lang)
    toks = [{"line": t.line, "col": t.col, "kind": t.kind, "text": t.text[:80], "error": t.error}
            for t in sf.all_tokens[:800]]
    scopes = [{"id": s.id, "kind": s.kind, "name": s.name, "parent": s.parent, "from": s.start_line,
               "to": s.end_line if s.end_line < 10 ** 8 else None} for s in sf.symbols.scopes]
    syms = [{"name": s.name, "kind": s.kind, "type": s.type_str(), "line": s.line, "scope": s.scope,
             "initialized": s.initialized,
             "params": ["%s %s" % (p.type, p.name) for p in s.params],
             "members": [m.name for m in s.members], "value": s.value} for s in sf.symbols.symbols]
    br = sf.brackets
    return {"diag_tokens": dt, "parse_trace": trace, "parse_steps": res.outcome.steps,
            "parse_errors": res.errors, "source_tokens": toks, "scopes": scopes, "symbols": syms,
            "brackets": {"balanced": br.balanced,
                         "unclosed": [{"text": sf.tokens[i].text, "line": sf.tokens[i].line} for i in br.unclosed],
                         "extra": [{"text": sf.tokens[i].text, "line": sf.tokens[i].line} for i in br.extra]}}


def report_payload(report, code, lang, want_internals=True):
    d = report.to_dict()
    for e in d["explanations"]:
        e.pop("diagnostic", None)
    d["fragments"] = render_fragment(report)
    markers = []
    for e in report.explanations:
        if not e.is_root:
            continue
        ln = e.real_line or (e.location.line if e.location and e.location.line else None)
        if ln:
            markers.append({"line": ln, "level": e.level, "id": e.id})
    d["markers"] = markers
    if want_internals:
        try:
            d["internals"] = internals(report, code, lang)
        except Exception as exc:          # internals are optional
            d["internals"] = {"error": repr(exc)}
    return d


class Handler(BaseHTTPRequestHandler):
    server_version = "CEDT/" + __version__

    def log_message(self, fmt, *args):
        if os.environ.get("CEDT_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=str)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file(os.path.join(STATIC, "index.html"))
        if path.startswith("/static/"):
            name = os.path.normpath(path[len("/static/"):]).replace("\\", "/")
            if name.startswith("..") or "/" in name:
                return self._send(404, {"error": "not found"})
            return self._file(os.path.join(STATIC, name))
        if path == "/api/info":
            k = kbmod.load()
            return self._send(200, {"version": __version__, "compilers": driver.available(),
                                    "kb": k.stats(), "python": sys.version.split()[0]})
        if path == "/api/samples":
            return self._send(200, load_samples())
        if path == "/api/rules":
            k = kbmod.load()
            rules = [{"id": r.id, "title": r.title, "phase": r.phase, "lang": r.lang, "what": r.what,
                      "why": r.why, "fix": r.fix, "example": r.example, "tip": r.tip, "samples": r.samples,
                      "patterns": len(r.patterns), "handler": r.handler} for r in sorted(k.rules, key=lambda r: r.id)]
            return self._send(200, {"stats": k.stats(), "rules": rules})
        if path == "/api/grammar":
            g = grammar()
            return self._send(200, {
                "grammar": g.format_grammar(), "grammar_actions": g.format_grammar(with_actions=True),
                "terminals": g.terminals, "nonterminals": g.nonterminals,
                "first": {a: sorted(g.first[a]) for a in g.nonterminals},
                "follow": {a: sorted(g.follow[a]) for a in g.nonterminals},
                "table": {a: {t: str(p) for t, p in g.table[a].items()} for a in g.nonterminals},
                "ll1": g.is_ll1(), "conflicts": g.conflicts})
        return self._send(404, {"error": "not found"})

    def _file(self, path):
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        with open(path, "rb") as fh:
            data = fh.read()
        self._send(200, data, TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_CODE * 3:
            raise ValueError("request too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._json_body()
        except Exception as exc:
            return self._send(400, {"error": "bad request: %s" % exc})
        code = body.get("code") or ""
        if len(code) > MAX_CODE:
            return self._send(413, {"error": "program too large"})
        lang = "c++" if body.get("lang") in ("c++", "cpp") else "c"
        try:
            if path == "/api/explain":
                rep = core.analyze_code(code, lang=lang, compiler=body.get("compiler") or "auto",
                                        std=body.get("std") or None, warnings=body.get("warnings") or "all",
                                        run=bool(body.get("run")), stdin_text=body.get("stdin") or "",
                                        sanitize=bool(body.get("sanitize")),
                                        timeout=min(float(body.get("timeout") or 4), 10.0))
                return self._send(200, report_payload(rep, code, lang))
            if path == "/api/explain-log":
                fname = "main.cpp" if lang == "c++" else "main.c"
                log = body.get("log") or ""
                sources = {}
                if code.strip():
                    import re
                    m = re.search(r"^([^\s:][^:\n]*\.(?:c|cc|cpp|cxx|C)):\d+", log, re.M)
                    sources[m.group(1) if m else fname] = code
                rep = core.analyze_log(log, sources, lang)
                return self._send(200, report_payload(rep, code, lang))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return self._send(500, {"error": "internal error: %r" % exc})
        return self._send(404, {"error": "not found"})


def serve(host="127.0.0.1", port=8000, open_browser=True):
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer((host, p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print("cedt: could not open a port near %d" % port, file=sys.stderr)
        return 1
    url = "http://%s:%d/" % ("127.0.0.1" if host in ("0.0.0.0", "") else host, port)
    comp = driver.detect()
    print("CEDT web interface running at %s" % url)
    print("Compiler: %s" % (comp.name if comp else "none found - install gcc or clang"))
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0
