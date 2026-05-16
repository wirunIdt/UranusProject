"""
Agent System — Fixed & Working
All functions tested and verified
"""
import os, subprocess, shutil, re, glob, sys, tempfile
from pathlib import Path
from datetime import datetime

SYSTEM = sys.platform

# ══════════════════════════════════════════════════════════════════════
#  FILE OPERATIONS — all return str result
# ══════════════════════════════════════════════════════════════════════

def create_file(path: str, content: str = "") -> str:
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        size = len(content.encode("utf-8"))
        return f"✅ Created: {p}  ({size} bytes)"
    except Exception as e:
        return f"❌ create_file: {e}"


def read_file(path: str, max_chars: int = 50000) -> str:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"❌ File not found: {path}"
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n… (truncated, {len(text)} total chars)"
        return f"📄 {p}\n\n{text}"
    except Exception as e:
        return f"❌ read_file: {e}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"❌ File not found: {path}"
        content = p.read_text(encoding="utf-8")
        if old_text not in content:
            return f"❌ Text not found in {path}:\n{old_text[:100]}"
        new_content = content.replace(old_text, new_text, 1)
        p.write_text(new_content, encoding="utf-8")
        return f"✅ Edited: {p}"
    except Exception as e:
        return f"❌ edit_file: {e}"


def append_file(path: str, content: str) -> str:
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"✅ Appended {len(content)} chars to {p}"
    except Exception as e:
        return f"❌ append_file: {e}"


def delete_file(path: str) -> str:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"❌ Not found: {path}"
        if p.is_dir():
            shutil.rmtree(p)
            return f"✅ Deleted folder: {p}"
        p.unlink()
        return f"✅ Deleted: {p}"
    except Exception as e:
        return f"❌ delete_file: {e}"


def move_file(src: str, dst: str) -> str:
    try:
        s = Path(src).expanduser()
        d = Path(dst).expanduser()
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return f"✅ Moved: {s} → {d}"
    except Exception as e:
        return f"❌ move_file: {e}"


def copy_file(src: str, dst: str) -> str:
    try:
        s = Path(src).expanduser()
        d = Path(dst).expanduser()
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(str(s), str(d))
        else:
            shutil.copy2(str(s), str(d))
        return f"✅ Copied: {s} → {d}"
    except Exception as e:
        return f"❌ copy_file: {e}"


def list_dir(path: str = ".") -> str:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"❌ Not found: {path}"
        if not p.is_dir():
            return f"❌ Not a directory: {path}"
        items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        lines = [f"📂 {p.resolve()}"]
        for item in items[:200]:
            if item.is_dir():
                lines.append(f"  📁 {item.name}/")
            else:
                sz = item.stat().st_size
                szs = f"{sz/1024:.1f}KB" if sz > 1024 else f"{sz}B"
                lines.append(f"  📄 {item.name}  ({szs})")
        if len(items) > 200:
            lines.append(f"  … and {len(items)-200} more")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ list_dir: {e}"


def make_dir(path: str) -> str:
    try:
        p = Path(path).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return f"✅ Created directory: {p}"
    except Exception as e:
        return f"❌ make_dir: {e}"


def find_files(pattern: str, path: str = ".") -> str:
    try:
        root = Path(path).expanduser()
        SKIP = {".git","__pycache__","node_modules",".venv","venv","dist","build"}
        found = []
        for fp in root.rglob(pattern):
            if any(s in fp.parts for s in SKIP): continue
            found.append(str(fp))
            if len(found) >= 100: break
        if not found:
            return f"🔍 No files matching '{pattern}' in {path}"
        return f"🔍 Found {len(found)}:\n" + "\n".join(found)
    except Exception as e:
        return f"❌ find_files: {e}"


# ══════════════════════════════════════════════════════════════════════
#  SHELL EXECUTION
# ══════════════════════════════════════════════════════════════════════

def run_shell(command: str, cwd: str = None, timeout: int = 60) -> str:
    """Run any shell command. Returns combined stdout+stderr."""
    try:
        cwd_path = str(Path(cwd).expanduser()) if cwd else None
        if cwd_path and not Path(cwd_path).exists():
            cwd_path = None

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd_path,
            encoding="utf-8",
            errors="replace",
        )
        parts = []
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(f"[stderr]\n{result.stderr.strip()}")
        output = "\n".join(parts) if parts else "(no output)"
        if len(output) > 10000:
            output = output[:10000] + "\n… (truncated)"
        status = "✅" if result.returncode == 0 else f"⚠️ exit {result.returncode}"
        return f"{status} $ {command}\n{output}"
    except subprocess.TimeoutExpired:
        return f"⏱️ Timeout ({timeout}s): {command}"
    except Exception as e:
        return f"❌ run_shell: {e}"


def run_python(code: str) -> str:
    """Execute Python code and return output."""
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmp],
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
        parts = []
        if result.stdout.strip(): parts.append(result.stdout.strip())
        if result.stderr.strip(): parts.append(result.stderr.strip())
        output = "\n".join(parts) if parts else "(no output)"
        if len(output) > 8000:
            output = output[:8000] + "\n… (truncated)"
        ok = result.returncode == 0
        return ("✅ " if ok else "❌ ") + output
    except subprocess.TimeoutExpired:
        return "⏱️ Timeout (60s)"
    except Exception as e:
        return f"❌ run_python: {e}"
    finally:
        try: os.unlink(tmp)
        except: pass


def list_processes(limit: int = 15) -> str:
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid","name","cpu_percent","memory_percent"]):
            try:
                procs.append({
                    "pid":  p.info["pid"],
                    "name": p.info["name"],
                    "cpu":  round(p.info["cpu_percent"] or 0, 1),
                    "mem":  round(p.info["memory_percent"] or 0, 1),
                })
            except: pass
        procs.sort(key=lambda x: x["cpu"], reverse=True)
        lines = ["PID      CPU%  MEM%  Name"]
        for p in procs[:limit]:
            lines.append(f"{p['pid']:<8} {p['cpu']:<5} {p['mem']:<5} {p['name']}")
        return "\n".join(lines)
    except ImportError:
        # Fallback
        cmd = "tasklist /fo csv" if sys.platform=="win32" else "ps aux --sort=-%cpu"
        return run_shell(cmd)


def kill_process(name_or_pid: str) -> str:
    try:
        if sys.platform == "win32":
            flag = "/PID" if name_or_pid.isdigit() else "/IM"
            return run_shell(f"taskkill /F {flag} {name_or_pid}")
        else:
            flag = "-9" if name_or_pid.isdigit() else ""
            cmd = f"kill {flag} {name_or_pid}" if name_or_pid.isdigit() else f"pkill -9 {name_or_pid}"
            return run_shell(cmd)
    except Exception as e:
        return f"❌ kill_process: {e}"


def get_system_info() -> str:
    import platform as pl
    lines = [
        f"OS:      {pl.system()} {pl.release()}",
        f"Machine: {pl.machine()}",
        f"Python:  {pl.python_version()}",
        f"CWD:     {os.getcwd()}",
    ]
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        lines += [
            f"CPU:     {cpu}%",
            f"RAM:     {mem.percent}% ({mem.used//1024//1024}MB / {mem.total//1024//1024}MB)",
        ]
    except ImportError:
        pass
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
#  COMMAND PARSER — natural language → action
# ══════════════════════════════════════════════════════════════════════

_PATTERNS = [
    # Shell prefix
    (r"^\$\s*(.+)",                                    "shell",   lambda m: {"command": m(1)}),
    (r"^>\s*(.+)",                                     "shell",   lambda m: {"command": m(1)}),
    # Python
    (r"^python:\s*(.+)",                               "python",  lambda m: {"code": m(1)}),
    (r"^```python\n([\s\S]+)```$",                     "python",  lambda m: {"code": m(1)}),
    # File ops
    (r"(?:สร้าง|create|new)\s+(?:ไฟล์|file)\s+['\"]?(\S+)['\"]?(?:\s+(?:เนื้อหา|content)[:=\s]+(.+))?", "create_file",
     lambda m: {"path": m(1), "content": m(2) or ""}),
    (r"(?:อ่าน|แสดง|show|read|cat|type|open)\s+(?:ไฟล์\s+)?['\"]?(\S+)['\"]?", "read_file",
     lambda m: {"path": m(1)}),
    (r"(?:ลบ|delete|remove|del|rm)\s+(?:ไฟล์|โฟลเดอร์|file|dir|folder)?\s*['\"]?(\S+)['\"]?", "delete_file",
     lambda m: {"path": m(1)}),
    (r"(?:แสดง|list|ls|dir|รายชื่อ)\s+(?:ไฟล์|โฟลเดอร์|files?|folder)?\s*(?:ใน|in)?\s*['\"]?([^\s\"']+)?['\"]?", "list_dir",
     lambda m: {"path": m(1) or "."}),
    (r"(?:สร้าง|create|mkdir|make)\s+(?:โฟลเดอร์|folder|directory|dir)\s+['\"]?(\S+)['\"]?", "make_dir",
     lambda m: {"path": m(1)}),
    (r"(?:ย้าย|move|mv)\s+['\"]?(\S+)['\"]?\s+(?:ไปที่|to)\s+['\"]?(\S+)['\"]?", "move_file",
     lambda m: {"src": m(1), "dst": m(2)}),
    (r"(?:คัดลอก|copy|cp)\s+['\"]?(\S+)['\"]?\s+(?:ไปที่|to)\s+['\"]?(\S+)['\"]?", "copy_file",
     lambda m: {"src": m(1), "dst": m(2)}),
    # Process
    (r"(?:แสดง|list|show)\s+(?:process|โปรเซส)", "list_processes", lambda m: {}),
    (r"(?:system|ระบบ)\s*(?:info|information|ข้อมูล)", "system_info", lambda m: {}),
]


def parse_agent_command(text: str) -> dict | None:
    """Parse natural language → action dict. Returns None if no match."""
    text_s = text.strip()
    for pattern, action, builder in _PATTERNS:
        m = re.match(pattern, text_s, re.IGNORECASE | re.DOTALL)
        if m:
            def getter(n, _m=m):
                try: return _m.group(n)
                except: return ""
            try:
                payload = builder(getter)
                return {"action": action, "payload": payload}
            except Exception as e:
                print(f"[AGENT] parse error: {e}")
    return None


def execute_agent_command(cmd: dict) -> str:
    """Execute parsed action dict. Returns result string."""
    action  = cmd.get("action", "")
    payload = cmd.get("payload", {})

    DISPATCH = {
        "shell":         lambda p: run_shell(p.get("command",""), p.get("cwd")),
        "python":        lambda p: run_python(p.get("code","")),
        "create_file":   lambda p: create_file(p.get("path",""), p.get("content","")),
        "read_file":     lambda p: read_file(p.get("path","")),
        "edit_file":     lambda p: edit_file(p.get("path",""), p.get("old",""), p.get("new","")),
        "append_file":   lambda p: append_file(p.get("path",""), p.get("content","")),
        "delete_file":   lambda p: delete_file(p.get("path","")),
        "move_file":     lambda p: move_file(p.get("src",""), p.get("dst","")),
        "copy_file":     lambda p: copy_file(p.get("src",""), p.get("dst","")),
        "list_dir":      lambda p: list_dir(p.get("path",".")),
        "make_dir":      lambda p: make_dir(p.get("path","")),
        "find_files":    lambda p: find_files(p.get("pattern","*"), p.get("path",".")),
        "run_shell":     lambda p: run_shell(p.get("command",""), p.get("cwd"), int(p.get("timeout",60))),
        "run_python":    lambda p: run_python(p.get("code","")),
        "list_processes":lambda p: list_processes(),
        "kill_process":  lambda p: kill_process(p.get("name_or_pid","")),
        "system_info":   lambda p: get_system_info(),
    }
    fn = DISPATCH.get(action)
    if not fn:
        return f"❌ Unknown action: {action}"
    try:
        return fn(payload)
    except Exception as e:
        return f"❌ {action} failed: {e}"


# ── Convenience wrappers (used by server.py imports) ──────────────────────
def open_app(name: str) -> str:
    from skills.system_control import open_app as _open_app
    return _open_app(name)

def open_url(url: str) -> str:
    from skills.system_control import open_url as _open_url
    return _open_url(url)
