"""Despachante RPC do agente: lista fechada de métodos permitidos."""

from __future__ import annotations

import asyncio
import logging
import platform
import sys
from collections.abc import Callable
from typing import Any

from . import __version__, actions
from .clipboard import ClipboardBackend, default_backend

log = logging.getLogger("jarvis_agent.rpc")


class RpcError(Exception):
    pass


def _str(params: dict, key: str, max_len: int = 100_000, required: bool = True) -> str | None:
    v = params.get(key)
    if v is None and not required:
        return None
    if not isinstance(v, str) or len(v) > max_len:
        raise RpcError(f"Parâmetro inválido: {key}")
    return v


class Dispatcher:
    def __init__(self, clipboard: ClipboardBackend | None = None, voice=None, whatsapp=None, notifier=None,
                 notifications=None, emit: Callable[[str, dict], None] | None = None):
        self.clipboard = clipboard or default_backend()
        self.voice = voice
        self.whatsapp = whatsapp
        self.notifier = notifier or actions.Notifier()
        self.notifications = notifications
        self.emit = emit or (lambda e, d: None)
        self.methods: dict[str, Callable[[dict], Any]] = {
            "ping": self.ping,
            "clipboard.read": self.clip_read,
            "clipboard.write": self.clip_write,
            "apps.launch": self.apps_launch,
            "open.url": self.open_url,
            "open.path": self.open_path,
            "process.run": self.process_run,
            "notify": self.notify,
            "voice.speak": self.voice_speak,
            "voice.stop_speaking": self.voice_stop,
            "voice.listen_once": self.voice_listen,
            "voice.devices": self.voice_devices,
            "voice.configure": self.voice_configure,
            "whatsapp.status": self.wa_status,
            "whatsapp.unread": self.wa_unread,
            "whatsapp.search_contact": self.wa_search,
            "whatsapp.send": self.wa_send,
        }

    def info(self) -> dict[str, Any]:
        caps = ["clipboard", "apps", "notify", "process"]
        if self.voice is not None and self.voice.capabilities().get("microphone"):
            caps.append("voice")
        if self.whatsapp is not None:
            caps.append("whatsapp_web")
        if self.notifications is not None and self.notifications.supported():
            caps.append("notifications")
        return {"platform": sys.platform, "os": platform.platform(), "version": __version__, "capabilities": caps,
                "clipboard_backend": self.clipboard.name,
                "voice": self.voice.capabilities() if self.voice is not None else {}}

    async def dispatch(self, method: str, params: dict | None) -> Any:
        fn = self.methods.get(method)
        if fn is None:
            raise RpcError(f"Método não permitido: {method}")
        params = params or {}
        if not isinstance(params, dict):
            raise RpcError("Parâmetros devem ser um objeto")
        res = fn(params)
        if asyncio.iscoroutine(res):
            return await res
        return res

    # -- métodos ------------------------------------------------------------------------
    def ping(self, p: dict) -> dict:
        return {"pong": True}

    async def clip_read(self, p: dict) -> dict:
        return await asyncio.to_thread(self.clipboard.read)

    async def clip_write(self, p: dict) -> dict:
        text = _str(p, "text", 1_000_000)
        await asyncio.to_thread(self.clipboard.write, text)
        return {"ok": True}

    async def apps_launch(self, p: dict) -> dict:
        return await asyncio.to_thread(actions.launch, _str(p, "command", 1000), p.get("args") or [])

    async def open_url(self, p: dict) -> dict:
        return await asyncio.to_thread(actions.open_url, _str(p, "url", 4000))

    async def open_path(self, p: dict) -> dict:
        return await asyncio.to_thread(actions.open_path, _str(p, "path", 2000))

    async def process_run(self, p: dict) -> dict:
        timeout = float(p.get("timeout") or 120)
        return await asyncio.to_thread(actions.run_process, _str(p, "executable", 1000), p.get("args") or [],
                                       _str(p, "cwd", 2000, required=False), timeout)

    def notify(self, p: dict) -> dict:
        return self.notifier.notify(_str(p, "title", 200) or "JARVIS", _str(p, "message", 2000))

    def _need_voice(self):
        if self.voice is None:
            raise RpcError("Voz não disponível no agente")
        return self.voice

    def voice_speak(self, p: dict) -> dict:
        return self._need_voice().speak(_str(p, "text", 5000))

    def voice_stop(self, p: dict) -> dict:
        return self.voice.stop_speaking() if self.voice else {"ok": True}

    async def voice_listen(self, p: dict) -> dict:
        v = self._need_voice()
        # Não bloqueia a resposta RPC: a transcrição chega como evento voice.command.
        asyncio.get_running_loop().run_in_executor(None, v.listen_once)
        return {"ok": True, "listening": True}

    def voice_devices(self, p: dict) -> dict:
        return self._need_voice().devices()

    def voice_configure(self, p: dict) -> dict:
        settings = p.get("settings") or {}
        if not isinstance(settings, dict):
            raise RpcError("settings inválido")
        return self._need_voice().configure(settings)

    def _need_wa(self):
        if self.whatsapp is None:
            raise RpcError("WhatsApp Web não habilitado no agente (instale playwright e use --whatsapp-web)")
        return self.whatsapp

    async def wa_status(self, p: dict) -> dict:
        return await self._need_wa().status()

    async def wa_unread(self, p: dict) -> list:
        return await self._need_wa().unread(int(p.get("limit") or 20))

    async def wa_search(self, p: dict) -> list:
        return await self._need_wa().search_contact(_str(p, "query", 200))

    async def wa_send(self, p: dict) -> dict:
        return await self._need_wa().send(_str(p, "chat", 200), _str(p, "text", 4000))
