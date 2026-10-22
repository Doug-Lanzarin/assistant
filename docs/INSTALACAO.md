# Instalação, inicialização e recuperação

Dois arquivos na raiz do projeto cuidam de tudo:

| Arquivo | Quando usar | O que faz |
|---|---|---|
| `setup.bat` | primeira vez, depois de atualizar o projeto, ou quando algo der errado | verifica o Windows, instala o que falta, prepara a configuração e testa se o JARVIS inicia |
| `start.bat` | sempre que quiser usar o JARVIS | confere a configuração e inicia o banco, a API, a interface (AI Voice Orb) e o agente local |

Os dois funcionam com dois cliques e de qualquer pasta, porque localizam sozinhos a raiz do projeto. Também aceitam caminhos com espaços e parênteses. Mesmo assim, prefira um caminho curto e sem acentos, como `C:\JARVIS`.

## Requisitos

| Item | Mínimo | Recomendado (seu PC) | Instalação automática |
|---|---|---|---|
| Windows | 10 versão 1809 (build 17763), 64 bits | Windows 11 | — |
| RAM | 8 GB | 16 GB | — |
| CPU / GPU | qualquer x64 / não precisa | i5 / sem GPU dedicada | — |
| Python | 3.11 | **3.12** (no 3.13 a palavra de ativação usa a versão 0.4 do openWakeWord) | `winget install Python.Python.3.12` (por usuário, sem administrador) |
| Node.js + npm | 20 | LTS atual | `winget install OpenJS.NodeJS.LTS` (o Windows pede permissão de administrador **só para esse instalador**) |
| Visual C++ Runtime | — | já vem no Windows 11 | `winget install Microsoft.VCRedist.2015+.x64`, somente se faltar e a voz local estiver ativada |
| Git | opcional | — | não é instalado; serve só para atualizar o projeto |
| Ollama (IA local) | opcional | — | só com `setup.bat -Ollama` |

O `setup.bat` **pergunta antes** de cada instalação pelo `winget` (fonte oficial da Microsoft). Para não ser perguntado, use `setup.bat -Yes`. Se o `winget` não existir, o instalador mostra o comando ou o site oficial para instalar à mão.

### Espaço em disco (medido)
| Componente | Tamanho |
|---|---|
| Ambiente Python com voz local (`backend\.venv`) | ~800 MB (sem voz: ~200 MB) |
| Pacotes da interface (`frontend\node_modules`) | ~130 MB |
| Modelos de voz: Piper pt-BR + Whisper base (`data\models`) | ~200 MB |
| **Total padrão** | **~1,1 GB** (medido em Linux; no Windows é semelhante) |
| WhatsApp Web (`-WhatsApp`): Playwright + Chromium | +~300 MB |
| IA local (`-Ollama`): Ollama + `qwen2.5:3b` | +~1 GB + ~1,9 GB |

Os modelos de IA local **não são baixados por padrão**. O `qwen2.5:3b` usa cerca de 2,5 GB de RAM e responde em alguns segundos num i5 sem GPU. Modelos maiores, de 7B ou mais, ficam lentos nesse hardware.

## `setup.bat`

```
setup.bat [-NoVoice] [-WhatsApp] [-Ollama] [-Tests] [-Force] [-Offline] [-Yes]
```

| Opção | Efeito |
|---|---|
| *(nenhuma)* | instalação padrão: backend, agente, interface e voz local |
| `-NoVoice` | não instala faster-whisper, Piper nem openWakeWord. O navegador continua falando com a voz do sistema, mas comandos falados não são transcritos |
| `-WhatsApp` | instala o adaptador WhatsApp Web (Playwright e Chromium) |
| `-Ollama` | instala o Ollama pelo `winget` e baixa o modelo local configurado (`qwen2.5:3b`) |
| `-Tests` | instala as ferramentas de teste e roda a suíte do backend; falhas impedem a conclusão |
| `-Force` | reinstala as dependências e recompila a interface, **sem apagar dados nem configurações** |
| `-Offline` | não baixa os modelos de voz |
| `-Yes` | não pergunta antes de instalar programas com o `winget` |

As opções ficam salvas. Se você usou `-WhatsApp` uma vez, as próximas execuções continuam mantendo o WhatsApp.

### O que ele faz, em ordem
1. **Sistema operacional:** versão, build, 64 bits, CPU e RAM. Avisa se estiver rodando como Administrador, o que não é necessário.
2. **Dependências do sistema:**
   - Python 3.11–3.13 (prefere o 3.12 e ignora o atalho da Microsoft Store);
   - Node.js 20+ com npm;
   - Git;
   - Visual C++ Runtime;
   - Ollama, quando pedido.
3. **Ambiente virtual** `backend\.venv`. Se estiver quebrado (Python removido ou pasta movida), o ambiente antigo é **renomeado** para `.venv.old-DATA`, nunca apagado, e um novo é criado.
4. **Diretórios** em `data\`: `logs`, `secrets`, `backups`, `library` (documentos) e `models` (modelos de voz).
5. **Dependências Python** (`backend\requirements*.txt`):
   - Se um pacote opcional não tiver versão para o seu Python, os demais são instalados mesmo assim.
   - O openWakeWord tem uma alternativa já validada, a versão 0.4.0.
6. **Interface:** `npm ci` e `npm run build` em `frontend\`, o que inclui o AI Voice Orb.
7. **Configuração:**
   - Cria `config\jarvis.toml` e `.env` a partir dos modelos **apenas se não existirem**.
   - Valida o `jarvis.toml`.
   - Avisa se `JARVIS_HOST` expõe o JARVIS na rede.
8. **Banco de dados:** cria ou abre `data\jarvis.db`, aplica as migrações pendentes e roda `PRAGMA integrity_check`.
9. **IA híbrida:**
   - Mostra o modo atual (padrão `remote_first`: nuvem primeiro, local como reserva).
   - Informa se há chave da nuvem, sem mostrar o valor.
   - Detecta se o Ollama está instalado, em execução e com o modelo baixado.
10. **Voz e microfone:**
    - Confere os pacotes de voz e baixa os modelos (Piper pt-BR e Whisper base, uma vez só).
    - Lê a permissão de microfone do Windows (Privacidade → Microfone) e lista os dispositivos de entrada.
    - **O microfone não é ligado.**
11. **Testes de integridade:**
    - O agente local carrega.
    - O backend **inicia de verdade** numa porta temporária e responde em `/api/health`, com o banco ok.
    - A interface é servida e a API recusa acesso sem login (401).
    - Com `-Tests`, roda também a suíte completa.
12. **Resultado:**
    - Grava `data\setup-report.json` e o relatório `data\logs\setup-AAAAMMDD-HHMMSS.log`.
    - Só quando **todos os itens obrigatórios** passam, grava o indicador `data\setup-complete.json`.

### Idempotência e retomada
- Cada etapa demorada guarda a impressão digital (SHA-256) do que instalou em `data\setup-state.json`. Numa nova execução, refaz só o que mudou.
- Exemplo medido: a segunda execução sem mudanças leva cerca de 7 segundos, contra 2 a 3 minutos na primeira.
- O indicador de conclusão é removido no início de cada execução e só volta no fim, se tudo der certo. Assim, uma execução interrompida (Ctrl+C, falha ou queda de energia) nunca deixa o JARVIS marcado como configurado.
- A etapa interrompida é refeita na próxima vez; as etapas já concluídas não são.
- O `.env`, o `config\jarvis.toml`, o banco, os segredos e os backups **nunca são sobrescritos nem apagados**.

### Mensagens e códigos de saída
`[OK]` passou · `[AVISO]` recurso opcional indisponível (o JARVIS funciona sem ele) · `[FALHA]` obrigatório; a instrução de correção aparece logo abaixo · `[INFO]` informação · `[PULADO]` não se aplica.

| Código | Significado |
|---|---|
| 0 | configuração concluída |
| 1 | algum item obrigatório falhou (veja o relatório) |
| 2 | falta Python ou Node.js e não foi possível instalar |
| 3 | sistema operacional não suportado |
| 130 | interrompido pelo usuário |

O `setup.bat` só declara sucesso quando o próprio JARVIS confirma que está pronto (`jarvisctl setup-status`), além do código 0 do instalador.

## `start.bat`

```
start.bat [--no-browser] [--no-agent] [--whatsapp-web]
```

1. Localiza a raiz do projeto e ativa o ambiente virtual.
2. Verifica se a configuração foi concluída (`data\setup-complete.json`), se as dependências não mudaram desde então, se a interface está compilada e se os pacotes essenciais carregam. Se faltar algo, pede para executar o `setup.bat`.
3. Carrega o `.env`. As variáveis já definidas no Windows têm prioridade.
4. Verifica a porta:
   - Se **este** JARVIS já estiver rodando, apenas abre o navegador.
   - Se outro programa ocupar a porta, informa qual é e sugere `JARVIS_PORT`.
5. Inicia na ordem: **banco e API** (backend), depois a **interface** (servida pelo backend) e, por fim, o **agente local** (voz, clipboard, apps, notificações). O agente só sobe depois que o backend responde.
6. A interface só é anunciada como pronta quando o backend responde **e** serve a página. Nesse momento, o navegador abre em `/#/jarvis`.
7. Os logs aparecem na janela com prefixo (`[backend]`, `[agente]`) e também ficam em `data\logs\` (`jarvis.log`, `agent.log`, `supervisor.log`), com segredos mascarados.
8. Se o backend ou o agente caírem, o supervisor os reinicia, com espera crescente.
9. **Para encerrar:** Ctrl+C. O supervisor encerra o agente e depois o backend. Se a janela for fechada, o Windows encerra os processos junto com ela (Job Object), e nada fica rodando escondido.

Não instala nada e não apaga dados.

> **Notas do terminal:** pelo terminal, chame os scripts como `.\setup.bat` e `.\start.bat`, com `.\` na frente. Sem ele, alguns interpretadores (o `cmd` do Wine, por exemplo) confundem `start.bat` com o comando interno `start`; com dois cliques isso não acontece. Depois do Ctrl+C, o `cmd` pode perguntar "Deseja finalizar o arquivo em lotes (S/N)?": a essa altura o JARVIS já foi encerrado, então tanto faz a resposta. Para rodar em segundo plano, sem janela, use `scripts\start.ps1`, e `scripts\stop.ps1` para parar.

## Variáveis de ambiente (`.env`)

| Variável | Padrão | Uso |
|---|---|---|
| `JARVIS_ENV` | `production` | `development` liga recarga automática e logs no terminal |
| `JARVIS_HOST` | `127.0.0.1` | mantenha local; não exponha à rede nem à internet |
| `JARVIS_PORT` | `8765` | porta da API e da interface |
| `JARVIS_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `JARVIS_LOG_CONSOLE` | (start.bat: `1`) | logs também no terminal |
| `JARVIS_DATA_DIR` | `.\data` | banco, logs, segredos, backups, modelos |
| `JARVIS_CONFIG_FILE` | `.\config\jarvis.toml` | permissões (apps, pastas, rotinas, dispositivos) |
| `ANTHROPIC_API_KEY` | — | IA na nuvem (alternativa a Configurações → IA) |
| `OPENAI_API_KEY` | — | provedor compatível com OpenAI |
| `JARVIS_HA_URL` / `JARVIS_HA_TOKEN` | — | Home Assistant (alternativa a Configurações → Integrações) |

**Chaves de API:** o recomendado é cadastrá-las na interface, onde ficam cifradas com DPAPI na sua conta do Windows. No `.env`, ficam em texto puro. O instalador nunca cria chaves fictícias, nunca exibe valores e nunca os grava nos logs.

A IA local (endereço do Ollama e modelo) e a escolha do modo híbrido ficam em **Configurações → IA**, e não no `.env`.

## Recuperação

| Problema | O que fazer |
|---|---|
| `setup.bat` mostra FALHA | siga a instrução ao lado do item e execute de novo; o detalhe completo está no relatório `data\logs\setup-*.log` |
| "Python/Node.js não encontrado" depois de instalar | feche a janela e abra o `setup.bat` de novo, para o PATH ser atualizado |
| Instalação interrompida | execute `setup.bat` de novo; ele continua de onde parou |
| Dependências corrompidas ou estranhas | `setup.bat -Force` (não apaga dados) |
| Ambiente virtual quebrado (pasta movida, Python removido) | `setup.bat`: o ambiente antigo é renomeado para `backend\.venv.old-…` e um novo é criado; depois de confirmar que tudo funciona, você pode apagar a pasta antiga |
| `start.bat`: "a configuração inicial não foi concluída" ou "as dependências mudaram" | execute `setup.bat` (normal depois de atualizar o projeto) |
| `start.bat`: "porta ocupada" | feche o programa indicado ou defina outra porta em `JARVIS_PORT` no `.env` |
| `start.bat`: "já em execução" | ele só abre o navegador; para parar a instância anterior, use `scripts\stop.ps1` |
| A interface não abre | veja `data\logs\jarvis.log`; teste com `scripts\diagnose.ps1` |
| Microfone não funciona | Configurações do Windows → Privacidade e segurança → Microfone: ative o acesso e "Permitir que aplicativos da área de trabalho…"; no navegador, permita o microfone para `127.0.0.1` |
| Banco corrompido (falha na integridade) | `scripts\restore.ps1 -File data\backups\<arquivo>.zip` (ver [BACKUP.md](BACKUP.md)) |
| Antivírus bloqueou algo | não desative o Windows Defender; libere apenas o arquivo indicado, se souber que ele é do projeto |

## O que foi testado

Detalhes em [RELATORIO_TESTES.md](RELATORIO_TESTES.md#instalador-e-inicialização).

- **Executado de verdade:**
  - o fluxo Python completo (`jarvisctl setup` e `run`) numa cópia limpa do projeto em Linux, num caminho com espaços, parênteses, `&` e acentos;
  - o `setup.ps1` no PowerShell 7 (análise sintática, recusa fora do Windows com código 3 e funções auxiliares);
  - o `setup.bat` e o `start.bat` no `cmd` do Wine.
- **Não executado:** no Windows real. Faltam o `winget`, a instalação do Python e do Node.js, o Job Object ao fechar a janela, a leitura da permissão de microfone no registro e o PowerShell 5.1. Esses itens estão em [FUNCIONALIDADES.md](FUNCIONALIDADES.md#lista-de-verificação-no-seu-windows).
