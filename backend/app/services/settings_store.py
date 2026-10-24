"""Preferências de runtime persistidas no SQLite, com valores padrão."""

from __future__ import annotations

import copy
from typing import Any

from app.core.db import Database, from_json, to_json, utcnow

DEFAULTS: dict[str, dict[str, Any]] = {
    "assistant": {
        "name": "JARVIS",
        "user_name": "",
        "personality": "objetivo, cordial e técnico; responde em português brasileiro",
        "verbosity": "concisa",
    },
    "ai": {
        # rules_only | local_only | remote_only | local_first | remote_first
        "mode": "remote_first",
        "remote_provider": "anthropic",  # anthropic | openai_compat
        "remote_model": "claude-opus-5-5",
        "remote_effort": "low",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_model": "",
        "local_url": "http://127.0.0.1:11434",
        "local_model": "qwen2.5:3b",
        "local_timeout_s": 120,  # CPU: carregar o modelo do disco + ler o prompt
        "local_num_ctx": 8192,  # contexto do Ollama (o padrão dele, 2048–4096, cortava o prompt com ferramentas)
        "local_max_tools": 8,  # modelos locais recebem só as ferramentas relevantes ao pedido
        "embedding_provider": "hash",  # hash | ollama
        "embedding_model": "nomic-embed-text",
        "timeout_s": 60,
        "turn_deadline_s": 150,  # tempo máximo de um pedido à IA (todas as etapas); depois, resposta honesta
        "daily_token_limit": 300_000,
        "monthly_budget_usd": 10.0,
        "send_memory_to_remote": True,
        "max_tool_iterations": 6,
        "history_messages": 12,
    },
    "voice": {
        "enabled": True,
        "wake_word_enabled": False,
        "wake_word": "jarvis",
        "wake_model": "hey_jarvis",
        "wake_threshold": 0.5,
        # small + beam 5: medido com 24 gravações (frases curtas, com e sem ruído): erro de palavras
        # de 38% (base, beam 1) para ~3%, ~1,7 s por frase em 4 núcleos. "base" é mais rápido e erra mais.
        "stt_model": "small",
        "stt_beam_size": 5,
        "stt_language": "pt",
        # Vocabulário que orienta o Whisper (melhora muito "Jarvis", "ar-condicionado", nomes próprios).
        "stt_prompt": "Jarvis, assistente pessoal. Comandos: Jarvis, salve o clipboard; consulta SQL; ar-condicionado em 23 graus; WhatsApp; VS Code; Home Assistant.",
        "tts_engine": "auto",  # auto (Piper se instalado; senão navegador/SAPI) | piper | browser | sapi
        "tts_voice": "",
        "rate": 1.0,
        "volume": 1.0,
        "input_device": None,
        "output_device": None,
        "speak_responses": True,
    },
    "memory": {
        "auto_consolidate": True,
        "consolidate_interval_min": 60,
        "save_conversations": True,
        "rag_top_k": 6,
        "min_score": 0.0,
    },
    "privacy": {
        "clipboard_sensitive_to_ai": False,
        "store_voice_audio": False,
    },
    "policy": {
        "disabled_permissions": [],
        "confirm_risk_levels": [3, 4],
        "confirm_llm_reversible_when_tainted": True,
        "kill_switch": False,
    },
    "home_assistant": {"url": "", "verify_ssl": True, "timeout_s": 10},
    "alexa": {"enabled": False, "notify_service": ""},
    "tcl": {"climate_entity": "", "model": "", "integration": ""},
    "whatsapp": {
        "mode": "disabled",  # disabled | notifications | web | business
        "phone_number_id": "",
        "api_version": "v23.0",
        "read_aloud_new": False,
    },
}

# Chaves cujos valores não podem ser alterados pela IA nem por importação.
PROTECTED_SECTIONS = {"policy"}


def _diff(base: dict, values: dict) -> dict:
    """Só o que difere do padrão (assim, novos padrões chegam a quem não mudou o valor)."""
    out: dict[str, Any] = {}
    for k, v in values.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            sub = _diff(base[k], v)
            if sub:
                out[k] = sub
        elif k not in base or base[k] != v:
            out[k] = v
    return out


# Migrações de preferências salvas (executadas uma única vez, em ordem).
def _m1_stt_small(stored: dict[str, dict]) -> None:
    # Antes, a seção inteira era gravada; quem nunca escolheu o modelo ficou preso ao antigo padrão "base".
    voice = stored.get("voice")
    if voice and voice.get("stt_model") == "base":
        voice["stt_model"] = "small"


SETTINGS_MIGRATIONS = [_m1_stt_small]


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class SettingsStore:
    def __init__(self, db: Database):
        self.db = db

    def get(self, section: str) -> dict[str, Any]:
        if section not in DEFAULTS:
            raise KeyError(section)
        row = self.db.query_one("SELECT value FROM settings WHERE key=?", (section,))
        stored = from_json(row["value"], {}) if row else {}
        return _deep_merge(DEFAULTS[section], stored)

    def all(self) -> dict[str, dict[str, Any]]:
        return {s: self.get(s) for s in DEFAULTS}

    def update(self, section: str, values: dict[str, Any]) -> dict[str, Any]:
        if section not in DEFAULTS:
            raise KeyError(section)
        unknown = set(values) - set(DEFAULTS[section])
        if unknown:
            raise ValueError(f"Chaves desconhecidas em '{section}': {sorted(unknown)}")
        current = self.get(section)
        merged = _deep_merge(current, values)
        self._write(section, _diff(DEFAULTS[section], merged))
        return merged

    def _write(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, to_json(value), utcnow()),
        )

    def migrate(self) -> int:
        """Aplica as migrações de preferências pendentes; devolve quantas foram aplicadas."""
        row = self.db.query_one("SELECT value FROM settings WHERE key='_settings_version'")
        version = int(from_json(row["value"], 0)) if row else 0
        if version >= len(SETTINGS_MIGRATIONS):
            return 0
        stored = {}
        for r in self.db.query("SELECT key, value FROM settings WHERE key != '_settings_version'"):
            if r["key"] in DEFAULTS:
                stored[r["key"]] = from_json(r["value"], {})
        for m in SETTINGS_MIGRATIONS[version:]:
            m(stored)
        for key, value in stored.items():
            self._write(key, _diff(DEFAULTS[key], value))
        self._write("_settings_version", len(SETTINGS_MIGRATIONS))
        return len(SETTINGS_MIGRATIONS) - version
