"""Ações no desktop: abrir apps/URLs/arquivos, executar comandos aprovados, notificações.

Defesa em profundidade: mesmo que o backend seja comprometido, o agente:
* nunca usa ``shell=True``;
* rejeita metacaracteres de shell no executável;
* só abre URLs http/https;
* só abre caminhos existentes.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

log = logging.getLogger("jarvis_agent.actions")

_BAD = re.compile(r"[;&|<>`$\n\r]")
_URL = re.compile(r"^https?://[^\s\"'<>]+$", re.I)


class ActionError(RuntimeError):
    pass


def _resolve_exe(command: str) -> str:
    if not command or _BAD.search(command):
        raise ActionError("Executável inválido")
    expanded = os.path.expandvars(os.path.expanduser(command))
    if Path(expanded).is_file():
        return expanded
    found = shutil.which(expanded)
    if found:
        return found
    raise ActionError(f"Executável não encontrado: {command}")


def _check_args(args: list[Any]) -> list[str]:
    if not isinstance(args, list) or len(args) > 50:
        raise ActionError("Argumentos inválidos")
    out = []
    for a in args:
        if not isinstance(a, str) or "\x00" in a or len(a) > 2000:
            raise ActionError("Argumento inválido")
        out.append(os.path.expandvars(a))
    return out


def launch(command: str, args: list[str] | None = None) -> dict[str, Any]:
    exe = _resolve_exe(command)
    argv = [exe, *_check_args(args or [])]
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                              "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    p = subprocess.Popen(argv, shell=False, **kwargs)  # noqa: S603 - argv validado, sem shell
    return {"ok": True, "pid": p.pid}


def open_url(url: str) -> dict[str, Any]:
    if not _URL.match(url or ""):
        raise ActionError("Somente URLs http/https são permitidas")
    return {"ok": bool(webbrowser.open(url, new=2))}


def open_path(path: str) -> dict[str, Any]:
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.exists():
        raise ActionError(f"Caminho não existe: {path}")
    if sys.platform == "win32":
        os.startfile(str(p))  # type: ignore[attr-defined]  # noqa: S606 - abre com o app associado
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603,S607
    else:
        raise ActionError("Sem programa para abrir arquivos neste sistema")
    return {"ok": True}


def run_process(executable: str, args: list[str] | None, cwd: str | None, timeout: float) -> dict[str, Any]:
    exe = _resolve_exe(executable)
    argv = [exe, *_check_args(args or [])]
    if cwd:
        cwd = os.path.expandvars(os.path.expanduser(cwd))
        if not Path(cwd).is_dir():
            raise ActionError(f"Diretório de trabalho não existe: {cwd}")
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=min(float(timeout), 1800), shell=False,  # noqa: S603
                           check=False, **kwargs)
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"tempo limite de {timeout}s excedido"}
    dec = lambda b: b.decode("utf-8", errors="replace")[-20000:]  # noqa: E731
    return {"returncode": r.returncode, "stdout": dec(r.stdout), "stderr": dec(r.stderr)}


class Notifier:
    """Notificações: usa o ícone da bandeja (pystray) quando disponível; senão, log."""

    def __init__(self) -> None:
        self.tray = None

    def notify(self, title: str, message: str) -> dict[str, Any]:
        title, message = str(title)[:80], str(message)[:500]
        if self.tray is not None:
            try:
                self.tray.notify(message, title)
                return {"ok": True, "via": "tray"}
            except Exception as e:  # noqa: BLE001
                log.warning("Falha na notificação da bandeja: %s", e)
        if sys.platform == "win32":
            try:
                from win11toast import notify  # type: ignore[import-not-found]

                notify(title, message)
                return {"ok": True, "via": "toast"}
            except ImportError:
                pass
        log.info("NOTIFICAÇÃO: %s — %s", title, message)
        return {"ok": True, "via": "log"}
