"""Registro de ferramentas.

Somente ferramentas registradas aqui podem ser executadas. O modelo de IA vê o
esquema JSON das ferramentas, mas a execução sempre passa por validação
Pydantic, política de permissão e (quando exigido) confirmação do usuário.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.services.container import Services


class Risk(IntEnum):
    READ = 1  # leitura informativa
    REVERSIBLE = 2  # alteração reversível
    EXTERNAL = 3  # comunicação externa / ação no mundo físico
    CRITICAL = 4  # sensível ou irreversível

    @property
    def label(self) -> str:
        return {
            1: "leitura informativa",
            2: "alteração reversível",
            3: "comunicação externa",
            4: "ação sensível ou irreversível",
        }[int(self)]


class NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolParams(BaseModel):
    """Base dos parâmetros de ferramentas: campos extras são rejeitados."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PrepareError(Exception):
    def __init__(self, message: str, data: Any = None):
        super().__init__(message)
        self.data = data


class ToolResult(BaseModel):
    ok: bool
    message: str
    data: Any = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    # True quando o resultado contém conteúdo externo não confiável
    # (mensagens recebidas, documentos importados, respostas de APIs).
    untrusted: bool = False


@dataclass
class ToolContext:
    services: Services
    conversation_id: int | None = None
    origin: str = "user"  # user | llm | routine | api | voice
    confirmed: bool = False
    tainted: bool = False  # contexto contém conteúdo externo não confiável
    state: dict[str, Any] = field(default_factory=dict)  # memória de trabalho da conversa


Handler = Callable[[ToolContext, Any], Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    params: type[BaseModel]
    handler: Handler
    risk: Risk
    permission: str
    category: str = "geral"
    timeout: float = 20.0
    # None = segue a política por nível de risco; True = sempre confirmar.
    always_confirm: bool | None = None
    summarize: Callable[[Any], str] | None = None
    expose_to_llm: bool = True
    # Alterações de dados EXISTENTES do usuário pedidas pela IA exigem confirmação
    # (a IA pode acrescentar, mas não reescrever/rebaixar sem você ver).
    confirm_if_llm: bool = False
    # Risco dependente dos argumentos (ex.: fechadura > lâmpada). Nunca reduz o risco base.
    risk_fn: Callable[[ToolContext, Any], Awaitable[Risk]] | None = None
    # Preparação antes da confirmação (ex.: resolver o contato exato a ser mostrado ao usuário).
    # Pode levantar ``PrepareError`` com uma mensagem para o usuário (ambiguidade, não encontrado).
    prepare: Callable[[ToolContext, Any], Awaitable[Any]] | None = None

    def describe_call(self, args: BaseModel) -> str:
        if self.summarize:
            try:
                return self.summarize(args)
            except Exception:  # noqa: BLE001 - resumo é cosmético
                pass
        return f"{self.name}({args.model_dump_json(exclude_none=True)})"

    def json_schema(self) -> dict[str, Any]:
        schema = self.params.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("properties", {})
        schema.setdefault("type", "object")
        return schema


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Ferramenta duplicada: {tool.name}")
        if not tool.name.replace("_", "").isalnum():
            raise ValueError(f"Nome de ferramenta inválido: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda t: (t.category, t.name))

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def anthropic_tools(self, names: set[str] | None = None) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": _llm_description(t), "input_schema": t.json_schema()}
            for t in self.all()
            if t.expose_to_llm and (names is None or t.name in names)
        ]

    def openai_tools(self, names: set[str] | None = None) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": _llm_description(t),
                    "parameters": t.json_schema(),
                },
            }
            for t in self.all()
            if t.expose_to_llm and (names is None or t.name in names)
        ]


def _llm_description(t: Tool) -> str:
    note = ""
    if t.risk >= Risk.EXTERNAL or t.always_confirm:
        note = " O usuário precisará confirmar antes da execução."
    return f"{t.description} (risco: {t.risk.label}).{note}"
