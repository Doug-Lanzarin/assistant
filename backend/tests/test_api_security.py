"""API: autenticação, autorização, entradas malformadas, segredos e backup."""

import asyncio
import io
import json
import socket
import threading
import time
import zipfile

import pytest
import uvicorn
from fastapi.testclient import TestClient

PROTECTED = [
    ("GET", "/api/status"), ("POST", "/api/chat"), ("GET", "/api/brain/memories"), ("GET", "/api/clipboard"),
    ("GET", "/api/settings"), ("GET", "/api/secrets"), ("POST", "/api/backup"), ("GET", "/api/home/devices"),
    ("GET", "/api/whatsapp/messages"), ("POST", "/api/tools/run"), ("GET", "/api/audit"), ("POST", "/api/emergency/stop"),
]


def test_unauthenticated_requests_rejected(app):
    with TestClient(app) as c:
        for method, path in PROTECTED:
            r = c.request(method, path, json={})
            assert r.status_code == 401, (method, path, r.status_code)
        assert c.get("/api/health").status_code == 200
        r = c.get("/api/status", headers={"Authorization": "Bearer token-falso"})
        assert r.status_code == 401


def test_setup_only_once_and_login(app):
    with TestClient(app) as c:
        assert c.post("/api/auth/setup", json={"username": "a", "password": "curta"}).status_code == 400
        assert c.post("/api/auth/setup", json={"username": "a", "password": "senha-boa-123"}).status_code == 200
        assert c.post("/api/auth/setup", json={"username": "b", "password": "senha-boa-123"}).status_code == 409
        assert c.post("/api/auth/login", json={"username": "a", "password": "errada"}).status_code == 401
        r = c.post("/api/auth/login", json={"username": "a", "password": "senha-boa-123"})
        assert r.status_code == 200
        tok = r.json()["token"]
        assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()["username"] == "a"
        c.post("/api/auth/logout", headers={"Authorization": f"Bearer {tok}"})
        assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_login_rate_limited(app):
    from app.api.deps import login_limiter

    login_limiter.events.clear()
    with TestClient(app) as c:
        codes = [c.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code for _ in range(12)]
        assert 429 in codes
    login_limiter.events.clear()


def test_password_hash_not_plaintext(client, services):
    row = services.db.query_one("SELECT password_hash FROM users")
    assert row["password_hash"].startswith("scrypt$") and "senha-forte-123" not in row["password_hash"]
    tok = client.headers["Authorization"].split()[1]
    assert services.db.scalar("SELECT COUNT(*) FROM sessions WHERE token_hash=?", (tok,)) == 0


def test_secrets_never_returned(client, services):
    r = client.put("/api/secrets/anthropic_api_key", json={"value": "sk-ant-api03-SEGREDO-123456789012345"})
    assert r.status_code == 200
    body = client.get("/api/secrets").text
    assert "SEGREDO" not in body
    assert "SEGREDO" not in client.get("/api/settings").text
    raw = (services.env.secrets_dir / "secrets.enc").read_text()
    assert "SEGREDO" not in raw
    assert client.put("/api/secrets/agent_token", json={"value": "x"}).status_code == 400
    assert client.put("/api/secrets/qualquer", json={"value": "x"}).status_code == 400


def test_logs_redact_secrets():
    from app.core.logging import redact

    assert "abcdefghij123456" not in redact("chave sk-ant-api03-abcdefghij1234567890")
    assert "xyz" not in redact("Authorization: Bearer xyzxyzxyzxyzxyz")


def test_malformed_requests(client):
    assert client.post("/api/chat", json={"text": ""}).status_code == 422
    assert client.post("/api/chat", content=b"{nope", headers={"Content-Type": "application/json"}).status_code == 422
    assert client.post("/api/chat", json={"text": "x" * 9000}).status_code == 422
    assert client.patch("/api/settings/policy_inexistente", json={}).status_code == 404
    assert client.patch("/api/settings/ai", json={"chave_nova": 1}).status_code == 400
    assert client.post("/api/clipboard/import", json={"format": "outro"}).status_code == 400


def test_backup_path_traversal(client):
    assert client.get("/api/backup/..%2F..%2Fsecrets%2Fmaster.key").status_code == 404
    assert client.get("/api/backup/../../jarvis.db").status_code == 404


def test_backup_and_restore(client, services):
    client.post("/api/brain/memories", json={"content": "Memória antes do backup", "kind": "note"})
    r = client.post("/api/backup")
    assert r.status_code == 200 and r.json()["manifest"]["counts"]["memories"] == 1
    name = r.json()["name"]
    data = client.get(f"/api/backup/{name}").content
    client.post("/api/brain/memories", json={"content": "Memória depois do backup", "kind": "note"})
    assert len(client.get("/api/brain/memories").json()) == 2
    r = client.post("/api/backup/restore", files={"file": ("b.zip", data, "application/zip")})
    assert r.status_code == 200, r.text
    mems = client.get("/api/brain/memories").json()
    assert [m["content"] for m in mems] == ["Memória antes do backup"]
    # busca continua funcionando após restaurar
    assert client.get("/api/brain/search", params={"q": "backup"}).json()
    # login continua válido (sessões fazem parte do banco restaurado? o usuário sim)
    assert client.get("/api/auth/me").status_code in (200, 401)


def test_restore_rejects_bad_zip(client):
    assert client.post("/api/backup/restore", files={"file": ("x.zip", b"nao e zip", "application/zip")}).status_code == 400
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "jarvis"}))
        z.writestr("jarvis.db", b"lixo")
        z.writestr("../../evil.txt", b"x")
    r = client.post("/api/backup/restore", files={"file": ("x.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 400


def test_cors_blocks_foreign_origin(client):
    r = client.options("/api/status", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") is None
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and "default-src 'self'" in r.headers["content-security-policy"]


def test_ws_requires_auth(app):
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app) as c, pytest.raises(WebSocketDisconnect), c.websocket_connect("/api/ws?token=bad") as ws:
        ws.receive_json()
    with TestClient(app) as c, pytest.raises(WebSocketDisconnect), c.websocket_connect(
            "/api/agent/ws", headers={"X-Jarvis-Agent-Token": "errado"}) as ws:
        ws.receive_text()


def test_chat_endpoint_and_events(client):
    r = client.post("/api/chat", json={"text": "que horas são?"})
    assert r.status_code == 200 and "Agora é" in r.json()["text"]
    cid = r.json()["conversation_id"]
    msgs = client.get(f"/api/conversations/{cid}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    tok = client.headers["Authorization"].split()[1]
    with client.websocket_connect(f"/api/ws?token={tok}") as ws:
        assert ws.receive_json()["type"] == "hello"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_agent_over_websocket(app, services):
    """Sobe o backend de verdade (uvicorn) e conecta o agente REAL (jarvis_agent.Agent) via WebSocket."""
    from jarvis_agent.__main__ import Agent
    from jarvis_agent.clipboard import MemoryClipboard
    from jarvis_agent.rpc import Dispatcher

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    token = services.secrets.get("agent_token")
    assert (services.env.secrets_dir / "agent.token").read_text() == token
    clip = MemoryClipboard()
    clip.set_text("kubectl get pods -A")
    agent = Agent(f"ws://127.0.0.1:{port}/api/agent/ws", token, Dispatcher(clipboard=clip))
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=lambda: loop.run_until_complete(agent.run()), daemon=True)
    t.start()
    try:
        for _ in range(100):
            if services.agent.connected:
                break
            time.sleep(0.05)
        assert services.agent.connected and services.agent.info["clipboard_backend"] == "memory"
        import httpx

        base = f"http://127.0.0.1:{port}"
        tok = httpx.post(f"{base}/api/auth/setup", json={"username": "u", "password": "senha-boa-123"}).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        r = httpx.post(f"http://127.0.0.1:{port}/api/chat", json={"text": "salve o que copiei como listar pods"},
                       headers=h, timeout=10)
        assert "Salvei" in r.json()["text"] or "já estava salvo" in r.json()["text"], r.json()
        clip.set_text("outra")
        r = httpx.post(f"http://127.0.0.1:{port}/api/chat", json={"text": "copie listar pods"}, headers=h, timeout=10)
        assert "Copiei" in r.json()["text"], r.json()
        assert clip.read()["text"] == "kubectl get pods -A"
    finally:
        loop.call_soon_threadsafe(agent.stop_event.set)
        t.join(timeout=5)
        server.should_exit = True
        th.join(timeout=5)
