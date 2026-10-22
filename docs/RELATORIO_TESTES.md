# Relatório de testes

Execução: 2026-10-22, ambiente de desenvolvimento Linux (Python 3.13, Node 22, Chromium 140 headless).
Comando: `scripts\test.ps1` (ou `python scripts/jarvisctl.py test`).

## Resumo
| Suíte | Testes | Resultado |
|---|---|---|
| Backend (pytest) | 155 | ✅ 155 aprovados |
| Interface (Vitest + Testing Library + axe-core) | 10 | ✅ 10 aprovados |
| Lint (ruff, regras de segurança S/B/BLE) | — | ✅ sem pendências |
| TypeScript estrito + build de produção | — | ✅ |
| Sintaxe dos scripts PowerShell (parser do PowerShell 7.4) | 11 scripts | ✅ |

## Legenda
- **Automatizado:** roda em `scripts\test.ps1`.
- **Simulado:** a dependência externa foi substituída por um simulador que segue a API documentada (MockTransport, página HTML local, provedor de IA roteirizado).
- **Manual/E2E:** executado de verdade neste ambiente (servidor real, navegador real, processos reais).
- **Bloqueado:** depende do seu Windows, das suas contas ou dos seus dispositivos.

## Backend por área
| Arquivo | Qtde | O que comprova | Tipo |
|---|---|---|---|
| `test_intents.py` | 52 | ~40 comandos do enunciado em pt-BR → ferramenta e argumentos certos; variações reais de transcrição do Whisper ("Já viz", "acondicionado", "vinte e três"); palavra de ativação não removida do meio de palavras | automatizado |
| `test_clipboard.py` | 18 | ciclo completo salvar → encontrar → copiar com o conteúdo **byte a byte** igual (quebras de linha, tab, acentos); sem duplicatas; clipboard vazio ou imagem; **nenhuma leitura sem pedido**; segredo cifrado, fora do índice e oculto na busca; atualizar/renomear/apagar (com confirmação); ambiguidade sem sobrescrever o clipboard e escolha "o segundo"; categorias; projeto; exportar/importar; agente ausente | automatizado (despachante **real** do agente com clipboard em memória) |
| `test_orchestrator.py` | 18 | ferramenta inventada pela IA rejeitada e auditada; argumentos inválidos ou extras; IA sem acesso a ferramentas internas; loop de ferramentas com fontes; **envio externo para em confirmação**; **prompt injection** em mensagem recebida não executa nada sem confirmação e chega como `<dados_nao_confiaveis>`; fallback entre provedores com métricas; modo offline honesto; limite de tokens bloqueia a nuvem; modo de emergência; permissão desativada; nível 4 sempre confirma e não executa duas vezes; cancelamento de tarefa; timeout; **persistência após reinício**; respostas ambíguas ("ok", "vai") não confirmam ações; chamadas repetidas da IA não duplicam ações; edições da IA em dados existentes pedem confirmação | automatizado (IA simulada) |
| `test_memory.py` | 16 | busca híbrida relevante com citação; filtros de projeto, tipo e período; **esquecer remove os índices derivados** (trechos, FTS, vetores, grafo); esquecer por conversa com confirmação; estados (inferida → confirmada → desatualizada → rejeitada); memória não altera permissões; documentos MD/DOCX/PDF, duplicados e nome com `../`; grafo ("quais projetos utilizam Python?"); visão de projeto e tarefas; lembretes disparam evento; linha do tempo; consolidação gera inferências sem reprocessar; duplicatas | automatizado |
| `test_integrations.py` | 17 | **Home Assistant**: sincronização com áreas; "desligue as luzes da sala" só nas luzes da sala, com estado verificado; TCL ligar/ajustar com verificação; temperatura fora da faixa rejeitada; estado que não muda é reportado como falha; sensor; cena; fechadura exige confirmação; 401; HA fora do ar; não configurado; ambiguidade. **WhatsApp Cloud API**: fluxo completo com confirmação e evidência `wamid`; contato ambíguo → escolha → erro 131047 explicado; modo sem envio; webhook (verify token + HMAC). **Notificações**: filtro por app e deduplicação. **Claude**: formato da requisição pelo SDK (modelo, esforço, fallback, sem `temperature`). Lista de permissões do `open_target`. Regressão do formato de mensagens compatível com OpenAI | simulado |
| `test_api_security.py` | 14 | 12 rotas protegidas retornam 401 sem token; primeiro cadastro único; login/logout; **rate limit**; senha com scrypt e token só como hash; **segredos nunca retornados** e cifrados em disco; logs mascaram chaves; entradas malformadas (422/400); path traversal no backup; **backup → alterar → restaurar**; ZIP malicioso recusado; CORS de origem estranha bloqueado e headers de segurança; WebSocket exige token; **backend real (uvicorn) + agente REAL via WebSocket** salvando e copiando o clipboard | automatizado + E2E |
| `test_agent.py` | 18 | métodos fora da lista recusados; parâmetros inválidos; clipboard Unicode; metacaracteres de shell recusados; argumentos inválidos; só URLs http(s); caminho inexistente; `process.run` sem shell (`a && echo hacked` passa literalmente); timeout de processo; lançamento real de processo | automatizado |
| `test_whatsapp_web.py` | 2 | adaptador Playwright: login, não lidas, busca de contato, envio com verificação, falha detectada, conversa inexistente | simulado (página local que imita o WhatsApp Web) |

## Interface
`frontend/tests/app.test.tsx` (10): primeiro cadastro e login; senha errada; backend fora do ar; painel com estados reais e sem violações graves de acessibilidade (axe); erro com "Tentar novamente"; parada de emergência; conversa com confirmação de ação pendente; erro de rede transparente; clipboard copiar; agente desconectado.

## Testes manuais / ponta a ponta executados
| Cenário | Resultado |
|---|---|
| Painel real no Chromium (uvicorn + build de produção): login, painel, conversa, segundo cérebro, clipboard, casa, WhatsApp, configurações, permissões, celular (390 px) | ✅ sem erros no console; capturas revisadas |
| Supervisor: `start` → `status` → segundo `start` recusado (instância única) | ✅ |
| Reinício controlado: "reinicie o jarvis" → confirmação → backend sai com código 3 → supervisor reinicia | ✅ |
| Recuperação de falha: `kill -9` no backend → supervisor reinicia em 2 s | ✅ |
| `stop` encerra supervisor, backend e agente (nenhum processo restante) | ✅ |
| Agente real iniciado pelo supervisor conecta e informa capacidades | ✅ |
| Voz: Piper sintetiza pt-BR → faster-whisper transcreve (tiny/base/small); vocabulário de contexto melhora "Jarvis" de 0/5 para 5/5 | ✅ (voz sintetizada, não humana) |
| **IA local real** (llama.cpp server compatível com OpenAI + Qwen2.5-1.5B-Instruct Q4, CPU): o modelo chamou `brain_search` e `task_create` pelo registro de ferramentas; o loop completo (resultado → resposta) funcionou depois da correção do formato da mensagem | ✅ · revelou 3 defeitos, todos corrigidos e com teste: (1) mensagem de assistente reenviada fora do formato canônico → HTTP 500; (2) modelo fraco repetindo a mesma ferramenta → 6 tarefas duplicadas (agora chamadas idênticas não são reexecutadas); (3) modelo alterando dados existentes por conta própria → agora exige confirmação |
| openWakeWord `hey_jarvis`: custo de CPU e ausência de falso positivo em ruído | ✅ · detecção com voz pt sintetizada ❌ (ver desempenho) |

## Bloqueados por dependência externa (não validados)
| Item | Por quê | Como validar |
|---|---|---|
| Clipboard Win32 real, abrir apps, DPAPI, notificações toast, início automático | exigem Windows | `scripts\install.ps1` → `scripts\test.ps1` → testes manuais da [lista de verificação](FUNCIONALIDADES.md#lista-de-verificação-no-seu-windows) |
| Microfone, palavra de ativação com a sua voz, SAPI | exigem hardware de áudio | Configurações → Voz |
| Claude real | sem chave de API neste ambiente | Configurações → IA → Testar conexão |
| Ollama real | download bloqueado aqui; o mesmo protocolo foi validado com llama.cpp server | instalar o Ollama e testar |
| Home Assistant, TCL, Alexa reais | sem HA nem dispositivos | guias HOME_ASSISTANT, TCL, ALEXA |
| WhatsApp real (Web ou Business) | sem conta conectada | guia WHATSAPP |
| Leitor de notificações do Windows (WinRT) | exige Windows; a API pode exigir pacote MSIX | modo `notifications` + permissão do Windows |
