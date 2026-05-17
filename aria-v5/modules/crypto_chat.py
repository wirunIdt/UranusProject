"""
modules/crypto_chat.py — End-to-End Encrypted Mesh Chat
Uses Fernet (AES-128-CBC + HMAC-SHA256) — symmetric key exchange via QR/passphrase
Pure Python, no extra deps (cryptography lib bundled with pip)
"""
import os, json, time, base64, hashlib, secrets, logging
from typing import Optional

log = logging.getLogger("ARIA.CryptoChat")

# Try cryptography lib first, fallback to XOR+HMAC
try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False
    log.warning("cryptography not installed — using fallback XOR encryption. Run: pip install cryptography")

import hmac as _hmac_mod
import struct

SALT_FILE = os.environ.get("CRYPTO_SALT", ".aria_chat_salt")
KEY_FILE  = os.environ.get("CRYPTO_KEY",  ".aria_chat.key")

# ── Key Management ─────────────────────────────────────────────────────────
def _load_or_create_salt() -> bytes:
    if os.path.exists(SALT_FILE):
        return open(SALT_FILE, "rb").read()
    salt = secrets.token_bytes(16)
    open(SALT_FILE, "wb").write(salt)
    return salt

def derive_key_from_passphrase(passphrase: str) -> bytes:
    """Derive a 32-byte key from a shared passphrase using PBKDF2"""
    salt = _load_or_create_salt()
    if _HAS_CRYPTO:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100_000)
        return kdf.derive(passphrase.encode())
    else:
        # Pure-Python PBKDF2 using hashlib
        return hashlib.pbkdf2_hmac('sha256', passphrase.encode(), salt, 100_000, dklen=32)

def generate_key() -> str:
    """Generate a random shared key (base64 URL-safe)"""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()

def save_key(key_b64: str):
    open(KEY_FILE, "w").write(key_b64)

def load_key() -> Optional[str]:
    if os.path.exists(KEY_FILE):
        return open(KEY_FILE).read().strip()
    return None

def key_fingerprint(key_b64: str) -> str:
    """Short fingerprint to verify both parties have same key"""
    raw = base64.urlsafe_b64decode(key_b64 + "==")
    h = hashlib.sha256(raw).hexdigest()
    return f"{h[:4].upper()}-{h[4:8].upper()}-{h[8:12].upper()}"

# ── Encryption ─────────────────────────────────────────────────────────────
class E2EChat:
    def __init__(self, key_b64: str):
        raw = base64.urlsafe_b64decode(key_b64 + "==")
        self._key = raw[:32]
        if _HAS_CRYPTO:
            # Fernet requires 32-byte key encoded as url-safe base64
            fk = base64.urlsafe_b64encode(self._key)
            self._fernet = Fernet(fk)
        self._has_crypto = _HAS_CRYPTO
        self.fingerprint = key_fingerprint(key_b64)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt message → base64 ciphertext"""
        data = plaintext.encode("utf-8")
        if self._has_crypto:
            ct = self._fernet.encrypt(data)
            return base64.urlsafe_b64encode(ct).decode()
        else:
            return self._xor_encrypt(data)

    def decrypt(self, ciphertext: str) -> Optional[str]:
        """Decrypt base64 ciphertext → plaintext, None if invalid"""
        try:
            raw = base64.urlsafe_b64decode(ciphertext + "==")
            if self._has_crypto:
                pt = self._fernet.decrypt(raw)
                return pt.decode("utf-8")
            else:
                return self._xor_decrypt(raw)
        except Exception:
            return None

    def _xor_encrypt(self, data: bytes) -> str:
        """XOR + HMAC fallback (simpler, still authenticated)"""
        nonce = secrets.token_bytes(16)
        # Expand key with nonce using PBKDF2
        stream_key = hashlib.pbkdf2_hmac('sha256', self._key, nonce, 1, dklen=len(data))
        ct = bytes(a ^ b for a, b in zip(data, stream_key))
        # HMAC for authentication
        mac = _hmac_mod.new(self._key, nonce + ct, hashlib.sha256).digest()
        payload = nonce + mac + ct
        return base64.urlsafe_b64encode(payload).decode()

    def _xor_decrypt(self, raw: bytes) -> Optional[str]:
        nonce = raw[:16]
        mac   = raw[16:48]
        ct    = raw[48:]
        # Verify HMAC
        expected_mac = _hmac_mod.new(self._key, nonce + ct, hashlib.sha256).digest()
        if not _hmac_mod.compare_digest(mac, expected_mac):
            return None  # Tampered!
        stream_key = hashlib.pbkdf2_hmac('sha256', self._key, nonce, 1, dklen=len(ct))
        pt = bytes(a ^ b for a, b in zip(ct, stream_key))
        return pt.decode("utf-8")

    def wrap_message(self, sender: str, content: str,
                     msg_type: str = "chat") -> dict:
        """Create encrypted message envelope"""
        payload = json.dumps({
            "sender":  sender,
            "content": content,
            "type":    msg_type,
            "ts":      time.time(),
        })
        return {
            "enc":  self.encrypt(payload),
            "fp":   self.fingerprint,
            "v":    "1",
        }

    def unwrap_message(self, envelope: dict) -> Optional[dict]:
        """Decrypt message envelope"""
        if envelope.get("fp") != self.fingerprint:
            log.warning("Fingerprint mismatch — different key?")
            return None
        pt = self.decrypt(envelope.get("enc", ""))
        if pt is None:
            return None
        try:
            return json.loads(pt)
        except:
            return None


# ── Session store (in-memory) ──────────────────────────────────────────────
_sessions: dict[str, E2EChat] = {}

def create_session(room: str, key_b64: str) -> str:
    """Create/join an encrypted chat room"""
    _sessions[room] = E2EChat(key_b64)
    fp = _sessions[room].fingerprint
    log.info(f"Crypto session created: room='{room}' fp={fp}")
    return fp

def get_session(room: str) -> Optional[E2EChat]:
    return _sessions.get(room)

def list_sessions() -> list[dict]:
    return [{"room": r, "fingerprint": s.fingerprint} for r, s in _sessions.items()]

def close_session(room: str):
    _sessions.pop(room, None)


# ── QR code helper (for key sharing) ──────────────────────────────────────
def key_qr_text(key_b64: str, room: str = "aria") -> str:
    """Return text to encode as QR for key sharing"""
    return f"aria://chat?room={room}&key={key_b64}"


# ── Convenience functions ──────────────────────────────────────────────────
def quick_setup(passphrase: str = None) -> dict:
    """Quick setup: generate or derive key, save, return info"""
    if passphrase:
        raw = derive_key_from_passphrase(passphrase)
        key_b64 = base64.urlsafe_b64encode(raw).decode()
    else:
        key_b64 = generate_key()

    save_key(key_b64)
    fp = key_fingerprint(key_b64)
    qr = key_qr_text(key_b64)
    return {
        "key":         key_b64,
        "fingerprint": fp,
        "qr_text":     qr,
        "method":      "passphrase" if passphrase else "random",
        "library":     "cryptography (Fernet)" if _HAS_CRYPTO else "XOR+HMAC (fallback)",
        "tip":         "Share fingerprint with peer to verify same key",
    }
