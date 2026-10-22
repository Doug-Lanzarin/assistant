"""Etapas de configuração do JARVIS (chamadas por ``setup.bat`` → ``scripts/setup.ps1``).

O PowerShell cuida do que precisa existir ANTES do Python (Windows, Python,
Node.js, Git, ambiente virtual). Este módulo, executado com o Python do
ambiente virtual, faz o restante:

1. diretórios de dados; 2. dependências Python; 3. interface (npm ci + build);
4. config/jarvis.toml e .env a partir dos modelos; 5. banco e migrações;
6. IA local (Ollama) e nuvem (chaves); 7. voz e microfone; 8. testes de
integridade (o backend sobe de verdade numa porta temporária); 9. relatório
e indicador ``data/setup-complete.json``.

Idempotência: cada etapa cara grava a impressão digital (SHA-256) do que
instalou em ``data/setup-state.json``. Numa nova execução, só refaz o que
mudou. Nenhum arquivo do usuário é sobrescrito: ``.env`` e ``jarvis.toml``
só são criados quando não existem. Se a execução for interrompida, a etapa
interrompida não grava a impressão digital e é refeita na próxima vez.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
WIN = sys.platform == "win32"
SETUP_VERSION = 1
MIN_PY = (3, 11)
MIN_NODE = 20

# Nomes de variáveis cujo valor nunca aparece em tela nem em log.
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASS)$", re.I)


# --------------------------------------------------------------------------- .env
def parse_env_file(path: Path) -> dict[str, str]:
    """Lê KEY=VALOR (ignora comentários, inclusive ``valor  # comentário``)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if val[:1] in ("'", '"') and val.count(val[0]) >= 2:
            val = val[1 : val.index(val[0], 1)]
        else:
            val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
        out[key] = val
    return out


def load_env(path: Path | None = None) -> dict[str, str]:
    """Carrega o .env no ambiente do processo SEM sobrescrever variáveis já definidas."""
    values = parse_env_file(path or REPO / ".env")
    for k, v in values.items():
        os.environ.setdefault(k, v)
    return values


def env_template_keys(path: Path) -> list[str]:
    """Variáveis citadas no .env.example (ativas ou comentadas)."""
    keys = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*#?\s*([A-Z][A-Z0-9_]+)=", line)
            if m and m.group(1) not in keys:
                keys.append(m.group(1))
    return keys


def mask(name: str, value: str | None) -> str:
    if not value:
        return "não definida"
    return "definida (oculta)" if SECRET_NAME.search(name) else value


# --------------------------------------------------------------------------- caminhos / estado
def data_dir() -> Path:
    return Path(os.environ.get("JARVIS_DATA_DIR") or REPO / "data")


def port() -> int:
    return int(os.environ.get("JARVIS_PORT", "8765"))


def state_file() -> Path:
    return data_dir() / "setup-state.json"


def marker_file() -> Path:
    return data_dir() / "setup-complete.json"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def fingerprint(paths: Iterable[Path], root: Path = REPO) -> str:
    """SHA-256 do caminho relativo + conteúdo de arquivos (diretórios percorridos em ordem)."""
    h = hashlib.sha256()
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files += [f for f in p.rglob("*") if f.is_file() and "node_modules" not in f.parts and "__pycache__" not in f.parts]
        elif p.is_file():
            files.append(p)
    for f in sorted(set(files)):
        h.update(f.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def requirement_files(features: dict) -> list[Path]:
    files = [BACKEND / "requirements.txt"]
    if WIN and features.get("desktop", True):
        files.append(BACKEND / "requirements-desktop.txt")
    if features.get("voice"):
        files.append(BACKEND / "requirements-voice.txt")
    if features.get("whatsapp"):
        files.append(BACKEND / "requirements-whatsapp.txt")
    if features.get("tests"):
        files.append(BACKEND / "requirements-dev.txt")
    return files


# Versões alternativas já validadas neste projeto, usadas só se a principal não instalar.
FALLBACKS = {"openwakeword": "openwakeword==0.4.0"}  # 0.6+ depende do tflite-runtime (sem pacote p/ Python 3.13)


def requirement_lines(req: Path) -> list[str]:
    """Especificações de um requirements.txt (sem comentários; marcadores de plataforma preservados)."""
    out = []
    for raw in req.read_text(encoding="utf-8").splitlines():
        line = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        if line and not line.startswith(("#", "-")):
            out.append(line)
    return out


def frontend_inputs() -> list[Path]:
    names = ["src", "public", "index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json",
             "tsconfig.app.json", "tsconfig.node.json"]
    return [FRONTEND / n for n in names if (FRONTEND / n).exists()]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_in_use(p: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", p)) == 0


_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 127.0.0.1 nunca passa por proxy


def http_get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    try:
        with _LOCAL.open(url, timeout=timeout) as r:
            return r.status, r.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError):
        return 0, ""


def npm_cmd() -> list[str] | None:
    exe = shutil.which("npm.cmd" if WIN else "npm") or shutil.which("npm")
    return [exe] if exe else None


def node_version() -> tuple[int, ...] | None:
    node = shutil.which("node")
    if not node:
        return None
    r = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    m = re.match(r"v(\d+)\.(\d+)\.(\d+)", r.stdout.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def ollama_exe() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if WIN:
        cand = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if cand.exists():
            return str(cand)
    return None


# --------------------------------------------------------------------------- relatório
class Report:
    """Mensagens de progresso na tela + log em arquivo (sem segredos)."""

    COLORS = {"OK": "32", "AVISO": "33", "FALHA": "31", "PULADO": "90", "INFO": "36"}

    def __init__(self, log_path: Path, color: bool = True):
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 - fechado em close()
        self.items: list[dict] = []
        self.color = color and sys.stdout.isatty()
        if WIN and self.color:
            os.system("")  # noqa: S605,S607 - habilita cores ANSI no console do Windows

    def _write(self, text: str) -> None:
        self._f.write(text + "\n")
        self._f.flush()

    def section(self, title: str) -> None:
        print(f"\n== {title} ==", flush=True)
        self._write(f"\n== {title} ==")

    def line(self, text: str) -> None:
        print("   " + text, flush=True)
        self._write("   " + text)

    def detail(self, text: str) -> None:
        """Só no arquivo (saída longa de pip/npm)."""
        self._write(text)

    def add(self, status: str, label: str, how: str = "", required: bool = False) -> None:
        tag = f"[{status}]".ljust(9)
        shown = f"\033[{self.COLORS[status]}m{tag}\033[0m" if self.color else tag
        print(f" {shown}{label}", flush=True)
        self._write(f" {tag}{label}")
        if how:
            for part in how.splitlines():
                print(f"          → {part}", flush=True)
                self._write(f"          → {part}")
        self.items.append({"status": status, "label": label, "how": how, "required": required})

    def ok(self, label: str, required: bool = False) -> None:
        self.add("OK", label, required=required)

    def warn(self, label: str, how: str = "") -> None:
        self.add("AVISO", label, how)

    def fail(self, label: str, how: str = "") -> None:
        self.add("FALHA", label, how, required=True)

    def skip(self, label: str, how: str = "") -> None:
        self.add("PULADO", label, how)

    def info(self, label: str, how: str = "") -> None:
        self.add("INFO", label, how)

    @property
    def failures(self) -> list[dict]:
        return [i for i in self.items if i["status"] == "FALHA"]

    def close(self) -> None:
        self._f.close()


def run_logged(rep: Report, cmd: list[str], cwd: Path, timeout: float = 1800, env: dict | None = None) -> int:
    """Executa um comando (sem shell), mostrando só um resumo; a saída completa vai para o log."""
    rep.detail(f"$ {' '.join(cmd)}  (em {cwd})")
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, check=False, env=env)
    except subprocess.TimeoutExpired:
        rep.detail("tempo esgotado")
        return 124
    except OSError as e:
        rep.detail(f"não foi possível executar: {e}")
        return 127
    rep.detail(r.stdout[-20000:])
    rep.detail(r.stderr[-20000:])
    rep.detail(f"código de saída: {r.returncode}")
    return r.returncode


def tail_error(rep: Report, n: int = 6) -> str:
    """Últimas linhas relevantes do log (para mostrar o motivo da falha)."""
    try:
        lines = rep.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    hits = [ln.strip() for ln in lines[-400:] if re.search(r"error|erro|failed|falh|ERR!", ln, re.I)]
    return "\n".join(hits[-n:])


# --------------------------------------------------------------------------- etapas
class Setup:
    def __init__(self, opts, rep: Report):
        self.o = opts
        self.rep = rep
        self.py = sys.executable
        self.state = read_json(state_file())
        prev = self.state.get("features", {})
        # Recursos opcionais lembram a escolha anterior (rodar de novo não desinstala nada).
        self.features = {
            "voice": prev.get("voice", True) if opts.voice is None else opts.voice,
            "whatsapp": prev.get("whatsapp", False) or opts.whatsapp,
            "tests": prev.get("tests", False) or opts.tests,
            "desktop": True,
        }

    def save_state(self, **kv) -> None:
        self.state.update(kv)
        self.state["features"] = self.features
        write_json(state_file(), self.state)

    # 1 ---------------------------------------------------------------
    def environment(self) -> None:
        r = self.rep
        r.section("1. Ambiente")
        r.info(f"Sistema: {platform.system()} {platform.release()} ({platform.version()}) · {platform.machine()}")
        r.info(f"Python do ambiente virtual: {sys.version.split()[0]} ({self.py})")
        if sys.version_info < MIN_PY:
            r.fail(f"Python {sys.version.split()[0]} é antigo", "instale o Python 3.12 e rode setup.bat novamente")
        elif sys.version_info >= (3, 13) and self.features["voice"]:
            r.warn("Python 3.13: o openWakeWord (palavra de ativação) pode não instalar",
                   "recomendado: Python 3.12 (o restante funciona)")
        else:
            r.ok(f"Python {sys.version_info.major}.{sys.version_info.minor} compatível", required=True)
        if sys.prefix == sys.base_prefix:
            r.fail("o setup não está rodando dentro do ambiente virtual", "execute pelo setup.bat")
        free = shutil.disk_usage(REPO).free / 1e9
        need = 1.5 + (0.6 if self.features["voice"] else 0) + (2.5 if self.o.ollama else 0)
        if free < need:
            r.fail(f"espaço livre em disco: {free:.1f} GB (necessário ~{need:.1f} GB)", "libere espaço e rode novamente")
        else:
            r.ok(f"espaço livre em disco: {free:.1f} GB (necessário ~{need:.1f} GB)")

    # 2 ---------------------------------------------------------------
    def directories(self) -> None:
        r = self.rep
        r.section("2. Diretórios")
        # Mesmos diretórios de Settings.ensure_dirs(), sem importar o backend (ainda sem dependências).
        d = data_dir()
        try:
            for sub in ("", "logs", "secrets", "backups", "library", "models"):
                (d / sub).mkdir(parents=True, exist_ok=True)
            if not WIN:
                os.chmod(d / "secrets", 0o700)
            t = d / ".write-test"
            t.write_text("x")
            t.unlink()
            r.ok(f"dados em {d} (logs, segredos, backups, biblioteca, modelos)", required=True)
        except OSError as e:
            r.fail(f"não foi possível preparar o diretório de dados: {e}", "verifique permissões ou JARVIS_DATA_DIR no .env")

    # 3 ---------------------------------------------------------------
    def python_deps(self) -> None:
        r = self.rep
        r.section("3. Dependências Python")
        files = requirement_files(self.features)
        fp = fingerprint(files)
        names = ", ".join(f.name for f in files)
        if self.state.get("pip") == fp and self._core_imports_ok() and not self.o.force:
            r.ok(f"já instaladas ({names}) — nada a fazer", required=True)
            return
        if not self.state.get("pip_upgraded"):
            run_logged(r, [self.py, "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check"], BACKEND, 600)
            self.save_state(pip_upgraded=True)
        self.save_state(pip=None)  # invalida até terminar (retomada segura após interrupção)
        core = [f for f in files if f.name in ("requirements.txt", "requirements-desktop.txt", "requirements-dev.txt")]
        r.line(f"instalando {', '.join(f.name for f in core)} (pode levar alguns minutos)…")
        args = [self.py, "-m", "pip", "install", "--disable-pip-version-check"]
        for f in core:
            args += ["-r", str(f)]
        if run_logged(r, args, BACKEND) != 0 or not self._core_imports_ok():
            r.fail("falha ao instalar as dependências do backend",
                   (tail_error(r) + "\n" if tail_error(r) else "") + f"detalhes em {r.log_path}")
            return
        r.ok("backend e agente: dependências instaladas", required=True)
        ok_optional = True
        for f, label in ((BACKEND / "requirements-voice.txt", "voz local (faster-whisper, Piper, openWakeWord)"),
                         (BACKEND / "requirements-whatsapp.txt", "WhatsApp Web (Playwright)")):
            if f not in files:
                continue
            r.line(f"instalando {label}…")
            failed = self._install_optional(f)
            if not failed:
                r.ok(label)
            else:
                ok_optional = False
                r.warn(f"{label}: não instalado(s): {', '.join(failed)}",
                       f"o restante foi instalado; detalhes em {r.log_path}\no JARVIS funciona sem este(s) pacote(s)")
        if self.features["whatsapp"]:
            if run_logged(r, [self.py, "-m", "playwright", "install", "chromium"], BACKEND) == 0:
                r.ok("Chromium do Playwright (WhatsApp Web)")
            else:
                ok_optional = False
                r.warn("Chromium do Playwright não instalado", "rode: backend\\.venv\\Scripts\\python -m playwright install chromium")
        # Só grava a impressão digital se tudo deu certo: senão, a próxima execução tenta de novo.
        if ok_optional:
            self.save_state(pip=fp)

    def _install_optional(self, req: Path) -> list[str]:
        """Instala um arquivo de requisitos opcional; se falhar, tenta pacote a pacote.

        Assim, um pacote sem versão para este Python (ex.: openWakeWord ≥ 0.6 no 3.13)
        não impede a instalação dos demais.
        """
        pip = [self.py, "-m", "pip", "install", "--disable-pip-version-check"]
        if run_logged(self.rep, [*pip, "-r", str(req)], BACKEND) == 0:
            return []
        failed = []
        for spec in requirement_lines(req):
            name = re.split(r"[<>=!~;\[ ]", spec, maxsplit=1)[0]
            if run_logged(self.rep, [*pip, spec], BACKEND) == 0:
                continue
            alt = FALLBACKS.get(name.lower())
            if alt and run_logged(self.rep, [*pip, alt], BACKEND) == 0:
                self.rep.info(f"{name}: usada a versão compatível {alt}")
                continue
            failed.append(name)
        return failed

    def _core_imports_ok(self) -> bool:
        code = "import fastapi, uvicorn, pydantic_settings, httpx, numpy, cryptography, psutil, anthropic, websockets, pypdf, docx"
        return subprocess.run([self.py, "-c", code], capture_output=True, check=False).returncode == 0

    # 4 ---------------------------------------------------------------
    def frontend(self) -> None:
        r = self.rep
        r.section("4. Interface (React + AI Voice Orb)")
        dist = FRONTEND / "dist" / "index.html"
        fp = fingerprint(frontend_inputs())
        if dist.exists() and self.state.get("frontend") == fp and not self.o.force:
            r.ok("interface já compilada e atualizada", required=True)
            return
        nv = node_version()
        npm = npm_cmd()
        if not nv or not npm:
            if dist.exists():
                r.warn("Node.js não encontrado; usando a interface já compilada", "instale o Node.js LTS para recompilar")
                return
            r.fail("Node.js/npm não encontrados e a interface não está compilada",
                   "instale o Node.js LTS (winget install OpenJS.NodeJS.LTS) e rode setup.bat novamente")
            return
        if nv[0] < MIN_NODE:
            r.fail(f"Node.js {'.'.join(map(str, nv))} é antigo (mínimo {MIN_NODE})", "atualize: winget upgrade OpenJS.NodeJS.LTS")
            return
        r.ok(f"Node.js {'.'.join(map(str, nv))}")
        lock = fingerprint([FRONTEND / "package-lock.json", FRONTEND / "package.json"])
        if not (FRONTEND / "node_modules").exists() or self.state.get("npm") != lock or self.o.force:
            self.save_state(npm=None)
            r.line("instalando pacotes JavaScript (npm ci)…")
            if run_logged(r, [*npm, "ci", "--no-audit", "--no-fund"], FRONTEND) != 0:
                r.fail("npm ci falhou", (tail_error(r) + "\n" if tail_error(r) else "") + f"detalhes em {r.log_path}")
                return
            self.save_state(npm=lock)
        self.save_state(frontend=None)  # invalida até a compilação terminar
        r.line("compilando a interface (npm run build)…")
        if run_logged(r, [*npm, "run", "build"], FRONTEND, 900) != 0 or not dist.exists():
            r.fail("falha ao compilar a interface", (tail_error(r) + "\n" if tail_error(r) else "") + f"detalhes em {r.log_path}")
            return
        self.save_state(frontend=fp)
        r.ok("interface compilada (frontend/dist)", required=True)

    # 5 ---------------------------------------------------------------
    def config_files(self) -> None:
        r = self.rep
        r.section("5. Configuração")
        example = REPO / "config" / "jarvis.example.toml"
        cfg = Path(os.environ.get("JARVIS_CONFIG_FILE") or REPO / "config" / "jarvis.toml")
        if cfg.exists():
            r.ok("config/jarvis.toml já existe (preservado)")
        else:
            cfg.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(example, cfg)
            r.ok(f"{cfg.name} criado a partir do modelo ({cfg})")
            r.info("revise os caminhos de apps, pastas e projetos em config\\jarvis.toml")
        try:
            sys.path.insert(0, str(BACKEND))
            from app.core.config import load_toml

            t = load_toml(cfg)
            r.ok(f"{cfg.name} válido ({len(t.apps)} apps, {len(t.allowed_dirs)} pastas, {len(t.routines)} rotinas)",
                 required=True)
        except Exception as e:  # noqa: BLE001
            r.fail(f"config/jarvis.toml inválido: {str(e)[:300]}", "corrija o arquivo (o modelo está em config\\jarvis.example.toml)")
        env_path, env_example = REPO / ".env", REPO / ".env.example"
        if env_path.exists():
            r.ok(".env já existe (preservado; nenhuma chave foi alterada)")
        else:
            shutil.copyfile(env_example, env_path)
            r.ok(".env criado a partir do .env.example (sem chaves)")
        values = parse_env_file(env_path)
        missing = [k for k in env_template_keys(env_example) if k not in values]
        if missing:
            r.info(f"variáveis opcionais não definidas no .env: {', '.join(missing)}")
        for k in values:
            r.detail(f"   .env {k}: {mask(k, values[k])}")
        host = values.get("JARVIS_HOST", "127.0.0.1")
        if host not in ("127.0.0.1", "localhost", "::1"):
            r.warn(f"JARVIS_HOST={host} expõe o JARVIS na rede", "use 127.0.0.1, a menos que saiba o que está fazendo")

    # 6 ---------------------------------------------------------------
    def database(self) -> None:
        r = self.rep
        r.section("6. Banco de dados")
        try:
            sys.path.insert(0, str(BACKEND))
            from app.core.config import Settings
            from app.core.db import Database

            env = Settings()
            existed = env.db_path.exists()
            db = Database(env.db_path)
            applied = db.migrate()
            res = db.scalar("PRAGMA integrity_check")
            db.close()
            if res != "ok":
                r.fail(f"integridade do banco: {res}", "restaure um backup: scripts\\restore.ps1 -File data\\backups\\...")
                return
            what = f"migrações aplicadas: {', '.join(applied)}" if applied else "sem migrações pendentes"
            r.ok(f"{'banco existente' if existed else 'banco criado'} ({env.db_path.name}); {what}; integridade ok", required=True)
        except Exception as e:  # noqa: BLE001
            r.fail(f"banco de dados: {e}", "veja o log; se o banco estiver corrompido, restaure um backup")

    # 7 ---------------------------------------------------------------
    def ai(self) -> None:
        r = self.rep
        r.section("7. IA (híbrida: nuvem + local)")
        cfg = {"mode": "remote_first", "local_url": "http://127.0.0.1:11434", "local_model": "qwen2.5:3b"}
        secret_names: list[str] = []
        try:
            sys.path.insert(0, str(BACKEND))
            from app.core.config import Settings
            from app.core.db import Database
            from app.security.secrets import SecretStore
            from app.services.settings_store import SettingsStore

            env = Settings()
            db = Database(env.db_path)
            try:
                cfg = SettingsStore(db).get("ai")
            finally:
                db.close()
            secret_names = SecretStore(env.secrets_dir).names()
        except Exception as e:  # noqa: BLE001
            r.detail(f"não foi possível ler as preferências de IA: {e}")
        r.info(f"modo atual: {cfg['mode']} (altere em Configurações → IA)")
        cloud = "anthropic_api_key" in secret_names or bool(os.environ.get("ANTHROPIC_API_KEY"))
        if cloud:
            r.ok("chave da Anthropic configurada (valor não exibido)")
        else:
            r.info("IA na nuvem: nenhuma chave configurada",
                   "adicione depois em Configurações → IA (fica cifrada com DPAPI)\nou defina ANTHROPIC_API_KEY no .env")
        exe = ollama_exe()
        status, body = http_get(cfg["local_url"].rstrip("/") + "/api/tags")
        if not exe and status != 200:
            r.info("IA local: Ollama não instalado (opcional)",
                   "para instalar: setup.bat -Ollama (instalador ~1 GB + modelo qwen2.5:3b ~1,9 GB)")
        elif status != 200:
            r.warn("Ollama instalado, mas não está em execução", "abra o aplicativo Ollama e rode setup.bat novamente")
        else:
            models = [m.get("name", "") for m in json.loads(body or "{}").get("models", [])]
            want = cfg["local_model"]
            has = any(m == want or m.split(":")[0] == want for m in models)
            if has:
                r.ok(f"Ollama em execução com o modelo {want}")
            elif self.o.ollama and exe:
                r.line(f"baixando o modelo {want} (~1,9 GB; pode demorar)…")
                rc = subprocess.run([exe, "pull", want], check=False).returncode
                (r.ok if rc == 0 else r.warn)(f"modelo {want} {'baixado' if rc == 0 else 'não baixado'}")
            else:
                r.info(f"Ollama em execução, sem o modelo {want}",
                       f"para baixar (~1,9 GB): setup.bat -Ollama   ou   ollama pull {want}")
        if not cloud and status != 200:
            r.warn("nenhuma IA configurada: o JARVIS responde só aos comandos diretos (offline)",
                   "funciona, mas para perguntas livres configure a chave da nuvem ou o Ollama")

    # 8 ---------------------------------------------------------------
    def voice(self) -> None:
        r = self.rep
        r.section("8. Voz e microfone")
        if not self.features["voice"]:
            r.skip("voz local desativada (-NoVoice)", "no navegador, a voz do sistema continua funcionando para falar")
            return
        mods = {"faster_whisper": "transcrição (faster-whisper)", "piper": "voz neural (Piper)",
                "sounddevice": "acesso ao microfone (sounddevice)", "openwakeword": "palavra de ativação (openWakeWord)"}
        have = {}
        for m, label in mods.items():
            res = subprocess.run([self.py, "-c", f"import {m}"], capture_output=True, text=True, check=False)
            have[m] = res.returncode == 0
            if have[m]:
                r.ok(label)
            elif "ModuleNotFoundError" in res.stderr:
                r.warn(f"{label}: não instalado", "execute setup.bat novamente")
            else:
                r.detail(res.stderr[-1500:])
                r.warn(f"{label}: instalado, mas não carregou", (res.stderr.strip().splitlines() or [""])[-1][:200])
        models = data_dir() / "models"
        piper_ok = any((models / "piper").glob("*.onnx"))
        whisper_ok = any((models / "whisper").glob("**/model.bin"))
        if (not piper_ok or not whisper_ok) and (have["faster_whisper"] or have["piper"]):
            if self.o.offline:
                r.skip("modelos de voz não baixados (modo offline)")
            else:
                r.line("baixando modelos de voz (Piper pt-BR ~60 MB + Whisper base ~145 MB, uma vez só)…")
                run_logged(r, [self.py, str(REPO / "scripts" / "download_voice_models.py"),
                               "--data-dir", str(data_dir())], REPO, 1800)
                piper_ok = any((models / "piper").glob("*.onnx"))
                whisper_ok = any((models / "whisper").glob("**/model.bin"))
        if have["piper"]:
            (r.ok if piper_ok else r.warn)("modelo de voz Piper pt-BR" + ("" if piper_ok else " ausente — será usada a voz do sistema"))
        if have["faster_whisper"]:
            (r.ok if whisper_ok else r.warn)("modelo de transcrição Whisper" + ("" if whisper_ok else " ausente — será baixado no primeiro uso"))
        if not have["faster_whisper"]:
            r.warn("sem transcrição local, o orb não entende comandos falados", "execute setup.bat novamente; detalhes no relatório")
        self.microphone(have["sounddevice"])

    def microphone(self, has_sd: bool) -> None:
        """Consulta permissões e dispositivos. NÃO abre o microfone."""
        r = self.rep
        if WIN:
            perm = _windows_mic_consent()
            if perm == "Deny":
                r.warn("o Windows está bloqueando o microfone",
                       "Configurações → Privacidade e segurança → Microfone → ative 'Acesso ao microfone'\n"
                       "e 'Permitir que aplicativos da área de trabalho acessem o microfone'")
            elif perm == "Allow":
                r.ok("permissão de microfone do Windows: permitido")
            else:
                r.info("permissão de microfone do Windows: não foi possível ler (verifique em Privacidade → Microfone)")
        if not has_sd:
            return
        code = ("import json, sounddevice as sd\n"
                "d=[x for x in sd.query_devices() if x['max_input_channels']>0]\n"
                "i=sd.default.device[0]\n"
                "print(json.dumps({'n':len(d),'default':sd.query_devices(i)['name'] if i is not None and i>=0 else None}))")
        res = subprocess.run([self.py, "-c", code], capture_output=True, text=True, check=False, timeout=30)
        try:
            info = json.loads(res.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            r.warn("não foi possível listar os dispositivos de áudio", "verifique o driver de áudio")
            return
        if info["n"]:
            r.ok(f"{info['n']} entrada(s) de áudio; padrão: {info['default'] or 'nenhum'} (o microfone NÃO foi ligado)")
        else:
            r.warn("nenhum microfone encontrado", "conecte um microfone; o JARVIS funciona por texto sem ele")
        r.info("no navegador, o microfone só é usado quando você clica no orb ou aperta Espaço (o navegador pede permissão)")

    # 9 ---------------------------------------------------------------
    def integrity(self) -> None:
        r = self.rep
        r.section("9. Testes de integridade")
        envv = dict(os.environ)
        envv["PYTHONPATH"] = os.pathsep.join([str(REPO / "desktop"), str(BACKEND)])
        rc = subprocess.run([self.py, "-m", "jarvis_agent", "--help"], cwd=str(BACKEND), env=envv,
                            capture_output=True, check=False, timeout=120).returncode
        (r.ok if rc == 0 else r.fail)("agente local carrega", **({} if rc == 0 else {"how": "reinstale: setup.bat -Force"}))
        if rc == 0:
            self.rep.items[-1]["required"] = True
        self._smoke_backend(envv)
        if self.features["tests"]:
            r.line("executando a suíte de testes do backend (pytest)…")
            rc = run_logged(r, [self.py, "-m", "pytest", "-q", "-p", "no:cacheprovider"], BACKEND, 1800)
            (r.ok if rc == 0 else r.fail)("testes automatizados do backend",
                                          **({} if rc == 0 else {"how": f"detalhes em {r.log_path}"}))

    def _smoke_backend(self, envv: dict) -> None:
        r = self.rep
        status, body = http_get(f"http://127.0.0.1:{port()}/api/health")
        if status == 200 and '"status"' in body and this_instance_running():
            r.ok(f"este JARVIS já está em execução na porta {port()} e responde", required=True)
            return
        p = free_port()
        envv = dict(envv, JARVIS_PORT=str(p), JARVIS_ENV="production")
        cmd = [self.py, "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1", "--port", str(p),
               "--log-level", "warning"]
        r.line(f"iniciando o backend numa porta temporária ({p}) para testar…")
        proc = subprocess.Popen(cmd, cwd=str(BACKEND), env=envv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        try:
            ok = False
            for _ in range(120):
                if proc.poll() is not None:
                    break
                st, body = http_get(f"http://127.0.0.1:{p}/api/health", 1)
                if st == 200:
                    ok = json.loads(body).get("db") is True
                    break
                time.sleep(0.5)
            if not ok:
                out = ""
                if proc.poll() is not None and proc.stdout:
                    out = proc.stdout.read()[-1500:]
                r.detail(out)
                r.fail("o backend não iniciou", (out.strip().splitlines() or ["sem saída"])[-1][:300] + f"\ndetalhes em {r.log_path}")
                return
            r.ok("backend inicia e o banco responde (/api/health)", required=True)
            st, html = http_get(f"http://127.0.0.1:{p}/")
            (r.ok if st == 200 and "<div id=\"root\"" in html else r.fail)(
                "interface servida pelo backend (AI Voice Orb em /#/jarvis)", "rode setup.bat -Force" if st != 200 else "")
            st, _ = http_get(f"http://127.0.0.1:{p}/api/status")
            (r.ok if st == 401 else r.fail)("API protegida por autenticação (401 sem login)")
        finally:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()

    # ----------------------------------------------------------------
    def finish(self) -> int:
        r = self.rep
        r.section("Resultado")
        fails = r.failures
        warns = [i for i in r.items if i["status"] == "AVISO"]
        report = {"version": SETUP_VERSION, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "python": sys.version.split()[0],
                  "features": self.features, "ok": not fails, "items": r.items, "log": str(r.log_path)}
        write_json(data_dir() / "setup-report.json", report)
        if fails:
            with suppress(OSError):
                marker_file().unlink()  # configuração deixou de estar válida
            r.add("FALHA", f"configuração INCOMPLETA: {len(fails)} item(ns) obrigatório(s) falharam")
            for f in fails:
                r.line(f"- {f['label']}")
            r.line("Corrija os itens acima e execute setup.bat novamente (o que já foi feito não será refeito).")
            r.line(f"Relatório completo: {r.log_path}")
            return 1
        write_json(marker_file(), {"version": SETUP_VERSION, "completed_at": report["finished_at"],
                                   "pip": self.state.get("pip"), "frontend": self.state.get("frontend"),
                                   "python": report["python"], "features": self.features})
        r.add("OK", "configuração concluída" + (f" com {len(warns)} aviso(s) opcional(is)" if warns else ""))
        r.line("Próximo passo: dê dois cliques em start.bat.")
        r.line(f"Relatório completo: {r.log_path}")
        return 0


def this_instance_running() -> bool:
    """O supervisor DESTA instalação está vivo? (pid em data/jarvis.pid)."""
    try:
        pid = int((data_dir() / "jarvis.pid").read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        return False


def _windows_mic_consent() -> str | None:
    try:
        import winreg  # type: ignore[import-not-found]

        key = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return str(winreg.QueryValueEx(k, "Value")[0])
    except (ImportError, OSError):
        return None


def run_setup(opts) -> int:
    load_env()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = data_dir() / "logs" / f"setup-{stamp}.log"
    if opts.log:
        log_path = Path(opts.log)
    rep = Report(log_path)
    rep.detail(f"JARVIS setup {time.strftime('%Y-%m-%d %H:%M:%S')} · repo {REPO}")
    s = Setup(opts, rep)
    # Em andamento = não concluída. O indicador só volta se esta execução terminar sem falhas
    # (uma interrupção, até por queda de energia, nunca deixa um indicador válido para trás).
    with suppress(OSError):
        marker_file().unlink()
    try:
        s.environment()
        s.directories()
        if rep.failures:
            return s.finish()
        s.python_deps()
        s.frontend()
        s.config_files()
        s.database()
        s.ai()
        s.voice()
        if not rep.failures:
            s.integrity()
        else:
            rep.section("9. Testes de integridade")
            rep.skip("não executados porque há falhas obrigatórias acima")
        return s.finish()
    except KeyboardInterrupt:
        rep.add("FALHA", "configuração interrompida pelo usuário",
                "execute setup.bat novamente para continuar de onde parou")
        with suppress(OSError):
            marker_file().unlink()
        return 130
    finally:
        rep.close()


def check_ready(require_marker: bool = True) -> list[str]:
    """Problemas que impedem o start.bat de iniciar (lista vazia = pronto)."""
    problems: list[str] = []
    m = read_json(marker_file())
    if require_marker and not m:
        problems.append("a configuração inicial não foi concluída — execute setup.bat")
        return problems
    if m and m.get("pip") and m.get("pip") != fingerprint(requirement_files(m.get("features", {}))):
        problems.append("as dependências do projeto mudaram desde a última configuração — execute setup.bat")
    if not (FRONTEND / "dist" / "index.html").exists():
        problems.append("a interface não está compilada — execute setup.bat")
    code = "import fastapi, uvicorn, pydantic_settings, numpy, cryptography, anthropic, websockets"
    if subprocess.run([sys.executable, "-c", code], capture_output=True, check=False).returncode != 0:
        problems.append("dependências essenciais ausentes no ambiente virtual — execute setup.bat")
    return problems
