# Manutenção e evolução

## Rotina
| Frequência | Tarefa |
|---|---|
| diária (automática) | consolidação de memórias; rotação de logs (5 × 2 MB) |
| semanal | revisar inferências (Segundo cérebro → Consolidação) e a Auditoria |
| semanal | backup copiado para fora do notebook |
| mensal | `scripts\diagnose.ps1`; atualizar dependências e rodar `scripts\test.ps1` |

## Atualizar dependências
```powershell
scripts\stop.ps1
backend\.venv\Scripts\pip install -U -r backend\requirements.txt -r backend\requirements-desktop.txt
cd frontend; npm update; npm run build; cd ..
scripts\test.ps1
scripts\start.ps1
```
Versões fixadas que merecem atenção: `anthropic` (SDK oficial; mudanças de modelo/API), `av<16` (compatibilidade com o faster-whisper) e `openwakeword` (a API mudou entre 0.4 e 0.6; o código suporta as duas).

## Logs e diagnóstico
- `data\logs\jarvis.log`: backend (JSON por linha, segredos mascarados).
- `data\logs\agent.log`: agente local.
- `data\logs\supervisor.log`: inícios, quedas e reinícios.
- `scripts\diagnose.ps1`: dependências, banco (`integrity_check`), porta, disco e últimos erros.

## Como estender
### Nova ferramenta
1. Crie a função em `backend/app/tools/<area>_tools.py` com parâmetros `ToolParams` (Pydantic, `extra=forbid`).
2. Registre `Tool(name, description, Params, handler, Risk.X, "permissao.nome", categoria, timeout=..., summarize=..., prepare=...)`.
3. Escolha o risco com cuidado (1 leitura · 2 reversível · 3 externo · 4 irreversível). Use `prepare` para resolver ambiguidades antes da confirmação e `risk_fn` quando o risco depender dos argumentos.
4. Opcional: adicione uma regra em `orchestrator/intents.py` para funcionar offline e um caso em `tests/test_intents.py`.
5. Teste em `backend/tests/`.

### Nova capacidade no agente
Adicione o método em `desktop/jarvis_agent/rpc.py` (`self.methods`), valide **todos** os parâmetros e nunca aceite comandos de shell. Informe a capacidade em `Dispatcher.info()`.

### Novo provedor de IA
Implemente o protocolo `LLMProvider` (`start`, `step`, `add_tool_results`, `available`, `tool_format`) em `backend/app/providers/` e inclua-o em `ProviderManager.chain()`.

### Migrações de banco
Crie `backend/app/migrations/000N_descricao.sql`. Ela é aplicada automaticamente na inicialização e na restauração de backups.

## Evoluções sugeridas
1. Modelo de ativação "Jarvis" treinado com a sua voz (openWakeWord).
2. Embeddings neurais por padrão quando o Ollama estiver presente (detecção automática + reindexação).
3. Índice ANN (`sqlite-vec`) quando o acervo passar de cerca de 200 mil trechos.
4. Clipboard de imagens (PNG em `data/library`, OCR opcional).
5. Instalador MSIX/Inno Setup para o agente (também destrava a API de notificações).
6. Calendário (Google/Outlook) como fonte de memória prospectiva.
7. HTTPS local (certificado de `mkcert`) para uso pelo celular sem Tailscale.
