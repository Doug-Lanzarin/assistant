#!/usr/bin/env python3
"""Controle do JARVIS: iniciar, parar, reiniciar, status, diagnóstico, testes e backup.

Uso (a partir da raiz do repositório):
  python scripts/jarvisctl.py start [--dev] [--no-agent] [--whatsapp-web]
  python scripts/jarvisctl.py stop | restart | status | doctor | test
  python scripts/jarvisctl.py backup | restore ARQUIVO.zip
  python scripts/jarvisctl.py autostart enable|disable|status
  python scripts/jarvisctl.py env-report

O comando ``start`` sobe um SUPERVISOR em segundo plano que mantém o backend
(uvicorn) e o agente local vivos: reinicia após falha (com espera crescente)
ou após um pedido de reinício controlado (código de saída 3), impede
instâncias duplicadas e encerra os filhos de forma limpa no ``stop``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
WIN = sys.platform == "win32"
VENV_PY = BACKEND / ".venv" / ("Scripts/python.exe" if WIN else "bin/python")
VENV_PYW = BACKEND / ".venv" / "Scripts" / "pythonw.exe"
RESTART_CODE = 3


def data_dir() -> Path:
    return Path(os.environ.get("JARVIS_DATA_DIR", REPO / "data"))


def port() -> int:
    return int(os.environ.get("JARVIS_PORT", "8765"))


def host() -> str:
    return os.environ.get("JARVIS_HOST", "127.0.0.1")


def pid_file() -> Path:
    return data_dir() / "jarvis.pid"


def stop_flag() -> Path:
    return data_dir() / "stop.flag"


def python() -> str:
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        (data_dir() / "logs").mkdir(parents=True, exist_ok=True)
        with open(data_dir() / "logs" / "supervisor.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if WIN:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid() -> int | None:
    try:
        pid = int(pid_file().read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def health(timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port()}/api/health", timeout=timeout) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def port_in_use(p: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", p)) == 0


# --------------------------------------------------------------------------- supervisor
def _spawn(cmd: list[str], env: dict) -> subprocess.Popen:
    kw: dict = {"cwd": str(BACKEND), "env": env}
    if WIN:
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return subprocess.Popen(cmd, **kw)


def _terminate(p: subprocess.Popen | None, name: str, grace: float = 10.0) -> None:
    if p is None or p.poll() is not None:
        return
    log(f"Encerrando {name} (pid {p.pid})")
    try:
        if WIN:
            p.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        else:
            p.terminate()
        p.wait(timeout=grace)
    except (subprocess.TimeoutExpired, OSError):
        log(f"{name} não encerrou a tempo; forçando")
        p.kill()


def supervise(args: argparse.Namespace) -> int:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    existing = read_pid()
    if existing and existing != os.getpid():
        log(f"Supervisor já em execução (pid {existing})")
        return 2
    pid_file().write_text(str(os.getpid()))
    stop_flag().unlink(missing_ok=True)
    env = dict(os.environ)
    env.setdefault("JARVIS_ENV", "development" if args.dev else "production")
    env["PYTHONPATH"] = str(BACKEND)
    backend_cmd = [python(), "-m", "uvicorn", "app.main:create_app", "--factory", "--host", host(), "--port", str(port()),
                   "--log-level", "warning"]
    if args.dev:
        backend_cmd.append("--reload")
    agent_cmd = [python(), "-m", "jarvis_agent", "--backend", f"ws://127.0.0.1:{port()}/api/agent/ws", "--data-dir", str(d)]
    if args.whatsapp_web:
        agent_cmd.append("--whatsapp-web")
    agent_env = dict(env)
    agent_env["PYTHONPATH"] = os.pathsep.join([str(REPO / "desktop"), str(BACKEND)])

    backend = agent = None
    failures = 0
    stopping = False

    def on_signal(signum, frame):  # noqa: ARG001
        nonlocal stopping
        stopping = True

    for sig in (signal.SIGINT, signal.SIGTERM) + ((signal.SIGBREAK,) if WIN else ()):  # type: ignore[attr-defined]
        try:
            signal.signal(sig, on_signal)
        except (OSError, ValueError):
            pass

    log(f"Supervisor iniciado (pid {os.getpid()}), backend em http://{host()}:{port()}")
    try:
        while not stopping and not stop_flag().exists():
            if backend is None or backend.poll() is not None:
                if backend is not None:
                    code = backend.returncode
                    if code == RESTART_CODE:
                        log("Reinício controlado solicitado pelo backend")
                        failures = 0
                    else:
                        failures += 1
                        wait = min(60, 2 ** min(failures, 6))
                        log(f"Backend saiu com código {code}; reiniciando em {wait}s (falha {failures})")
                        for _ in range(wait * 2):
                            if stop_flag().exists() or stopping:
                                break
                            time.sleep(0.5)
                        if stop_flag().exists() or stopping:
                            break
                if port_in_use(port()) and health() is None:
                    log(f"Porta {port()} ocupada por outro programa; aguardando")
                    time.sleep(5)
                    continue
                backend = _spawn(backend_cmd, env)
                log(f"Backend iniciado (pid {backend.pid})")
                for _ in range(60):
                    if health():
                        break
                    if backend.poll() is not None:
                        break
                    time.sleep(0.5)
                if health():
                    failures = 0
            if not args.no_agent and (agent is None or agent.poll() is not None) and health():
                if agent is not None:
                    log(f"Agente saiu com código {agent.returncode}; reiniciando")
                    time.sleep(3)
                agent = _spawn(agent_cmd, agent_env)
                log(f"Agente iniciado (pid {agent.pid})")
            time.sleep(1)
    finally:
        _terminate(agent, "agente")
        _terminate(backend, "backend")
        pid_file().unlink(missing_ok=True)
        stop_flag().unlink(missing_ok=True)
        log("Supervisor encerrado")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    if read_pid():
        print(f"O JARVIS já está em execução (pid {read_pid()}).")
        return 0
    if args.foreground:
        return supervise(args)
    cmd = [str(VENV_PYW) if WIN and VENV_PYW.exists() else python(), str(Path(__file__).resolve()), "start", "--foreground"]
    for flag in ("dev", "no_agent", "whatsapp_web"):
        if getattr(args, flag):
            cmd.append("--" + flag.replace("_", "-"))
    kw: dict = {"cwd": str(REPO), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if WIN:
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)
    for _ in range(80):
        if health():
            print(f"JARVIS no ar: http://127.0.0.1:{port()}/")
            return 0
        time.sleep(0.5)
    print("O supervisor foi iniciado, mas o backend ainda não respondeu. Veja data/logs/supervisor.log e jarvis.log.")
    return 1


def cmd_stop(args: argparse.Namespace) -> int:
    pid = read_pid()
    if not pid:
        print("O JARVIS não está em execução.")
        return 0
    data_dir().mkdir(parents=True, exist_ok=True)
    stop_flag().write_text("stop")
    for _ in range(60):
        if not pid_alive(pid):
            print("JARVIS encerrado.")
            return 0
        time.sleep(0.5)
    print("O supervisor não encerrou em 30 s; finalizando processo.")
    if WIN:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
    else:
        os.kill(pid, signal.SIGTERM)
    return 1


def cmd_restart(args: argparse.Namespace) -> int:
    cmd_stop(args)
    time.sleep(1)
    return cmd_start(args)


def cmd_status(args: argparse.Namespace) -> int:
    pid = read_pid()
    h = health()
    print("Supervisor: " + (f"em execução (pid {pid})" if pid else "parado"))
    print(f"Backend:    {'ok ' + json.dumps(h) if h else 'sem resposta'} em http://127.0.0.1:{port()}/")
    return 0 if h else 1


# --------------------------------------------------------------------------- diagnóstico
def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True

    def check(label: str, cond: bool, fix: str = "") -> None:
        nonlocal ok
        print(f"[{'OK' if cond else 'FALHA'}] {label}" + ("" if cond or not fix else f"\n        → {fix}"))
        ok = ok and cond

    def info(label: str, cond: bool, note: str) -> None:
        print(f"[{'OK' if cond else 'OPCIONAL'}] {label}" + ("" if cond else f" — {note}"))

    print(f"Sistema: {sys.platform} · Python {sys.version.split()[0]}")
    check("Python 3.11+", sys.version_info >= (3, 11), "instale Python 3.11 ou superior (python.org)")
    check("Ambiente virtual do backend", VENV_PY.exists(), "rode scripts\\install.ps1")
    py = python()
    code = ("import fastapi, pydantic, httpx, numpy, cryptography, psutil, anthropic, websockets, pypdf, docx; print('ok')")
    r = subprocess.run([py, "-c", code], capture_output=True, text=True, check=False)
    check("Dependências do backend", r.returncode == 0, "pip install -r backend/requirements.txt  " + r.stderr.strip()[-200:])
    check("Frontend compilado", (REPO / "frontend" / "dist" / "index.html").exists(), "cd frontend && npm ci && npm run build")
    cfg = REPO / "config" / "jarvis.toml"
    info("config/jarvis.toml", cfg.exists(), "usando config/jarvis.example.toml; copie e ajuste os caminhos")
    info("Node.js (apenas para compilar o frontend)", shutil.which("node") is not None, "necessário só para npm run build")
    for mod, label, note in [
        ("faster_whisper", "Transcrição local (faster-whisper)", "pip install -r backend/requirements-voice.txt"),
        ("sounddevice", "Microfone (sounddevice)", "pip install -r backend/requirements-voice.txt"),
        ("openwakeword", "Palavra de ativação (openWakeWord)", "pip install -r backend/requirements-voice.txt"),
        ("piper", "Voz Piper", "opcional; o navegador e o SAPI também falam"),
        ("pystray", "Ícone na bandeja", "pip install -r backend/requirements-desktop.txt"),
        ("playwright", "WhatsApp Web (Playwright)", "pip install -r backend/requirements-whatsapp.txt && python -m playwright install chromium"),
    ]:
        rr = subprocess.run([py, "-c", f"import {mod}"], capture_output=True, check=False)
        info(label, rr.returncode == 0, note)
    if shutil.which("ollama"):
        info("Ollama instalado", True, "")
    else:
        info("Ollama (IA local)", False, "opcional: https://ollama.com — ex.: ollama pull qwen2.5:3b")
    d = data_dir()
    check(f"Diretório de dados gravável ({d})", _writable(d), "verifique permissões")
    dbp = d / "jarvis.db"
    if dbp.exists():
        import sqlite3

        con = sqlite3.connect(dbp)
        try:
            res = con.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            con.close()
        check("Integridade do banco", res == "ok", f"resultado: {res}; restaure um backup")
    free = shutil.disk_usage(d).free / 1e9
    check(f"Espaço livre em disco ({free:.1f} GB)", free > 1, "libere espaço")
    h = health()
    info("Backend respondendo", h is not None, "inicie com scripts\\start.ps1")
    if port_in_use(port()) and not h:
        check(f"Porta {port()} livre", False, "outro programa está usando a porta; defina JARVIS_PORT")
    print("\nResultado:", "tudo certo para executar." if ok else "há itens obrigatórios a corrigir.")
    return 0 if ok else 1


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        t = d / ".write-test"
        t.write_text("x")
        t.unlink()
        return True
    except OSError:
        return False


def cmd_test(args: argparse.Namespace) -> int:
    rc = subprocess.run([python(), "-m", "pytest", "-q"], cwd=BACKEND, check=False).returncode
    if shutil.which("npm") and (REPO / "frontend" / "node_modules").exists():
        rc |= subprocess.run(["npm", "test"], cwd=REPO / "frontend", check=False, shell=WIN).returncode
    return rc


def _offline_services():
    sys.path.insert(0, str(BACKEND))
    from app.core.config import Settings
    from app.services.container import build_services

    return build_services(Settings())


def cmd_backup(args: argparse.Namespace) -> int:
    s = _offline_services()
    from app.services.backup import create_backup

    out = create_backup(s)
    print(f"Backup criado: {out}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    if read_pid():
        print("Pare o JARVIS antes de restaurar (scripts\\stop.ps1).")
        return 1
    s = _offline_services()
    from app.services.backup import restore_backup

    res = restore_backup(s, Path(args.file))
    print(f"Restaurado. Backup de segurança anterior: {res['safety_backup']}")
    return 0


def cmd_env(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(BACKEND))
    from app.services.system_info import environment_report

    print(json.dumps(environment_report(), indent=2, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------- início com o Windows
def _startup_file() -> Path:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "JARVIS.vbs"


def cmd_autostart(args: argparse.Namespace) -> int:
    if not WIN:
        print("Início automático disponível apenas no Windows (pasta Inicializar do usuário, sem privilégios de administrador).")
        return 1
    f = _startup_file()
    if args.action == "status":
        print("Ativado" if f.exists() else "Desativado")
        return 0
    if args.action == "disable":
        f.unlink(missing_ok=True)
        print("Início automático desativado.")
        return 0
    if not health():
        print("Por segurança, inicie e valide o JARVIS manualmente antes de ativar o início automático (scripts\\start.ps1).")
        return 1
    pyw = VENV_PYW if VENV_PYW.exists() else Path(sys.executable).with_name("pythonw.exe")
    script = Path(__file__).resolve()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.Run """{pyw}"" ""{script}"" start --foreground", 0, False\r\n',
        encoding="utf-8",
    )
    print(f"Início automático ativado: {f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="jarvisctl", description="Controle do JARVIS")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("start", "restart"):
        p = sub.add_parser(name)
        p.add_argument("--dev", action="store_true", help="modo de desenvolvimento (recarrega ao editar)")
        p.add_argument("--no-agent", action="store_true", help="não iniciar o agente local")
        p.add_argument("--whatsapp-web", action="store_true", help="habilitar WhatsApp Web no agente")
        p.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    for name in ("stop", "status", "doctor", "test", "backup", "env-report"):
        sub.add_parser(name)
    p = sub.add_parser("restore")
    p.add_argument("file")
    p = sub.add_parser("autostart")
    p.add_argument("action", choices=["enable", "disable", "status"])
    args = ap.parse_args()
    handlers = {"start": cmd_start, "stop": cmd_stop, "restart": cmd_restart, "status": cmd_status, "doctor": cmd_doctor,
                "test": cmd_test, "backup": cmd_backup, "restore": cmd_restore, "autostart": cmd_autostart,
                "env-report": cmd_env}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
