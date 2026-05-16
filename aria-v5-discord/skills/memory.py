"""
Layer 1 — Memory System
Short-term : ใน RAM (conversation context)
Long-term  : SQLite vector-like (keyword index)
Episodic   : บันทึกเหตุการณ์สำคัญ
"""
import sqlite3, json, re, os
from datetime import datetime
from pathlib import Path

DB = Path(__file__).parent.parent / "memory.db"


def _conn():
    c = sqlite3.connect(str(DB))
    c.execute("""CREATE TABLE IF NOT EXISTS long_term(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT, value TEXT, tags TEXT, ts TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS episodic(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        summary TEXT, importance INTEGER DEFAULT 1, ts TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS preferences(
        key TEXT PRIMARY KEY, value TEXT, ts TEXT)""")
    c.commit()
    return c


# ── Long-term memory ───────────────────────────────────────────────────────

def remember(key: str, value: str, tags: str = "") -> str:
    c = _conn()
    ts = datetime.now().isoformat()
    # Update if key exists
    existing = c.execute("SELECT id FROM long_term WHERE key=?", (key,)).fetchone()
    if existing:
        c.execute("UPDATE long_term SET value=?,tags=?,ts=? WHERE key=?", (value,tags,ts,key))
    else:
        c.execute("INSERT INTO long_term(key,value,tags,ts) VALUES(?,?,?,?)", (key,value,tags,ts))
    c.commit(); c.close()
    return f"✅ จำแล้ว: {key}"


def recall(query: str, limit: int = 5) -> list[dict]:
    """Search memory by keyword."""
    c = _conn()
    words = query.lower().split()
    results = []
    rows = c.execute("SELECT key,value,tags,ts FROM long_term ORDER BY ts DESC LIMIT 200").fetchall()
    for key, value, tags, ts in rows:
        score = sum(1 for w in words if w in (key+value+(tags or "")).lower())
        if score > 0:
            results.append({"key":key,"value":value,"tags":tags,"ts":ts,"score":score})
    c.close()
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def recall_all() -> list[dict]:
    c = _conn()
    rows = c.execute("SELECT key,value,tags,ts FROM long_term ORDER BY ts DESC LIMIT 100").fetchall()
    c.close()
    return [{"key":r[0],"value":r[1],"tags":r[2],"ts":r[3]} for r in rows]


def forget(key: str) -> str:
    c = _conn()
    c.execute("DELETE FROM long_term WHERE key=?", (key,))
    c.commit(); c.close()
    return f"🗑️ ลืม: {key}"


# ── Episodic memory ────────────────────────────────────────────────────────

def record_episode(summary: str, importance: int = 1):
    c = _conn()
    c.execute("INSERT INTO episodic(summary,importance,ts) VALUES(?,?,?)",
              (summary, importance, datetime.now().isoformat()))
    c.commit(); c.close()


def get_episodes(limit: int = 10) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT summary,importance,ts FROM episodic ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    c.close()
    return [{"summary":r[0],"importance":r[1],"ts":r[2]} for r in rows]


# ── User preferences ───────────────────────────────────────────────────────

def set_pref(key: str, value: str):
    c = _conn()
    c.execute("INSERT OR REPLACE INTO preferences(key,value,ts) VALUES(?,?,?)",
              (key, value, datetime.now().isoformat()))
    c.commit(); c.close()


def get_pref(key: str, default: str = "") -> str:
    c = _conn()
    row = c.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
    c.close()
    return row[0] if row else default


def get_all_prefs() -> dict:
    c = _conn()
    rows = c.execute("SELECT key,value FROM preferences").fetchall()
    c.close()
    return {r[0]: r[1] for r in rows}


# ── Memory context builder ─────────────────────────────────────────────────

def build_memory_context(query: str) -> str:
    """Build memory context string to inject into system prompt."""
    relevant = recall(query, limit=3)
    prefs    = get_all_prefs()
    episodes = get_episodes(limit=3)
    parts    = []

    if relevant:
        parts.append("💾 ความจำที่เกี่ยวข้อง:")
        for m in relevant:
            parts.append(f"  • {m['key']}: {m['value']}")

    if prefs:
        parts.append("👤 ความชอบของ user:")
        for k, v in list(prefs.items())[:5]:
            parts.append(f"  • {k}: {v}")

    if episodes:
        parts.append("📅 เหตุการณ์ล่าสุด:")
        for e in episodes:
            parts.append(f"  • {e['summary']}")

    return "\n".join(parts) if parts else ""


# ── Parse memory commands from chat ───────────────────────────────────────

def parse_memory_command(text: str) -> dict | None:
    t = text.strip().lower()
    if any(k in t for k in ["จำว่า","remember that","จำไว้","บันทึกว่า"]):
        # จำว่า X คือ Y / remember that X is Y
        m = re.search(r"(?:จำว่า|remember that|จำไว้|บันทึกว่า)\s+(.+)", text, re.I)
        if m:
            parts = re.split(r"\s+(?:คือ|เป็น|is|=|:)\s+", m.group(1), 1)
            key = parts[0].strip()
            val = parts[1].strip() if len(parts) > 1 else m.group(1).strip()
            return {"action":"remember","key":key,"value":val}
    if any(k in t for k in ["ลืม","forget","ลบความจำ"]):
        m = re.search(r"(?:ลืม|forget|ลบความจำ)\s+(.+)", text, re.I)
        if m:
            return {"action":"forget","key":m.group(1).strip()}
    if any(k in t for k in ["จำอะไรได้","ความจำ","หน่วยความจำ","what do you remember","recall"]):
        return {"action":"recall_all"}
    return None
