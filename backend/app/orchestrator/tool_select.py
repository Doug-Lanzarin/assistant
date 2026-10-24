"""Escolha das ferramentas relevantes para modelos LOCAIS.

As 47 ferramentas com descrições e esquemas somam cerca de 7 mil tokens. Num
i5 sem GPU, um modelo de 3B lê o prompt a algumas centenas de tokens por
segundo. Mandar todas as ferramentas em cada pedido custava dezenas de segundos
antes da primeira palavra da resposta. Aqui, cada pedido leva só as ferramentas
que combinam com o texto (no máximo ``k``), escolhidas por palavras-chave, sem
IA. Os modelos na nuvem continuam recebendo todas.
"""

from __future__ import annotations

import re

from app.orchestrator.textnorm import fold

# Radicais (texto já sem acentos) → ferramentas. Ordem não importa.
_TOPICS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("luz", "luze", "lamp", "tomad", "ligu", "deslig", "liga ", "tv", "televis", "ventil", "fechadur", "portao", "casa",
      "dispositiv", "comodo", "sala", "quarto", "cozinha"), ("home_turn", "home_state", "home_list")),
    (("ar condicion", "ar-condicion", "temperatur", "grau", "climat", "tcl", "esfri", "esquent"), ("climate_set", "home_sensor")),
    (("umidad", "sensor"), ("home_sensor",)),
    (("cena", "script", "automac"), ("home_scene",)),
    (("alexa", "anunci"), ("alexa_announce",)),
    (("whats", "zap", "mensag", "mand", "envi", "respond"), ("whatsapp_send", "whatsapp_read", "whatsapp_search", "whatsapp_status")),
    (("clipboard", "area de transfer", "copi", "colar", "cole ", "copiei", "salve o que"),
     ("clipboard_save", "clipboard_copy", "clipboard_search", "clipboard_list", "clipboard_read_current")),
    (("abr", "inici", "execut", "rode", "rodar", "program", "aplicativ", "site", "pasta"), ("open_target", "open_file", "routine_run")),
    (("arquiv", "document", "pdf", "planilh"), ("file_search", "open_file", "document_read")),
    (("comando", "build", "teste", "git ", "npm", "compil"), ("dev_command_run",)),
    (("rotina",), ("routine_run",)),
    (("lembr", "avis", "alarm", "agend", "amanha", "hora", "minuto"), ("reminder_create", "reminder_list")),
    (("tarefa", "pendent", "todo", "afazer", "conclu", "termine", "fiz"), ("task_create", "task_list", "task_complete")),
    (("anot", "nota", "ideia", "decid", "decis", "aprend", "preferenc", "memoria", "lembra", "sabe sobre", "registr", "guard"),
     ("memory_add", "brain_search", "memory_timeline")),
    (("ontem", "semana", "mes passado", "fiz ", "historic", "linha do tempo"), ("memory_timeline",)),
    (("projeto", "tecnolog", "relac", "utiliza", "usa "), ("graph_query", "graph_related")),
    (("esquec", "apag", "remov", "delet"), ("memory_forget", "clipboard_delete")),
    (("fonte", "de onde"), ("last_sources",)),
    (("cpu", "memoria ram", "ram", "disco", "desempenh", "uso do sistema", "computador"), ("system_status",)),
    (("log",), ("logs_tail",)),
    (("notific",), ("notify",)),
    (("data", "dia e hoje", "que horas", "hoje"), ("datetime_now",)),
]
ALWAYS = ("brain_search",)  # perguntas sobre o passado do usuário dependem da memória


def select_tools(text: str, available: set[str], k: int = 8) -> set[str]:
    """Nomes das ferramentas relevantes para o pedido (vazio = conversa pura, sem ferramentas)."""
    t = " " + re.sub(r"\s+", " ", fold(text)) + " "
    scores: dict[str, int] = {}
    for stems, tools in _TOPICS:
        hits = sum(1 for s in stems if s in t)
        if hits:
            for rank, name in enumerate(tools):
                scores[name] = scores.get(name, 0) + hits * 10 - rank
    chosen = [n for n, _ in sorted(scores.items(), key=lambda kv: -kv[1]) if n in available][: max(0, k - len(ALWAYS))]
    return set(chosen) | {n for n in ALWAYS if n in available}
