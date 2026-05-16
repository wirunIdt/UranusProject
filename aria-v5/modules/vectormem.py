"""modules/vectormem.py — Vector Memory (FAISS + Ollama embeddings)"""
import os, json, time, sqlite3, threading, struct, math, hashlib, logging

log = logging.getLogger("ARIA.VectorMem")
DB_PATH  = os.environ.get("VECTOR_DB", "aria_vectors.db")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
_LOCK = threading.Lock()

# Try FAISS
try:
    import faiss, numpy as np
    _HAS_FAISS = True
    _faiss_index = None
    _faiss_ids   = []   # maps faiss index → db row id
    log.info("FAISS available — using GPU-accelerated vector search")
except ImportError:
    _HAS_FAISS = False
    log.info("FAISS not found — using cosine similarity fallback (pip install faiss-cpu)")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    text     TEXT NOT NULL,
    embedding BLOB,
    meta     TEXT,
    source   TEXT,
    ts       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vec_ts ON vectors(ts DESC);
"""

def _db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    c = _db(); c.executescript(_SCHEMA); c.commit(); c.close()
    if _HAS_FAISS:
        _rebuild_faiss()

def _embed_ollama(text: str):
    import requests as req
    try:
        r = req.post(f"{OLLAMA_URL}/api/embeddings",
                     json={"model": EMBED_MODEL, "prompt": text[:2000]},
                     timeout=30)
        if r.status_code == 200:
            vec = r.json().get("embedding")
            if vec: return vec
    except: pass
    return None

def _embed_tfidf(text: str, dim: int = 512):
    import re
    words = re.findall(r'\w+', text.lower())
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    vec = [0.0] * dim
    for w, cnt in freq.items():
        h = int(hashlib.md5(w.encode()).hexdigest(), 16) % dim
        vec[h] += cnt / max(len(words), 1)
    mag = math.sqrt(sum(x*x for x in vec)) or 1.0
    return [x/mag for x in vec]

def _get_embedding(text: str):
    vec = _embed_ollama(text)
    if not vec:
        vec = _embed_tfidf(text)
    return vec

def _vec_to_bytes(vec) -> bytes:
    return struct.pack(f'{len(vec)}f', *vec)

def _bytes_to_vec(b: bytes):
    n = len(b) // 4
    return list(struct.unpack(f'{n}f', b))

def _cosine(v1, v2) -> float:
    dot  = sum(a*b for a,b in zip(v1,v2))
    mag1 = math.sqrt(sum(a*a for a in v1)) or 1e-9
    mag2 = math.sqrt(sum(b*b for b in v2)) or 1e-9
    return dot / (mag1 * mag2)

def _rebuild_faiss():
    global _faiss_index, _faiss_ids
    if not _HAS_FAISS: return
    c = _db()
    rows = c.execute("SELECT id, embedding FROM vectors WHERE embedding IS NOT NULL").fetchall()
    c.close()
    if not rows: return
    dim = len(_bytes_to_vec(rows[0]["embedding"]))
    idx = faiss.IndexFlatIP(dim)  # Inner product (cosine with normalized vecs)
    vecs, ids = [], []
    for row in rows:
        v = _bytes_to_vec(row["embedding"])
        # Normalize for cosine
        mag = math.sqrt(sum(x*x for x in v)) or 1.0
        v = [x/mag for x in v]
        vecs.append(v); ids.append(row["id"])
    if vecs:
        mat = np.array(vecs, dtype=np.float32)
        idx.add(mat)
    _faiss_index = idx
    _faiss_ids   = ids

# ── Public API ─────────────────────────────────────────────────────────────
def add(text: str, meta: dict = None, source: str = "user") -> int:
    vec = _get_embedding(text)
    blob = _vec_to_bytes(vec) if vec else None
    with _LOCK:
        c = _db()
        cur = c.execute(
            "INSERT INTO vectors (text, embedding, meta, source, ts) VALUES (?,?,?,?,?)",
            (text[:4000], blob, json.dumps(meta or {}), source, time.time())
        )
        row_id = cur.lastrowid
        c.commit(); c.close()
    # Update FAISS index
    if _HAS_FAISS and vec and _faiss_index is not None:
        import numpy as np
        mag = math.sqrt(sum(x*x for x in vec)) or 1.0
        v = [x/mag for x in vec]
        _faiss_index.add(np.array([v], dtype=np.float32))
        _faiss_ids.append(row_id)
    return row_id

def search(query: str, top_k: int = 5) -> list:
    q_vec = _get_embedding(query)
    if not q_vec:
        return []
    if _HAS_FAISS and _faiss_index is not None and _faiss_index.ntotal > 0:
        import numpy as np
        mag = math.sqrt(sum(x*x for x in q_vec)) or 1.0
        q_norm = [x/mag for x in q_vec]
        scores, indices = _faiss_index.search(
            np.array([q_norm], dtype=np.float32), min(top_k, _faiss_index.ntotal))
        results = []
        c = _db()
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(_faiss_ids): continue
            row_id = _faiss_ids[idx]
            row = c.execute("SELECT * FROM vectors WHERE id=?", (row_id,)).fetchone()
            if row:
                results.append({"id": row["id"], "text": row["text"],
                                 "score": float(score), "source": row["source"],
                                 "meta": json.loads(row["meta"] or "{}"),
                                 "ts": row["ts"]})
        c.close()
        return results
    # Fallback: linear scan
    with _LOCK:
        c = _db()
        rows = c.execute("SELECT * FROM vectors WHERE embedding IS NOT NULL").fetchall()
        c.close()
    scored = []
    for row in rows:
        v = _bytes_to_vec(row["embedding"])
        score = _cosine(q_vec, v)
        scored.append({"id": row["id"], "text": row["text"], "score": score,
                       "source": row["source"],
                       "meta": json.loads(row["meta"] or "{}"), "ts": row["ts"]})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

def stats() -> dict:
    with _LOCK:
        c = _db()
        total = c.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        c.close()
    return {"total": total, "faiss": _HAS_FAISS,
            "faiss_indexed": _faiss_index.ntotal if _HAS_FAISS and _faiss_index else 0,
            "embed_model": EMBED_MODEL, "db": DB_PATH}

def clear():
    global _faiss_index, _faiss_ids
    with _LOCK:
        c = _db(); c.execute("DELETE FROM vectors"); c.commit(); c.close()
    if _HAS_FAISS:
        _faiss_index = None; _faiss_ids = []


def get_all_vectors(limit: int = 100) -> list:
    with _LOCK:
        c = _db()
        rows = c.execute("SELECT id,text,meta,source,ts FROM vectors ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        c.close()
    return [
        {
            "id": row["id"],
            "text": row["text"],
            "meta": json.loads(row["meta"] or "{}"),
            "source": row["source"],
            "ts": row["ts"],
        }
        for row in rows
    ]


def delete_vector(vector_id: int) -> bool:
    with _LOCK:
        c = _db()
        cur = c.execute("DELETE FROM vectors WHERE id=?", (vector_id,))
        c.commit()
        deleted = cur.rowcount > 0
        c.close()
    if deleted and _HAS_FAISS:
        _rebuild_faiss()
    return deleted


# Backward-compatible names used by server.py.
add_vector = add
search_vectors = search
rebuild_faiss = _rebuild_faiss
vstats = stats

init()
