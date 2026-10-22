import pytest

from app.orchestrator.intents import parse

CASES = [
    ("Jarvis, abra o VS Code.", "open_target", {"target": "VS Code"}),
    ("Jarvis, encontre a ideia de projeto que anotei.", "brain_search", {}),
    ("Jarvis, leia minhas mensagens do WhatsApp.", "whatsapp_read", {}),
    ("Jarvis, copie a consulta SQL de coletas.", "clipboard_copy", {"query": "consulta SQL de coletas"}),
    ("Jarvis, ajuste o ar-condicionado para 23 graus.", "climate_set", {"temperature": 23.0}),
    ("Jarvis, ajuste o ar para 23 graus", "climate_set", {"target": "ar", "temperature": 23.0}),
    ("Jarvis, resuma o que fiz ontem no projeto JARVIS.", "memory_timeline", {"project": "JARVIS"}),
    ("Jarvis, quais tarefas estão pendentes?", "task_list", {}),
    ("Jarvis, salve o conteúdo que copiei.", None, {}),
    ("Jarvis, salve o que copiei como consulta SQL de coletas.", "clipboard_save", {"title": "consulta SQL de coletas"}),
    ("Salve o clipboard como configuração do Docker", "clipboard_save", {"title": "configuração do Docker"}),
    ("Guarde isso no projeto JARVIS", "clipboard_save", {"project": "JARVIS"}),
    ("Encontre o código que salvei ontem", "clipboard_search", {}),
    ("Procure aquela consulta SQL", "clipboard_search", {}),
    ("Liste meus comandos Git salvos", "clipboard_list", {"query": "comandos Git"}),
    ("Copie o conteúdo salvo para eu colar", "clipboard_copy", {"query": None}),
    ("Mostre os registros da categoria SQL", "clipboard_list", {"category": "SQL"}),
    ("Atualize esse registro com o que copiei agora", "clipboard_update_from_clipboard", {"query": None}),
    ("Renomeie esse conteúdo para Consulta de coletas v2", "clipboard_rename", {"new_title": "Consulta de coletas v2"}),
    ("Apague o registro que salvei por engano", "clipboard_delete", {"query": None}),
    ("Jarvis, execute minha rotina de início do trabalho.", "routine_run", {"name": "início do trabalho"}),
    ("Jarvis, inicie meu ambiente de desenvolvimento", "routine_run", {"name": "desenvolvimento"}),
    ("Jarvis, mostre o uso de memória", "system_status", {}),
    ("Jarvis, crie um lembrete para revisar esse código amanhã", "reminder_create", {"text": "revisar esse código amanhã"}),
    ("Jarvis, ligue o ar-condicionado", "home_turn", {"target": "ar-condicionado", "on": True}),
    ("Jarvis, desligue as luzes da sala", "home_turn", {"target": "luzes da sala", "on": False}),
    ("Jarvis, qual é a temperatura da sala?", "home_sensor", {"target": "sala", "measure": "temperatura"}),
    ("Jarvis, execute a rotina de boa noite", "routine_run", {"name": "boa noite"}),
    ("Jarvis, mande uma mensagem para o João dizendo que estou chegando", "whatsapp_send",
     {"to": "João", "text": "Estou chegando"}),
    ("O que eu estava desenvolvendo no mês passado?", "memory_timeline", {}),
    ("Encontre aquela ideia de aplicativo que registrei", "brain_search", {}),
    ("Quais decisões tomei sobre o sistema?", "brain_search", {"kind": "decision"}),
    ("Relacione minhas notas de Java", "graph_related", {"query": "Java"}),
    ("De onde veio essa informação?", "last_sources", {}),
    ("Esqueça essa informação e remova seus índices derivados", "memory_forget", {"query": None}),
    ("Anote a ideia de um app de receitas no projeto Cozinha", "memory_add", {"kind": "idea", "project": "Cozinha"}),
    ("Quais projetos utilizam Python?", "graph_query", {"entity": "Python"}),
    ("que horas são?", "datetime_now", {}),
    ("parar tudo", "emergency_stop", {}),
    ("retomar operações", "emergency_resume", {}),
    ("Crie uma tarefa chamada revisar documentação do JARVIS, por favor.", "task_create", {"title": "revisar documentação do JARVIS"}),
    ("Jarvis, abra meu projeto de APIs", "open_target", {"target": "projeto de APIs"}),
]


@pytest.mark.parametrize("text,tool,args", CASES)
def test_intents(text, tool, args):
    intent = parse(text)
    if tool is None:
        # "salve o conteúdo que copiei" também deve salvar o clipboard
        assert intent is not None and intent.tool == "clipboard_save"
        return
    assert intent is not None, text
    assert intent.tool == tool, (text, intent)
    for k, v in args.items():
        assert intent.args.get(k) == v, (text, k, intent.args)


def test_unknown_goes_to_ai():
    assert parse("Qual a capital da Austrália e por que ela foi escolhida?") is None
    assert parse("Explique o que é RAG em poucas palavras") is None


# Transcrições reais do faster-whisper (voz sintetizada pt-BR), medidas em scripts/benchmark.py
ASR = [
    ("Jarvis, ajuste o ACONDITIONADO para 23 graus.", "climate_set", {"temperature": 23.0}),
    ("que avise ajuste o ACondicionado para vinte e três graus", "climate_set", {"temperature": 23.0}),
    ("Já vi isso, mandi uma mensagem para o João dizendo que estou chegando.", "whatsapp_send", {"to": "João"}),
    ("Jarvis, abro o VS Code.", "open_target", {"target": "VS Code"}),
    ("Da Viz, salve o que copiei como consulta SQL de coletas.", "clipboard_save", {"title": "consulta SQL de coletas"}),
    ("Avis, quais tarefas estão pendentes?", "task_list", {}),
    ("ajuste o ar para 20 e 3 graus", "climate_set", {"temperature": 23.0}),
    ("Jarvis, ajuste o ar para dezoito graus", "climate_set", {"temperature": 18.0}),
    ("Jarvis, que aora são.", "datetime_now", {}),
]


@pytest.mark.parametrize("text,tool,args", ASR)
def test_asr_variants(text, tool, args):
    intent = parse(text)
    assert intent is not None and intent.tool == tool, (text, intent)
    for k, v in args.items():
        assert intent.args.get(k) == v


def test_wake_word_not_stripped_inside_words():
    from app.orchestrator.textnorm import strip_wake_word

    assert strip_wake_word("Avisar o time amanhã") == "Avisar o time amanhã"
    assert strip_wake_word("Davison é meu colega") == "Davison é meu colega"
