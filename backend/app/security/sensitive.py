"""Detecção heurística de segredos (senhas, tokens, chaves de API).

Conteúdo marcado como sensível:
* é cifrado em repouso;
* não é indexado em texto pleno nem gera embeddings;
* nunca é enviado a provedores de IA sem autorização explícita.

Falsos positivos são preferíveis a falsos negativos aqui.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("chave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("chave AWS", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("token GitHub", re.compile(r"\b(ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("chave Anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("chave OpenAI", re.compile(r"\bsk-(proj-)?[A-Za-z0-9_\-]{20,}")),
    ("chave Google", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("token Slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    (
        "atribuição de senha",
        re.compile(
            r"(?i)\b(password|passwd|pwd|senha|secret|segredo|api[_-]?key|token|access[_-]?key)"
            r"\s*[:=]\s*['\"]?[^\s'\"]{4,}"
        ),
    ),
    ("string de conexão com senha", re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@/]+@")),
    ("cartão de crédito", re.compile(r"\b(?:\d[ -]?){15,16}\b")),
]


@dataclass
class SensitiveReport:
    sensitive: bool
    reasons: list[str]


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    if len(nums) < 13:
        return False
    total = 0
    for i, d in enumerate(reversed(nums)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def detect_sensitive(text: str) -> SensitiveReport:
    reasons: list[str] = []
    for label, pat in _PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        if label == "cartão de crédito" and not _luhn_ok(m.group(0)):
            continue
        reasons.append(label)
    # Token isolado de alta entropia (ex.: chave copiada sozinha).
    stripped = text.strip()
    if not reasons and 20 <= len(stripped) <= 200 and " " not in stripped and "\n" not in stripped:
        has_classes = sum(
            bool(re.search(p, stripped)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]")
        )
        if _entropy(stripped) >= 4.0 and has_classes >= 3 and not stripped.startswith("http"):
            reasons.append("token de alta entropia")
    return SensitiveReport(bool(reasons), reasons)
