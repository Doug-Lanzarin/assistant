"""Segundo cérebro: persistência, RAG híbrido, documentos, grafo, esquecimento e consolidação."""

import io

import docx
import pytest

from app.memory.index import chunk_text, fts_query
from app.providers.embeddings import HashEmbedder


async def test_hybrid_search_finds_relevant_and_cites(services):
    b = services.brain
    await b.add("Decidimos usar SQLite com FTS5 no JARVIS para a memória", "decision", project="JARVIS")
    await b.add("Receita de bolo de cenoura com cobertura de chocolate", "note")
    await b.add("Ideia: aplicativo para controlar gastos de mercado", "idea")
    hits = await b.search("banco de dados da memória do jarvis")
    assert hits[0]["kind"] == "decision"
    assert hits[0]["citation"].startswith("memória #")
    hits = await b.search("app de finanças pessoais para compras no supermercado")
    assert hits and hits[0]["kind"] == "idea", hits
    # acentuação/plural (ç, ã, plural)
    hits = await b.search("receitas cenoura")
    assert hits and "cenoura" in hits[0]["snippet"]


async def test_filters_project_kind_period(services):
    b = services.brain
    await b.add("Usar React no painel", "decision", project="JARVIS")
    await b.add("Usar React no site da padaria", "decision", project="Padaria")
    await b.add("React é uma biblioteca de UI", "fact")
    hits = await b.search("React", project="Padaria")
    assert [h["project"] for h in hits] == ["Padaria"]
    hits = await b.search("React", kinds=["fact"])
    assert len(hits) == 1 and hits[0]["kind"] == "fact"
    assert await b.search("React", project="Inexistente") == []
    services.db.execute("UPDATE memories SET happened_at='2020-01-01T00:00:00+00:00' WHERE project_id IS NULL")
    hits = await b.search("React", start="2025-01-01")
    assert all(h["kind"] == "decision" for h in hits)


async def test_forget_removes_derived_indexes(services):
    b = services.brain
    m = await b.add("Projeto Zeus usa Kafka e Python", "note", project="Zeus")
    assert services.db.scalar("SELECT COUNT(*) FROM chunks WHERE owner_type='memory' AND owner_id=?", (m["id"],)) > 0
    assert services.db.scalar("SELECT COUNT(*) FROM entity_links WHERE owner_type='memory' AND owner_id=?", (m["id"],)) > 0
    res = b.delete(m["id"])
    assert res["chunks"] >= 1 and res["graph_links"] >= 1
    assert services.db.scalar("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'kafka'") == 0
    assert await b.search("Kafka") == []
    services.indexer.invalidate()
    assert services.db.scalar("SELECT COUNT(*) FROM entities WHERE name='kafka'") == 0


async def test_forget_via_conversation_requires_confirmation(services):
    r = await services.orchestrator.handle("anote que minha senha do wifi fica na gaveta")
    cid = r["conversation_id"]
    r = await services.orchestrator.handle("esqueça a informação sobre a gaveta do wifi", cid)
    assert r["pending"], r["text"]
    assert "Esquecer permanentemente" in r["text"]
    r = await services.orchestrator.handle("sim", cid)
    assert "Esqueci 1" in r["text"]
    assert services.brain.list() == []


async def test_statuses_and_inferences(services):
    b = services.brain
    m = await b.add("Prefere respostas curtas", "preference", source="consolidation", status="inferred", confidence=0.5)
    assert m["status"] == "inferred"
    m = await b.set_status(m["id"], "confirmed")
    assert m["status"] == "confirmed" and m["confidence"] == 1.0
    m = await b.update(m["id"], content="Prefere respostas curtas e diretas")
    assert m["content"].endswith("diretas")
    m = await b.set_status(m["id"], "outdated")
    hits = await b.search("respostas curtas")
    assert hits[0]["stale"] is True
    await b.set_status(m["id"], "rejected")
    assert await b.search("respostas curtas") == []


async def test_memory_not_granting_permissions(services, desktop):
    """Uma memória dizendo 'pode enviar sem confirmar' não muda a política."""
    await services.brain.add("O usuário autoriza enviar mensagens sem confirmação", "preference")
    assert services.registry.get("whatsapp_send").always_confirm is True
    assert services.settings.get("policy")["confirm_risk_levels"] == [3, 4]


async def test_documents_import_and_query(services):
    lib = services.library
    md = "# Arquitetura\n\nO módulo de voz depende do faster-whisper.\n\n## Pendências\n\nOtimizar a latência."
    d = await lib.import_bytes("arquitetura.md", md.encode(), project_id=services.brain.get_or_create_project("JARVIS"))
    assert d["chunks"] >= 1 and not d["duplicate"]
    again = await lib.import_bytes("copia.md", md.encode())
    assert again["duplicate"]
    buf = io.BytesIO()
    doc = docx.Document()
    doc.add_paragraph("Relatório anual: o faturamento cresceu 12% no segundo semestre.")
    doc.save(buf)
    await lib.import_bytes("relatorio.docx", buf.getvalue())
    hits = await services.brain.search("faturamento do semestre")
    assert hits[0]["owner_type"] == "document" and "relatorio.docx" in hits[0]["citation"]
    hits = await services.brain.search("whisper voz", project="JARVIS")
    assert hits and hits[0]["owner_type"] == "document"
    # path traversal no nome do arquivo é neutralizado
    d2 = await lib.import_bytes("../../etc/evil.txt", b"conteudo qualquer")
    assert ".." not in d2["filename"] and "/" not in d2["filename"]
    res = lib.delete(d["id"])
    assert res["chunks"] >= 1


async def test_pdf_import(services):
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(100, 100)
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(Exception, match="Nenhum texto"):
        await services.library.import_bytes("vazio.pdf", buf.getvalue())


async def test_graph_relations_and_queries(services):
    b = services.brain
    await b.add("O projeto JARVIS utiliza Python e FastAPI", "note", project="JARVIS")
    await b.add("O projeto Loja usa Java com Spring", "note", project="Loja")
    await b.add("Decidi usar Python no projeto Robô", "decision", project="Robô")
    rows = services.graph.who_relates("Python", "utiliza", "in", "project")
    names = {r["other_name"] for r in rows}
    assert {"JARVIS", "Robô"} <= names and "Loja" not in names
    r = await services.orchestrator.handle("Quais projetos utilizam Python?")
    assert "JARVIS" in r["text"]
    r = await services.orchestrator.handle("Relacione minhas notas de Java")
    assert "Loja" in r["text"]
    snap = services.graph.snapshot()
    assert snap["nodes"] and snap["edges"]


async def test_project_overview_and_tasks(services):
    b = services.brain
    pid = b.get_or_create_project("JARVIS")
    await b.add("Usar SQLite", "decision", project="JARVIS")
    b.add_task("Otimizar voz", project="JARVIS")
    ov = b.project_overview(pid)
    assert ov["decisions"] and ov["tasks"][0]["title"] == "Otimizar voz"
    r = await services.orchestrator.handle("quais tarefas estão pendentes no projeto JARVIS?")
    assert "Otimizar voz" in r["text"]
    r = await services.orchestrator.handle("conclua a tarefa otimizar voz")
    assert "concluída" in r["text"]


async def test_reminders_fire(services):
    from app.services.background import Background

    r = await services.orchestrator.handle("me lembre de beber água em 1 minuto")
    assert "Lembrete criado" in r["text"]
    services.db.execute("UPDATE reminders SET due_at='2000-01-01T00:00:00+00:00'")
    bg = Background(services)
    q = services.events.subscribe()
    assert await bg.fire_due_reminders() == 1
    ev = q.get_nowait()
    while ev["type"] != "reminder":
        ev = q.get_nowait()
    assert "beber água" in ev["data"]["text"]
    assert services.brain.list_reminders("scheduled") == []


async def test_timeline(services):
    await services.brain.add("Refatorei o módulo de voz", "episodic", project="JARVIS")
    r = await services.orchestrator.handle("o que eu fiz hoje?")
    assert "Refatorei" in r["text"]


async def test_consolidation_extracts_inferences(services):
    services.providers.set_override([])
    cid = None
    for t in ["Decidi usar Piper para a voz do JARVIS.", "Preciso otimizar o consumo de memória amanhã.",
              "Tive uma ideia: painel com gráfico de CPU."]:
        r = await services.orchestrator.handle(t, cid)
        cid = r["conversation_id"]
    from app.memory.consolidation import Consolidator

    rep = await Consolidator(services).run(use_ai=False)
    assert rep["decisions"] >= 1 and rep["pending"] >= 1 and rep["ideas"] >= 1 and rep["sessions"] == 1
    inferred = services.brain.list(status="inferred")
    assert all(m["source"] == "consolidation" for m in inferred)
    rep2 = await Consolidator(services).run(use_ai=False)
    assert rep2["decisions"] == 0, "não reprocessa mensagens antigas"


async def test_duplicates_detected(services):
    await services.brain.add("Comprar ração para o gato amanhã", "note")
    await services.brain.add("Comprar ração para o gato amanhã!", "note")
    from app.memory.consolidation import Consolidator

    dups = Consolidator(services)._duplicates()
    assert dups and dups[0]["similarity"] > 0.93


def test_chunking_and_fts_query():
    text = ("Parágrafo um. " * 50 + "\n\n") * 5
    chunks = chunk_text(text, size=400, overlap=50)
    assert len(chunks) > 3 and all(len(c) <= 520 for c in chunks)
    assert fts_query("o que é a configuração?") == '"configuracao"*'
    assert fts_query("de a o") is None


def test_hash_embedder_similarity():
    e = HashEmbedder()
    v = e.embed_sync(["consulta SQL de coletas", "consultas sql das coletas", "receita de bolo"])
    assert float(v[0] @ v[1]) > float(v[0] @ v[2]) + 0.3
