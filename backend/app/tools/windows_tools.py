"""Automação controlada do Windows (via agente local) e rotinas registradas.

Não existe ferramenta de "executar comando arbitrário": só aplicativos, sites,
projetos e comandos de desenvolvimento previamente cadastrados em
``config/jarvis.toml`` podem ser abertos/executados.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

from app.integrations.agent_bridge import AgentError, AgentUnavailable
from app.orchestrator.registry import Risk, Tool, ToolContext, ToolParams, ToolRegistry, ToolResult
from app.orchestrator.textnorm import normalize_key
from app.services.files import FileAccessError

_URL = re.compile(r"^https?://[\w.\-]+(:\d+)?(/[\w\-./?%&=+#~:@!$,;]*)?$", re.I)


def _names(entry) -> set[str]:
    return {normalize_key(entry.name), *(normalize_key(a) for a in entry.aliases)}


def resolve_target(ctx: ToolContext, target: str) -> dict:
    toml = ctx.services.toml
    raw = target.strip()
    if _URL.match(raw):
        return {"kind": "url", "url": raw, "label": raw}
    key = normalize_key(raw)
    key = re.sub(r"^(o|a|os|as|meu|minha)\s+", "", key)
    proj_key = re.sub(r"^(projeto|pasta do projeto|repositorio)\s+(de\s+|do\s+|da\s+)?", "", key)
    for p in toml.projects:
        names = _names(p)
        if proj_key in names or key in names or any(n and n in proj_key for n in names if len(n) > 3):
            app = next((x for x in toml.apps if x.name == p.open_with), None)
            return {"kind": "project", "path": p.path, "app": app, "label": p.name}
    for a in toml.apps:
        if key in _names(a):
            return {"kind": "app", "app": a, "label": a.name}
    for w in toml.websites:
        if key in _names(w) or key.removeprefix("site ").removeprefix("o site ") in _names(w):
            return {"kind": "url", "url": w.url, "label": w.name}
    folder_key = re.sub(r"^(a\s+)?pasta\s+(de\s+|do\s+|da\s+)?", "", key)
    if folder_key != key or key in {normalize_key(Path(d).name) for d in toml.allowed_dirs}:
        for d in toml.allowed_dirs:
            if normalize_key(Path(d).name) == folder_key:
                return {"kind": "path", "path": d, "label": d}
    # Correspondência parcial em apps (ex.: "code" → "VS Code")
    partial = [a for a in toml.apps if any(key in n or n in key for n in _names(a) if len(n) > 2)]
    if len(partial) == 1:
        return {"kind": "app", "app": partial[0], "label": partial[0].name}
    known = [a.name for a in toml.apps] + [w.name for w in toml.websites] + [p.name for p in toml.projects]
    raise LookupError(
        f"'{target}' não está na lista de itens autorizados. Conhecidos: {', '.join(known) or 'nenhum'}. "
        "Cadastre novos apps/sites/projetos em config/jarvis.toml."
    )


class OpenParams(ToolParams):
    target: str = Field(..., min_length=1, max_length=300, description="Nome do app, site, projeto, pasta ou URL")


async def _open(ctx: ToolContext, a: OpenParams) -> ToolResult:
    try:
        t = resolve_target(ctx, a.target)
    except LookupError as e:
        return ToolResult(ok=False, message=str(e))
    agent = ctx.services.agent
    try:
        if t["kind"] == "url":
            res = await agent.call("open.url", {"url": t["url"]})
        elif t["kind"] == "app":
            res = await agent.call("apps.launch", {"command": t["app"].command, "args": t["app"].args})
        elif t["kind"] == "project":
            if t["app"]:
                res = await agent.call("apps.launch", {"command": t["app"].command, "args": [*t["app"].args, t["path"]]})
            else:
                res = await agent.call("open.path", {"path": t["path"]})
        else:
            ctx.services.files.check(t["path"])
            res = await agent.call("open.path", {"path": t["path"]})
    except (AgentUnavailable, AgentError, FileAccessError) as e:
        return ToolResult(ok=False, message=str(e))
    if not (isinstance(res, dict) and res.get("ok")):
        return ToolResult(ok=False, message=f"Não consegui abrir {t['label']}: {(res or {}).get('error', 'sem confirmação do agente')}")
    pid = f" (processo {res['pid']})" if res.get("pid") else ""
    return ToolResult(ok=True, message=f"Abri {t['label']}{pid}.", data={"kind": t["kind"], "label": t["label"], **res})


class FileSearchParams(ToolParams):
    query: str = Field(..., min_length=1, max_length=200, description="Parte do nome ou padrão (*.pdf)")
    limit: int = Field(15, ge=1, le=100)


async def _file_search(ctx: ToolContext, a: FileSearchParams) -> ToolResult:
    import asyncio

    try:
        found = await asyncio.to_thread(ctx.services.files.search, a.query, a.limit)
    except FileAccessError as e:
        return ToolResult(ok=False, message=str(e))
    if not found:
        return ToolResult(ok=True, message=f"Nenhum arquivo encontrado para '{a.query}' nas pastas permitidas.", data=[])
    ctx.state["last_files"] = [f["path"] for f in found]
    lines = [f"• {f['path']}" + (" (pasta)" if f["is_dir"] else "") for f in found]
    return ToolResult(ok=True, message=f"Encontrei {len(found)} item(ns):\n" + "\n".join(lines), data=found)


class OpenFileParams(ToolParams):
    path: str = Field(..., min_length=1, max_length=1000)


async def _open_file(ctx: ToolContext, a: OpenFileParams) -> ToolResult:
    try:
        p = ctx.services.files.check(a.path)
        if not p.exists():
            return ToolResult(ok=False, message=f"Arquivo não existe: {p}")
        res = await ctx.services.agent.call("open.path", {"path": str(p)})
    except (FileAccessError, AgentUnavailable, AgentError) as e:
        return ToolResult(ok=False, message=str(e))
    if not (isinstance(res, dict) and res.get("ok")):
        return ToolResult(ok=False, message=f"O agente não confirmou a abertura: {(res or {}).get('error')}")
    return ToolResult(ok=True, message=f"Abri {p.name}.", data={"path": str(p)})


class NotifyParams(ToolParams):
    title: str = Field("JARVIS", max_length=80)
    message: str = Field(..., min_length=1, max_length=500)


async def _notify(ctx: ToolContext, a: NotifyParams) -> ToolResult:
    try:
        res = await ctx.services.agent.call("notify", {"title": a.title, "message": a.message})
    except (AgentUnavailable, AgentError) as e:
        return ToolResult(ok=False, message=str(e))
    return ToolResult(ok=bool(res and res.get("ok")), message="Notificação exibida." if res and res.get("ok") else "Falha na notificação.")


class DevCommandParams(ToolParams):
    name: str = Field(..., min_length=1, max_length=100)


async def _dev_command(ctx: ToolContext, a: DevCommandParams) -> ToolResult:
    key = normalize_key(a.name)
    cmd = next((c for c in ctx.services.toml.dev_commands if key in _names(c)), None)
    if not cmd:
        names = ", ".join(c.name for c in ctx.services.toml.dev_commands) or "nenhum"
        return ToolResult(ok=False, message=f"Comando '{a.name}' não cadastrado. Disponíveis: {names}.")
    try:
        res = await ctx.services.agent.call(
            "process.run", {"executable": cmd.executable, "args": cmd.args, "cwd": cmd.cwd, "timeout": cmd.timeout},
            timeout=cmd.timeout + 10,
        )
    except (AgentUnavailable, AgentError) as e:
        return ToolResult(ok=False, message=str(e))
    code = res.get("returncode")
    out = (res.get("stdout") or "")[-1500:]
    err = (res.get("stderr") or "")[-800:]
    ok = code == 0
    msg = f"'{cmd.name}' terminou com código {code}." + (f"\nSaída:\n{out}" if out else "") + (f"\nErros:\n{err}" if err and not ok else "")
    return ToolResult(ok=ok, message=msg, data=res, untrusted=True)


class RoutineParams(ToolParams):
    name: str = Field(..., min_length=1, max_length=120)


def find_routine(ctx: ToolContext, name: str):
    key = normalize_key(name)
    for r in ctx.services.toml.routines:
        names = _names(r)
        if key in names or any(n and (n in key or key in n) for n in names if len(n) > 3):
            return r
    return None


async def _routine(ctx: ToolContext, a: RoutineParams) -> ToolResult:
    from app.orchestrator.registry import ToolContext as TC

    r = find_routine(ctx, a.name)
    if not r:
        names = ", ".join(x.name for x in ctx.services.toml.routines) or "nenhuma"
        return ToolResult(ok=False, message=f"Rotina '{a.name}' não encontrada. Rotinas cadastradas: {names}.")
    lines, all_ok = [], True
    for step in r.steps:
        if step.tool == "routine_run":
            lines.append("• (rotina aninhada ignorada)")
            continue
        sub = TC(ctx.services, ctx.conversation_id, "routine", confirmed=False, tainted=False, state=ctx.state)
        out = await ctx.services.executor.run(step.tool, step.args, sub)
        icon = {"ok": "✔", "needs_confirmation": "⏸"}.get(out.status, "✖")
        if out.status != "ok":
            all_ok = False
        lines.append(f"{icon} {out.message.splitlines()[0] if out.message else step.tool}"
                     + (" (aguardando sua confirmação)" if out.status == "needs_confirmation" else ""))
    return ToolResult(ok=all_ok, message=f"Rotina '{r.name}':\n" + "\n".join(lines), data={"routine": r.name})


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("open_target", "Abre um aplicativo, site, projeto ou pasta cadastrados (lista de permissões)",
                      OpenParams, _open, Risk.REVERSIBLE, "windows.open", "computador", timeout=20))
    reg.register(Tool("file_search", "Procura arquivos pelo nome nas pastas permitidas", FileSearchParams, _file_search,
                      Risk.READ, "files.read", "computador", timeout=10))
    reg.register(Tool("open_file", "Abre um arquivo ou pasta dentro das pastas permitidas", OpenFileParams, _open_file,
                      Risk.REVERSIBLE, "files.open", "computador"))
    reg.register(Tool("notify", "Mostra uma notificação na área de trabalho", NotifyParams, _notify, Risk.READ,
                      "windows.notify", "computador"))
    reg.register(Tool("dev_command_run", "Executa um comando de desenvolvimento PRÉ-APROVADO em config/jarvis.toml",
                      DevCommandParams, _dev_command, Risk.REVERSIBLE, "windows.dev_command", "computador", timeout=600,
                      summarize=lambda a: f"Executar o comando cadastrado '{a.name}'"))
    reg.register(Tool("routine_run", "Executa uma rotina cadastrada (sequência de ferramentas autorizadas)",
                      RoutineParams, _routine, Risk.REVERSIBLE, "routines.run", "computador", timeout=900))
