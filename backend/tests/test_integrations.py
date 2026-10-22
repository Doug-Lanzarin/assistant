"""Integrações com serviços externos usando servidores HTTP simulados (MockTransport).

Estes testes validam o protocolo e a lógica — NÃO substituem o teste com um
Home Assistant / Meta reais (ver docs/RELATORIO_TESTES.md).
"""

import hashlib
import hmac
import json

import httpx
import pytest

from app.integrations.home_assistant.client import HomeAssistantClient
from app.orchestrator.registry import ToolContext


class FakeHA:
    def __init__(self):
        self.states = {
            "light.sala_teto": {"state": "on", "attributes": {"friendly_name": "Luz do teto da sala"}},
            "light.sala_abajur": {"state": "on", "attributes": {"friendly_name": "Abajur da sala"}},
            "switch.tv_sala": {"state": "off", "attributes": {"friendly_name": "Tomada da TV"}},
            "light.quarto": {"state": "off", "attributes": {"friendly_name": "Luz do quarto"}},
            "climate.tcl_quarto": {"state": "off", "attributes": {"friendly_name": "Ar TCL", "temperature": 25,
                                                                   "current_temperature": 27.5, "min_temp": 16, "max_temp": 31}},
            "sensor.temp_sala": {"state": "24.1", "attributes": {"friendly_name": "Temperatura sala", "device_class": "temperature",
                                                                  "unit_of_measurement": "°C"}},
            "scene.boa_noite": {"state": "scening", "attributes": {"friendly_name": "Boa noite"}},
            "lock.porta": {"state": "locked", "attributes": {"friendly_name": "Fechadura da porta"}},
        }
        self.areas = {"light.sala_teto": "Sala", "light.sala_abajur": "Sala", "switch.tv_sala": "Sala",
                      "light.quarto": "Quarto", "climate.tcl_quarto": "Quarto", "sensor.temp_sala": "Sala"}
        self.calls = []
        self.broken = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != "Bearer tok":
            return httpx.Response(401)
        path = request.url.path
        if path == "/api/":
            return httpx.Response(200, json={"message": "API running."})
        if path == "/api/states":
            return httpx.Response(200, json=[{"entity_id": k, **v} for k, v in self.states.items()])
        if path.startswith("/api/states/"):
            eid = path.split("/")[-1]
            return httpx.Response(200, json={"entity_id": eid, **self.states[eid]})
        if path == "/api/template":
            body = json.loads(request.content)
            return httpx.Response(200, text=json.dumps([[e, self.areas.get(e)] for e in body["variables"]["ids"]]),
                                  headers={"content-type": "text/plain"})
        if path.startswith("/api/services/"):
            _, _, _, dom, srv = path.split("/")
            data = json.loads(request.content)
            self.calls.append((dom, srv, data))
            eid = data.get("entity_id")
            if eid in self.broken:
                return httpx.Response(200, json=[])
            st = self.states.get(eid)
            if st is not None:
                if srv == "turn_on":
                    st["state"] = "cool" if dom == "climate" else "on"
                elif srv == "turn_off":
                    st["state"] = "off"
                elif srv == "set_temperature":
                    st["attributes"]["temperature"] = data["temperature"]
                elif srv == "unlock":
                    st["state"] = "unlocked"
            return httpx.Response(200, json=[])
        return httpx.Response(404)


@pytest.fixture
def ha(services):
    fake = FakeHA()
    transport = httpx.MockTransport(fake.handler)
    services.settings.update("home_assistant", {"url": "http://ha.local:8123"})
    services.secrets.set("ha_token", "tok")
    services.home._client_factory = lambda: HomeAssistantClient("http://ha.local:8123", "tok", transport=transport)
    services.home.verify_delay = 0
    return fake


async def say(s, text, cid=None):
    return await s.orchestrator.handle(text, cid)


async def test_ha_sync_and_rooms(services, ha):
    devs = await services.home.sync()
    sala = [d for d in devs if d["room"] == "Sala"]
    assert len(sala) == 4


async def test_turn_off_room_lights_verified(services, ha):
    r = await say(services, "Jarvis, desligue as luzes da sala")
    assert "estado confirmado" in r["text"], r["text"]
    assert ha.states["light.sala_teto"]["state"] == "off" and ha.states["light.sala_abajur"]["state"] == "off"
    assert ha.states["switch.tv_sala"]["state"] == "off"  # não tocou na tomada (não é luz)
    assert all(c[0] == "light" for c in ha.calls)


async def test_climate_tcl(services, ha):
    services.settings.update("tcl", {"climate_entity": "climate.tcl_quarto"})
    r = await say(services, "Jarvis, ligue o ar-condicionado")
    assert "Ar TCL" in r["text"] and "confirmado" in r["text"]
    r = await say(services, "Jarvis, ajuste o ar para 23 graus")
    assert "23 °C" in r["text"] and "confirmado" in r["text"], r["text"]
    assert ha.states["climate.tcl_quarto"]["attributes"]["temperature"] == 23
    r = await say(services, "ajuste o ar para 40 graus")
    assert ha.states["climate.tcl_quarto"]["attributes"]["temperature"] == 23
    assert r["actions"][0]["status"] == "invalid"


async def test_unverified_state_reported_truthfully(services, ha):
    ha.broken.add("light.quarto")
    r = await say(services, "ligue a luz do quarto")
    assert "NÃO mudou" in r["text"]
    assert r["actions"][0]["status"] == "error"


async def test_sensor_scene_and_sensitive_lock(services, ha):
    r = await say(services, "qual é a temperatura da sala?")
    assert "24.1°C" in r["text"]
    r = await say(services, "execute a cena boa noite")
    assert "Boa noite" in r["text"]
    r = await say(services, "ligue a fechadura da porta")
    assert r["pending"], "fechadura exige confirmação (risco crítico)"
    assert ha.states["lock.porta"]["state"] == "locked"


async def test_ha_auth_error_and_offline(services, ha):
    services.home._client_factory = lambda: HomeAssistantClient(
        "http://ha.local:8123", "errado", transport=httpx.MockTransport(ha.handler))
    services.db.execute("DELETE FROM devices")
    r = await say(services, "desligue as luzes da sala")
    assert "401" in r["text"]

    def down(request):
        raise httpx.ConnectError("offline")

    services.home._client_factory = lambda: HomeAssistantClient("http://ha.local:8123", "tok", transport=httpx.MockTransport(down))
    r = await say(services, "desligue as luzes da sala")
    assert "Falha de comunicação" in r["text"]


async def test_ha_not_configured(services):
    r = await say(services, "ligue as luzes da sala")
    assert "Configure o Home Assistant" in r["text"] or "não configurado" in r["text"]


async def test_ambiguous_device(services, ha):
    r = await say(services, "ligue a luz")
    assert "mais de um dispositivo" in r["text"]


# --------------------------------------------------------------------------- WhatsApp
def _cloud(calls, status=200, body=None):
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body or {"messages": [{"id": "wamid.ABC"}]})

    return httpx.MockTransport(handler)


async def test_whatsapp_business_send_flow(services):
    calls = []
    services.whatsapp._transport = _cloud(calls)
    services.settings.update("whatsapp", {"mode": "business", "phone_number_id": "999"})
    services.secrets.set("whatsapp_cloud_token", "EAAtoken")
    services.whatsapp.add_contact("João Silva", "+55 (11) 99999-8888")
    services.whatsapp.add_contact("Maria", "5521988887777")
    r = await say(services, "Jarvis, mande uma mensagem para o João dizendo que estou chegando")
    assert "Encontrei João Silva" in r["text"] and "Estou chegando" in r["text"]
    assert calls == []
    r = await say(services, "pode enviar", r["conversation_id"])
    assert "Mensagem enviada para João Silva" in r["text"] and "wamid.ABC" in r["text"]
    body = json.loads(calls[0].content)
    assert body["to"] == "5511999998888" and body["text"]["body"] == "Estou chegando"
    assert calls[0].url.path == "/v23.0/999/messages"
    assert services.whatsapp.outbox()[0]["status"] == "sent"


async def test_whatsapp_ambiguous_contact_and_failure(services):
    calls = []
    services.whatsapp._transport = _cloud(calls, 400, {"error": {"message": "Re-engagement message", "code": 131047}})
    services.settings.update("whatsapp", {"mode": "business", "phone_number_id": "999"})
    services.secrets.set("whatsapp_cloud_token", "EAAtoken")
    services.whatsapp.add_contact("João Silva", "5511999998888")
    services.whatsapp.add_contact("João Pereira", "5511977776666")
    r = await say(services, "mande uma mensagem para o João dizendo que cheguei")
    assert "mais de um contato" in r["text"]
    r = await say(services, "João Pereira", r["conversation_id"])
    assert r["pending"], r["text"]
    r = await say(services, "sim", r["conversation_id"])
    assert "NÃO foi enviada" in r["text"] and "template" in r["text"]
    assert services.whatsapp.outbox()[0]["status"] == "failed"


async def test_whatsapp_send_disabled_mode(services):
    r = await say(services, "mande uma mensagem para a Ana dizendo oi")
    assert "Envio indisponível" in r["text"]


async def test_whatsapp_webhook_signature(client, services):
    services.secrets.set("whatsapp_app_secret", "s3cr3t")
    services.secrets.set("whatsapp_verify_token", "vt")
    r = client.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"
    assert client.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"}).status_code == 403
    payload = {"entry": [{"changes": [{"value": {"contacts": [{"wa_id": "5511", "profile": {"name": "Ana"}}],
                                                 "messages": [{"from": "5511", "id": "wamid.1", "timestamp": "1700000000",
                                                               "type": "text", "text": {"body": "Oi Jarvis"}}]}}]}]}
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"s3cr3t", raw, hashlib.sha256).hexdigest()
    noauth = {"Authorization": ""}
    assert client.post("/api/whatsapp/webhook", content=raw, headers={**noauth, "X-Hub-Signature-256": "sha256=00"}).status_code == 401
    r = client.post("/api/whatsapp/webhook", content=raw, headers={**noauth, "X-Hub-Signature-256": sig, "Content-Type": "application/json"})
    assert r.json() == {"ok": True, "ingested": 1}
    msgs = services.db.query("SELECT sender, text FROM whatsapp_messages")
    assert msgs == [{"sender": "Ana", "text": "Oi Jarvis"}]


async def test_whatsapp_notifications_ingest_and_read(services):
    services.settings.update("whatsapp", {"mode": "notifications"})
    await services.whatsapp.handle_agent_event("notification", {"app": "WhatsApp", "title": "Carla", "body": "Chego às 8", "id": "n1"})
    await services.whatsapp.handle_agent_event("notification", {"app": "WhatsApp", "title": "Carla", "body": "Chego às 8", "id": "n1"})
    await services.whatsapp.handle_agent_event("notification", {"app": "Outlook", "title": "x", "body": "y", "id": "n2"})
    r = await say(services, "leia minhas mensagens do WhatsApp")
    assert "Carla: Chego às 8" in r["text"] and "notificações" in r["text"]
    assert services.db.scalar("SELECT COUNT(*) FROM whatsapp_messages") == 1


# --------------------------------------------------------------------------- Anthropic (SDK simulado)
class _Blk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


async def test_anthropic_provider_request_shape():
    from app.providers.anthropic_provider import AnthropicProvider

    captured = {}

    class FakeMessages:
        async def create(self, **kw):
            captured.update(kw)
            return _Blk(content=[_Blk(type="text", text="Olá!")], stop_reason="end_turn",
                        usage=_Blk(input_tokens=12, output_tokens=3), model="claude-opus-5-5")

    class FakeClient:
        beta = _Blk(messages=FakeMessages())
        messages = FakeMessages()

    p = AnthropicProvider("k", "claude-opus-5-5", "low", client=FakeClient())
    st = p.start("sistema", [], "oi")
    resp = await p.step(st, [{"name": "x", "description": "d", "input_schema": {"type": "object", "properties": {}}}])
    assert resp.text == "Olá!" and resp.input_tokens == 12
    assert captured["model"] == "claude-opus-5-5" and captured["output_config"] == {"effort": "low"}
    assert captured["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in captured["betas"]
    assert "temperature" not in captured and "thinking" not in captured
    # histórico só cresce dentro do turno (append-only)
    assert st.messages[-1]["role"] == "assistant"


async def test_tool_use_executor_via_api(client, services, desktop):
    r = client.post("/api/tools/run", json={"tool": "datetime_now", "args": {}})
    assert r.json()["status"] == "ok"
    r = client.post("/api/tools/run", json={"tool": "inexistente", "args": {}})
    assert r.status_code == 404


async def test_open_target_allowlist(services, desktop):
    from app.core.config import AppEntry, WebsiteEntry

    services.toml.apps.append(AppEntry(name="VS Code", aliases=["vscode", "code"], command="code.exe"))
    services.toml.websites.append(WebsiteEntry(name="GitHub", aliases=["github"], url="https://github.com"))
    r = await say(services, "Jarvis, abra o VS Code")
    assert desktop.launched == [("code.exe", [])] and "Abri VS Code" in r["text"]
    r = await say(services, "abra o github")
    assert desktop.opened == ["https://github.com"]
    r = await say(services, "abra o cmd.exe /c del *")
    assert "não está na lista" in r["text"]
    out = await services.executor.run("open_target", {"target": "javascript:alert(1)"}, ToolContext(services))
    assert out.status == "error"


async def test_openai_compat_canonical_tool_messages():
    """Regressão (achado com llama.cpp real): mensagem do assistente deve ser reenviada no formato canônico."""
    from app.providers.openai_compat import OpenAICompatProvider

    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "function_call": None,
                "tool_calls": [{"id": "call_1", "function": {"name": "task_list", "arguments": "{}"}}]}}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}]})

    p = OpenAICompatProvider("t", "http://x/v1", "m", transport=httpx.MockTransport(handler))
    st = p.start("sys", [], "oi")
    r1 = await p.step(st, [{"type": "function", "function": {"name": "task_list", "parameters": {}}}])
    assert r1.tool_calls[0].name == "task_list"
    p.add_tool_results(st, r1, [("call_1", '{"status":"ok"}', False)])
    r2 = await p.step(st, None)
    assert r2.text == "ok"
    asst = bodies[1]["messages"][2]
    assert asst == {"role": "assistant", "content": "",
                    "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "task_list", "arguments": "{}"}}]}
    assert bodies[1]["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": '{"status":"ok"}'}
