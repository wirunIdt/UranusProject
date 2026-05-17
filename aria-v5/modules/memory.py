"""modules/memory.py — Persistent AI Memory across sessions"""
import os, json, time, sqlite3, threading, re
from datetime import datetime

DB_PATH = os.environ.get("MEMORY_DB", "aria_memory.db")
_LOCK   = threading.Lock()

# ── Schema ────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL    NOT NULL,
    type      TEXT    NOT NULL DEFAULT 'chat',
    role      TEXT    NOT NULL DEFAULT 'user',
    content   TEXT    NOT NULL,
    summary   TEXT,
    tags      TEXT,
    session   TEXT,
    important INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS facts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL    NOT NULL,
    key     TEXT    NOT NULL UNIQUE,
    value   TEXT    NOT NULL,
    source  TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id       TEXT    PRIMARY KEY,
    started  REAL    NOT NULL,
    ended    REAL,
    title    TEXT,
    turns    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mem_ts   ON memories(ts DESC);
CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(type);
CREATE INDEX IF NOT EXISTS idx_mem_tags ON memories(tags);
"""

def _db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    with _LOCK:
        c = _db()
        c.executescript(_SCHEMA)
        c.commit()
        c.close()

# ── Write ─────────────────────────────────────────────────────────────────
def save_message(content: str, role: str = "user", session: str = None,
                 msg_type: str = "chat", important: bool = False) -> int:
    tags = _extract_tags(content)
    with _LOCK:
        c = _db()
        cur = c.execute(
            "INSERT INTO memories (ts,type,role,content,tags,session,important) VALUES (?,?,?,?,?,?,?)",
            (time.time(), msg_type, role, content[:4000], json.dumps(tags), session, int(important))
        )
        mid = cur.lastrowid
        if session:
            c.execute("INSERT OR IGNORE INTO sessions (id,started) VALUES (?,?)", (session, time.time()))
            c.execute("UPDATE sessions SET turns=turns+1, ended=? WHERE id=?", (time.time(), session))
        c.commit(); c.close()
    return mid

def save_fact(key: str, value: str, source: str = "user"):
    with _LOCK:
        c = _db()
        c.execute(
            "INSERT OR REPLACE INTO facts (ts,key,value,source) VALUES (?,?,?,?)",
            (time.time(), key.lower().strip(), value[:1000], source)
        )
        c.commit(); c.close()

def save_summary(session: str, summary: str):
    with _LOCK:
        c = _db()
        c.execute("UPDATE sessions SET title=? WHERE id=?", (summary[:200], session))
        c.commit(); c.close()

# ── Read ──────────────────────────────────────────────────────────────────
def get_recent(limit: int = 20, session: str = None) -> list:
    with _LOCK:
        c = _db()
        if session:
            rows = c.execute(
                "SELECT * FROM memories WHERE session=? ORDER BY ts DESC LIMIT ?",
                (session, limit)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM memories ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        c.close()
    return [dict(r) for r in reversed(rows)]

def search(query: str, limit: int = 20) -> list:
    q = f"%{query.lower()}%"
    with _LOCK:
        c = _db()
        rows = c.execute(
            "SELECT * FROM memories WHERE lower(content) LIKE ? OR tags LIKE ? ORDER BY ts DESC LIMIT ?",
            (q, q, limit)
        ).fetchall()
        c.close()
    return [dict(r) for r in rows]

def get_facts(key: str = None) -> list:
    with _LOCK:
        c = _db()
        if key:
            rows = c.execute("SELECT * FROM facts WHERE key LIKE ?", (f"%{key.lower()}%",)).fetchall()
        else:
            rows = c.execute("SELECT * FROM facts ORDER BY ts DESC").fetchall()
        c.close()
    return [dict(r) for r in rows]

def get_important(limit: int = 30) -> list:
    with _LOCK:
        c = _db()
        rows = c.execute(
            "SELECT * FROM memories WHERE important=1 ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        c.close()
    return [dict(r) for r in rows]

def get_sessions(limit: int = 20) -> list:
    with _LOCK:
        c = _db()
        rows = c.execute(
            "SELECT * FROM sessions ORDER BY started DESC LIMIT ?", (limit,)
        ).fetchall()
        c.close()
    return [dict(r) for r in rows]

def get_context(session: str = None, max_chars: int = 3000) -> str:
    """Build context string for AI from recent + important memories"""
    lines = []
    # Recent session messages
    recent = get_recent(limit=10, session=session)
    for m in recent:
        prefix = "User" if m["role"] == "user" else "AI"
        lines.append(f"[{prefix}] {m['content'][:300]}")
    # Important facts
    facts = get_facts()[:10]
    if facts:
        lines.append("\n[Known facts]")
        for f in facts:
            lines.append(f"  {f['key']}: {f['value']}")
    ctx = "\n".join(lines)
    return ctx[-max_chars:]

def stats() -> dict:
    with _LOCK:
        c = _db()
        total    = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        sessions = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        facts_n  = c.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        oldest   = c.execute("SELECT MIN(ts) FROM memories").fetchone()[0]
        c.close()
    return {
        "total_messages": total,
        "sessions": sessions,
        "facts": facts_n,
        "oldest": datetime.fromtimestamp(oldest).isoformat() if oldest else None,
        "db_path": DB_PATH,
        "db_size_kb": round(os.path.getsize(DB_PATH)/1024, 1) if os.path.exists(DB_PATH) else 0,
    }

def delete_session(session_id: str):
    with _LOCK:
        c = _db()
        c.execute("DELETE FROM memories WHERE session=?", (session_id,))
        c.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        c.commit(); c.close()

def clear_all():
    with _LOCK:
        c = _db()
        c.execute("DELETE FROM memories")
        c.execute("DELETE FROM sessions")
        c.execute("DELETE FROM facts")
        c.commit(); c.close()

# ── Tag extraction ────────────────────────────────────────────────────────
_KEYWORDS = ["bitcoin","crypto","war","conflict","earthquake","weather","code",
             "python","error","help","thai","price","stock","news","hack","server"]

def _extract_tags(text: str) -> list:
    text_lower = text.lower()
    tags = [k for k in _KEYWORDS if k in text_lower]
    # Extract /commands
    cmds = re.findall(r'/(\w+)', text)
    tags.extend(cmds[:3])
    return list(set(tags))[:8]

# Init on import
init()
