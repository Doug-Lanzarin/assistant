# Funcionalidades, limitações e pendências

Legenda: ✅ implementado e testado automaticamente · 🧪 implementado e testado com simulador · 🪟 implementado, aguarda teste no Windows · 🔌 implementado, aguarda conta/dispositivo externo · ⚠️ limitação conhecida

## Critérios de aceitação (seção 20 do enunciado)
| # | Critério | Situação |
|---|---|---|
| 1 | Inicia no Windows seguindo a documentação | 🪟 scripts prontos (sintaxe verificada); supervisor testado em Linux |
| 2 | Painel funciona de verdade | ✅ testado no navegador contra o backend real |
| 3 | Conversação por texto | ✅ |
| 4 | Modelo de IA integrado | 🧪 Claude (SDK oficial, formato validado) e Ollama/compatível OpenAI; 🔌 chave e modelo reais |
| 5 | Orquestrador executa ferramentas autorizadas | ✅ |
| 6 | Memória persiste entre reinicializações | ✅ |
| 7 | Busca semântica recupera informações relevantes | ✅ (hashing local); 🔌 embeddings neurais via Ollama |
| 8 | Documentos importados consultáveis | ✅ PDF, DOCX, MD, TXT, código |
| 9 | Relaciona informações e projetos | ✅ grafo + visão de projeto |
| 10 | Memórias corrigidas e excluídas | ✅ com remoção dos índices derivados |
| 11 | Clipboard salvo por comando | ✅ (despachante real do agente); 🪟 API Win32 |
| 12 | Conteúdo salvo encontrado por linguagem natural | ✅ |
| 13 | Conteúdo original copiado de volta | ✅ byte a byte; 🪟 Win32 |
| 14 | Operação por voz com alternativa textual | ✅ STT/TTS locais medidos; 🪟 microfone; ⚠️ palavra de ativação não comprovada com voz real |
| 15 | Automação do Windows respeita permissões | ✅ lista de permissões e validações; 🪟 abertura real de apps |
| 16 | Home Assistant consulta e controla dispositivos reais | 🧪 com verificação de estado; 🔌 HA real |
| 17 | Alexa implementada ou bloqueada só por dependência externa | 🔌 via HA (Nabu Casa ou skill) + anúncios `notify.*` |
| 18 | TCL implementada ou tecnicamente delimitada | 🧪 via entidade `climate` do HA; 🔌 integração comunitária e modelo exato |
| 19 | WhatsApp opera dentro dos recursos disponíveis | 🧪 Cloud API e WhatsApp Web; 🪟 notificações; 🔌 contas |
| 20 | Envio exige autorização | ✅ sempre confirma (não configurável) |
| 21 | Ações reportam resultados verdadeiros | ✅ verificação de estado, releitura do clipboard, evidência de envio |
| 22 | Testes essenciais passam | ✅ 158 + 19 |
| 23 | Credenciais protegidas | ✅ Fernet + arquivo 0600 (Linux); 🪟 DPAPI |
| 24 | Backup e restauração funcionam | ✅ |
| 25 | Consumo de recursos documentado | ✅ neste ambiente; 🪟 rodar `benchmark.py` no i5 |
| 26 | Inicialização e encerramento confiáveis | ✅ supervisor (instância única, reinício, recuperação, parada limpa); 🪟 início com o Windows |
| 27 | Documentação permite instalar, configurar e manter | ✅ README + 15 documentos |

## Limitações conhecidas
- ⚠️ **"Jarvis" sozinho como palavra de ativação** não existe pronto; usa-se "Hey Jarvis" (modelo inglês). Ele não detectou a voz portuguesa sintetizada, então é preciso validar com a sua voz. Atalho `Ctrl+Alt+J` e botão como alternativa.
- ⚠️ **Embeddings padrão** (hashing) captam semelhança de palavras, não sinônimos ("finanças" × "gastos" só se houver termos em comum). Para semântica real, ative embeddings do Ollama.
- ⚠️ **WhatsApp pessoal:** sem acesso ao histórico completo. O modo Web depende do HTML do site, que muda sem aviso, e pode contrariar os Termos de Serviço. O modo Notificações pode ser negado pelo Windows a apps não empacotados.
- ⚠️ **Clipboard:** imagens e outros formatos não são salvos (só detectados).
- ⚠️ **TCL:** depende de integração comunitária no Home Assistant; nenhuma API oficial.
- ⚠️ **Alexa:** sem comandos arbitrários aos Echo; anúncios dependem de integração não oficial (Alexa Media Player).
- ⚠️ **Interpretador offline:** cobre os comandos documentados; frases muito diferentes vão para a IA (ou caem na busca, sem IA).
- ⚠️ **Lembretes** disparam apenas com o JARVIS em execução; os atrasados disparam ao iniciar.
- ⚠️ **Busca vetorial por força bruta:** adequada até cerca de 200 mil trechos.
- ⚠️ **Um usuário:** o painel é pessoal (sem perfis múltiplos).

## Configurações externas pendentes (na ordem sugerida)
1. **Windows:** rodar `scripts\install.ps1 -Voice` e a lista de verificação abaixo.
2. **IA:** chave da Anthropic e/ou Ollama + `qwen2.5:3b` (opcional: `paraphrase-multilingual` para embeddings).
3. **Home Assistant:** URL + token de longa duração.
4. **TCL:** modelo exato + app (TCL Home ou Intelligent AC) → integração no HA → `tcl.climate_entity`.
5. **WhatsApp:** escolher o modo (`web` exige `-WhatsApp` + QR; `business` exige conta Meta).
6. **Alexa:** Nabu Casa ou skill manual; Alexa Media Player para anúncios.
7. Depois de validar: `scripts\autostart.ps1 -Enable`.

## Lista de verificação no seu Windows
1. `scripts\install.ps1 -Voice` termina com "tudo certo" no `doctor`.
2. `scripts\test.ps1`: 158 + 19 testes passam no Windows.
3. `scripts\start.ps1` abre o painel → crie o usuário.
4. Painel → cartão JARVIS: "Agente local conectado".
5. Copie um texto no Bloco de Notas → Conversa: "salve o que copiei como teste" → copie outra coisa → "copie teste" → Ctrl+V no Bloco de Notas mostra o texto original.
6. Copie uma chave falsa `sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxx` → salve → o painel mostra "sensível · cifrado".
7. "abra o VS Code" (ajuste o caminho em `config\jarvis.toml` se precisar).
8. Configurações → Voz → "Falar agora" → diga "que horas são".
9. Ligue a palavra de ativação → diga "Hey Jarvis" → teste e ajuste `wake_threshold`.
10. "parar tudo" → "salve o que copiei" é recusado → "retomar operações".
11. `scripts\stop.ps1` → nenhum `python.exe` do JARVIS fica no Gerenciador de Tarefas.
12. `scripts\autostart.ps1 -Enable` → reinicie o Windows → painel acessível.
13. `backend\.venv\Scripts\python scripts\benchmark.py` → anexe o JSON ao relatório de desempenho.
