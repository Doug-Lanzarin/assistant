from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import current_user, services
from app.services.container import Services

router = APIRouter(prefix="/api", tags=["chat"], dependencies=[Depends(current_user)])


class ChatIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    conversation_id: int | None = None
    origin: str = Field("user", pattern=r"^(user|voice)$")


class ConfirmIn(BaseModel):
    approve: bool


class ToolRunIn(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)
    conversation_id: int | None = None


@router.post("/chat")
async def chat(body: ChatIn, s: Services = Depends(services)):
    task = asyncio.create_task(s.orchestrator.handle(body.text, body.conversation_id, body.origin))
    try:
        return await task
    except asyncio.CancelledError:
        return {"conversation_id": body.conversation_id, "text": "Tarefa cancelada.", "actions": [], "cancelled": True}


@router.post("/chat/cancel")
async def cancel(conversation_id: int | None = None, s: Services = Depends(services)):
    if conversation_id is None:
        n = await s.orchestrator.cancel_all()
        return {"cancelled": n}
    return {"cancelled": int(await s.orchestrator.cancel_conversation(conversation_id))}


@router.get("/conversations")
def conversations(s: Services = Depends(services)):
    return s.orchestrator.conversations()


@router.get("/conversations/{cid}/messages")
def messages(cid: int, s: Services = Depends(services)):
    return s.orchestrator.messages(cid)


@router.delete("/conversations/{cid}")
def delete_conversation(cid: int, s: Services = Depends(services)):
    s.db.execute("DELETE FROM conversations WHERE id=?", (cid,))
    s.conversation_state.pop(cid, None)
    return {"ok": True}


@router.get("/actions/pending")
def pending(conversation_id: int | None = None, s: Services = Depends(services)):
    return s.executor.list_pending(conversation_id)


@router.post("/actions/{pid}/confirm")
async def confirm(pid: str, body: ConfirmIn, s: Services = Depends(services)):
    row = s.db.query_one("SELECT conversation_id FROM pending_actions WHERE id=?", (pid,))
    state = s.state_for(row["conversation_id"]) if row and row["conversation_id"] else {}
    out = await s.executor.confirm(pid, body.approve, state)
    if row and row["conversation_id"]:
        s.orchestrator._save_message(row["conversation_id"], "assistant", out.message, {"provider": "confirmação", "actions": [out.to_dict()]})
    return out.to_dict()


@router.post("/tools/run")
async def run_tool(body: ToolRunIn, s: Services = Depends(services)):
    """Execução direta de uma ferramenta pela interface (mesma política e confirmação)."""
    from app.orchestrator.registry import ToolContext

    if body.tool not in s.registry:
        raise HTTPException(404, "Ferramenta não registrada")
    ctx = ToolContext(s, body.conversation_id, "api", state=s.state_for(body.conversation_id))
    out = await s.executor.run(body.tool, body.args, ctx)
    return out.to_dict()


@router.get("/tools")
def tools(s: Services = Depends(services)):
    disabled = set(s.settings.get("policy")["disabled_permissions"])
    return [
        {"name": t.name, "description": t.description, "risk": int(t.risk), "risk_label": t.risk.label,
         "permission": t.permission, "category": t.category, "always_confirm": bool(t.always_confirm),
         "enabled": t.permission not in disabled, "schema": t.json_schema(), "llm": t.expose_to_llm}
        for t in s.registry.all()
    ]


@router.get("/audit")
def audit(limit: int = 100, s: Services = Depends(services)):
    return s.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(limit, 1000),))


@router.post("/emergency/stop")
async def emergency_stop(s: Services = Depends(services)):
    from app.orchestrator.registry import ToolContext

    out = await s.executor.run("emergency_stop", {}, ToolContext(s, None, "api"))
    return out.to_dict()


@router.post("/emergency/resume")
async def emergency_resume(s: Services = Depends(services)):
    from app.orchestrator.registry import ToolContext

    out = await s.executor.run("emergency_resume", {}, ToolContext(s, None, "api"))
    return out.to_dict()
