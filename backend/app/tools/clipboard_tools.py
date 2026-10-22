"""Ferramentas da memória da área de transferência."""

from __future__ import annotations

from pydantic import Field

from app.clipboard_memory.service import Ambiguous, ClipboardError
from app.integrations.agent_bridge import AgentError, AgentUnavailable
from app.orchestrator.registry import (
    NoParams,
    PrepareError,
    Risk,
    Tool,
    ToolContext,
    ToolParams,
    ToolRegistry,
    ToolResult,
)


def _err(e: Exception) -> ToolResult:
    data = {"options": e.options} if isinstance(e, Ambiguous) else None
    return ToolResult(ok=False, message=str(e), data=data)


def _remember(ctx: ToolContext, item: dict) -> None:
    ctx.state["last_clipboard_id"] = item["id"]


def _brief(item: dict) -> str:
    proj = f", projeto {item['project_name']}" if item.get("project_name") else ""
    return f"#{item['id']} “{item['title']}” ({item['category']}{proj})"


class SaveParams(ToolParams):
    title: str | None = Field(None, max_length=200, description="Título; se vazio, um título é sugerido")
    category: str | None = Field(None, max_length=40)
    project: str | None = Field(None, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=20)


async def _save(ctx: ToolContext, a: SaveParams) -> ToolResult:
    try:
        res = await ctx.services.clipboard.save_from_clipboard(a.title, a.category, a.project, a.tags)
    except (ClipboardError, AgentUnavailable, AgentError) as e:
        return _err(e)
    item = res["item"]
    _remember(ctx, item)
    if res["duplicate"]:
        return ToolResult(ok=True, message=f"Esse conteúdo já estava salvo como {_brief(item)}. Não dupliquei.", data=res)
    msg = f"Salvei o conteúdo copiado como {_brief(item)}, {item['char_count']} caracteres."
    if res.get("title_suggested"):
        msg += " Sugeri o título automaticamente; diga 'renomeie esse conteúdo para …' se quiser outro."
    if item["sensitive"]:
        msg += (" ⚠ Parece conter segredo (" + ", ".join(res.get("sensitive_reasons", [])) +
                "): guardei cifrado e ele não será enviado à IA.")
    return ToolResult(ok=True, message=msg, data=res)


class SearchParams(ToolParams):
    query: str = Field(..., min_length=1, max_length=300)
    category: str | None = None
    project: str | None = None
    limit: int = Field(8, ge=1, le=30)


async def _search(ctx: ToolContext, a: SearchParams) -> ToolResult:
    items = await ctx.services.clipboard.search(a.query, a.category, a.project, a.limit)
    if not items:
        return ToolResult(ok=True, message=f"Não encontrei registros salvos para '{a.query}'.", data=[])
    _remember(ctx, items[0])
    sources = [{"owner_type": "clipboard", "owner_id": i["id"], "title": i["title"], "citation": f"clipboard #{i['id']} '{i['title']}'"} for i in items]
    ctx.state["last_sources"] = sources
    lines = [f"{n}. {_brief(i)} — {i['preview'][:100].strip()}" for n, i in enumerate(items, 1)]
    hint = "\nDiga 'copie o primeiro' ou 'copie <nome>' para colocar no clipboard."
    return ToolResult(ok=True, message=f"Encontrei {len(items)} registro(s):\n" + "\n".join(lines) + hint, data=items,
                      sources=sources)


class ListParams(ToolParams):
    category: str | None = None
    project: str | None = None
    query: str | None = None
    limit: int = Field(30, ge=1, le=100)


async def _list(ctx: ToolContext, a: ListParams) -> ToolResult:
    items = ctx.services.clipboard.list(a.category, a.project, a.query, limit=a.limit)
    if not items and a.query and not a.category:
        items = await ctx.services.clipboard.search(a.query, limit=a.limit)
    if not items:
        what = a.category or a.query or ""
        return ToolResult(ok=True, message=f"Nenhum registro salvo{(' para ' + what) if what else ''}.", data=[])
    lines = [f"• {_brief(i)}" + (" 📌" if i["pinned"] else "") for i in items]
    return ToolResult(ok=True, message=f"{len(items)} registro(s):\n" + "\n".join(lines), data=items)


class RefParams(ToolParams):
    query: str | None = Field(None, max_length=300, description="Nome/descrição do registro; vazio = o último citado")
    item_id: int | None = None


async def _resolve(ctx: ToolContext, a: RefParams) -> dict:
    cm = ctx.services.clipboard
    if a.item_id:
        return cm.get(a.item_id, include_content=False)
    q = a.query
    if q and q.strip().lower() in {"o primeiro", "primeiro", "o 1", "1", "o segundo", "segundo", "2", "o terceiro", "3"}:
        idx = {"o primeiro": 0, "primeiro": 0, "o 1": 0, "1": 0, "o segundo": 1, "segundo": 1, "2": 1, "o terceiro": 2, "3": 2}[q.strip().lower()]
        last = ctx.state.get("last_sources") or []
        clip = [s for s in last if s.get("owner_type") == "clipboard"]
        if idx < len(clip):
            return cm.get(clip[idx]["owner_id"], include_content=False)
    return await cm.resolve(q, ctx.state.get("last_clipboard_id"))


async def _copy(ctx: ToolContext, a: RefParams) -> ToolResult:
    try:
        item = await _resolve(ctx, a)
        item = await ctx.services.clipboard.copy_to_clipboard(item["id"])
    except (ClipboardError, AgentUnavailable, AgentError) as e:
        return _err(e)
    _remember(ctx, item)
    return ToolResult(ok=True, message=f"Copiei {_brief(item)} para a área de transferência. Pode colar com Ctrl+V.", data=item)


async def _prepare_ref(ctx: ToolContext, a):
    try:
        item = await _resolve(ctx, a)
    except Ambiguous as e:
        opts = "\n".join(f"• #{o['id']} {o['title']}" for o in e.options[:5])
        raise PrepareError(f"Encontrei mais de um registro:\n{opts}\nQual deles? (diga o nome ou o número)", data=e.options) from e
    except ClipboardError as e:
        raise PrepareError(str(e)) from e
    return a.model_copy(update={"item_id": item["id"], "query": a.query or item["title"]})


async def _update(ctx: ToolContext, a: RefParams) -> ToolResult:
    try:
        item = await ctx.services.clipboard.update_from_clipboard(a.item_id)  # type: ignore[arg-type]
    except (ClipboardError, AgentUnavailable, AgentError) as e:
        return _err(e)
    _remember(ctx, item)
    return ToolResult(ok=True, message=f"Atualizei {_brief(item)} com o conteúdo copiado agora (a versão anterior ficou no histórico).", data=item)


class RenameParams(RefParams):
    new_title: str = Field(..., min_length=1, max_length=200)


async def _rename(ctx: ToolContext, a: RenameParams) -> ToolResult:
    try:
        old = ctx.services.clipboard.get(a.item_id, include_content=False)  # type: ignore[arg-type]
        item = await ctx.services.clipboard.update_meta(old["id"], title=a.new_title)
    except ClipboardError as e:
        return _err(e)
    _remember(ctx, item)
    return ToolResult(ok=True, message=f"Renomeei “{old['title']}” para “{item['title']}”.", data=item)


class MetaParams(RefParams):
    category: str | None = None
    project: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None


async def _meta(ctx: ToolContext, a: MetaParams) -> ToolResult:
    try:
        item = await ctx.services.clipboard.update_meta(a.item_id, None, a.category, a.project, a.tags, a.pinned)  # type: ignore[arg-type]
    except ClipboardError as e:
        return _err(e)
    return ToolResult(ok=True, message=f"Atualizei {_brief(item)}.", data=item)


async def _delete(ctx: ToolContext, a: RefParams) -> ToolResult:
    try:
        item = ctx.services.clipboard.get(a.item_id, include_content=False)  # type: ignore[arg-type]
        ctx.services.clipboard.delete(item["id"])
    except ClipboardError as e:
        return _err(e)
    ctx.state.pop("last_clipboard_id", None)
    return ToolResult(ok=True, message=f"Apaguei o registro “{item['title']}”.", data={"id": item["id"]})


async def _read_current(ctx: ToolContext, a: NoParams) -> ToolResult:
    from app.security.sensitive import detect_sensitive

    try:
        clip = await ctx.services.clipboard.read_system_clipboard()
    except (AgentUnavailable, AgentError) as e:
        return _err(e)
    if clip.get("format") != "text":
        return ToolResult(ok=True, message=f"O clipboard contém: {clip.get('format')}.", data={"format": clip.get("format")})
    text = clip.get("text", "")
    if detect_sensitive(text).sensitive and not ctx.services.settings.get("privacy")["clipboard_sensitive_to_ai"]:
        return ToolResult(ok=True, message="O clipboard contém o que parece ser um segredo; não vou exibi-lo.",
                          data={"format": "text", "sensitive": True, "chars": len(text)})
    return ToolResult(ok=True, message=f"Conteúdo atual do clipboard ({len(text)} caracteres):\n{text[:4000]}",
                      data={"format": "text", "chars": len(text)})


def _ref_summary(verb: str):
    return lambda a: f"{verb} o registro #{a.item_id} “{a.query}”"


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("clipboard_save", "Lê o conteúdo atual do clipboard do Windows e o salva com título, categoria e projeto",
                      SaveParams, _save, Risk.REVERSIBLE, "clipboard.save", "clipboard", timeout=15))
    reg.register(Tool("clipboard_search", "Procura registros salvos do clipboard por título, categoria, projeto e conteúdo",
                      SearchParams, _search, Risk.READ, "clipboard.read", "clipboard"))
    reg.register(Tool("clipboard_list", "Lista registros salvos do clipboard (filtros: categoria, projeto, texto)",
                      ListParams, _list, Risk.READ, "clipboard.read", "clipboard"))
    reg.register(Tool("clipboard_copy", "Coloca o conteúdo original de um registro salvo no clipboard do Windows para colar",
                      RefParams, _copy, Risk.REVERSIBLE, "clipboard.write", "clipboard", timeout=15))
    reg.register(Tool("clipboard_update_from_clipboard", "Substitui o conteúdo de um registro salvo pelo que está no clipboard agora",
                      RefParams, _update, Risk.REVERSIBLE, "clipboard.save", "clipboard", timeout=15, prepare=_prepare_ref,
                      summarize=_ref_summary("Substituir o conteúdo de")))
    reg.register(Tool("clipboard_rename", "Renomeia um registro salvo do clipboard", RenameParams, _rename, Risk.REVERSIBLE,
                      "clipboard.save", "clipboard", prepare=_prepare_ref,
                      summarize=lambda a: f"Renomear #{a.item_id} “{a.query}” para “{a.new_title}”"))
    reg.register(Tool("clipboard_update_meta", "Altera categoria, projeto, etiquetas ou fixação de um registro salvo",
                      MetaParams, _meta, Risk.REVERSIBLE, "clipboard.save", "clipboard", prepare=_prepare_ref))
    reg.register(Tool("clipboard_delete", "Apaga definitivamente um registro salvo do clipboard", RefParams, _delete,
                      Risk.CRITICAL, "clipboard.delete", "clipboard", prepare=_prepare_ref,
                      summarize=_ref_summary("Apagar definitivamente")))
    reg.register(Tool("clipboard_read_current", "Mostra o texto que está agora no clipboard do Windows (segredos são ocultados)",
                      NoParams, _read_current, Risk.READ, "clipboard.read_live", "clipboard", timeout=10))
