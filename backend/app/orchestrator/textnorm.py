"""Normalização de texto em português preservando o alinhamento de caracteres."""

from __future__ import annotations

import re
import unicodedata


def _base_char(c: str) -> str:
    decomposed = unicodedata.normalize("NFKD", c)
    base = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    low = base.lower()
    return low if len(low) == 1 else (c.lower() if len(c.lower()) == 1 else c)


def fold(text: str) -> str:
    """Minúsculas e sem acentos, mesmo comprimento do original (1:1)."""
    return "".join(_base_char(c) for c in text)


def normalize_key(text: str) -> str:
    """Chave para comparação (sem acentos, sem pontuação, espaços simples)."""
    t = fold(text)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_WAKE = re.compile(r"^\s*(ok\s+|ei\s+|hey\s+|oi\s+)?jarvis[\s,.:!-]*", re.I)


def strip_wake_word(text: str, wake: str = "jarvis") -> str:
    pat = _WAKE if wake.lower() == "jarvis" else re.compile(
        r"^\s*(ok\s+|ei\s+|hey\s+|oi\s+)?" + re.escape(wake) + r"[\s,.:!-]*", re.I
    )
    return pat.sub("", text, count=1).strip()


def clean_tail(text: str) -> str:
    return text.strip().strip(" .,!?;:\"'“”").strip()
