# Guia de voz

## Componentes

| Função | Implementação | Onde roda |
|---|---|---|
| Transcrição (STT) | faster-whisper (CTranslate2 int8, CPU) com vocabulário de contexto | agente (microfone do PC) e backend (áudio enviado pelo painel) |
| Palavra de ativação | openWakeWord, modelo pré-treinado `hey_jarvis` | agente |
| Fala (TTS) | Piper (voz neural local pt-BR; padrão **Cadu**, também Faber e Jeff), voz do navegador (no Edge, vozes neurais "Natural" online) ou SAPI via pyttsx3 | backend / painel / agente |
| Botão para falar | painel (🎤) · menu da bandeja "Falar agora" · atalho `Ctrl+Alt+J` | — |

Nada de áudio vai para a nuvem e nada é gravado em disco (o arquivo temporário da transcrição é apagado em seguida). A escuta da palavra de ativação vem **desligada por padrão**; o estado aparece no painel (cartão Voz) e na bandeja.

## Instalação

```powershell
setup.bat                        # instala os pacotes e baixa os modelos (~1,3 GB no total; -NoVoice pula)
# ou manualmente:
backend\.venv\Scripts\pip install -r backend\requirements-voice.txt
backend\.venv\Scripts\python scripts\download_voice_models.py --whisper small --piper cadu
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

## Por que às vezes "ficava só processando" (corrigido em 24/10/2026)
Investigado com áudio real (frases faladas tocadas no microfone do Chromium, transcrição local, resposta e voz):

| Causa | Efeito | Correção |
|---|---|---|
| O modelo Whisper só carregava no 1º comando | 1ª transcrição levava ~24 s | carregado em segundo plano ao iniciar o JARVIS (sem acessar a internet se já estiver baixado) |
| Modelo `base` com `beam_size=1` | "Boa noite" virava "Ponoichi", "que horas são" virava "Kjorsson" | `small` com `beam_size=5` (ver medições abaixo) |
| Cumprimentos não eram comandos | sem IA: "não reconheci"; com IA local lenta: dezenas de segundos para responder "boa noite" | conversa social respondida na hora, sem IA |
| No exemplo de configuração, "bom dia" e "boa noite jarvis" eram atalhos de **rotinas** | um cumprimento abria programas ou executava cena do Home Assistant | cumprimentos nunca disparam ações; atalhos removidos do exemplo |
| Fim de fala com limiar fixo | com ruído de fundo (ventoinha), a gravação só parava após 15 s | detecção adaptativa: calibra o ruído nos primeiros 300 ms e mede o silêncio relativo à sua voz |
| Sem limite de tempo | um modelo local lento podia segurar o pedido por minutos | limite total de 150 s no backend e 180 s na interface, com mensagem clara; a interface mostra os segundos e o que está acontecendo |
| Animação do orb competindo pela CPU | transcrição 2,4× mais lenta com a página aberta (navegador sem aceleração de vídeo) | 30 quadros/s fora da escuta/fala, fundo em cache e resolução adaptativa |

**Resultado medido (fim da fala → resposta começando a tocar):** 2,5 s para "Boa noite, Jarvis." com o orb aberto (antes: 3,5 s na mesma condição, ou ~24 s no primeiro comando).

## Qualidade da transcrição em português (medida)
24 gravações (12 frases curtas faladas pelo Piper, em condição "limpa" e "notebook": volume baixo, ruído de fundo e silêncio no fim):

| Configuração | Erro de palavras | Tempo médio por frase |
|---|---|---|
| base, beam 1 (padrão antigo) | 38% (11 de 24 frases erradas) | 0,75 s |
| base, beam 5 | 24% | 0,66 s |
| small, beam 1 | 9% | 1,43 s |
| **small, beam 5, sem timestamps (novo padrão)** | **~3%** (as 2 "erradas" escreveram "23 graus" em vez de "vinte e três graus") | **1,52 s** |

Memória: o processo do JARVIS usa ~1,3 GB de RAM com o `small` (~650 MB com o `base`). Tempos medidos neste ambiente de desenvolvimento (Xeon, 4 vCPU), **não** no seu i5. Se o seu notebook ficar lento, escolha "Precisão da transcrição" = 1 ou o modelo `base` em Configurações → Voz.

O vocabulário de contexto (`voice.stt_prompt`) e o hotword "Jarvis" continuam ativos; personalize-os com nomes que você usa (contatos, projetos, cômodos).

## Voz de resposta
Em **Configurações → Voz → Voz de resposta** você ouve uma amostra de cada voz e escolhe a que preferir:

| Voz | Onde roda | Observação |
|---|---|---|
| **Cadu** (padrão) | Piper, local | ritmo de conversa (~2,4 palavras/s) e a melhor inteligibilidade nas medições |
| Faber | Piper, local | a voz anterior; fala mais rápido (~3,5 palavras/s), o que soa mais "robótico" |
| Jeff | Piper, local | grave e pausada |
| Vozes "Natural" do **Microsoft Edge** (Francisca, Antonio) | navegador, **online** | as mais naturais; o texto da resposta é processado pela Microsoft |
| Vozes do Windows (Maria, Daniel) | navegador/SAPI, local | as mais sintéticas |

As vozes Piper que faltarem são baixadas com um clique (do repositório oficial `rhasspy/piper-voices`, ~63 MB cada). O texto também é preparado para a fala: horários ("21:30" → "21 e 30"), graus, porcentagens, valores em reais, sem símbolos, links nem citações.

## Dispositivos de áudio
Configurações → Voz → "Dispositivos de áudio (agente)" lista microfones e saídas detectados pelo `sounddevice`. Escolha o índice desejado.

## Microfone pelo navegador de outro dispositivo
Navegadores só liberam o microfone em contexto seguro: `http://127.0.0.1` (no próprio PC) ou HTTPS. Acessando o painel pelo celular via `http://IP:8765`, o botão 🎤 fica indisponível. Use o texto ou o microfone do PC (agente).
