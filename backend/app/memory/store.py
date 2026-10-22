"""Segundo cérebro: memórias, projetos, tarefas, lembretes e linha do tempo.

Tipos de memória (``kind``):
  episodic  – acontecimento/interação com contexto temporal
  semantic/fact – conhecimento ou fato
  preference – preferência (explícita, confirmada ou inferida)
  project   – estado/objetivo/problema de um projeto
  idea, decision, note, learning, goal, event
  session_summary – resumo gerado pela consolidação

Estados (``status``): explicit, confirmed, inferred, outdated, contradicted, rejected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.db import Database, from_json, to_json, utcnow
from app.memory.graph import Graph
from app.memory.index import Indexer
from app.orchestrator.textnorm import normalize_key
from app.security.sensitive import detect_sensitive

KINDS = {
    "episodic", "semantic", "fact", "preference", "project", "idea", "decision", "note", "learning",
    "goal", "event", "session_summary",
}
STATUSES = {"explicit", "confirmed", "inferred", "outdated", "contradicted", "rejected"}
KIND_LABELS = {
    "episodic": "episódio", "semantic": "conhecimento", "fact": "fato", "preference": "preferência",
    "project": "projeto", "idea": "ideia", "decision": "decisão", "note": "nota", "learning": "aprendizado",
    "goal": "objetivo", "event": "evento", "session_summary": "resumo de sessão",
}
STALE_AFTER_DAYS = {"project": 90, "preference": 365, "fact": 365}


class Brain:
    def __init__(self, db: Database, indexer: Indexer, graph: Graph):
        self.db = db
        self.indexer = indexer
        self.graph = graph

    # -- projetos ---------------------------------------------------------------
    def get_or_create_project(self, name: str | None) -> int | None:
        if not name or not name.strip():
            return None
        norm = normalize_key(name)
        row = self.db.query_one("SELECT id FROM projects WHERE normalized=?", (norm,))
        if row:
            return row["id"]
        now = utcnow()
        pid = self.db.insert(
            "INSERT INTO projects(name, normalized, created_at, updated_at) VALUES (?,?,?,?)",
            (name.strip(), norm, now, now),
        )
        self.graph.upsert_entity("project", name.strip())
        return pid

    def find_project(self, name: str | None) -> dict | None:
        if not name:
            return None
        norm = normalize_key(name)
        row = self.db.query_one("SELECT * FROM projects WHERE normalized=?", (norm,))
        if row:
            return row
        return self.db.query_one(
            "SELECT * FROM projects WHERE normalized LIKE ? ORDER BY length(name) LIMIT 1", (f"%{norm}%",)
        )

    def list_projects(self) -> list[dict]:
        return self.db.query(
            "SELECT p.*, (SELECT COUNT(*) FROM memories m WHERE m.project_id=p.id AND m.status!='rejected') AS memories,"
            " (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status='pending') AS pending_tasks"
            " FROM projects p ORDER BY p.updated_at DESC"
        )

    def update_project(self, project_id: int, **fields: Any) -> dict | None:
        allowed = {k: v for k, v in fields.items() if k in {"name", "description", "status"} and v is not None}
        if "name" in allowed:
            allowed["normalized"] = normalize_key(allowed["name"])
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self.db.execute(f"UPDATE projects SET {sets}, updated_at=? WHERE id=?", (*allowed.values(), utcnow(), project_id))
        return self.db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))

    def project_overview(self, project_id: int) -> dict[str, Any]:
        p = self.db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if not p:
            raise KeyError("Projeto não encontrado")
        mems = self.db.query(
            "SELECT * FROM memories WHERE project_id=? AND status!='rejected' ORDER BY created_at DESC LIMIT 100",
            (project_id,),
        )
        tasks = self.db.query("SELECT * FROM tasks WHERE project_id=? ORDER BY status, created_at DESC", (project_id,))
        ent = self.db.query_one("SELECT id FROM entities WHERE type='project' AND normalized=?", (p["normalized"],))
        relations = self.graph.neighbors(ent["id"]) if ent else []
        return {
            "project": p,
            "decisions": [self._public(m) for m in mems if m["kind"] == "decision"],
            "ideas": [self._public(m) for m in mems if m["kind"] == "idea"],
            "memories": [self._public(m) for m in mems],
            "tasks": tasks,
            "relations": relations,
        }

    # -- memórias ---------------------------------------------------------------
    async def add(
        self,
        content: str,
        kind: str = "note",
        title: str = "",
        source: str = "user",
        status: str = "explicit",
        confidence: float = 1.0,
        project: str | None = None,
        tags: list[str] | None = None,
        happened_at: str | None = None,
        source_ref: str | None = None,
    ) -> dict:
        if kind not in KINDS:
            raise ValueError(f"Tipo de memória inválido: {kind}")
        if status not in STATUSES:
            raise ValueError(f"Estado inválido: {status}")
        content = content.strip()
        if not content:
            raise ValueError("Conteúdo vazio")
        sensitive = detect_sensitive(content).sensitive
        project_id = self.get_or_create_project(project)
        now = utcnow()
        mid = self.db.insert(
            "INSERT INTO memories(kind, title, content, source, source_ref, status, confidence, project_id, tags,"
            " happened_at, sensitive, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, title.strip(), content, source, source_ref, status, confidence, project_id,
             to_json(tags or []), happened_at or now, int(sensitive), now, now),
        )
        await self._index(mid)
        if project_id:
            self.db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
        return self.get(mid)

    async def _index(self, mid: int) -> None:
        m = self.db.query_one(
            "SELECT m.*, p.name AS project_name FROM memories m LEFT JOIN projects p ON p.id=m.project_id WHERE m.id=?",
            (mid,),
        )
        if not m:
            return
        self.graph.unlink_owner("memory", mid)
        if m["sensitive"] or m["status"] == "rejected":
            self.indexer.remove("memory", mid)
            return
        text = (m["title"] + "\n" if m["title"] else "") + m["content"]
        tags = from_json(m["tags"], [])
        if tags:
            text += "\n" + " ".join("#" + t for t in tags)
        await self.indexer.index("memory", mid, text)
        self.graph.index_owner("memory", mid, text, m["kind"], m["project_name"], m["title"] or None)

    def get(self, mid: int) -> dict:
        m = self.db.query_one(
            "SELECT m.*, p.name AS project_name FROM memories m LEFT JOIN projects p ON p.id=m.project_id WHERE m.id=?",
            (mid,),
        )
        if not m:
            raise KeyError(f"Memória {mid} não encontrada")
        return self._public(m)

    def _public(self, m: dict) -> dict:
        out = dict(m)
        out["tags"] = from_json(m.get("tags"), [])
        out["kind_label"] = KIND_LABELS.get(m["kind"], m["kind"])
        out["stale"] = self._is_stale(m)
        if m.get("sensitive"):
            out["content"] = "[conteúdo sensível oculto]"
        return out

    def _is_stale(self, m: dict) -> bool:
        if m["status"] == "outdated":
            return True
        days = STALE_AFTER_DAYS.get(m["kind"])
        if not days:
            return False
        try:
            updated = datetime.fromisoformat(m["updated_at"])
        except (TypeError, ValueError):
            return False
        return datetime.now(UTC) - updated > timedelta(days=days)

    async def update(self, mid: int, **fields: Any) -> dict:
        current = self.db.query_one("SELECT * FROM memories WHERE id=?", (mid,))
        if not current:
            raise KeyError(f"Memória {mid} não encontrada")
        allowed: dict[str, Any] = {}
        for key in ("title", "content", "kind", "status", "confidence", "tags", "happened_at"):
            if key in fields and fields[key] is not None:
                allowed[key] = to_json(fields[key]) if key == "tags" else fields[key]
        if "kind" in allowed and allowed["kind"] not in KINDS:
            raise ValueError("Tipo inválido")
        if "status" in allowed and allowed["status"] not in STATUSES:
            raise ValueError("Estado inválido")
        if "project" in fields:
            allowed["project_id"] = self.get_or_create_project(fields["project"])
        if "content" in allowed:
            allowed["sensitive"] = int(detect_sensitive(allowed["content"]).sensitive)
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self.db.execute(f"UPDATE memories SET {sets}, updated_at=? WHERE id=?", (*allowed.values(), utcnow(), mid))
        await self._index(mid)
        return self.get(mid)

    async def set_status(self, mid: int, status: str) -> dict:
        return await self.update(mid, status=status, confidence=1.0 if status == "confirmed" else None)

    def delete(self, mid: int) -> dict[str, int]:
        """Remove a memória e todos os índices derivados (trechos, FTS, vetores, grafo)."""
        if not self.db.query_one("SELECT id FROM memories WHERE id=?", (mid,)):
            raise KeyError(f"Memória {mid} não encontrada")
        with self.db.transaction():
            chunks = self.indexer.remove("memory", mid)
            links = self.graph.unlink_owner("memory", mid)
            self.db.execute("UPDATE memories SET supersedes_id=NULL WHERE supersedes_id=?", (mid,))
            self.db.execute("DELETE FROM memories WHERE id=?", (mid,))
        return {"memories": 1, "chunks": chunks, "graph_links": links}

    def list(
        self,
        kind: str | None = None,
        status: str | None = None,
        project_id: int | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        sql = "SELECT m.*, p.name AS project_name FROM memories m LEFT JOIN projects p ON p.id=m.project_id WHERE 1=1"
        params: list[Any] = []
        if kind:
            sql += " AND m.kind=?"
            params.append(kind)
        if status:
            sql += " AND m.status=?"
            params.append(status)
        else:
            sql += " AND m.status!='rejected'"
        if project_id:
            sql += " AND m.project_id=?"
            params.append(project_id)
        if start:
            sql += " AND COALESCE(m.happened_at, m.created_at) >= ?"
            params.append(start)
        if end:
            sql += " AND COALESCE(m.happened_at, m.created_at) < ?"
            params.append(end)
        sql += " ORDER BY COALESCE(m.happened_at, m.created_at) DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [self._public(m) for m in self.db.query(sql, tuple(params))]

    # -- busca ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        kinds: list[str] | None = None,
        owner_types: list[str] | None = None,
        project: str | None = None,
        start: str | None = None,
        end: str | None = None,
        include_outdated: bool = True,
        limit: int = 8,
    ) -> list[dict]:
        owner_types = owner_types or ["memory", "document", "clipboard"]
        allowed: dict[str, set[int]] = {}
        project_row = self.find_project(project) if project else None
        if project and not project_row:
            return []
        filters_on = bool(kinds or project_row or start or end or not include_outdated)
        if "memory" in owner_types and filters_on:
            sql = "SELECT id FROM memories WHERE status!='rejected'"
            params: list[Any] = []
            if kinds:
                sql += f" AND kind IN ({','.join('?' * len(kinds))})"
                params += kinds
            if project_row:
                sql += " AND project_id=?"
                params.append(project_row["id"])
            if start:
                sql += " AND COALESCE(happened_at, created_at) >= ?"
                params.append(start)
            if end:
                sql += " AND COALESCE(happened_at, created_at) < ?"
                params.append(end)
            if not include_outdated:
                sql += " AND status NOT IN ('outdated','contradicted')"
            allowed["memory"] = {r["id"] for r in self.db.query(sql, tuple(params))}
        if kinds:  # tipos de memória só se aplicam a memórias
            owner_types = [o for o in owner_types if o == "memory"] or ["memory"]
        if project_row:
            for ot, table in (("document", "documents"), ("clipboard", "clipboard_items")):
                if ot in owner_types:
                    allowed[ot] = {r["id"] for r in self.db.query(f"SELECT id FROM {table} WHERE project_id=?", (project_row["id"],))}
        if start or end:
            for ot, table, col in (("document", "documents", "imported_at"), ("clipboard", "clipboard_items", "created_at")):
                if ot in owner_types:
                    sql = f"SELECT id FROM {table} WHERE 1=1"
                    params = []
                    if start:
                        sql += f" AND {col} >= ?"
                        params.append(start)
                    if end:
                        sql += f" AND {col} < ?"
                        params.append(end)
                    ids = {r["id"] for r in self.db.query(sql, tuple(params))}
                    allowed[ot] = allowed[ot] & ids if ot in allowed else ids
        hits = await self.indexer.search(query, owner_types, allowed or None, limit=limit)
        return [self._describe_hit(h) for h in hits if self._describe_hit(h)]

    def _describe_hit(self, h) -> dict | None:
        base = {"owner_type": h.owner_type, "owner_id": h.owner_id, "snippet": h.text[:400],
                "score": round(h.score, 4), "vector_sim": h.vector_sim, "keyword": h.keyword_rank is not None}
        if h.owner_type == "memory":
            m = self.db.query_one(
                "SELECT m.*, p.name AS project_name FROM memories m LEFT JOIN projects p ON p.id=m.project_id WHERE m.id=?",
                (h.owner_id,),
            )
            if not m:
                return None
            pub = self._public(m)
            return {**base, "title": m["title"] or m["content"][:60], "kind": m["kind"], "status": m["status"],
                    "stale": pub["stale"], "project": m["project_name"], "created_at": m["created_at"],
                    "source": m["source"], "confidence": m["confidence"],
                    "citation": f"memória #{m['id']} ({KIND_LABELS.get(m['kind'], m['kind'])}, {m['created_at'][:10]})"}
        if h.owner_type == "document":
            d = self.db.query_one("SELECT id, title, filename, imported_at FROM documents WHERE id=?", (h.owner_id,))
            if not d:
                return None
            return {**base, "title": d["title"], "kind": "document", "created_at": d["imported_at"],
                    "source": d["filename"], "citation": f"documento '{d['filename']}'"}
        if h.owner_type == "clipboard":
            c = self.db.query_one("SELECT id, title, category, created_at FROM clipboard_items WHERE id=?", (h.owner_id,))
            if not c:
                return None
            return {**base, "title": c["title"], "kind": "clipboard", "category": c["category"],
                    "created_at": c["created_at"], "source": "clipboard",
                    "citation": f"clipboard #{c['id']} '{c['title']}'"}
        return None

    # -- linha do tempo -----------------------------------------------------------
    def timeline(self, start: str | None, end: str | None, project_id: int | None = None, limit: int = 200) -> list[dict]:
        items: list[dict] = []
        for m in self.list(project_id=project_id, start=start, end=end, limit=limit):
            items.append({"type": "memory", "id": m["id"], "kind": m["kind"], "title": m["title"] or m["content"][:80],
                          "content": m["content"], "at": m["happened_at"] or m["created_at"], "project": m["project_name"]})
        params: list[Any] = []
        tsql = "SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id=t.project_id WHERE 1=1"
        if project_id:
            tsql += " AND t.project_id=?"
            params.append(project_id)
        for t in self.db.query(tsql, tuple(params)):
            for field_, label in (("created_at", "tarefa criada"), ("completed_at", "tarefa concluída")):
                at = t.get(field_)
                if at and (not start or at >= start) and (not end or at < end):
                    items.append({"type": "task", "id": t["id"], "kind": label, "title": t["title"], "content": t["notes"],
                                  "at": at, "project": t["project_name"]})
        if not project_id:
            csql = "SELECT id, title, category, created_at FROM clipboard_items WHERE 1=1"
            cparams: list[Any] = []
            if start:
                csql += " AND created_at >= ?"
                cparams.append(start)
            if end:
                csql += " AND created_at < ?"
                cparams.append(end)
            for c in self.db.query(csql, tuple(cparams)):
                items.append({"type": "clipboard", "id": c["id"], "kind": "clipboard salvo", "title": c["title"],
                              "content": c["category"], "at": c["created_at"], "project": None})
        items.sort(key=lambda x: x["at"], reverse=True)
        return items[:limit]

    # -- tarefas e lembretes --------------------------------------------------------
    def add_task(self, title: str, notes: str = "", project: str | None = None, due_at: str | None = None,
                 source: str = "user") -> dict:
        now = utcnow()
        pid = self.get_or_create_project(project)
        tid = self.db.insert(
            "INSERT INTO tasks(title, notes, project_id, due_at, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (title.strip(), notes, pid, due_at, source, now, now),
        )
        if pid:
            p = self.db.query_one("SELECT name FROM projects WHERE id=?", (pid,))
            proj_ent = self.graph.upsert_entity("project", p["name"])
            task_ent = self.graph.upsert_entity("task", title[:120])
            self.graph.link(task_ent, "task", tid)
            self.graph.relate(proj_ent, "tem_tarefa", task_ent, "task", tid)
        return self.get_task(tid)

    def get_task(self, tid: int) -> dict:
        t = self.db.query_one(
            "SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id=t.project_id WHERE t.id=?", (tid,)
        )
        if not t:
            raise KeyError("Tarefa não encontrada")
        return t

    def list_tasks(self, status: str | None = "pending", project_id: int | None = None) -> list[dict]:
        sql = "SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id=t.project_id WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND t.status=?"
            params.append(status)
        if project_id:
            sql += " AND t.project_id=?"
            params.append(project_id)
        sql += " ORDER BY CASE WHEN t.due_at IS NULL THEN 1 ELSE 0 END, t.due_at, t.created_at DESC"
        return self.db.query(sql, tuple(params))

    def update_task(self, tid: int, **fields: Any) -> dict:
        allowed = {k: v for k, v in fields.items() if k in {"title", "notes", "status", "due_at"} and v is not None}
        if allowed.get("status") not in (None, "pending", "done", "cancelled"):
            raise ValueError("Status inválido")
        if "project" in fields:
            allowed["project_id"] = self.get_or_create_project(fields["project"])
        if allowed.get("status") == "done":
            allowed["completed_at"] = utcnow()
        elif allowed.get("status") == "pending":
            allowed["completed_at"] = None
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self.db.execute(f"UPDATE tasks SET {sets}, updated_at=? WHERE id=?", (*allowed.values(), utcnow(), tid))
        return self.get_task(tid)

    def delete_task(self, tid: int) -> None:
        self.graph.unlink_owner("task", tid)
        self.db.execute("DELETE FROM tasks WHERE id=?", (tid,))

    def find_task(self, query: str) -> list[dict]:
        norm = normalize_key(query)
        rows = self.list_tasks("pending")
        return [r for r in rows if norm and norm in normalize_key(r["title"])]

    def add_reminder(self, text: str, due_at: datetime) -> dict:
        rid = self.db.insert(
            "INSERT INTO reminders(text, due_at, created_at) VALUES (?,?,?)",
            (text.strip(), due_at.astimezone(UTC).isoformat(timespec="seconds"), utcnow()),
        )
        return self.db.query_one("SELECT * FROM reminders WHERE id=?", (rid,))  # type: ignore[return-value]

    def list_reminders(self, status: str | None = "scheduled") -> list[dict]:
        if status:
            return self.db.query("SELECT * FROM reminders WHERE status=? ORDER BY due_at", (status,))
        return self.db.query("SELECT * FROM reminders ORDER BY due_at DESC LIMIT 200")

    def cancel_reminder(self, rid: int) -> None:
        self.db.execute("UPDATE reminders SET status='cancelled' WHERE id=?", (rid,))

    def due_reminders(self) -> list[dict]:
        return self.db.query("SELECT * FROM reminders WHERE status='scheduled' AND due_at <= ?", (utcnow(),))

    def mark_fired(self, rid: int) -> None:
        self.db.execute("UPDATE reminders SET status='fired', fired_at=? WHERE id=?", (utcnow(), rid))
