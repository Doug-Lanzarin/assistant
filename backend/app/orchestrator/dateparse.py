"""Interpretação de datas e horários em português ("amanhã às 9", "em 10 minutos").

Retorna o instante encontrado e o texto com a expressão temporal removida.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.orchestrator.textnorm import fold

WEEKDAYS = {
    "segunda": 0, "segunda-feira": 0, "terca": 1, "terca-feira": 1, "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3, "sexta": 4, "sexta-feira": 4, "sabado": 5, "domingo": 6,
}
NUM_WORDS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
    "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "quinze": 15,
    "vinte": 20, "trinta": 30, "quarenta": 40, "meia": 30,
}
_NUM = r"(\d+|" + "|".join(NUM_WORDS) + r")"


def _num(s: str) -> int:
    return int(s) if s.isdigit() else NUM_WORDS[s]


@dataclass
class ParsedTime:
    when: datetime
    rest: str
    has_time: bool


def _cut(original: str, folded: str, m: re.Match) -> tuple[str, str]:
    a, b = m.span()
    return (original[:a] + " " + original[b:]), (folded[:a] + " " + folded[b:])


def parse_when(text: str, now: datetime | None = None) -> ParsedTime | None:
    now = now or datetime.now().astimezone()
    original = text
    t = fold(text)
    found = False
    day: datetime | None = None
    hour: int | None = None
    minute = 0

    # Relativo: "em 10 minutos", "daqui a 2 horas", "daqui 3 dias"
    m = re.search(r"\b(?:em|daqui a|daqui)\s+" + _NUM + r"\s*(minutos?|min|horas?|h|dias?|semanas?)\b", t)
    if m:
        n = _num(m.group(1))
        unit = m.group(2)
        if unit.startswith("min"):
            delta = timedelta(minutes=n)
        elif unit.startswith("h"):
            delta = timedelta(hours=n)
        elif unit.startswith("dia"):
            delta = timedelta(days=n)
        else:
            delta = timedelta(weeks=n)
        original, t = _cut(original, t, m)
        when = now + delta
        return ParsedTime(when.replace(microsecond=0), _squash(original), unit[0] in "mh")

    m = re.search(r"\bdepois de amanha\b", t)
    if m:
        day, found = now + timedelta(days=2), True
        original, t = _cut(original, t, m)
    else:
        m = re.search(r"\bamanha\b", t)
        if m:
            day, found = now + timedelta(days=1), True
            original, t = _cut(original, t, m)
        else:
            m = re.search(r"\bhoje\b", t)
            if m:
                day, found = now, True
                original, t = _cut(original, t, m)

    if day is None:
        m = re.search(r"\b(?:na |no |nesta |neste |proxima |proximo )?(" + "|".join(
            sorted(WEEKDAYS, key=len, reverse=True)) + r")\b", t)
        if m:
            target = WEEKDAYS[m.group(1)]
            delta = (target - now.weekday()) % 7 or 7
            day, found = now + timedelta(days=delta), True
            original, t = _cut(original, t, m)

    if day is None:
        m = re.search(r"\b(?:dia\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
        if m:
            d, mo = int(m.group(1)), int(m.group(2))
            y = int(m.group(3)) if m.group(3) else now.year
            if y < 100:
                y += 2000
            try:
                day = now.replace(year=y, month=mo, day=d)
                if not m.group(3) and day.date() < now.date():
                    day = day.replace(year=y + 1)
                found = True
                original, t = _cut(original, t, m)
            except ValueError:
                day = None
        else:
            m = re.search(r"\bdia\s+(\d{1,2})\b", t)
            if m:
                d = int(m.group(1))
                try:
                    day = now.replace(day=d)
                    if day.date() < now.date():
                        month = now.month % 12 + 1
                        day = day.replace(month=month, year=now.year + (1 if month == 1 else 0))
                    found = True
                    original, t = _cut(original, t, m)
                except ValueError:
                    day = None

    # Horário
    m = re.search(r"\b(?:as|a|ao)?\s*(\d{1,2})(?::|h)(\d{2})\b", t) or re.search(
        r"\b(?:as|às)\s+(\d{1,2})(?:\s*h(?:oras?)?)?\b", t
    ) or re.search(r"\b(\d{1,2})\s*h(?:oras?)?\b", t)
    if m:
        hour = int(m.group(1))
        if m.lastindex and m.lastindex >= 2 and m.group(2):
            minute = int(m.group(2))
        original, t = _cut(original, t, m)
        found = True
    else:
        m = re.search(r"\bao meio-dia\b|\bmeio dia\b|\bmeio-dia\b", t)
        if m:
            hour = 12
            original, t = _cut(original, t, m)
            found = True
    pm = re.search(r"\b(da|de|a|à) (tarde|noite)\b", t)
    am = re.search(r"\b(da|de) manha\b", t)
    if pm:
        if hour is None:
            hour = 15 if pm.group(2) == "tarde" else 20
        elif hour < 12:
            hour += 12
        original, t = _cut(original, t, pm)
        found = True
    elif am:
        if hour is None:
            hour = 9
        original, t = _cut(original, t, am)
        found = True

    if not found:
        return None
    if hour is not None and not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    base = day or now
    has_time = hour is not None
    if hour is None:
        hour, minute = 9, 0  # padrão: 9h do dia indicado
    when = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day is None and when <= now:
        when += timedelta(days=1)
    return ParsedTime(when, _squash(original), has_time)


def _squash(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;!?])", r"\1", s)
    return s.strip(" ,")


def parse_period(text: str, now: datetime | None = None) -> tuple[datetime, datetime, str] | None:
    """Períodos passados: ontem, hoje, semana passada, mês passado, últimos N dias."""
    now = now or datetime.now().astimezone()
    t = fold(text)
    until_now = now + timedelta(minutes=1)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\banteontem\b", t):
        s = start_today - timedelta(days=2)
        return s, s + timedelta(days=1), "anteontem"
    if re.search(r"\bontem\b", t):
        s = start_today - timedelta(days=1)
        return s, start_today, "ontem"
    if re.search(r"\bhoje\b", t):
        return start_today, until_now, "hoje"
    if re.search(r"\bsemana passada\b", t):
        s = start_today - timedelta(days=now.weekday() + 7)
        return s, s + timedelta(days=7), "semana passada"
    if re.search(r"\b(esta|essa|nesta|nessa) semana\b", t):
        s = start_today - timedelta(days=now.weekday())
        return s, until_now, "esta semana"
    if re.search(r"\bmes passado\b", t):
        first_this = start_today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), first_this, "mês passado"
    if re.search(r"\b(este|esse|neste|nesse) mes\b", t):
        return start_today.replace(day=1), until_now, "este mês"
    m = re.search(r"\bultimos?\s+" + _NUM + r"\s+dias\b", t)
    if m:
        n = _num(m.group(1))
        return start_today - timedelta(days=n), until_now, f"últimos {n} dias"
    if re.search(r"\bano passado\b", t):
        s = start_today.replace(month=1, day=1)
        return s.replace(year=s.year - 1), s, "ano passado"
    return None
