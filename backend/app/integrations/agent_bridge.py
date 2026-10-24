"""Ponte entre o backend e o agente local do Windows.

O agente abre um WebSocket autenticado para ``/api/agent/ws`` e atende
chamadas RPC (``clipboard.read``, ``clipboard.write``, ``apps.open`` ...). O
backend nunca executa comandos de sistema operacional diretamente: tudo que
toca o desktop passa pelo agente, que tem sua própria lista de métodos
permitidos.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger("jarvis.agent")


class AgentUnavailable(RuntimeError):
    def __init__(self, msg: str = "O agente local do Windows não está conectado. Inicie o JARVIS pelo start.bat (ele sobe o agente junto)."):
        super().__init__(msg)


class AgentError(RuntimeError):
    pass


Sender = Callable[[dict[str, Any]], Awaitable[None]]


class AgentBridge:
    def __init__(self) -> None:
        self._send: Sender | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self.info: dict[str, Any] = {}
        self._event_handlers: list[Callable[[str, dict], Awaitable[None]]] = []
        self._local: Callable[[str, dict], Awaitable[Any]] | None = None

    @property
    def connected(self) -> bool:
        return self._send is not None or self._local is not None

    def attach(self, send: Sender, info: dict[str, Any]) -> None:
        if self._send is not None:
            log.warning("Novo agente conectado; substituindo a conexão anterior")
            self._fail_pending("Conexão do agente substituída")
        self._send = send
        self.info = info

    def detach(self) -> None:
        self._send = None
        self.info = {}
        self._fail_pending("Agente desconectado")

    def attach_local(self, handler: Callable[[str, dict], Awaitable[Any]], info: dict[str, Any]) -> None:
        """Agente em processo (testes ou execução tudo-em-um)."""
        self._local = handler
        self.info = info

    def on_event(self, handler: Callable[[str, dict], Awaitable[None]]) -> None:
        self._event_handlers.append(handler)

    def _fail_pending(self, reason: str) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(AgentUnavailable(reason))
        self._pending.clear()

    def has_capability(self, cap: str) -> bool:
        return cap in set(self.info.get("capabilities", []))

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
        params = params or {}
        if self._local is not None:
            return await asyncio.wait_for(self._local(method, params), timeout)
        if self._send is None:
            raise AgentUnavailable()
        rid = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._send({"id": rid, "method": method, "params": params})
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError as e:
            raise AgentError(f"O agente não respondeu a '{method}' em {timeout:.0f}s") from e
        finally:
            self._pending.pop(rid, None)

    async def handle_message(self, msg: dict[str, Any]) -> None:
        if "id" in msg and ("result" in msg or "error" in msg):
            fut = self._pending.get(msg["id"])
            if fut and not fut.done():
                if msg.get("error"):
                    fut.set_exception(AgentError(str(msg["error"])))
                else:
                    fut.set_result(msg.get("result"))
            return
        if "event" in msg:
            for h in self._event_handlers:
                try:
                    await h(str(msg["event"]), msg.get("data") or {})
                except Exception:  # noqa: BLE001 - um handler com erro não derruba a conexão
                    log.exception("Falha ao tratar evento do agente: %s", msg.get("event"))
