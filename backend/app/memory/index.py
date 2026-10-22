"""Indexação de trechos (FTS5 + vetores) e busca híbrida.

A busca combina BM25 (palavras-chave) e similaridade de cosseno (embeddings)
por Reciprocal Rank Fusion. Os vetores ficam no SQLite (BLOB) e são
carregados numa matriz NumPy em cache — busca exata por força bruta, que para
um acervo pessoal (dezenas de milhares de trechos) responde em milissegundos.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.db import Database, utcnow
from app.orchestrator.textnorm import fold
from app.providers.embeddings import Embedder, HashEmbedder, from_blob, to_blob

log = logging.getLogger("jarvis.index")

_STOP = set(
    ["a", "o", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "por", "para", "pra", "pro", "com", "sem", "que", "e", "ou", "se", "me", "meu", "minha", "meus", "minhas", "seu", "sua", "isso", "isto", "esse", "essa", "este", "esta", "aquele", "aquela", "aquilo", "eu", "voce", "ele", "ela", "nos", "eles", "elas", "foi", "ser", "ter", "tem", "como", "qual", "quais", "quando", "onde", "ja", "mais", "muito", "pouco", "sobre", "ate", "entre", "tambem", "so", "ao", "aos", "the", "of", "and", "to", "in", "is"]
)


def chunk_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if len(text) <= size:
        return [text] if text else []
    paras = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buf = ""
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) + 2 <= size:
            buf = f"{buf}\n\n{p}" if buf else p
            continue
        if buf:
            chunks.append(buf)
        while len(p) > size:
            cut = p.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            chunks.append(p[:cut])
            p = p[max(0, cut - overlap):]
        buf = (chunks[-1][-overlap:] + "\n" + p) if chunks and overlap else p
    if buf:
        chunks.append(buf)
    return chunks


def fts_query(text: str) -> str | None:
    tokens = [t for t in re.findall(r"[a-z0-9]+", fold(text)) if t not in _STOP and len(t) > 1]
    if not tokens:
        return None
    return " OR ".join(f'"{t}"*' for t in tokens[:16])


@dataclass
class Hit:
    chunk_id: int
    owner_type: str
    owner_id: int
    text: str
    score: float
    keyword_rank: int | None = None
    vector_rank: int | None = None
    vector_sim: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Indexer:
    def __init__(self, db: Database, embedder: Embedder | None = None):
        self.db = db
        self.embedder: Embedder = embedder or HashEmbedder()
        self._cache_lock = threading.Lock()
        self._matrix: np.ndarray | None = None
        self._ids: np.ndarray | None = None
        self._dirty = True

    def set_embedder(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self._dirty = True

    def invalidate(self) -> None:
        self._dirty = True

    async def _embed(self, texts: list[str]) -> tuple[list[bytes | None], str | None]:
        if not texts:
            return [], None
        try:
            vecs = await self.embedder.embed(texts)
            return [to_blob(v) for v in vecs], self.embedder.name
        except Exception as e:  # noqa: BLE001 - embeddings opcionais; FTS continua funcionando
            log.warning("Falha ao gerar embeddings (%s): %s — usando fallback local", self.embedder.name, e)
            fb = HashEmbedder()
            vecs = fb.embed_sync(texts)
            return [to_blob(v) for v in vecs], fb.name

    async def index(self, owner_type: str, owner_id: int, text: str, chunk: bool = True) -> int:
        pieces = chunk_text(text) if chunk else ([text] if text.strip() else [])
        blobs, model = await self._embed(pieces)
        now = utcnow()
        with self.db.transaction():
            self.db.execute("DELETE FROM chunks WHERE owner_type=? AND owner_id=?", (owner_type, owner_id))
            for i, (piece, blob) in enumerate(zip(pieces, blobs, strict=True)):
                self.db.execute(
                    "INSERT INTO chunks(owner_type, owner_id, ord, text, embedding, embed_model, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (owner_type, owner_id, i, piece, blob, model, now),
                )
        self._dirty = True
        return len(pieces)

    def remove(self, owner_type: str, owner_id: int) -> int:
        cur = self.db.execute("DELETE FROM chunks WHERE owner_type=? AND owner_id=?", (owner_type, owner_id))
        self._dirty = True
        return cur.rowcount

    async def reindex_all(self) -> int:
        rows = self.db.query("SELECT id, text FROM chunks ORDER BY id")
        total = 0
        for i in range(0, len(rows), 64):
            batch = rows[i : i + 64]
            blobs, model = await self._embed([r["text"] for r in batch])
            with self.db.transaction():
                for r, blob in zip(batch, blobs, strict=True):
                    self.db.execute("UPDATE chunks SET embedding=?, embed_model=? WHERE id=?", (blob, model, r["id"]))
            total += len(batch)
        self._dirty = True
        return total

    def _load_matrix(self) -> tuple[np.ndarray, np.ndarray]:
        with self._cache_lock:
            if self._dirty or self._matrix is None:
                rows = self.db.query(
                    "SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL AND embed_model=?",
                    (self.embedder.name,),
                )
                if rows:
                    self._ids = np.array([r["id"] for r in rows], dtype=np.int64)
                    self._matrix = np.vstack([from_blob(r["embedding"]) for r in rows])
                else:
                    self._ids = np.zeros(0, dtype=np.int64)
                    self._matrix = np.zeros((0, 1), dtype=np.float32)
                self._dirty = False
            return self._ids, self._matrix  # type: ignore[return-value]

    async def search(
        self,
        query: str,
        owner_types: list[str] | None = None,
        allowed: dict[str, set[int]] | None = None,
        limit: int = 10,
        candidates: int = 50,
    ) -> list[Hit]:
        """Busca híbrida. ``allowed`` restringe por dono (filtros de projeto/período/tipo)."""
        owner_types = owner_types or ["memory", "document", "clipboard"]
        placeholders = ",".join("?" * len(owner_types))

        def permitted(ot: str, oid: int) -> bool:
            if ot not in owner_types:
                return False
            return allowed is None or ot not in allowed or oid in allowed[ot]

        keyword: list[dict] = []
        q = fts_query(query)
        if q:
            try:
                keyword = self.db.query(
                    f"SELECT c.id, c.owner_type, c.owner_id, c.text, bm25(chunks_fts) AS rank"
                    f" FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid"
                    f" WHERE chunks_fts MATCH ? AND c.owner_type IN ({placeholders})"
                    f" ORDER BY rank LIMIT ?",
                    (q, *owner_types, candidates * 4),
                )
            except Exception as e:  # noqa: BLE001
                log.warning("FTS falhou: %s", e)
        keyword = [r for r in keyword if permitted(r["owner_type"], r["owner_id"])][:candidates]

        vector: list[tuple[int, float]] = []
        ids, matrix = self._load_matrix()
        if len(ids):
            try:
                qv = (await self.embedder.embed([query]))[0]
            except Exception:  # noqa: BLE001
                qv = None
            if qv is not None and qv.shape[0] == matrix.shape[1]:
                sims = matrix @ qv
                order = np.argsort(-sims)[: candidates * 4]
                vector = [(int(ids[i]), float(sims[i])) for i in order if sims[i] > 0.05]

        hits: dict[int, Hit] = {}
        for rank, r in enumerate(keyword):
            hits[r["id"]] = Hit(r["id"], r["owner_type"], r["owner_id"], r["text"], 1 / (60 + rank), keyword_rank=rank)
        if vector:
            vec_ids = [cid for cid, _ in vector]
            meta = {
                r["id"]: r
                for r in self.db.query(
                    f"SELECT id, owner_type, owner_id, text FROM chunks WHERE id IN ({','.join('?' * len(vec_ids))})",
                    tuple(vec_ids),
                )
            }
            rank = 0
            for cid, sim in vector:
                r = meta.get(cid)
                if not r or not permitted(r["owner_type"], r["owner_id"]):
                    continue
                h = hits.get(cid)
                if h is None:
                    h = hits[cid] = Hit(cid, r["owner_type"], r["owner_id"], r["text"], 0.0)
                h.score += 1 / (60 + rank)
                h.vector_rank, h.vector_sim = rank, sim
                rank += 1
                if rank >= candidates:
                    break
        # Um resultado por dono (o melhor trecho)
        best: dict[tuple[str, int], Hit] = {}
        for h in sorted(hits.values(), key=lambda x: -x.score):
            best.setdefault((h.owner_type, h.owner_id), h)
        return sorted(best.values(), key=lambda x: -x.score)[:limit]


async def run_sync(fn, *args):
    return await asyncio.to_thread(fn, *args)
