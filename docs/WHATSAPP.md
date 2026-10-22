# Guia do WhatsApp

## O que é possível (e o que não é)
- **Não existe API oficial** para ler todo o histórico de uma conta **pessoal** do WhatsApp. O JARVIS não promete isso.
- A **WhatsApp Business Platform (Cloud API)** é para números empresariais: ela envia e recebe mensagens **desse número**, não da sua conta pessoal.
- Notificações do Windows mostram só remetente e prévia, e só das mensagens que chegam enquanto o PC está ligado.

Por isso o JARVIS tem **três modos independentes** (Configurações → Integrações → WhatsApp → `mode`):

| Modo | Leitura | Envio | Requisitos | Riscos / limites |
|---|---|---|---|---|
| `notifications` | prévias das notificações do WhatsApp Desktop | não | agente + pacotes `winrt` + permissão de acesso às notificações no Windows | só o que aparece na notificação; algumas versões do Windows negam essa API a apps não empacotados (o JARVIS detecta e informa) |
| `web` | conversas não lidas visíveis no WhatsApp Web | sim, uma por vez, com confirmação e verificação | `setup.bat -WhatsApp`; iniciar com `start.bat --whatsapp-web`; escanear o QR na janela aberta | automação de interface: quebra quando o site muda (seletores ajustáveis em `config/whatsapp_selectors.json`) e pode contrariar os Termos do WhatsApp; uso pessoal, sem envio em massa |
| `business` | mensagens recebidas pelo número empresarial (webhook) | sim, com confirmação | conta Meta Business, número dedicado, app na Meta, token, webhook público HTTPS | custos por mensagem; fora da janela de 24 h só templates aprovados |

Em todos os modos: mensagens recebidas são **dados não confiáveis**. Uma mensagem nunca autoriza ações, e qualquer ação que a IA tente depois de ler mensagens exige a sua confirmação.

## Fluxo de envio
> **Você:** Jarvis, mande uma mensagem para o João dizendo que estou chegando.
> **JARVIS:** Encontrei João Silva. Vou enviar: “Estou chegando”. Posso enviar?
> **Você:** Pode enviar.
> **JARVIS:** Mensagem enviada para João Silva (confirmação: …).

- Mais de um "João" → o JARVIS pergunta qual ("João Pereira" ou "o segundo").
- Falha → "A mensagem NÃO foi enviada: <motivo>" e o registro em WhatsApp → Envios.
- O JARVIS só diz "enviada" com evidência: o ID `wamid…` retornado pela Cloud API, ou a mensagem visível como enviada (✓) no WhatsApp Web.
- Contatos: cadastre em WhatsApp → Contatos (nome + telefone internacional, que é obrigatório no modo `business`). No modo `web`, o JARVIS também procura pelo nome na busca do WhatsApp Web.

## Modo `business` (Cloud API) — passo a passo
1. https://developers.facebook.com → **Criar app** → tipo **Business** → adicionar o produto **WhatsApp**.
2. Em WhatsApp → API Setup: anote o **Phone number ID**, adicione um número de teste ou registre um número próprio (que não pode estar em uso no app WhatsApp comum).
3. Crie um **token permanente** (System User no Business Manager, com permissões `whatsapp_business_messaging` e `whatsapp_business_management`).
4. No JARVIS: `mode = business`, `phone_number_id`, `api_version` (padrão `v23.0`; use a versão atual da Graph API) e, em Segredos: **Token da Cloud API**, **App Secret** e **Verify token** (uma senha que você inventa).
5. **Webhook:** a Meta precisa alcançar `https://<seu-dominio>/api/whatsapp/webhook`. **Não abra o JARVIS inteiro para a internet.** Use um túnel que exponha **somente esse caminho** (por exemplo, Cloudflare Tunnel com regra de caminho) ou um pequeno proxy na nuvem. O endpoint valida o verify token e a assinatura `X-Hub-Signature-256` (HMAC-SHA256 com o App Secret) e recusa o resto.
6. Na Meta → Webhooks: URL de retorno + verify token → assinar o campo `messages`.

**Custos (referência, confira na fonte):** desde julho de 2025 a Meta cobra **por mensagem entregue**, com valores por categoria (marketing, utilidade, autenticação) e por país. Mensagens de serviço respondidas dentro da janela de 24 h aberta pelo cliente são gratuitas. Para o Brasil, a Meta anunciou cobrança em BRL a partir de julho de 2026. A tabela oficial fica em https://developers.facebook.com/docs/whatsapp/pricing.

**Histórico:** a Cloud API não fornece histórico de conversas; o JARVIS guarda o que recebe pelo webhook a partir da configuração.

## Estado da validação
| Item | Situação |
|---|---|
| Cloud API: envio, erros (fora da janela de 24 h), verificação do webhook, assinatura HMAC, ingestão de mensagens e status | testado com servidor simulado |
| WhatsApp Web: login, não lidas, busca de contato, envio e verificação, falha de envio | testado contra página local que imita a estrutura do site |
| Notificações do Windows | implementado; **não testado** (exige Windows) |
| Conta real (Web ou Business) | **pendente de validação externa** |
