"""
Debug & Profiler Skill
- Run code with full trace (line-by-line)
- Profile functions (time + calls)
- Inspect variables at each step
- Build call graph / data flow
- AST analysis for data links
"""
import subprocess, sys, os, ast, json, time, tempfile, re, textwrap
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════
#  INSTRUMENTED EXECUTION — captures locals at each step
# ══════════════════════════════════════════════════════════════════════

TRACE_WRAPPER = '''
import sys, json, traceback, time

_trace_log = []
_max_steps = 500

def _serialize(v):
    try:
        if isinstance(v, (int, float, bool, str, type(None))):
            return v
        if isinstance(v, (list, tuple)):
            return [_serialize(x) for x in v[:20]]
        if isinstance(v, dict):
            return {str(k): _serialize(val) for k, val in list(v.items())[:20]}
        return str(v)[:200]
    except:
        return "<unserializable>"

def _tracer(frame, event, arg):
    global _trace_log
    if len(_trace_log) >= _max_steps:
        return _tracer
    if event in ("line", "call", "return", "exception"):
        locs = {k: _serialize(v) for k, v in frame.f_locals.items()
                if not k.startswith("_")}
        _trace_log.append({
            "event":  event,
            "file":   frame.f_code.co_filename,
            "func":   frame.f_code.co_name,
            "line":   frame.f_lineno,
            "locals": locs,
            "arg":    _serialize(arg) if arg is not None else None,
        })
    return _tracer

sys.settrace(_tracer)
_stdout_lines = []
_orig_print = print
def _cap_print(*a, **kw):
    import io; buf=io.StringIO()
    _orig_print(*a,file=buf,**kw)
    _stdout_lines.append(buf.getvalue().rstrip())
    _orig_print(*a, **kw)
print = _cap_print

_t0 = time.perf_counter()
_error = None
try:
    {CODE_PLACEHOLDER}
except Exception as e:
    _error = traceback.format_exc()
finally:
    sys.settrace(None)

_elapsed = time.perf_counter() - _t0
print("|||TRACE_DATA|||")
print(json.dumps({
    "trace":   _trace_log,
    "output":  _stdout_lines,
    "error":   _error,
    "elapsed_ms": round(_elapsed * 1000, 2),
}))
'''

PROFILE_WRAPPER = '''
import cProfile, pstats, io, json, traceback, time

_error = None
_t0 = time.perf_counter()
profiler = cProfile.Profile()
_stdout = []
_orig_print = print
def _cap(*a, **kw):
    import io as _io; b=_io.StringIO()
    _orig_print(*a, file=b, **kw)
    _stdout.append(b.getvalue().rstrip())
    _orig_print(*a, **kw)
print = _cap

try:
    profiler.enable()
    {CODE_PLACEHOLDER}
    profiler.disable()
except Exception as e:
    profiler.disable()
    _error = traceback.format_exc()

_elapsed = time.perf_counter() - _t0

# Stats
s = io.StringIO()
ps = pstats.Stats(profiler, stream=s)
ps.sort_stats("cumulative")
ps.print_stats(20)

# Parse top functions
rows = []
for func, (cc, nc, tt, ct, callers) in profiler.getstats():
    if hasattr(func, "co_name"):
        rows.append({
            "func":     func.co_name,
            "file":     func.co_filename.split("/")[-1],
            "line":     func.co_firstlineno,
            "calls":    nc,
            "total_ms": round(tt * 1000, 3),
            "cum_ms":   round(ct * 1000, 3),
        })
rows.sort(key=lambda x: x["cum_ms"], reverse=True)

print("|||PROFILE_DATA|||")
print(json.dumps({
    "stats_text": s.getvalue(),
    "functions":  rows[:30],
    "output":     _stdout,
    "error":      _error,
    "elapsed_ms": round(_elapsed * 1000, 2),
}))
'''


def run_with_trace(code: str) -> dict:
    """Execute code with line-by-line trace. Returns trace steps + locals."""
    # Indent user code
    indented = textwrap.indent(code, "    ")
    wrapped  = TRACE_WRAPPER.replace("{CODE_PLACEHOLDER}", indented)

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w",
                                      delete=False, encoding="utf-8") as f:
        f.write(wrapped); tmp = f.name
    try:
        r = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace"
        )
        out = r.stdout + r.stderr
        if "|||TRACE_DATA|||" in out:
            json_str = out.split("|||TRACE_DATA|||")[1].strip().splitlines()[0]
            return json.loads(json_str)
        return {"error": out[:2000] or "No output", "trace": [], "output": []}
    except subprocess.TimeoutExpired:
        return {"error": "Timeout (30s)", "trace": [], "output": []}
    except Exception as e:
        return {"error": str(e), "trace": [], "output": []}
    finally:
        try: os.unlink(tmp)
        except: pass


def run_with_profile(code: str) -> dict:
    """Execute code with cProfile. Returns per-function timing."""
    indented = textwrap.indent(code, "    ")
    wrapped  = PROFILE_WRAPPER.replace("{CODE_PLACEHOLDER}", indented)

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w",
                                      delete=False, encoding="utf-8") as f:
        f.write(wrapped); tmp = f.name
    try:
        r = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace"
        )
        out = r.stdout + r.stderr
        if "|||PROFILE_DATA|||" in out:
            json_str = out.split("|||PROFILE_DATA|||")[1].strip().splitlines()[0]
            return json.loads(json_str)
        return {"error": out[:2000] or "No output", "functions": []}
    except subprocess.TimeoutExpired:
        return {"error": "Timeout (30s)", "functions": []}
    except Exception as e:
        return {"error": str(e), "functions": []}
    finally:
        try: os.unlink(tmp)
        except: pass


# ══════════════════════════════════════════════════════════════════════
#  AST ANALYSIS — data flow & function call graph
# ══════════════════════════════════════════════════════════════════════

def analyze_code(code: str, filename: str = "<code>") -> dict:
    """
    Static analysis via AST:
    - Functions defined + args + return type hints
    - Class hierarchy
    - Call graph (who calls who)
    - Variable assignments (data flow)
    - Import graph
    """
    try:
        tree = ast.parse(code, filename=filename)
    except SyntaxError as e:
        return {"error": f"SyntaxError: {e}", "functions": [], "calls": [], "imports": []}

    functions = []
    classes   = []
    calls     = []
    imports   = []
    variables = []
    call_graph = {}   # func → list of called funcs

    current_func = [None]

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            args  = [a.arg for a in node.args.args]
            rtype = ast.unparse(node.returns) if node.returns else None
            decorators = [ast.unparse(d) for d in node.decorator_list]
            docstring = ast.get_docstring(node) or ""
            functions.append({
                "name":       node.name,
                "line":       node.lineno,
                "args":       args,
                "return":     rtype,
                "decorators": decorators,
                "doc":        docstring[:100],
                "lines":      node.end_lineno - node.lineno + 1,
            })
            call_graph.setdefault(node.name, [])
            prev = current_func[0]
            current_func[0] = node.name
            self.generic_visit(node)
            current_func[0] = prev

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            bases = [ast.unparse(b) for b in node.bases]
            methods = [n.name for n in ast.walk(node)
                       if isinstance(n, ast.FunctionDef)]
            classes.append({
                "name":    node.name,
                "line":    node.lineno,
                "bases":   bases,
                "methods": methods,
            })
            self.generic_visit(node)

        def visit_Call(self, node):
            try:
                if isinstance(node.func, ast.Name):
                    callee = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    callee = f"{ast.unparse(node.func.value)}.{node.func.attr}"
                else:
                    callee = ast.unparse(node.func)[:50]
                caller = current_func[0] or "<module>"
                calls.append({"caller": caller, "callee": callee, "line": node.lineno})
                call_graph.setdefault(caller, [])
                if callee not in call_graph[caller]:
                    call_graph[caller].append(callee)
            except: pass
            self.generic_visit(node)

        def visit_Import(self, node):
            for alias in node.names:
                imports.append({"module": alias.name, "as": alias.asname, "line": node.lineno})

        def visit_ImportFrom(self, node):
            for alias in node.names:
                imports.append({
                    "module": f"{node.module}.{alias.name}",
                    "as": alias.asname,
                    "line": node.lineno,
                    "from": node.module,
                })

        def visit_Assign(self, node):
            for target in node.targets:
                try:
                    name = ast.unparse(target)
                    val  = ast.unparse(node.value)[:80]
                    variables.append({
                        "name": name, "value": val,
                        "line": node.lineno,
                        "scope": current_func[0] or "<module>",
                    })
                except: pass
            self.generic_visit(node)

    Visitor().visit(tree)

    # Build data-flow edges: variable written in func A, read in func B
    data_flow = []
    var_writers = {}
    for v in variables:
        var_writers.setdefault(v["name"], []).append(v["scope"])
    for call in calls:
        # If caller writes a var that callee reads → data flow edge
        data_flow.append({
            "from": call["caller"],
            "to":   call["callee"],
            "line": call["line"],
            "type": "call",
        })

    return {
        "functions":  functions,
        "classes":    classes,
        "calls":      calls[:100],
        "imports":    imports,
        "variables":  variables[:50],
        "call_graph": call_graph,
        "data_flow":  data_flow[:100],
        "lines":      len(code.splitlines()),
        "error":      None,
    }


def analyze_file(path: str) -> dict:
    """Analyze a file from disk."""
    try:
        code = Path(path).expanduser().read_text(encoding="utf-8", errors="replace")
        result = analyze_code(code, filename=path)
        result["file"] = path
        result["size_kb"] = round(len(code.encode()) / 1024, 1)
        return result
    except Exception as e:
        return {"error": str(e), "functions": [], "calls": [], "imports": []}


def analyze_project(root: str) -> dict:
    """Analyze entire project — cross-file call graph."""
    from pathlib import Path
    root_path = Path(root).expanduser()
    SKIP = {"__pycache__", ".git", "node_modules", ".venv", "venv", "dist", "build"}

    all_funcs   = {}   # file → functions
    all_imports = {}   # file → imports
    cross_calls = []   # {from_file, from_func, to_module, line}

    py_files = [
        f for f in root_path.rglob("*.py")
        if not any(s in f.parts for s in SKIP)
    ][:30]

    for pyf in py_files:
        try:
            code = pyf.read_text(encoding="utf-8", errors="replace")
            info = analyze_code(code, str(pyf))
            rel  = str(pyf.relative_to(root_path))
            all_funcs[rel]   = info["functions"]
            all_imports[rel] = info["imports"]
            for call in info["calls"]:
                cross_calls.append({
                    "file": rel,
                    "func": call["caller"],
                    "calls": call["callee"],
                    "line": call["line"],
                })
        except: pass

    return {
        "files":       list(all_funcs.keys()),
        "file_count":  len(py_files),
        "functions":   all_funcs,
        "imports":     all_imports,
        "cross_calls": cross_calls[:200],
    }
