"""Classificação heurística (local, offline) do conteúdo copiado."""

from __future__ import annotations

import json
import re

CATEGORIES = [
    "sql", "git", "docker", "powershell", "shell", "python", "javascript", "java", "csharp", "json", "yaml",
    "html", "regex", "url", "email", "comando", "codigo", "configuracao", "senha", "texto", "arquivos",
]

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("sql", re.compile(r"(?is)^\s*(with\s+\w+\s+as\s*\(|select\s+.+\s+from\s|select\s+[\w*(]+.*\)|insert\s+into\s|update\s+\w+\s+set\s|delete\s+from\s|create\s+(table|view|index|procedure)\s|alter\s+table\s|merge\s+into\s)")),
    ("git", re.compile(r"(?m)^\s*git\s+\w+")),
    ("docker", re.compile(r"(?im)^\s*(docker(-compose)?\s+\w+|FROM\s+[\w./:-]+|services:\s*$)")),
    ("powershell", re.compile(r"(?m)(\b(Get|Set|New|Remove|Start|Stop|Invoke|Write)-[A-Z]\w+|\$env:\w+)")),
    ("shell", re.compile(r"(?m)^\s*(sudo |apt(-get)? |npm |pnpm |yarn |pip |uv |curl |wget |cd |ls |export |chmod |ssh |kubectl )")),
    ("python", re.compile(r"(?m)^\s*(def \w+\(|class \w+[:(]|import \w+|from [\w.]+ import |if __name__ == )")),
    ("java", re.compile(r"(?m)(public\s+(static\s+)?(class|void|interface)\s|System\.out\.println|@Override)")),
    ("csharp", re.compile(r"(?m)(using System;|namespace \w+|public\s+(async\s+)?Task<|Console\.WriteLine)")),
    ("javascript", re.compile(r"(?m)(\bconst \w+ = |\bfunction \w+\(|=>\s*{|\bexport (default|const|function)|console\.log\(|import .+ from ['\"])")),
    ("html", re.compile(r"(?is)^\s*<(!doctype|html|div|span|body|head|p|a|table)\b")),
    ("url", re.compile(r"^\s*https?://\S+\s*$")),
    ("email", re.compile(r"^\s*[\w.+-]+@[\w-]+\.[\w.-]+\s*$")),
    ("yaml", re.compile(r"(?m)^[\w-]+:\s*(\S.*)?$\n^\s+[\w-]+:")),
    ("configuracao", re.compile(r"(?m)^\s*[A-Z_][A-Z0-9_]*=\S*\s*$|^\s*\[[\w.\- ]+\]\s*$")),
]


def classify(text: str, sensitive: bool = False) -> str:
    if sensitive:
        return "senha"
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(stripped)
            return "json"
        except ValueError:
            pass
    for name, pat in _RULES:
        if pat.search(text):
            return name
    if "\n" not in stripped and re.match(r"^[\w.\-]+(\s+-{1,2}[\w-]+)+", stripped):
        return "comando"
    if re.search(r"[{};]\s*$", stripped, re.M) and stripped.count("\n") >= 2:
        return "codigo"
    return "texto"


def suggest_title(text: str, category: str) -> str:
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    first = re.sub(r"\s+", " ", first)
    if category == "senha":
        return "Segredo copiado"
    if len(first) > 60:
        first = first[:57].rstrip() + "…"
    label = {"sql": "Consulta SQL", "git": "Comando Git", "docker": "Docker", "powershell": "PowerShell",
             "shell": "Comando", "url": "Link", "texto": "Texto"}.get(category, category.capitalize())
    return f"{label}: {first}" if first else label
