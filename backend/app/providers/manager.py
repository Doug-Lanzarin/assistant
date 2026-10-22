"""Seleção de provedores, limites de uso e métricas (sem conteúdo sensível)."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.db import Database, utcnow
from app.providers.anthropic_provider import AnthropicProvider, estimate_cost
from app.providers.base import LLMProvider, LLMResponse, ProviderError, TurnState
from app.providers.embeddings import HashEmbedder, OllamaEmbedder
from app.providers.openai_compat import OpenAICompatProvider

log = logging.getLogger("jarvis.ai")


class ProviderManager:
    def __init__(self, db: Database, settings_store, secrets, env_settings=None):
        self.db = db
        self.settings = settings_store
        self.secrets = secrets
        self.env = env_settings
        self._override: list[LLMProvider] | None = None  # testes
        self._avail_cache: dict[str, tuple[float, bool]] = {}

    def set_override(self, providers: list[LLMProvider] | None) -> None:
        self._override = providers

    def _secret(self, name: str) -> str | None:
        val = self.secrets.get(name) if self.secrets else None
        if not val and self.env is not None:
            val = getattr(self.env, name, None)
        return val or None

    def build_remote(self, cfg: dict) -> LLMProvider | None:
        if cfg["remote_provider"] == "anthropic":
            key = self._secret("anthropic_api_key")
            if not key:
                return None
            return AnthropicProvider(key, cfg["remote_model"], cfg.get("remote_effort"), cfg["timeout_s"])
        if cfg["remote_provider"] == "openai_compat":
            key = self._secret("openai_api_key")
            if not (key and cfg.get("openai_model")):
                return None
            return OpenAICompatProvider("openai_compat", cfg["openai_base_url"], cfg["openai_model"], key,
                                        cfg["timeout_s"], remote=True)
        return None

    def build_local(self, cfg: dict) -> LLMProvider | None:
        if not cfg.get("local_model"):
            return None
        base = cfg["local_url"].rstrip("/")
        return OpenAICompatProvider("ollama", base + "/v1", cfg["local_model"], None, cfg["timeout_s"],
                                    remote=False, health_url=base + "/api/tags")

    def chain(self) -> list[LLMProvider]:
        if self._override is not None:
            return list(self._override)
        cfg = self.settings.get("ai")
        mode = cfg["mode"]
        remote = self.build_remote(cfg)
        local = self.build_local(cfg)
        order: list[LLMProvider | None] = {
            "rules_only": [],
            "local_only": [local],
            "remote_only": [remote],
            "local_first": [local, remote],
            "remote_first": [remote, local],
        }.get(mode, [remote, local])
        return [p for p in order if p is not None]

    async def achain(self) -> list[LLMProvider]:
        """Cadeia de provedores, pulando os locais que não respondem (cache de 30 s)."""
        chain = self.chain()
        if self._override is not None:
            return chain
        out = []
        for p in chain:
            if p.remote:
                out.append(p)
                continue
            key = f"{p.name}:{p.model}"
            ts, ok = self._avail_cache.get(key, (0.0, False))
            if time.monotonic() - ts > 30:
                ok, _ = await p.available()
                self._avail_cache[key] = (time.monotonic(), ok)
            if ok:
                out.append(p)
        return out

    def embedder(self):
        cfg = self.settings.get("ai")
        if cfg["embedding_provider"] == "ollama" and cfg.get("embedding_model"):
            return OllamaEmbedder(cfg["local_url"], cfg["embedding_model"], cfg["timeout_s"])
        return HashEmbedder()

    # -- limites ------------------------------------------------------------------
    def usage_today(self) -> dict[str, Any]:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        month = day[:7]
        row = self.db.query_one(
            "SELECT COALESCE(SUM(input_tokens+output_tokens),0) AS tokens, COUNT(*) AS calls FROM ai_usage"
            " WHERE ts >= ? AND provider != 'ollama'", (day,)
        )
        cost = self.db.scalar("SELECT COALESCE(SUM(est_cost_usd),0) FROM ai_usage WHERE ts >= ?", (month,))
        return {"tokens_today": row["tokens"], "calls_today": row["calls"], "cost_month_usd": round(cost or 0, 4)}

    def check_budget(self, provider: LLMProvider) -> str | None:
        if not provider.remote:
            return None
        cfg = self.settings.get("ai")
        u = self.usage_today()
        if cfg["daily_token_limit"] and u["tokens_today"] >= cfg["daily_token_limit"]:
            return f"limite diário de {cfg['daily_token_limit']} tokens atingido"
        if cfg["monthly_budget_usd"] and u["cost_month_usd"] >= cfg["monthly_budget_usd"]:
            return f"orçamento mensal de US$ {cfg['monthly_budget_usd']:.2f} atingido"
        return None

    def record(self, provider: LLMProvider, resp: LLMResponse | None, ok: bool, latency_ms: int, error: str | None = None) -> None:
        model = (resp.model if resp else None) or provider.model
        inp = resp.input_tokens if resp else 0
        out = resp.output_tokens if resp else 0
        cost = estimate_cost(model, inp, out) if provider.name == "anthropic" else 0.0
        self.db.execute(
            "INSERT INTO ai_usage(ts, provider, model, input_tokens, output_tokens, est_cost_usd, ok, latency_ms, error)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (utcnow(), provider.name, model, inp, out, cost, int(ok), latency_ms, (error or "")[:300] or None),
        )

    async def timed_step(self, provider: LLMProvider, state: TurnState, tools) -> LLMResponse:
        t0 = time.perf_counter()
        try:
            resp = await provider.step(state, tools)
        except ProviderError as e:
            self.record(provider, None, False, int((time.perf_counter() - t0) * 1000), str(e))
            raise
        self.record(provider, resp, True, int((time.perf_counter() - t0) * 1000))
        return resp

    async def status(self) -> list[dict[str, Any]]:
        out = []
        cfg = self.settings.get("ai")
        remote = self.build_remote(cfg)
        local = self.build_local(cfg)
        if remote:
            out.append({"name": remote.name, "model": remote.model, "remote": True, "available": True, "detail": "chave configurada"})
        else:
            out.append({"name": cfg["remote_provider"], "model": cfg["remote_model"] if cfg["remote_provider"] == "anthropic" else cfg["openai_model"],
                        "remote": True, "available": False, "detail": "chave de API não configurada"})
        if local:
            ok, detail = await local.available()
            out.append({"name": "ollama", "model": local.model, "remote": False, "available": ok, "detail": detail})
        return out
