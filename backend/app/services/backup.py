"""Backup e restauração.

O arquivo de backup (.zip) contém:
* ``jarvis.db`` — cópia consistente via API de backup do SQLite;
* ``library/`` — documentos importados;
* ``manifest.json`` — versão, data e contagens.

Segredos NÃO entram no backup por padrão (a chave-mestra é protegida por
DPAPI e vinculada à conta do Windows). Itens sensíveis do clipboard ficam
cifrados dentro do banco; para restaurá-los em outra máquina, exporte a
chave manualmente (veja docs/BACKUP.md).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from app.core.db import utcnow

TABLES_COUNTED = ["memories", "documents", "clipboard_items", "tasks", "reminders", "projects", "conversations", "messages"]


class BackupError(RuntimeError):
    pass


def create_backup(services, dest_dir: Path | None = None) -> Path:
    env = services.env
    dest_dir = dest_dir or env.backups_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = dest_dir / f"jarvis-backup-{stamp}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "jarvis.db"
        services.db.backup_to(db_copy)
        counts = {}
        con = sqlite3.connect(db_copy)
        try:
            for t in TABLES_COUNTED:
                counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            version = [r[0] for r in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
        finally:
            con.close()
        manifest = {"app": "jarvis", "format": 1, "created_at": utcnow(), "schema": version, "counts": counts,
                    "includes_secrets": False}
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(db_copy, "jarvis.db")
            z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            if env.library_dir.exists():
                for f in env.library_dir.rglob("*"):
                    if f.is_file():
                        z.write(f, "library/" + f.relative_to(env.library_dir).as_posix())
    return out


def inspect_backup(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "manifest.json" not in names or "jarvis.db" not in names:
                raise BackupError("Arquivo não é um backup do JARVIS (manifest/jarvis.db ausentes).")
            for n in names:
                if n.startswith("/") or ".." in Path(n).parts:
                    raise BackupError(f"Caminho suspeito no backup: {n}")
            manifest = json.loads(z.read("manifest.json"))
    except zipfile.BadZipFile as e:
        raise BackupError("Arquivo corrompido ou não é ZIP.") from e
    if manifest.get("app") != "jarvis":
        raise BackupError("Manifesto inválido.")
    return manifest


def restore_backup(services, path: Path) -> dict:
    """Restaura substituindo o banco atual. Faz um backup de segurança antes."""
    manifest = inspect_backup(path)
    safety = create_backup(services, services.env.backups_dir / "pre-restore")
    env = services.env
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        new_db = Path(tmp) / "jarvis.db"
        con = sqlite3.connect(new_db)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            con.close()
        if ok != "ok":
            raise BackupError(f"Banco do backup falhou na verificação de integridade: {ok}")
        # Copia o conteúdo do backup para o banco em uso (mantém a mesma conexão).
        src = sqlite3.connect(new_db)
        try:
            with services.db._lock:  # noqa: SLF001 - operação administrativa
                src.backup(services.db._conn)  # noqa: SLF001
        finally:
            src.close()
        lib_src = Path(tmp) / "library"
        if lib_src.exists():
            env.library_dir.mkdir(parents=True, exist_ok=True)
            for f in lib_src.rglob("*"):
                if f.is_file():
                    target = env.library_dir / f.relative_to(lib_src)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)
    services.db.migrate()
    services.indexer.invalidate()
    return {"restored": manifest, "safety_backup": str(safety)}


def list_backups(services) -> list[dict]:
    d = services.env.backups_dir
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("jarvis-backup-*.zip"), reverse=True):
        out.append({"name": f.name, "size": f.stat().st_size, "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()})
    return out
