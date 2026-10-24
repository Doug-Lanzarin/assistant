# JARVIS — assistente pessoal com IA, automação residencial e segundo cérebro

JARVIS é um assistente pessoal **local** para Windows. Ele conversa por texto e voz em português, executa ações autorizadas no computador, controla a casa pelo Home Assistant, trabalha com o WhatsApp dentro do que as plataformas permitem e funciona como **segundo cérebro**, com memória de longo prazo, busca semântica, documentos, projetos, grafo de relações e memória da área de transferência.

> **Estado do projeto:** o software está implementado e testado em ambiente Linux de desenvolvimento, com 217 testes de backend e 36 de interface. Os itens que dependem do seu Windows, das suas contas ou dos seus dispositivos estão marcados como **pendentes de validação externa** em [PROJECT_STATUS.md](PROJECT_STATUS.md). Leia esse arquivo antes de considerar algo "pronto".

## Interface

A tela inicial é um **orb holográfico** que reage ao áudio real: aos anéis durante a escuta e ao tamanho do núcleo durante a fala ([docs/ORB.md](docs/ORB.md)). As demais telas cobrem o painel, a conversa, o segundo cérebro, o clipboard, a casa, o WhatsApp e as configurações.

![JARVIS falando](docs/media/orb-falando.png)

## O que ele faz

| Área | Exemplos de comando |
|---|---|
| Clipboard inteligente | "salve o que copiei como consulta SQL de coletas" · "copie a consulta SQL de coletas" · "liste meus comandos Git salvos" |
| Segundo cérebro | "anote a ideia de um app de receitas no projeto Cozinha" · "o que fiz ontem?" · "quais decisões tomei sobre o JARVIS?" · "esqueça …" |
| Tarefas e lembretes | "crie um lembrete para revisar o código amanhã às 9" · "quais tarefas estão pendentes?" |
| Computador | "abra o VS Code" · "abra meu projeto de APIs" · "mostre o uso de memória" · "execute minha rotina de início do trabalho" |
| Casa | "ajuste o ar para 23 graus" · "desligue as luzes da sala" · "qual a temperatura da sala?" · "estou saindo de casa" |
| WhatsApp | "leia minhas mensagens" · "mande uma mensagem para o João dizendo que estou chegando" (sempre com confirmação) |
| Segurança | "parar tudo" desativa todas as ações; "retomar operações" reativa |

Os comandos acima funcionam **sem IA e sem internet**, por meio de um interpretador determinístico em português. Com um modelo configurado (Claude na nuvem ou Ollama local), o JARVIS também atende pedidos livres e escolhe sozinho as ferramentas registradas, sempre sob as mesmas regras de permissão.

## Instalação e uso (Windows 10/11)

**Primeira execução**

1. Baixe o projeto e abra a pasta do JARVIS (de preferência num caminho sem acentos, como `C:\JARVIS`).
2. Dê dois cliques em **`setup.bat`**. Ele verifica o Windows, instala o que faltar (Python 3.12 e Node.js LTS pelo `winget`, sempre perguntando antes), prepara tudo e testa se o JARVIS consegue iniciar. Leva de 5 a 15 minutos na primeira vez.
3. Se quiser IA para perguntas livres, adicione depois a chave da Anthropic em **Configurações → IA** (fica cifrada) ou no arquivo `.env`. Sem chave, os comandos diretos funcionam offline.
4. Se o instalador mostrar itens com **FALHA**, siga a instrução que aparece ao lado e execute o `setup.bat` de novo. Ele continua de onde parou e não refaz o que já está pronto.

**Execuções seguintes**

- Dê dois cliques em **`start.bat`**. Quando aparecer "JARVIS pronto", o navegador abre no AI Voice Orb (`http://127.0.0.1:8765/#/jarvis`). O menu das outras telas fica no botão ☰, no canto superior esquerdo.
- Para encerrar, aperte **Ctrl+C** na janela do JARVIS (ou feche a janela).

No primeiro acesso, você cria o usuário e a senha do painel. Isso só é possível a partir do próprio computador. Depois disso:

1. Edite `config\jarvis.toml` com seus apps, sites, projetos, pastas permitidas e rotinas, e clique em **Sistema → Recarregar**.
2. **Configurações → Integrações**: Home Assistant (URL e token), entidade do ar TCL e modo do WhatsApp.
3. Depois de validar que tudo funciona, `scripts\autostart.ps1 -Enable` faz o JARVIS iniciar com o Windows, sem precisar de administrador.

Requisitos, opções do instalador (`-NoVoice`, `-Ollama`, `-WhatsApp`, `-Tests`…), espaço em disco, variáveis de ambiente e o que fazer quando algo dá errado estão em **[docs/INSTALACAO.md](docs/INSTALACAO.md)**.

## Comandos do dia a dia

| Ação | Comando |
|---|---|
| Iniciar com logs na janela (recomendado) | `start.bat` (Ctrl+C encerra) |
| Iniciar em segundo plano / parar / reiniciar | `scripts\start.ps1` · `scripts\stop.ps1` · `scripts\restart.ps1` |
| Reconfigurar / atualizar dependências | `setup.bat` (só refaz o que mudou; `-Force` refaz tudo) |
| Estado | `scripts\status.ps1` |
| Diagnóstico completo | `scripts\diagnose.ps1` |
| Testes | `scripts\test.ps1` |
| Backup / restauração | `scripts\backup.ps1` · `scripts\restore.ps1 -File data\backups\...zip` |
| Início automático | `scripts\autostart.ps1 -Enable` / `-Disable` |
| Medir desempenho | `backend\.venv\Scripts\python scripts\benchmark.py` |

Todos chamam `scripts/jarvisctl.py`, que também funciona em Linux/macOS para desenvolvimento.

## Estrutura

```
setup.bat           configuração inicial (dois cliques; pode repetir)
start.bat           inicia o JARVIS (dois cliques; Ctrl+C encerra)
.env.example        modelo de variáveis de ambiente (o .env real não é versionado)
backend/            API FastAPI, orquestrador, memória, integrações, testes
  app/api/          rotas HTTP e WebSocket
  app/orchestrator/ interpretador pt-BR, registro de ferramentas, política, executor, orquestrador
  app/providers/    Claude (SDK oficial), compatível OpenAI/Ollama, embeddings
  app/memory/       segundo cérebro: memórias, índice híbrido, documentos, grafo, consolidação
  app/clipboard_memory/  memória da área de transferência
  app/integrations/ Home Assistant (+TCL/Alexa), WhatsApp, ponte com o agente
  app/tools/        ferramentas registradas (a única forma de o sistema agir)
  app/security/     autenticação, segredos (DPAPI), detecção de dados sensíveis
desktop/jarvis_agent/  agente local do Windows: clipboard Win32, apps, voz, notificações, WhatsApp Web
frontend/           PWA React + TypeScript
scripts/            setup.ps1 + jarvis_setup.py (instalador), jarvisctl.py (supervisor), diagnóstico, benchmark
config/             jarvis.example.toml (permissões: apps, pastas, rotinas, dispositivos)
docs/               guias e relatórios
data/               criado pelo setup: banco, logs, segredos, backups, modelos de voz (NUNCA versionado)
```

## Documentação

- [Instalação, requisitos e recuperação](docs/INSTALACAO.md) · [Arquitetura e fluxos](docs/ARQUITETURA.md) · [Interface de voz (orb)](docs/ORB.md)
- Guias: [IA](docs/IA.md) · [Voz](docs/VOZ.md) · [Segundo cérebro](docs/SEGUNDO_CEREBRO.md) · [Clipboard](docs/CLIPBOARD.md) · [Home Assistant](docs/HOME_ASSISTANT.md) · [Alexa](docs/ALEXA.md) · [Ar-condicionado TCL](docs/TCL.md) · [WhatsApp](docs/WHATSAPP.md)
- [Segurança e privacidade](docs/SEGURANCA.md) · [Backup e restauração](docs/BACKUP.md)
- [Relatório de testes](docs/RELATORIO_TESTES.md) · [Relatório de desempenho](docs/RELATORIO_DESEMPENHO.md)
- [Funcionalidades, limitações e pendências](docs/FUNCIONALIDADES.md) · [Manutenção e evolução](docs/MANUTENCAO.md)
- [PROJECT_STATUS.md](PROJECT_STATUS.md): estado atual, decisões e próximos passos

## Desenvolvimento

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q            # 217 testes
cd ../frontend && npm ci && npm test && npm run build
python scripts/jarvisctl.py start --dev  # backend com recarga + agente
cd frontend && npm run dev               # interface em http://127.0.0.1:5173 (proxy para a API)
```
