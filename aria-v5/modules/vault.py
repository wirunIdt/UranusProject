"""modules/vault.py — Encrypted Secrets Vault (AES via Fernet)"""
import os, json, time, sqlite3, hashlib, threading, base64, secrets
from typing import Optional

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    HAS_FERNET = True
except ImportError:
    HAS_FERNET = False

DB_PATH  = os.environ.get("VAULT_DB", "aria_vault.db")
_LOCK    = threading.Lock()
_fernet  = None   # initialized on unlock

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS secrets (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    category  TEXT    NOT NULL DEFAULT 'general',
    name      TEXT    NOT NULL,
    enc_data  BLOB    NOT NULL,
    tags      TEXT,
    created   REAL    NOT NULL,
    updated   REAL    NOT NULL,
    notes     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sec_cat ON secrets(category);
"""

def _db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    c = _db(); c.executescript(_SCHEMA); c.commit(); c.close()

def _derive_key(master_password: str) -> bytes:
    c = _db()
    row = c.execute("SELECT value FROM vault_meta WHERE key='salt'").fetchone()
    c.close()
    if row:
        salt = base64.b64decode(row["value"])
    else:
        salt = secrets.token_bytes(16)
        c2 = _db()
        c2.execute("INSERT OR REPLACE INTO vault_meta VALUES (?,?)",
                   ("salt", base64.b64encode(salt).decode()))
        c2.commit(); c2.close()
    if HAS_FERNET:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
        return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
    else:
        raw = hashlib.pbkdf2_hmac("sha256", master_password.encode(), salt, 200_000, 32)
        return base64.urlsafe_b64encode(raw)

def is_initialized() -> bool:
    c = _db()
    row = c.execute("SELECT value FROM vault_meta WHERE key='pw_hash'").fetchone()
    c.close()
    return bool(row)

def is_unlocked() -> bool:
    return _fernet is not None

def setup(master_password: str) -> dict:
    """First-time setup — set master password"""
    global _fernet
    if is_initialized():
        return {"ok": False, "error": "Vault already initialized. Use unlock()."}
    key    = _derive_key(master_password)
    pw_h   = hashlib.sha256(master_password.encode() + b"aria_vault").hexdigest()
    c = _db()
    c.execute("INSERT OR REPLACE INTO vault_meta VALUES (?,?)", ("pw_hash", pw_h))
    c.commit(); c.close()
    if HAS_FERNET:
        _fernet = Fernet(key)
    return {"ok": True, "msg": "Vault created. Save your master password — it cannot be recovered!"}

def unlock(master_password: str) -> dict:
    global _fernet
    if not is_initialized():
        return setup(master_password)
    pw_h  = hashlib.sha256(master_password.encode() + b"aria_vault").hexdigest()
    c = _db()
    row = c.execute("SELECT value FROM vault_meta WHERE key='pw_hash'").fetchone()
    c.close()
    if not row or row["value"] != pw_h:
        return {"ok": False, "error": "Wrong master password"}
    key = _derive_key(master_password)
    if HAS_FERNET:
        _fernet = Fernet(key)
    return {"ok": True, "msg": "Vault unlocked"}

def lock():
    global _fernet
    _fernet = None

def _encrypt(data: dict) -> bytes:
    raw = json.dumps(data).encode()
    if HAS_FERNET and _fernet:
        return _fernet.encrypt(raw)
    # XOR fallback
    import struct
    k = hashlib.sha256(b"aria_vault_fallback").digest()
    n = secrets.token_bytes(16)
    stream = hashlib.sha256(k + n).digest() * ((len(raw)//32)+1)
    ct = bytes(a^b for a,b in zip(raw, stream))
    return n + ct

def _decrypt(blob: bytes) -> Optional[dict]:
    try:
        if HAS_FERNET and _fernet:
            return json.loads(_fernet.decrypt(blob))
        # XOR fallback
        k = hashlib.sha256(b"aria_vault_fallback").digest()
        n, ct = blob[:16], blob[16:]
        stream = hashlib.sha256(k + n).digest() * ((len(ct)//32)+1)
        raw = bytes(a^b for a,b in zip(ct, stream))
        return json.loads(raw)
    except:
        return None

# CRUD
def add_secret(name: str, data: dict, category: str = "general",
               tags: str = "", notes: str = "") -> dict:
    if not is_unlocked():
        return {"ok": False, "error": "Vault locked — call unlock() first"}
    enc = _encrypt(data)
    now = time.time()
    with _LOCK:
        c = _db()
        cur = c.execute(
            "INSERT INTO secrets (category,name,enc_data,tags,created,updated,notes) VALUES (?,?,?,?,?,?,?)",
            (category, name, enc, tags, now, now, notes))
        sid = cur.lastrowid
        c.commit(); c.close()
    return {"ok": True, "id": sid}

def get_secret(sid: int) -> Optional[dict]:
    if not is_unlocked(): return None
    with _LOCK:
        c = _db()
        row = c.execute("SELECT * FROM secrets WHERE id=?", (sid,)).fetchone()
        c.close()
    if not row: return None
    data = _decrypt(row["enc_data"])
    return {"id": row["id"], "name": row["name"], "category": row["category"],
            "data": data, "tags": row["tags"], "notes": row["notes"],
            "created": row["created"], "updated": row["updated"]}

def list_secrets(category: str = None) -> list:
    """List secrets metadata (no decrypted data)"""
    with _LOCK:
        c = _db()
        if category:
            rows = c.execute("SELECT id,category,name,tags,notes,created,updated FROM secrets WHERE category=? ORDER BY name", (category,)).fetchall()
        else:
            rows = c.execute("SELECT id,category,name,tags,notes,created,updated FROM secrets ORDER BY category,name").fetchall()
        c.close()
    return [dict(r) for r in rows]

def update_secret(sid: int, data: dict = None, name: str = None,
                  notes: str = None) -> dict:
    if not is_unlocked(): return {"ok": False, "error": "Vault locked"}
    with _LOCK:
        c = _db()
        row = c.execute("SELECT * FROM secrets WHERE id=?", (sid,)).fetchone()
        if not row: return {"ok": False, "error": "Not found"}
        enc = _encrypt(data) if data else row["enc_data"]
        nm  = name  or row["name"]
        nt  = notes or row["notes"]
        c.execute("UPDATE secrets SET enc_data=?,name=?,notes=?,updated=? WHERE id=?",
                  (enc, nm, nt, time.time(), sid))
        c.commit(); c.close()
    return {"ok": True}

def delete_secret(sid: int) -> dict:
    with _LOCK:
        c = _db()
        c.execute("DELETE FROM secrets WHERE id=?", (sid,))
        c.commit(); c.close()
    return {"ok": True}

def categories() -> list:
    with _LOCK:
        c = _db()
        rows = c.execute("SELECT DISTINCT category FROM secrets").fetchall()
        c.close()
    return [r["category"] for r in rows]

def stats() -> dict:
    with _LOCK:
        c = _db()
        total = c.execute("SELECT COUNT(*) FROM secrets").fetchone()[0]
        cats  = c.execute("SELECT COUNT(DISTINCT category) FROM secrets").fetchone()[0]
        c.close()
    return {"total": total, "categories": cats, "unlocked": is_unlocked(),
            "initialized": is_initialized(), "has_fernet": HAS_FERNET}

init()
