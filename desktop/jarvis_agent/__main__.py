"""Ponto de entrada do agente local: ``python -m jarvis_agent``.

Conecta-se ao backend em ws://127.0.0.1:8765/api/agent/ws com o token gerado
pelo backend (data/secrets/agent.token, protegido por DPAPI no Windows),
reconecta automaticamente e encerra de forma limpa com Ctrl+C ou pelo menu
da bandeja.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .rpc import Dispatcher, RpcError

REPO = Path(__file__).resolve().parents[2]
log = logging.getLogger("jarvis_agent")


def read_token(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"DPAPI"):
        sys.path.insert(0, str(REPO / "backend"))
        from app.security.secrets import _Dpapi  # reutiliza o wrapper DPAPI

        return _Dpapi().unprotect(data[5:]).decode()
    return data.decode().strip()


class SingleInstance:
    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")  # noqa: SIM115 - mantido aberto durante a execução
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(str(os.getpid()))
        self.fh.flush()
        return True


class Agent:
    def __init__(self, url: str, token: str, dispatcher: Dispatcher):
        self.url = url
        self.token = token
        self.d = dispatcher
        self.ws = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop_event = asyncio.Event()
        self.connected = False

    def emit(self, event: str, data: dict) -> None:
        """Pode ser chamado de qualquer thread (voz, notificações)."""
        if self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._send({"event": event, "data": data}), self.loop)

    async def _send(self, payload: dict) -> None:
        if self.ws is not None:
            try:
                await self.ws.send(json.dumps(payload, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                log.debug("Envio falhou: %s", e)

    async def _handle(self, msg: dict) -> None:
        if "event" in msg:
            if msg["event"] == "config" and self.d.voice is not None:
                voice_cfg = (msg.get("data") or {}).get("voice") or {}
                await asyncio.to_thread(self.d.voice.configure, voice_cfg)
            return
        rid = msg.get("id")
        try:
            result = await self.d.dispatch(str(msg.get("method")), msg.get("params"))
            await self._send({"id": rid, "result": result})
        except RpcError as e:
            await self._send({"id": rid, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            log.exception("Falha ao executar %s", msg.get("method"))
            await self._send({"id": rid, "error": f"{type(e).__name__}: {e}"})

    async def run(self) -> None:
        import websockets

        self.loop = asyncio.get_running_loop()
        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                async with websockets.connect(self.url, additional_headers={"X-Jarvis-Agent-Token": self.token},
                                              max_size=8 * 1024 * 1024, ping_interval=20) as ws:
                    self.ws = ws
                    await ws.send(json.dumps({"hello": self.d.info()}))
                    self.connected = True
                    backoff = 1.0
                    log.info("Conectado ao backend %s", self.url)
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except ValueError:
                            continue
                        asyncio.create_task(self._handle(msg))
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                log.warning("Sem conexão com o backend (%s). Nova tentativa em %.0fs", e, backoff)
            finally:
                self.ws = None
                self.connected = False
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=backoff)
            except TimeoutError:
                pass
            backoff = min(backoff * 2, 30)


def start_tray(agent: Agent, panel_url: str, notifier) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        log.info("pystray/Pillow não instalados: sem ícone na bandeja")
        return
    img = Image.new("RGB", (64, 64), "#0b1530")
    dr = ImageDraw.Draw(img)
    dr.ellipse((8, 8, 56, 56), outline="#3fb6ff", width=5)
    dr.ellipse((24, 24, 40, 40), fill="#2fe0a0")

    def open_panel(icon, item):
        import webbrowser

        webbrowser.open(panel_url)

    def listen(icon, item):
        if agent.d.voice:
            threading.Thread(target=agent.d.voice.listen_once, daemon=True).start()

    def quit_(icon, item):
        icon.stop()
        if agent.loop:
            agent.loop.call_soon_threadsafe(agent.stop_event.set)

    menu = pystray.Menu(pystray.MenuItem("Abrir painel", open_panel, default=True),
                        pystray.MenuItem("Falar agora", listen), pystray.MenuItem("Sair", quit_))
    icon = pystray.Icon("jarvis", img, "JARVIS", menu)
    notifier.tray = icon
    threading.Thread(target=icon.run, daemon=True, name="tray").start()


def main() -> int:
    ap = argparse.ArgumentParser(description="Agente local do JARVIS")
    ap.add_argument("--backend", default=os.environ.get("JARVIS_BACKEND", "ws://127.0.0.1:8765/api/agent/ws"))
    ap.add_argument("--data-dir", default=os.environ.get("JARVIS_DATA_DIR", str(REPO / "data")))
    ap.add_argument("--no-voice", action="store_true", help="desativa o módulo de voz")
    ap.add_argument("--whatsapp-web", action="store_true", help="habilita o adaptador WhatsApp Web (Playwright)")
    ap.add_argument("--no-tray", action="store_true")
    ap.add_argument("--hotkey", default="ctrl+alt+j", help="atalho global para falar (requer pacote 'keyboard')")
    args = ap.parse_args()

    data = Path(args.data_dir)
    (data / "logs").mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(data / "logs" / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    lock = SingleInstance(data / "agent.lock")
    if not lock.acquire():
        log.error("Já existe um agente do JARVIS em execução.")
        return 2
    token_file = data / "secrets" / "agent.token"
    if not token_file.exists():
        log.error("Token do agente não encontrado em %s. Inicie o backend primeiro.", token_file)
        return 3
    token = read_token(token_file)

    from .actions import Notifier

    notifier = Notifier()
    agent_holder: dict = {}

    def emit(event: str, payload: dict) -> None:
        a = agent_holder.get("agent")
        if a:
            a.emit(event, payload)

    voice = None
    if not args.no_voice:
        from .voice import VoiceEngine

        voice = VoiceEngine(emit, models_dir=str(data / "models" / "whisper"))
    wa = None
    if args.whatsapp_web:
        from .whatsapp_web import WhatsAppWeb

        if WhatsAppWeb.installed():
            wa = WhatsAppWeb(data / "whatsapp-session", REPO / "config" / "whatsapp_selectors.json")
        else:
            log.warning("Playwright não instalado; WhatsApp Web desativado")
    from .notifications import NotificationWatcher

    watcher = NotificationWatcher(emit)
    dispatcher = Dispatcher(voice=voice, whatsapp=wa, notifier=notifier, notifications=watcher, emit=emit)
    agent = Agent(args.backend, token, dispatcher)
    agent_holder["agent"] = agent
    log.info("Agente JARVIS %s iniciando (clipboard: %s)", __version__, dispatcher.clipboard.name)

    if not args.no_tray:
        start_tray(agent, args.backend.replace("ws://", "http://").replace("/api/agent/ws", "/"), notifier)
    if voice is not None and args.hotkey:
        try:
            import keyboard  # type: ignore[import-not-found]

            keyboard.add_hotkey(args.hotkey, lambda: threading.Thread(target=voice.listen_once, daemon=True).start())
            log.info("Atalho de voz: %s", args.hotkey)
        except Exception as e:  # noqa: BLE001
            log.info("Atalho global indisponível (%s)", e)

    async def runner():
        tasks = [asyncio.create_task(agent.run())]
        if NotificationWatcher.supported():
            tasks.append(asyncio.create_task(watcher.run()))
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, agent.stop_event.set)
            except (NotImplementedError, RuntimeError):
                pass
        await agent.stop_event.wait()
        for t in tasks:
            t.cancel()
        if wa:
            await wa.close()

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        pass
    log.info("Agente encerrado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
