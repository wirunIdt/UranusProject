"""
Layer 2+4 — Task Scheduler & Autonomous Agent
- Queue tasks, run in background threads
- Self-correction loop (retry on fail)
- Proactive suggestions
- Audit log
"""
import sqlite3, json, threading, time, traceback
from datetime import datetime
from pathlib import Path
from collections import deque

DB = Path(__file__).parent.parent / "tasks.db"
_task_lock = threading.Lock()
_callbacks: dict = {}   # task_id → callback fn


def _conn():
    c = sqlite3.connect(str(DB))
    c.execute("""CREATE TABLE IF NOT EXISTS tasks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, action TEXT, payload TEXT,
        status TEXT DEFAULT 'pending',
        result TEXT, error TEXT,
        created_at TEXT, started_at TEXT, done_at TEXT,
        retry INTEGER DEFAULT 0, max_retry INTEGER DEFAULT 2)""")
    c.execute("""CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor TEXT, action TEXT, detail TEXT,
        ts TEXT, success INTEGER DEFAULT 1)""")
    c.commit()
    return c


# ══ Audit Log ════════════════════════════════════════════════════════════════

def audit(actor: str, action: str, detail: str = "", success: bool = True):
    c = _conn()
    c.execute("INSERT INTO audit_log(actor,action,detail,ts,success) VALUES(?,?,?,?,?)",
              (actor, action, detail[:500], datetime.now().isoformat(), int(success)))
    c.commit(); c.close()


def get_audit_log(limit: int = 20) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT actor,action,detail,ts,success FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    c.close()
    return [{"actor":r[0],"action":r[1],"detail":r[2],"ts":r[3],"success":bool(r[4])} for r in rows]


# ══ Task Queue ════════════════════════════════════════════════════════════════

def queue_task(name: str, action: str, payload: dict, callback=None, max_retry: int = 2) -> int:
    """Add task to queue, return task_id."""
    c = _conn()
    cur = c.execute(
        "INSERT INTO tasks(name,action,payload,status,created_at,max_retry) VALUES(?,?,?,?,?,?)",
        (name, action, json.dumps(payload), "pending", datetime.now().isoformat(), max_retry)
    )
    task_id = cur.lastrowid
    c.commit(); c.close()
    if callback:
        _callbacks[task_id] = callback
    # Run in thread
    threading.Thread(target=_run_task, args=(task_id,), daemon=True).start()
    return task_id


def _run_task(task_id: int):
    """Execute a task with retry + self-correction loop."""
    c = _conn()
    row = c.execute(
        "SELECT name,action,payload,retry,max_retry FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    c.close()
    if not row: return
    name, action, payload_str, retry, max_retry = row
    payload = json.loads(payload_str)

    for attempt in range(max_retry + 1):
        try:
            _update_task(task_id, "running", started_at=datetime.now().isoformat(), retry=attempt)
            result = _dispatch_action(action, payload)
            _update_task(task_id, "done", result=result)
            audit("agent", f"task:{action}", f"{name} → {result[:100]}")
            cb = _callbacks.pop(task_id, None)
            if cb: cb({"task_id":task_id,"status":"done","result":result})
            return
        except Exception as e:
            err = traceback.format_exc()
            if attempt < max_retry:
                time.sleep(2 ** attempt)   # exponential backoff
                # Self-correction: log and retry
                audit("agent", f"task_retry:{action}", f"attempt {attempt+1}: {str(e)}", success=False)
            else:
                _update_task(task_id, "failed", error=err)
                audit("agent", f"task_failed:{action}", str(e)[:200], success=False)
                cb = _callbacks.pop(task_id, None)
                if cb: cb({"task_id":task_id,"status":"failed","error":str(e)})


def _dispatch_action(action: str, payload: dict) -> str:
    """Dispatch task action to appropriate skill."""
    if action == "shell":
        from skills.agent_system import run_shell
        return run_shell(payload.get("command",""), payload.get("cwd"))
    if action == "python":
        from skills.agent_system import run_python
        return run_python(payload.get("code",""))
    if action == "create_file":
        from skills.agent_system import create_file
        return create_file(payload.get("path",""), payload.get("content",""))
    if action == "remember":
        from skills.memory import remember
        return remember(payload.get("key",""), payload.get("value",""))
    if action == "weather":
        from skills.weather import get_weather
        d = get_weather(payload.get("city","Bangkok"), payload.get("lang","th"))
        return d.get("summary","❓")
    raise ValueError(f"Unknown action: {action}")


def _update_task(task_id: int, status: str, result: str = None,
                 error: str = None, started_at: str = None, retry: int = None):
    c = _conn()
    updates = {"status": status, "done_at": datetime.now().isoformat()}
    if result is not None:    updates["result"]     = result[:2000]
    if error is not None:     updates["error"]      = error[:2000]
    if started_at is not None:updates["started_at"] = started_at
    if retry is not None:     updates["retry"]      = retry
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [task_id]
    c.execute(f"UPDATE tasks SET {sets} WHERE id=?", vals)
    c.commit(); c.close()


def get_tasks(limit: int = 20) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT id,name,action,status,result,error,created_at,retry FROM tasks ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    c.close()
    return [{"id":r[0],"name":r[1],"action":r[2],"status":r[3],
             "result":r[4],"error":r[5],"created_at":r[6],"retry":r[7]} for r in rows]


def get_task(task_id: int) -> dict | None:
    c = _conn()
    row = c.execute(
        "SELECT id,name,action,status,result,error,created_at,done_at,retry FROM tasks WHERE id=?",
        (task_id,)
    ).fetchone()
    c.close()
    if not row: return None
    return {"id":row[0],"name":row[1],"action":row[2],"status":row[3],
            "result":row[4],"error":row[5],"created_at":row[6],"done_at":row[7],"retry":row[8]}


# ══ Proactive Suggestions ═════════════════════════════════════════════════════

PROACTIVE_TIPS = [
    "💡 ลองพูดว่า 'จำว่า...' เพื่อให้ฉันจดจำข้อมูลสำคัญ",
    "💡 พิมพ์ $ ตามด้วยคำสั่ง เช่น `$ dir` เพื่อรัน shell ตรงๆ",
    "💡 ส่งรูปหรือ PDF มาฉันอ่านให้ได้",
    "💡 บอกว่า 'แสดง task' เพื่อดูงานที่กำลังทำอยู่",
    "💡 อยากรู้อากาศไหม? พิมพ์ 'อากาศวันนี้ [เมือง]'",
]
_tip_idx = 0

def get_proactive_tip() -> str:
    global _tip_idx
    tip = PROACTIVE_TIPS[_tip_idx % len(PROACTIVE_TIPS)]
    _tip_idx += 1
    return tip
