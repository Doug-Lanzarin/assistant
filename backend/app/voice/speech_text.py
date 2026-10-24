"""Texto pronto para ser FALADO (vale para o Piper e para a voz do PC).

A resposta exibida na tela tem símbolos, citações e formatação. Lidos ao pé da
letra, eles tornam a fala robótica ("vinte e três ºC", "colchete memória doze",
"✔", "21 dois pontos 30"). Aqui o texto vira o que uma pessoa diria.
"""

from __future__ import annotations

import re

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")
_UNITS = [
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:°|º)\s*C\b"), r"\1 graus"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:°|º)(?!\w)"), r"\1 graus"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*%"), r"\1 por cento"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*GB\b"), r"\1 gigabytes"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*MB\b"), r"\1 megabytes"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*km/h\b"), r"\1 quilômetros por hora"),
    (re.compile(r"(\d+)\s*ms\b"), r"\1 milissegundos"),
]


def _money(m: re.Match) -> str:
    reais = int(m.group(1).replace(".", ""))
    cents = int(m.group(2) or 0)
    out = f"{reais} {'real' if reais == 1 else 'reais'}"
    if cents:
        out += f" e {cents} {'centavo' if cents == 1 else 'centavos'}"
    return out


def _time(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    if mi == 0:
        return f"{h} {'hora' if h == 1 else 'horas'}"
    return f"{h} e {mi}"


def to_speech(text: str, max_chars: int = 600) -> str:
    t = re.sub(r"```.*?```", " (trecho de código na tela) ", text, flags=re.S)
    t = re.sub(r"`([^`]{1,40})`", r"\1", t)
    t = re.sub(r"https?://\S+", " (link na tela) ", t)
    t = re.sub(r"\[[^\]]{0,80}\]", "", t)  # citações [memória #12]
    t = re.sub(r"\(\s*\)", "", t)
    t = _EMOJI.sub(" ", t)
    t = re.sub(r"[✔✖✓✗→←⇒•▪◦]", " ", t)
    t = re.sub(r"(?m)^\s*[-*•]\s+", "", t)  # marcadores de lista
    t = re.sub(r"[*#>_~|]+", " ", t)
    t = re.sub(r"R\$\s*(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?", _money, t)
    t = re.sub(r"\b([01]?\d|2[0-3])[:h]([0-5]\d)\b", _time, t)
    for pat, rep in _UNITS:
        t = pat.sub(rep, t)
    t = re.sub(r"\s*\n+\s*", ". ", t)  # quebras de linha viram pausas
    t = re.sub(r"\.(\s*\.)+", ".", t)
    t = re.sub(r"([:;,])\s*\.", r"\1", t)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r"\(\s*([^)]*?)\s*\)", lambda m: f"({m.group(1)})" if m.group(1) else "", t)
    t = re.sub(r"\s+", " ", t).strip(" .")
    if t and t[-1] not in ".!?…":
        t += "."
    if len(t) > max_chars:
        t = t[:max_chars].rsplit(" ", 1)[0] + "… Os detalhes estão na tela."
    return t
