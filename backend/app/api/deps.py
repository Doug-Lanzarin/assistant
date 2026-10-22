"""Dependências comuns da API: serviços, autenticação e limites."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from app.services.container import Services


def services(request: Request) -> Services:
    return request.app.state.services


def _token_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get("jarvis_session")


def current_user(request: Request, s: Services = Depends(services)) -> dict:
    user = s.auth.validate(_token_from(request))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado", headers={"WWW-Authenticate": "Bearer"})
    return user


def is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


class RateLimiter:
    def __init__(self, max_events: int, window_s: float):
        self.max = max_events
        self.window = window_s
        self.events: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self.events[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Muitas tentativas. Aguarde alguns minutos.")
        q.append(now)


login_limiter = RateLimiter(10, 300)
