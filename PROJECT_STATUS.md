# PROJECT_STATUS — JARVIS

> Arquivo para retomar o trabalho sem perder contexto. Atualizado em **2026-10-22**.
> Branch: `claude/jarvis-v1`.

## Resumo
O sistema está **implementado de ponta a ponta** e **testado em ambiente Linux de desenvolvimento**, com 155 testes de backend, 10 de interface, testes E2E no navegador e no supervisor, e medições de voz e desempenho. **Ainda não foi executado no Windows de referência** nem conectado às contas e dispositivos reais. Esses itens estão listados como pendências externas abaixo e não devem ser considerados validados.

## Etapas
| Etapa | Situação | Observações |
|---|---|---|
| 1. Diagnóstico e planejamento | ✅ concluída | o ambiente de desenvolvimento é Linux em nuvem (Xeon 4 vCPU, 15 GB), **não** o notebook Windows; o diagnóstico real do Windows é feito por `scripts\install.ps1` (gera `data\environment-report.json`) |
| 2. Fundação | ✅ | FastAPI, SQLite + migrações, logs JSON com rotação, autenticação, segredos, registro de ferramentas, supervisor, scripts |
| 3. IA e conversação | ✅ (provedores reais pendentes) | interpretador pt-BR offline, Claude (SDK oficial), Ollama/compatível OpenAI, fallback, orçamento, cancelamento |
| 4. Segundo cérebro | ✅ | memórias tipadas com estado e confiança, RAG híbrido, documentos, projetos, tarefas, lembretes, grafo, consolidação, interface |
| 5. Clipboard inteligente | ✅ (Win32 pendente no Windows) | despachante real do agente testado com backend em memória; API Win32 escrita com ctypes |
| 6. Voz | ✅ parcial | STT/TTS locais medidos; vocabulário de contexto; palavra de ativação implementada, **não comprovada com voz real** |
| 7. Automação do Windows | ✅ (execução real pendente) | apps, sites, projetos, pastas, busca de arquivos, comandos aprovados, rotinas, métricas, logs, reinício |
| 8. Casa inteligente | 🧪 simulada | Home Assistant com verificação de estado, TCL via `climate`, Alexa via HA |
| 9. WhatsApp | 🧪 simulada | Cloud API (envio, webhook HMAC), WhatsApp Web (Playwright, página simulada), notificações (WinRT, não testado) |
| 10. Estabilização | ✅ | backup/restauração, diagnóstico, autostart, recuperação de falhas, documentação, relatórios |

## Testes executados (2026-10-22)
- `backend`: **155 aprovados** (`python -m pytest -q`), ruff sem pendências.
- `frontend`: **10 aprovados** (`npm test`), `tsc` estrito e build ok.
- E2E: painel real no Chromium (todas as telas, desktop e celular), supervisor (instância única, reinício controlado, `kill -9` → recuperação, parada limpa), agente real via WebSocket.
- Voz: Piper → faster-whisper (tiny/base/small) e custo do openWakeWord.
- IA local real (llama.cpp + Qwen2.5-1.5B): chamadas de ferramenta reais; 3 defeitos encontrados e corrigidos (formato de mensagem, ações duplicadas, edições sem confirmação).
- Detalhes: [docs/RELATORIO_TESTES.md](docs/RELATORIO_TESTES.md), [docs/RELATORIO_DESEMPENHO.md](docs/RELATORIO_DESEMPENHO.md).

## Erros conhecidos / riscos
- A palavra de ativação `hey_jarvis` não detectou "Hey Jarvis" falado por voz **portuguesa** sintetizada (0,04 de pontuação). É preciso testar com voz humana e ajustar o limiar ou treinar um modelo "Jarvis".
- O `openwakeword>=0.6` não instala em Python 3.13 no Linux (dependência `tflite-runtime`); com 0.4 funciona. No Windows, recomenda-se Python 3.12.
- A API `UserNotificationListener` pode negar acesso a apps Python não empacotados (MSIX) em algumas versões do Windows.
- Os seletores do WhatsApp Web podem quebrar com mudanças no site (ficam em `config/whatsapp_selectors.json`).
- O Ollama não pôde ser baixado aqui (proxy bloqueou o GitHub de terceiros); o caminho de IA local foi validado com **llama.cpp server** (mesma API compatível com OpenAI) e Qwen2.5-1.5B. Modelos de 1,5B escolhem ferramentas mal: use ≥3B (`qwen2.5:3b`) no dia a dia.

## Dependências externas (pendentes)
1. **Windows 11 + i5 + 16 GB:** rodar `scripts\install.ps1 -Voice` e a lista de verificação em [docs/FUNCIONALIDADES.md](docs/FUNCIONALIDADES.md#lista-de-verificação-no-seu-windows).
2. **Chave Anthropic** (opcional) e/ou **Ollama** + `qwen2.5:3b`.
3. **Home Assistant:** URL + token de longa duração.
4. **Ar TCL:** modelo exato + app usado → integração comunitária no HA → `tcl.climate_entity`.
5. **WhatsApp:** escolher modo (Web com QR, ou conta Meta Business).
6. **Alexa:** Nabu Casa ou skill manual (+ Alexa Media Player para anúncios).

## Próximas tarefas
1. Executar a lista de verificação no Windows e registrar os resultados aqui.
2. Rodar `scripts\benchmark.py` no i5 e atualizar o relatório de desempenho.
3. Validar o clipboard Win32 (texto grande, Unicode, CF_HDROP) e a abertura de apps reais.
4. Testar a palavra de ativação com voz real; se não for confiável, treinar o modelo "Jarvis".
5. Conectar o Home Assistant real; depois o TCL.
6. Escolher e validar o modo do WhatsApp.
7. Ativar `autostart` após validar.

## Decisões arquiteturais importantes
- **SQLite único** (FTS5 + vetores em BLOB + grafo relacional): nenhuma instalação extra; 36 ms para buscar em 10 mil memórias.
- **Interpretador determinístico antes da IA:** comandos funcionam offline, sem custo e em cerca de 2 ms.
- **Ferramentas registradas como única forma de agir:** validação estrita, níveis de risco, confirmação humana, modo de emergência e auditoria. A IA não confirma nada e não acessa ferramentas internas.
- **Conteúdo externo é dado não confiável:** depois de ler mensagens ou documentos, qualquer alteração pedida pela IA exige confirmação.
- **Agente local separado** com lista fechada de RPC (clipboard, apps, voz, notificações, WhatsApp Web), autenticado por token protegido por DPAPI.
- **Supervisor Python na sessão do usuário** (sem serviço do Windows e sem admin): instância única, reinício controlado (código 3), recuperação com espera crescente.
- **Claude via SDK oficial** (`claude-opus-5-5`, esforço `low`, fallback de recusa no servidor), histórico append-only dentro do turno; Ollama/LM Studio via API compatível com OpenAI.
- **Embeddings por hashing como padrão** (funciona em qualquer PC); embeddings neurais via Ollama são opcionais, com reindexação.
- **Segredos:** Fernet com chave-mestra protegida por DPAPI; itens sensíveis do clipboard cifrados, fora do índice e da IA.

## Onde está cada coisa
- Backend: `backend/app` (ver [docs/ARQUITETURA.md](docs/ARQUITETURA.md)).
- Agente: `desktop/jarvis_agent`.
- Interface: `frontend/src`.
- Scripts: `scripts/` (`jarvisctl.py` é o núcleo; os `.ps1` são atalhos para Windows).
- Configuração de permissões: `config/jarvis.example.toml` → copie para `config/jarvis.toml`.
- Dados (não versionados): `data/`.
