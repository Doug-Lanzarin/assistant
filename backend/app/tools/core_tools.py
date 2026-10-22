"""Ferramentas básicas: ajuda, data/hora, sistema, emergência, logs."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.core.logging import redact
from app.orchestrator.registry import NoParams, Risk, Tool, ToolContext, ToolParams, ToolRegistry, ToolResult
from app.services.system_info import system_status

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro"]

HELP = """Posso ajudar com:
• Clipboard: "salve o que copiei como consulta SQL de coletas", "copie a consulta SQL de coletas", "liste meus comandos Git salvos"
• Segundo cérebro: "anote a ideia ...", "encontre a ideia de aplicativo que registrei", "o que fiz ontem?", "quais decisões tomei sobre o JARVIS?", "esqueça ..."
• Tarefas: "crie um lembrete para revisar o código amanhã às 9", "quais tarefas estão pendentes?"
• Computador: "abra o VS Code", "mostre o uso de memória", "procure o arquivo relatório", "execute minha rotina de início do trabalho"
• Casa: "ligue o ar-condicionado", "ajuste o ar para 23 graus", "desligue as luzes da sala", "qual a temperatura da sala?"
• WhatsApp: "leia minhas mensagens", "mande uma mensagem para o João dizendo que estou chegando"
• Emergência: "parar tudo" (desativa ações) e "retomar operações\""""


def fmt_dt(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]}, {dt.day} de {MONTHS[dt.month - 1]} de {dt.year}, {dt.hour:02d}:{dt.minute:02d}"


async def _help(ctx: ToolContext, a: NoParams) -> ToolResult:
    return ToolResult(ok=True, message=HELP)


async def _datetime(ctx: ToolContext, a: NoParams) -> ToolResult:
    now = datetime.now().astimezone()
    return ToolResult(ok=True, message=f"Agora é {fmt_dt(now)}.", data={"iso": now.isoformat()})


async def _system(ctx: ToolContext, a: NoParams) -> ToolResult:
    st = system_status(ctx.services.env.data_dir)
    msg = (
        f"CPU em {st['cpu_percent']:.0f}% ({st['cpu_count']} núcleos lógicos). "
        f"Memória: {st['ram_used_percent']:.0f}% usada, {st['ram_available_gb']} GB livres de {st['ram_total_gb']} GB. "
        f"Disco: {st['disk_free_gb']} GB livres ({st['disk_used_percent']:.0f}% usado). "
        f"Internet: {'conectada' if st['internet'] else 'sem conexão'}. "
        f"O JARVIS está usando {st['jarvis_rss_mb']} MB."
    )
    return ToolResult(ok=True, message=msg, data=st)


async def _emergency_stop(ctx: ToolContext, a: NoParams) -> ToolResult:
    s = ctx.services
    s.settings.update("policy", {"kill_switch": True})
    cancelled_pending = s.executor.cancel_all_pending()
    cancelled_tasks = await s.orchestrator.cancel_all(exclude_current=True)
    if s.agent.connected:
        try:
            await s.agent.call("voice.stop_speaking", {}, timeout=2)
        except Exception:  # noqa: BLE001
            pass
    await s.events.publish("kill_switch", {"active": True})
    return ToolResult(
        ok=True,
        message=(
            f"Modo de emergência ativado. Cancelei {cancelled_tasks} tarefa(s) em execução e "
            f"{cancelled_pending} ação(ões) pendente(s). Ferramentas de ação estão desativadas até você dizer "
            "'retomar operações'."
        ),
    )


async def _emergency_resume(ctx: ToolContext, a: NoParams) -> ToolResult:
    if ctx.origin not in {"user", "voice", "api"}:
        return ToolResult(ok=False, message="Somente o usuário pode retomar as operações.")
    ctx.services.settings.update("policy", {"kill_switch": False})
    await ctx.services.events.publish("kill_switch", {"active": False})
    return ToolResult(ok=True, message="Operações retomadas. Ferramentas de ação reativadas.")


class LogsParams(ToolParams):
    lines: int = Field(30, ge=1, le=500)


async def _logs(ctx: ToolContext, a: LogsParams) -> ToolResult:
    path = ctx.services.env.logs_dir / "jarvis.log"
    if not path.exists():
        return ToolResult(ok=True, message="Ainda não há registros de log.", data=[])
    with path.open("r", encoding="utf-8", errors="replace") as f:
        tail = f.readlines()[-a.lines:]
    lines = [redact(line.rstrip()) for line in tail]
    errors = sum(1 for ln in lines if '"level": "ERROR"' in ln)
    return ToolResult(ok=True, message=f"Últimas {len(lines)} linhas do log ({errors} erro(s)).", data=lines)


async def _restart(ctx: ToolContext, a: NoParams) -> ToolResult:
    bg = ctx.services.background
    if bg is None:
        return ToolResult(ok=False, message="Reinício controlado indisponível neste modo de execução.")
    bg.request_restart()
    return ToolResult(ok=True, message="Reiniciando o serviço do JARVIS em instantes. Volto em alguns segundos.")


async def _last_sources(ctx: ToolContext, a: NoParams) -> ToolResult:
    sources = ctx.state.get("last_sources") or []
    if not sources:
        return ToolResult(ok=True, message="A última resposta não usou fontes da memória.", data=[])
    lines = [f"• {s.get('citation') or s.get('title')}" for s in sources]
    return ToolResult(ok=True, message="A informação veio de:\n" + "\n".join(lines), data=sources, sources=sources)


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("help", "Lista o que o JARVIS sabe fazer", NoParams, _help, Risk.READ, "core.read", "sistema"))
    reg.register(Tool("datetime_now", "Informa a data e a hora atuais", NoParams, _datetime, Risk.READ, "core.read", "sistema"))
    reg.register(Tool("system_status", "Consulta CPU, memória RAM, disco e conectividade do computador",
                      NoParams, _system, Risk.READ, "system.read", "sistema", timeout=10))
    reg.register(Tool("emergency_stop", "Interrompe tarefas em execução e desativa ferramentas de ação (modo de emergência)",
                      NoParams, _emergency_stop, Risk.READ, "core.emergency", "sistema"))
    reg.register(Tool("emergency_resume", "Desativa o modo de emergência (somente por pedido direto do usuário)",
                      NoParams, _emergency_resume, Risk.READ, "core.emergency", "sistema", expose_to_llm=False))
    reg.register(Tool("logs_tail", "Mostra as últimas linhas do log do JARVIS", LogsParams, _logs, Risk.READ, "core.logs", "sistema"))
    reg.register(Tool("service_restart", "Reinicia o serviço do JARVIS de forma controlada", NoParams, _restart,
                      Risk.CRITICAL, "core.restart", "sistema", summarize=lambda a: "Reiniciar o serviço do JARVIS"))
    reg.register(Tool("last_sources", "Mostra de onde veio a informação da última resposta", NoParams, _last_sources,
                      Risk.READ, "core.read", "memória"))
