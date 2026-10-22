"""Execução controlada de ferramentas.

Pipeline: ferramenta registrada? → argumentos válidos? → política → confirmação
pendente ou execução com timeout → auditoria → evento para a interface.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.core.db import from_json, to_json, utcnow
from app.core.logging import log_event, redact
from app.orchestrator.policy import decide
from app.orchestrator.registry import PrepareError, Risk, ToolContext, ToolResult

if TYPE_CHECKING:
    from app.services.container import Services

log = logging.getLogger("jarvis.executor")

PENDING_TTL = timedelta(minutes=5)


@dataclass
class Outcome:
    status: str  # ok | error | needs_confirmation | denied | invalid | timeout | cancelled | unknown_tool
    tool: str
    message: str
    result: ToolResult | None = None
    pending_id: str | None = None
    risk: int = 0
    args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "tool": self.tool,
            "message": self.message,
            "pending_id": self.pending_id,
            "risk": self.risk,
            "data": self.result.data if self.result else None,
            "sources": self.result.sources if self.result else [],
        }


def _safe_args_for_log(args: dict[str, Any]) -> str:
    text = to_json(args)
    if len(text) > 500:
        text = text[:500] + "…"
    return redact(text)


class ToolExecutor:
    def __init__(self, services: Services):
        self.s = services

    async def run(self, name: str, raw_args: dict[str, Any] | None, ctx: ToolContext) -> Outcome:
        tool = self.s.registry.get(name)
        if tool is not None and ctx.origin == "llm" and not tool.expose_to_llm:
            tool = None  # ferramentas internas não podem ser acionadas pela IA
        if tool is None:
            # O modelo não pode inventar ferramentas.
            self._audit(name, raw_args or {}, 0, ctx, "unknown_tool", "ferramenta inexistente", 0)
            return Outcome("unknown_tool", name, f"A ferramenta '{name}' não existe ou não está registrada.")
        try:
            args = tool.params.model_validate(raw_args or {})
        except ValidationError as e:
            errors = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'args'}: {err['msg']}" for err in e.errors()
            )
            self._audit(name, raw_args or {}, tool.risk, ctx, "invalid", errors, 0)
            return Outcome("invalid", name, f"Argumentos inválidos para {name}: {errors}", risk=tool.risk)

        policy = self.s.settings.get("policy")
        if tool.prepare is not None and not policy.get("kill_switch"):
            try:
                args = await asyncio.wait_for(tool.prepare(ctx, args), timeout=tool.timeout)
            except PrepareError as e:
                self._audit(name, args.model_dump(mode="json"), tool.risk, ctx, "error", str(e), 0)
                return Outcome("error", name, str(e), result=ToolResult(ok=False, message=str(e), data=e.data),
                               risk=tool.risk)
            except Exception as e:  # noqa: BLE001
                log.exception("Falha ao preparar %s", name)
                return Outcome("error", name, f"Não consegui preparar '{name}': {e}", risk=tool.risk)
        if tool.risk_fn is not None:
            try:
                effective = max(tool.risk, await tool.risk_fn(ctx, args))
            except Exception:  # noqa: BLE001 - na dúvida, trata como crítico
                effective = Risk.CRITICAL
            if effective != tool.risk:
                tool = dataclasses.replace(tool, risk=Risk(effective))
        decision = decide(tool, ctx, policy)
        args_dict = args.model_dump(mode="json")
        if not decision.allowed:
            self._audit(name, args_dict, tool.risk, ctx, "denied", decision.reason, 0)
            return Outcome("denied", name, decision.reason, risk=tool.risk, args=args_dict)
        if decision.needs_confirmation:
            summary = tool.describe_call(args)
            pid = self._create_pending(name, args_dict, summary, tool.risk, ctx)
            self._audit(name, args_dict, tool.risk, ctx, "needs_confirmation", summary, 0)
            await self.s.events.publish(
                "confirmation_required",
                {"id": pid, "tool": name, "summary": summary, "risk": int(tool.risk),
                 "conversation_id": ctx.conversation_id},
            )
            return Outcome(
                "needs_confirmation", name, summary, pending_id=pid, risk=tool.risk, args=args_dict
            )
        return await self._execute(tool, args, args_dict, ctx)

    async def _execute(self, tool, args, args_dict, ctx: ToolContext) -> Outcome:
        await self.s.events.publish("tool_started", {"tool": tool.name, "conversation_id": ctx.conversation_id})
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(tool.handler(ctx, args), timeout=tool.timeout)
            status = "ok" if result.ok else "error"
        except TimeoutError:
            result = ToolResult(ok=False, message=f"A operação '{tool.name}' excedeu {tool.timeout:.0f}s.")
            status = "timeout"
        except asyncio.CancelledError:
            ms = int((time.perf_counter() - t0) * 1000)
            self._audit(tool.name, args_dict, tool.risk, ctx, "cancelled", "cancelada", ms)
            await self.s.events.publish("tool_finished", {"tool": tool.name, "status": "cancelled"})
            raise
        except Exception as e:  # noqa: BLE001 - erro reportado ao usuário de forma transparente
            log.exception("Falha na ferramenta %s", tool.name)
            result = ToolResult(ok=False, message=f"Erro ao executar {tool.name}: {e}")
            status = "error"
        ms = int((time.perf_counter() - t0) * 1000)
        self._audit(tool.name, args_dict, tool.risk, ctx, status, result.message, ms)
        await self.s.events.publish(
            "tool_finished",
            {"tool": tool.name, "status": status, "message": result.message[:300],
             "conversation_id": ctx.conversation_id},
        )
        return Outcome(status, tool.name, result.message, result=result, risk=tool.risk, args=args_dict)

    # -- confirmações -----------------------------------------------------------
    def _create_pending(self, name, args, summary, risk, ctx: ToolContext) -> str:
        pid = secrets.token_urlsafe(9)
        now = datetime.now(UTC)
        self.s.db.execute(
            "INSERT INTO pending_actions(id, conversation_id, tool, args, summary, risk, origin,"
            " status, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, ctx.conversation_id, name, to_json(args), summary, int(risk), ctx.origin,
             "pending", now.isoformat(timespec="seconds"),
             (now + PENDING_TTL).isoformat(timespec="seconds")),
        )
        return pid

    def list_pending(self, conversation_id: int | None = None) -> list[dict[str, Any]]:
        self._expire_pending()
        sql = "SELECT id, conversation_id, tool, summary, risk, created_at, expires_at FROM pending_actions WHERE status='pending'"
        params: tuple = ()
        if conversation_id is not None:
            sql += " AND conversation_id=?"
            params = (conversation_id,)
        return self.s.db.query(sql + " ORDER BY created_at DESC", params)

    def _expire_pending(self) -> None:
        self.s.db.execute(
            "UPDATE pending_actions SET status='expired' WHERE status='pending' AND expires_at < ?",
            (utcnow(),),
        )

    async def confirm(self, pending_id: str, approve: bool, state: dict | None = None) -> Outcome:
        self._expire_pending()
        row = self.s.db.query_one("SELECT * FROM pending_actions WHERE id=?", (pending_id,))
        if not row:
            return Outcome("error", "?", "Ação pendente não encontrada.")
        if row["status"] != "pending":
            return Outcome("error", row["tool"], f"Esta ação já está '{row['status']}'.")
        if not approve:
            self.s.db.execute("UPDATE pending_actions SET status='rejected' WHERE id=?", (pending_id,))
            self._audit(row["tool"], from_json(row["args"], {}), row["risk"],
                        ToolContext(self.s, row["conversation_id"], row["origin"]), "rejected", "recusada", 0)
            return Outcome("cancelled", row["tool"], "Ação cancelada. Nada foi executado.", risk=row["risk"])
        # Marca antes de executar: impede dupla execução por cliques repetidos.
        cur = self.s.db.execute(
            "UPDATE pending_actions SET status='approved' WHERE id=? AND status='pending'", (pending_id,)
        )
        if cur.rowcount != 1:
            return Outcome("error", row["tool"], "Esta ação já foi processada.")
        tool = self.s.registry.get(row["tool"])
        if tool is None:
            return Outcome("unknown_tool", row["tool"], "Ferramenta não existe mais.")
        ctx = ToolContext(
            self.s, row["conversation_id"], row["origin"], confirmed=True, state=state if state is not None else {}
        )
        if row["risk"] > tool.risk:
            tool = dataclasses.replace(tool, risk=Risk(row["risk"]))
        decision = decide(tool, ctx, self.s.settings.get("policy"))
        if not decision.allowed:
            return Outcome("denied", tool.name, decision.reason, risk=tool.risk)
        args = tool.params.model_validate(from_json(row["args"], {}))
        outcome = await self._execute(tool, args, args.model_dump(mode="json"), ctx)
        self.s.db.execute(
            "UPDATE pending_actions SET status=?, result=? WHERE id=?",
            ("done" if outcome.status == "ok" else outcome.status, outcome.message[:1000], pending_id),
        )
        return outcome

    def cancel_all_pending(self) -> int:
        cur = self.s.db.execute("UPDATE pending_actions SET status='cancelled' WHERE status='pending'")
        return cur.rowcount

    # -- auditoria -------------------------------------------------------------
    def _audit(self, tool, args, risk, ctx: ToolContext, status, summary, ms) -> None:
        try:
            self.s.db.execute(
                "INSERT INTO audit_log(ts, tool, args, risk, origin, status, result_summary, duration_ms,"
                " conversation_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (utcnow(), tool, _safe_args_for_log(args), int(risk), ctx.origin, status,
                 redact(str(summary))[:500], ms, ctx.conversation_id),
            )
        except Exception:  # noqa: BLE001
            log.exception("Falha ao gravar auditoria")
        log_event(log, "tool", tool=tool, status=status, risk=int(risk), origin=ctx.origin, ms=ms)


__all__ = ["Outcome", "ToolExecutor", "Risk"]
