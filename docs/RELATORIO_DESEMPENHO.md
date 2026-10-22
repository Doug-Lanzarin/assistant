# Relatório de desempenho

> **Importante:** estas medições foram feitas no **ambiente de desenvolvimento em nuvem** (Linux, Intel Xeon 2,8 GHz, 4 vCPU, 15 GB de RAM, sem GPU), **não** no notebook de referência (Windows, Core i5, 16 GB). Servem como ordem de grandeza. Um i5 de notebook costuma ter desempenho por núcleo semelhante ou um pouco menor. Para obter os números reais do seu PC:
> ```powershell
> backend\.venv\Scripts\python scripts\benchmark.py
> ```
> O resultado é salvo em `data\benchmark-<data>.json`.

Data da medição: 2026-10-22 · arquivo de origem: `data/benchmark-20261022-1517.json` (local, não versionado).

## Núcleo (backend)
| Métrica | Resultado |
|---|---|
| Inicialização (serviços + app, banco vazio) | **1,6 s** |
| RAM do processo após iniciar | **115 MB** (Python puro: 25 MB) |
| RAM com 10 mil memórias indexadas | **164 MB** |
| Interpretação de comando (regras pt-BR) | 0,05 ms (p50) · 0,10 ms (p95) |
| Pedido completo sem IA ("que horas são?", com gravação no banco e auditoria) | **2,2 ms** (p50) · 2,7 ms (p95) |
| Inserir memória (com índice FTS, vetor e grafo) | 6,6 ms/item até 1 mil itens · 10,4 ms/item até 10 mil |
| Busca híbrida: 1 mil memórias | **8 ms** (p50) · 11 ms (p95) |
| Busca híbrida: 10 mil memórias | **36 ms** (p50) · 45 ms (p95) |

Leitura: o segundo cérebro aguenta dezenas de milhares de itens com busca abaixo de 0,1 s e sem banco externo. Acima de cerca de 200 mil trechos, vale trocar a busca vetorial por força bruta por um índice ANN (ver [MANUTENCAO.md](MANUTENCAO.md)).

## Voz
### Síntese Piper (pt_BR-faber-medium)
| Frase | Áudio | Tempo de síntese | RTF |
|---|---|---|---|
| 1ª chamada (inclui carga do modelo) | 3,6 s | 2,2 s | 0,62 |
| chamadas seguintes | 3,3–3,4 s | 0,14–0,17 s | **0,04–0,05** |

A fala é gerada cerca de 20 vezes mais rápido que o tempo real depois que o modelo é carregado.

### Transcrição faster-whisper (int8, CPU, sem vocabulário de contexto)
| Modelo | Carga | RAM do processo | RTF médio | WER* |
|---|---|---|---|---|
| tiny | 1,9 s | 514 MB | 0,28 | 0,39 |
| **base** | 1,3 s | 650 MB | 0,34 | 0,39 |
| small | 10,3 s | 1.314 MB | 0,81 | 0,36 |

\*WER sobre frases ditas por **voz sintetizada** (um teste mais difícil que a voz humana). Os erros se concentravam em "Jarvis" ("Já viz", "Tavis") e em "SQL". Com o **vocabulário de contexto** (`voice.stt_prompt` + hotword "Jarvis"), implementado depois da medição, o modelo `base` acertou "Jarvis" nas 5 frases testadas, levando cerca de 1,0 s por frase de 3 s. As variações restantes ("acondicionado", "20 e 3 graus") são corrigidas pelo interpretador e cobertas por testes.

Recomendação para o i5 com 16 GB: `base` (padrão). Use `small` só se a precisão no seu microfone for insuficiente e uma latência de cerca de 2,5 s por frase for aceitável.

### Palavra de ativação (openWakeWord `hey_jarvis`, ONNX)
| Métrica | Resultado |
|---|---|
| Custo por quadro de 80 ms | **3,9 ms** de CPU (≈ 5% de um núcleo, em escuta contínua) |
| Pontuação máxima em 10 s de ruído | 0,002 (nenhum falso positivo) |
| Pontuação com "Hey Jarvis" sintetizado por voz **portuguesa** | 0,038 (**não detectou**; limiar 0,5) |

Conclusão honesta: o custo é baixo, mas a confiabilidade da detecção **não foi comprovada** com fala real. O modelo foi treinado com pronúncia inglesa. Teste com a sua voz e, se necessário, ajuste o limiar ou treine um modelo próprio. Atalho e botão estão sempre disponíveis (ver [VOZ.md](VOZ.md)).

## IA
- **Sem IA (regras):** cerca de 2 ms por pedido; cobre os comandos do dia a dia.
- **Claude (nuvem):** a latência depende da rede e do modelo; não foi medida aqui porque não há chave de API neste ambiente. O painel registra a latência real em Configurações → IA → Estado e uso.
- **Ollama local:** ver a seção abaixo (quando disponível) ou meça no seu PC.

## Consumo estimado em uso diário (i5, 16 GB)
| Cenário | RAM aproximada |
|---|---|
| Backend + agente, sem voz | ~200 MB |
| \+ Whisper `base` carregado | +~550 MB |
| \+ palavra de ativação ativa | +~60 MB, ~5% de um núcleo |
| \+ Ollama com modelo 3B | +~2,5 GB |

Tudo cabe com folga em 16 GB.
