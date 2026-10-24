"""Aplicação FastAPI do JARVIS."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api import auth, chat, clipboard, integrations, memory, system, ws
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.services.background import RESTART_EXIT_CODE, Background
from app.services.container import Services, build_services
from app.voice.engines import PiperTTS, STTEngine

log = logging.getLogger("jarvis")


class VoiceEngines:
    def __init__(self, models_dir: Path):
        self.stt = STTEngine(models_dir)
        self.tts = PiperTTS(models_dir)


def _warm_voice(s: Services) -> None:
    """Carrega Whisper e Piper em segundo plano: o primeiro comando de voz não espera ~20 s."""
    cfg = s.settings.get("voice")
    if not cfg["enabled"] or s.voice is None:
        return

    def run():
        if STTEngine.installed():
            s.voice.stt.warm(cfg["stt_model"])
        if PiperTTS.installed() and s.voice.tts.available_voices():
            try:
                s.voice.tts.synthesize("ok", cfg.get("tts_voice") or None)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao pré-carregar o Piper")

    threading.Thread(target=run, name="voice-warmup", daemon=True).start()


def ensure_agent_token(s: Services) -> str:
    token = s.secrets.get("agent_token")
    if not token:
        token = secrets.token_urlsafe(32)
        s.secrets.set("agent_token", token)
    write_agent_token_file(s.env.secrets_dir / "agent.token", token)
    return token


def write_agent_token_file(path: Path, token: str) -> None:
    """Arquivo lido pelo agente local. No Windows é protegido por DPAPI (só o usuário atual decifra)."""
    data = token.encode()
    if sys.platform == "win32":
        from app.security.secrets import _Dpapi

        data = b"DPAPI" + _Dpapi().protect(data)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    if sys.platform != "win32":
        os.chmod(path, 0o600)


def create_app(env: Settings | None = None, services: Services | None = None) -> FastAPI:
    env = env or get_settings()
    env.ensure_dirs()
    if env.env != "test":
        setup_logging(env.logs_dir, env.log_level,
                      console=env.log_console if env.log_console is not None else env.env == "development")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s: Services = app.state.services
        ensure_agent_token(s)
        bg = Background(s)
        s.background = bg

        def _restart():
            log.warning("Encerrando com código %s para reinício pelo supervisor", RESTART_EXIT_CODE)
            os._exit(RESTART_EXIT_CODE)

        bg.on_restart = _restart
        if env.env != "test":
            bg.start()
            _warm_voice(s)
            warm_task = asyncio.create_task(s.providers.warm_local())  # noqa: RUF006 - referência mantida abaixo
            app.state.warm_task = warm_task
        log.info("JARVIS iniciado em http://%s:%s", env.host, env.port)
        yield
        await bg.stop()
        s.db.close() if env.env != "test" else None
        log.info("JARVIS encerrado")

    app = FastAPI(title="JARVIS", version=system.VERSION, lifespan=lifespan,
                  docs_url="/api/docs" if env.env == "development" else None, redoc_url=None)
    s = services or build_services(env)
    s.voice = VoiceEngines(env.data_dir / "models")
    if s.background is None:
        s.background = Background(s)
    app.state.services = s

    app.add_middleware(
        CORSMiddleware,
        allow_origins=env.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline';"
                " connect-src 'self' ws: wss:; frame-ancestors 'none'",
            )
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("Erro não tratado em %s", request.url.path)
        return JSONResponse({"detail": "Erro interno. Consulte os logs."}, status_code=500)

    for r in (system.public, auth.router, chat.router, memory.router, clipboard.router, integrations.home,
              integrations.wa, integrations.wa_public, system.router, ws.router):
        app.include_router(r)

    dist = env.frontend_dist
    if dist.exists():
        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Não encontrado"}, status_code=404)
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def no_ui():
            return JSONResponse({"detail": "Interface não compilada. Rode scripts/build_frontend (npm run build em frontend/).",
                                 "api_docs": "/api/docs"})

    return app
