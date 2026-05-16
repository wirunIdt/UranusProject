"""
ARIA-AGI v3.0 — Advanced Reasoning & Intelligent Assistant
Flask Backend: 50+ API endpoints + 7-Layer AGI + Mesh Network
"""
import os, sys, json, time, uuid, sqlite3, subprocess, threading, socket
import traceback, ast, cProfile, pstats, io, importlib, textwrap, signal
import logging, hashlib, base64
from datetime import datetime
from pathlib import Path
from functools import wraps

import requests
import json
import psutil
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from flask_cors import CORS
try:
    from flask_socketio import SocketIO, emit, join_room, leave_room
    HAS_SOCKETIO = True
except ImportError:
    HAS_SOCKETIO = False

# ─── App Setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "aria-agi-secret-" + str(uuid.uuid4())[:8])
CORS(app, resources={r"/api/*": {"origins": "*"}})

if HAS_SOCKETIO:
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# ── ARIA v5 Modules ───────────────────────────────────────────────────────
import sys
sys.path.insert(0, os.path.dirname(__file__))
from modules import system as sys_mod
from modules import worldlayers as wl_mod
from modules import weather as weather_mod
from modules import finance as finance_mod
from modules import alerts as alerts_mod
from modules import freeinet as freeinet_mod
from modules.personal_ai_prompt import build_personal_ai_prompt, normalize_mode
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ARIA")

# ─── Auto-start Ollama ────────────────────────────────────────────────────
def ensure_ollama():
    """Start ollama serve if not already running"""
    def _check():
        try:
            requests.get("http://localhost:11434/api/tags", timeout=2)
            log.info("✓ Ollama already running")
            return
        except:
            pass
        log.info("⚡ Starting ollama serve...")
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            for i in range(15):
                time.sleep(1)
                try:
                    requests.get("http://localhost:11434/api/tags", timeout=2)
                    log.info("✓ Ollama started successfully")
                    return
                except:
                    pass
            log.warning("⚠ Ollama did not respond after 15s")
        except FileNotFoundError:
            log.warning("⚠ ollama not found — install from https://ollama.ai")
        except Exception as e:
            log.warning(f"⚠ Could not start ollama: {e}")

    threading.Thread(target=_check, daemon=True, name="ollama-autostart").start()

ensure_ollama()

# ─── Constants ────────────────────────────────────────────────────────────────
DB_PATH     = os.environ.get("ARIA_DB", "aria.db")
OLLAMA_URL  = os.environ.get("OLLAMA_URL", "http://localhost:11434")
WORKSPACE   = os.environ.get("WORKSPACE", str(Path.home()))
NODE_ID     = str(uuid.uuid4())[:8]
NODE_NAME   = socket.gethostname()
NODE_PORT   = int(os.environ.get("PORT", 5000))
MESH_PORT   = int(os.environ.get("MESH_PORT", 47777))
MESH_IFACE  = os.environ.get("MESH_IFACE", "0.0.0.0")
VERSION     = "5.0.0"

# ─── Database ─────────────────────────────────────────────────────────────────
def get_db():
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS short_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT, content TEXT, ts REAL DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS long_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE, value TEXT, ts REAL DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS episodic_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT, detail TEXT, ts REAL DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS task_queue (
            id TEXT PRIMARY KEY,
            desc TEXT, status TEXT DEFAULT 'pending',
            result TEXT, retries INTEGER DEFAULT 0,
            created REAL DEFAULT (strftime('%s','now')),
            updated REAL DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT, detail TEXT, ip TEXT,
            ts REAL DEFAULT (strftime('%s','now'))
        );
        CREATE TABLE IF NOT EXISTS personality_traits (
            key TEXT PRIMARY KEY, value TEXT
        );
        CREATE TABLE IF NOT EXISTS mesh_nodes (
            node_id TEXT PRIMARY KEY,
            name TEXT, ip TEXT, port INTEGER,
            last_seen REAL, info TEXT
        );
        CREATE TABLE IF NOT EXISTS mesh_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_node TEXT, from_name TEXT,
            to_node TEXT, content TEXT, encrypted INTEGER DEFAULT 0,
            ts REAL DEFAULT (strftime('%s','now'))
        );
        INSERT OR IGNORE INTO personality_traits VALUES ('name','ARIA');
        INSERT OR IGNORE INTO personality_traits VALUES ('style','Jarvis');
        INSERT OR IGNORE INTO personality_traits VALUES ('language','th-en');
        INSERT OR IGNORE INTO personality_traits VALUES ('tts_voice','PremwadeeNeural');
        INSERT OR IGNORE INTO personality_traits VALUES ('jokes_enabled','1');
        INSERT OR IGNORE INTO personality_traits VALUES ('mode','HYBRID');
        DELETE FROM personality_traits WHERE key='emergency_key';
    """)
    db.commit()
    db.close()

init_db()

# ─── Audit Helper ─────────────────────────────────────────────────────────────
def audit(action, detail="", ip="system"):
    db = get_db()
    db.execute("INSERT INTO audit_log(action,detail,ip) VALUES(?,?,?)", (action, str(detail)[:500], ip))
    db.commit(); db.close()

# ─── AGI 7-Layer Engine ───────────────────────────────────────────────────────
current_model = {"name": "qwen2.5:7b"}

def get_personality():
    db = get_db()
    rows = db.execute("SELECT key,value FROM personality_traits").fetchall()
    db.close()
    return {r["key"]: r["value"] for r in rows}

def build_system_prompt():
    p = get_personality()
    db = get_db()
    lm = db.execute("SELECT key,value FROM long_memory LIMIT 20").fetchall()
    db.close()
    facts = "\n".join(f"- {r['key']}: {r['value']}" for r in lm) or "none"
    return build_personal_ai_prompt(p, facts=facts, mode=normalize_mode(p.get("mode")))

# ─── Ollama Helper ────────────────────────────────────────────────────────────
def ollama_chat_stream(messages, model=None):
    m = model or current_model["name"]
    payload = {"model": m, "messages": messages, "stream": True}
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True, timeout=120)
        for line in r.iter_lines():
            if line:
                data = json.loads(line)
                if "message" in data:
                    yield data["message"].get("content", "")
                if data.get("done"):
                    break
    except Exception as e:
        yield f"\n[Ollama Error: {e}]"

def ollama_chat(messages, model=None):
    return "".join(ollama_chat_stream(messages, model))

# ─── Mesh Network ─────────────────────────────────────────────────────────────
mesh_lock = threading.Lock()
_running  = True

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

def mesh_announce():
    """Broadcast this node's presence via UDP"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(1)
    payload = json.dumps({
        "type": "ARIA_ANNOUNCE",
        "node_id": NODE_ID,
        "name": NODE_NAME,
        "ip": LOCAL_IP,
        "port": NODE_PORT,
        "version": VERSION,
        "ts": time.time()
    }).encode()
    try:
        sock.sendto(payload, ("<broadcast>", MESH_PORT))
    except:
        pass
    finally:
        sock.close()

def mesh_listen():
    """Listen for UDP broadcasts from other nodes"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass
    try:
        sock.bind(("0.0.0.0", MESH_PORT))
        sock.settimeout(2)
    except Exception as e:
        log.warning(f"Mesh listen bind failed: {e}")
        return

    while _running:
        try:
            data, addr = sock.recvfrom(4096)
            msg = json.loads(data.decode())
            if msg.get("type") == "ARIA_ANNOUNCE" and msg.get("node_id") != NODE_ID:
                db = get_db()
                db.execute("""
                    INSERT OR REPLACE INTO mesh_nodes(node_id,name,ip,port,last_seen,info)
                    VALUES(?,?,?,?,?,?)
                """, (msg["node_id"], msg["name"], msg["ip"], msg["port"],
                      time.time(), json.dumps(msg)))
                db.commit(); db.close()
                if HAS_SOCKETIO:
                    try:
                        socketio.emit("mesh_node", msg)
                    except:
                        pass
        except socket.timeout:
            pass
        except Exception as e:
            log.debug(f"Mesh listen error: {e}")
    sock.close()

def mesh_heartbeat():
    """Announce presence + prune dead nodes every 15s"""
    while _running:
        mesh_announce()
        # prune nodes not seen in 60s
        db = get_db()
        db.execute("DELETE FROM mesh_nodes WHERE last_seen < ?", (time.time() - 60,))
        db.commit(); db.close()
        time.sleep(15)

# Start mesh threads
threading.Thread(target=mesh_listen,    daemon=True, name="mesh-listen").start()
threading.Thread(target=mesh_heartbeat, daemon=True, name="mesh-beat").start()

# ─── Task Queue Runner ────────────────────────────────────────────────────────
def task_runner():
    while _running:
        db = get_db()
        rows = db.execute(
            "SELECT * FROM task_queue WHERE status='pending' AND retries < 3 LIMIT 1"
        ).fetchall()
        db.close()
        for row in rows:
            tid = row["id"]
            desc = row["desc"]
            try:
                msgs = [{"role": "system", "content": build_system_prompt()},
                        {"role": "user", "content": desc}]
                result = ollama_chat(msgs)
                db = get_db()
                db.execute("UPDATE task_queue SET status='done',result=?,updated=? WHERE id=?",
                           (result[:2000], time.time(), tid))
                db.commit(); db.close()
            except Exception as e:
                db = get_db()
                db.execute("UPDATE task_queue SET status='failed',retries=retries+1,updated=? WHERE id=?",
                           (time.time(), tid))
                db.commit(); db.close()
        time.sleep(3)

threading.Thread(target=task_runner, daemon=True, name="task-runner").start()

# ─── Routes: Pages ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("terminal.html",
        node_id=NODE_ID, node_name=NODE_NAME, local_ip=LOCAL_IP, version=VERSION)

@app.route("/terminal")
def terminal_page():
    return render_template("terminal.html",
        node_id=NODE_ID, node_name=NODE_NAME, local_ip=LOCAL_IP, version=VERSION)

@app.route("/finance")
def finance_page():
    return render_template("finance.html",
        node_id=NODE_ID, node_name=NODE_NAME, version=VERSION)

@app.route("/worldmonitor")
def worldmonitor_page():
    return render_template("worldmonitor.html",
        node_id=NODE_ID, node_name=NODE_NAME, version=VERSION)

@app.route("/chat")
def chat_page():
    return render_template("chat.html",
        node_id=NODE_ID, node_name=NODE_NAME, version=VERSION)

@app.route("/code")
def code_page():
    return render_template("code.html",
        node_id=NODE_ID, node_name=NODE_NAME, version=VERSION)

@app.route("/status")
def status_page():
    return render_template("status.html",
        node_id=NODE_ID, node_name=NODE_NAME, version=VERSION)

@app.route("/network")
def network_page():
    return render_template("network.html",
        node_id=NODE_ID, node_name=NODE_NAME, local_ip=LOCAL_IP, version=VERSION)

# ─── API: Chat (SSE Streaming) ────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.json or {}
    user_msg  = body.get("message", "")
    model     = body.get("model") or current_model["name"]
    use_mem   = body.get("memory", True)

    audit("chat", user_msg[:100], request.remote_addr)

    # save to short memory
    if use_mem:
        db = get_db()
        db.execute("INSERT INTO short_memory(role,content) VALUES(?,?)", ("user", user_msg))
        db.commit()
        history = db.execute(
            "SELECT role,content FROM short_memory ORDER BY ts DESC LIMIT 20"
        ).fetchall()
        db.close()
        msgs = [{"role": "system", "content": build_system_prompt()}]
        for h in reversed(history):
            msgs.append({"role": h["role"], "content": h["content"]})
    else:
        msgs = [{"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": user_msg}]

    def generate():
        full = ""
        for chunk in ollama_chat_stream(msgs, model):
            full += chunk
            yield f"data: {json.dumps({'content': chunk})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
        if use_mem:
            db = get_db()
            db.execute("INSERT INTO short_memory(role,content) VALUES(?,?)", ("assistant", full))
            db.commit(); db.close()

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ─── API: Models ──────────────────────────────────────────────────────────────
@app.route("/api/models")
def api_models():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = r.json().get("models", [])
        return jsonify({"models": models, "current": current_model["name"]})
    except:
        return jsonify({"models": [], "current": current_model["name"],
                        "error": "Ollama offline"})

@app.route("/api/models/switch", methods=["POST"])
def api_switch():
    name = request.json.get("name","")
    current_model["name"] = name
    audit("model_switch", name, request.remote_addr)
    return jsonify({"ok": True, "model": name})

@app.route("/api/models/pull", methods=["POST"])
def api_pull():
    name = request.json.get("name","")
    audit("model_pull", name, request.remote_addr)
    def gen():
        try:
            r = requests.post(f"{OLLAMA_URL}/api/pull",
                              json={"name": name}, stream=True, timeout=600)
            for line in r.iter_lines():
                if line:
                    yield f"data: {line.decode()}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error':str(e)})}\n\n"
        yield "data: {\"done\":true}\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache"})

# ─── API: Shell ───────────────────────────────────────────────────────────────
@app.route("/api/shell", methods=["POST"])
def api_shell():
    cmd = request.json.get("cmd","")
    cwd = request.json.get("cwd", WORKSPACE)
    timeout = request.json.get("timeout", 30)
    audit("shell", cmd[:200], request.remote_addr)
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout, cwd=cwd)
        return jsonify({"stdout": r.stdout, "stderr": r.stderr,
                        "code": r.returncode, "cmd": cmd})
    except subprocess.TimeoutExpired:
        return jsonify({"stdout":"","stderr":"Timeout","code":-1,"cmd":cmd})
    except Exception as e:
        return jsonify({"stdout":"","stderr":str(e),"code":-1,"cmd":cmd})

# ─── API: Python Execute ──────────────────────────────────────────────────────
@app.route("/api/python", methods=["POST"])
def api_python():
    code  = request.json.get("code","")
    audit("python", code[:100], request.remote_addr)
    buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    result = {"stdout":"","stderr":"","error":"","locals":{}}
    try:
        local_vars = {}
        exec(compile(code, "<aria>", "exec"), local_vars)
        result["stdout"] = buf.getvalue()
        result["locals"] = {k:repr(v) for k,v in local_vars.items()
                            if not k.startswith("_") and k != "__builtins__"}
    except Exception as e:
        result["error"] = traceback.format_exc()
        result["stdout"] = buf.getvalue()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return jsonify(result)

# ─── API: Python Profile ─────────────────────────────────────────────────────
@app.route("/api/python/profile", methods=["POST"])
def api_profile():
    code = request.json.get("code","")
    pr   = cProfile.Profile()
    buf  = io.StringIO()
    try:
        pr.enable()
        exec(compile(code, "<profile>", "exec"), {})
        pr.disable()
        s = pstats.Stats(pr, stream=buf)
        s.sort_stats("cumulative")
        s.print_stats(20)
        return jsonify({"profile": buf.getvalue()})
    except Exception as e:
        return jsonify({"profile":"","error":str(e)})

# ─── API: Code Trace ─────────────────────────────────────────────────────────
@app.route("/api/trace", methods=["POST"])
def api_trace():
    code = request.json.get("code","")
    steps = []
    def tracer(frame, event, arg):
        if event in ("line","call","return","exception"):
            info = {
                "event":   event,
                "file":    frame.f_code.co_filename,
                "func":    frame.f_code.co_name,
                "line":    frame.f_lineno,
                "locals":  {k: repr(v)[:80] for k,v in frame.f_locals.items()
                            if not k.startswith("_") and k != "__builtins__"},
            }
            if event == "return":
                info["return"] = repr(arg)[:80]
            if event == "exception":
                info["exc"] = repr(arg)[:80]
            if len(steps) < 200:
                steps.append(info)
        return tracer
    try:
        sys.settrace(tracer)
        exec(compile(code, "<trace>", "exec"), {})
    except Exception as e:
        steps.append({"event":"exception","error":str(e)})
    finally:
        sys.settrace(None)
    return jsonify({"steps": steps})

# ─── API: AST Analysis ───────────────────────────────────────────────────────
@app.route("/api/ast", methods=["POST"])
def api_ast():
    code = request.json.get("code","")
    try:
        tree = ast.parse(code)
        nodes = []
        for node in ast.walk(tree):
            n = {"type": type(node).__name__}
            if isinstance(node, ast.FunctionDef):
                n["name"] = node.name; n["line"] = node.lineno
                n["args"] = [a.arg for a in node.args.args]
            elif isinstance(node, ast.ClassDef):
                n["name"] = node.name; n["line"] = node.lineno
            elif isinstance(node, ast.Import):
                n["names"] = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                n["module"] = node.module
                n["names"]  = [a.name for a in node.names]
            nodes.append(n)
        return jsonify({"nodes": nodes, "dump": ast.dump(tree, indent=2)[:3000]})
    except SyntaxError as e:
        return jsonify({"nodes":[], "error": str(e)})

# ─── API: Filesystem ─────────────────────────────────────────────────────────
@app.route("/api/fs/list")
def api_fs_list():
    path = request.args.get("path", WORKSPACE)
    try:
        p    = Path(path)
        items = []
        for entry in sorted(p.iterdir(), key=lambda x:(x.is_file(), x.name)):
            try:
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "type": "dir" if entry.is_dir() else "file",
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "ext":  entry.suffix.lstrip(".")
                })
            except:
                pass
        return jsonify({"items": items, "path": str(p)})
    except Exception as e:
        return jsonify({"items":[], "error": str(e)})

@app.route("/api/fs/read")
def api_fs_read():
    path = request.args.get("path","")
    try:
        content = Path(path).read_text(errors="replace")
        return jsonify({"content": content, "path": path})
    except Exception as e:
        return jsonify({"content":"","error":str(e)})

@app.route("/api/fs/write", methods=["POST"])
def api_fs_write():
    body = request.json or {}
    path, content = body.get("path",""), body.get("content","")
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content)
        audit("fs_write", path, request.remote_addr)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/api/fs/delete", methods=["POST"])
def api_fs_delete():
    path = request.json.get("path","")
    try:
        p = Path(path)
        if p.is_dir():
            import shutil; shutil.rmtree(p)
        else:
            p.unlink()
        audit("fs_delete", path, request.remote_addr)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/api/fs/mkdir", methods=["POST"])
def api_fs_mkdir():
    path = request.json.get("path","")
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/api/fs/search")
def api_fs_search():
    q    = request.args.get("q","")
    root = request.args.get("root", WORKSPACE)
    results = []
    try:
        for p in Path(root).rglob(f"*{q}*"):
            if len(results) >= 50: break
            results.append({"path":str(p),"type":"dir" if p.is_dir() else "file"})
    except:
        pass
    return jsonify({"results":results})

# ─── API: Git ─────────────────────────────────────────────────────────────────
@app.route("/api/git", methods=["POST"])
def api_git():
    body    = request.json or {}
    action  = body.get("action","status")
    cwd     = body.get("cwd", WORKSPACE)
    message = body.get("message","Auto commit")
    branch  = body.get("branch","")

    cmds = {
        "status":  "git status",
        "log":     "git log --oneline -15",
        "diff":    "git diff",
        "add":     "git add -A",
        "commit":  f"git commit -m '{message}'",
        "push":    "git push",
        "pull":    "git pull",
        "branch":  "git branch -a",
        "checkout":f"git checkout {branch}",
        "init":    "git init",
    }
    cmd = cmds.get(action, f"git {action}")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=30, cwd=cwd)
        return jsonify({"stdout":r.stdout,"stderr":r.stderr,"code":r.returncode})
    except Exception as e:
        return jsonify({"stdout":"","stderr":str(e),"code":-1})

# ─── API: System Status ───────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    try:
        cpu_per = psutil.cpu_percent(interval=0.3, percpu=True)
        mem     = psutil.virtual_memory()
        disk    = psutil.disk_usage("/")
        net     = psutil.net_io_counters()
        boot    = psutil.boot_time()

        gpu = {"available": False}
        try:
            r = subprocess.run(
                ["nvidia-smi","--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                parts = r.stdout.strip().split(",")
                gpu = {
                    "available": True,
                    "name":     parts[0].strip(),
                    "temp":     int(parts[1].strip()),
                    "util":     int(parts[2].strip()),
                    "mem_used": int(parts[3].strip()),
                    "mem_total":int(parts[4].strip()),
                }
        except:
            pass

        # Ollama status
        ollama_ok = False
        try:
            requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
            ollama_ok = True
        except:
            pass

        # mesh node count
        db = get_db()
        mesh_count = db.execute("SELECT COUNT(*) FROM mesh_nodes WHERE last_seen > ?",
                                (time.time()-60,)).fetchone()[0]
        db.close()

        return jsonify({
            "cpu":        {"percent": sum(cpu_per)/len(cpu_per) if cpu_per else 0,
                           "per_core": cpu_per, "count": psutil.cpu_count()},
            "memory":     {"total":mem.total,"used":mem.used,"percent":mem.percent},
            "disk":       {"total":disk.total,"used":disk.used,"percent":disk.percent},
            "network":    {"bytes_sent":net.bytes_sent,"bytes_recv":net.bytes_recv},
            "gpu":        gpu,
            "boot_time":  boot,
            "uptime":     int(time.time()-boot),
            "ollama":     ollama_ok,
            "model":      current_model["name"],
            "node_id":    NODE_ID,
            "node_name":  NODE_NAME,
            "local_ip":   LOCAL_IP,
            "mesh_peers": mesh_count,
        })
    except Exception as e:
        return jsonify({"error":str(e)})

# ─── API: Processes ───────────────────────────────────────────────────────────
@app.route("/api/processes")
def api_processes():
    procs = []
    for p in sorted(psutil.process_iter(["pid","name","cpu_percent","memory_percent","status"]),
                    key=lambda x: x.info["cpu_percent"] or 0, reverse=True)[:30]:
        try:
            procs.append(p.info)
        except:
            pass
    return jsonify({"processes": procs})

@app.route("/api/processes/<int:pid>/kill", methods=["POST"])
def api_kill(pid):
    try:
        os.kill(pid, signal.SIGTERM)
        audit("kill_process", str(pid), request.remote_addr)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

# ─── API: Memory ─────────────────────────────────────────────────────────────
@app.route("/api/memory/short")
def api_mem_short():
    db = get_db()
    rows = db.execute("SELECT * FROM short_memory ORDER BY ts DESC LIMIT 50").fetchall()
    db.close()
    return jsonify({"messages": [dict(r) for r in rows]})

@app.route("/api/memory/long", methods=["GET","POST","DELETE"])
def api_mem_long():
    db = get_db()
    if request.method == "GET":
        rows = db.execute("SELECT * FROM long_memory ORDER BY ts DESC").fetchall()
        db.close()
        return jsonify({"memories":[dict(r) for r in rows]})
    elif request.method == "POST":
        k,v = request.json.get("key",""), request.json.get("value","")
        db.execute("INSERT OR REPLACE INTO long_memory(key,value) VALUES(?,?)",(k,v))
        db.commit(); db.close()
        return jsonify({"ok":True})
    else:
        k = request.json.get("key","")
        db.execute("DELETE FROM long_memory WHERE key=?", (k,))
        db.commit(); db.close()
        return jsonify({"ok":True})

@app.route("/api/memory/episodic", methods=["GET","POST"])
def api_mem_episodic():
    db = get_db()
    if request.method == "POST":
        e,d = request.json.get("event",""), request.json.get("detail","")
        db.execute("INSERT INTO episodic_memory(event,detail) VALUES(?,?)",(e,d))
        db.commit(); db.close()
        return jsonify({"ok":True})
    rows = db.execute("SELECT * FROM episodic_memory ORDER BY ts DESC LIMIT 50").fetchall()
    db.close()
    return jsonify({"episodes":[dict(r) for r in rows]})


# ─── API: Tasks ───────────────────────────────────────────────────────────────
@app.route("/api/tasks", methods=["GET","POST"])
def api_tasks():
    db = get_db()
    if request.method == "POST":
        tid  = str(uuid.uuid4())[:8]
        desc = request.json.get("desc","")
        db.execute("INSERT INTO task_queue(id,desc) VALUES(?,?)",(tid,desc))
        db.commit(); db.close()
        return jsonify({"ok":True,"id":tid})
    rows = db.execute("SELECT * FROM task_queue ORDER BY created DESC LIMIT 50").fetchall()
    db.close()
    return jsonify({"tasks":[dict(r) for r in rows]})

@app.route("/api/tasks/<tid>", methods=["DELETE"])
def api_task_delete(tid):
    db = get_db()
    db.execute("DELETE FROM task_queue WHERE id=?", (tid,))
    db.commit(); db.close()
    return jsonify({"ok":True})

# ─── API: Audit Log ───────────────────────────────────────────────────────────
@app.route("/api/audit")
def api_audit():
    db = get_db()
    rows = db.execute("SELECT * FROM audit_log ORDER BY ts DESC LIMIT 100").fetchall()
    db.close()
    return jsonify({"logs":[dict(r) for r in rows]})

# ─── API: Web Search ─────────────────────────────────────────────────────────
@app.route("/api/websearch")
def api_websearch():
    q = request.args.get("q","")
    try:
        headers = {"User-Agent":"Mozilla/5.0 (ARIA-AGI) Gecko/20100101 Firefox/118"}
        r = requests.get(f"https://html.duckduckgo.com/html/?q={requests.utils.quote(q)}",
                         headers=headers, timeout=10)
        from html.parser import HTMLParser
        class DDGParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.results=[]
                self._in_result=False
                self._cur={}
            def handle_starttag(self,tag,attrs):
                d=dict(attrs)
                if tag=="a" and "result__a" in d.get("class",""):
                    self._cur={"href":d.get("href","")}
                    self._in_result=True
            def handle_endtag(self,tag):
                if tag=="a" and self._in_result:
                    self._in_result=False
                    if self._cur.get("title"):
                        self.results.append(self._cur)
                        self._cur={}
            def handle_data(self,data):
                if self._in_result and data.strip():
                    self._cur["title"]=data.strip()
        parser=DDGParser()
        parser.feed(r.text)
        return jsonify({"results":parser.results[:10],"query":q})
    except Exception as e:
        return jsonify({"results":[],"error":str(e)})

# ─── API: Personality ─────────────────────────────────────────────────────────
@app.route("/api/personality", methods=["GET","POST"])
def api_personality():
    db = get_db()
    if request.method == "POST":
        for k,v in (request.json or {}).items():
            db.execute("INSERT OR REPLACE INTO personality_traits(key,value) VALUES(?,?)",(k,v))
        db.commit(); db.close()
        return jsonify({"ok":True})
    rows = db.execute("SELECT key,value FROM personality_traits").fetchall()
    db.close()
    return jsonify({r["key"]:r["value"] for r in rows})

# ─── API: Joke ────────────────────────────────────────────────────────────────
@app.route("/api/joke")
def api_joke():
    msgs = [{"role":"user","content":"เล่าเรื่องตลก IT หรือ AI สั้นๆ 1 ข้อ เป็นภาษาไทย"}]
    joke = ollama_chat(msgs)
    return jsonify({"joke": joke})

# ─── API: Owner Recovery Status ──────────────────────────────────────────────
@app.route("/api/emergency", methods=["POST"])
def api_emergency():
    audit("owner_recovery_requested", "disabled_command_channel", request.remote_addr)
    return jsonify({
        "ok": False,
        "error": "Emergency command execution is disabled.",
        "recovery": (
            "Use the normal authenticated console or local terminal. "
            "ARIA does not provide a hidden backdoor or secret command bypass."
        )
    }), 403

# ─── API: Mesh Network ────────────────────────────────────────────────────────
@app.route("/api/mesh/nodes")
def api_mesh_nodes():
    db = get_db()
    nodes = db.execute(
        "SELECT * FROM mesh_nodes WHERE last_seen > ?", (time.time()-120,)
    ).fetchall()
    db.close()
    result = [dict(n) for n in nodes]
    # Add self
    result.insert(0, {
        "node_id":   NODE_ID,
        "name":      NODE_NAME,
        "ip":        LOCAL_IP,
        "port":      NODE_PORT,
        "last_seen": time.time(),
        "is_self":   True
    })
    return jsonify({"nodes": result})

@app.route("/api/mesh/scan", methods=["POST"])
def api_mesh_scan():
    """Force a broadcast announce"""
    mesh_announce()
    return jsonify({"ok":True, "message":"Broadcast sent"})

@app.route("/api/mesh/send", methods=["POST"])
def api_mesh_send():
    """Send HTTP message to a specific node"""
    body    = request.json or {}
    to_ip   = body.get("ip","")
    to_port = body.get("port", NODE_PORT)
    content = body.get("content","")
    to_node = body.get("node_id","")
    encrypted = body.get("encrypted", False)

    if encrypted:
        # Simple XOR obfuscation (demo — real system should use proper crypto)
        key = b"ARIA-MESH-KEY"
        enc = bytes([ord(c) ^ key[i % len(key)] for i,c in enumerate(content)])
        content_send = base64.b64encode(enc).decode()
    else:
        content_send = content

    try:
        r = requests.post(
            f"http://{to_ip}:{to_port}/api/mesh/receive",
            json={"from_node":NODE_ID,"from_name":NODE_NAME,
                  "content":content_send,"encrypted":encrypted},
            timeout=5
        )
        # save to db
        db = get_db()
        db.execute(
            "INSERT INTO mesh_messages(from_node,from_name,to_node,content,encrypted) VALUES(?,?,?,?,?)",
            (NODE_ID, NODE_NAME, to_node, content, 1 if encrypted else 0)
        )
        db.commit(); db.close()
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/api/mesh/receive", methods=["POST"])
def api_mesh_receive():
    """Receive a message from another node"""
    body      = request.json or {}
    from_node = body.get("from_node","?")
    from_name = body.get("from_name","?")
    content   = body.get("content","")
    encrypted = body.get("encrypted", False)

    if encrypted:
        try:
            key = b"ARIA-MESH-KEY"
            dec_bytes = base64.b64decode(content)
            content = "".join(chr(b ^ key[i % len(key)]) for i,b in enumerate(dec_bytes))
        except:
            pass

    db = get_db()
    db.execute(
        "INSERT INTO mesh_messages(from_node,from_name,to_node,content,encrypted) VALUES(?,?,?,?,?)",
        (from_node, from_name, NODE_ID, content, 1 if encrypted else 0)
    )
    db.commit(); db.close()

    if HAS_SOCKETIO:
        try:
            socketio.emit("mesh_message", {
                "from_node":from_node,"from_name":from_name,"content":content,"ts":time.time()
            })
        except:
            pass

    return jsonify({"ok":True})

@app.route("/api/mesh/broadcast", methods=["POST"])
def api_mesh_broadcast():
    """Send message to all known nodes"""
    content = request.json.get("content","")
    db = get_db()
    nodes = db.execute(
        "SELECT * FROM mesh_nodes WHERE last_seen > ?", (time.time()-60,)
    ).fetchall()
    db.close()
    results = []
    for node in nodes:
        try:
            r = requests.post(
                f"http://{node['ip']}:{node['port']}/api/mesh/receive",
                json={"from_node":NODE_ID,"from_name":NODE_NAME,"content":content,"encrypted":False},
                timeout=3
            )
            results.append({"node":node["name"],"ok":r.ok})
        except Exception as e:
            results.append({"node":node["name"],"ok":False,"error":str(e)})
    return jsonify({"results":results,"sent_to":len(results)})

@app.route("/api/mesh/messages")
def api_mesh_messages():
    limit = int(request.args.get("limit",50))
    db = get_db()
    rows = db.execute(
        "SELECT * FROM mesh_messages ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    db.close()
    return jsonify({"messages":[dict(r) for r in rows]})

@app.route("/api/mesh/info")
def api_mesh_info():
    """Return this node's info"""
    return jsonify({
        "node_id":   NODE_ID,
        "name":      NODE_NAME,
        "ip":        LOCAL_IP,
        "port":      NODE_PORT,
        "version":   VERSION,
        "mesh_port": MESH_PORT,
        "ts":        time.time()
    })

# ─── SocketIO Events ──────────────────────────────────────────────────────────
if HAS_SOCKETIO:
    @socketio.on("connect")
    def on_connect():
        emit("node_info", {"node_id":NODE_ID,"name":NODE_NAME,"ip":LOCAL_IP})

    @socketio.on("mesh_chat")
    def on_mesh_chat(data):
        emit("mesh_message", data, broadcast=True)

# ─── Intranet Module Init ────────────────────────────────────────────────
try:
    from modules.mesh_intranet import init_intranet, get_intranet
    _intranet = init_intranet(NODE_ID, NODE_NAME, LOCAL_IP, NODE_PORT)
    HAS_INTRANET = True
    log.info("Intranet module started")
except Exception as e:
    HAS_INTRANET = False
    log.warning(f"Intranet module not started: {e}")
    def get_intranet(): return None

# ─── Intranet Routes ──────────────────────────────────────────────────────
@app.route("/intranet")
def intranet_page():
    return render_template("intranet.html",
        node_id=NODE_ID, node_name=NODE_NAME, local_ip=LOCAL_IP, version=VERSION)

@app.route("/api/intranet/dns")
def api_intranet_dns():
    intr = get_intranet()
    if not intr: return jsonify({"dns":{}})
    return jsonify({"dns": intr.get_dns_map()})

@app.route("/api/intranet/dns/add", methods=["POST"])
def api_intranet_dns_add():
    intr = get_intranet()
    if not intr: return jsonify({"ok":False,"error":"Intranet not running"})
    body = request.json or {}
    intr.add_dns(body.get("hostname",""), body.get("ip",""))
    return jsonify({"ok":True})

@app.route("/api/intranet/dns/delete", methods=["POST"])
def api_intranet_dns_delete():
    intr = get_intranet()
    if not intr: return jsonify({"ok":False})
    intr.remove_dns(request.json.get("hostname",""))
    return jsonify({"ok":True})

@app.route("/api/intranet/services")
def api_intranet_services():
    intr = get_intranet()
    if not intr: return jsonify({"services":{}})
    return jsonify({"services": intr.get_services()})

@app.route("/api/intranet/services/register", methods=["POST"])
def api_intranet_svc_register():
    intr = get_intranet()
    if not intr: return jsonify({"ok":False})
    body = request.json or {}
    intr.register_service(body.get("name",""), int(body.get("port",0)), body.get("desc",""))
    return jsonify({"ok":True})

@app.route("/api/intranet/peers")
def api_intranet_peers():
    intr = get_intranet()
    if not intr: return jsonify({"peers":{}})
    return jsonify({"peers": intr.get_peers()})

@app.route("/api/intranet/resolve")
def api_intranet_resolve():
    intr = get_intranet()
    hostname = request.args.get("q","")
    if not intr: return jsonify({"ip":None})
    return jsonify({"ip": intr.resolve(hostname), "hostname": hostname})

@app.route("/api/intranet/proxy", methods=["POST"])
def api_intranet_proxy():
    url = request.json.get("url","")
    intr = get_intranet()
    if intr:
        content, cached, error = intr.proxy_request(url, timeout=8)
    else:
        try:
            r = requests.get(url, timeout=8, headers={"User-Agent":"ARIA-Intranet/3"})
            content, error = r.text, None
        except Exception as e:
            content, error = None, str(e)
    if error:
        return jsonify({"online":False,"error":error})
    return jsonify({"online":True,"length":len(content),"snippet":content[:200] if content else ""})

@app.route("/api/intranet/connectivity")
def api_intranet_connectivity():
    """Check if external internet is reachable"""
    try:
        requests.get("https://www.google.com", timeout=5)
        return jsonify({"online":True})
    except:
        pass
    try:
        requests.get("https://1.1.1.1", timeout=3)
        return jsonify({"online":True})
    except:
        pass
    return jsonify({"online":False})





# ═══════════════════════════════════════════════════════════════════════════
# ─── API: Realtime SSE Stream ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/stream")
def api_stream():
    """Server-Sent Events — push system stats every 2s"""
    def gen():
        while True:
            try:
                data = {
                    "cpu":     sys_mod.get_cpu(),
                    "memory":  sys_mod.get_memory(),
                    "network": sys_mod.get_network(),
                    "gpu":     sys_mod.get_gpu(),
                    "uptime":  sys_mod.get_uptime(),
                    "ts":      time.time(),
                }
                yield f"data: {json.dumps(data)}\n\n"
                time.sleep(2)
            except GeneratorExit:
                break
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                time.sleep(5)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache","Access-Control-Allow-Origin":"*"})

# ─── API: Weather ──────────────────────────────────────────────────────────


@app.route("/api/weather/stream")
def api_weather_stream():
    city = request.args.get("city", "Bangkok")
    def gen():
        while True:
            try:
                data = weather_mod.get_weather(city)
                yield f"data: {json.dumps(data)}\n\n"
                time.sleep(300)  # refresh every 5 min
            except GeneratorExit:
                break
    return Response(gen(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache"})

# ─── API: Finance ──────────────────────────────────────────────────────────
@app.route("/api/finance/crypto")
def api_crypto():
    syms = request.args.get("symbols","").upper().split(",") if request.args.get("symbols") else None
    return jsonify(finance_mod.get_crypto_prices(syms))

@app.route("/api/finance/forex")
def api_forex():
    return jsonify(finance_mod.get_forex())

@app.route("/api/finance/indices")
def api_indices():
    return jsonify(finance_mod.get_indices())

@app.route("/api/finance/thai")
def api_thai_stocks():
    syms = request.args.get("symbols","").upper().split(",") if request.args.get("symbols") else None
    return jsonify(finance_mod.get_thai_stocks(syms))

@app.route("/api/finance/us")
def api_us_stocks():
    syms = request.args.get("symbols","").upper().split(",") if request.args.get("symbols") else None
    return jsonify(finance_mod.get_us_stocks(syms))

@app.route("/api/finance/stream")
def api_finance_stream():
    """SSE stream for crypto prices every 30s"""
    def gen():
        while True:
            try:
                data = {
                    "crypto":  finance_mod.get_crypto_prices(),
                    "forex":   finance_mod.get_forex(),
                    "ts":      time.time(),
                }
                yield f"data: {json.dumps(data)}\n\n"
                time.sleep(30)
            except GeneratorExit:
                break
    return Response(gen(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache"})

# ─── API: Alerts ───────────────────────────────────────────────────────────




# ─── API: Free Internet / Decentralized ───────────────────────────────────
@app.route("/api/freeinet/status")
def api_freeinet_status():
    return jsonify(freeinet_mod.full_status())

@app.route("/api/freeinet/doh", methods=["POST"])
def api_doh_lookup():
    body   = request.json or {}
    host   = body.get("host","google.com")
    server = body.get("server","Cloudflare")
    return jsonify(freeinet_mod.doh_lookup(host, server))

@app.route("/api/freeinet/tor/status")
def api_tor_status():
    return jsonify(freeinet_mod.tor_status())

@app.route("/api/freeinet/tor/start", methods=["POST"])
def api_tor_start():
    return jsonify(freeinet_mod.tor_start())

@app.route("/api/freeinet/tor/ip")
def api_tor_ip():
    return jsonify(freeinet_mod.get_tor_ip())



@app.route("/api/freeinet/batman", methods=["POST"])
def api_batman():
    body  = request.json or {}
    iface = body.get("iface","wlan0")
    if body.get("setup"):
        return jsonify(freeinet_mod.setup_batman(iface))
    return jsonify(freeinet_mod.batman_status())

# ─── API: File Upload → AI ─────────────────────────────────────────────────
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)







# ═══════════════════════════════════════════════════════════════════════════
# ─── API: WorldMonitor Data (native, no iframe) ───────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

WM_CACHE = {}
WM_CACHE_TTL = {"quakes":120,"flights":30,"news":300,"solar":600,"airq":180,"ships":120}

def wm_cached(key, ttl=120):
    c = WM_CACHE.get(key)
    return c["d"] if c and time.time()-c["t"]<ttl else None
def wm_store(key, data):
    WM_CACHE[key]={"d":data,"t":time.time()}

def wm_get(url, **kw):
    return requests.get(url, timeout=10,
        headers={"User-Agent":"ARIA-WorldMonitor/5","Accept":"application/json"},
        **kw)

@app.route("/api/wm/earthquakes")
def api_wm_quakes():
    c=wm_cached("quakes",WM_CACHE_TTL["quakes"])
    if c: return jsonify(c)
    try:
        mn=float(request.args.get("min","2.5"))
        period=request.args.get("period","day")  # hour day week month
        url=f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{mn}_{period}.geojson"
        d=wm_get(url).json()
        out=[]
        for f in d.get("features",[])[:100]:
            p=f["properties"]; c2=f["geometry"]["coordinates"]
            out.append({
                "id":f["id"],"mag":p.get("mag",0),"place":p.get("place",""),
                "time":p.get("time",0),"depth":c2[2] if len(c2)>2 else 0,
                "lon":c2[0],"lat":c2[1],
                "alert":p.get("alert"),"tsunami":p.get("tsunami",0),
                "type":p.get("type","earthquake"),
            })
        out.sort(key=lambda x:x["mag"],reverse=True)
        wm_store("quakes",out); return jsonify(out)
    except Exception as e:
        return jsonify({"error":str(e)})

@app.route("/api/wm/flights")
def api_wm_flights():
    c=wm_cached("flights",WM_CACHE_TTL["flights"])
    if c: return jsonify(c)
    try:
        # OpenSky Network — free, no key needed
        lat_min=float(request.args.get("lat_min",5))
        lat_max=float(request.args.get("lat_max",20))
        lon_min=float(request.args.get("lon_min",97))
        lon_max=float(request.args.get("lon_max",105))
        url=(f"https://opensky-network.org/api/states/all"
             f"?lamin={lat_min}&lamax={lat_max}&lomin={lon_min}&lomax={lon_max}")
        d=requests.get(url,timeout=8,headers={"User-Agent":"ARIA/5"}).json()
        states=d.get("states",[]) or []
        out=[]
        for s in states[:80]:
            if s[5] is None or s[6] is None: continue
            out.append({
                "icao":s[0],"callsign":(s[1] or "").strip()[:8],
                "country":s[2],"lon":s[5],"lat":s[6],
                "alt":round(s[7],0) if s[7] else 0,
                "vel":round(s[9],0) if s[9] else 0,
                "hdg":round(s[10],0) if s[10] else 0,
                "on_ground":s[8],
            })
        wm_store("flights",out); return jsonify(out)
    except Exception as e:
        return jsonify({"error":str(e)})

@app.route("/api/wm/flights/global")
def api_wm_flights_global():
    """Sample flights from multiple regions"""
    c=wm_cached("flights_global",60)
    if c: return jsonify(c)
    try:
        d=requests.get("https://opensky-network.org/api/states/all",timeout=10,
                       headers={"User-Agent":"ARIA/5"}).json()
        states=d.get("states",[]) or []
        out=[]
        for s in states[:200]:
            if s[5] is None or s[6] is None: continue
            out.append({"icao":s[0],"callsign":(s[1] or "").strip()[:8],
                        "country":s[2],"lon":s[5],"lat":s[6],
                        "alt":round(s[7],0) if s[7] else 0,
                        "vel":round(s[9],0) if s[9] else 0,
                        "hdg":round(s[10],0) if s[10] else 0,
                        "on_ground":s[8]})
        wm_store("flights_global",out); return jsonify(out)
    except Exception as e:
        return jsonify({"error":str(e)})

@app.route("/api/wm/news")
def api_wm_news():
    c=wm_cached("news",WM_CACHE_TTL["news"])
    if c: return jsonify(c)
    feeds=[
        ("BBC World","https://feeds.bbci.co.uk/news/world/rss.xml","world"),
        ("Reuters","https://feeds.reuters.com/reuters/topNews","business"),
        ("Al Jazeera","https://www.aljazeera.com/xml/rss/all.xml","world"),
        ("Bangkok Post","https://www.bangkokpost.com/rss/data/topstories.xml","thailand"),
        ("TechCrunch","https://techcrunch.com/feed/","tech"),
    ]
    articles=[]
    for name,url,cat in feeds:
        try:
            r=requests.get(url,timeout=6,headers={"User-Agent":"ARIA/5"})
            root=ET.fromstring(r.content)
            ns={"media":"http://search.yahoo.com/mrss/"}
            for item in root.iter("item"):
                title=(item.findtext("title") or "").strip()
                link=(item.findtext("link") or "").strip()
                pub=(item.findtext("pubDate") or "").strip()
                desc=(item.findtext("description") or "").strip()[:200]
                if title:
                    articles.append({"source":name,"cat":cat,"title":title,
                                     "link":link,"pub":pub,"desc":desc})
                if len(articles)>50: break
        except:
            pass
    wm_store("news",articles); return jsonify(articles)

@app.route("/api/wm/solar")
def api_wm_solar():
    """NOAA Space Weather — free public API"""
    c=wm_cached("solar",WM_CACHE_TTL["solar"])
    if c: return jsonify(c)
    try:
        # Planetary K-index (geomagnetic storm indicator)
        kp=wm_get("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json").json()
        latest_kp=kp[-1] if kp else [None,0]
        # Solar wind speed
        sw=wm_get("https://services.swpc.noaa.gov/products/solar-wind/plasma-6-hour.json").json()
        latest_sw=sw[-1] if len(sw)>1 else [None,0,0,0]
        # CME alerts
        alerts=[]
        try:
            a=wm_get("https://services.swpc.noaa.gov/products/alerts.json").json()
            alerts=[{"msg":x.get("message","")[:120],"issue":x.get("issue_datetime","")}
                    for x in (a or [])[:5]]
        except:
            pass
        out={"kp_index":float(latest_kp[1]) if latest_kp[1] else 0,
             "kp_time":latest_kp[0],"solar_wind_speed":latest_sw[2] if len(latest_sw)>2 else 0,
             "density":latest_sw[1] if len(latest_sw)>1 else 0,"alerts":alerts,
             "storm_level":"G"+str(min(5,max(0,int((float(latest_kp[1])-5)/0.67)+1))) if float(latest_kp[1] or 0)>=5 else "None"}
        wm_store("solar",out); return jsonify(out)
    except Exception as e:
        return jsonify({"error":str(e),"kp_index":0,"solar_wind_speed":0,"storm_level":"None","alerts":[]})

@app.route("/api/wm/airquality")
def api_wm_airquality():
    """OpenAQ — free, no API key needed"""
    c=wm_cached("airq",WM_CACHE_TTL["airq"])
    if c: return jsonify(c)
    cities=[("Bangkok","th"),("London","gb"),("New York","us"),("Beijing","cn"),
            ("Tokyo","jp"),("Delhi","in"),("Jakarta","id"),("Sydney","au")]
    results=[]
    for city,country in cities:
        try:
            r=wm_get(f"https://api.openaq.org/v2/latest?city={city}&country={country}&limit=5",
                     headers={"User-Agent":"ARIA/5","Accept":"application/json"})
            d=r.json()
            locs=d.get("results",[])
            if not locs: continue
            meas={m["parameter"]:m["value"] for loc in locs for m in loc.get("measurements",[])}
            pm25=meas.get("pm25",meas.get("pm2.5",None))
            aqi_level="Good" if not pm25 else ("Moderate" if pm25<35 else ("Unhealthy" if pm25<75 else "Hazardous"))
            results.append({"city":city,"country":country.upper(),"pm25":pm25,
                            "pm10":meas.get("pm10"),
                            "aqi_level":aqi_level,
                            "color":"#3fb950" if aqi_level=="Good" else "#d29922" if aqi_level=="Moderate" else "#f85149"})
        except:
            pass
    wm_store("airq",results); return jsonify(results)

@app.route("/api/wm/volcanoes")
def api_wm_volcanoes():
    """Smithsonian GVP current eruptions"""
    c=wm_cached("volc",3600)
    if c: return jsonify(c)
    # Static well-known active volcanoes with known positions
    data=[
        {"name":"Kīlauea","country":"USA","lat":19.42,"lon":-155.29,"status":"erupting","alert":"WARNING"},
        {"name":"Merapi","country":"Indonesia","lat":-7.54,"lon":110.44,"status":"active","alert":"WATCH"},
        {"name":"Sakurajima","country":"Japan","lat":31.58,"lon":130.66,"status":"erupting","alert":"LEVEL 3"},
        {"name":"Stromboli","country":"Italy","lat":38.79,"lon":15.21,"status":"erupting","alert":"YELLOW"},
        {"name":"Popocatépetl","country":"Mexico","lat":19.02,"lon":-98.63,"status":"active","alert":"YELLOW-PHASE 3"},
        {"name":"Etna","country":"Italy","lat":37.75,"lon":14.99,"status":"active","alert":"YELLOW"},
        {"name":"Fuego","country":"Guatemala","lat":14.47,"lon":-90.88,"status":"erupting","alert":"ORANGE"},
        {"name":"Erebus","country":"Antarctica","lat":-77.53,"lon":167.15,"status":"active","alert":"GREEN"},
        {"name":"Sinabung","country":"Indonesia","lat":3.17,"lon":98.39,"status":"active","alert":"WATCH"},
        {"name":"Taal","country":"Philippines","lat":14.0,"lon":121.0,"status":"unrest","alert":"YELLOW"},
    ]
    wm_store("volc",data); return jsonify(data)

@app.route("/api/wm/summary")
def api_wm_summary():
    """Fast combined endpoint for WorldMonitor dashboard"""
    try:
        fin=[]; idx=[]
        try: fin=finance_mod.get_crypto_prices(["BTC","ETH","BNB","SOL"])
        except: pass
        try: idx=finance_mod.get_indices()
        except: pass
        wx={}
        try: wx=weather_mod.get_weather("Bangkok")
        except: pass
        sys={}
        try: sys=sys_mod.get_full_status(NODE_ID,NODE_NAME,LOCAL_IP,VERSION,current_model,len(mesh_nodes))
        except: pass
        return jsonify({"crypto":fin,"indices":idx[:4],"weather":wx,
                        "node":NODE_ID,"ts":time.time()})
    except Exception as e:
        return jsonify({"error":str(e)})


# ═══════════════════════════════════════════════════════════════════════════
# ─── API: WorldLayers (all 25 layers) ─────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/layers/earthquakes")
def layer_earthquakes():
    mn = float(request.args.get("min","2.5"))
    period = request.args.get("period","week")
    return jsonify(wl_mod.earthquakes(mn, period))

@app.route("/api/layers/fires")
def layer_fires():
    return jsonify(wl_mod.fires())

@app.route("/api/layers/aviation")
def layer_aviation():
    return jsonify(wl_mod.aviation())

@app.route("/api/layers/ships")
def layer_ships():
    return jsonify(wl_mod.ships())

@app.route("/api/layers/natural_events")
def layer_natural_events():
    return jsonify(wl_mod.natural_events())

@app.route("/api/layers/conflicts")
def layer_conflicts():
    return jsonify(wl_mod.armed_conflicts())

@app.route("/api/layers/protests")
def layer_protests():
    return jsonify(wl_mod.protests())

@app.route("/api/layers/weather_alerts")
def layer_weather_alerts():
    return jsonify(wl_mod.weather_alerts())

@app.route("/api/layers/solar")
def layer_solar():
    return jsonify(wl_mod.solar_weather())

@app.route("/api/layers/airquality")
def layer_airquality():
    return jsonify(wl_mod.air_quality())

@app.route("/api/layers/cables")
def layer_cables():
    return jsonify(wl_mod.submarine_cables())

@app.route("/api/layers/landing_points")
def layer_landing_points():
    return jsonify(wl_mod.landing_points())

@app.route("/api/layers/military_bases")
def layer_military_bases():
    return jsonify(wl_mod.military_bases())

@app.route("/api/layers/nuclear_sites")
def layer_nuclear():
    return jsonify(wl_mod.nuclear_sites())

@app.route("/api/layers/spaceports")
def layer_spaceports():
    return jsonify(wl_mod.spaceports())

@app.route("/api/layers/waterways")
def layer_waterways():
    return jsonify(wl_mod.strategic_waterways())

@app.route("/api/layers/internet_disruptions")
def layer_inet_disruptions():
    return jsonify(wl_mod.internet_disruptions())

@app.route("/api/layers/gps_jamming")
def layer_gps_jamming():
    return jsonify(wl_mod.gps_jamming())

@app.route("/api/layers/economic_centers")
def layer_economic_centers():
    return jsonify(wl_mod.economic_centers())

@app.route("/api/layers/critical_minerals")
def layer_minerals():
    return jsonify(wl_mod.critical_minerals())

@app.route("/api/layers/volcanoes")
def layer_volcanoes():
    return jsonify(wl_mod.volcanoes())

@app.route("/api/layers/iss")
def layer_iss():
    return jsonify(wl_mod.iss_position())

@app.route("/api/layers/news")
def layer_news():
    return jsonify(wl_mod.global_news())

@app.route("/api/layers/climate")
def layer_climate():
    return jsonify(wl_mod.climate_anomalies())

@app.route("/api/layers/conflict_zones")
def layer_conflict_zones():
    return jsonify(wl_mod.conflict_zones())

@app.route("/api/layers/all_static")
def layer_all_static():
    """Returns all static layers in one request"""
    return jsonify({
        "military_bases":   wl_mod.military_bases(),
        "nuclear_sites":    wl_mod.nuclear_sites(),
        "spaceports":       wl_mod.spaceports(),
        "waterways":        wl_mod.strategic_waterways(),
        "economic_centers": wl_mod.economic_centers(),
        "critical_minerals":wl_mod.critical_minerals(),
        "conflict_zones":   wl_mod.conflict_zones(),
        "gps_jamming":      wl_mod.gps_jamming(),
        "climate":          wl_mod.climate_anomalies(),
        "ts": time.time(),
    })


# ═══════════════════════════════════════════════════════════════════════════
# ─── WorldMonitor Extended Layers ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/wm/fires")
def api_wm_fires():
    """NASA FIRMS active fires — free public API"""
    _WM_CACHE = getattr(api_wm_fires, '_cache', {})
    api_wm_fires._cache = _WM_CACHE
    if 'data' in _WM_CACHE and time.time()-_WM_CACHE.get('ts',0) < 600:
        return jsonify(_WM_CACHE['data'])
    try:
        # FIRMS public endpoint — world, last 24h, VIIRS
        # Uses MAP_KEY = FIRMS_MAP_KEY (or demo key)
        firms_key = os.environ.get("FIRMS_MAP_KEY","")
        if firms_key:
            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{firms_key}/VIIRS_SNPP_NRT/world/1"
            r = requests.get(url, timeout=15, headers={"User-Agent":"ARIA/5"})
            lines = r.text.strip().split("\n")
            fires = []
            if len(lines) > 1:
                header = lines[0].split(",")
                for line in lines[1:101]:
                    parts = line.split(",")
                    if len(parts) >= 4:
                        try:
                            fires.append({"lat":float(parts[0]),"lon":float(parts[1]),
                                         "bright":float(parts[2]) if len(parts)>2 else 0,
                                         "frp":float(parts[9]) if len(parts)>9 else 0})
                        except: pass
        else:
            # Fallback: MODIS NRT via NASA EARTHDATA open access
            r = requests.get(
                "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv",
                timeout=15, headers={"User-Agent":"ARIA/5"}
            )
            lines = r.text.strip().split("\n")[1:201]
            fires = []
            for line in lines:
                p = line.split(",")
                if len(p) >= 2:
                    try: fires.append({"lat":float(p[0]),"lon":float(p[1]),
                                       "bright":float(p[2]) if len(p)>2 else 300,
                                       "frp":float(p[8]) if len(p)>8 else 0})
                    except: pass
        _WM_CACHE['data'] = fires; _WM_CACHE['ts'] = time.time()
        return jsonify(fires)
    except Exception as e:
        return jsonify({"error":str(e),"data":[]})

@app.route("/api/wm/conflicts")
def api_wm_conflicts():
    """Armed conflict events — GDELT GKG (free, no key)"""
    _cache = getattr(api_wm_conflicts,'_c',{})
    api_wm_conflicts._c = _cache
    if 'data' in _cache and time.time()-_cache.get('ts',0)<1800:
        return jsonify(_cache['data'])
    try:
        # GDELT last events with geo
        url = "https://api.gdeltproject.org/api/v2/events/events?query=conflict%20OR%20war%20OR%20military%20OR%20attack&mode=artlist&maxrecords=50&format=json&timespan=3days"
        r = requests.get(url,timeout=10,headers={"User-Agent":"ARIA/5"})
        d = r.json()
        events = []
        for art in (d.get("articles") or [])[:50]:
            if art.get("geolat") and art.get("geolong"):
                events.append({"lat":float(art["geolat"]),"lon":float(art["geolong"]),
                               "title":(art.get("title") or "")[:80],
                               "url": art.get("url",""),
                               "date": art.get("seendate",""),
                               "country": art.get("geofullname","")})
        _cache['data'] = events; _cache['ts'] = time.time()
        return jsonify(events)
    except Exception as e:
        # Return known active conflict zones as fallback
        return jsonify([
            {"lat":15.6,"lon":32.5,"title":"Sudan Armed Conflict","country":"Sudan","type":"conflict"},
            {"lat":48.0,"lon":37.8,"title":"Ukraine War Zone","country":"Ukraine","type":"conflict"},
            {"lat":31.5,"lon":35.0,"title":"Gaza Conflict","country":"Palestine","type":"conflict"},
            {"lat":16.8,"lon":43.7,"title":"Yemen Civil War","country":"Yemen","type":"conflict"},
            {"lat":12.6,"lon":44.1,"title":"Tigray/Ethiopia Conflict","country":"Ethiopia","type":"conflict"},
            {"lat":3.8,"lon":11.5,"title":"Sahel Instability","country":"Cameroon","type":"conflict"},
            {"lat":14.5,"lon":75.8,"title":"Myanmar Civil War","country":"Myanmar","type":"conflict"},
            {"lat":33.9,"lon":66.0,"title":"Afghanistan Unrest","country":"Afghanistan","type":"conflict"},
            {"lat":36.2,"lon":37.1,"title":"NW Syria Conflict","country":"Syria","type":"conflict"},
            {"lat":5.8,"lon":1.0,"title":"Sahel Region","country":"West Africa","type":"conflict"},
        ])

@app.route("/api/wm/cables")
def api_wm_cables():
    """Submarine cables — TeleGeography full dataset (all cables in world)"""
    _cache = getattr(api_wm_cables,'_c',{})
    api_wm_cables._c = _cache
    if 'data' in _cache and time.time()-_cache.get('ts',0)<86400:
        return jsonify(_cache['data'])
    try:
        r = requests.get(
            "https://raw.githubusercontent.com/telegeography/www.submarinecablemap.com/master/public/api/v3/cable/cable-geo.json",
            timeout=20, headers={"User-Agent":"ARIA/5"}
        )
        d = r.json()
        _cache['data'] = d; _cache['ts'] = time.time()
        return jsonify(d)
    except Exception as e:
        return jsonify({"error":str(e)})

@app.route("/api/wm/landing-points")
def api_wm_landing():
    """Cable landing points — TeleGeography"""
    _cache = getattr(api_wm_landing,'_c',{})
    api_wm_landing._c = _cache
    if 'data' in _cache and time.time()-_cache.get('ts',0)<86400:
        return jsonify(_cache['data'])
    try:
        r = requests.get(
            "https://raw.githubusercontent.com/telegeography/www.submarinecablemap.com/master/public/api/v3/landing-point/landing-point-geo.json",
            timeout=15, headers={"User-Agent":"ARIA/5"}
        )
        d = r.json()
        _cache['data'] = d; _cache['ts'] = time.time()
        return jsonify(d)
    except Exception as e:
        return jsonify({"error":str(e)})

@app.route("/api/wm/weather-radar")
def api_wm_weather_radar():
    """RainViewer API — free global weather radar tiles"""
    try:
        r = requests.get("https://api.rainviewer.com/public/weather-maps.json",timeout=8,
                         headers={"User-Agent":"ARIA/5"})
        d = r.json()
        # Return radar frames info
        return jsonify({
            "host": d.get("host","https://tilecache.rainviewer.com"),
            "radar":   [{"time":f["time"],"path":f["path"]} for f in (d.get("radar",{}).get("past",[]) or [])[-3:]],
            "satellite":[{"time":f["time"],"path":f["path"]} for f in (d.get("satellite",{}).get("infrared",[]) or [])[-2:]],
        })
    except Exception as e:
        return jsonify({"error":str(e)})



@app.route("/api/wm/nuclear-sites")
def api_wm_nuclear():
    """Nuclear facilities worldwide — IAEA + NTI public data"""
    return jsonify([
        # Power Plants
        {"name":"Zaporizhzhia NPP","lat":47.50,"lon":34.58,"country":"Ukraine","type":"power","status":"occupied","flag":"⚠"},
        {"name":"Chernobyl","lat":51.39,"lon":30.10,"country":"Ukraine","type":"accident_site","status":"monitoring","flag":"☢"},
        {"name":"Bushehr NPP","lat":28.83,"lon":50.89,"country":"Iran","type":"power","status":"operational","flag":"⚛"},
        {"name":"Natanz","lat":33.72,"lon":51.73,"country":"Iran","type":"enrichment","status":"active","flag":"🔴"},
        {"name":"Fordow","lat":34.88,"lon":49.22,"country":"Iran","type":"enrichment","status":"active","flag":"🔴"},
        {"name":"Yongbyon","lat":39.78,"lon":125.75,"country":"North Korea","type":"research","status":"active","flag":"🔴"},
        {"name":"Dimona","lat":31.00,"lon":35.15,"country":"Israel","type":"research","status":"classified","flag":"🔵"},
        {"name":"Sellafield","lat":54.42,"lon":-3.50,"country":"UK","type":"reprocessing","status":"decommission","flag":"⚛"},
        {"name":"Hanford Site","lat":46.55,"lon":-119.53,"country":"USA","type":"cleanup","status":"remediation","flag":"⚛"},
        # Weapons States
        {"name":"Los Alamos NL","lat":35.88,"lon":-106.30,"country":"USA","type":"weapons_lab","status":"classified","flag":"🔵"},
        {"name":"Sandia NL","lat":34.75,"lon":-106.50,"country":"USA","type":"weapons_lab","status":"classified","flag":"🔵"},
        {"name":"Seversk","lat":56.60,"lon":84.87,"country":"Russia","type":"weapons","status":"classified","flag":"🔵"},
        {"name":"Novaya Zemlya","lat":73.50,"lon":54.80,"country":"Russia","type":"test_site","status":"closed","flag":"⚛"},
        {"name":"Lop Nor","lat":40.50,"lon":89.50,"country":"China","type":"test_site","status":"monitoring","flag":"⚛"},
        {"name":"Kahuta","lat":33.61,"lon":73.38,"country":"Pakistan","type":"weapons","status":"active","flag":"🔵"},
        {"name":"Trombay","lat":19.02,"lon":72.92,"country":"India","type":"research","status":"active","flag":"⚛"},
        {"name":"Rokkasho","lat":40.96,"lon":141.37,"country":"Japan","type":"reprocessing","status":"construction","flag":"⚛"},
    ])




@app.route("/api/wm/internet-disruptions")
def api_wm_internet():
    """Internet disruptions — Cloudflare Radar (free, no key needed)"""
    _cache = getattr(api_wm_internet,'_c',{})
    api_wm_internet._c = _cache
    if 'data' in _cache and time.time()-_cache.get('ts',0)<300:
        return jsonify(_cache['data'])
    try:
        r = requests.get(
            "https://radar.cloudflare.com/api/v0/attacks/layer7/top/industry",
            timeout=8, headers={"User-Agent":"ARIA/5"}
        )
        # Try more specific endpoint
        r2 = requests.get(
            "https://radar.cloudflare.com/api/v0/reports/outages",
            timeout=8, headers={"User-Agent":"ARIA/5"}
        )
        outages = []
        try:
            d2 = r2.json()
            for o in (d2.get("result",{}).get("outages") or [])[:20]:
                outages.append({"country":o.get("ccAlpha2",""),"severity":o.get("severity",""),
                                "start":o.get("startDate",""),"end":o.get("endDate","")})
        except: pass
        result = {"outages": outages, "ts": time.time()}
        _cache['data'] = result; _cache['ts'] = time.time()
        return jsonify(result)
    except Exception as e:
        # Static known recent disruptions
        return jsonify({"outages":[
            {"country":"MM","region":"Myanmar","severity":"high","cause":"government_shutdown"},
            {"country":"SD","region":"Sudan","severity":"high","cause":"conflict"},
            {"country":"IR","region":"Iran","severity":"medium","cause":"government_filter"},
            {"country":"RU","region":"Russia","severity":"medium","cause":"government_restriction"},
        ],"ts":time.time(),"error":str(e)})




@app.route("/api/wm/ai-datacenters")
def api_wm_aidc():
    return jsonify([
        {"name":"Google The Dalles","lat":45.6,"lon":-121.2,"country":"USA","company":"Google","capacity_mw":500},
        {"name":"Microsoft Quincy","lat":47.2,"lon":-119.8,"country":"USA","company":"Microsoft","capacity_mw":200},
        {"name":"Amazon US-East (Ashburn)","lat":39.0,"lon":-77.5,"country":"USA","company":"AWS","capacity_mw":800},
        {"name":"Meta Lulea","lat":65.6,"lon":22.1,"country":"Sweden","company":"Meta","capacity_mw":120},
        {"name":"Google Singapore","lat":1.3,"lon":103.8,"country":"Singapore","company":"Google","capacity_mw":60},
        {"name":"Microsoft Dublin","lat":53.4,"lon":-6.2,"country":"Ireland","company":"Microsoft","capacity_mw":160},
        {"name":"AWS Tokyo","lat":35.7,"lon":139.7,"country":"Japan","company":"AWS","capacity_mw":100},
        {"name":"Alibaba Zhangjiakou","lat":40.8,"lon":114.9,"country":"China","company":"Alibaba","capacity_mw":200},
        {"name":"Baidu AI Cloud Beijing","lat":40.0,"lon":116.4,"country":"China","company":"Baidu","capacity_mw":150},
        {"name":"Google Belgium","lat":50.4,"lon":3.8,"country":"Belgium","company":"Google","capacity_mw":350},
        {"name":"OpenAI/Azure Iowa","lat":41.9,"lon":-93.6,"country":"USA","company":"Microsoft/OpenAI","capacity_mw":300},
        {"name":"xAI Memphis","lat":35.1,"lon":-90.0,"country":"USA","company":"xAI","capacity_mw":200},
        {"name":"NVIDIA Israel","lat":32.1,"lon":34.9,"country":"Israel","company":"NVIDIA","capacity_mw":50},
        {"name":"Tencent Guizhou","lat":26.6,"lon":106.7,"country":"China","company":"Tencent","capacity_mw":120},
    ])

@app.route("/api/wm/gps-jamming")
def api_wm_gps():
    """GPS jamming hotspots — based on known incidents"""
    return jsonify([
        {"lat":32.1,"lon":34.9,"region":"Tel Aviv / Israel","severity":"extreme","source":"confirmed","active":True,"note":"IDF electronic warfare"},
        {"lat":33.5,"lon":36.3,"region":"Damascus / Syria","severity":"high","source":"confirmed","active":True},
        {"lat":55.8,"lon":37.6,"region":"Moscow","severity":"medium","source":"reported","active":True,"note":"Kremlin protection"},
        {"lat":60.0,"lon":24.5,"region":"Finland/Baltic","severity":"high","source":"confirmed","active":True,"note":"Russia spoofing"},
        {"lat":56.9,"lon":24.1,"region":"Latvia/Riga","severity":"high","source":"confirmed","active":True},
        {"lat":36.2,"lon":37.1,"region":"NW Syria","severity":"high","source":"confirmed","active":True},
        {"lat":39.0,"lon":45.0,"region":"Iran/Azerbaijan border","severity":"medium","source":"reported","active":False},
        {"lat":41.0,"lon":28.9,"region":"Istanbul","severity":"medium","source":"reported","active":True,"note":"Maritime spoofing"},
        {"lat":29.0,"lon":34.5,"region":"Red Sea (Houthi)","severity":"high","source":"confirmed","active":True},
        {"lat":22.5,"lon":114.0,"region":"South China Sea","severity":"medium","source":"reported","active":True},
        {"lat":40.7,"lon":44.5,"region":"Armenia/Azerbaijan","severity":"medium","source":"confirmed","active":False},
        {"lat":69.0,"lon":28.0,"region":"Norwegian Lapland","severity":"medium","source":"confirmed","active":True},
    ])


@app.route("/wm/security")
def wm_security(): return render_template("wm_security.html", node_id=NODE_ID, version=VERSION)

@app.route("/wm/infrastructure")
def wm_infra(): return render_template("wm_infrastructure.html", node_id=NODE_ID, version=VERSION)

@app.route("/wm/economy")
def wm_economy(): return render_template("wm_economy.html", node_id=NODE_ID, version=VERSION)

@app.route("/wm/natural")
def wm_natural(): return render_template("wm_natural.html", node_id=NODE_ID, version=VERSION)


# ═══════════════════════════════════════════════════════════════════════════
# ─── THREAT MONITOR — War & Economic Surveillance ─────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
import threading, smtplib
from email.mime.text import MIMEText

_THREAT_CFG = {
    "war_threshold":      float(os.environ.get("WAR_THRESHOLD",    "7.0")),  # earthquake M → escalate
    "econ_crash_pct":     float(os.environ.get("ECON_CRASH_PCT",  "-5.0")),  # crypto/stock drop %
    "kp_storm_threshold": float(os.environ.get("KP_THRESHOLD",    "5.0")),   # geomagnetic K-index
    "fire_count_alert":   int(os.environ.get("FIRE_ALERT_COUNT",  "500")),   # NASA fire count
    "alert_channel":      os.environ.get("THREAT_ALERT_CHANNEL",  "ntfy"),   # ntfy|telegram|all
    "monitor_interval":   int(os.environ.get("MONITOR_INTERVAL",  "300")),   # seconds (5 min)
    "enabled":            os.environ.get("THREAT_MONITOR", "1") == "1",
}

_THREAT_STATE = {
    "last_quake_alert": 0,
    "last_econ_alert":  0,
    "last_solar_alert": 0,
    "last_fire_alert":  0,
    "last_conflict_alert": 0,
    "active_threats":   [],
    "threat_level":     "GREEN",  # GREEN / YELLOW / ORANGE / RED
    "last_scan":        0,
}
_THREAT_LOCK = threading.Lock()

def _threat_send(title, message, priority="high"):
    try:
        import modules.alerts as al
        return al.send(title, message, _THREAT_CFG["alert_channel"], priority, NODE_ID)
    except Exception as e:
        log.error(f"Threat alert send failed: {e}")
        return {"ok": False, "error": str(e)}

def _calc_threat_level(threats):
    if any(t["severity"] == "CRITICAL" for t in threats): return "RED"
    if any(t["severity"] == "HIGH"     for t in threats): return "ORANGE"
    if any(t["severity"] == "MEDIUM"   for t in threats): return "YELLOW"
    return "GREEN"

def _monitor_cycle():
    now = time.time()
    new_threats = []
    cooldown = 3600  # 1h between same-type alerts

    # 1. EARTHQUAKE — Major seismic event
    try:
        r = requests.get(
            "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_hour.geojson",
            timeout=8)
        feats = r.json().get("features", [])
        for f in feats:
            p = f["properties"]
            mag = p.get("mag", 0) or 0
            if mag >= _THREAT_CFG["war_threshold"]:
                threat = {
                    "type": "SEISMIC", "severity": "CRITICAL" if mag>=8 else "HIGH",
                    "title": f"Major Earthquake M{mag}",
                    "detail": p.get("place", "Unknown location"),
                    "ts": now
                }
                new_threats.append(threat)
                if now - _THREAT_STATE["last_quake_alert"] > cooldown:
                    _threat_send(f"⚠ Earthquake M{mag}", p.get("place",""), "urgent")
                    _THREAT_STATE["last_quake_alert"] = now
    except: pass

    # 2. GEOMAGNETIC STORM — Space weather
    try:
        r = requests.get(
            "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
            timeout=8)
        data = r.json()
        kp = float(data[-1][1]) if data else 0
        if kp >= _THREAT_CFG["kp_storm_threshold"]:
            sev = "CRITICAL" if kp>=8 else "HIGH" if kp>=6 else "MEDIUM"
            new_threats.append({
                "type": "SOLAR_STORM", "severity": sev,
                "title": f"Geomagnetic Storm K{kp:.1f}",
                "detail": f"G{min(5,int((kp-5)/0.67+1))} storm — GPS/comms disruption possible",
                "ts": now
            })
            if kp >= 6 and now - _THREAT_STATE["last_solar_alert"] > cooldown:
                _threat_send(f"☀ Geomagnetic Storm K{kp:.1f}",
                             f"G-level storm — may disrupt communications, GPS, power grids", "high")
                _THREAT_STATE["last_solar_alert"] = now
    except: pass

    # 3. ECONOMIC CRASH — Crypto/market drop
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true",
            timeout=8)
        prices = r.json()
        for coin, data in prices.items():
            chg = data.get("usd_24h_change", 0) or 0
            if chg <= _THREAT_CFG["econ_crash_pct"]:
                sev = "CRITICAL" if chg<=-15 else "HIGH" if chg<=-10 else "MEDIUM"
                new_threats.append({
                    "type": "ECON_CRASH", "severity": sev,
                    "title": f"Crypto Crash: {coin.upper()} {chg:.1f}%",
                    "detail": f"${data.get('usd',0):,.0f} USD — {chg:.2f}% 24h change",
                    "ts": now
                })
                if now - _THREAT_STATE["last_econ_alert"] > 3600:
                    _threat_send(f"📉 Market Crash: {coin.upper()}",
                                 f"{chg:.1f}% drop in 24h — ${data.get('usd',0):,.0f}", "high")
                    _THREAT_STATE["last_econ_alert"] = now
    except: pass

    # 4. INTERNET DISRUPTION — Major outage
    try:
        r = requests.get(
            "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/events?limit=10",
            timeout=8)
        events = r.json().get("data", {}).get("events", [])
        major = [e for e in events if e.get("score", 0) > 0.5]
        if major:
            new_threats.append({
                "type": "INTERNET_DISRUPTION", "severity": "HIGH",
                "title": f"Internet Disruption: {major[0].get('entityName','')}",
                "detail": f"{len(major)} regions affected",
                "ts": now
            })
    except: pass

    # 5. WEATHER ALERT — Extreme NOAA
    try:
        r = requests.get(
            "https://api.weather.gov/alerts/active?status=actual&severity=Extreme&limit=10",
            headers={"User-Agent": "ARIA-ThreatMonitor/5", "Accept": "application/geo+json"},
            timeout=8)
        feats = r.json().get("features", [])
        if feats:
            p = feats[0]["properties"]
            new_threats.append({
                "type": "EXTREME_WEATHER", "severity": "HIGH",
                "title": f"Extreme Weather: {p.get('event','')}",
                "detail": p.get("areaDesc", "")[:80],
                "ts": now
            })
    except: pass

    with _THREAT_LOCK:
        _THREAT_STATE["active_threats"] = new_threats
        _THREAT_STATE["threat_level"]   = _calc_threat_level(new_threats)
        _THREAT_STATE["last_scan"]       = now
        log.info(f"Threat scan: {len(new_threats)} threats | Level: {_THREAT_STATE['threat_level']}")

def _start_threat_monitor():
    if not _THREAT_CFG["enabled"]:
        log.info("Threat monitor disabled (set THREAT_MONITOR=1 to enable)")
        return
    def loop():
        time.sleep(15)  # wait for startup
        while True:
            try:
                _monitor_cycle()
            except Exception as e:
                log.error(f"Threat monitor error: {e}")
            time.sleep(_THREAT_CFG["monitor_interval"])
    t = threading.Thread(target=loop, daemon=True, name="threat-monitor")
    t.start()
    log.info(f"🔴 Threat Monitor started (interval: {_THREAT_CFG['monitor_interval']}s)")

_start_threat_monitor()

# ── Threat Monitor API ─────────────────────────────────────────────────────
@app.route("/api/threat/status")
def api_threat_status():
    with _THREAT_LOCK:
        return jsonify({
            "level":    _THREAT_STATE["threat_level"],
            "threats":  _THREAT_STATE["active_threats"],
            "count":    len(_THREAT_STATE["active_threats"]),
            "last_scan":_THREAT_STATE["last_scan"],
            "config":   _THREAT_CFG,
            "node":     NODE_ID,
            "ts":       time.time(),
        })

@app.route("/api/threat/config", methods=["POST"])
def api_threat_config():
    body = request.json or {}
    for k in ["war_threshold","econ_crash_pct","kp_storm_threshold","monitor_interval"]:
        if k in body:
            _THREAT_CFG[k] = float(body[k])
    if "alert_channel" in body:
        _THREAT_CFG["alert_channel"] = body["alert_channel"]
    if "enabled" in body:
        _THREAT_CFG["enabled"] = bool(body["enabled"])
    return jsonify({"ok": True, "config": _THREAT_CFG})

@app.route("/api/threat/scan", methods=["POST"])
def api_threat_scan():
    """Manual threat scan trigger"""
    threading.Thread(target=_monitor_cycle, daemon=True).start()
    return jsonify({"ok": True, "msg": "Scan started"})

@app.route("/api/threat/test", methods=["POST"])
def api_threat_test():
    """Test alert channel"""
    r = _threat_send("🔴 ARIA Threat Monitor Test", f"Node {NODE_ID} — alerts working ✓", "default")
    return jsonify(r)

@app.route("/api/threat/stream")
def api_threat_stream():
    """SSE stream — push threat updates"""
    def gen():
        while True:
            try:
                with _THREAT_LOCK:
                    data = {
                        "level":   _THREAT_STATE["threat_level"],
                        "count":   len(_THREAT_STATE["active_threats"]),
                        "threats": _THREAT_STATE["active_threats"][:5],
                        "ts":      time.time(),
                    }
                yield f"data: {json.dumps(data)}\n\n"
                time.sleep(30)
            except GeneratorExit:
                break
    return Response(gen(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache"})


# ═══════════════════════════════════════════════════════════════════════════
# ─── Memory API ───────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
from modules.memory import (save_message, save_fact, get_recent, search as mem_search,
                             get_facts, get_sessions, get_important, get_context,
                             delete_session, clear_all as mem_clear, stats as mem_stats,
                             save_summary)

@app.route("/api/memory/save", methods=["POST"])
def api_mem_save():
    b = request.json or {}
    mid = save_message(b.get("content",""), b.get("role","user"),
                       b.get("session"), b.get("type","chat"), b.get("important",False))
    return jsonify({"ok":True,"id":mid})

@app.route("/api/memory/recent")
def api_mem_recent():
    session = request.args.get("session")
    limit   = int(request.args.get("limit",20))
    return jsonify(get_recent(limit, session))

@app.route("/api/memory/search")
def api_mem_search():
    q = request.args.get("q","")
    return jsonify(mem_search(q, int(request.args.get("limit",20))))

@app.route("/api/memory/facts", methods=["GET","POST"])
def api_mem_facts():
    if request.method == "POST":
        b = request.json or {}
        save_fact(b.get("key",""), b.get("value",""), b.get("source","user"))
        return jsonify({"ok":True})
    return jsonify(get_facts(request.args.get("key")))

@app.route("/api/memory/sessions")
def api_mem_sessions():
    return jsonify(get_sessions(int(request.args.get("limit",20))))

@app.route("/api/memory/sessions/<sid>", methods=["DELETE"])
def api_mem_del_session(sid):
    delete_session(sid)
    return jsonify({"ok":True})

@app.route("/api/memory/context")
def api_mem_context():
    return jsonify({"context": get_context(request.args.get("session"),
                                           int(request.args.get("max_chars",3000)))})

@app.route("/api/memory/stats")
def api_mem_stats():
    return jsonify(mem_stats())

@app.route("/api/memory/important")
def api_mem_important():
    return jsonify(get_important(int(request.args.get("limit",30))))

@app.route("/api/memory/clear", methods=["POST"])
def api_mem_clear():
    mem_clear()
    return jsonify({"ok":True})

# ═══════════════════════════════════════════════════════════════════════════
# ─── Scheduler API ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
from modules.scheduler import (add_job, remove_job, toggle_job, run_now,
                                get_jobs, get_logs)

@app.route("/api/scheduler/jobs", methods=["GET","POST"])
def api_sched_jobs():
    if request.method == "POST":
        b = request.json or {}
        jid = add_job(b.get("name","job"), b.get("cmd",""), 
                      int(b.get("interval_s",3600)), b.get("type","interval"),
                      bool(b.get("enabled",True)), b.get("tags",""))
        return jsonify({"ok":True,"id":jid})
    return jsonify(get_jobs())

@app.route("/api/scheduler/jobs/<jid>", methods=["DELETE","PATCH"])
def api_sched_job(jid):
    if request.method == "DELETE":
        remove_job(jid); return jsonify({"ok":True})
    b = request.json or {}
    toggle_job(jid, bool(b.get("enabled",True)))
    return jsonify({"ok":True})

@app.route("/api/scheduler/jobs/<jid>/run", methods=["POST"])
def api_sched_run(jid):
    return jsonify(run_now(jid))

@app.route("/api/scheduler/logs")
def api_sched_logs():
    return jsonify(get_logs(request.args.get("job_id"), int(request.args.get("limit",50))))

# ═══════════════════════════════════════════════════════════════════════════
# ─── PWA ──────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/manifest.json")
def pwa_manifest():
    return app.send_static_file("manifest.json")

@app.route("/sw.js")
def pwa_sw():
    resp = app.send_static_file("sw.js")
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# ─── AI AGENT API ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
from modules.agent import run_agent, run_agent_sync, TOOLS

@app.route("/api/agent/run", methods=["POST"])
def api_agent_run():
    """SSE stream of agent execution steps"""
    body  = request.json or {}
    task  = body.get("task", "")
    model = body.get("model", current_model or "qwen2.5:7b")
    steps = int(body.get("max_steps", 6))
    if not task:
        return jsonify({"error": "task required"})
    def gen():
        for event in run_agent(task, model, steps):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: {\"done\":true}\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache"})

@app.route("/api/agent/run_sync", methods=["POST"])
def api_agent_sync():
    body  = request.json or {}
    task  = body.get("task","")
    model = body.get("model", current_model or "qwen2.5:7b")
    if not task: return jsonify({"error":"task required"})
    return jsonify(run_agent_sync(task, model, int(body.get("max_steps",6))))

@app.route("/api/agent/tools")
def api_agent_tools():
    return jsonify(TOOLS)

# ─── RAG API ──────────────────────────────────────────────────────────────
from modules.rag import (index_document, ask as rag_ask, list_docs,
                          delete_doc, stats as rag_stats, search as rag_search)

@app.route("/api/rag/upload", methods=["POST"])
def api_rag_upload():
    if "file" in request.files:
        f    = request.files["file"]
        name = f.filename or "upload"
        ext  = os.path.splitext(name)[1].lower()
        text = ""
        if ext == ".pdf":
            try:
                import subprocess as sp
                raw = f.read()
                tmp = f"/tmp/rag_{int(time.time())}.pdf"
                open(tmp,"wb").write(raw)
                r = sp.run(["pdftotext",tmp,"-"], capture_output=True, text=True, timeout=30)
                text = r.stdout
                os.remove(tmp)
            except: text = ""
        else:
            text = f.read().decode("utf-8", errors="ignore")
        if not text.strip():
            return jsonify({"error":"Could not extract text from file"})
        body    = request.form
        doc_type = body.get("type", ext.lstrip(".") or "text")
    else:
        b    = request.json or {}
        text = b.get("text","")
        name = b.get("name","document")
        doc_type = b.get("type","text")
    if not text.strip(): return jsonify({"error":"No text content"})
    doc_id = index_document(text, name, doc_type=doc_type)
    s = rag_stats()
    return jsonify({"ok":True,"doc_id":doc_id,"name":name,
                    "chunks": s["chunks"], "docs": s["documents"]})

@app.route("/api/rag/ask", methods=["POST"])
def api_rag_ask():
    b     = request.json or {}
    q     = b.get("question","")
    model = b.get("model", current_model or "qwen2.5:7b")
    doc   = b.get("doc_id")
    top_k = int(b.get("top_k", 5))
    if not q: return jsonify({"error":"question required"})
    return jsonify(rag_ask(q, model, top_k, doc))

@app.route("/api/rag/ask/stream", methods=["POST"])
def api_rag_ask_stream():
    """RAG with streaming LLM output"""
    b     = request.json or {}
    q     = b.get("question","")
    model = b.get("model", current_model or "qwen2.5:7b")
    doc   = b.get("doc_id")
    if not q: return jsonify({"error":"question required"})
    # Get relevant chunks
    chunks = rag_search(q, 5, doc)
    context = "\n\n---\n\n".join(c["text"] for c in chunks[:5])
    prompt = f"""Answer using ONLY this context. Say "Not in documents" if unsure.

Context:
{context}

Question: {q}
Answer:"""
    def gen():
        sources = list({c["doc_id"] for c in chunks})
        yield f"data: {json.dumps({'type':'sources','sources':sources})}\n\n"
        try:
            with requests.post(f"{OLLAMA_URL}/api/chat",
                               json={"model":model,"stream":True,
                                     "messages":[{"role":"user","content":prompt}]},
                               stream=True, timeout=120) as r:
                for line in r.iter_lines():
                    if not line: continue
                    try:
                        d = json.loads(line)
                        c2 = d.get("message",{}).get("content","")
                        if c2: yield f"data: {json.dumps({'type':'token','content':c2})}\n\n"
                    except: pass
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','msg':str(e)})}\n\n"
        yield "data: {\"done\":true}\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache"})

@app.route("/api/rag/docs")
def api_rag_docs():
    return jsonify(list_docs())

@app.route("/api/rag/docs/<doc_id>", methods=["DELETE"])
def api_rag_del(doc_id):
    delete_doc(doc_id); return jsonify({"ok":True})

@app.route("/api/rag/search")
def api_rag_search():
    q   = request.args.get("q","")
    doc = request.args.get("doc_id")
    k   = int(request.args.get("k",5))
    return jsonify(rag_search(q, k, doc))

@app.route("/api/rag/stats")
def api_rag_stats():
    return jsonify(rag_stats())

# ─── E2E ENCRYPTED CHAT API ───────────────────────────────────────────────
from modules.crypto_chat import (create_session, get_session, list_sessions,
                                  close_session, quick_setup, generate_key,
                                  derive_key_from_passphrase, key_fingerprint)
import base64, hashlib

_ECHAT_MSGS: dict = {}   # room → list of encrypted envelopes (in-memory)
_ECHAT_LOCK = threading.Lock()

@app.route("/api/echat/setup", methods=["POST"])
def api_echat_setup():
    b    = request.json or {}
    pp   = b.get("passphrase")
    room = b.get("room", "aria-secure")
    info = quick_setup(pp)
    fp   = create_session(room, info["key"])
    return jsonify({**info, "room": room, "fingerprint": fp})

@app.route("/api/echat/join", methods=["POST"])
def api_echat_join():
    b    = request.json or {}
    key  = b.get("key","")
    room = b.get("room","aria-secure")
    if not key: return jsonify({"error":"key required"})
    fp = create_session(room, key)
    return jsonify({"ok":True,"room":room,"fingerprint":fp})

@app.route("/api/echat/send", methods=["POST"])
def api_echat_send():
    b       = request.json or {}
    room    = b.get("room","aria-secure")
    sender  = b.get("sender", NODE_NAME)
    content = b.get("content","")
    sess    = get_session(room)
    if not sess: return jsonify({"error":"Not in room — call /setup or /join first"})
    env = sess.wrap_message(sender, content)
    with _ECHAT_LOCK:
        _ECHAT_MSGS.setdefault(room,[]).append(env)
        _ECHAT_MSGS[room] = _ECHAT_MSGS[room][-200:]
    # Also broadcast via mesh
    try:
        intr = get_intranet() if HAS_INTRANET else None
        if intr:
            intr.broadcast_message(json.dumps({"type":"echat","room":room,"env":env}))
    except: pass
    return jsonify({"ok":True,"fingerprint":sess.fingerprint})

@app.route("/api/echat/messages")
def api_echat_messages():
    room  = request.args.get("room","aria-secure")
    limit = int(request.args.get("limit",50))
    sess  = get_session(room)
    if not sess:
        return jsonify({"error":"Not in room","messages":[]})
    with _ECHAT_LOCK:
        envs = _ECHAT_MSGS.get(room,[])[-limit:]
    decrypted = []
    for env in envs:
        msg = sess.unwrap_message(env)
        if msg:
            decrypted.append(msg)
        else:
            decrypted.append({"sender":"[unknown]","content":"⚠ Decryption failed",
                              "ts":0,"type":"error"})
    return jsonify(decrypted)

@app.route("/api/echat/rooms")
def api_echat_rooms():
    return jsonify(list_sessions())

@app.route("/api/echat/stream")
def api_echat_stream():
    """SSE stream for new encrypted messages"""
    room  = request.args.get("room","aria-secure")
    last  = int(request.args.get("last",0))
    def gen():
        cursor = last
        while True:
            sess = get_session(room)
            if sess:
                with _ECHAT_LOCK:
                    msgs = _ECHAT_MSGS.get(room,[])
                for env in msgs[cursor:]:
                    msg = sess.unwrap_message(env)
                    if msg:
                        yield f"data: {json.dumps(msg)}\n\n"
                        cursor += 1
            time.sleep(1)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache"})

# ─── BOT BRIDGES (Discord + LINE) ─────────────────────────────────────────
DISCORD_TOKEN   = os.environ.get("DISCORD_TOKEN","")
DISCORD_CHANNEL = os.environ.get("DISCORD_CHANNEL","")
LINE_CHANNEL    = os.environ.get("LINE_CHANNEL_SECRET","")
LINE_ACCESS     = os.environ.get("LINE_ACCESS_TOKEN","")

def _ollama_reply(message: str, model: str = None) -> str:
    """Get AI reply for bot message"""
    mdl = model or current_model or "qwen2.5:7b"
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat",
                          json={"model":mdl,"stream":False,
                                "messages":[{"role":"user","content":message}]},
                          timeout=60)
        return r.json().get("message",{}).get("content","...")[:1500]
    except Exception as e:
        return f"Error: {str(e)[:100]}"

@app.route("/api/bot/discord/webhook", methods=["POST"])
def api_bot_discord():
    """Discord bot webhook handler"""
    data = request.json or {}
    # Discord verification challenge
    if data.get("type") == 1:
        return jsonify({"type":1})
    msg_type = data.get("type", 0)
    if msg_type == 2:  # APPLICATION_COMMAND
        content = data.get("data",{}).get("options",[{}])[0].get("value","")
    elif msg_type == 0:
        return jsonify({"type":4,"data":{"content":"👋"}})
    else:
        content = data.get("content","")
    if not content: return jsonify({"error":"no content"})
    reply = _ollama_reply(content)
    # Send back via Discord interaction response
    return jsonify({"type":4,"data":{"content":f"**ARIA:** {reply}"}})

@app.route("/api/bot/discord/send", methods=["POST"])
def api_bot_discord_send():
    """Send message to Discord channel"""
    if not DISCORD_TOKEN or not DISCORD_CHANNEL:
        return jsonify({"error":"Set DISCORD_TOKEN + DISCORD_CHANNEL env vars"})
    b = request.json or {}
    msg = b.get("message","")
    if not msg: return jsonify({"error":"message required"})
    try:
        r = requests.post(
            f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL}/messages",
            headers={"Authorization":f"Bot {DISCORD_TOKEN}","Content-Type":"application/json"},
            json={"content": f"🤖 **ARIA:** {msg}"[:2000]},
            timeout=10
        )
        return jsonify({"ok": r.status_code in (200,201), "status": r.status_code})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/api/bot/line/webhook", methods=["POST"])
def api_bot_line():
    """LINE Messaging API webhook"""
    data = request.json or {}
    events = data.get("events",[])
    for evt in events:
        if evt.get("type") == "message" and evt.get("message",{}).get("type") == "text":
            user_text = evt["message"]["text"]
            reply_tok = evt.get("replyToken","")
            # Get AI reply
            reply = _ollama_reply(user_text)
            # Send reply via LINE
            if LINE_ACCESS and reply_tok:
                try:
                    requests.post(
                        "https://api.line.me/v2/bot/message/reply",
                        headers={"Authorization":f"Bearer {LINE_ACCESS}",
                                 "Content-Type":"application/json"},
                        json={"replyToken":reply_tok,
                              "messages":[{"type":"text","text":f"ARIA: {reply[:4999]}"}]},
                        timeout=10
                    )
                except: pass
    return jsonify({"status":"ok"})

@app.route("/api/bot/line/send", methods=["POST"])
def api_bot_line_send():
    """Send LINE message via LINE Notify (simpler)"""
    if not LINE_ACCESS:
        return jsonify({"error":"Set LINE_ACCESS_TOKEN env var"})
    b = request.json or {}
    msg = b.get("message","")
    if not msg: return jsonify({"error":"message required"})
    try:
        r = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization":f"Bearer {LINE_ACCESS}"},
            data={"message":f"\n🤖 ARIA: {msg}"},
            timeout=10
        )
        return jsonify({"ok": r.status_code==200})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/api/bot/status")
def api_bot_status():
    return jsonify({
        "discord": {"configured": bool(DISCORD_TOKEN and DISCORD_CHANNEL),
                    "webhook_url": f"/api/bot/discord/webhook",
                    "note": "Set DISCORD_TOKEN + DISCORD_CHANNEL env vars"},
        "line":    {"configured": bool(LINE_ACCESS),
                    "webhook_url": f"/api/bot/line/webhook",
                    "note": "Set LINE_CHANNEL_SECRET + LINE_ACCESS_TOKEN env vars"},
    })

@app.route("/vault")
def vault_page():
    return render_template("vault.html", node_id=NODE_ID, version=VERSION)

@app.route("/scanner")
def scanner_page():
    return render_template("scanner.html", node_id=NODE_ID, version=VERSION)

@app.route("/logs")
def logs_page():
    return render_template("logs.html", node_id=NODE_ID, version=VERSION)

# ═══════════════════════════════════════════════════════════════════════════
# ─── MULTI-AGENT API (Planner→Researcher→Executor→Critic) ─────────────────
# ═══════════════════════════════════════════════════════════════════════════
from modules.multiagent import run_multi_agent, AGENT_ROLES

@app.route("/api/multiagent/run", methods=["POST"])
def api_multiagent_run():
    b     = request.json or {}
    task  = b.get("task","")
    model = b.get("model", current_model or "qwen2.5:7b")
    if not task: return jsonify({"error":"task required"})
    def gen():
        for event in run_multi_agent(task, model):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: {\"done\":true}\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache"})

@app.route("/api/multiagent/roles")
def api_multiagent_roles():
    return jsonify({k: {"model":v["model"]} for k,v in AGENT_ROLES.items()})

# ═══════════════════════════════════════════════════════════════════════════
# ─── VECTOR MEMORY API (FAISS / cosine fallback) ──────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
from modules.vectormem import (add_vector, search_vectors, get_all_vectors,
                                delete_vector, rebuild_faiss, vstats)

@app.route("/api/vmem/add", methods=["POST"])
def api_vmem_add():
    b = request.json or {}
    vid = add_vector(b.get("text",""), b.get("meta",{}), b.get("source","api"))
    return jsonify({"ok":True,"id":vid})

@app.route("/api/vmem/search")
def api_vmem_search():
    q   = request.args.get("q","")
    k   = int(request.args.get("k",5))
    if not q: return jsonify({"error":"q required"})
    return jsonify(search_vectors(q, k))

@app.route("/api/vmem/stats")
def api_vmem_stats():
    return jsonify(vstats())

@app.route("/api/vmem/rebuild", methods=["POST"])
def api_vmem_rebuild():
    rebuild_faiss()
    return jsonify({"ok":True})

# ═══════════════════════════════════════════════════════════════════════════
# ─── SELF-IMPROVEMENT API ─────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
from modules.selfimprove import (save_feedback, get_feedback, analyze_errors,
                                  get_improvements, run_improvement_cycle,
                                  log_error, si_stats)

@app.route("/api/improve/feedback", methods=["POST"])
def api_feedback():
    b = request.json or {}
    fid = save_feedback(b.get("query",""), b.get("response",""),
                        int(b.get("rating",3)), b.get("comment",""),
                        b.get("session"), b.get("model", current_model))
    return jsonify({"ok":True,"id":fid})

@app.route("/api/improve/analyze", methods=["POST"])
def api_improve_analyze():
    """Trigger improvement cycle — AI analyzes past errors and suggests fixes"""
    def gen():
        result = run_improvement_cycle()
        yield f"data: {json.dumps({'type':'result', 'result': result})}\n\n"
        yield "data: {\"done\":true}\n\n"
    return Response(gen(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache"})

@app.route("/api/improve/stats")
def api_improve_stats():
    return jsonify(si_stats())

@app.route("/api/improve/improvements")
def api_improve_list():
    return jsonify(get_improvements(int(request.args.get("limit",20))))

# ═══════════════════════════════════════════════════════════════════════════
# ─── IoT DEVICE CONTROL API ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
from modules.iot import (register_device, remove_device, list_devices,
                          send_command, read_sensor, get_sensor_history,
                          iot_stats, mqtt_publish)

@app.route("/iot")
def iot_page():
    return render_template("iot.html", node_id=NODE_ID, version=VERSION)

@app.route("/api/iot/devices", methods=["GET","POST"])
def api_iot_devices():
    if request.method == "POST":
        b = request.json or {}
        did = register_device(
            b.get("name","device"), b.get("ip",""), b.get("port",80),
            b.get("type","esp32"), b.get("protocol","http"),
            b.get("topic",""), b.get("meta",{}))
        return jsonify({"ok":True,"id":did})
    return jsonify(list_devices())

@app.route("/api/iot/devices/<did>", methods=["DELETE"])
def api_iot_del(did):
    remove_device(did); return jsonify({"ok":True})

@app.route("/api/iot/command", methods=["POST"])
def api_iot_command():
    b = request.json or {}
    did = b.get("device_id","")
    cmd = b.get("command","")
    params = b.get("params",{})
    if not did or not cmd: return jsonify({"error":"device_id and command required"})
    return jsonify(send_command(did, cmd, params))

@app.route("/api/iot/sensor/<did>")
def api_iot_sensor(did):
    return jsonify(read_sensor(did, request.args.get("endpoint","/sensor")))

@app.route("/api/iot/history/<did>")
def api_iot_history(did):
    return jsonify(get_sensor_history(did, int(request.args.get("limit",50))))

@app.route("/api/iot/mqtt", methods=["POST"])
def api_iot_mqtt():
    b = request.json or {}
    ok = mqtt_publish(b.get("topic",""), b.get("payload",""), int(b.get("qos",0)))
    return jsonify({"ok":ok})

@app.route("/api/iot/stats")
def api_iot_stats():
    return jsonify(iot_stats())

@app.route("/api/iot/stream")
def api_iot_stream():
    """SSE: push sensor readings every 5s"""
    devices = request.args.get("devices","").split(",")
    def gen():
        while True:
            readings = {}
            for did in devices:
                if did:
                    r = read_sensor(did)
                    readings[did] = r
            yield f"data: {json.dumps({'readings':readings,'ts':time.time()})}\n\n"
            time.sleep(5)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering":"no","Cache-Control":"no-cache"})

# ═══════════════════════════════════════════════════════════════════════════
# ─── WHISPER STT API ──────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/voice/transcribe", methods=["POST"])
def api_voice_transcribe():
    """Transcribe audio via Whisper (via Ollama or OpenAI Whisper API)"""
    # Check if audio file uploaded
    if "audio" not in request.files and not request.json:
        return jsonify({"error":"No audio file"})
    # Try Ollama Whisper first (if model installed)
    try:
        import base64, subprocess as sp
        if "audio" in request.files:
            f = request.files["audio"]
            tmp = f"/tmp/aria_audio_{int(time.time())}.webm"
            f.save(tmp)
        else:
            # base64 encoded audio
            b64 = (request.json or {}).get("audio_b64","")
            tmp = f"/tmp/aria_audio_{int(time.time())}.webm"
            with open(tmp,"wb") as fh: fh.write(base64.b64decode(b64))
        # Try whisper.cpp or faster-whisper if installed
        for cmd in [
            ["whisper", tmp, "--model", "base", "--output_format", "txt", "--output_dir", "/tmp"],
            ["whisper-ctranslate2", tmp, "--model", "base", "--output_dir", "/tmp"],
        ]:
            try:
                r = sp.run(cmd, capture_output=True, text=True, timeout=60)
                if r.returncode == 0:
                    txt_path = tmp.replace(".webm",".txt")
                    if os.path.exists(txt_path):
                        text = open(txt_path).read().strip()
                        os.remove(tmp); os.remove(txt_path)
                        return jsonify({"ok":True,"text":text,"engine":"whisper"})
            except FileNotFoundError:
                continue
        # Fallback: return message about installing whisper
        os.remove(tmp)
        return jsonify({"ok":False,"error":"Whisper not installed. Run: pip install whisper-ctranslate2",
                        "install_cmd":"pip install whisper-ctranslate2"})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

# ═══════════════════════════════════════════════════════════════════════════
# ─── NGROK / PUBLIC EXPOSURE API ──────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
_ngrok_url = None

@app.route("/api/ngrok/start", methods=["POST"])
def api_ngrok_start():
    """Start ngrok tunnel"""
    global _ngrok_url
    b = request.json or {}
    auth_token = b.get("token", os.environ.get("NGROK_TOKEN",""))
    port = b.get("port", NODE_PORT)
    try:
        import subprocess as sp
        # Kill existing ngrok
        sp.run(["pkill","-f","ngrok"], capture_output=True)
        time.sleep(1)
        # Set auth token if provided
        if auth_token:
            sp.run(["ngrok","config","add-authtoken", auth_token], capture_output=True)
        # Start ngrok in background
        proc = sp.Popen(["ngrok","http",str(port),"--log=stdout"],
                        stdout=sp.PIPE, stderr=sp.PIPE)
        time.sleep(3)
        # Get tunnel URL via ngrok API
        r = requests.get("http://localhost:4040/api/tunnels", timeout=5)
        tunnels = r.json().get("tunnels",[])
        if tunnels:
            _ngrok_url = tunnels[0].get("public_url","")
            return jsonify({"ok":True,"url":_ngrok_url,
                            "note":"Share this URL to access ARIA from anywhere"})
        return jsonify({"ok":False,"error":"ngrok started but no tunnel found",
                        "install":"Download ngrok from https://ngrok.com/download"})
    except FileNotFoundError:
        return jsonify({"ok":False,"error":"ngrok not installed",
                        "install":"Download: https://ngrok.com/download",
                        "alternative":"Use Cloudflare Tunnel: cloudflared tunnel --url http://localhost:5000"})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/api/ngrok/status")
def api_ngrok_status():
    global _ngrok_url
    if not _ngrok_url:
        # Try to get from running ngrok
        try:
            r = requests.get("http://localhost:4040/api/tunnels",timeout=2)
            tunnels = r.json().get("tunnels",[])
            if tunnels: _ngrok_url = tunnels[0].get("public_url","")
        except: pass
    return jsonify({"active": bool(_ngrok_url), "url": _ngrok_url or ""})

@app.route("/api/ngrok/stop", methods=["POST"])
def api_ngrok_stop():
    global _ngrok_url
    import subprocess as sp
    sp.run(["pkill","-f","ngrok"], capture_output=True)
    _ngrok_url = None
    return jsonify({"ok":True})

# ═══════════════════════════════════════════════════════════════════════════
# ─── PERSONALIZATION ENGINE ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
_USER_PREFS: dict = {}  # in-memory + persisted to memory.py facts

def _load_prefs():
    from modules.memory import get_facts
    for f in get_facts("pref_"):
        _USER_PREFS[f["key"][5:]] = f["value"]

def _save_pref(key: str, value: str):
    _USER_PREFS[key] = value
    from modules.memory import save_fact
    save_fact(f"pref_{key}", value, "personalization")

@app.route("/api/persona", methods=["GET","POST"])
def api_persona():
    if request.method == "POST":
        b = request.json or {}
        for k,v in b.items():
            _save_pref(k, str(v))
        return jsonify({"ok":True,"saved":len(b)})
    return jsonify(_USER_PREFS)

@app.route("/api/persona/learn", methods=["POST"])
def api_persona_learn():
    """Automatically learn preferences from conversation patterns"""
    b = request.json or {}
    query = b.get("query","")
    response = b.get("response","")
    rating = int(b.get("rating",3))
    # Simple pattern matching for preferences
    prefs_detected = {}
    q_lower = query.lower()
    # Language preference
    thai_chars = sum(1 for c in query if "\u0e00" <= c <= "\u0e7f")
    if thai_chars > 5:
        prefs_detected["language"] = "th"
    elif len(query) > 10:
        prefs_detected["language"] = "en"
    # Formality
    if any(w in q_lower for w in ["please","could you","would you"]):
        prefs_detected["formality"] = "formal"
    # Topics of interest from high-rated responses
    if rating >= 4:
        for topic in ["crypto","weather","code","news","security","iot"]:
            if topic in q_lower:
                count = int(_USER_PREFS.get(f"interest_{topic}",0)) + 1
                prefs_detected[f"interest_{topic}"] = str(count)
    for k,v in prefs_detected.items():
        _save_pref(k,v)
    return jsonify({"ok":True,"learned":prefs_detected})

# Enhanced /ask endpoint with all features
@app.route("/ask")
def api_ask():
    """Unified ask endpoint — uses personalization + memory + vector search"""
    q      = request.args.get("q", request.args.get("query",""))
    model  = request.args.get("model", current_model or "qwen2.5:7b")
    use_mem = request.args.get("memory","1") == "1"
    if not q: return jsonify({"error":"q parameter required"})
    # Build context from vector memory
    context_parts = []
    if use_mem:
        try:
            vresults = search_vectors(q, 3)
            if vresults:
                context_parts.append("Relevant context:\n" + "\n".join(
                    f"- {r.get('text','')[:200]}" for r in vresults))
        except: pass
    # Get user preferences for personalization
    lang = _USER_PREFS.get("language","en")
    formality = _USER_PREFS.get("formality","casual")
    # Build system prompt
    system = (f"You are ARIA, an intelligent assistant. "
              f"Language: {lang}. Style: {formality}. "
              f"Be concise and helpful.")
    if context_parts:
        system += "\n\n" + "\n".join(context_parts)
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat",
                         json={"model":model,"stream":False,
                               "messages":[{"role":"system","content":system},
                                           {"role":"user","content":q}]},
                         timeout=60)
        answer = r.json().get("message",{}).get("content","").strip()
        # Save to vector memory
        if use_mem:
            threading.Thread(target=add_vector, args=(f"Q:{q} A:{answer}", {"type":"qa"}, "ask"),
                            daemon=True).start()
        # Auto-learn from interaction
        threading.Thread(target=api_persona_learn.__wrapped__ if hasattr(api_persona_learn,"__wrapped__") else lambda:None,
                        daemon=True).start()
        return jsonify({"answer":answer,"model":model,"ts":time.time()})
    except Exception as e:
        return jsonify({"error":str(e)})

@app.route("/world")
def api_world():
    """Unified world status endpoint"""
    world = {}
    try:
        from modules.weather import get_weather
        world["weather"] = get_weather(os.environ.get("BRIEF_CITY","Bangkok"))
    except: world["weather"] = {}
    try:
        from modules.finance import get_crypto_prices
        world["crypto"] = get_crypto_prices(["BTC","ETH"])
    except: world["crypto"] = []
    try:
        world["threat"] = {
            "level": _THREAT_STATE.get("threat_level","UNKNOWN"),
            "count": len(_THREAT_STATE.get("active_threats",[]))
        }
    except: world["threat"] = {}
    world["node"] = {"id":NODE_ID,"name":NODE_NAME,"ip":LOCAL_IP,"ts":time.time()}
    return jsonify(world)

# ─── Jupyter Notebook export ──────────────────────────────────────────────
@app.route("/api/notebook/export")
def api_notebook_export():
    """Generate a Jupyter notebook that runs ARIA server"""
    nb = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name":"python3","display_name":"Python 3"}},
        "cells": [
            {"cell_type":"markdown","metadata":{},"source":["# ARIA AGI v5 — Jupyter Server\n","Run each cell in order to start your AI assistant."]},
            {"cell_type":"code","metadata":{},"execution_count":None,"outputs":[],
             "source":["# Install dependencies\n","!pip install flask flask-cors flask-socketio psutil requests cryptography paho-mqtt -q"]},
            {"cell_type":"code","metadata":{},"execution_count":None,"outputs":[],
             "source":["import threading, subprocess, time\n",
                       "# Start ARIA server in background thread\n",
                       "def run_server():\n",
                       "    subprocess.run(['python3', 'server.py'])\n\n",
                       "t = threading.Thread(target=run_server, daemon=True)\n",
                       "t.start()\n",
                       "time.sleep(3)\n",
                       "print('ARIA server started on http://localhost:5000')"]},
            {"cell_type":"code","metadata":{},"execution_count":None,"outputs":[],
             "source":["# Optional: expose publicly with ngrok\n",
                       "# !pip install pyngrok -q\n",
                       "# from pyngrok import ngrok\n",
                       "# public_url = ngrok.connect(5000)\n",
                       "# print('Public URL:', public_url)"]},
            {"cell_type":"code","metadata":{},"execution_count":None,"outputs":[],
             "source":["# Test the API\n",
                       "import requests\n",
                       "r = requests.get('http://localhost:5000/ask?q=Hello+ARIA')\n",
                       "print(r.json())"]},
        ]
    }
    import io
    buf = io.BytesIO(json.dumps(nb, indent=2).encode())
    return Response(buf.getvalue(), mimetype="application/json",
                    headers={"Content-Disposition":"attachment;filename=ARIA_v5.ipynb"})
# ─── Run ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port  = NODE_PORT
    debug = os.environ.get("DEBUG","0") == "1"
    _load_prefs()  # load user preferences on startup
    log.info(f"🤖 ARIA-AGI v{VERSION} starting on port {port}")
    log.info(f"📡 Node ID: {NODE_ID} | IP: {LOCAL_IP}")
    log.info(f"🌐 Mesh Port: {MESH_PORT}")
    if HAS_SOCKETIO:
        socketio.run(app, host="0.0.0.0", port=port, debug=debug, allow_unsafe_werkzeug=True)
    else:
        app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
