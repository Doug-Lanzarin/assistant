from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import current_user, is_local, login_limiter, services
from app.services.container import Services

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8, max_length=256)


@router.get("/status")
def auth_status(s: Services = Depends(services)):
    return {"has_user": s.auth.has_user()}


@router.post("/setup")
def setup(body: Credentials, request: Request, s: Services = Depends(services)):
    if s.auth.has_user():
        raise HTTPException(409, "O usuário já foi configurado.")
    if not (s.env.allow_first_setup and is_local(request)):
        raise HTTPException(403, "O primeiro cadastro só pode ser feito a partir deste computador (localhost).")
    try:
        s.auth.create_user(body.username, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    token = s.auth.login(body.username, body.password, request.headers.get("user-agent"))
    return {"token": token, "username": body.username}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, s: Services = Depends(services)):
    login_limiter.check(request.client.host if request.client else "?")
    token = s.auth.login(body.username, body.password, request.headers.get("user-agent"))
    if not token:
        raise HTTPException(401, "Usuário ou senha incorretos.")
    response.set_cookie("jarvis_session", token, httponly=True, samesite="strict",
                        max_age=s.env.session_ttl_hours * 3600, secure=request.url.scheme == "https")
    return {"token": token, "username": body.username}


@router.post("/logout")
def logout(request: Request, response: Response, s: Services = Depends(services), user=Depends(current_user)):
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.cookies.get("jarvis_session")
    if token:
        s.auth.logout(token)
    response.delete_cookie("jarvis_session")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return user


@router.post("/password")
def change_password(body: PasswordChange, s: Services = Depends(services), user=Depends(current_user)):
    try:
        s.auth.change_password(user["id"], body.old_password, body.new_password)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "detail": "Senha alterada; faça login novamente."}
