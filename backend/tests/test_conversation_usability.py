"""Usabilidade da conversa por voz: cumprimentos, IA local rápida, limites de tempo, preferências."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

import httpx
import pytest

from app.orchestrator import smalltalk
from app.orchestrator.tool_select import select_tools
from app.providers.base import LLMResponse, ProviderError, TurnState
from app.providers.ollama import OllamaProvider
from app.services.settings_store import DEFAULTS, SettingsStore

NIGHT = datetime(2026, 10, 24, 21, 30)
MORNING = datetime(2026, 10, 24, 8, 0)


@pytest.mark.parametrize("text", ["boa noite", "Boa noite!", "Jarvis, boa noite.", "Boa noite, Jarvis", "oi", "Olá Jarvis", "e aí"])
def test_cumprimentos_respondem_sem_ia(text):
    r = smalltalk.reply(text, "Doug Lanzarin", now=NIGHT)
    assert r and r.startswith("Boa noite, Doug!")


def test_espelha_o_cumprimento_mesmo_com_relogio_em_outro_fuso():
    assert smalltalk.reply("Boa noite, Jarvis", now=MORNING).startswith("Boa noite!")
    assert smalltalk.reply("bom dia", now=NIGHT).startswith("Bom dia!")


def test_cumprimento_segue_o_horario_e_conversa_continua():
    assert smalltalk.reply("oi", now=MORNING).startswith("Bom dia!")
    st: dict = {}
    assert "E com você?" in smalltalk.reply("oi, tudo bem?", state=st, now=NIGHT)
    assert smalltalk.reply("tudo ótimo também", state=st, now=NIGHT).startswith("Que bom!")


@pytest.mark.parametrize("text,start", [("obrigado", "Por nada"), ("Muito obrigado, Jarvis!", "Por nada"), ("valeu", "Por nada"),
                                        ("tchau", "Boa noite"), ("quem é você?", "Sou o JARVIS")])
def test_agradecimento_despedida_identidade(text, start):
    assert smalltalk.reply(text, now=NIGHT).startswith(start)


@pytest.mark.parametrize("text", ["que horas são", "boa noite, desligue as luzes da sala", "obrigado pela ajuda com o SQL",
                                  "Ponoichi.", "abra o VS Code", "bom dia é uma música?"])
def test_nao_captura_pedidos(text):
    assert smalltalk.reply(text, now=NIGHT) is None


def test_separa_cumprimento_do_comando():
    assert smalltalk.split_greeting("Boa noite, desligue as luzes da sala") == ("Boa noite", "desligue as luzes da sala")
    assert smalltalk.split_greeting("Olá Jarvis, que horas são?") == ("Olá Jarvis", "que horas são?")
    assert smalltalk.split_greeting("que horas são") == (None, "que horas são")


async def test_orquestrador_cumprimento_nao_dispara_rotina(services):
    """Antes: 'bom dia' (alias de rotina no exemplo) abria apps; 'boa noite' sem IA → 'não reconheci'."""
    from app.core.config import RoutineEntry, RoutineStep

    services.toml.routines.append(RoutineEntry(name="início do trabalho", aliases=["bom dia"],
                                               steps=[RoutineStep(tool="task_list", args={})]))
    r = await services.orchestrator.handle("bom dia")
    assert r["provider"] == "regras" and not r["actions"]
    assert "Em que posso ajudar" in r["text"] and 'rotina início do trabalho' in r["text"]
    r = await services.orchestrator.handle("rotina início do trabalho")
    assert r["actions"] and r["actions"][0]["tool"] == "routine_run"
    r = await services.orchestrator.handle("Jarvis, boa noite.")
    assert r["provider"] == "regras" and "Não reconheci" not in r["text"]


async def test_cumprimento_mais_comando_executa_o_comando(services):
    r = await services.orchestrator.handle("Boa noite, que horas são?")
    assert r["text"].startswith("Boa noite! ")
    assert any(a["tool"] == "datetime_now" for a in r["actions"])


def test_ferramentas_para_modelo_local_sao_poucas_e_relevantes(services):
    exposed = {t.name for t in services.registry.all() if t.expose_to_llm}
    assert len(exposed) > 40
    assert select_tools("me explica o que é recursão", exposed) == {"brain_search"}
    home = select_tools("desligue a luz do quarto", exposed)
    assert "home_turn" in home and len(home) <= 8
    assert "reminder_create" in select_tools("me lembre de pagar a conta amanhã", exposed)
    assert "whatsapp_send" in select_tools("manda mensagem pro João", exposed)
    full = len(json.dumps(services.registry.openai_tools(), ensure_ascii=False))
    small = len(json.dumps(services.registry.openai_tools(home), ensure_ascii=False))
    assert small < full / 5  # prompt muito menor → resposta muito mais rápida em CPU


# ---------------------------------------------------------------- Ollama (API nativa documentada)
def _ollama(handler) -> OllamaProvider:
    return OllamaProvider("http://127.0.0.1:11434", "qwen2.5:3b", timeout=5, transport=httpx.MockTransport(handler))


async def test_ollama_envia_num_ctx_keep_alive_e_le_ferramentas():
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body)
        assert req.url.path == "/api/chat"
        if len(seen) == 1:
            return httpx.Response(200, json={"model": "qwen2.5:3b", "message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "datetime_now", "arguments": {}}}]}, "done": True, "done_reason": "stop",
                "prompt_eval_count": 320, "eval_count": 12})
        return httpx.Response(200, json={"model": "qwen2.5:3b", "message": {"role": "assistant", "content": "São 21:30."},
                                         "done": True, "done_reason": "stop", "prompt_eval_count": 360, "eval_count": 6})

    p = _ollama(handler)
    st = p.start("sistema", [], "que horas são?")
    tools = [{"type": "function", "function": {"name": "datetime_now", "description": "hora", "parameters": {"type": "object"}}}]
    r1 = await p.step(st, tools)
    assert seen[0]["options"]["num_ctx"] == 8192 and seen[0]["keep_alive"] == "30m" and seen[0]["stream"] is False
    assert r1.tool_calls[0].name == "datetime_now" and r1.input_tokens == 320
    p.add_tool_results(st, r1, [(r1.tool_calls[0].id, '{"status":"ok"}', False)])
    r2 = await p.step(st, tools)
    assert r2.text == "São 21:30."
    sent = seen[1]["messages"]
    assert sent[-2]["tool_calls"][0]["function"]["arguments"] == {}  # argumentos como objeto (formato nativo)
    assert sent[-1] == {"role": "tool", "content": '{"status":"ok"}', "tool_name": "datetime_now"}


async def test_ollama_erros_viram_provider_error():
    def slow(req):
        raise httpx.ReadTimeout("lento", request=req)

    with pytest.raises(ProviderError, match="tempo esgotado"):
        await _ollama(slow).step(TurnState(system="s", messages=[]), None)
    with pytest.raises(ProviderError, match="HTTP 404"):
        await _ollama(lambda r: httpx.Response(404, text="model not found")).step(TurnState(system="s", messages=[]), None)


async def test_ollama_warm_carrega_modelo():
    calls = []

    def handler(req):
        calls.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={"done": True})

    assert await _ollama(handler).warm()
    assert calls == [("/api/generate", {"model": "qwen2.5:3b", "keep_alive": "30m"})]


async def test_limite_total_do_pedido_nunca_fica_processando(services):
    """Um modelo que não responde não segura o pedido além do limite (antes: até 6 × 60 s)."""

    class Hang:
        name, model, remote = "ollama", "lento", False

        def tool_format(self):
            return "openai"

        def start(self, system, history, user_text):
            return TurnState(system=system, messages=[])

        async def step(self, state, tools):
            await asyncio.sleep(30)
            return LLMResponse(text="tarde demais")

        async def available(self):
            return True, "ok"

    services.settings.update("ai", {"turn_deadline_s": 1.5, "mode": "local_only"})
    services.providers.set_override([Hang()])
    t0 = asyncio.get_running_loop().time()
    r = await services.orchestrator.handle("me explica o que é recursão")
    assert asyncio.get_running_loop().time() - t0 < 5
    assert "indisponível" in r["text"] and "tempo total" in r["text"]


# ---------------------------------------------------------------- preferências
def test_preferencias_guardam_so_diferencas_e_migram_padrao_antigo(services):
    db = services.db
    # Instalação antiga: a seção inteira gravada, com o antigo padrão "base".
    old = dict(DEFAULTS["voice"], stt_model="base")
    db.execute("INSERT OR REPLACE INTO settings(key, value, updated_at) VALUES ('voice', ?, 'x')", (json.dumps(old),))
    db.execute("DELETE FROM settings WHERE key='_settings_version'")
    st = SettingsStore(db)
    assert st.migrate() == 1
    assert st.get("voice")["stt_model"] == "small" and st.get("voice")["stt_beam_size"] == 5
    assert st.migrate() == 0  # uma vez só
    # Quem escolheu "tiny" depois da migração mantém a escolha.
    st.update("voice", {"stt_model": "tiny"})
    raw = json.loads(db.query_one("SELECT value FROM settings WHERE key='voice'")["value"])
    assert raw == {"stt_model": "tiny"}  # só a diferença
    assert st.get("voice")["stt_model"] == "tiny"
