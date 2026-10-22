"""Provedor Claude (Anthropic) via SDK oficial ``anthropic``."""

from __future__ import annotations

import json
from typing import Any

import anthropic

from .base import ChatMessage, LLMResponse, ProviderError, ToolCall, TurnState

# Preço por 1M de tokens (USD), para estimativa de custo local.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}
# Modelos que aceitam o fallback de recusa no servidor ("default").
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


def estimate_cost(model: str, inp: int, out: int) -> float:
    pin, pout = PRICES.get(model, (4.0, 20.0))
    return (inp * pin + out * pout) / 1_000_000


class AnthropicProvider:
    remote = True

    def __init__(self, api_key: str, model: str = "claude-opus-5-5", effort: str | None = "low",
                 timeout: float = 60, max_tokens: int = 16000, client: anthropic.AsyncAnthropic | None = None):
        self.name = "anthropic"
        self.model = model
        self.effort = effort or None
        self.max_tokens = max_tokens
        self.client = client or anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=2)

    async def available(self) -> tuple[bool, str]:
        return True, "chave configurada"

    def tool_format(self) -> str:
        return "anthropic"

    def start(self, system: str, history: list[ChatMessage], user_text: str) -> TurnState:
        msgs: list[dict[str, Any]] = []
        for m in history:
            if m.role not in ("user", "assistant") or not m.content.strip():
                continue
            if msgs and msgs[-1]["role"] == m.role:
                msgs[-1]["content"] += "\n\n" + m.content
            else:
                msgs.append({"role": m.role, "content": m.content})
        if msgs and msgs[0]["role"] == "assistant":
            msgs.pop(0)
        if msgs and msgs[-1]["role"] == "user":
            msgs[-1]["content"] += "\n\n" + user_text
        else:
            msgs.append({"role": "user", "content": user_text})
        return TurnState(system=system, messages=msgs)

    async def step(self, state: TurnState, tools: list[dict[str, Any]] | None) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": state.system,
            "messages": state.messages,
        }
        if tools:
            kwargs["tools"] = tools
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        betas: list[str] = []
        if self.model in _FALLBACK_MODELS:
            betas.append("server-side-fallback-2026-07-01")
            kwargs["fallbacks"] = "default"
        try:
            if betas:
                resp = await self.client.beta.messages.create(betas=betas, **kwargs)
            else:
                resp = await self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise ProviderError("Chave da API Anthropic inválida ou revogada.") from e
        except anthropic.PermissionDeniedError as e:
            raise ProviderError(f"Acesso negado pela API Anthropic: {e.message}") from e
        except anthropic.NotFoundError as e:
            raise ProviderError(f"Modelo '{self.model}' não encontrado na API Anthropic.") from e
        except anthropic.RateLimitError as e:
            raise ProviderError("Limite de uso da API Anthropic atingido; tente mais tarde.", retryable=True) from e
        except anthropic.BadRequestError as e:
            raise ProviderError(f"Requisição rejeitada pela API Anthropic: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Erro da API Anthropic ({e.status_code}).", retryable=e.status_code >= 500) from e
        except anthropic.APITimeoutError as e:
            raise ProviderError("A API Anthropic não respondeu a tempo.", retryable=True) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("Sem conexão com a API Anthropic.", retryable=True) from e

        # Guarda o conteúdo exatamente como veio (inclui blocos de raciocínio).
        state.messages.append({"role": "assistant", "content": resp.content})
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                if isinstance(block.input, str):
                    try:
                        args = json.loads(block.input)
                    except ValueError:
                        args = {}
                calls.append(ToolCall(block.id, block.name, args))
        usage = getattr(resp, "usage", None)
        stop = resp.stop_reason or ""
        return LLMResponse(
            text="".join(text_parts).strip(),
            tool_calls=calls if stop == "tool_use" or calls else [],
            stop_reason=stop,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            model=getattr(resp, "model", self.model) or self.model,
            provider=self.name,
            refusal=stop == "refusal",
        )

    def add_tool_results(self, state: TurnState, response: LLMResponse, results: list[tuple[str, str, bool]]) -> None:
        # Todos os resultados numa única mensagem de usuário.
        state.messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": cid, "content": content, **({"is_error": True} if err else {})}
                for cid, content, err in results
            ],
        })
