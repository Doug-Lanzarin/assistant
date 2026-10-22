"""Armazenamento de segredos.

* Uma chave-mestra aleatória cifra os segredos com Fernet (AES-128-CBC + HMAC).
* No Windows a chave-mestra é protegida com DPAPI (``CryptProtectData``),
  vinculada à conta do usuário: copiar o arquivo para outra máquina/conta não
  permite decifrá-lo.
* Em outros sistemas (testes/dev) a chave fica num arquivo com permissão 0600.

O mesmo ``Cipher`` é usado para cifrar itens sensíveis do clipboard em repouso.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class _Dpapi:
    """Wrapper mínimo de DPAPI via ctypes (sem pywin32)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        self.ctypes = ctypes
        self.BLOB = BLOB
        self.crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        self.kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    def _call(self, fn, data: bytes) -> bytes:
        ctypes = self.ctypes
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = self.BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = self.BLOB()
        CRYPTPROTECT_UI_FORBIDDEN = 0x01
        ok = fn(
            ctypes.byref(blob_in), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(blob_out),
        )
        if not ok:
            raise OSError("Falha na DPAPI: " + str(ctypes.GetLastError()))
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            self.kernel32.LocalFree(blob_out.pbData)

    def protect(self, data: bytes) -> bytes:
        return self._call(self.crypt32.CryptProtectData, data)

    def unprotect(self, data: bytes) -> bytes:
        return self._call(self.crypt32.CryptUnprotectData, data)


def _load_master_key(secrets_dir: Path) -> tuple[bytes, str]:
    secrets_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        path = secrets_dir / "master.key.dpapi"
        dpapi = _Dpapi()
        if path.exists():
            return dpapi.unprotect(path.read_bytes()), "dpapi"
        key = Fernet.generate_key()
        path.write_bytes(dpapi.protect(key))
        return key, "dpapi"
    path = secrets_dir / "master.key"
    if path.exists():
        return path.read_bytes().strip(), "file-0600"
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key, "file-0600"


class Cipher:
    def __init__(self, key: bytes):
        self._f = Fernet(key)

    def encrypt(self, text: str) -> str:
        return self._f.encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._f.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as e:
            raise ValueError("Não foi possível decifrar o conteúdo (chave diferente?)") from e


class SecretStore:
    """Chave/valor cifrado em ``secrets/secrets.enc``."""

    KNOWN = {
        "anthropic_api_key": "Chave da API Anthropic (Claude)",
        "openai_api_key": "Chave de API compatível com OpenAI",
        "ha_token": "Token de longa duração do Home Assistant",
        "whatsapp_cloud_token": "Token da WhatsApp Cloud API",
        "whatsapp_app_secret": "App Secret da Meta (assinatura de webhooks)",
        "whatsapp_verify_token": "Verify token do webhook do WhatsApp",
        "agent_token": "Token de autenticação do agente local",
    }

    def __init__(self, secrets_dir: Path):
        self.dir = secrets_dir
        key, self.backend = _load_master_key(secrets_dir)
        self.cipher = Cipher(key)
        self.path = secrets_dir / "secrets.enc"
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.cipher.decrypt(self.path.read_text("ascii")))

    def _write(self, data: dict[str, str]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(self.cipher.encrypt(json.dumps(data)), "ascii")
        os.replace(tmp, self.path)
        if sys.platform != "win32":
            os.chmod(self.path, 0o600)

    def get(self, name: str) -> str | None:
        with self._lock:
            return self._read().get(name)

    def set(self, name: str, value: str) -> None:
        with self._lock:
            data = self._read()
            data[name] = value
            self._write(data)

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._read()
            data.pop(name, None)
            self._write(data)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._read().keys())

    def status(self) -> list[dict]:
        present = set(self.names())
        return [
            {"name": k, "description": v, "configured": k in present}
            for k, v in self.KNOWN.items()
        ]
