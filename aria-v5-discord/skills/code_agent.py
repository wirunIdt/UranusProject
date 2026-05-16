"""
Code Agent — Claude Code style
Plan → Execute → Verify → Iterate loop
Handles: multi-file edit, git, tests, search, refactor
"""
import subprocess, shutil, os, re, json, threading, time
from pathlib import Path
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════
#  FILE TREE
# ══════════════════════════════════════════════════════════════════════

def get_file_tree(root: str = ".", max_depth: int = 4, max_files: int = 200) -> dict:
    """Return full file tree as nested dict."""
    root_path = Path(root).expanduser().resolve()
    IGNORE = {'.git','__pycache__','node_modules','.next','.nuxt','dist','build',
              '.venv','venv','env','.env','*.pyc','*.pyo','*.egg-info','.DS_Store',
              'thumbs.db','.idea','.vscode','coverage','*.min.js','*.min.css'}

    def _should_ignore(name: str) -> bool:
        for pat in IGNORE:
            if pat.startswith('*'):
                if name.endswith(pat[1:]): return True
            elif name == pat:
                return True
        return False

    def _build(path: Path, depth: int) -> dict | None:
        if depth > max_depth: return None
        if _should_ignore(path.name): return None
        if path.is_file():
            try:
                size = path.stat().st_size
                return {"type":"file","name":path.name,
                        "path":str(path),"size":size,
                        "ext":path.suffix.lstrip('.')}
            except: return None
        if path.is_dir():
            children = []
            try:
                for child in sorted(path.iterdir(),
                                    key=lambda x:(x.is_file(), x.name.lower())):
                    node = _build(child, depth+1)
                    if node: children.append(node)
                    if len(children) >= max_files: break
            except PermissionError:
                pass
            return {"type":"dir","name":path.name,
                    "path":str(path),"children":children}
        return None

    return _build(root_path, 0) or {"type":"dir","name":root_path.name,
                                     "path":str(root_path),"children":[]}


def search_in_files(query: str, path: str = ".", file_ext: str = "") -> list[dict]:
    """Grep-style search across files. Returns matches with context."""
    results = []
    root = Path(path).expanduser()
    pattern = re.compile(query, re.IGNORECASE)
    SKIP = {'.git','__pycache__','node_modules','.venv','venv','dist','build'}

    for fp in root.rglob("*"):
        if any(s in fp.parts for s in SKIP): continue
        if fp.is_dir(): continue
        if file_ext and fp.suffix != '.'+file_ext.lstrip('.'): continue
        if fp.stat().st_size > 500_000: continue  # skip large files
        try:
            lines = fp.read_text(encoding='utf-8', errors='replace').splitlines()
            for i, line in enumerate(lines):
                if pattern.search(line):
                    results.append({
                        "file":     str(fp),
                        "line_num": i + 1,
                        "line":     line.strip(),
                        "context":  lines[max(0,i-1):i+2],
                    })
                    if len(results) >= 50: return results
        except: pass
    return results


# ══════════════════════════════════════════════════════════════════════
#  GIT OPERATIONS
# ══════════════════════════════════════════════════════════════════════

def git_run(args: list[str], cwd: str = ".") -> str:
    try:
        r = subprocess.run(
            ["git"] + args, capture_output=True, text=True,
            cwd=str(Path(cwd).expanduser()), timeout=30,
            encoding="utf-8", errors="replace"
        )
        out = r.stdout.strip()
        err = r.stderr.strip()
        if r.returncode != 0 and err:
            return f"❌ {err}"
        return out or "(no output)"
    except FileNotFoundError:
        return "❌ git not found — install git"
    except Exception as e:
        return f"❌ {e}"


def git_status(cwd: str = ".") -> str:
    return git_run(["status", "--short", "--branch"], cwd)

def git_log(cwd: str = ".", n: int = 10) -> str:
    return git_run(["log", f"--oneline", f"-{n}"], cwd)

def git_diff(cwd: str = ".", file: str = "") -> str:
    args = ["diff", "--color=never"]
    if file: args.append(file)
    return git_run(args, cwd)

def git_add(files: str = ".", cwd: str = ".") -> str:
    return git_run(["add", files], cwd)

def git_commit(message: str, cwd: str = ".") -> str:
    return git_run(["commit", "-m", message], cwd)

def git_push(remote: str = "origin", branch: str = "", cwd: str = ".") -> str:
    args = ["push", remote]
    if branch: args.append(branch)
    return git_run(args, cwd)

def git_pull(cwd: str = ".") -> str:
    return git_run(["pull"], cwd)

def git_checkout(branch: str, create: bool = False, cwd: str = ".") -> str:
    args = ["checkout"]
    if create: args.append("-b")
    args.append(branch)
    return git_run(args, cwd)

def git_branches(cwd: str = ".") -> str:
    return git_run(["branch", "-a"], cwd)


# ══════════════════════════════════════════════════════════════════════
#  CODE EXECUTION + TESTING
# ══════════════════════════════════════════════════════════════════════

def run_tests(path: str = ".", framework: str = "auto") -> str:
    """Auto-detect and run tests (pytest, npm test, etc.)."""
    p = Path(path).expanduser()

    # Detect framework
    if framework == "auto":
        if (p/"package.json").exists():
            framework = "npm"
        elif list(p.rglob("test_*.py")) or list(p.rglob("*_test.py")):
            framework = "pytest"
        elif list(p.rglob("*.test.js")) or list(p.rglob("*.spec.js")):
            framework = "jest"
        else:
            framework = "pytest"

    cmds = {
        "pytest": ["python", "-m", "pytest", "--tb=short", "-v"],
        "npm":    ["npm", "test", "--", "--watchAll=false"],
        "jest":   ["npx", "jest", "--ci"],
        "cargo":  ["cargo", "test"],
        "go":     ["go", "test", "./..."],
    }
    cmd = cmds.get(framework, cmds["pytest"])

    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(p), timeout=120,
                           encoding="utf-8", errors="replace")
        out = (r.stdout + r.stderr).strip()
        return ("✅ Tests passed\n" if r.returncode == 0 else "❌ Tests failed\n") + out[:3000]
    except Exception as e:
        return f"❌ {e}"


def install_deps(path: str = ".") -> str:
    """Auto-detect and install dependencies."""
    p = Path(path).expanduser()
    if (p/"requirements.txt").exists():
        cmd = ["pip", "install", "-r", "requirements.txt", "--break-system-packages"]
    elif (p/"package.json").exists():
        cmd = ["npm", "install"]
    elif (p/"Cargo.toml").exists():
        cmd = ["cargo", "build"]
    elif (p/"go.mod").exists():
        cmd = ["go", "mod", "tidy"]
    else:
        return "❓ No dependency file found (requirements.txt, package.json, Cargo.toml)"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=str(p), timeout=120,
                           encoding="utf-8", errors="replace")
        return ("✅ Installed\n" if r.returncode == 0 else "❌ Failed\n") + (r.stdout+r.stderr)[:2000]
    except Exception as e:
        return f"❌ {e}"


def lint_file(path: str) -> str:
    """Run linter on file."""
    p = Path(path).expanduser()
    ext = p.suffix.lower()
    if ext == ".py":
        for linter in [["ruff", "check", str(p)],
                       ["flake8", str(p)],
                       ["pylint", "--output-format=text", str(p)]]:
            if shutil.which(linter[0]):
                try:
                    r = subprocess.run(linter, capture_output=True, text=True, timeout=30)
                    return f"🔍 {linter[0]}: " + (r.stdout or r.stderr or "No issues")
                except: continue
    elif ext in (".js",".ts",".jsx",".tsx"):
        if shutil.which("eslint"):
            r = subprocess.run(["eslint", str(p)], capture_output=True, text=True, timeout=30)
            return "🔍 eslint: " + (r.stdout or "No issues")
    return f"⚠️ No linter available for {ext}"


# ══════════════════════════════════════════════════════════════════════
#  AGENTIC PLAN-EXECUTE LOOP
# ══════════════════════════════════════════════════════════════════════

class CodeTask:
    """A coding task with plan → execute → verify loop."""

    def __init__(self, description: str, workspace: str = "."):
        self.description = description
        self.workspace   = str(Path(workspace).expanduser())
        self.steps: list[dict] = []
        self.status = "planning"
        self.result = ""
        self.created = datetime.now().isoformat()

    def add_step(self, action: str, detail: str, result: str = "", ok: bool = True):
        self.steps.append({
            "action": action,
            "detail": detail,
            "result": result,
            "ok":     ok,
            "ts":     datetime.now().isoformat(),
        })

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "workspace":   self.workspace,
            "status":      self.status,
            "result":      self.result,
            "steps":       self.steps,
            "created":     self.created,
        }


def execute_code_task(task: CodeTask, on_step=None) -> CodeTask:
    """
    Execute a code task step by step.
    on_step(step_dict) called after each step.
    """
    from skills.agent_system import (
        create_file, read_file, list_dir, run_shell, run_python
    )

    task.status = "running"

    # Step 1: Understand workspace
    tree_result = list_dir(task.workspace)
    task.add_step("explore", f"Exploring {task.workspace}", tree_result)
    if on_step: on_step(task.steps[-1])

    # Step 2: Execute based on description keywords
    desc_lower = task.description.lower()

    if any(k in desc_lower for k in ["install","pip install","npm install"]):
        result = install_deps(task.workspace)
        task.add_step("install", "Installing dependencies", result, "❌" not in result)
        if on_step: on_step(task.steps[-1])

    if any(k in desc_lower for k in ["test","pytest","jest","spec"]):
        result = run_tests(task.workspace)
        task.add_step("test", "Running tests", result, "✅" in result)
        if on_step: on_step(task.steps[-1])

    if any(k in desc_lower for k in ["git","commit","push","pull","status"]):
        result = git_status(task.workspace)
        task.add_step("git", "Git status", result)
        if on_step: on_step(task.steps[-1])

    # Completed
    task.status = "done"
    success_count = sum(1 for s in task.steps if s.get("ok", True))
    task.result = f"✅ Completed {success_count}/{len(task.steps)} steps"
    return task


# ══════════════════════════════════════════════════════════════════════
#  WEB SEARCH (DuckDuckGo scrape — no API key)
# ══════════════════════════════════════════════════════════════════════

def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search web via DuckDuckGo (no API key needed)."""
    import urllib.request, urllib.parse, html
    try:
        q   = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={q}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", errors="replace")

        results = []
        # Parse result snippets
        pattern = re.compile(
            r'<a class="result__a"[^>]*href="([^"]+)"[^>]*>(.+?)</a>'
            r'.*?<a class="result__snippet"[^>]*>(.+?)</a>',
            re.DOTALL
        )
        for m in pattern.finditer(body):
            url_raw, title, snippet = m.groups()
            results.append({
                "url":     html.unescape(url_raw),
                "title":   re.sub(r'<[^>]+>','', html.unescape(title)).strip(),
                "snippet": re.sub(r'<[^>]+>','', html.unescape(snippet)).strip(),
            })
            if len(results) >= max_results: break
        return results
    except Exception as e:
        return [{"url":"","title":f"Search error: {e}","snippet":""}]


def web_fetch(url: str, max_chars: int = 6000) -> str:
    """Fetch and extract text from a URL."""
    import urllib.request, html as html_mod
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # Strip tags
        text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>',  '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = html_mod.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars] + ("…" if len(text) > max_chars else "")
    except Exception as e:
        return f"❌ {e}"
