"""Configuração do JARVIS.

Três camadas, em ordem de precedência:
1. Variáveis de ambiente / arquivo ``.env`` (infraestrutura: portas, diretórios, chaves).
2. ``config/jarvis.toml`` (listas de permissões: apps, pastas, rotinas, aliases de dispositivos).
3. Preferências de runtime salvas no banco (tabela ``settings``), editáveis pela interface.

Segredos (tokens de API) nunca ficam no TOML: vão para o ``SecretStore``.
"""

from __future__ import annotations

import os
import sys
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class AppEntry(BaseModel):
    """Aplicativo que o JARVIS pode abrir."""

    name: str
    aliases: list[str] = Field(default_factory=list)
    command: str  # executável ou caminho; nunca uma linha de shell
    args: list[str] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    path: str
    open_with: str | None = None  # nome de um AppEntry


class RoutineStep(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class RoutineEntry(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    steps: list[RoutineStep]


class DevCommand(BaseModel):
    """Comando de desenvolvimento pré-aprovado (sem shell, argumentos fixos)."""

    name: str
    aliases: list[str] = Field(default_factory=list)
    executable: str
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    timeout: float = 120


class DeviceAlias(BaseModel):
    entity_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    room: str | None = None


class WebsiteEntry(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    url: str


class JarvisToml(BaseModel):
    apps: list[AppEntry] = Field(default_factory=list)
    websites: list[WebsiteEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    allowed_dirs: list[str] = Field(default_factory=list)
    routines: list[RoutineEntry] = Field(default_factory=list)
    dev_commands: list[DevCommand] = Field(default_factory=list)
    devices: list[DeviceAlias] = Field(default_factory=list)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"  # development | production | test
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = REPO_ROOT / "data"
    config_file: Path = REPO_ROOT / "config" / "jarvis.toml"
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"
    log_level: str = "INFO"
    # Logs também no terminal (padrão: só em desenvolvimento). O start.bat liga.
    log_console: bool | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )
    session_ttl_hours: int = 24 * 7
    # Quando true, permite primeiro cadastro de senha sem token de instalação (só localhost).
    allow_first_setup: bool = True

    # Chaves opcionais via ambiente (alternativa ao SecretStore).
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    ha_url: str | None = None
    ha_token: str | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jarvis.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def library_dir(self) -> Path:
        return self.data_dir / "library"

    @property
    def is_windows(self) -> bool:
        return sys.platform == "win32"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.logs_dir, self.secrets_dir, self.backups_dir, self.library_dir):
            d.mkdir(parents=True, exist_ok=True)
        if not self.is_windows:
            os.chmod(self.secrets_dir, 0o700)


def load_toml(path: Path) -> JarvisToml:
    if not path.exists():
        example = path.with_name("jarvis.example.toml")
        if example.exists():
            path = example
        else:
            return JarvisToml()
    with path.open("rb") as f:
        raw = tomllib.load(f)
    data = _expand_env(raw)
    return JarvisToml.model_validate(data)


def _expand_env(value: Any) -> Any:
    """Expande %VAR% / $VAR / ~ em strings do TOML (ex.: %USERPROFILE%)."""
    if isinstance(value, str):
        return os.path.expanduser(os.path.expandvars(value))
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
