"""Ferramentas de WhatsApp. Conteúdo de mensagens é sempre dado não confiável."""

from __future__ import annotations

from pydantic import Field

from app.integrations.agent_bridge import AgentError, AgentUnavailable
from app.integrations.whatsapp.service import WhatsAppError
from app.orchestrator.registry import NoParams, PrepareError, Risk, Tool, ToolContext, ToolParams, ToolRegistry, ToolResult


async def _status(ctx: ToolContext, a: NoParams) -> ToolResult:
    st = await ctx.services.whatsapp.status()
    return ToolResult(ok=True, message=f"WhatsApp (modo {st['mode']}): {st['detail']} Mensagens não lidas guardadas: {st['unread']}.", data=st)


class ReadParams(ToolParams):
    only_unread: bool = True
    limit: int = Field(20, ge=1, le=100)


async def _read(ctx: ToolContext, a: ReadParams) -> ToolResult:
    wa = ctx.services.whatsapp
    st = await wa.status()
    msgs = await wa.read(a.only_unread, a.limit)
    if not msgs:
        detail = "" if st["can_read"] else f" ({st['detail']})"
        return ToolResult(ok=True, message=f"Nenhuma mensagem {'nova ' if a.only_unread else ''}disponível{detail}.", data=[])
    lines = [f"• {m['sender']}: {m['text'][:300]}" for m in reversed(msgs)]
    note = " (somente o que apareceu nas notificações)" if st["mode"] == "notifications" else ""
    return ToolResult(ok=True, message=f"{len(msgs)} mensagem(ns){note}:\n" + "\n".join(lines), data=msgs, untrusted=True)


class SearchParams(ToolParams):
    query: str = Field(..., min_length=1, max_length=200)


async def _search(ctx: ToolContext, a: SearchParams) -> ToolResult:
    msgs = ctx.services.whatsapp.search(a.query)
    if not msgs:
        return ToolResult(ok=True, message=f"Nenhuma mensagem acessível contém '{a.query}'. Só pesquiso o que o JARVIS já recebeu.", data=[])
    lines = [f"• {m['received_at'][:16].replace('T', ' ')} {m['sender']}: {m['text'][:200]}" for m in msgs]
    return ToolResult(ok=True, message="\n".join(lines), data=msgs, untrusted=True)


class SendParams(ToolParams):
    to: str = Field(..., min_length=1, max_length=120, description="Nome do contato")
    text: str = Field(..., min_length=1, max_length=2000)
    resolved_name: str | None = Field(None, description="Preenchido automaticamente")
    resolved_address: str | None = Field(None, description="Preenchido automaticamente")


async def _send_prepare(ctx: ToolContext, a: SendParams) -> SendParams:
    wa = ctx.services.whatsapp
    if wa.mode not in {"web", "business"}:
        raise PrepareError("Envio indisponível: configure o WhatsApp no modo 'web' ou 'business' em Configurações → WhatsApp.")
    matches = await wa.resolve_contact(a.to)
    if not matches:
        raise PrepareError(f"Não encontrei o contato '{a.to}'. Cadastre-o em WhatsApp → Contatos ou confira o nome.")
    if len(matches) > 1:
        opts = "; ".join(f"{m['name']}" for m in matches[:6])
        raise PrepareError(f"Encontrei mais de um contato para '{a.to}': {opts}. Para qual deles?", data=matches)
    m = matches[0]
    return a.model_copy(update={"resolved_name": m["name"], "resolved_address": m["address"]})


async def _send(ctx: ToolContext, a: SendParams) -> ToolResult:
    try:
        res = await ctx.services.whatsapp.send(a.resolved_name or a.to, a.resolved_address, a.text)
    except (WhatsAppError, AgentUnavailable, AgentError) as e:
        return ToolResult(ok=False, message=f"A mensagem NÃO foi enviada: {e}")
    return ToolResult(ok=True, message=f"Mensagem enviada para {a.resolved_name} (confirmação: {res['evidence']}).", data=res)


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("whatsapp_status", "Mostra o estado da integração com o WhatsApp", NoParams, _status, Risk.READ,
                      "whatsapp.read", "whatsapp", timeout=20))
    reg.register(Tool("whatsapp_read", "Lê mensagens do WhatsApp acessíveis ao JARVIS (não lidas por padrão)", ReadParams, _read,
                      Risk.READ, "whatsapp.read", "whatsapp", timeout=40))
    reg.register(Tool("whatsapp_search", "Procura nas mensagens do WhatsApp já recebidas pelo JARVIS", SearchParams, _search,
                      Risk.READ, "whatsapp.read", "whatsapp"))
    reg.register(Tool("whatsapp_send", "Envia uma mensagem de WhatsApp a um contato (sempre pede confirmação)", SendParams, _send,
                      Risk.EXTERNAL, "whatsapp.send", "whatsapp", timeout=90, always_confirm=True, prepare=_send_prepare,
                      summarize=lambda a: f"Encontrei {a.resolved_name}. Vou enviar: “{a.text}”. Posso enviar?"))
