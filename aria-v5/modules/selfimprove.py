"""modules/selfimprove.py — Self-Improvement: feedback analysis + response adaptation"""
import os, json, time, sqlite3, threading, logging, requests
from collections import Counter

log = logging.getLogger("ARIA.SelfImprove")
DB_PATH    = os.environ.get("IMPROVE_DB", "aria_improve.db")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    query     TEXT NOT NULL,
    response  TEXT NOT NULL,
    rating    INTEGER,        -- 1-5
    comment   TEXT,
    session   TEXT,
    model     TEXT,
    improved  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS error_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    error     TEXT NOT NULL,
    context   TEXT,
    resolved  INTEGER DEFAULT 0,
    fix       TEXT
);
CREATE TABLE IF NOT EXISTS improvements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL NOT NULL,
    type        TEXT NOT NULL,
    description TEXT NOT NULL,
    applied     INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS prompt_templates (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT UNIQUE NOT NULL,
    template TEXT NOT NULL,
    score    REAL DEFAULT 0.0,
    uses     INTEGER DEFAULT 0,
    ts       REAL NOT NULL
);
"""

def _db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    c = _db(); c.executescript(_SCHEMA); c.commit(); c.close()

# ── Feedback Collection ────────────────────────────────────────────────────
def record_feedback(query: str, response: str, rating: int,
                    comment: str = "", session: str = "", model: str = "") -> int:
    """Rating: 1=terrible 2=bad 3=ok 4=good 5=excellent"""
    with _LOCK:
        c = _db()
        cur = c.execute(
            "INSERT INTO feedback (ts,query,response,rating,comment,session,model) VALUES (?,?,?,?,?,?,?)",
            (time.time(), query[:1000], response[:2000], rating, comment, session, model)
        )
        fid = cur.lastrowid
        c.commit(); c.close()
    log.info(f"Feedback: rating={rating} | query={query[:50]}")
    if rating <= 2:
        # Auto-analyze bad responses
        threading.Thread(target=_analyze_bad_response,
                         args=(query, response, comment), daemon=True).start()
    return fid

def record_error(error: str, context: str = ""):
    with _LOCK:
        c = _db()
        c.execute("INSERT INTO error_log (ts,error,context) VALUES (?,?,?)",
                  (time.time(), str(error)[:500], context[:500]))
        c.commit(); c.close()

# ── Analysis ───────────────────────────────────────────────────────────────
def _analyze_bad_response(query: str, response: str, comment: str):
    """Use LLM to understand why a response was bad"""
    try:
        prompt = f"""Analyze why this AI response was poor and suggest improvements.

User query: {query}
AI response: {response[:500]}
User feedback: {comment or 'No comment — rated 1-2/5'}

Output JSON: {{"root_cause": "...", "improvement": "...", "prompt_fix": "..."}}"""
        r = requests.post(f"{OLLAMA_URL}/api/chat",
                          json={"model": os.environ.get("IMPROVE_MODEL","qwen2.5:7b"),
                                "stream": False, "format": "json",
                                "messages": [{"role":"user","content":prompt}]},
                          timeout=60)
        analysis = json.loads(r.json().get("message",{}).get("content","{}"))
        with _LOCK:
            c = _db()
            c.execute("INSERT INTO improvements (ts,type,description) VALUES (?,?,?)",
                      (time.time(), "response_quality",
                       f"Q: {query[:100]} | Fix: {analysis.get('improvement','')[:200]}"))
            c.commit(); c.close()
        log.info(f"Self-improvement: {analysis.get('improvement','')[:80]}")
    except Exception as e:
        log.warning(f"Self-improve analysis failed: {e}")

def get_stats() -> dict:
    with _LOCK:
        c = _db()
        total_fb  = c.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        avg_rating = c.execute("SELECT AVG(rating) FROM feedback").fetchone()[0] or 0
        total_err  = c.execute("SELECT COUNT(*) FROM error_log").fetchone()[0]
        improvements = c.execute("SELECT COUNT(*) FROM improvements").fetchone()[0]
        recent_bad = c.execute(
            "SELECT query,rating,comment FROM feedback WHERE rating<=2 ORDER BY ts DESC LIMIT 5"
        ).fetchall()
        c.close()
    return {
        "total_feedback": total_fb,
        "avg_rating": round(avg_rating, 2),
        "total_errors": total_err,
        "improvements_found": improvements,
        "recent_issues": [{"q": r["query"][:80], "rating": r["rating"],
                           "comment": r["comment"]} for r in recent_bad],
    }

def get_feedback(limit: int = 50, min_rating: int = None) -> list:
    with _LOCK:
        c = _db()
        if min_rating is not None:
            rows = c.execute("SELECT * FROM feedback WHERE rating>=? ORDER BY ts DESC LIMIT ?",
                             (min_rating, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM feedback ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        c.close()
    return [dict(r) for r in rows]

def get_improvements(limit: int = 20) -> list:
    with _LOCK:
        c = _db()
        rows = c.execute("SELECT * FROM improvements ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        c.close()
    return [dict(r) for r in rows]

def run_improvement_cycle() -> dict:
    """Periodic cycle: analyze patterns and generate system improvements"""
    with _LOCK:
        c = _db()
        bad_queries = c.execute(
            "SELECT query, comment FROM feedback WHERE rating<=2 AND improved=0 LIMIT 20"
        ).fetchall()
        c.close()
    if not bad_queries:
        return {"status": "no_new_issues"}
    patterns = Counter()
    for row in bad_queries:
        q = row["query"].lower()
        if "weather" in q: patterns["weather"] += 1
        if "price" in q or "btc" in q: patterns["finance"] += 1
        if "error" in q or "fail" in q: patterns["errors"] += 1
        if len(row["query"].split()) < 3: patterns["short_queries"] += 1
    improvements = []
    for pattern, count in patterns.most_common(3):
        improvements.append({
            "type": "pattern",
            "description": f"Poor responses on '{pattern}' queries ({count} times). Review prompts.",
        })
    with _LOCK:
        c = _db()
        for imp in improvements:
            c.execute("INSERT INTO improvements (ts,type,description) VALUES (?,?,?)",
                      (time.time(), imp["type"], imp["description"]))
        # Mark as improved
        c.execute("UPDATE feedback SET improved=1 WHERE rating<=2 AND improved=0")
        c.commit(); c.close()
    return {"status": "done", "improvements": len(improvements), "patterns": dict(patterns)}

# ── Adaptive Response Context ──────────────────────────────────────────────
def get_adaptive_context(query: str) -> str:
    """Build a context string based on similar past interactions"""
    with _LOCK:
        c = _db()
        good = c.execute(
            "SELECT query, response FROM feedback WHERE rating>=4 ORDER BY ts DESC LIMIT 10"
        ).fetchall()
        c.close()
    if not good:
        return ""
    # Find similar queries (simple word overlap)
    q_words = set(query.lower().split())
    relevant = []
    for row in good:
        r_words = set(row["query"].lower().split())
        overlap = len(q_words & r_words) / max(len(q_words), 1)
        if overlap > 0.3:
            relevant.append(row)
    if not relevant:
        return ""
    examples = "\n".join(f"Q: {r['query'][:80]}\nA: {r['response'][:150]}" for r in relevant[:2])
    return f"\n[Similar successful responses for context]\n{examples}\n"


def analyze_errors() -> dict:
    """Backward-compatible helper for older API imports."""
    return run_improvement_cycle()


# Backward-compatible names used by server.py.
save_feedback = record_feedback
log_error = record_error
si_stats = get_stats

init()
