"""Acesso controlado a arquivos: somente dentro dos diretórios permitidos."""

from __future__ import annotations

import fnmatch
import os
import time
from pathlib import Path

from app.orchestrator.textnorm import fold

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "$Recycle.Bin", "AppData", ".cache"}


class FileAccessError(PermissionError):
    pass


class FileGuard:
    def __init__(self, allowed_dirs: list[str]):
        self.roots = [Path(d).expanduser().resolve() for d in allowed_dirs if d]

    def check(self, path: str | Path) -> Path:
        p = Path(path).expanduser()
        try:
            resolved = p.resolve(strict=False)
        except (OSError, RuntimeError) as e:
            raise FileAccessError(f"Caminho inválido: {path}") from e
        for root in self.roots:
            if resolved == root or root in resolved.parents:
                return resolved
        raise FileAccessError(
            f"Acesso negado: '{path}' está fora dos diretórios permitidos. "
            "Adicione a pasta em config/jarvis.toml (allowed_dirs) se quiser liberar."
        )

    def search(self, query: str, limit: int = 25, max_seconds: float = 4.0) -> list[dict]:
        if not self.roots:
            raise FileAccessError("Nenhum diretório permitido configurado (allowed_dirs em config/jarvis.toml).")
        q = fold(query).strip()
        pattern = q if any(c in q for c in "*?") else None
        words = [w for w in q.replace("*", " ").split() if w]
        results: list[dict] = []
        deadline = time.monotonic() + max_seconds
        for root in self.roots:
            if not root.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
                for name in filenames + dirnames:
                    fname = fold(name)
                    ok = fnmatch.fnmatch(fname, pattern) if pattern else all(w in fname for w in words)
                    if ok:
                        full = Path(dirpath) / name
                        try:
                            st = full.stat()
                        except OSError:
                            continue
                        results.append({"path": str(full), "name": name, "is_dir": full.is_dir(),
                                        "size": st.st_size, "modified": st.st_mtime})
                        if len(results) >= limit:
                            return results
                if time.monotonic() > deadline:
                    return results
        results.sort(key=lambda r: -r["modified"])
        return results
