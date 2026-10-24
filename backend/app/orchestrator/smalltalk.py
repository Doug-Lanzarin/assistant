"""Conversa social (saudações, agradecimentos, despedidas), respondida na hora e sem IA.

Antes, "boa noite" não era um comando e ia para a IA. Sem IA configurada, a
resposta era "não reconheci"; com um modelo local lento, o orb ficava
"processando" por muito tempo para responder a um simples cumprimento.

Só responde quando a frase INTEIRA é conversa social. "Boa noite, desligue as
luzes" separa o cumprimento e segue com o comando.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.orchestrator.textnorm import fold

_WAKE = r"(?:jarvis|jarvez|jarviz|javis|djarvis)"
_GREET = (r"(?:oi+|ola|ei|opa|e ai|eai|salve|hey|alo|bom dia|boa tarde|boa noite|boa madrugada|"
          r"(?:muito )?bom te ver|que bom te ver)")
_HOW = (r"(?:tudo bem|tudo bom|tudo certo|tudo joia|tudo tranquilo|beleza|blz|como vai|como (?:voce )?esta|"
        r"como (?:voce )?ta|como vai voce|como estao as coisas|e ai como (?:vai|esta|ta))")
_THANKS = r"(?:obrigad[oa]|muito obrigad[oa]|obg|valeu|vlw|brigad[oa]|agradeco|grato|grata|obrigadao)"
_BYE = r"(?:tchau|ate logo|ate mais|ate depois|ate amanha|falou|fui|adeus|tenha uma boa noite|bons sonhos|durma bem)"
_WHO = (r"(?:quem (?:e|eh) voce|quem voce e|o que (?:e|eh) voce|qual (?:e )?(?:o )?seu nome|como (?:voce )?se chama|"
        r"o que voce faz|para que voce serve|voce e quem)")
_FINE = (r"(?:(?:tudo |to |estou |eu estou |eu to )?(?:bem|otimo|otima|tranquilo|tranquila|joia|de boa|bem tambem|"
         r"tudo bem tambem|tudo otimo|tudo certo|mais ou menos|cansad[oa]))")
_FILL = r"(?:\s+(?:" + _WAKE + r"|meu amigo|amigo|cara|por favor|pra voce|para voce|tambem|entao))*"


def _clean(text: str) -> str:
    t = fold(text)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _full(pattern: str, t: str) -> bool:
    return re.fullmatch(rf"(?:{_WAKE}\s+)?(?:{pattern}){_FILL}", t) is not None


def period(now: datetime) -> str:
    h = now.hour
    if 5 <= h < 12:
        return "Bom dia"
    if 12 <= h < 18:
        return "Boa tarde"
    return "Boa noite"


_LEAD = re.compile(rf"^\s*(?:{_WAKE}[\s,]+)?((?:bom dia|boa tarde|boa noite|oi+|ola|e ai|opa)(?:[\s,]+{_WAKE})?)[\s,.!;:-]+(?=\w)")


def split_greeting(text: str) -> tuple[str | None, str]:
    """Separa um cumprimento inicial do restante ("boa noite, que horas são?")."""
    m = _LEAD.match(fold(text))  # fold preserva o comprimento: os índices valem para o original
    if not m:
        return None, text
    return text[m.start(1):m.end(1)], text[m.end():]


def reply(text: str, user_name: str = "", assistant: str = "JARVIS", state: dict | None = None,
          now: datetime | None = None) -> str | None:
    """Resposta curta e natural (adequada para voz), ou None se não for conversa social."""
    t = _clean(text)
    if not t:
        return None
    now = now or datetime.now()
    name = f", {user_name.split()[0]}" if user_name.strip() else ""
    state = state if state is not None else {}
    asked = state.pop("smalltalk_asked", False)

    if asked and _full(_FINE, t):
        return "Que bom! Se precisar de alguma coisa, é só falar."
    greet_how = re.fullmatch(rf"(?:{_WAKE}\s+)?{_GREET}(?:\s+{_WAKE})?\s+(?:{_HOW})(?:\s+{_WAKE})?", t)
    if greet_how or _full(_HOW, t):
        state["smalltalk_asked"] = True
        said = re.search(r"\b(bom dia|boa tarde|boa noite)\b", t)
        greet = said.group(1).capitalize() if said else period(now)
        return f"{greet}{name}! Tudo certo por aqui, obrigado por perguntar. E com você?"
    if _full(_GREET, t):
        # Responde com o mesmo cumprimento da pessoa (o relógio do PC pode estar em outro fuso).
        said = re.search(r"\b(bom dia|boa tarde|boa noite)\b", t)
        greet = said.group(1).capitalize() if said else period(now)
        return f"{greet}{name}! Em que posso ajudar?"
    if _full(_THANKS, t) or _full(rf"{_THANKS}\s+{_WAKE}", t):
        return "Por nada! Estou por aqui se precisar."
    if _full(_BYE, t) or _full(rf"(?:{_THANKS}\s+)?{_BYE}", t):
        late = now.hour >= 20 or now.hour < 5
        return f"{'Boa noite' if late else 'Até logo'}{name}! Quando precisar, é só chamar."
    if _full(_WHO, t):
        return (f"Sou o {assistant}, seu assistente pessoal. Posso abrir programas, salvar e copiar textos, "
                "criar tarefas e lembretes, consultar sua memória e controlar a casa. Diga \"ajuda\" para ver exemplos.")
    return None
