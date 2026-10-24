"""Accounts and sessions for the web app.

- Passwords are hashed with Argon2id (argon2-cffi). Plain passwords are never stored or logged.
- A session is a random 256-bit token in an HttpOnly, SameSite=Lax cookie. Only its SHA-256
  is stored, so a leaked database can't be replayed as a login.
- CSRF: every state-changing request from a signed-in browser must send the session's CSRF token in
  `X-CSRF-Token`. Requests whose Origin doesn't match the host are refused, too.
- A demo account is seeded from DEMO_USER / DEMO_PASSWORD when both are set. Nothing is hardcoded.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .store import Store

COOKIE = "sc_session"
SESSION_DAYS = 14
MIN_PASSWORD = 10
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT, pw_hash TEXT NOT NULL, ts REAL,
  is_demo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, csrf TEXT NOT NULL, created REAL, expires REAL);
"""

_ph = PasswordHasher()  # argon2id, library defaults (t=3, m=64 MiB, p=4)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class User:
    id: int
    email: str
    name: str | None
    is_demo: bool


@dataclass
class Session:
    user: User
    csrf: str


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class Auth:
    def __init__(self, store: Store, enabled: bool = True, signup_open: bool = True):
        self.store, self.enabled, self.signup_open = store, enabled, signup_open
        with store.lock:
            store.db.executescript(SCHEMA)
            store.db.commit()
        self._fails: dict[str, list[float]] = {}

    # -- accounts -------------------------------------------------------------------------------
    def create_user(self, email: str, password: str, name: str | None = None, is_demo: bool = False) -> User:
        email = (email or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise AuthError(400, "Enter a valid email address.")
        if len(password or "") < MIN_PASSWORD:
            raise AuthError(400, f"Use at least {MIN_PASSWORD} characters for the password.")
        if self.store.query("SELECT 1 FROM users WHERE email=?", email):
            raise AuthError(409, "An account with that email already exists. Sign in instead.")
        uid = self.store.insert("users", email=email, name=(name or "").strip()[:80] or None,
                                pw_hash=_ph.hash(password), is_demo=int(is_demo))
        return User(uid, email, name, is_demo)

    def seed_demo(self) -> str | None:
        """Create or refresh the demo account from DEMO_USER / DEMO_PASSWORD (both required)."""
        email, pw = os.environ.get("DEMO_USER"), os.environ.get("DEMO_PASSWORD")
        if not email or not pw:
            return None
        email = email.strip().lower()
        rows = self.store.query("SELECT id, pw_hash FROM users WHERE email=?", email)
        if rows:
            if not self._verify(rows[0]["pw_hash"], pw):
                self.store.update("users", rows[0]["id"], pw_hash=_ph.hash(pw), is_demo=1)
        else:
            self.create_user(email, pw, "Demo", is_demo=True)
        return email

    @staticmethod
    def _verify(pw_hash: str, password: str) -> bool:
        try:
            return _ph.verify(pw_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def _throttled(self, key: str) -> bool:
        now = time.time()
        recent = [t for t in self._fails.get(key, []) if now - t < 600]
        self._fails[key] = recent
        return len(recent) >= 8

    def login(self, email: str, password: str, client: str = "") -> tuple[str, Session]:
        email = (email or "").strip().lower()
        key = f"{client}|{email}"
        if self._throttled(key):
            raise AuthError(429, "Too many attempts. Wait 10 minutes and try again.")
        rows = self.store.query("SELECT * FROM users WHERE email=?", email)
        # Verify against a dummy hash when the user doesn't exist, so timing doesn't reveal accounts.
        ok = self._verify(rows[0]["pw_hash"] if rows else _DUMMY, password or "")
        if not rows or not ok:
            self._fails.setdefault(key, []).append(time.time())
            raise AuthError(401, "That email and password don't match an account.")
        self._fails.pop(key, None)
        r = rows[0]
        if _ph.check_needs_rehash(r["pw_hash"]):
            self.store.update("users", r["id"], pw_hash=_ph.hash(password))
        return self._new_session(User(r["id"], r["email"], r["name"], bool(r["is_demo"])))

    def _new_session(self, user: User) -> tuple[str, Session]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        now = time.time()
        self.store.execute("DELETE FROM sessions WHERE expires < ?", now)
        self.store.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", _sha(token), user.id, csrf, now,
                           now + SESSION_DAYS * 86400)
        return token, Session(user, csrf)

    def session(self, token: str | None) -> Session | None:
        if not token:
            return None
        rows = self.store.query(
            "SELECT s.csrf, s.expires, u.id, u.email, u.name, u.is_demo FROM sessions s JOIN users u "
            "ON u.id = s.user_id WHERE s.token_hash=?", _sha(token))
        if not rows or rows[0]["expires"] < time.time():
            return None
        r = rows[0]
        return Session(User(r["id"], r["email"], r["name"], bool(r["is_demo"])), r["csrf"])

    def logout(self, token: str | None) -> None:
        if token:
            self.store.execute("DELETE FROM sessions WHERE token_hash=?", _sha(token))

    @staticmethod
    def csrf_ok(session: Session, header: str | None) -> bool:
        return bool(header) and hmac.compare_digest(session.csrf, header)


_DUMMY = _ph.hash(secrets.token_urlsafe(16))
