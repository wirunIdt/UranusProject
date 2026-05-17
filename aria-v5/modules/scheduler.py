"""modules/scheduler.py — Task Scheduler with persistent jobs"""
import os, json, time, threading, subprocess, sqlite3, uuid, logging
from datetime import datetime

log = logging.getLogger("ARIA.Scheduler")

DB_PATH = os.environ.get("SCHEDULER_DB", "aria_scheduler.db")
_LOCK   = threading.Lock()
_JOBS   = {}   # id → thread/timer
_RUNNING = True

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'interval',
    cmd         TEXT NOT NULL,
    interval_s  INTEGER DEFAULT 3600,
    cron        TEXT,
    next_run    REAL,
    last_run    REAL,
    last_result TEXT,
    enabled     INTEGER DEFAULT 1,
    runs        INTEGER DEFAULT 0,
    created     REAL NOT NULL,
    tags        TEXT
);
CREATE TABLE IF NOT EXISTS job_logs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id   TEXT NOT NULL,
    ts       REAL NOT NULL,
    success  INTEGER,
    output   TEXT,
    duration REAL
);
CREATE INDEX IF NOT EXISTS idx_jlog_job ON job_logs(job_id);
"""

def _db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    c = _db(); c.executescript(_SCHEMA); c.commit(); c.close()
    _load_all()
    threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler").start()
    log.info("Task Scheduler started")

# ── Job management ────────────────────────────────────────────────────────
def add_job(name: str, cmd: str, interval_s: int = 3600, job_type: str = "interval",
            enabled: bool = True, tags: str = "") -> str:
    jid = str(uuid.uuid4())[:8]
    next_run = time.time() + interval_s
    c = _db()
    c.execute(
        "INSERT INTO jobs (id,name,type,cmd,interval_s,next_run,enabled,created,tags) VALUES (?,?,?,?,?,?,?,?,?)",
        (jid, name, job_type, cmd, interval_s, next_run, int(enabled), time.time(), tags)
    )
    c.commit(); c.close()
    log.info(f"Job added: {name} ({jid}) every {interval_s}s")
    return jid

def remove_job(jid: str):
    c = _db()
    c.execute("DELETE FROM jobs WHERE id=?", (jid,))
    c.execute("DELETE FROM job_logs WHERE job_id=?", (jid,))
    c.commit(); c.close()

def toggle_job(jid: str, enabled: bool):
    c = _db(); c.execute("UPDATE jobs SET enabled=? WHERE id=?", (int(enabled), jid)); c.commit(); c.close()

def run_now(jid: str) -> dict:
    c = _db()
    row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    c.close()
    if not row: return {"ok": False, "error": "Job not found"}
    result = _execute_job(dict(row))
    return result

def get_jobs() -> list:
    c = _db()
    rows = c.execute("SELECT * FROM jobs ORDER BY created DESC").fetchall()
    c.close()
    return [dict(r) for r in rows]

def get_logs(jid: str = None, limit: int = 50) -> list:
    c = _db()
    if jid:
        rows = c.execute("SELECT * FROM job_logs WHERE job_id=? ORDER BY ts DESC LIMIT ?", (jid, limit)).fetchall()
    else:
        rows = c.execute("SELECT * FROM job_logs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]

# ── Execution ──────────────────────────────────────────────────────────────
def _execute_job(job: dict) -> dict:
    start = time.time()
    cmd   = job["cmd"]
    output = ""
    success = False
    try:
        if cmd.startswith("shell:"):
            r = subprocess.run(cmd[6:], shell=True, capture_output=True, text=True, timeout=60)
            output = (r.stdout + r.stderr).strip()[:2000]
            success = r.returncode == 0
        elif cmd.startswith("python:"):
            exec_globals = {"__builtins__": __builtins__}
            exec(cmd[7:], exec_globals)
            output = "Python executed OK"
            success = True
        elif cmd.startswith("alert:"):
            # Send alert via ARIA alerts module
            try:
                import modules.alerts as al
                parts = cmd[6:].split("|", 1)
                title = parts[0].strip()
                msg   = parts[1].strip() if len(parts) > 1 else title
                al.send(title, msg, "ntfy", "default", "scheduler")
                output = f"Alert sent: {title}"
                success = True
            except Exception as e:
                output = str(e)
        elif cmd.startswith("http:") or cmd.startswith("https:"):
            import requests
            r = requests.get(cmd, timeout=10)
            output = f"HTTP {r.status_code} — {len(r.content)} bytes"
            success = r.status_code < 400
        else:
            output = f"Unknown command type: {cmd[:50]}"

    except Exception as e:
        output = str(e)[:500]

    duration = time.time() - start

    # Update job record
    c = _db()
    c.execute(
        "UPDATE jobs SET last_run=?, last_result=?, runs=runs+1, next_run=? WHERE id=?",
        (start, output[:200], start + job.get("interval_s", 3600), job["id"])
    )
    c.execute(
        "INSERT INTO job_logs (job_id,ts,success,output,duration) VALUES (?,?,?,?,?)",
        (job["id"], start, int(success), output[:2000], round(duration, 3))
    )
    c.commit(); c.close()

    log.info(f"Job [{job['name']}] {'OK' if success else 'FAIL'} ({duration:.1f}s): {output[:80]}")
    return {"ok": success, "output": output, "duration": duration}

def _load_all():
    pass  # Jobs are polled from DB in scheduler loop

def _scheduler_loop():
    while _RUNNING:
        try:
            c = _db()
            due = c.execute(
                "SELECT * FROM jobs WHERE enabled=1 AND next_run <= ?", (time.time(),)
            ).fetchall()
            c.close()
            for row in due:
                job = dict(row)
                threading.Thread(target=_execute_job, args=(job,), daemon=True,
                                 name=f"job-{job['id']}").start()
        except Exception as e:
            log.error(f"Scheduler loop error: {e}")
        time.sleep(10)  # Check every 10s

init()
