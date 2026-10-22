"""Política de permissões e confirmação.

Regras fixas (não configuráveis):
* Nível 4 (crítico) sempre exige confirmação.
* Com o interruptor de emergência ligado, só ferramentas de leitura rodam.
* Uma chamada vinda da IA com contexto "contaminado" por conteúdo externo
  exige confirmação a partir do nível 2 (configurável apenas para endurecer).
* Memória e conteúdo importado nunca concedem permissões.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.orchestrator.registry import Risk, Tool, ToolContext


@dataclass
class Decision:
    allowed: bool
    needs_confirmation: bool
    reason: str = ""


def decide(tool: Tool, ctx: ToolContext, policy: dict) -> Decision:
    if policy.get("kill_switch") and tool.risk > Risk.READ:
        return Decision(
            False, False,
            "Modo de emergência ativo: ferramentas de ação estão desativadas. "
            "Desative-o nas configurações ou diga 'Jarvis, retomar operações'.",
        )
    if tool.permission in set(policy.get("disabled_permissions", [])):
        return Decision(False, False, f"Permissão '{tool.permission}' está desativada.")

    if ctx.confirmed:
        return Decision(True, False)

    levels = {int(x) for x in policy.get("confirm_risk_levels", [3, 4])}
    levels.add(int(Risk.CRITICAL))
    needs = tool.always_confirm is True or int(tool.risk) in levels
    if (
        not needs
        and ctx.origin == "llm"
        and ctx.tainted
        and tool.risk >= Risk.REVERSIBLE
        and policy.get("confirm_llm_reversible_when_tainted", True)
    ):
        needs = True
    return Decision(True, needs, "confirmação necessária" if needs else "")
