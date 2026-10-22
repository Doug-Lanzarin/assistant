"""Ferramentas do segundo cérebro: memórias, busca, grafo, tarefas e lembretes."""

from __future__ import annotations

from datetime import UTC
from typing import Literal

from pydantic import Field

from app.memory.store import KIND_LABELS
from app.orchestrator.dateparse import parse_period, parse_when
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
from app.tools.core_tools import fmt_dt

MemoryKind = Literal["note", "idea", "decision", "fact", "preference", "learning", "goal", "event", "project", "episodic"]


def _period_bounds(text: str | None) -> tuple[str | None, str | None, str | None]:
    if not text:
        return None, None, None
    p = parse_period(text)
    if not p:
        return None, None, None
    return p[0].astimezone(UTC).isoformat(timespec="seconds"), p[1].astimezone(UTC).isoformat(timespec="seconds"), p[2]


def _format_hits(hits: list[dict]) -> str:
    lines = []
    for i, h in enumerate(hits, 1):
        flag = ""
        if h.get("stale"):
            flag = " ⚠ possivelmente desatualizada"
        if h.get("status") in {"inferred"}:
            flag += " (inferência não confirmada)"
        if h.get("status") == "contradicted":
            flag += " ⚠ contradita"
        lines.append(f"{i}. {h['title']} — {h['snippet'][:160].strip()} [{h['citation']}]{flag}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- busca
class SearchParams(ToolParams):
    query: str = Field(..., min_length=1, max_length=500, description="O que procurar")
    kind: MemoryKind | None = Field(None, description="Filtrar por tipo de memória")
    project: str | None = Field(None, description="Filtrar por projeto")
    period_text: str | None = Field(None, description="Período em linguagem natural, ex.: 'mês passado'")
    sources: list[Literal["memory", "document", "clipboard"]] | None = None
    limit: int = Field(6, ge=1, le=20)


async def _brain_search(ctx: ToolContext, a: SearchParams) -> ToolResult:
    start, end, label = _period_bounds(a.period_text or a.query)
    hits = await ctx.services.brain.search(
        a.query, kinds=[a.kind] if a.kind else None, owner_types=a.sources, project=a.project,
        start=start, end=end, limit=a.limit,
    )
    if not hits:
        return ToolResult(ok=True, message=f"Não encontrei nada na memória sobre '{a.query}'.", data=[])
    ctx.state["last_sources"] = hits
    if hits[0]["owner_type"] == "memory":
        ctx.state["last_memory_id"] = hits[0]["owner_id"]
    untrusted = any(h["owner_type"] == "document" or h.get("source") not in (None, "user", "clipboard") for h in hits)
    when = f" ({label})" if label else ""
    return ToolResult(ok=True, message=f"Encontrei {len(hits)} resultado(s){when}:\n" + _format_hits(hits),
                      data=hits, sources=hits, untrusted=untrusted)


class AddParams(ToolParams):
    content: str = Field(..., min_length=1, max_length=20000)
    kind: MemoryKind = "note"
    title: str | None = Field(None, max_length=200)
    project: str | None = Field(None, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=20)


async def _memory_add(ctx: ToolContext, a: AddParams) -> ToolResult:
    source = "user" if ctx.origin in {"user", "voice", "api"} else ctx.origin
    status = "explicit" if source == "user" else "inferred"
    m = await ctx.services.brain.add(a.content, a.kind, a.title or "", source=source, status=status,
                                     confidence=1.0 if status == "explicit" else 0.6, project=a.project, tags=a.tags)
    ctx.state["last_memory_id"] = m["id"]
    where = f" no projeto {m['project_name']}" if m.get("project_name") else ""
    return ToolResult(ok=True, message=f"Registrei {KIND_LABELS.get(a.kind, a.kind)} #{m['id']}{where}.", data=m)


class ForgetParams(ToolParams):
    query: str | None = Field(None, max_length=500, description="Descrição da memória a esquecer")
    memory_id: int | None = None
    resolved_ids: list[int] = Field(default_factory=list, description="Preenchido automaticamente")
    resolved_titles: list[str] = Field(default_factory=list, description="Preenchido automaticamente")


async def _forget_prepare(ctx: ToolContext, a: ForgetParams) -> ForgetParams:
    brain = ctx.services.brain
    if a.memory_id:
        m = brain.get(a.memory_id)
        return a.model_copy(update={"resolved_ids": [m["id"]], "resolved_titles": [m["title"] or m["content"][:80]]})
    if not a.query:
        last = ctx.state.get("last_memory_id")
        if not last:
            raise PrepareError("Qual informação devo esquecer? Diga do que se trata.")
        m = brain.get(last)
        return a.model_copy(update={"resolved_ids": [m["id"]], "resolved_titles": [m["title"] or m["content"][:80]]})
    hits = [h for h in await brain.search(a.query, owner_types=["memory"], limit=5)]
    if not hits:
        raise PrepareError(f"Não encontrei memória sobre '{a.query}'.")
    if len(hits) > 1 and hits[0]["score"] < hits[1]["score"] * 1.5:
        options = "\n".join(f"• #{h['owner_id']} {h['title']}" for h in hits[:5])
        raise PrepareError(f"Encontrei mais de uma memória possível:\n{options}\nQual delas devo esquecer? (diga o número)",
                           data=hits)
    h = hits[0]
    return a.model_copy(update={"resolved_ids": [h["owner_id"]], "resolved_titles": [h["title"]]})


async def _forget(ctx: ToolContext, a: ForgetParams) -> ToolResult:
    total = {"memories": 0, "chunks": 0, "graph_links": 0}
    for mid in a.resolved_ids:
        try:
            res = ctx.services.brain.delete(mid)
        except KeyError:
            continue
        for k, v in res.items():
            total[k] += v
    if not total["memories"]:
        return ToolResult(ok=False, message="Nada foi apagado (memória não encontrada).")
    ctx.state.pop("last_memory_id", None)
    return ToolResult(ok=True, message=(f"Esqueci {total['memories']} memória(s) e removi {total['chunks']} trecho(s) "
                                        f"indexado(s) e {total['graph_links']} ligação(ões) do grafo."), data=total)


class TimelineParams(ToolParams):
    period_text: str = Field("últimos 7 dias", max_length=300)
    project: str | None = None


async def _timeline(ctx: ToolContext, a: TimelineParams) -> ToolResult:
    start, end, label = _period_bounds(a.period_text)
    if not start:
        start, end, label = _period_bounds("últimos 7 dias")
    project_id = None
    if a.project:
        p = ctx.services.brain.find_project(a.project)
        if not p:
            return ToolResult(ok=True, message=f"Não conheço o projeto '{a.project}'.", data=[])
        project_id = p["id"]
    items = ctx.services.brain.timeline(start, end, project_id, limit=80)
    if not items:
        return ToolResult(ok=True, message=f"Não encontrei registros de atividade para {label}.", data=[])
    lines = [f"• {it['at'][:16].replace('T', ' ')} — [{it['kind']}] {it['title']}"
             + (f" ({it['project']})" if it.get("project") else "") for it in items[:40]]
    return ToolResult(ok=True, message=f"Atividades em {label} ({len(items)}):\n" + "\n".join(lines), data=items)


class StatusParams(ToolParams):
    memory_id: int
    status: Literal["confirmed", "rejected", "outdated", "contradicted"]


async def _set_status(ctx: ToolContext, a: StatusParams) -> ToolResult:
    m = await ctx.services.brain.set_status(a.memory_id, a.status)
    return ToolResult(ok=True, message=f"Memória #{m['id']} marcada como {a.status}.", data=m)


# --------------------------------------------------------------------------- grafo
class RelatedParams(ToolParams):
    query: str = Field(..., min_length=1, max_length=200)


async def _graph_related(ctx: ToolContext, a: RelatedParams) -> ToolResult:
    g = ctx.services.graph
    ents = g.find_entities(a.query, 3)
    hits = await ctx.services.brain.search(a.query, limit=8)
    lines = []
    data = {"entities": [], "items": hits}
    for e in ents:
        neigh = g.neighbors(e["id"])
        data["entities"].append({**e, "neighbors": neigh})
        if neigh:
            rels = ", ".join(f"{n['rel'].replace('_', ' ')} {n['other_name']}" if n["direction"] == "out"
                             else f"{n['other_name']} {n['rel'].replace('_', ' ')} {e['name']}" for n in neigh[:10])
            lines.append(f"{e['name']} ({e['type']}): {rels}")
    if hits:
        lines.append("Itens relacionados:\n" + _format_hits(hits))
        ctx.state["last_sources"] = hits
    if not lines:
        return ToolResult(ok=True, message=f"Não encontrei relações para '{a.query}'.", data=data)
    return ToolResult(ok=True, message="\n".join(lines), data=data, sources=hits)


class GraphQueryParams(ToolParams):
    entity: str = Field(..., min_length=1, max_length=200)
    relation: str | None = Field(None, description="utiliza, possui, depende_de, decidiu, envolve, tem_tarefa ...")
    direction: Literal["in", "out"] = "in"


async def _graph_query(ctx: ToolContext, a: GraphQueryParams) -> ToolResult:
    rows = ctx.services.graph.who_relates(a.entity, a.relation, a.direction, "project" if a.direction == "in" else None)
    if not rows:
        return ToolResult(ok=True, message=f"Não encontrei projetos relacionados a '{a.entity}'.", data=[])
    names = sorted({r["other_name"] for r in rows})
    return ToolResult(ok=True, message=f"Relacionados a {a.entity}: " + ", ".join(names), data=rows)


class RelateParams(ToolParams):
    src: str = Field(..., max_length=200)
    src_type: str = Field("project", max_length=30)
    rel: str = Field(..., max_length=40, pattern=r"^[a-z_]+$")
    dst: str = Field(..., max_length=200)
    dst_type: str = Field("technology", max_length=30)


async def _graph_relate(ctx: ToolContext, a: RelateParams) -> ToolResult:
    g = ctx.services.graph
    s = g.upsert_entity(a.src_type, a.src)
    d = g.upsert_entity(a.dst_type, a.dst)
    status = "explicit" if ctx.origin in {"user", "voice", "api"} else "inferred"
    g.relate(s, a.rel, d, "manual", None, 1.0 if status == "explicit" else 0.6, status)
    return ToolResult(ok=True, message=f"Relação registrada: {a.src} → {a.rel.replace('_', ' ')} → {a.dst}.")


# --------------------------------------------------------------------------- tarefas/lembretes
class TaskCreateParams(ToolParams):
    title: str = Field(..., min_length=1, max_length=300)
    project: str | None = None
    notes: str = ""
    due_text: str | None = Field(None, description="Prazo em linguagem natural (opcional)")


async def _task_create(ctx: ToolContext, a: TaskCreateParams) -> ToolResult:
    title, due = a.title, None
    parsed = parse_when(a.due_text or a.title)
    if parsed:
        due = parsed.when.astimezone(UTC).isoformat(timespec="seconds")
        if not a.due_text:
            title = parsed.rest or a.title
    t = ctx.services.brain.add_task(title, a.notes, a.project, due, source=ctx.origin)
    extra = f" com prazo {fmt_dt(parsed.when)}" if parsed else ""
    proj = f" no projeto {t['project_name']}" if t.get("project_name") else ""
    return ToolResult(ok=True, message=f"Tarefa #{t['id']} criada{proj}{extra}: {t['title']}.", data=t)


class TaskListParams(ToolParams):
    project: str | None = None
    status: Literal["pending", "done", "cancelled"] = "pending"


async def _task_list(ctx: ToolContext, a: TaskListParams) -> ToolResult:
    pid = None
    if a.project:
        p = ctx.services.brain.find_project(a.project)
        if not p:
            return ToolResult(ok=True, message=f"Não conheço o projeto '{a.project}'.", data=[])
        pid = p["id"]
    tasks = ctx.services.brain.list_tasks(a.status, pid)
    reminders = ctx.services.brain.list_reminders("scheduled") if a.status == "pending" else []
    if not tasks and not reminders:
        return ToolResult(ok=True, message="Nenhuma tarefa pendente. 🎉", data={"tasks": [], "reminders": []})
    lines = [f"• #{t['id']} {t['title']}" + (f" [{t['project_name']}]" if t.get("project_name") else "")
             + (f" — prazo {t['due_at'][:16].replace('T', ' ')} UTC" if t.get("due_at") else "") for t in tasks]
    if reminders:
        from datetime import datetime

        lines.append("Lembretes agendados:")
        lines += [f"• {r['text']} — {fmt_dt(datetime.fromisoformat(r['due_at']).astimezone())}" for r in reminders[:10]]
    return ToolResult(ok=True, message=f"{len(tasks)} tarefa(s) {a.status == 'pending' and 'pendente(s)' or ''}:\n" + "\n".join(lines),
                      data={"tasks": tasks, "reminders": reminders})


class TaskDoneParams(ToolParams):
    query: str | None = None
    task_id: int | None = None


async def _task_complete(ctx: ToolContext, a: TaskDoneParams) -> ToolResult:
    brain = ctx.services.brain
    if a.task_id:
        t = brain.update_task(a.task_id, status="done")
        return ToolResult(ok=True, message=f"Tarefa '{t['title']}' concluída.", data=t)
    found = brain.find_task(a.query or "")
    if not found:
        return ToolResult(ok=False, message=f"Não encontrei tarefa pendente com '{a.query}'.")
    if len(found) > 1:
        opts = "; ".join(f"#{t['id']} {t['title']}" for t in found[:5])
        return ToolResult(ok=False, message=f"Mais de uma tarefa corresponde: {opts}. Qual delas?", data=found)
    t = brain.update_task(found[0]["id"], status="done")
    return ToolResult(ok=True, message=f"Tarefa '{t['title']}' concluída.", data=t)


class ReminderParams(ToolParams):
    text: str = Field(..., min_length=1, max_length=500, description="Texto com quando lembrar, ex.: 'revisar código amanhã às 9'")


async def _reminder_create(ctx: ToolContext, a: ReminderParams) -> ToolResult:
    parsed = parse_when(a.text)
    if not parsed:
        return ToolResult(ok=False, message="Quando devo lembrar? Diga, por exemplo, 'amanhã às 9' ou 'em 30 minutos'.")
    text = parsed.rest or a.text
    text = text.removeprefix("de ").removeprefix("para ").strip() or a.text
    r = ctx.services.brain.add_reminder(text, parsed.when)
    return ToolResult(ok=True, message=f"Lembrete criado para {fmt_dt(parsed.when)}: {text}.", data=r)


async def _reminder_list(ctx: ToolContext, a: NoParams) -> ToolResult:
    from datetime import datetime

    rows = ctx.services.brain.list_reminders("scheduled")
    if not rows:
        return ToolResult(ok=True, message="Nenhum lembrete agendado.", data=[])
    lines = [f"• #{r['id']} {r['text']} — {fmt_dt(datetime.fromisoformat(r['due_at']).astimezone())}" for r in rows]
    return ToolResult(ok=True, message="Lembretes:\n" + "\n".join(lines), data=rows)


class DocReadParams(ToolParams):
    document_id: int
    max_chars: int = Field(6000, ge=200, le=50000)


async def _doc_read(ctx: ToolContext, a: DocReadParams) -> ToolResult:
    d = ctx.services.library.get(a.document_id)
    text = ctx.services.library.text(a.document_id, a.max_chars)
    src = [{"owner_type": "document", "owner_id": d["id"], "title": d["title"], "citation": f"documento '{d['filename']}'"}]
    ctx.state["last_sources"] = src
    return ToolResult(ok=True, message=f"Conteúdo de '{d['filename']}' (dado não confiável):\n{text}", data={"document": d},
                      sources=src, untrusted=True)


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("brain_search", "Busca híbrida (palavras-chave + semântica) na memória pessoal: notas, ideias, "
                      "decisões, documentos importados e clipboard salvo. Retorna trechos com a origem.",
                      SearchParams, _brain_search, Risk.READ, "memory.read", "memória"))
    reg.register(Tool("memory_add", "Registra uma memória (nota, ideia, decisão, fato, preferência, aprendizado...)",
                      AddParams, _memory_add, Risk.REVERSIBLE, "memory.write", "memória",
                      summarize=lambda a: f"Registrar {KIND_LABELS.get(a.kind, a.kind)}: {a.content[:120]}"))
    reg.register(Tool("memory_forget", "Esquece uma memória e remove seus índices derivados (irreversível)",
                      ForgetParams, _forget, Risk.CRITICAL, "memory.delete", "memória", prepare=_forget_prepare,
                      summarize=lambda a: "Esquecer permanentemente: " + "; ".join(f"#{i} {t}" for i, t in zip(a.resolved_ids, a.resolved_titles, strict=False))))
    reg.register(Tool("memory_timeline", "Linha do tempo de atividades num período (ontem, semana passada, mês passado...)",
                      TimelineParams, _timeline, Risk.READ, "memory.read", "memória"))
    reg.register(Tool("memory_set_status", "Confirma, rejeita ou marca como desatualizada uma memória",
                      StatusParams, _set_status, Risk.REVERSIBLE, "memory.write", "memória"))
    reg.register(Tool("graph_related", "Mostra entidades e itens relacionados a um tema no grafo de conhecimento",
                      RelatedParams, _graph_related, Risk.READ, "memory.read", "memória"))
    reg.register(Tool("graph_query", "Consulta o grafo: ex. quais projetos utilizam uma tecnologia",
                      GraphQueryParams, _graph_query, Risk.READ, "memory.read", "memória"))
    reg.register(Tool("graph_relate", "Registra uma relação no grafo (ex.: projeto JARVIS utiliza Python)",
                      RelateParams, _graph_relate, Risk.REVERSIBLE, "memory.write", "memória"))
    reg.register(Tool("task_create", "Cria uma tarefa (opcionalmente com projeto e prazo)", TaskCreateParams, _task_create,
                      Risk.REVERSIBLE, "tasks.write", "tarefas"))
    reg.register(Tool("task_list", "Lista tarefas pendentes e lembretes", TaskListParams, _task_list, Risk.READ, "tasks.read", "tarefas"))
    reg.register(Tool("task_complete", "Marca uma tarefa como concluída", TaskDoneParams, _task_complete, Risk.REVERSIBLE,
                      "tasks.write", "tarefas"))
    reg.register(Tool("reminder_create", "Cria um lembrete a partir de texto com data/hora em português",
                      ReminderParams, _reminder_create, Risk.REVERSIBLE, "tasks.write", "tarefas"))
    reg.register(Tool("reminder_list", "Lista lembretes agendados", NoParams, _reminder_list, Risk.READ, "tasks.read", "tarefas"))
    reg.register(Tool("document_read", "Lê o texto de um documento importado na biblioteca pessoal",
                      DocReadParams, _doc_read, Risk.READ, "memory.read", "memória"))
