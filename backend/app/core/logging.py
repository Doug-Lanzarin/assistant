"""Logs estruturados (JSON por linha) com rotação e mascaramento de segredos."""

from __future__ import annotations

import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET_PATTERNS = [
    re.compile(r"(sk-ant-[A-Za-z0-9_\-]{8})[A-Za-z0-9_\-]+"),
    re.compile(r"(sk-[A-Za-z0-9]{4})[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{12,}", re.I),
    re.compile(r"(eyJ[A-Za-z0-9_\-]{6})[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
]


def redact(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: m.group(1) + "***", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update({k: redact(str(v)) if isinstance(v, str) else v for k, v in extra.items()})
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(logs_dir: Path, level: str = "INFO", console: bool = True) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        if getattr(h, "_jarvis", False):
            root.removeHandler(h)
    file_handler = RotatingFileHandler(
        logs_dir / "jarvis.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler._jarvis = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)
    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(JsonFormatter())
        ch._jarvis = True  # type: ignore[attr-defined]
        root.addHandler(ch)


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields: object) -> None:
    logger.log(level, msg, extra={"fields": fields})
