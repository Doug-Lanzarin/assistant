"""Consolidação de memórias em segundo plano.

Produz apenas DADOS com status ``inferred`` (para o usuário confirmar ou
rejeitar): resumos de sessão, decisões e pendências extraídas, duplicatas,
contradições e conexões sugeridas. Nunca executa ferramentas nem altera
regras de segurança.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np

from app.core.db import from_json, to_json, utcnow
from app.orchestrator.textnorm import fold

log = logging.getLogger("jarvis.consolidation")

DECISION = re.compile(r"\b(decidi|decidimos|vamos usar|vou usar|optei|optamos|a decisao (e|foi)|ficou decidido|escolhi)\b")
PENDING = re.compile(r"\b(preciso|tenho que|temos que|falta|faltou|pendente|todo|a fazer|nao esquecer|lembrar de)\b")
IDEA = re.compile(r"\b(tive uma ideia|ideia:|que tal|seria legal|poderiamos|poderia criar)\b")
NEGATION = re.compile(r"\b(nao|nunca|jamais|odeio|detesto|evito)\b")
STATE_KEY = "_consolidation_state"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 12]


class Consolidator:
    def __init__(self, services):
        self.s = services

    def _state(self) -> dict[str, Any]:
        row = self.s.db.query_one("SELECT value FROM settings WHERE key=?", (STATE_KEY,))
        return from_json(row["value"], {}) if row else {}

    def _save_state(self, st: dict) -> None:
        self.s.db.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET"
            " value=excluded.value, updated_at=excluded.updated_at", (STATE_KEY, to_json(st), utcnow()),
        )

    def last_report(self) -> dict:
        return self._state().get("last_report", {})

    async def run(self, use_ai: bool = True) -> dict[str, Any]:
        st = self._state()
        last_msg = int(st.get("last_message_id", 0))
        report: dict[str, Any] = {"started_at": utcnow(), "sessions": 0, "decisions": 0, "pending": 0, "ideas": 0,
                                  "duplicates": [], "contradictions": [], "connections": 0}
        convs = self.s.db.query(
            "SELECT conversation_id, MAX(id) AS max_id FROM messages WHERE id > ? GROUP BY conversation_id", (last_msg,)
        )
        max_seen = last_msg
        for c in convs:
            msgs = self.s.db.query(
                "SELECT id, role, content, meta FROM messages WHERE conversation_id=? AND id > ? ORDER BY id",
                (c["conversation_id"], last_msg),
            )
            max_seen = max(max_seen, c["max_id"])
            user_msgs = [m for m in msgs if m["role"] == "user"]
            if len(user_msgs) < 2:
                continue
            await self._extract(c["conversation_id"], user_msgs, report)
            await self._summarize_session(c["conversation_id"], msgs, report, use_ai)
        report["duplicates"] = self._duplicates()
        report["contradictions"] = self._contradictions()
        report["connections"] = self._connections()
        report["finished_at"] = utcnow()
        st["last_message_id"] = max_seen
        st["last_report"] = report
        self._save_state(st)
        await self.s.events.publish("consolidation", {k: v if not isinstance(v, list) else len(v) for k, v in report.items()})
        return report

    async def _extract(self, cid: int, user_msgs: list[dict], report: dict) -> None:
        for m in user_msgs:
            if from_json(m["meta"], {}).get("origin") not in (None, "user", "voice"):
                continue
            for sent in _sentences(m["content"]):
                f = fold(sent)
                kind = "decision" if DECISION.search(f) else "idea" if IDEA.search(f) else "note" if PENDING.search(f) else None
                if not kind:
                    continue
                ref = f"conv:{cid}:msg:{m['id']}"
                if self.s.db.query_one("SELECT id FROM memories WHERE source_ref=? AND content=?", (ref, sent)):
                    continue
                tags = ["pendência"] if kind == "note" else []
                await self.s.brain.add(sent, kind, source="consolidation", status="inferred", confidence=0.5,
                                       tags=tags, source_ref=ref)
                report[{"decision": "decisions", "idea": "ideas", "note": "pending"}[kind]] += 1

    async def _summarize_session(self, cid: int, msgs: list[dict], report: dict, use_ai: bool) -> None:
        ref = f"conv:{cid}:upto:{msgs[-1]['id']}"
        if self.s.db.query_one("SELECT id FROM memories WHERE source_ref=?", (ref,)):
            return
        transcript = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in msgs[-40:])
        summary = None
        if use_ai:
            try:
                res = await self.s.orchestrator._summarize(
                    "Resuma esta sessão de trabalho em até 5 linhas: objetivo, decisões e pendências.", transcript,
                    "resumo da sessão")
                summary = res["text"] if res else None
            except Exception:  # noqa: BLE001
                log.exception("Resumo com IA falhou")
        if not summary:
            asks = [m["content"][:120] for m in msgs if m["role"] == "user"][:8]
            summary = "Pedidos da sessão: " + "; ".join(asks)
        conv = self.s.db.query_one("SELECT title FROM conversations WHERE id=?", (cid,))
        await self.s.brain.add(summary, "session_summary", title=f"Sessão: {(conv or {}).get('title', cid)}",
                               source="consolidation", status="inferred", confidence=0.6, source_ref=ref)
        report["sessions"] += 1

    def _duplicates(self, threshold: float = 0.93) -> list[dict]:
        rows = self.s.db.query(
            "SELECT c.owner_id, c.embedding FROM chunks c JOIN memories m ON m.id=c.owner_id"
            " WHERE c.owner_type='memory' AND c.ord=0 AND c.embed_model=? AND m.status!='rejected'"
            " ORDER BY c.owner_id DESC LIMIT 2000", (self.s.indexer.embedder.name,),
        )
        if len(rows) < 2:
            return []
        ids = [r["owner_id"] for r in rows]
        mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
        sims = mat @ mat.T
        out = []
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                if sims[i, j] >= threshold:
                    out.append({"a": ids[i], "b": ids[j], "similarity": round(float(sims[i, j]), 3)})
                    if len(out) >= 50:
                        return out
        return out

    def _contradictions(self) -> list[dict]:
        prefs = self.s.db.query("SELECT id, content FROM memories WHERE kind='preference' AND status NOT IN ('rejected','outdated')")
        out = []
        for i, a in enumerate(prefs):
            ta = set(re.findall(r"[a-z]{4,}", fold(a["content"])))
            for b in prefs[i + 1:]:
                tb = set(re.findall(r"[a-z]{4,}", fold(b["content"])))
                if not ta or not tb:
                    continue
                overlap = len(ta & tb) / min(len(ta), len(tb))
                neg_a, neg_b = bool(NEGATION.search(fold(a["content"]))), bool(NEGATION.search(fold(b["content"])))
                if overlap >= 0.5 and neg_a != neg_b:
                    out.append({"a": a["id"], "b": b["id"], "reason": "preferências semelhantes com sentidos opostos"})
        return out[:50]

    def _connections(self) -> int:
        pairs = self.s.db.query(
            "SELECT l1.entity_id AS a, l2.entity_id AS b, COUNT(*) AS n FROM entity_links l1"
            " JOIN entity_links l2 ON l1.owner_type=l2.owner_type AND l1.owner_id=l2.owner_id AND l1.entity_id < l2.entity_id"
            " GROUP BY l1.entity_id, l2.entity_id HAVING n >= 2 LIMIT 200"
        )
        created = 0
        for p in pairs:
            exists = self.s.db.query_one(
                "SELECT id FROM relations WHERE (src_id=? AND dst_id=?) OR (src_id=? AND dst_id=?)", (p["a"], p["b"], p["b"], p["a"])
            )
            if not exists:
                self.s.graph.relate(p["a"], "relacionado_a", p["b"], "consolidation", None, min(0.9, 0.3 + 0.1 * p["n"]), "inferred")
                created += 1
        return created
