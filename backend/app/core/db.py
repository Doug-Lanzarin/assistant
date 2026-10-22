"""Acesso ao SQLite com migrações versionadas.

Uma única conexão serializada por ``RLock`` — adequado para um assistente de um
usuário e evita "database is locked". WAL habilitado para leituras concorrentes
pelo backup online.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def from_json(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._in_tx = 0

    # -- primitivas ---------------------------------------------------------
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, seq: list[tuple]) -> None:
        with self._lock:
            self._conn.executemany(sql, seq)

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def scalar(self, sql: str, params: tuple | dict = ()) -> Any:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return row[0] if row else None

    def insert(self, sql: str, params: tuple | dict = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return int(cur.lastrowid or 0)

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        with self._lock:
            outer = self._in_tx == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            else:
                self._conn.execute(f"SAVEPOINT sp{self._in_tx}")
            self._in_tx += 1
            try:
                yield self
            except BaseException:
                self._in_tx -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                else:
                    self._conn.execute(f"ROLLBACK TO sp{self._in_tx}")
                    self._conn.execute(f"RELEASE sp{self._in_tx}")
                raise
            else:
                self._in_tx -= 1
                if outer:
                    self._conn.execute("COMMIT")
                else:
                    self._conn.execute(f"RELEASE sp{self._in_tx}")

    # -- migrações ----------------------------------------------------------
    def migrate(self) -> list[str]:
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {r["version"] for r in self.query("SELECT version FROM schema_migrations")}
            done: list[str] = []
            for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = f.stem
                if version in applied:
                    continue
                sql = f.read_text(encoding="utf-8")
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in _split_sql(sql):
                        self._conn.execute(stmt)
                    self._conn.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, utcnow()),
                    )
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise
                done.append(version)
            return done

    def backup_to(self, dest: Path) -> None:
        """Backup online consistente (API de backup do SQLite)."""
        with self._lock:
            target = sqlite3.connect(str(dest))
            try:
                self._conn.backup(target)
            finally:
                target.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _split_sql(sql: str) -> list[str]:
    """Divide o script em instruções completas (lida com BEGIN...END de triggers)."""
    statements: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        if line.strip().startswith("--") and not buf.strip():
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                statements.append(buf.strip())
            buf = ""
    if buf.strip():
        statements.append(buf.strip())
    return statements
