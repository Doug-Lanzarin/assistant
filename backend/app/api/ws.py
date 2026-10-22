"""WebSockets: eventos para a interface e canal RPC do agente local."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger("jarvis.ws")
router = APIRouter()


def _origin_ok(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return True  # clientes não-navegador (agente, testes)
    s = ws.app.state.services
    host = ws.headers.get("host", "")
    allowed = set(s.env.cors_origins) | {f"http://{host}", f"https://{host}"}
    return origin in allowed


@router.websocket("/api/ws")
async def events_ws(ws: WebSocket):
    s = ws.app.state.services
    token = ws.query_params.get("token") or ws.cookies.get("jarvis_session")
    if not _origin_ok(ws) or not s.auth.validate(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    q = s.events.subscribe()
    try:
        await ws.send_json({"type": "hello", "data": {"agent": s.agent.connected}})

        async def pump():
            while True:
                ev = await q.get()
                await ws.send_json(ev)

        sender = asyncio.create_task(pump())
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
        finally:
            sender.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        s.events.unsubscribe(q)


@router.websocket("/api/agent/ws")
async def agent_ws(ws: WebSocket):
    s = ws.app.state.services
    expected = s.secrets.get("agent_token")
    supplied = ws.headers.get("x-jarvis-agent-token", "")
    if not expected or not hmac.compare_digest(supplied, expected) or ws.headers.get("origin"):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        hello = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
    except (TimeoutError, ValueError):
        await ws.close(code=4400)
        return
    info = hello.get("hello") if isinstance(hello, dict) else None
    if not isinstance(info, dict):
        await ws.close(code=4400)
        return

    async def send(payload: dict) -> None:
        await ws.send_text(json.dumps(payload, ensure_ascii=False))

    s.agent.attach(send, info)
    log.info("Agente conectado: %s", {k: info.get(k) for k in ("platform", "version", "capabilities")})
    await s.events.publish("agent", {"connected": True, "info": info})
    # Envia a configuração de voz atual ao agente.
    try:
        await send({"event": "config", "data": {"voice": s.settings.get("voice")}})
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict):
                if "event" in msg:
                    asyncio.create_task(s.agent.handle_message(msg))
                else:
                    await s.agent.handle_message(msg)
    except WebSocketDisconnect:
        pass
    finally:
        s.agent.detach()
        await s.events.publish("agent", {"connected": False})
        log.info("Agente desconectado")
