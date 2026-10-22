"""Grafo de conhecimento relacional (SQLite).

Entidades: project, person, idea, decision, technology, document, task, event,
goal, learning, tag. Relações dirigidas com origem e confiança.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.db import Database, utcnow
from app.orchestrator.textnorm import fold, normalize_key

TECHNOLOGIES = {
    "python", "java", "javascript", "typescript", "react", "vue", "angular", "node", "node.js", "fastapi",
    "django", "flask", "spring", "spring boot", "sql", "sqlite", "postgres", "postgresql", "mysql",
    "oracle", "mongodb", "redis", "docker", "kubernetes", "git", "github", "linux", "windows",
    "powershell", "c#", ".net", "go", "rust", "kotlin", "swift", "php", "html", "css", "tailwind",
    "vite", "ollama", "whisper", "faster-whisper", "piper", "home assistant", "alexa", "whatsapp",
    "aws", "azure", "gcp", "terraform", "ansible", "kafka", "rabbitmq", "graphql", "rest", "api",
    "excel", "power bi", "pandas", "numpy", "pytorch", "tensorflow", "claude", "openai", "llm", "rag",
    "android", "ios", "flutter", "electron", "selenium", "playwright", "pytest", "junit", "maven",
    "gradle", "nginx", "apache", "jenkins", "sap", "delphi", "cobol",
}

RELATION_LABELS = {
    "utiliza": "utiliza", "possui": "possui", "depende_de": "depende de", "menciona": "menciona",
    "decidiu": "decidiu", "pertence_a": "pertence a", "relacionado_a": "relacionado a",
    "tem_tarefa": "tem tarefa", "envolve": "envolve", "aprendeu": "aprendeu",
}

_USE_VERBS = re.compile(r"\b(usa|usar|usando|utiliza|utilizar|utilizando|feito em|escrito em|com base em|baseado em|migrar para|adotar|adotamos|vamos usar)\b")


class Graph:
    def __init__(self, db: Database):
        self.db = db

    def upsert_entity(self, type_: str, name: str) -> int:
        norm = normalize_key(name)
        row = self.db.query_one("SELECT id FROM entities WHERE type=? AND normalized=?", (type_, norm))
        if row:
            return row["id"]
        return self.db.insert(
            "INSERT INTO entities(type, name, normalized, created_at) VALUES (?,?,?,?)",
            (type_, name.strip(), norm, utcnow()),
        )

    def link(self, entity_id: int, owner_type: str, owner_id: int) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO entity_links(entity_id, owner_type, owner_id) VALUES (?,?,?)",
            (entity_id, owner_type, owner_id),
        )

    def relate(
        self, src: int, rel: str, dst: int, source_type: str | None = None, source_id: int | None = None,
        confidence: float = 1.0, status: str = "explicit",
    ) -> int:
        if src == dst:
            return 0
        self.db.execute(
            "INSERT INTO relations(src_id, rel, dst_id, source_type, source_id, confidence, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(src_id, rel, dst_id) DO UPDATE SET"
            " confidence=MAX(confidence, excluded.confidence)",
            (src, rel, dst, source_type, source_id, confidence, status, utcnow()),
        )
        return int(self.db.scalar("SELECT id FROM relations WHERE src_id=? AND rel=? AND dst_id=?", (src, rel, dst)))

    def unlink_owner(self, owner_type: str, owner_id: int) -> int:
        n = self.db.execute(
            "DELETE FROM entity_links WHERE owner_type=? AND owner_id=?", (owner_type, owner_id)
        ).rowcount
        n += self.db.execute(
            "DELETE FROM relations WHERE source_type=? AND source_id=?", (owner_type, owner_id)
        ).rowcount
        # Remove entidades órfãs que não são projetos
        self.db.execute(
            "DELETE FROM entities WHERE type NOT IN ('project') AND id NOT IN (SELECT entity_id FROM entity_links)"
            " AND id NOT IN (SELECT src_id FROM relations) AND id NOT IN (SELECT dst_id FROM relations)"
        )
        return n

    # -- extração heurística ---------------------------------------------------
    def extract(self, text: str, known_projects: list[str]) -> dict[str, list[str]]:
        t = " " + fold(text) + " "
        techs = sorted({tech for tech in TECHNOLOGIES if re.search(r"(?<![a-z0-9])" + re.escape(tech) + r"(?![a-z0-9])", t)})
        projects = [p for p in known_projects if re.search(r"(?<![a-z0-9])" + re.escape(fold(p)) + r"(?![a-z0-9])", t)]
        tags = sorted(set(re.findall(r"#([\w\-]{2,30})", text)))
        people = sorted(set(re.findall(r"\b(?:com|para|do|da|ao|à)\s+(?:o |a )?([A-ZÁÉÍÓÚÂÊÔÃÕ][a-záéíóúâêôãõç]{2,}(?: [A-ZÁÉÍÓÚ][a-záéíóúâêôãõç]{2,})?)", text)))
        people = [p for p in people if fold(p) not in TECHNOLOGIES and p not in projects]
        return {"technology": techs, "project": projects, "tag": tags, "person": people}

    def index_owner(
        self, owner_type: str, owner_id: int, text: str, kind: str | None, project: str | None,
        title: str | None = None,
    ) -> dict[str, Any]:
        known = [r["name"] for r in self.db.query("SELECT name FROM projects")]
        found = self.extract(text, known)
        if project and project not in found["project"]:
            found["project"].append(project)
        entity_ids: dict[str, list[int]] = {}
        for type_, names in found.items():
            for name in names:
                eid = self.upsert_entity(type_, name)
                self.link(eid, owner_type, owner_id)
                entity_ids.setdefault(type_, []).append(eid)
        # Entidade do próprio item (ideia, decisão, aprendizado, documento, tarefa)
        own_type = {"idea": "idea", "decision": "decision", "learning": "learning", "goal": "goal",
                    "event": "event", "document": "document", "task": "task"}.get(kind or "")
        own_id = None
        if own_type:
            own_id = self.upsert_entity(own_type, (title or text)[:120])
            self.link(own_id, owner_type, owner_id)
        uses = bool(_USE_VERBS.search(fold(text)))
        for pid in entity_ids.get("project", []):
            for tid in entity_ids.get("technology", []):
                self.relate(pid, "utiliza" if uses else "menciona", tid, owner_type, owner_id,
                            0.7 if uses else 0.4, "inferred")
            for person in entity_ids.get("person", []):
                self.relate(pid, "envolve", person, owner_type, owner_id, 0.5, "inferred")
            if own_id:
                rel = {"decision": "decidiu", "task": "tem_tarefa", "document": "possui"}.get(kind or "", "possui")
                self.relate(pid, rel, own_id, owner_type, owner_id, 0.9, "explicit")
        if own_id:
            for tid in entity_ids.get("technology", []):
                self.relate(own_id, "relacionado_a", tid, owner_type, owner_id, 0.5, "inferred")
        return {k: v for k, v in found.items() if v}

    # -- consultas -------------------------------------------------------------
    def find_entities(self, query: str, limit: int = 10) -> list[dict]:
        norm = normalize_key(query)
        if not norm:
            return []
        exact = self.db.query("SELECT * FROM entities WHERE normalized=? LIMIT ?", (norm, limit))
        if exact:
            return exact
        like = "%" + norm.replace("%", "") + "%"
        return self.db.query("SELECT * FROM entities WHERE normalized LIKE ? ORDER BY length(name) LIMIT ?", (like, limit))

    def neighbors(self, entity_id: int) -> list[dict]:
        return self.db.query(
            "SELECT r.id, r.rel, r.confidence, r.status, 'out' AS direction, e.id AS other_id, e.type AS other_type,"
            " e.name AS other_name FROM relations r JOIN entities e ON e.id = r.dst_id WHERE r.src_id=?"
            " UNION ALL "
            "SELECT r.id, r.rel, r.confidence, r.status, 'in' AS direction, e.id, e.type, e.name"
            " FROM relations r JOIN entities e ON e.id = r.src_id WHERE r.dst_id=?"
            " ORDER BY 3 DESC",
            (entity_id, entity_id),
        )

    def sources_of(self, entity_id: int, limit: int = 20) -> list[dict]:
        return self.db.query(
            "SELECT owner_type, owner_id FROM entity_links WHERE entity_id=? LIMIT ?", (entity_id, limit)
        )

    def who_relates(self, entity_query: str, rel: str | None, direction: str = "in", type_: str | None = "project") -> list[dict]:
        ents = self.find_entities(entity_query, 5)
        out = []
        for e in ents:
            for n in self.neighbors(e["id"]):
                if rel and n["rel"] not in (rel, "menciona" if rel == "utiliza" else rel):
                    continue
                if n["direction"] != direction:
                    continue
                if type_ and n["other_type"] != type_:
                    continue
                out.append({"entity": e["name"], **n})
        return out

    def snapshot(self, limit: int = 300) -> dict[str, Any]:
        nodes = self.db.query(
            "SELECT e.id, e.type, e.name, (SELECT COUNT(*) FROM entity_links l WHERE l.entity_id=e.id) AS mentions"
            " FROM entities e ORDER BY mentions DESC LIMIT ?",
            (limit,),
        )
        ids = {n["id"] for n in nodes}
        edges = [
            e for e in self.db.query("SELECT id, src_id, rel, dst_id, confidence, status FROM relations")
            if e["src_id"] in ids and e["dst_id"] in ids
        ]
        return {"nodes": nodes, "edges": edges}
