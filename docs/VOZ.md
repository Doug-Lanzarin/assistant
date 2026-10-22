# Guia de voz

## Componentes

| Função | Implementação | Onde roda |
|---|---|---|
| Transcrição (STT) | faster-whisper (CTranslate2 int8, CPU) com vocabulário de contexto | agente (microfone do PC) e backend (áudio enviado pelo painel) |
| Palavra de ativação | openWakeWord, modelo pré-treinado `hey_jarvis` | agente |
| Fala (TTS) | voz do navegador (Web Speech, vozes do Windows), SAPI via pyttsx3 ou Piper (voz neural pt_BR "faber") | painel / agente / backend |
| Botão para falar | painel (🎤) · menu da bandeja "Falar agora" · atalho `Ctrl+Alt+J` | — |

Nada de áudio vai para a nuvem e nada é gravado em disco (o arquivo temporário da transcrição é apagado em seguida). A escuta da palavra de ativação vem **desligada por padrão**; o estado aparece no painel (cartão Voz) e na bandeja.

## Instalação

```powershell
setup.bat                        # instala os pacotes e baixa os modelos (~600 MB no total; -NoVoice pula)
# ou manualmente:
backend\.venv\Scripts\pip install -r backend\requirements-voice.txt
backend\.venv\Scripts\python scripts\download_voice_models.py --whisper base
```

> `av<16` está fixado: o faster-whisper 1.2 usa um parâmetro removido no PyAV 16 (o erro encontrado e corrigido na validação foi `open() got an unexpected keyword argument 'metadata_errors'`).

## Uso
- **Tela JARVIS (orb):** a forma principal de falar com o JARVIS. Veja [ORB.md](ORB.md).
- **Painel:** clique em 🎤, fale e clique de novo para enviar. A transcrição roda localmente no backend. Marque "responder em voz alta" para ouvir as respostas; o botão "Interromper fala" corta a fala no meio.
- **Microfone do PC (agente):** Configurações → Voz → "Falar agora", ou o atalho `Ctrl+Alt+J`.
- **Palavra de ativação:** Configurações → Voz → "Ligar palavra de ativação". Diga **"Hey Jarvis"**, espere o indicador mudar para "ouvindo" e fale o comando.
- **Cancelar:** diga "parar tudo" ou clique em Cancelar na conversa.

## Sobre "Jarvis" × "Hey Jarvis"
O openWakeWord publica o modelo `hey_jarvis` (treinado em inglês com fala sintetizada). Não existe modelo pronto para "Jarvis" sozinho. Opções:
1. Usar "Hey Jarvis" (padrão).
2. Treinar um modelo próprio "Jarvis" no notebook de treino do openWakeWord (Google Colab, cerca de 1 hora) e salvá-lo como `.onnx`. Informe o nome em `voice.wake_model`.
3. Usar o atalho de teclado ou o botão (sempre disponíveis).

**Validação feita aqui:** o custo medido foi de cerca de 3,9 ms de CPU por quadro de 80 ms (≈5% de um núcleo). Um "Hey Jarvis" sintetizado por uma voz **portuguesa** (Piper) **não disparou** o detector (pontuação 0,04, abaixo do limiar de 0,5). O modelo responde a pronúncia inglesa; teste com a sua voz e ajuste `voice.wake_threshold` (0,3 a 0,6). Se não ficar confiável no seu microfone, use o atalho e o botão, como previsto no projeto.

## Qualidade da transcrição em português (medida)
Frases ditas pela voz sintetizada pt_BR do Piper, transcritas com o modelo `base`:
- sem vocabulário de contexto, "Jarvis" saiu como "Já viz", "Tavis", "Davis" e "ar-condicionado" como "acondicionado";
- com o vocabulário de contexto (`voice.stt_prompt`) e o hotword "Jarvis", "Jarvis" saiu certo nas 5 frases testadas, e o interpretador ainda normaliza variações comuns ("vinte e três"/"20 e 3" → 23, "acondicionado" → ar-condicionado, "abro" → abra).

Personalize `voice.stt_prompt` com nomes que você usa (contatos, projetos, cômodos): isso melhora muito o reconhecimento.

## Escolha do modelo Whisper
| Modelo | Carga | RAM do processo | Tempo / duração do áudio (RTF)* | Uso |
|---|---|---|---|---|
| tiny | 1,9 s | ~510 MB | 0,28 | máquinas fracas |
| **base** (padrão) | 1,3 s | ~650 MB | 0,34 | recomendado |
| small | 10 s | ~1,3 GB | 0,81 | melhor precisão, mais lento |

\*Medido neste ambiente de desenvolvimento (Xeon 2,8 GHz, 4 vCPU), **não** no seu i5. Um RTF de 0,34 significa que uma frase de 3 s leva cerca de 1 s para ser transcrita. Rode `scripts\benchmark.py` no notebook para obter os números reais.

## Dispositivos de áudio
Configurações → Voz → "Dispositivos de áudio (agente)" lista microfones e saídas detectados pelo `sounddevice`. Escolha o índice desejado.

## Microfone pelo navegador de outro dispositivo
Navegadores só liberam o microfone em contexto seguro: `http://127.0.0.1` (no próprio PC) ou HTTPS. Acessando o painel pelo celular via `http://IP:8765`, o botão 🎤 fica indisponível. Use o texto ou o microfone do PC (agente).
