# Guia de configuração da IA

O JARVIS funciona em quatro níveis, do mais simples ao mais capaz:

| Modo (`ai.mode`) | O que usa | Quando escolher |
|---|---|---|
| `rules_only` | só o interpretador pt-BR (offline) | máxima privacidade, sem custo; comandos conhecidos |
| `local_only` | Ollama no próprio PC | privacidade e uso offline; respostas mais simples |
| `local_first` | Ollama e, se cair, nuvem | equilíbrio entre privacidade e qualidade |
| `remote_first` (padrão) | Claude e, se cair, Ollama | melhor qualidade em pedidos livres |
| `remote_only` | só nuvem | — |

Em **todos os modos**, os comandos reconhecidos pelo interpretador (clipboard, tarefas, casa, rotinas…) são executados sem IA. A IA entra apenas nos pedidos livres e nos resumos.

## Claude (Anthropic) — nuvem

1. Crie uma chave em https://console.anthropic.com (é necessário ter créditos na conta).
2. No painel: **Configurações → IA → Chaves de API → Anthropic** → cole e salve. A chave fica cifrada (DPAPI) e nunca volta pela API.
3. Modelo padrão: `claude-opus-5-5` (US$ 4 / US$ 20 por milhão de tokens de entrada/saída) com esforço `low`, que reduz custo e latência em conversas e comandos. Para gastar menos, use `claude-haiku-5-5` (US$ 0,10 / US$ 0,50) ou `claude-sonnet-5-5` (US$ 2 / US$ 10).
4. Clique em **Testar conexão**.

Recursos usados: chamada de ferramentas (tool use) com o registro do JARVIS, fallback de recusa no servidor (`fallbacks: "default"`) nos modelos que o suportam e histórico append-only dentro do turno. Os preços acima foram consultados em outubro de 2026; confira em https://www.anthropic.com/pricing.

### Controle de custos
- `ai.daily_token_limit` (padrão 300 mil tokens/dia) e `ai.monthly_budget_usd` (padrão US$ 10): ao atingir um deles, a nuvem é bloqueada e o JARVIS usa o próximo provedor ou o modo offline, avisando o motivo.
- **Configurações → IA → Estado e uso** mostra chamadas, tokens, custo estimado e latência por dia. As métricas não guardam conteúdo.
- `ai.send_memory_to_remote = false` impede que trechos da memória sejam enviados à nuvem (o pedido em si ainda é enviado).

## Ollama — IA local

1. Instale: https://ollama.com/download (Windows).
2. Baixe um modelo pequeno com suporte a ferramentas:
   ```powershell
   ollama pull qwen2.5:3b        # ~2 GB de RAM; bom em português e em chamar ferramentas
   # alternativas: llama3.2:3b, qwen2.5:7b (mais lento em CPU, ~5 GB)
   ```
3. **Configurações → IA**: `local_model = qwen2.5:3b`, `local_url = http://127.0.0.1:11434`.

Expectativa em i5 sem GPU: modelos de 3B parâmetros geram aproximadamente 8 a 15 tokens/s, ou seja, de 3 a 10 s por resposta curta. Modelos de 7B ficam de 2 a 3 vezes mais lentos. Não carregue modelos maiores que 7B com 16 GB de RAM. **Estes números são estimativas, não foram medidos no seu hardware**; registre os reais com `scripts\benchmark.py` depois de instalar.

### Embeddings semânticos locais
O padrão (`hash`) não exige modelo: ele captura semelhança de palavras (plural, acentos, palavras compostas). Para semântica real em português:
```powershell
ollama pull paraphrase-multilingual    # ~560 MB, multilíngue
```
Em **Configurações → IA**: `embedding_provider = ollama`, `embedding_model = paraphrase-multilingual`. Depois, em **Memória → Reindexar tudo**. Alternativas: `bge-m3` (melhor, cerca de 1,2 GB) e `nomic-embed-text` (mais voltado ao inglês).

## Provedor compatível com OpenAI
`remote_provider = openai_compat`, `openai_base_url` e `openai_model`, mais a chave em **Chaves de API**. Funciona com qualquer serviço que implemente `/v1/chat/completions` com ferramentas.

## Garantias de segurança (valem para qualquer provedor)
- A IA só enxerga as ferramentas registradas. Uma ferramenta inexistente é rejeitada e auditada; ferramentas internas (como `emergency_resume`) não podem ser chamadas pela IA.
- Argumentos passam por validação estrita e campos extras são rejeitados.
- Ações de nível 3 ou 4 exigem confirmação do usuário. Depois de ler conteúdo externo (mensagens, documentos), qualquer alteração pedida pela IA também exige confirmação.
- Conteúdo de mensagens e documentos chega à IA dentro de `<dados_nao_confiaveis>`, com instrução explícita para não segui-lo.
- Itens sensíveis do clipboard nunca vão para a IA, a menos que você mude `privacy.clipboard_sensitive_to_ai`.
