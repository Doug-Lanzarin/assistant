"""Autenticação do painel: senha com scrypt e tokens de sessão opacos.

Somente o hash SHA-256 do token é guardado no banco, então um vazamento do
banco não permite sequestrar sessões.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from app.core.db import Database, utcnow

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, dk_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(dk_b64)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return hmac.compare_digest(dk, expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    MIN_PASSWORD = 8

    def __init__(self, db: Database, ttl_hours: int = 168):
        self.db = db
        self.ttl = timedelta(hours=ttl_hours)

    def has_user(self) -> bool:
        return bool(self.db.scalar("SELECT COUNT(*) FROM users"))

    def create_user(self, username: str, password: str) -> int:
        if len(password) < self.MIN_PASSWORD:
            raise ValueError(f"A senha precisa ter pelo menos {self.MIN_PASSWORD} caracteres.")
        if not username.strip():
            raise ValueError("Nome de usuário obrigatório.")
        return self.db.insert(
            "INSERT INTO users(username, password_hash, created_at) VALUES (?,?,?)",
            (username.strip(), hash_password(password), utcnow()),
        )

    def change_password(self, user_id: int, old: str, new: str) -> None:
        row = self.db.query_one("SELECT password_hash FROM users WHERE id=?", (user_id,))
        if not row or not verify_password(old, row["password_hash"]):
            raise PermissionError("Senha atual incorreta.")
        if len(new) < self.MIN_PASSWORD:
            raise ValueError(f"A senha precisa ter pelo menos {self.MIN_PASSWORD} caracteres.")
        self.db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), user_id))
        self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def login(self, username: str, password: str, user_agent: str | None = None) -> str | None:
        row = self.db.query_one(
            "SELECT id, password_hash FROM users WHERE username=?", (username.strip(),)
        )
        if not row or not verify_password(password, row["password_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        self.db.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, user_agent)"
            " VALUES (?,?,?,?,?)",
            (
                _token_hash(token),
                row["id"],
                now.isoformat(timespec="seconds"),
                (now + self.ttl).isoformat(timespec="seconds"),
                (user_agent or "")[:200],
            ),
        )
        return token

    def validate(self, token: str | None) -> dict | None:
        if not token:
            return None
        row = self.db.query_one(
            "SELECT s.user_id, s.expires_at, u.username FROM sessions s"
            " JOIN users u ON u.id = s.user_id WHERE s.token_hash=?",
            (_token_hash(token),),
        )
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(UTC):
            self.logout(token)
            return None
        return {"id": row["user_id"], "username": row["username"]}

    def logout(self, token: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))

    def purge_expired(self) -> int:
        cur = self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (utcnow(),))
        return cur.rowcount
