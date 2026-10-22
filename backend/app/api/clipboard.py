from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import current_user, services
from app.clipboard_memory.service import ClipboardError
from app.integrations.agent_bridge import AgentError, AgentUnavailable
from app.services.container import Services

router = APIRouter(prefix="/api/clipboard", tags=["clipboard"], dependencies=[Depends(current_user)])


class ItemIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=1_000_000)
    title: str | None = None
    category: str | None = None
    project: str | None = None
    tags: list[str] = Field(default_factory=list)


class SaveCurrentIn(BaseModel):
    title: str | None = None
    category: str | None = None
    project: str | None = None
    tags: list[str] = Field(default_factory=list)


class ItemPatch(BaseModel):
    title: str | None = None
    category: str | None = None
    project: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None
    content: str | None = None


def _fail(e: Exception):
    code = 503 if isinstance(e, AgentUnavailable) else 404 if "não encontrado" in str(e) else 400
    raise HTTPException(code, str(e))


@router.get("")
async def list_items(q: str | None = None, category: str | None = None, project: str | None = None,
                     pinned: bool | None = None, s: Services = Depends(services)):
    if q:
        return await s.clipboard.search(q, category, project, limit=50)
    return s.clipboard.list(category, project, None, pinned)


@router.get("/categories")
def categories(s: Services = Depends(services)):
    return s.clipboard.categories()


@router.get("/export")
def export(include_sensitive: bool = False, s: Services = Depends(services)):
    return s.clipboard.export(include_sensitive)


@router.post("/import")
async def import_items(payload: dict, s: Services = Depends(services)):
    try:
        return await s.clipboard.import_items(payload)
    except ClipboardError as e:
        _fail(e)


@router.post("")
async def create(body: ItemIn, s: Services = Depends(services)):
    try:
        return await s.clipboard.save_text(body.content, body.title, body.category, body.project, body.tags)
    except ClipboardError as e:
        _fail(e)


@router.post("/save-current")
async def save_current(body: SaveCurrentIn, s: Services = Depends(services)):
    try:
        return await s.clipboard.save_from_clipboard(body.title, body.category, body.project, body.tags)
    except (ClipboardError, AgentUnavailable, AgentError) as e:
        _fail(e)


@router.get("/{item_id}")
def get_item(item_id: int, s: Services = Depends(services)):
    try:
        return s.clipboard.get(item_id)
    except ClipboardError as e:
        _fail(e)


@router.patch("/{item_id}")
async def patch(item_id: int, body: ItemPatch, s: Services = Depends(services)):
    try:
        if body.content is not None:
            await s.clipboard.update_content(item_id, body.content)
        return await s.clipboard.update_meta(item_id, body.title, body.category, body.project, body.tags, body.pinned)
    except ClipboardError as e:
        _fail(e)


@router.post("/{item_id}/copy")
async def copy(item_id: int, s: Services = Depends(services)):
    try:
        return await s.clipboard.copy_to_clipboard(item_id)
    except (ClipboardError, AgentUnavailable, AgentError) as e:
        _fail(e)


@router.post("/{item_id}/update-from-clipboard")
async def update_from_clipboard(item_id: int, s: Services = Depends(services)):
    try:
        return await s.clipboard.update_from_clipboard(item_id)
    except (ClipboardError, AgentUnavailable, AgentError) as e:
        _fail(e)


@router.get("/{item_id}/history")
def history(item_id: int, s: Services = Depends(services)):
    return s.clipboard.history(item_id)


@router.delete("/{item_id}")
def delete(item_id: int, s: Services = Depends(services)):
    try:
        return s.clipboard.delete(item_id)
    except ClipboardError as e:
        _fail(e)
