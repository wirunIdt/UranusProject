"""
modules/rag.py — RAG (Retrieval-Augmented Generation)
Upload docs → chunk → embed → semantic search → answer
Uses Ollama embeddings (nomic-embed-text) or TF-IDF fallback
"""
import os, json, time, sqlite3, hashlib, threading, logging, re
import struct
import math

log = logging.getLogger("ARIA.RAG")
DB_PATH = os.environ.get("RAG_DB", "aria_rag.db")
_LOCK = threading.Lock()
CHUNK_SIZE = 400   # chars per chunk
CHUNK_OVERLAP = 80
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
OLLAMA_URL  = os.environ.get("OLLAMA_URL",  "http://localhost:11434")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    path     TEXT,
    type     TEXT,
    chars    INTEGER,
    chunks   INTEGER,
    added    REAL NOT NULL,
    meta     TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id   TEXT NOT NULL,
    idx      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    embed    BLOB,
    FOREIGN KEY(doc_id) REFERENCES documents(id)
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunks(doc_id);
"""

def _db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    c = _db(); c.executescript(_SCHEMA); c.commit(); c.close()

# ── Chunking ──────────────────────────────────────────────────────────────
def _chunk_text(text: str) -> list:
    """Split text into overlapping chunks"""
    text = re.sub(r'\s+', ' ', text).strip()
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks

# ── Embeddings ────────────────────────────────────────────────────────────
def _embed_ollama(text: str) -> list[float] | None:
    """Get embedding vector from Ollama"""
    try:
        import requests as req
        r = req.post(f"{OLLAMA_URL}/api/embeddings",
                     json={"model": EMBED_MODEL, "prompt": text[:2000]},
                     timeout=30)
        if r.status_code == 200:
            return r.json().get("embedding")
    except:
        pass
    return None

def _tfidf_embed(text: str, vocab_size: int = 512) -> list[float]:
    """Simple TF-IDF style embedding as fallback (no external deps)"""
    words = re.findall(r'\w+', text.lower())
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    vec = [0.0] * vocab_size
    for w, cnt in freq.items():
        h = int(hashlib.md5(w.encode()).hexdigest(), 16) % vocab_size
        vec[h] += cnt / max(len(words), 1)
    # L2 normalize
    mag = math.sqrt(sum(x*x for x in vec)) or 1.0
    return [x/mag for x in vec]

def _embed(text: str) -> bytes:
    """Get embedding as bytes for storage"""
    vec = _embed_ollama(text) or _tfidf_embed(text)
    return struct.pack(f'{len(vec)}f', *vec)

def _cosine(b1: bytes, b2: bytes) -> float:
    """Cosine similarity between two packed float vectors"""
    try:
        n = len(b1) // 4
        if n != len(b2) // 4: return 0.0
        v1 = struct.unpack(f'{n}f', b1)
        v2 = struct.unpack(f'{n}f', b2)
        dot  = sum(a*b for a,b in zip(v1,v2))
        mag1 = math.sqrt(sum(a*a for a in v1)) or 1e-9
        mag2 = math.sqrt(sum(b*b for b in v2)) or 1e-9
        return dot / (mag1 * mag2)
    except:
        return 0.0

# ── Index document ────────────────────────────────────────────────────────
def index_document(text: str, name: str, path: str = "", doc_type: str = "text",
                   meta: dict = None) -> str:
    """Chunk + embed + store a document. Returns doc_id."""
    doc_id = hashlib.md5(f"{name}{time.time()}".encode()).hexdigest()[:12]
    chunks = _chunk_text(text)

    with _LOCK:
        c = _db()
        c.execute(
            "INSERT OR REPLACE INTO documents (id,name,path,type,chars,chunks,added,meta) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, name, path, doc_type, len(text), len(chunks), time.time(), json.dumps(meta or {}))
        )
        for idx, chunk in enumerate(chunks):
            embed_bytes = _embed(chunk)
            c.execute(
                "INSERT INTO chunks (doc_id,idx,text,embed) VALUES (?,?,?,?)",
                (doc_id, idx, chunk, embed_bytes)
            )
        c.commit(); c.close()

    log.info(f"RAG indexed: '{name}' → {len(chunks)} chunks")
    return doc_id

# ── Search ────────────────────────────────────────────────────────────────
def search(query: str, top_k: int = 5, doc_id: str = None) -> list:
    """Semantic search — returns top_k most relevant chunks"""
    q_embed = _embed(query)

    with _LOCK:
        c = _db()
        if doc_id:
            rows = c.execute("SELECT * FROM chunks WHERE doc_id=?", (doc_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM chunks").fetchall()
        c.close()

    scored = []
    for row in rows:
        if row["embed"]:
            score = _cosine(q_embed, row["embed"])
        else:
            # Keyword fallback
            q_words = set(query.lower().split())
            t_words = set(row["text"].lower().split())
            score = len(q_words & t_words) / max(len(q_words), 1)
        scored.append({"text": row["text"], "doc_id": row["doc_id"],
                       "idx": row["idx"], "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

# ── Ask question ──────────────────────────────────────────────────────────
def ask(question: str, model: str = None, top_k: int = 5, doc_id: str = None) -> dict:
    """RAG pipeline: search → build context → LLM answer"""
    import requests as req

    chunks = search(question, top_k, doc_id)
    if not chunks:
        return {"answer": "No documents indexed. Upload a document first with /rag upload <path>",
                "chunks": [], "sources": []}

    context = "\n\n---\n\n".join(
        f"[Chunk {c['idx']+1} | score {c['score']:.2f}]\n{c['text']}"
        for c in chunks
    )
    prompt = f"""Answer the question using ONLY the provided context.
If the answer is not in the context, say "Not found in documents."

Context:
{context}

Question: {question}

Answer:"""

    if not model:
        model = os.environ.get("RAG_MODEL", "qwen2.5:7b")

    try:
        r = req.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": model, "stream": False,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60
        )
        answer = r.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        answer = f"LLM error: {str(e)}"

    # Get document names for sources
    doc_ids = list({c["doc_id"] for c in chunks})
    with _LOCK:
        c = _db()
        docs = {r["id"]: r["name"] for r in
                c.execute(f"SELECT id,name FROM documents WHERE id IN ({','.join('?'*len(doc_ids))})",
                          doc_ids).fetchall()}
        c.close()

    return {
        "answer": answer,
        "chunks": chunks,
        "sources": [{"doc_id": did, "name": docs.get(did, did)} for did in doc_ids],
        "model": model,
    }

# ── List / Delete ─────────────────────────────────────────────────────────
def list_docs() -> list:
    with _LOCK:
        c = _db()
        rows = c.execute("SELECT * FROM documents ORDER BY added DESC").fetchall()
        c.close()
    return [dict(r) for r in rows]

def delete_doc(doc_id: str):
    with _LOCK:
        c = _db()
        c.execute("DELETE FROM chunks WHERE doc_id=?",    (doc_id,))
        c.execute("DELETE FROM documents WHERE id=?",     (doc_id,))
        c.commit(); c.close()

def stats() -> dict:
    with _LOCK:
        c = _db()
        docs   = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        c.close()
    return {"documents": docs, "chunks": chunks, "db": DB_PATH,
            "db_kb": round(os.path.getsize(DB_PATH)/1024, 1) if os.path.exists(DB_PATH) else 0}

init()
