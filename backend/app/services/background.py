"""Tarefas em segundo plano: lembretes, consolidação, limpeza e reinício controlado."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from app.memory.consolidation import Consolidator
from app.orchestrator.orchestrator import speakable

log = logging.getLogger("jarvis.background")

RESTART_EXIT_CODE = 3


class Background:
    def __init__(self, services):
        self.s = services
        self.consolidator = Consolidator(services)
        self._tasks: list[asyncio.Task] = []
        self._restart_requested = False
        self._last_consolidation = time.monotonic()
        self.consolidating = False
        self.on_restart = None  # callback definido pelo servidor

    def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._loop(), name="jarvis-background"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks.clear()

    def request_restart(self) -> None:
        self._restart_requested = True

    async def _loop(self) -> None:
        tick = 0
        while True:
            try:
                await self.fire_due_reminders()
                if tick % 60 == 0:
                    self.s.auth.purge_expired()
                await self._maybe_consolidate()
                if self._restart_requested:
                    log.warning("Reinício controlado solicitado")
                    await asyncio.sleep(1.5)
                    if self.on_restart:
                        self.on_restart()
                    return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - o laço nunca deve morrer
                log.exception("Falha no laço de segundo plano")
            tick += 1
            await asyncio.sleep(5)

    async def fire_due_reminders(self) -> int:
        due = self.s.brain.due_reminders()
        for r in due:
            self.s.brain.mark_fired(r["id"])
            text = f"Lembrete: {r['text']}"
            await self.s.events.publish("reminder", {"id": r["id"], "text": r["text"]})
            if self.s.agent.connected:
                try:
                    await self.s.agent.call("notify", {"title": "JARVIS — lembrete", "message": r["text"]}, timeout=5)
                    if self.s.settings.get("voice")["speak_responses"]:
                        await self.s.agent.call("voice.speak", {"text": speakable(text)}, timeout=5)
                except Exception as e:  # noqa: BLE001
                    log.warning("Falha ao notificar lembrete: %s", e)
        return len(due)

    async def _maybe_consolidate(self) -> None:
        cfg = self.s.settings.get("memory")
        if not cfg["auto_consolidate"] or self.consolidating:
            return
        if time.monotonic() - self._last_consolidation < cfg["consolidate_interval_min"] * 60:
            return
        self._last_consolidation = time.monotonic()
        asyncio.create_task(self.run_consolidation())

    async def run_consolidation(self, use_ai: bool = True) -> dict:
        if self.consolidating:
            return {"status": "já em execução"}
        self.consolidating = True
        try:
            return await self.consolidator.run(use_ai=use_ai)
        finally:
            self.consolidating = False
