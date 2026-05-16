"""
Conversation Recorder
- Records ALL messages to SQLite (offline, no internet needed)
- Session-based history
- Export to JSON/TXT
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "history.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            session   TEXT NOT NULL,
            role      TEXT NOT NULL,
            content   TEXT NOT NULL,
            model     TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            summary    TEXT
        )
    """)
    conn.commit()
    return conn


class Recorder:
    def __init__(self):
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        conn = _get_conn()
        conn.execute("INSERT OR IGNORE INTO sessions VALUES (?,?,?)",
                     (self.session_id, datetime.now().isoformat(), None))
        conn.commit()
        conn.close()

    def record(self, role: str, content: str, model: str = ""):
        """Record a single message."""
        conn = _get_conn()
        conn.execute(
            "INSERT INTO messages (session,role,content,model,timestamp) VALUES (?,?,?,?,?)",
            (self.session_id, role, content, model, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    def get_session_history(self, session_id: str = None) -> list[dict]:
        sid = session_id or self.session_id
        conn = _get_conn()
        rows = conn.execute(
            "SELECT role,content,model,timestamp FROM messages WHERE session=? ORDER BY id",
            (sid,)
        ).fetchall()
        conn.close()
        return [{"role": r[0], "content": r[1], "model": r[2], "ts": r[3]}
                for r in rows]

    def get_all_sessions(self) -> list[dict]:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id,created_at,summary FROM sessions ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        # Count messages per session
        result = []
        for sid, created, summary in rows:
            count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session=?", (sid,)
            ).fetchone()[0]
            result.append({"id": sid, "created": created,
                            "summary": summary, "count": count})
        conn.close()
        return result

    def export_txt(self, path: str, session_id: str = None) -> str:
        history = self.get_session_history(session_id)
        lines = [f"=== Aria Chat Export — Session {session_id or self.session_id} ===\n"]
        for msg in history:
            ts  = msg["ts"][:16].replace("T", " ")
            role = "🦾 Aria" if msg["role"] == "assistant" else "👤 You"
            lines.append(f"[{ts}] {role}:\n{msg['content']}\n")
        text = "\n".join(lines)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return f"✅ Exported to {path}"

    def export_json(self, path: str, session_id: str = None) -> str:
        history = self.get_session_history(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"session": session_id or self.session_id,
                       "messages": history}, f, indent=2, ensure_ascii=False)
        return f"✅ Exported to {path}"

    def delete_session(self, session_id: str):
        conn = _get_conn()
        conn.execute("DELETE FROM messages WHERE session=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        conn.commit()
        conn.close()

    def get_stats(self) -> dict:
        conn = _get_conn()
        total_msg  = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        total_sess = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        return {"total_messages": total_msg, "total_sessions": total_sess,
                "db_path": DB_PATH}
