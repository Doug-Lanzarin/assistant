from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import current_user, services
from app.memory.documents import UnsupportedDocument
from app.orchestrator.dateparse import parse_period, parse_when
from app.services.container import Services

router = APIRouter(prefix="/api/brain", tags=["segundo cérebro"], dependencies=[Depends(current_user)])


class MemoryIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=50000)
    kind: str = "note"
    title: str = ""
    project: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: str = "explicit"


class MemoryPatch(BaseModel):
    content: str | None = None
    title: str | None = None
    kind: str | None = None
    status: str | None = None
    project: str | None = None
    tags: list[str] | None = None


class TaskIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    notes: str = ""
    project: str | None = None
    due_text: str | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    notes: str | None = None
    status: str | None = None


class ProjectIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class RelationIn(BaseModel):
    src: str
    src_type: str = "project"
    rel: str = Field(..., pattern=r"^[a-z_]+$")
    dst: str
    dst_type: str = "technology"


class ReminderIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


def _err(e: Exception):
    if isinstance(e, KeyError):
        raise HTTPException(404, str(e).strip("'"))
    raise HTTPException(400, str(e))


# -- memórias -----------------------------------------------------------------------------
@router.get("/memories")
def list_memories(kind: str | None = None, status: str | None = None, project: str | None = None,
                  limit: int = 50, offset: int = 0, s: Services = Depends(services)):
    pid = None
    if project:
        p = s.brain.find_project(project)
        if not p:
            return []
        pid = p["id"]
    return s.brain.list(kind, status, pid, limit=min(limit, 500), offset=offset)


@router.post("/memories")
async def create_memory(body: MemoryIn, s: Services = Depends(services)):
    try:
        return await s.brain.add(body.content, body.kind, body.title, "user", body.status, 1.0, body.project, body.tags)
    except ValueError as e:
        _err(e)


@router.get("/memories/{mid}")
def get_memory(mid: int, s: Services = Depends(services)):
    try:
        return s.brain.get(mid)
    except KeyError as e:
        _err(e)


@router.patch("/memories/{mid}")
async def patch_memory(mid: int, body: MemoryPatch, s: Services = Depends(services)):
    try:
        return await s.brain.update(mid, **body.model_dump(exclude_unset=True))
    except (KeyError, ValueError) as e:
        _err(e)


@router.delete("/memories/{mid}")
def delete_memory(mid: int, s: Services = Depends(services)):
    try:
        return s.brain.delete(mid)
    except KeyError as e:
        _err(e)


@router.get("/search")
async def search(q: str, kind: str | None = None, project: str | None = None, period: str | None = None,
                 sources: str | None = None, limit: int = 10, s: Services = Depends(services)):
    start = end = None
    if period:
        p = parse_period(period)
        if p:
            start, end = (x.astimezone(UTC).isoformat(timespec="seconds") for x in p[:2])
    owner_types = [x for x in (sources or "").split(",") if x in {"memory", "document", "clipboard"}] or None
    return await s.brain.search(q, [kind] if kind else None, owner_types, project, start, end, limit=min(limit, 50))


@router.get("/timeline")
def timeline(period: str = "últimos 30 dias", project: str | None = None, s: Services = Depends(services)):
    p = parse_period(period) or parse_period("últimos 30 dias")
    start, end = (x.astimezone(UTC).isoformat(timespec="seconds") for x in p[:2])
    pid = None
    if project:
        prow = s.brain.find_project(project)
        pid = prow["id"] if prow else -1
    return {"label": p[2], "items": s.brain.timeline(start, end, pid)}


# -- projetos ------------------------------------------------------------------------------
@router.get("/projects")
def projects(s: Services = Depends(services)):
    return s.brain.list_projects()


@router.post("/projects")
def create_project(body: ProjectIn, s: Services = Depends(services)):
    pid = s.brain.get_or_create_project(body.name)
    return s.brain.update_project(pid, description=body.description)


@router.get("/projects/{pid}")
def project(pid: int, s: Services = Depends(services)):
    try:
        return s.brain.project_overview(pid)
    except KeyError as e:
        _err(e)


@router.patch("/projects/{pid}")
def patch_project(pid: int, body: ProjectPatch, s: Services = Depends(services)):
    return s.brain.update_project(pid, **body.model_dump(exclude_unset=True))


# -- tarefas e lembretes ------------------------------------------------------------------
@router.get("/tasks")
def tasks(status: str | None = "pending", s: Services = Depends(services)):
    return s.brain.list_tasks(status or None)


@router.post("/tasks")
def create_task(body: TaskIn, s: Services = Depends(services)):
    due = None
    if body.due_text:
        p = parse_when(body.due_text)
        if not p:
            raise HTTPException(400, "Prazo não reconhecido")
        due = p.when.astimezone(UTC).isoformat(timespec="seconds")
    return s.brain.add_task(body.title, body.notes, body.project, due)


@router.patch("/tasks/{tid}")
def patch_task(tid: int, body: TaskPatch, s: Services = Depends(services)):
    try:
        return s.brain.update_task(tid, **body.model_dump(exclude_unset=True))
    except (KeyError, ValueError) as e:
        _err(e)


@router.delete("/tasks/{tid}")
def delete_task(tid: int, s: Services = Depends(services)):
    s.brain.delete_task(tid)
    return {"ok": True}


@router.get("/reminders")
def reminders(status: str | None = "scheduled", s: Services = Depends(services)):
    return s.brain.list_reminders(status or None)


@router.post("/reminders")
def create_reminder(body: ReminderIn, s: Services = Depends(services)):
    p = parse_when(body.text)
    if not p:
        raise HTTPException(400, "Não reconheci a data/hora do lembrete")
    return s.brain.add_reminder(p.rest or body.text, p.when)


@router.delete("/reminders/{rid}")
def cancel_reminder(rid: int, s: Services = Depends(services)):
    s.brain.cancel_reminder(rid)
    return {"ok": True}


# -- grafo -----------------------------------------------------------------------------------
@router.get("/graph")
def graph(limit: int = 300, s: Services = Depends(services)):
    return s.graph.snapshot(min(limit, 2000))


@router.get("/graph/entity")
def graph_entity(q: str, s: Services = Depends(services)):
    out = []
    for e in s.graph.find_entities(q, 5):
        out.append({**e, "neighbors": s.graph.neighbors(e["id"]), "sources": s.graph.sources_of(e["id"])})
    return out


@router.post("/graph/relations")
def add_relation(body: RelationIn, s: Services = Depends(services)):
    a = s.graph.upsert_entity(body.src_type, body.src)
    b = s.graph.upsert_entity(body.dst_type, body.dst)
    return {"id": s.graph.relate(a, body.rel, b, "manual", None, 1.0, "explicit")}


@router.delete("/graph/relations/{rid}")
def delete_relation(rid: int, s: Services = Depends(services)):
    s.db.execute("DELETE FROM relations WHERE id=?", (rid,))
    return {"ok": True}


# -- documentos ---------------------------------------------------------------------------
@router.get("/documents")
def documents(s: Services = Depends(services)):
    return s.library.list()


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), title: str | None = Form(None), project: str | None = Form(None),
                          s: Services = Depends(services)):
    data = await file.read()
    try:
        pid = s.brain.get_or_create_project(project) if project else None
        return await s.library.import_bytes(file.filename or "documento.txt", data, title, project_id=pid)
    except UnsupportedDocument as e:
        raise HTTPException(415, str(e)) from e


@router.get("/documents/{did}")
def document(did: int, s: Services = Depends(services)):
    try:
        d = s.library.get(did)
    except KeyError as e:
        _err(e)
    return {**d, "text": s.library.text(did, 20000)}


@router.delete("/documents/{did}")
def delete_document(did: int, s: Services = Depends(services)):
    try:
        return s.library.delete(did)
    except KeyError as e:
        _err(e)


# -- consolidação e índice --------------------------------------------------------------
@router.post("/consolidate")
async def consolidate(use_ai: bool = True, s: Services = Depends(services)):
    return await s.background.run_consolidation(use_ai)


@router.get("/consolidate")
def consolidation_report(s: Services = Depends(services)):
    return {"running": s.background.consolidating, "report": s.background.consolidator.last_report()}


@router.post("/reindex")
async def reindex(s: Services = Depends(services)):
    s.refresh_embedder()
    n = await s.indexer.reindex_all()
    return {"reindexed": n, "embedder": s.indexer.embedder.name}


@router.get("/stats")
def stats(s: Services = Depends(services)):
    q = s.db.scalar
    return {
        "memories": q("SELECT COUNT(*) FROM memories WHERE status!='rejected'"),
        "inferred_pending": q("SELECT COUNT(*) FROM memories WHERE status='inferred'"),
        "documents": q("SELECT COUNT(*) FROM documents"),
        "clipboard": q("SELECT COUNT(*) FROM clipboard_items"),
        "chunks": q("SELECT COUNT(*) FROM chunks"),
        "entities": q("SELECT COUNT(*) FROM entities"),
        "relations": q("SELECT COUNT(*) FROM relations"),
        "projects": q("SELECT COUNT(*) FROM projects"),
        "tasks_pending": q("SELECT COUNT(*) FROM tasks WHERE status='pending'"),
        "embedder": s.indexer.embedder.name,
    }
