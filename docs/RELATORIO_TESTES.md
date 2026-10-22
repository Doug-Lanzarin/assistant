# Relatório de testes

Execução: 2026-10-22, ambiente de desenvolvimento Linux (Python 3.13, Node 22, Chromium 140 headless).
Comando: `scripts\test.ps1` (ou `python scripts/jarvisctl.py test`); no Windows, também `setup.bat -Tests`.

## Resumo
| Suíte | Testes | Resultado |
|---|---|---|
| Backend (pytest) | 172 | ✅ 172 aprovados |
| Interface (Vitest + Testing Library + axe-core) | 27 | ✅ 27 aprovados |
| Lint (ruff, regras de segurança S/B/BLE) | — | ✅ sem pendências |
| TypeScript estrito + build de produção | — | ✅ |
| Sintaxe dos scripts PowerShell (parser do PowerShell 7.4) | 12 scripts | ✅ |

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
| `test_setup_scripts.py` | 14 | instalador e inicialização: leitura do `.env` (comentários, aspas, BOM) sem sobrescrever o ambiente; chaves nunca exibidas; `.env.example` sem valores de chave; impressão digital (idempotência) ignora `node_modules`; requisitos por recurso e alternativa do openWakeWord; `start` recusa sem configuração concluída ou com dependências alteradas; falha obrigatória remove o indicador e retorna 1; recursos escolhidos são lembrados; `.env`/`jarvis.toml` existentes preservados byte a byte e chave fora do log; `jarvisctl run`/`setup-status` sem setup → código 1; `.bat` em ASCII com CRLF e `.ps1` com BOM | automatizado |
| `test_whatsapp_web.py` | 2 | adaptador Playwright: login, não lidas, busca de contato, envio com verificação, falha detectada, conversa inexistente | simulado (página local que imita o WhatsApp Web) |

## Interface
`frontend/tests/app.test.tsx` (10): primeiro cadastro e login; senha errada; backend fora do ar; painel com estados reais e sem violações graves de acessibilidade (axe); erro com "Tentar novamente"; parada de emergência; conversa com confirmação de ação pendente; erro de rede transparente; clipboard copiar; agente desconectado.

`frontend/tests/orb.test.tsx` (17): **máquina de estados** (fluxo real microfone→transcrição→IA→TTS→repouso; LISTENING só com microfone e SPEAKING só com TTS tocando; eventos ignorados fora do estado; OFF aceita só iniciar; FAILED de qualquer estado ativo com motivo e RECOVER; CANCEL e interrupção da fala); **visual** (cada estado converge para a sua cor; brilho repouso < processando < ouvindo < falando; transição de cor sem saltos; ao falar, núcleo e brilho seguem a amplitude, silêncio não gera ondas e mais volume gera mais ondas; ao ouvir, o núcleo expande com a voz; processando ignora o áudio; erro com exatamente 3 pulsos e depois estável; interpolação independente da taxa de quadros); medição RMS→dB, faixas log e envelope por palavra; **tela** (estado visual = estado da máquina ao iniciar, com falha real do microfone → ERROR → IDLE e encerrar; pedido digitado em THINKING até a resposta; falha do backend → ERROR com o motivo).

## Testes manuais / ponta a ponta executados
| **Orb com áudio real** (`scripts/orb_e2e.py`): Chromium com microfone alimentado por frase falada → Whisper local → resposta → Piper | ✅ correlação amplitude×raio 0,99; cores medidas por estado; histórico da máquina OFF→IDLE→LISTENING→THINKING→SPEAKING→IDLE; falha simulada (500) → ERROR com 3 pulsos → IDLE; vídeo em docs/media/orb-demo.mp4 |
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

## Instalador e inicialização
Executado em 2026-10-22 numa **cópia limpa** do projeto (sem `.venv`, `node_modules`, `dist`, `data`, `.env` nem `jarvis.toml`), num caminho com espaços, parênteses, `&` e acentos.

| Cenário | Resultado |
|---|---|
| `jarvisctl setup` (o que o `setup.bat` executa depois dos pré-requisitos), primeira vez | ✅ código 0 em 74 s: dependências, voz (openWakeWord via alternativa 0.4.0 no Python 3.13), interface, `jarvis.toml` e `.env` criados, banco e migração, modelos de voz, backend iniciado numa porta temporária (`/api/health`, página do orb, 401 sem login) |
| Segunda execução | ✅ 7 s, "nada a fazer"; `.env`, `jarvis.toml` e banco com o mesmo SHA-1 de antes; a chave de teste no `.env` não aparece em nenhum log nem relatório |
| Falha de um pacote opcional (openWakeWord ≥ 0.6 no 3.13) | ✅ os demais pacotes de voz são instalados; aviso com o nome do pacote; a impressão digital não é gravada e a próxima execução tenta de novo |
| Ctrl+C durante `npm run build` | ✅ "interrompida pelo usuário", indicador removido, `start` recusa; a próxima execução pula o `npm ci` já concluído e refaz só a compilação |
| `jarvisctl run` (o que o `start.bat` executa) | ✅ "JARVIS pronto em 3 s"; logs `[backend]` e `[agente]` na janela; agente conectado; orb carregado no Chromium (estado IDLE, sem erros) |
| Segunda instância | ✅ "já em execução", código 0, sem processos novos |
| Porta ocupada por outro programa | ✅ código 1: "A porta 8790 está ocupada por python3 (pid …)" |
| Sem configuração / dependências alteradas | ✅ código 1 com a instrução "execute setup.bat" |
| Ctrl+C no `run` | ✅ agente → backend → supervisor encerrados em 1 s; nenhum processo restante |
| Um JARVIS de **outra** pasta já em execução na mesma porta | ✅ o teste de integridade não a confunde com esta instalação (usa porta temporária) — defeito encontrado e corrigido |
| `setup.ps1` no PowerShell 7.4 (Linux) | ✅ análise sintática sem erros; fora do Windows retorna 3 com a mensagem; funções de versão, `.env` (espaços, aspas, comentário) e execução silenciosa testadas — o teste revelou um `$LASTEXITCODE` herdado, corrigido |
| `setup.bat` e `start.bat` no `cmd` do **Wine 9** | ✅ caminho com espaços, parênteses e `&`; argumentos repassados com aspas corretas; códigos 0/1/5 propagados; mensagens de "não configurado" e "pasta incompleta"; o `setup.bat` **não** declara sucesso quando o PowerShell não fez nada (o Wine tem um PowerShell vazio que retorna 0) — defeito encontrado e corrigido com a confirmação `setup-status`. Encontrados também: `||` após `cd` e `%CMDCMDLINE%` não funcionam no Wine → substituídos por verificações que funcionam nos dois |

**Não executado (exige Windows real):** `winget` instalando Python/Node.js/VC++/Ollama, PowerShell 5.1 com acentos (os `.ps1` agora têm BOM UTF-8 justamente para isso), Job Object ao fechar a janela, leitura da permissão de microfone no registro, pausa ao abrir com dois cliques, caminho com acentos no `cmd` (no Wine, `%~dp0` com acentos falha — limitação do Wine).

## Bloqueados por dependência externa (não validados)
| Item | Por quê | Como validar |
|---|---|---|
| Clipboard Win32 real, abrir apps, DPAPI, notificações toast, início automático | exigem Windows | `setup.bat -Tests` → `start.bat` → testes manuais da [lista de verificação](FUNCIONALIDADES.md#lista-de-verificação-no-seu-windows) |
| Microfone, palavra de ativação com a sua voz, SAPI | exigem hardware de áudio | Configurações → Voz |
| Claude real | sem chave de API neste ambiente | Configurações → IA → Testar conexão |
| Ollama real | download bloqueado aqui; o mesmo protocolo foi validado com llama.cpp server | instalar o Ollama e testar |
| Home Assistant, TCL, Alexa reais | sem HA nem dispositivos | guias HOME_ASSISTANT, TCL, ALEXA |
| WhatsApp real (Web ou Business) | sem conta conectada | guia WHATSAPP |
| Leitor de notificações do Windows (WinRT) | exige Windows; a API pode exigir pacote MSIX | modo `notifications` + permissão do Windows |
