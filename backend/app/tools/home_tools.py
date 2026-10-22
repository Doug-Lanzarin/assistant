"""Ferramentas de casa inteligente (Home Assistant, ar-condicionado TCL, Alexa)."""

from __future__ import annotations

from pydantic import Field

from app.integrations.home_assistant.client import HAError
from app.integrations.home_assistant.service import Ambiguity, HomeService
from app.orchestrator.registry import NoParams, Risk, Tool, ToolContext, ToolParams, ToolRegistry, ToolResult

STATE_PT = {"on": "ligado", "off": "desligado", "open": "aberto", "closed": "fechado", "locked": "trancado",
            "unlocked": "destrancado", "unavailable": "indisponível", "unknown": "desconhecido", "cool": "refrigerando",
            "heat": "aquecendo", "dry": "desumidificando", "fan_only": "ventilando", "auto": "automático",
            "heat_cool": "automático", "playing": "tocando", "paused": "pausado", "idle": "ocioso"}


def _pt(state: str | None) -> str:
    return STATE_PT.get(state or "", state or "?")


def _fail(e: Exception) -> ToolResult:
    if isinstance(e, Ambiguity):
        opts = "; ".join(f"{o['name']}" + (f" ({o['room']})" if o.get("room") else "") for o in e.options[:6])
        return ToolResult(ok=False, message=f"Encontrei mais de um dispositivo: {opts}. Qual deles?", data=e.options)
    return ToolResult(ok=False, message=str(e))


async def _list(ctx: ToolContext, a: NoParams) -> ToolResult:
    home = ctx.services.home
    try:
        devs = await home.sync() if home.configured() else home.devices()
    except HAError as e:
        return _fail(e)
    if not devs:
        return ToolResult(ok=False, message="Nenhum dispositivo: configure o Home Assistant em Configurações → Integrações.")
    by_room: dict[str, list[str]] = {}
    for d in devs:
        if d["domain"] in {"sensor", "binary_sensor", "automation"}:
            continue
        by_room.setdefault(d.get("room") or "Sem cômodo", []).append(f"{d['name']} ({_pt(d.get('last_state'))})")
    lines = [f"{room}: " + ", ".join(items) for room, items in sorted(by_room.items())]
    return ToolResult(ok=True, message="Dispositivos:\n" + "\n".join(lines), data=devs, untrusted=True)


class TargetParams(ToolParams):
    target: str = Field(..., min_length=1, max_length=200, description="Dispositivo/cômodo, ex.: 'luzes da sala'")


async def _state(ctx: ToolContext, a: TargetParams) -> ToolResult:
    try:
        res = await ctx.services.home.read(a.target)
    except (HAError, Ambiguity) as e:
        return _fail(e)
    lines = []
    for d in res["devices"]:
        attrs = d["attributes"]
        extra = ""
        if d["entity_id"].startswith("climate."):
            extra = f", alvo {attrs.get('temperature')} °C, ambiente {attrs.get('current_temperature')} °C"
        lines.append(f"{d['name']}: {_pt(d['state'])}{extra}")
    return ToolResult(ok=True, message="\n".join(lines), data=res, untrusted=True)


class SensorParams(ToolParams):
    target: str = Field("", max_length=200)
    measure: str = Field("temperatura", pattern=r"^(temperatura|umidade)$")


async def _sensor(ctx: ToolContext, a: SensorParams) -> ToolResult:
    try:
        r = await ctx.services.home.measure(a.target, a.measure)
    except HAError as e:
        return _fail(e)
    return ToolResult(ok=True, message=f"A {a.measure} em {r['name']} é {r['value']}{r['unit']}.", data=r, untrusted=True)


class TurnParams(TargetParams):
    on: bool = Field(..., description="true para ligar, false para desligar")


async def _turn_risk(ctx: ToolContext, a: TurnParams) -> Risk:
    try:
        devs = await ctx.services.home.resolve(a.target)
    except (HAError, Ambiguity):
        return Risk.REVERSIBLE  # o handler reportará o erro
    return Risk.CRITICAL if any(HomeService.is_sensitive(d) for d in devs) else Risk.REVERSIBLE


async def _turn(ctx: ToolContext, a: TurnParams) -> ToolResult:
    try:
        res = await ctx.services.home.turn(a.target, a.on)
    except (HAError, Ambiguity) as e:
        return _fail(e)
    verb = "Liguei" if a.on else "Desliguei"
    ok_items = [r for r in res["results"] if r["verified"]]
    bad = [r for r in res["results"] if not r["verified"]]
    parts = []
    if ok_items:
        parts.append(f"{verb} " + ", ".join(r["name"] for r in ok_items) + " (estado confirmado).")
    if bad:
        parts.append("Comando enviado, mas o estado NÃO mudou como esperado em: " +
                     ", ".join(f"{r['name']} ({_pt(r['state'])})" for r in bad) + ".")
    return ToolResult(ok=not bad, message=" ".join(parts), data=res)


class ClimateParams(ToolParams):
    target: str = Field("ar condicionado", max_length=200)
    temperature: float = Field(..., ge=10, le=35)
    hvac_mode: str | None = Field(None, pattern=r"^(cool|heat|auto|dry|fan_only|heat_cool|off)$")


async def _climate(ctx: ToolContext, a: ClimateParams) -> ToolResult:
    try:
        r = await ctx.services.home.set_temperature(a.target, a.temperature, a.hvac_mode)
    except (HAError, Ambiguity) as e:
        return _fail(e)
    if r["verified"]:
        return ToolResult(ok=True, message=f"{r['name']} ajustado para {a.temperature:g} °C (confirmado; modo {_pt(r['state'])}).", data=r)
    return ToolResult(ok=False, message=f"Enviei o ajuste para {r['name']}, mas o aparelho ainda informa alvo {r.get('target')} °C.", data=r)


class SceneParams(ToolParams):
    name: str = Field(..., min_length=1, max_length=200)


async def _scene(ctx: ToolContext, a: SceneParams) -> ToolResult:
    try:
        r = await ctx.services.home.run_scene(a.name)
    except (HAError, Ambiguity) as e:
        return _fail(e)
    kind = {"scene": "cena", "script": "script", "automation": "automação"}[r["domain"]]
    return ToolResult(ok=True, message=f"Executei a {kind} '{r['name']}' no Home Assistant.", data=r)


class AnnounceParams(ToolParams):
    message: str = Field(..., min_length=1, max_length=300)


async def _announce(ctx: ToolContext, a: AnnounceParams) -> ToolResult:
    cfg = ctx.services.settings.get("alexa")
    if not cfg.get("enabled") or not cfg.get("notify_service"):
        return ToolResult(ok=False, message="Anúncios na Alexa não configurados (Configurações → Alexa: serviço notify.*).")
    try:
        await ctx.services.home.notify(cfg["notify_service"], a.message, {"type": "announce"})
    except HAError as e:
        return _fail(e)
    return ToolResult(ok=True, message="Anúncio enviado para a Alexa pelo Home Assistant (a reprodução não pode ser confirmada pela API).")


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("home_list", "Lista dispositivos da casa e seus estados (Home Assistant)", NoParams, _list,
                      Risk.READ, "home.read", "casa", timeout=20))
    reg.register(Tool("home_state", "Consulta o estado de um dispositivo", TargetParams, _state, Risk.READ, "home.read", "casa"))
    reg.register(Tool("home_sensor", "Lê temperatura ou umidade de um cômodo", SensorParams, _sensor, Risk.READ, "home.read", "casa"))
    reg.register(Tool("home_turn", "Liga ou desliga dispositivos (luzes, tomadas, ar, TV...). Fechaduras/portões exigem confirmação",
                      TurnParams, _turn, Risk.REVERSIBLE, "home.control", "casa", timeout=25, risk_fn=_turn_risk,
                      summarize=lambda a: f"{'Ligar/abrir' if a.on else 'Desligar/fechar'} {a.target}"))
    reg.register(Tool("climate_set", "Ajusta a temperatura do ar-condicionado (inclui o TCL integrado ao Home Assistant)",
                      ClimateParams, _climate, Risk.REVERSIBLE, "home.control", "casa", timeout=25))
    reg.register(Tool("home_scene", "Executa uma cena, script ou automação do Home Assistant", SceneParams, _scene,
                      Risk.REVERSIBLE, "home.control", "casa", timeout=20))
    reg.register(Tool("alexa_announce", "Faz um anúncio falado nos dispositivos Alexa via Home Assistant",
                      AnnounceParams, _announce, Risk.EXTERNAL, "home.alexa", "casa",
                      summarize=lambda a: f"Anunciar na Alexa: “{a.message}”"))
