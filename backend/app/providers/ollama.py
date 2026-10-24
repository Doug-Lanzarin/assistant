"""Provedor Ollama pela API nativa (``/api/chat``).

Por que não pela rota compatível com OpenAI (``/v1``):

* a ``/v1`` não aceita ``options.num_ctx``. Com o contexto padrão do Ollama
  (2048–4096 tokens), o prompt com ferramentas era cortado sem aviso, e o
  modelo perdia as instruções ou a própria pergunta;
* a nativa aceita ``keep_alive``: o modelo fica carregado na memória entre os
  pedidos. Sem isso, cada pedido após 5 minutos parado recarrega o modelo do
  disco, o que leva dezenas de segundos em CPU.

API documentada em https://github.com/ollama/ollama/blob/main/docs/api.md
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .base import LLMResponse, ProviderError, ToolCall, TurnState
from .openai_compat import OpenAICompatProvider

KEEP_ALIVE = "30m"


class OllamaProvider(OpenAICompatProvider):
    def __init__(self, base_url: str, model: str, timeout: float = 120, num_ctx: int = 8192,
                 transport: httpx.AsyncBaseTransport | None = None):
        base = base_url.rstrip("/")
        super().__init__("ollama", base, model, None, timeout, remote=False, transport=transport,
                         health_url=base + "/api/tags")
        self.num_ctx = num_ctx

    async def warm(self) -> bool:
        """Carrega o modelo na memória (``/api/generate`` sem prompt) para o primeiro pedido não esperar."""
        try:
            async with self._client(timeout=max(self.timeout, 180)) as c:
                r = await c.post(f"{self.base_url}/api/generate", json={"model": self.model, "keep_alive": KEEP_ALIVE})
            return r.status_code < 400
        except httpx.HTTPError:
            return False

    async def step(self, state: TurnState, tools: list[dict[str, Any]] | None) -> LLMResponse:
        body: dict[str, Any] = {"model": self.model, "messages": state.messages, "stream": False,
                                "keep_alive": KEEP_ALIVE, "options": {"num_ctx": self.num_ctx, "temperature": 0.4}}
        if tools:
            body["tools"] = tools
        try:
            async with self._client() as c:
                r = await c.post(f"{self.base_url}/api/chat", json=body)
        except httpx.TimeoutException as e:
            raise ProviderError(f"ollama: tempo esgotado ({self.timeout:.0f} s)", retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"ollama: sem conexão ({type(e).__name__})", retryable=True) from e
        if r.status_code >= 400:
            raise ProviderError(f"ollama: HTTP {r.status_code} {r.text[:200]}", retryable=r.status_code >= 500)
        data = r.json()
        msg = data.get("message") or {}
        calls: list[ToolCall] = []
        canonical: list[dict[str, Any]] = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            raw = fn.get("arguments") or {}
            if isinstance(raw, str):
                try:
                    args = json.loads(raw or "{}")
                except ValueError:
                    args = {"__invalid_json__": raw}
            else:
                args = dict(raw)
            cid = tc.get("id") or f"call_{len(state.messages)}_{i}"
            calls.append(ToolCall(cid, fn.get("name", ""), args))
            canonical.append({"function": {"name": fn.get("name", ""), "arguments": args}})
        assistant: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
        if canonical:
            assistant["tool_calls"] = canonical
        state.messages.append(assistant)
        state.extra["names"] = {c.id: c.name for c in calls}
        return LLMResponse(
            text=(msg.get("content") or "").strip(),
            tool_calls=calls,
            stop_reason=data.get("done_reason") or "",
            input_tokens=data.get("prompt_eval_count", 0) or 0,
            output_tokens=data.get("eval_count", 0) or 0,
            model=data.get("model", self.model),
            provider=self.name,
        )

    def add_tool_results(self, state: TurnState, response: LLMResponse, results: list[tuple[str, str, bool]]) -> None:
        names = state.extra.get("names", {})
        for cid, content, _err in results:
            state.messages.append({"role": "tool", "content": content, "tool_name": names.get(cid, "")})
