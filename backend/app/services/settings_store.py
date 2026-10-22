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
        "embedding_provider": "hash",  # hash | ollama
        "embedding_model": "nomic-embed-text",
        "timeout_s": 60,
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
        "stt_model": "base",
        "stt_language": "pt",
        # Vocabulário que orienta o Whisper (melhora muito "Jarvis", "ar-condicionado", nomes próprios).
        "stt_prompt": "Jarvis, assistente pessoal. Comandos: Jarvis, salve o clipboard; consulta SQL; ar-condicionado em 23 graus; WhatsApp; VS Code; Home Assistant.",
        "tts_engine": "browser",  # browser | sapi | piper
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
        self.db.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (section, to_json(merged), utcnow()),
        )
        return merged
