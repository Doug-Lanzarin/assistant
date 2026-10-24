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
| 14 | Operação por voz com alternativa textual | ✅ STT/TTS locais medidos (small+beam 5, ~3% de erro em frases curtas; resposta em ~2,5 s); 🪟 microfone; ⚠️ palavra de ativação não comprovada com voz real |
| 15 | Automação do Windows respeita permissões | ✅ lista de permissões e validações; 🪟 abertura real de apps |
| 16 | Home Assistant consulta e controla dispositivos reais | 🧪 com verificação de estado; 🔌 HA real |
| 17 | Alexa implementada ou bloqueada só por dependência externa | 🔌 via HA (Nabu Casa ou skill) + anúncios `notify.*` |
| 18 | TCL implementada ou tecnicamente delimitada | 🧪 via entidade `climate` do HA; 🔌 integração comunitária e modelo exato |
| 19 | WhatsApp opera dentro dos recursos disponíveis | 🧪 Cloud API e WhatsApp Web; 🪟 notificações; 🔌 contas |
| 20 | Envio exige autorização | ✅ sempre confirma (não configurável) |
| 21 | Ações reportam resultados verdadeiros | ✅ verificação de estado, releitura do clipboard, evidência de envio |
| 22 | Testes essenciais passam | ✅ 217 + 36 |
| 23 | Credenciais protegidas | ✅ Fernet + arquivo 0600 (Linux); 🪟 DPAPI |
| 24 | Backup e restauração funcionam | ✅ |
| 25 | Consumo de recursos documentado | ✅ neste ambiente; 🪟 rodar `benchmark.py` no i5 |
| 26 | Inicialização e encerramento confiáveis | ✅ `setup.bat` idempotente e retomável + `start.bat` (supervisor: instância única, porta, reinício, recuperação, parada limpa com Ctrl+C); 🪟 `winget`, Job Object e início com o Windows |
| 27 | Documentação permite instalar, configurar e manter | ✅ README + 16 documentos (instalação e recuperação em `docs/INSTALACAO.md`) |

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
1. **Windows:** rodar `setup.bat` e a lista de verificação abaixo.
2. **IA:** chave da Anthropic e/ou Ollama + `qwen2.5:3b` (opcional: `paraphrase-multilingual` para embeddings).
3. **Home Assistant:** URL + token de longa duração.
4. **TCL:** modelo exato + app (TCL Home ou Intelligent AC) → integração no HA → `tcl.climate_entity`.
5. **WhatsApp:** escolher o modo (`web` exige `-WhatsApp` + QR; `business` exige conta Meta).
6. **Alexa:** Nabu Casa ou skill manual; Alexa Media Player para anúncios.
7. Depois de validar: `scripts\autostart.ps1 -Enable`.

## Lista de verificação no seu Windows
1. `setup.bat` (dois cliques) termina com "configuração concluída"; se faltar Python ou Node.js, o `winget` os instala depois de perguntar. Verifique em `data\logs\setup-*.log` se nenhuma chave aparece.
2. Rode `setup.bat` de novo: deve terminar em segundos, com "nada a fazer" e "preservado".
3. `start.bat` (dois cliques) mostra "JARVIS pronto" e abre o orb; abra um segundo `start.bat`, que deve responder "já em execução".
4. Ctrl+C na janela do `start.bat` → "Supervisor encerrado". Repita fechando a janela pelo X: nenhum `python.exe` do JARVIS deve ficar no Gerenciador de Tarefas (Job Object).
5. Em Privacidade → Microfone, desative o acesso → `setup.bat` avisa que o Windows está bloqueando o microfone; reative.
6. `setup.bat -Tests`: a suíte do backend passa no Windows.
7. No orb aberto pelo `start.bat`, crie o usuário.
8. Painel → cartão JARVIS: "Agente local conectado".
9. Copie um texto no Bloco de Notas → Conversa: "salve o que copiei como teste" → copie outra coisa → "copie teste" → Ctrl+V no Bloco de Notas mostra o texto original.
10. Copie uma chave falsa `sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxx` → salve → o painel mostra "sensível · cifrado".
11. "abra o VS Code" (ajuste o caminho em `config\jarvis.toml` se precisar).
12. Configurações → Voz → "Falar agora" → diga "que horas são".
13. Ligue a palavra de ativação → diga "Hey Jarvis" → teste e ajuste `wake_threshold`.
14. "parar tudo" → "salve o que copiei" é recusado → "retomar operações".
15. `scripts\stop.ps1` → nenhum `python.exe` do JARVIS fica no Gerenciador de Tarefas.
16. `scripts\autostart.ps1 -Enable` → reinicie o Windows → painel acessível.
17. `backend\.venv\Scripts\python scripts\benchmark.py` → anexe o JSON ao relatório de desempenho.
