"""Contratos dos provedores de IA (independentes de fornecedor)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(RuntimeError):
    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


@dataclass
class ChatMessage:
    role: str  # user | assistant
    content: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""
    refusal: bool = False


@dataclass
class TurnState:
    """Estado de um turno com ferramentas, no formato nativo do provedor.

    A lista de mensagens só cresce durante o turno (append-only), mantendo
    válidos os blocos de raciocínio que o provedor devolve.
    """

    system: str
    messages: list[Any] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)  # dados auxiliares do provedor (ex.: id → nome da ferramenta)


class LLMProvider(Protocol):
    name: str
    model: str
    remote: bool

    async def available(self) -> tuple[bool, str]: ...

    def start(self, system: str, history: list[ChatMessage], user_text: str) -> TurnState: ...

    async def step(self, state: TurnState, tools: list[dict[str, Any]] | None) -> LLMResponse: ...

    def add_tool_results(self, state: TurnState, response: LLMResponse, results: list[tuple[str, str, bool]]) -> None: ...

    def tool_format(self) -> str: ...  # "anthropic" | "openai"
