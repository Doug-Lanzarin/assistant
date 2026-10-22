"""Sistema: saúde, painel, configurações, segredos, IA, backup e voz."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.api.deps import current_user, services
from app.services import backup as backup_svc
from app.services.container import Services
from app.services.settings_store import DEFAULTS
from app.services.system_info import environment_report, system_status

public = APIRouter(prefix="/api", tags=["sistema"])
router = APIRouter(prefix="/api", tags=["sistema"], dependencies=[Depends(current_user)])

VERSION = "1.0.0"


@public.get("/health")
def health(s: Services = Depends(services)):
    try:
        s.db.scalar("SELECT 1")
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "version": VERSION, "db": db_ok}


@router.get("/status")
async def status(s: Services = Depends(services)):
    sysst = await asyncio.to_thread(system_status, s.env.data_dir)
    ai = await s.providers.status()
    policy = s.settings.get("policy")
    voice = s.settings.get("voice")
    wa = await s.whatsapp.status()
    return {
        "version": VERSION,
        "system": sysst,
        "ai": {"mode": s.settings.get("ai")["mode"], "providers": ai, "usage": s.providers.usage_today()},
        "agent": {"connected": s.agent.connected, "info": s.agent.info},
        "voice": {"enabled": voice["enabled"], "wake_word_enabled": voice["wake_word_enabled"],
                  "wake_word": voice["wake_word"], "agent_voice": s.agent.has_capability("voice")},
        "home": {"configured": s.home.configured(), "devices": len(s.home.devices())},
        "whatsapp": wa,
        "kill_switch": policy["kill_switch"],
        "pending_actions": len(s.executor.list_pending()),
        "tasks_pending": s.db.scalar("SELECT COUNT(*) FROM tasks WHERE status='pending'"),
        "reminders": s.brain.list_reminders("scheduled")[:5],
        "recent_activity": s.db.query("SELECT ts, tool, status, result_summary FROM audit_log ORDER BY id DESC LIMIT 12"),
        "running_tasks": len(s.orchestrator.running),
    }


@router.get("/system/environment")
def env_report():
    return environment_report()


@router.get("/system/logs")
def logs(lines: int = 200, s: Services = Depends(services)):
    from app.core.logging import redact

    path = s.env.logs_dir / "jarvis.log"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return [redact(x.rstrip()) for x in f.readlines()[-min(lines, 2000):]]


@router.post("/system/reload-config")
def reload_config(s: Services = Depends(services)):
    s.reload_toml()
    t = s.toml
    return {"apps": len(t.apps), "websites": len(t.websites), "projects": len(t.projects), "routines": len(t.routines),
            "allowed_dirs": t.allowed_dirs, "dev_commands": len(t.dev_commands), "devices": len(t.devices)}


@router.get("/system/config")
def toml_config(s: Services = Depends(services)):
    return s.toml.model_dump()


# -- configurações --------------------------------------------------------------------------
@router.get("/settings")
def get_settings(s: Services = Depends(services)):
    return s.settings.all()


@router.patch("/settings/{section}")
def patch_settings(section: str, values: dict, s: Services = Depends(services)):
    if section not in DEFAULTS:
        raise HTTPException(404, "Seção desconhecida")
    try:
        updated = s.settings.update(section, values)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if section == "ai" and {"embedding_provider", "embedding_model", "local_url"} & set(values):
        s.refresh_embedder()
    return updated


class SecretIn(BaseModel):
    value: str = Field(..., min_length=1, max_length=4096)


@router.get("/secrets")
def secrets_status(s: Services = Depends(services)):
    return {"backend": s.secrets.backend, "items": s.secrets.status()}


@router.put("/secrets/{name}")
def set_secret(name: str, body: SecretIn, s: Services = Depends(services)):
    if name not in s.secrets.KNOWN or name == "agent_token":
        raise HTTPException(400, "Segredo desconhecido")
    s.secrets.set(name, body.value.strip())
    return {"ok": True}


@router.delete("/secrets/{name}")
def delete_secret(name: str, s: Services = Depends(services)):
    if name == "agent_token":
        raise HTTPException(400, "Use scripts/jarvisctl.py agent-token --rotate")
    s.secrets.delete(name)
    return {"ok": True}


# -- IA ----------------------------------------------------------------------------------------
@router.get("/ai/status")
async def ai_status(s: Services = Depends(services)):
    return {"providers": await s.providers.status(), "usage": s.providers.usage_today(),
            "embedder": s.indexer.embedder.name}


@router.get("/ai/usage")
def ai_usage(days: int = 30, s: Services = Depends(services)):
    return s.db.query(
        "SELECT substr(ts,1,10) AS day, provider, model, SUM(input_tokens) AS input_tokens,"
        " SUM(output_tokens) AS output_tokens, ROUND(SUM(est_cost_usd), 4) AS cost_usd, COUNT(*) AS calls,"
        " SUM(1-ok) AS errors, CAST(AVG(latency_ms) AS INTEGER) AS avg_latency_ms"
        " FROM ai_usage WHERE ts >= date('now', ?) GROUP BY day, provider, model ORDER BY day DESC",
        (f"-{min(days, 365)} days",),
    )


@router.post("/ai/test")
async def ai_test(s: Services = Depends(services)):
    results = []
    for p in s.providers.chain():
        try:
            st = p.start("Responda apenas com a palavra OK.", [], "Teste de conexão")
            resp = await s.providers.timed_step(p, st, None)
            results.append({"provider": p.name, "model": p.model, "ok": True, "reply": resp.text[:80]})
        except Exception as e:  # noqa: BLE001
            results.append({"provider": p.name, "model": p.model, "ok": False, "error": str(e)})
    return results


# -- backup ------------------------------------------------------------------------------------
@router.get("/backup")
def backups(s: Services = Depends(services)):
    return backup_svc.list_backups(s)


@router.post("/backup")
def make_backup(s: Services = Depends(services)):
    path = backup_svc.create_backup(s)
    return {"name": path.name, "size": path.stat().st_size, "manifest": backup_svc.inspect_backup(path)}


@router.get("/backup/{name}")
def download_backup(name: str, s: Services = Depends(services)):
    path = (s.env.backups_dir / Path(name).name).resolve()
    if path.parent != s.env.backups_dir.resolve() or not path.exists():
        raise HTTPException(404, "Backup não encontrado")
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/backup/restore")
async def restore(file: UploadFile = File(...), s: Services = Depends(services)):
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(await file.read())
        tmp = Path(f.name)
    try:
        return backup_svc.restore_backup(s, tmp)
    except backup_svc.BackupError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/data/wipe-conversations")
def wipe_conversations(s: Services = Depends(services)):
    n = s.db.execute("DELETE FROM conversations").rowcount
    s.conversation_state.clear()
    return {"deleted": n}


# -- voz -----------------------------------------------------------------------------------------
@router.get("/voice/status")
async def voice_status(s: Services = Depends(services)):
    from app.voice.engines import PiperTTS, STTEngine

    devices = None
    if s.agent.connected and s.agent.has_capability("voice"):
        try:
            devices = await s.agent.call("voice.devices", {}, timeout=5)
        except Exception as e:  # noqa: BLE001
            devices = {"error": str(e)}
    return {"stt_installed": STTEngine.installed(), "piper_installed": PiperTTS.installed(),
            "piper_voices": s.voice.tts.available_voices() if s.voice else [],
            "agent_voice": s.agent.has_capability("voice"), "devices": devices, "settings": s.settings.get("voice")}


@router.post("/voice/transcribe")
async def transcribe(file: UploadFile = File(...), s: Services = Depends(services)):
    from app.voice.engines import VoiceUnavailable

    cfg = s.settings.get("voice")
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Áudio grande demais")
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    try:
        return await asyncio.to_thread(s.voice.stt.transcribe_bytes, data, suffix, model=cfg["stt_model"],
                                       language=cfg["stt_language"])
    except VoiceUnavailable as e:
        raise HTTPException(501, str(e)) from e


class SpeakIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.post("/voice/tts")
async def tts(body: SpeakIn, s: Services = Depends(services)):
    from app.orchestrator.orchestrator import speakable
    from app.voice.engines import VoiceUnavailable

    cfg = s.settings.get("voice")
    try:
        wav = await asyncio.to_thread(s.voice.tts.synthesize, speakable(body.text), cfg.get("tts_voice") or None, cfg["rate"])
    except VoiceUnavailable as e:
        raise HTTPException(501, str(e)) from e
    return Response(wav, media_type="audio/wav")


@router.post("/voice/agent/{action}")
async def agent_voice(action: str, s: Services = Depends(services)):
    if action not in {"listen", "stop_speaking", "wake_on", "wake_off"}:
        raise HTTPException(400, "Ação inválida")
    if action in {"wake_on", "wake_off"}:
        s.settings.update("voice", {"wake_word_enabled": action == "wake_on"})
    if not s.agent.connected:
        raise HTTPException(503, "Agente local não conectado")
    method = {"listen": "voice.listen_once", "stop_speaking": "voice.stop_speaking",
              "wake_on": "voice.configure", "wake_off": "voice.configure"}[action]
    return await s.agent.call(method, {"settings": s.settings.get("voice")}, timeout=10)
