"""APIs de casa inteligente e WhatsApp."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import current_user, services
from app.integrations.home_assistant.client import HAError
from app.integrations.home_assistant.service import Ambiguity
from app.integrations.whatsapp.service import WhatsAppError
from app.orchestrator.registry import ToolContext
from app.services.container import Services

home = APIRouter(prefix="/api/home", tags=["casa"], dependencies=[Depends(current_user)])
wa = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"], dependencies=[Depends(current_user)])
wa_public = APIRouter(prefix="/api/whatsapp", tags=["whatsapp-webhook"])


class AliasIn(BaseModel):
    aliases: list[str] | None = None
    room: str | None = None
    name: str | None = None


class CommandIn(BaseModel):
    tool: str = Field(..., pattern=r"^(home_turn|climate_set|home_scene|home_state|home_sensor)$")
    args: dict = Field(default_factory=dict)


def _ha_fail(e: Exception):
    if isinstance(e, Ambiguity):
        raise HTTPException(409, {"message": str(e), "options": e.options})
    raise HTTPException(502, str(e))


@home.get("/status")
async def home_status(s: Services = Depends(services)):
    cfg = s.settings.get("home_assistant")
    out = {"configured": s.home.configured(), "url": cfg.get("url"), "devices": len(s.home.devices()),
           "tcl": s.settings.get("tcl"), "alexa": s.settings.get("alexa")}
    if out["configured"]:
        try:
            out["connection"] = await s.home.test_connection()
        except HAError as e:
            out["connection"] = {"ok": False, "message": str(e)}
    return out


@home.post("/sync")
async def sync(s: Services = Depends(services)):
    try:
        return await s.home.sync()
    except HAError as e:
        _ha_fail(e)


@home.get("/devices")
def devices(domain: str | None = None, s: Services = Depends(services)):
    return s.home.devices(domain)


@home.patch("/devices/{entity_id}")
def set_alias(entity_id: str, body: AliasIn, s: Services = Depends(services)):
    try:
        return s.home.set_alias(entity_id, body.aliases, body.room, body.name)
    except HAError as e:
        raise HTTPException(404, str(e)) from e


@home.post("/command")
async def command(body: CommandIn, s: Services = Depends(services)):
    out = await s.executor.run(body.tool, body.args, ToolContext(s, None, "api"))
    return out.to_dict()


# -- WhatsApp --------------------------------------------------------------------------------
class ContactIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    phone: str | None = None
    aliases: list[str] = Field(default_factory=list)


class SendIn(BaseModel):
    to: str = Field(..., min_length=1, max_length=120)
    text: str = Field(..., min_length=1, max_length=2000)
    conversation_id: int | None = None


@wa.get("/status")
async def wa_status(s: Services = Depends(services)):
    return await s.whatsapp.status()


@wa.get("/messages")
async def wa_messages(only_unread: bool = False, limit: int = 50, refresh: bool = False, s: Services = Depends(services)):
    if refresh:
        return await s.whatsapp.read(only_unread, limit, mark_read=False)
    sql = "SELECT * FROM whatsapp_messages" + (" WHERE is_read=0" if only_unread else "") + " ORDER BY received_at DESC LIMIT ?"
    return s.db.query(sql, (min(limit, 500),))


@wa.post("/messages/read-all")
def wa_mark_read(s: Services = Depends(services)):
    s.db.execute("UPDATE whatsapp_messages SET is_read=1 WHERE is_read=0")
    return {"ok": True}


@wa.get("/contacts")
def contacts(s: Services = Depends(services)):
    return s.whatsapp.list_contacts()


@wa.post("/contacts")
def add_contact(body: ContactIn, s: Services = Depends(services)):
    try:
        return s.whatsapp.add_contact(body.name, body.phone, body.aliases)
    except WhatsAppError as e:
        raise HTTPException(400, str(e)) from e


@wa.delete("/contacts/{cid}")
def delete_contact(cid: int, s: Services = Depends(services)):
    s.whatsapp.delete_contact(cid)
    return {"ok": True}


@wa.get("/outbox")
def outbox(s: Services = Depends(services)):
    return s.whatsapp.outbox()


@wa.post("/send")
async def send(body: SendIn, s: Services = Depends(services)):
    """Prepara o envio: sempre cria uma ação pendente que o usuário precisa confirmar."""
    out = await s.executor.run("whatsapp_send", {"to": body.to, "text": body.text},
                               ToolContext(s, body.conversation_id, "api", state=s.state_for(body.conversation_id)))
    return out.to_dict()


# Webhook da Cloud API (público, protegido por verify token e assinatura HMAC).
@wa_public.get("/webhook")
def verify(mode: str | None = Query(None, alias="hub.mode"), token: str | None = Query(None, alias="hub.verify_token"),
           challenge: str | None = Query(None, alias="hub.challenge"), s: Services = Depends(services)):
    res = s.whatsapp.verify_webhook(mode, token, challenge)
    if res is None:
        raise HTTPException(403, "Verificação recusada")
    return Response(res, media_type="text/plain")


@wa_public.post("/webhook")
async def webhook(request: Request, s: Services = Depends(services)):
    raw = await request.body()
    if not s.whatsapp.check_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Assinatura inválida")
    try:
        payload = json.loads(raw)
    except ValueError as e:
        raise HTTPException(400, "JSON inválido") from e
    n = await s.whatsapp.ingest_webhook(payload)
    return {"ok": True, "ingested": n}
