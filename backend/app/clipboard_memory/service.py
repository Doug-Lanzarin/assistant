"""Memória inteligente da área de transferência.

Regras de privacidade:
* O clipboard só é lido quando o usuário pede (nunca monitorado por padrão).
* Nada é salvo automaticamente.
* O clipboard só é sobrescrito quando o usuário pede para copiar um registro.
* Conteúdo sensível é cifrado em repouso, não é indexado em texto pleno e não
  é enviado à IA.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC
from typing import Any

from app.core.db import Database, from_json, to_json, utcnow
from app.integrations.agent_bridge import AgentBridge
from app.memory.graph import Graph
from app.memory.index import Indexer
from app.orchestrator.dateparse import parse_period
from app.orchestrator.textnorm import fold, normalize_key
from app.security.secrets import Cipher
from app.security.sensitive import detect_sensitive

from .classify import CATEGORIES, classify, suggest_title

MAX_CHARS = 1_000_000
_FILLER = re.compile(
    r"\b(aquel[ae]s?|aquilo|o|a|os|as|um|uma|meu|minha|meus|minhas|que|eu|salvei|copiei|guardei|registrei|"
    r"salvo|salva|salvos|salvas|ontem|hoje|anteontem|semana|passada|mes|passado|recente|ultim[oa]|de|do|da)\b"
)


class ClipboardError(RuntimeError):
    pass


class Ambiguous(ClipboardError):
    def __init__(self, options: list[dict]):
        self.options = options
        titles = "; ".join(f"#{o['id']} {o['title']}" for o in options[:5])
        super().__init__(f"Encontrei mais de um registro: {titles}. Qual deles?")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ClipboardMemory:
    def __init__(self, db: Database, indexer: Indexer, graph: Graph, cipher: Cipher, agent: AgentBridge, brain=None):
        self.db = db
        self.indexer = indexer
        self.graph = graph
        self.cipher = cipher
        self.agent = agent
        self.brain = brain  # para resolver projetos

    # -- leitura/escrita do clipboard real (via agente) --------------------------
    async def read_system_clipboard(self) -> dict[str, Any]:
        data = await self.agent.call("clipboard.read", {}, timeout=5)
        if not isinstance(data, dict):
            raise ClipboardError("Resposta inválida do agente")
        return data

    async def write_system_clipboard(self, text: str) -> None:
        res = await self.agent.call("clipboard.write", {"text": text}, timeout=5)
        if not (isinstance(res, dict) and res.get("ok")):
            raise ClipboardError("O agente não confirmou a escrita no clipboard")
        # Verificação: relê e compara (garante resultado verdadeiro).
        check = await self.read_system_clipboard()
        if check.get("text") != text:
            raise ClipboardError("O clipboard não ficou com o conteúdo esperado após a escrita")

    # -- CRUD ---------------------------------------------------------------------
    def _project_id(self, project: str | None) -> int | None:
        if not project or not self.brain:
            return None
        return self.brain.get_or_create_project(project)

    def _plain(self, row: dict) -> str:
        return self.cipher.decrypt(row["content"]) if row["encrypted"] else row["content"]

    def public(self, row: dict, include_content: bool = True) -> dict[str, Any]:
        out = {k: v for k, v in row.items() if k != "content"}
        out["tags"] = from_json(row.get("tags"), [])
        out["pinned"] = bool(row.get("pinned"))
        out["sensitive"] = bool(row.get("sensitive"))
        out["encrypted"] = bool(row.get("encrypted"))
        if include_content:
            out["content"] = self._plain(row)
        out["preview"] = "•••••• (conteúdo sensível)" if row.get("sensitive") else self._plain(row)[:240]
        return out

    def get_row(self, item_id: int) -> dict:
        row = self.db.query_one(
            "SELECT c.*, p.name AS project_name FROM clipboard_items c LEFT JOIN projects p ON p.id=c.project_id WHERE c.id=?",
            (item_id,),
        )
        if not row:
            raise ClipboardError(f"Registro #{item_id} não encontrado")
        return row

    def get(self, item_id: int, include_content: bool = True) -> dict:
        return self.public(self.get_row(item_id), include_content)

    async def save_text(
        self, content: str, title: str | None = None, category: str | None = None, project: str | None = None,
        tags: list[str] | None = None, content_format: str = "text", allow_duplicate: bool = False,
    ) -> dict[str, Any]:
        if not content or not content.strip():
            raise ClipboardError("Não há conteúdo de texto para salvar.")
        if len(content) > MAX_CHARS:
            raise ClipboardError("Conteúdo grande demais (limite de 1 milhão de caracteres).")
        sha = _sha(content)
        dup = self.db.query_one("SELECT id FROM clipboard_items WHERE sha256=?", (sha,))
        if dup and not allow_duplicate:
            item = self.get(dup["id"], include_content=False)
            return {"item": item, "duplicate": True, "title_suggested": False}
        report = detect_sensitive(content)
        cat = (category or "").strip().lower() or classify(content, report.sensitive)
        if report.sensitive:
            cat = category.strip().lower() if category else "senha"
        title_suggested = not title
        final_title = (title or suggest_title(content, cat)).strip()[:200]
        stored = self.cipher.encrypt(content) if report.sensitive else content
        now = utcnow()
        iid = self.db.insert(
            "INSERT INTO clipboard_items(title, content, encrypted, content_format, category, project_id, tags, sha256,"
            " sensitive, char_count, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (final_title, stored, int(report.sensitive), content_format, cat, self._project_id(project),
             to_json(tags or []), sha, int(report.sensitive), len(content), now, now),
        )
        await self._index(iid)
        return {
            "item": self.get(iid, include_content=False),
            "duplicate": False,
            "title_suggested": title_suggested,
            "sensitive_reasons": report.reasons,
        }

    async def save_from_clipboard(self, title=None, category=None, project=None, tags=None) -> dict[str, Any]:
        clip = await self.read_system_clipboard()
        fmt = clip.get("format", "empty")
        if fmt == "text":
            text = clip.get("text") or ""
        elif fmt == "files":
            text = "\n".join(clip.get("files") or [])
            category = category or "arquivos"
        elif fmt == "empty":
            raise ClipboardError("A área de transferência está vazia. Copie algo com Ctrl+C e tente novamente.")
        else:
            raise ClipboardError(
                f"O clipboard contém '{fmt}'. Esta versão salva texto, código e listas de arquivos; "
                "imagens e outros formatos ainda não são suportados."
            )
        return await self.save_text(text, title, category, project, tags, content_format=fmt)

    async def _index(self, iid: int) -> None:
        row = self.get_row(iid)
        self.graph.unlink_owner("clipboard", iid)
        tags = from_json(row["tags"], [])
        header = f"{row['title']}\ncategoria: {row['category']}" + (" " + " ".join("#" + t for t in tags) if tags else "")
        if row["sensitive"]:
            # Apenas metadados (título/categoria) são indexados.
            await self.indexer.index("clipboard", iid, header, chunk=False)
            return
        body = row["content"]
        await self.indexer.index("clipboard", iid, header + "\n" + body[:20000])
        self.graph.index_owner("clipboard", iid, header + "\n" + body[:5000], None, row.get("project_name"))

    def _history(self, row: dict, change_type: str) -> None:
        self.db.execute(
            "INSERT INTO clipboard_history(item_id, change_type, old_title, old_content, old_encrypted, changed_at)"
            " VALUES (?,?,?,?,?,?)",
            (row["id"], change_type, row["title"], row["content"], row["encrypted"], utcnow()),
        )

    async def update_content(self, item_id: int, content: str) -> dict:
        if not content.strip():
            raise ClipboardError("Conteúdo vazio; nada foi alterado.")
        row = self.get_row(item_id)
        self._history(row, "content")
        report = detect_sensitive(content)
        sensitive = report.sensitive or bool(row["sensitive"])
        stored = self.cipher.encrypt(content) if sensitive else content
        self.db.execute(
            "UPDATE clipboard_items SET content=?, encrypted=?, sensitive=?, sha256=?, char_count=?, updated_at=? WHERE id=?",
            (stored, int(sensitive), int(sensitive), _sha(content), len(content), utcnow(), item_id),
        )
        await self._index(item_id)
        return self.get(item_id, include_content=False)

    async def update_from_clipboard(self, item_id: int) -> dict:
        clip = await self.read_system_clipboard()
        if clip.get("format") != "text" or not clip.get("text"):
            raise ClipboardError("O clipboard atual não contém texto.")
        return await self.update_content(item_id, clip["text"])

    async def update_meta(self, item_id: int, title=None, category=None, project=None, tags=None, pinned=None) -> dict:
        row = self.get_row(item_id)
        fields: dict[str, Any] = {}
        if title is not None and title.strip() and title.strip() != row["title"]:
            self._history(row, "title")
            fields["title"] = title.strip()[:200]
        if category is not None:
            fields["category"] = category.strip().lower() or "texto"
        if project is not None:
            fields["project_id"] = self._project_id(project) if project else None
        if tags is not None:
            fields["tags"] = to_json([t.strip() for t in tags if t.strip()])
        if pinned is not None:
            fields["pinned"] = int(bool(pinned))
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            self.db.execute(f"UPDATE clipboard_items SET {sets}, updated_at=? WHERE id=?", (*fields.values(), utcnow(), item_id))
            await self._index(item_id)
        return self.get(item_id, include_content=False)

    def delete(self, item_id: int) -> dict[str, int]:
        self.get_row(item_id)
        with self.db.transaction():
            chunks = self.indexer.remove("clipboard", item_id)
            self.graph.unlink_owner("clipboard", item_id)
            self.db.execute("DELETE FROM clipboard_items WHERE id=?", (item_id,))
        return {"items": 1, "chunks": chunks}

    def history(self, item_id: int) -> list[dict]:
        rows = self.db.query("SELECT * FROM clipboard_history WHERE item_id=? ORDER BY id DESC", (item_id,))
        out = []
        for r in rows:
            content = r["old_content"]
            if r["old_encrypted"] and content:
                content = "•••••• (sensível)"
            out.append({**r, "old_content": content})
        return out

    async def copy_to_clipboard(self, item_id: int) -> dict:
        row = self.get_row(item_id)
        await self.write_system_clipboard(self._plain(row))
        self.db.execute(
            "UPDATE clipboard_items SET copy_count=copy_count+1, last_copied_at=? WHERE id=?", (utcnow(), item_id)
        )
        return self.get(item_id, include_content=False)

    # -- consulta -----------------------------------------------------------------
    def list(self, category: str | None = None, project: str | None = None, query: str | None = None,
             pinned: bool | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        sql = ("SELECT c.*, p.name AS project_name FROM clipboard_items c LEFT JOIN projects p ON p.id=c.project_id"
               " WHERE 1=1")
        params: list[Any] = []
        if category:
            sql += " AND c.category=?"
            params.append(normalize_key(category).replace(" ", ""))
        if project and self.brain:
            prow = self.brain.find_project(project)
            if not prow:
                return []
            sql += " AND c.project_id=?"
            params.append(prow["id"])
        if pinned is not None:
            sql += " AND c.pinned=?"
            params.append(int(pinned))
        sql += " ORDER BY c.pinned DESC, c.updated_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        rows = self.db.query(sql, tuple(params))
        if query:
            keys = [k for k in normalize_key(query).split() if k not in {"de", "do", "da", "o", "a", "os", "as"}]
            # singular simples ("comandos" casa com "comando")
            keys = [k[:-1] if len(k) > 4 and k.endswith("s") else k for k in keys]

            def matches(r: dict) -> bool:
                hay = normalize_key(" ".join([r["title"], r["category"], " ".join(from_json(r["tags"], []))]))
                if not r["sensitive"]:
                    hay += " " + normalize_key(r["content"][:2000])
                return all(k in hay for k in keys)

            rows = [r for r in rows if matches(r)]
        return [self.public(r, include_content=False) for r in rows]

    async def search(self, query: str, category: str | None = None, project: str | None = None, limit: int = 10) -> list[dict]:
        period = parse_period(query)
        start = end = None
        if period:
            start = period[0].astimezone(UTC).isoformat(timespec="seconds")
            end = period[1].astimezone(UTC).isoformat(timespec="seconds")
        cleaned = re.sub(r"\s+", " ", _FILLER.sub(" ", fold(query))).strip()
        # Categoria implícita ("consulta SQL", "comandos git")
        if not category:
            for c in CATEGORIES:
                if re.search(rf"\b{c}\b", cleaned):
                    category = c
                    break
        scores: dict[int, float] = {}
        # 1) título (forte)
        if cleaned:
            keys = [k for k in cleaned.split() if len(k) > 1]
            for r in self.db.query("SELECT id, title, category, tags FROM clipboard_items"):
                hay = normalize_key(r["title"] + " " + " ".join(from_json(r["tags"], [])))
                hits = sum(1 for k in keys if k in hay or (k.endswith("s") and k[:-1] in hay))
                if hits:
                    scores[r["id"]] = scores.get(r["id"], 0) + 0.05 * hits / max(1, len(keys)) + (0.05 if hits == len(keys) else 0)
        # 2) busca híbrida no conteúdo (não sensível)
        for h in await self.indexer.search(cleaned or query, ["clipboard"], None, limit=limit * 3):
            scores[h.owner_id] = scores.get(h.owner_id, 0) + h.score
        if not scores and not cleaned and (start or category):
            scores = {r["id"]: 0.01 for r in self.db.query("SELECT id FROM clipboard_items")}
        rows = []
        for iid, score in sorted(scores.items(), key=lambda kv: -kv[1]):
            r = self.db.query_one(
                "SELECT c.*, p.name AS project_name FROM clipboard_items c LEFT JOIN projects p ON p.id=c.project_id WHERE c.id=?",
                (iid,),
            )
            if not r:
                continue
            if category and r["category"] != category and category not in fold(r["title"]):
                continue
            if start and not (start <= r["created_at"] < end):  # type: ignore[operator]
                continue
            if project and self.brain:
                prow = self.brain.find_project(project)
                if not prow or r["project_id"] != prow["id"]:
                    continue
            item = self.public(r, include_content=False)
            item["score"] = round(score, 4)
            rows.append(item)
        return rows[:limit]

    async def resolve(self, query: str | None, last_id: int | None) -> dict:
        """Encontra exatamente um registro; levanta ``Ambiguous`` se houver empate."""
        if not query:
            if last_id:
                return self.get(last_id, include_content=False)
            raise ClipboardError("Não sei a qual registro você se refere. Diga o nome do registro.")
        found = await self.search(query, limit=5)
        if not found:
            raise ClipboardError(f"Não encontrei nenhum registro salvo para '{query}'.")
        if len(found) == 1:
            return found[0]
        top, second = found[0]["score"], found[1]["score"]
        exact = [f for f in found if normalize_key(f["title"]) == normalize_key(query)]
        if len(exact) == 1:
            return exact[0]
        if top >= second * 1.5:
            return found[0]
        raise Ambiguous(found)

    # -- exportação/importação ------------------------------------------------------
    def export(self, include_sensitive: bool = False) -> dict:
        items = []
        for r in self.db.query(
            "SELECT c.*, p.name AS project_name FROM clipboard_items c LEFT JOIN projects p ON p.id=c.project_id ORDER BY c.id"
        ):
            if r["sensitive"] and not include_sensitive:
                continue
            items.append({
                "title": r["title"], "content": self._plain(r), "category": r["category"],
                "project": r["project_name"], "tags": from_json(r["tags"], []), "pinned": bool(r["pinned"]),
                "content_format": r["content_format"], "created_at": r["created_at"],
            })
        return {"format": "jarvis-clipboard", "version": 1, "exported_at": utcnow(), "items": items}

    async def import_items(self, payload: dict) -> dict[str, int]:
        if payload.get("format") != "jarvis-clipboard" or not isinstance(payload.get("items"), list):
            raise ClipboardError("Arquivo de importação inválido (esperado formato jarvis-clipboard).")
        created = skipped = 0
        for it in payload["items"][:10000]:
            if not isinstance(it, dict) or not isinstance(it.get("content"), str):
                skipped += 1
                continue
            res = await self.save_text(
                it["content"], str(it.get("title") or "")[:200] or None, str(it.get("category") or "") or None,
                str(it.get("project") or "") or None, [str(t) for t in it.get("tags", []) if isinstance(t, str)][:20],
                content_format=str(it.get("content_format") or "text"),
            )
            if res["duplicate"]:
                skipped += 1
            else:
                created += 1
                if it.get("pinned"):
                    await self.update_meta(res["item"]["id"], pinned=True)
        return {"created": created, "skipped": skipped}

    def categories(self) -> list[dict]:
        return self.db.query("SELECT category, COUNT(*) AS n FROM clipboard_items GROUP BY category ORDER BY n DESC")
