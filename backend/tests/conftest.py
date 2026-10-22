from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import JarvisToml, Settings
from app.main import create_app
from app.providers.base import ChatMessage, LLMResponse, ProviderError, ToolCall, TurnState
from app.services.container import build_services
from jarvis_agent.clipboard import MemoryClipboard
from jarvis_agent.rpc import Dispatcher


@pytest.fixture
def env(tmp_path: Path) -> Settings:
    cfg = tmp_path / "jarvis.toml"
    cfg.write_text("", "utf-8")
    return Settings(env="test", data_dir=tmp_path / "data", config_file=cfg, frontend_dist=tmp_path / "nodist",
                    anthropic_api_key=None, openai_api_key=None, ha_url=None, ha_token=None)


class FakeDesktop:
    """Agente em processo usando o despachante REAL com clipboard em memória."""

    def __init__(self):
        self.clipboard = MemoryClipboard()
        self.launched: list[tuple[str, list[str]]] = []
        self.opened: list[str] = []
        self.d = Dispatcher(clipboard=self.clipboard)
        self.d.methods["apps.launch"] = self._launch
        self.d.methods["open.url"] = self._open
        self.d.methods["open.path"] = self._open_path
        self.d.methods["notify"] = lambda p: {"ok": True}

    def _launch(self, p):
        self.launched.append((p["command"], p.get("args", [])))
        return {"ok": True, "pid": 4242}

    def _open(self, p):
        self.opened.append(p["url"])
        return {"ok": True}

    def _open_path(self, p):
        self.opened.append(p["path"])
        return {"ok": True}

    async def __call__(self, method: str, params: dict) -> Any:
        return await self.d.dispatch(method, params)


@pytest.fixture
def services(env):
    s = build_services(env)
    yield s
    s.db.close()


@pytest.fixture
def desktop(services) -> FakeDesktop:
    fd = FakeDesktop()
    services.agent.attach_local(fd, {"platform": "test", "capabilities": ["clipboard", "apps", "notify"]})
    return fd


@pytest.fixture
def app(env, services):
    return create_app(env, services)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        r = c.post("/api/auth/setup", json={"username": "doug", "password": "senha-forte-123"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


class ScriptedProvider:
    """Provedor de IA simulado: devolve respostas roteirizadas (formato Anthropic)."""

    remote = True

    def __init__(self, script: list[Any], name: str = "fake"):
        self.name = name
        self.model = "fake-model"
        self.script = list(script)
        self.calls: list[list[Any]] = []

    async def available(self):
        return True, "ok"

    def tool_format(self):
        return "anthropic"

    def start(self, system: str, history: list[ChatMessage], user_text: str) -> TurnState:
        msgs = [{"role": m.role, "content": m.content} for m in history] + [{"role": "user", "content": user_text}]
        return TurnState(system=system, messages=msgs)

    async def step(self, state: TurnState, tools) -> LLMResponse:
        self.calls.append(json.loads(json.dumps(state.messages, default=str)))
        if not self.script:
            return LLMResponse("fim", [], "end_turn", 1, 1, self.model, self.name)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            state.messages.append({"role": "assistant", "content": item})
            return LLMResponse(item, [], "end_turn", 10, 5, self.model, self.name)
        name, args = item
        state.messages.append({"role": "assistant", "content": f"tool:{name}"})
        return LLMResponse("", [ToolCall(f"c{len(self.calls)}", name, args)], "tool_use", 10, 5, self.model, self.name)

    def add_tool_results(self, state, response, results):
        state.messages.append({"role": "user", "content": [{"tool_result": r[1], "id": r[0]} for r in results]})


@pytest.fixture
def scripted():
    return ScriptedProvider


__all__ = ["ProviderError", "ScriptedProvider", "FakeDesktop", "JarvisToml", "httpx"]
