# Segurança e privacidade

## Modelo de ameaça
| Ameaça | Defesa |
|---|---|
| Alguém na rede acessando o painel | o backend escuta só em `127.0.0.1`; login obrigatório (senha com scrypt); sessões opacas (o banco guarda só o SHA-256 do token); limite de 10 tentativas de login a cada 5 min; primeiro cadastro só a partir do próprio PC |
| Site malicioso no navegador chamando a API local | CORS restrito às origens do JARVIS; WebSocket valida a `Origin`; token Bearer (não basta o cookie); CSP `default-src 'self'`, `X-Frame-Options: DENY` |
| Processo local se passando pelo agente | o agente se autentica com token aleatório protegido por **DPAPI** (`data/secrets/agent.token`), comparado em tempo constante; conexões de navegador (com `Origin`) são recusadas nesse canal |
| IA "inventando" ou abusando de ferramentas | só ferramentas registradas; validação Pydantic estrita (`extra=forbid`); ferramentas internas inacessíveis à IA; tudo auditado |
| **Prompt injection** (mensagem, documento ou página com ordens) | conteúdo externo vai como `<dados_nao_confiaveis>`; depois de ler conteúdo externo, qualquer alteração pedida pela IA exige confirmação humana; confirmações só valem vindas do usuário (a IA não confirma); memória e documentos nunca concedem permissões; a consolidação só gera inferências |
| Execução de comandos arbitrários | não existe ferramenta de shell; apps, sites, projetos e comandos de desenvolvimento só pela lista de `config/jarvis.toml`; o agente recusa metacaracteres de shell, usa `shell=False`, só abre URLs http(s) e caminhos existentes; a busca e abertura de arquivos respeitam `allowed_dirs` (incluindo proteção contra `..` e links simbólicos via `resolve()`) |
| Vazamento de segredos | chaves e tokens cifrados (Fernet) com chave-mestra protegida por DPAPI (vinculada à sua conta do Windows); nunca retornados pela API; logs mascaram padrões de chaves e tokens; itens sensíveis do clipboard cifrados, fora do índice e da IA |
| Ação errada por ambiguidade | contatos, dispositivos e registros ambíguos geram pergunta, não palpite; ações pendentes expiram em 5 min e são marcadas antes de executar (não executam duas vezes) |
| Arquivos de backup manipulados | o restore valida o manifesto, recusa caminhos `..` ou absolutos, roda `PRAGMA integrity_check` e cria antes um backup de segurança |

## Níveis de risco e confirmação
| Nível | Exemplos | Padrão |
|---|---|---|
| 1. Leitura informativa | buscar, listar, status, ler mensagens | executa |
| 2. Alteração reversível | salvar memória ou clipboard, copiar para o clipboard, abrir app, luzes, temperatura | executa; **confirma** se a IA pedir depois de ler conteúdo externo |
| 3. Comunicação externa | enviar WhatsApp, anúncio na Alexa | **confirma** (WhatsApp sempre, sem exceção) |
| 4. Sensível ou irreversível | esquecer memória, apagar clipboard, reiniciar serviço, fechaduras, alarme, garagem | **sempre confirma** (não configurável) |

Configurações → Permissões: desative permissões inteiras (por exemplo `whatsapp.send`, `windows.open`) e escolha quais níveis confirmam (o nível 4 é fixo).

## Modo de emergência
"**Parar tudo**" (ou o botão do painel): cancela as tarefas em execução e as ações pendentes, interrompe a fala e desativa todas as ferramentas acima do nível 1. Só o usuário pode desfazer ("retomar operações" ou o botão); a IA não tem acesso a essa ferramenta.

## Privacidade
- Dados ficam em `data/` no seu PC. Nada é enviado para a nuvem, exceto, quando você configura IA remota, o texto do pedido, o histórico recente e trechos da memória (desative com `ai.send_memory_to_remote`).
- O áudio é processado localmente e não é gravado.
- O clipboard não é monitorado e nunca é sobrescrito sem pedido.
- Exportar e apagar: Clipboard → Exportar; Segundo cérebro → apagar memórias e documentos; Configurações → Sistema → Apagar conversas; backup completo em Sistema.
- Métricas de uso de IA guardam apenas tokens, custo, latência e erros, nunca o conteúdo.

## Acessar pelo celular (rede local) — opcional
Por padrão o JARVIS não aceita conexões de fora do PC. Se quiser usar o painel no celular:
1. **Recomendado:** Tailscale no PC e no celular (rede privada cifrada), `JARVIS_HOST=0.0.0.0` e acesse `http://<IP-do-Tailscale>:8765` (mesma origem: não é preciso mexer em CORS).
2. Na rede doméstica sem túnel, o tráfego HTTP **não é cifrado**: o token de sessão pode ser capturado por quem estiver na mesma rede Wi-Fi. Evite fazer isso em redes compartilhadas.
3. **Nunca** faça encaminhamento de porta do roteador para o JARVIS.

## Boas práticas
- Use uma senha forte no painel e no Windows (o DPAPI é tão seguro quanto a sua conta).
- Mantenha `allowed_dirs` restrito.
- Revise a Auditoria (Configurações → Sistema) de vez em quando.
- Atualize as dependências periodicamente (`pip install -U -r backend\requirements.txt`, depois `scripts\test.ps1`).
