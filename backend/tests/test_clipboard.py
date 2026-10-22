"""Fluxo completo do clipboard: Ctrl+C → "salve" → "encontre" → "copie" → Ctrl+V."""

import pytest

from app.clipboard_memory.classify import classify

SQL = "SELECT c.id,\n       c.data_coleta\n  FROM coletas c\n WHERE c.status = 'ok'\t-- tab e acentuação: ção\n"


async def say(s, text, cid=None):
    return await s.orchestrator.handle(text, cid)


async def test_save_find_copy_roundtrip(services, desktop):
    desktop.clipboard.set_text(SQL)
    r = await say(services, "Jarvis, salve o que copiei como consulta SQL de coletas")
    assert "Salvei" in r["text"], r
    cid = r["conversation_id"]
    item = services.clipboard.list()[0]
    assert item["title"] == "consulta SQL de coletas"
    assert item["category"] == "sql"

    # Usuário copia outra coisa
    desktop.clipboard.set_text("outra coisa")
    r = await say(services, "Jarvis, encontre a consulta SQL de coletas", cid)
    assert "consulta SQL de coletas" in r["text"]

    r = await say(services, "Jarvis, copie a consulta SQL de coletas", cid)
    assert "Copiei" in r["text"], r["text"]
    # Conteúdo original preservado byte a byte (quebras de linha, tabs, acentos)
    assert desktop.clipboard.read() == {"format": "text", "text": SQL}
    assert services.clipboard.get(item["id"], include_content=False)["copy_count"] == 1


async def test_duplicate_not_saved_twice(services, desktop):
    desktop.clipboard.set_text("git log --oneline --graph")
    await say(services, "salve o que copiei")
    r = await say(services, "salve o que copiei")
    assert "já estava salvo" in r["text"]
    assert len(services.clipboard.list()) == 1
    assert services.clipboard.list()[0]["category"] == "git"


async def test_empty_and_non_text_clipboard(services, desktop):
    r = await say(services, "salve o que copiei")
    assert "vazia" in r["text"]
    desktop.clipboard.set_other("image")
    r = await say(services, "salve o que copiei")
    assert "image" in r["text"] and "não são suportados" in r["text"]
    assert services.clipboard.list() == []


async def test_never_reads_without_request(services, desktop):
    calls = []
    orig = desktop.d.methods["clipboard.read"]

    async def spy(p):
        calls.append(1)
        return await orig(p)

    desktop.d.methods["clipboard.read"] = spy
    await say(services, "que horas são?")
    await say(services, "quais tarefas estão pendentes?")
    assert calls == []


async def test_sensitive_content_encrypted_and_hidden(services, desktop):
    secret = "ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
    desktop.clipboard.set_text(secret)
    r = await say(services, "salve o que copiei como chave da api")
    assert "cifrado" in r["text"]
    row = services.db.query_one("SELECT * FROM clipboard_items")
    assert row["encrypted"] == 1 and secret not in row["content"]
    # Não indexado em texto pleno
    chunks = services.db.query("SELECT text FROM chunks WHERE owner_type='clipboard'")
    assert all("sk-ant" not in c["text"] for c in chunks)
    # Ainda pode ser copiado de volta
    desktop.clipboard.set_text("x")
    r = await say(services, "copie a chave da api", r["conversation_id"])
    assert desktop.clipboard.read()["text"] == secret
    # Busca não revela o conteúdo
    found = await services.clipboard.search("chave da api")
    assert "sk-ant" not in found[0]["preview"]


async def test_update_rename_delete_with_confirmation(services, desktop):
    desktop.clipboard.set_text("docker compose up -d")
    r = await say(services, "salve o que copiei como subir containers")
    cid = r["conversation_id"]
    desktop.clipboard.set_text("docker compose up -d --build")
    r = await say(services, "Atualize esse registro com o que copiei agora", cid)
    assert "Atualizei" in r["text"], r["text"]
    item = services.clipboard.list()[0]
    assert services.clipboard.get(item["id"])["content"] == "docker compose up -d --build"
    assert len(services.clipboard.history(item["id"])) == 1

    r = await say(services, "Renomeie esse conteúdo para Subir containers com build", cid)
    assert "Renomeei" in r["text"]

    r = await say(services, "Apague o registro que salvei por engano", cid)
    assert r["pending"], "exclusão deve exigir confirmação"
    assert services.clipboard.list(), "nada apagado antes da confirmação"
    r = await say(services, "sim", cid)
    assert "Apaguei" in r["text"]
    assert services.clipboard.list() == []


async def test_ambiguous_copy_asks_and_choice_resolves(services, desktop):
    for t in ("SELECT 1 FROM coletas_a", "SELECT 2 FROM coletas_b"):
        await services.clipboard.save_text(t, title="consulta de coletas")
    desktop.clipboard.set_text("antes")
    r = await say(services, "copie a consulta de coletas")
    assert "mais de um" in r["text"]
    assert desktop.clipboard.read()["text"] == "antes", "não sobrescreve clipboard em caso ambíguo"
    r = await say(services, "o segundo", r["conversation_id"])
    assert "Copiei" in r["text"], r["text"]
    assert desktop.clipboard.read()["text"].startswith("SELECT")


async def test_list_by_category_and_git(services, desktop):
    await services.clipboard.save_text("git rebase -i HEAD~3", title="rebase interativo")
    await services.clipboard.save_text("git stash pop", title="recuperar stash")
    await services.clipboard.save_text("SELECT now()", title="hora do banco")
    r = await say(services, "Liste meus comandos Git salvos")
    assert "rebase interativo" in r["text"] and "recuperar stash" in r["text"] and "hora do banco" not in r["text"]
    r = await say(services, "Mostre os registros da categoria SQL")
    assert "hora do banco" in r["text"] and "rebase" not in r["text"]


async def test_project_link_and_export_import(services, desktop):
    desktop.clipboard.set_text("FROM python:3.13-slim\nRUN pip install uv")
    await say(services, "Guarde isso no projeto JARVIS")
    item = services.clipboard.list()[0]
    assert item["project_name"] == "JARVIS"
    exported = services.clipboard.export()
    services.clipboard.delete(item["id"])
    res = await services.clipboard.import_items(exported)
    assert res == {"created": 1, "skipped": 0}
    assert services.clipboard.list()[0]["content_format"] == "text"


async def test_agent_missing_reports_truthfully(services):
    r = await say(services, "salve o que copiei")
    assert "agente local" in r["text"].lower()


@pytest.mark.parametrize("text,cat", [
    ("SELECT * FROM t", "sql"), ("git push origin main", "git"), ("docker run -it ubuntu", "docker"),
    ("Get-ChildItem -Recurse", "powershell"), ("def f(x):\n    return x", "python"), ('{"a": 1}', "json"),
    ("https://exemplo.com/x", "url"), ("Olá, tudo bem?", "texto"),
])
def test_classify(text, cat):
    assert classify(text) == cat
