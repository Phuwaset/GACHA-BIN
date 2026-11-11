"""Security helpers: PIN hashing and in-memory bearer tokens."""
import hashlib
import secrets
import threading
import time
from typing import Optional

_PBKDF2_ROUNDS = 120_000


def hash_pin(pin: str) -> str:
    """Return 'salt$hash' using PBKDF2-SHA256 (stdlib only)."""
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), _PBKDF2_ROUNDS).hex()
    return f"{salt}${digest}"


def verify_pin(pin: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, digest = stored.split("$", 1)
    candidate = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), _PBKDF2_ROUNDS).hex()
    return secrets.compare_digest(candidate, digest)


class TokenStore:
    """Maps opaque bearer tokens to (key_id, role) with expiry."""

    # shortcut: in-memory tokens are lost on restart (users just log in again); move to DB if multi-worker.
    def __init__(self) -> None:
        self._tokens: dict[str, dict] = {}
        self._lock = threading.Lock()

    def issue(self, key_id: str, role: str, ttl_sec: int) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            now = time.time()
            self._tokens = {t: v for t, v in self._tokens.items() if v["expires"] > now}
            self._tokens[token] = {"key_id": key_id, "role": role, "expires": now + ttl_sec}
        return token

    def resolve(self, token: str) -> Optional[dict]:
        with self._lock:
            entry = self._tokens.get(token)
            if not entry or entry["expires"] < time.time():
                self._tokens.pop(token, None)
                return None
            return dict(entry)

    def revoke(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token, None)


class AttemptLimiter:
    """Locks a key for lock_sec after max_fail consecutive failures (PIN brute-force guard)."""

    def __init__(self, max_fail: int = 5, lock_sec: int = 60) -> None:
        self.max_fail = max_fail
        self.lock_sec = lock_sec
        self._state: dict[str, dict] = {}
        self._lock = threading.Lock()

    def locked_for(self, key: str) -> int:
        with self._lock:
            s = self._state.get(key)
            if s and s["until"] > time.time():
                return int(s["until"] - time.time()) + 1
            return 0

    def fail(self, key: str) -> None:
        with self._lock:
            s = self._state.setdefault(key, {"count": 0, "until": 0.0})
            s["count"] += 1
            if s["count"] >= self.max_fail:
                s["until"] = time.time() + self.lock_sec
                s["count"] = 0

    def success(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)


tokens = TokenStore()
pin_limiter = AttemptLimiter()
