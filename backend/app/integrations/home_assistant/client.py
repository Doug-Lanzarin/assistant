"""Cliente REST do Home Assistant (token de longa duração).

Endpoints usados (API REST oficial):
  GET  /api/                       – verificação
  GET  /api/states                 – estados de todas as entidades
  GET  /api/states/<entity_id>     – estado de uma entidade
  POST /api/services/<dom>/<srv>   – chamada de serviço
  POST /api/template               – renderização de template (áreas/cômodos)
"""

from __future__ import annotations

from typing import Any

import httpx


class HAError(RuntimeError):
    pass


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10, verify_ssl: bool = True,
                 transport: httpx.AsyncBaseTransport | None = None):
        if not base_url:
            raise HAError("URL do Home Assistant não configurada")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.verify = verify_ssl
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            timeout=self.timeout,
            verify=self.verify,
            transport=self._transport,
        )

    async def _request(self, method: str, path: str, **kw) -> Any:
        try:
            async with self._client() as c:
                r = await c.request(method, path, **kw)
        except httpx.TimeoutException as e:
            raise HAError("O Home Assistant não respondeu a tempo.") from e
        except httpx.HTTPError as e:
            raise HAError(f"Falha de comunicação com o Home Assistant ({type(e).__name__}).") from e
        if r.status_code == 401:
            raise HAError("Token do Home Assistant inválido (HTTP 401).")
        if r.status_code == 404:
            raise HAError(f"Recurso não encontrado no Home Assistant: {path}")
        if r.status_code >= 400:
            raise HAError(f"Home Assistant retornou HTTP {r.status_code}: {r.text[:200]}")
        ctype = r.headers.get("content-type", "")
        return r.json() if "json" in ctype else r.text

    async def ping(self) -> str:
        data = await self._request("GET", "/api/")
        return data.get("message", "ok") if isinstance(data, dict) else str(data)

    async def states(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/api/states")

    async def state(self, entity_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/states/{entity_id}")

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> Any:
        return await self._request("POST", f"/api/services/{domain}/{service}", json=data)

    async def areas(self, entity_ids: list[str]) -> dict[str, str | None]:
        tpl = (
            "{% set ns = namespace(items=[]) %}{% for e in ids %}"
            "{% set ns.items = ns.items + [[e, area_name(e)]] %}{% endfor %}{{ ns.items | tojson }}"
        )
        import json

        try:
            text = await self._request("POST", "/api/template", json={"template": tpl, "variables": {"ids": entity_ids}})
            pairs = json.loads(text) if isinstance(text, str) else text
            return {e: a for e, a in pairs}
        except (HAError, ValueError, TypeError):
            return {}
