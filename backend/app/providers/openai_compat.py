"""Provedor compatível com a API de chat da OpenAI.

Usado para modelos locais via Ollama (``http://127.0.0.1:11434/v1``), LM Studio,
ou qualquer serviço remoto compatível configurado pelo usuário.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .base import ChatMessage, LLMResponse, ProviderError, ToolCall, TurnState


class OpenAICompatProvider:
    def __init__(self, name: str, base_url: str, model: str, api_key: str | None = None, timeout: float = 60,
                 remote: bool = False, transport: httpx.AsyncBaseTransport | None = None,
                 health_url: str | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.remote = remote
        self._transport = transport
        self.health_url = health_url

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        return httpx.AsyncClient(timeout=timeout or self.timeout, headers=headers, transport=self._transport)

    def tool_format(self) -> str:
        return "openai"

    async def available(self) -> tuple[bool, str]:
        if not self.model:
            return False, "modelo não configurado"
        try:
            async with self._client(timeout=3) as c:
                if self.health_url:  # Ollama: /api/tags lista os modelos baixados
                    r = await c.get(self.health_url)
                    r.raise_for_status()
                    names = {m.get("name", "") for m in r.json().get("models", [])}
                    base_names = {n.split(":")[0] for n in names}
                    if self.model not in names and self.model.split(":")[0] not in base_names:
                        return False, f"modelo '{self.model}' não baixado (ollama pull {self.model})"
                    return True, "ok"
                r = await c.get(f"{self.base_url}/models")
                return r.status_code < 500, f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            return False, f"indisponível ({type(e).__name__})"

    def start(self, system: str, history: list[ChatMessage], user_text: str) -> TurnState:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
        msgs += [{"role": m.role, "content": m.content} for m in history if m.role in ("user", "assistant")]
        msgs.append({"role": "user", "content": user_text})
        return TurnState(system=system, messages=msgs)

    async def step(self, state: TurnState, tools: list[dict[str, Any]] | None) -> LLMResponse:
        body: dict[str, Any] = {"model": self.model, "messages": state.messages, "stream": False}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        try:
            async with self._client() as c:
                r = await c.post(f"{self.base_url}/chat/completions", json=body)
        except httpx.TimeoutException as e:
            raise ProviderError(f"{self.name}: tempo esgotado", retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name}: sem conexão ({type(e).__name__})", retryable=True) from e
        if r.status_code >= 400:
            raise ProviderError(f"{self.name}: HTTP {r.status_code} {r.text[:200]}", retryable=r.status_code >= 500)
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        state.messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")} | {"role": "assistant"})
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except ValueError:
                args = {"__invalid_json__": raw}
            calls.append(ToolCall(tc.get("id") or fn.get("name", "call"), fn.get("name", ""), args))
        usage = data.get("usage") or {}
        return LLMResponse(
            text=(msg.get("content") or "").strip(),
            tool_calls=calls,
            stop_reason=choice.get("finish_reason") or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", self.model),
            provider=self.name,
        )

    def add_tool_results(self, state: TurnState, response: LLMResponse, results: list[tuple[str, str, bool]]) -> None:
        for cid, content, _err in results:
            state.messages.append({"role": "tool", "tool_call_id": cid, "content": content})
