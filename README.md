# JARVIS — assistente pessoal com IA, automação residencial e segundo cérebro

JARVIS é um assistente pessoal **local** para Windows. Ele conversa por texto e voz em português, executa ações autorizadas no computador, controla a casa pelo Home Assistant, trabalha com o WhatsApp dentro do que as plataformas permitem e funciona como **segundo cérebro**, com memória de longo prazo, busca semântica, documentos, projetos, grafo de relações e memória da área de transferência.

> **Estado do projeto:** o software está implementado e testado em ambiente Linux de desenvolvimento, com 151 testes de backend e 10 de interface. Os itens que dependem do seu Windows, das suas contas ou dos seus dispositivos estão marcados como **pendentes de validação externa** em [PROJECT_STATUS.md](PROJECT_STATUS.md). Leia esse arquivo antes de considerar algo "pronto".

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

## Requisitos

- Windows 10 ou 11, 8 GB de RAM ou mais (o projeto foi dimensionado para i5 com 16 GB e sem GPU).
- Python 3.12 (recomendado) ou 3.11. O Python 3.13 funciona, exceto que o openWakeWord ≥ 0.6 ainda não publica pacotes para ele.
- Node.js LTS, apenas para compilar a interface.
- Opcional: [Ollama](https://ollama.com) para IA local, chave da API Anthropic para IA na nuvem, Home Assistant para a casa.

## Instalação (Windows)

```powershell
git clone https://github.com/Doug-Lanzarin/assistant.git
cd assistant
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Voice   # -WhatsApp para o WhatsApp Web
scripts\start.ps1                                                     # abre http://127.0.0.1:8765
```

No primeiro acesso você cria o usuário e a senha do painel (somente a partir do próprio computador). Depois:

1. **Configurações → IA**: escolha o modo e, se quiser, cole a chave da Anthropic. Ela fica cifrada com DPAPI.
2. Edite `config\jarvis.toml` com seus apps, sites, projetos, pastas permitidas e rotinas, e clique em **Sistema → Recarregar**.
3. **Configurações → Integrações**: Home Assistant (URL + token), entidade do ar TCL e modo do WhatsApp.
4. Depois de validar que tudo funciona: `scripts\autostart.ps1 -Enable` (inicia com o Windows, sem precisar de administrador).

## Comandos do dia a dia

| Ação | Comando |
|---|---|
| Iniciar / parar / reiniciar | `scripts\start.ps1` · `scripts\stop.ps1` · `scripts\restart.ps1` |
| Estado | `scripts\status.ps1` |
| Diagnóstico completo | `scripts\diagnose.ps1` |
| Testes | `scripts\test.ps1` |
| Backup / restauração | `scripts\backup.ps1` · `scripts\restore.ps1 -File data\backups\...zip` |
| Início automático | `scripts\autostart.ps1 -Enable` / `-Disable` |
| Medir desempenho | `backend\.venv\Scripts\python scripts\benchmark.py` |

Todos chamam `scripts/jarvisctl.py`, que também funciona em Linux/macOS para desenvolvimento.

## Estrutura

```
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
scripts/            instalação, supervisor, diagnóstico, benchmark (PowerShell + Python)
config/             jarvis.example.toml (permissões: apps, pastas, rotinas, dispositivos)
docs/               guias e relatórios
data/               banco, logs, backups, modelos (NUNCA versionado)
```

## Documentação

- [Arquitetura e fluxos](docs/ARQUITETURA.md)
- Guias: [IA](docs/IA.md) · [Voz](docs/VOZ.md) · [Segundo cérebro](docs/SEGUNDO_CEREBRO.md) · [Clipboard](docs/CLIPBOARD.md) · [Home Assistant](docs/HOME_ASSISTANT.md) · [Alexa](docs/ALEXA.md) · [Ar-condicionado TCL](docs/TCL.md) · [WhatsApp](docs/WHATSAPP.md)
- [Segurança e privacidade](docs/SEGURANCA.md) · [Backup e restauração](docs/BACKUP.md)
- [Relatório de testes](docs/RELATORIO_TESTES.md) · [Relatório de desempenho](docs/RELATORIO_DESEMPENHO.md)
- [Funcionalidades, limitações e pendências](docs/FUNCIONALIDADES.md) · [Manutenção e evolução](docs/MANUTENCAO.md)
- [PROJECT_STATUS.md](PROJECT_STATUS.md): estado atual, decisões e próximos passos

## Desenvolvimento

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q            # 151 testes
cd ../frontend && npm ci && npm test && npm run build
python scripts/jarvisctl.py start --dev  # backend com recarga + agente
cd frontend && npm run dev               # interface em http://127.0.0.1:5173 (proxy para a API)
```
