# Guia da Alexa

A Alexa é **opcional**. O JARVIS funciona sem ela.

## Como a Alexa entra no projeto
O Home Assistant é a ponte. Quando o HA está ligado à Alexa, os dispositivos do HA (incluindo o ar TCL) aparecem no app Alexa e podem ser comandados pelos Echo ("Alexa, ligue o ar do quarto"). O JARVIS e a Alexa passam a controlar **os mesmos** dispositivos, cada um pelo seu lado.

O JARVIS **não** envia comandos arbitrários para os Echo: a Amazon não oferece uma API pública para isso. Não usamos endpoints não documentados.

## Opções de integração HA ↔ Alexa

| Opção | Custo | Exposição à internet | Esforço |
|---|---|---|---|
| **Home Assistant Cloud (Nabu Casa)** | assinatura: US$ 6,50/mês ou US$ 65/ano nos EUA (preços de referência; confira em https://www.nabucasa.com/pricing/), com 31 dias de teste | não precisa abrir portas | baixo: ative "Alexa" em Configurações → Home Assistant Cloud |
| **Skill Smart Home manual** (https://www.home-assistant.io/integrations/alexa.smart_home/) | grátis no nível gratuito da AWS (Lambda) | o HA precisa estar acessível pela internet via HTTPS na porta 443, com certificado confiável | alto: conta de desenvolvedor Amazon + AWS + função Lambda + vinculação de conta |

Recomendação: Nabu Casa, se o custo for aceitável. A skill manual exige expor o HA (com HTTPS e acesso bem protegido).

## Anúncios falados pelo JARVIS (opcional)
A ferramenta `alexa_announce` chama um serviço `notify.*` do Home Assistant. O caminho mais comum é a integração comunitária **Alexa Media Player** (HACS), que cria serviços como `notify.alexa_media_sala`. Ela é **não oficial**: faz login com a sua conta Amazon e pode deixar de funcionar quando a Amazon mudar algo.

Para ativar: Configurações → Integrações → Alexa → `enabled = true` e `notify_service = notify.alexa_media_sala`. Todo anúncio passa por confirmação (risco 3). O JARVIS informa que o anúncio foi **enviado**, porque a API não confirma se foi tocado.

## Estado
- Implementado: `alexa_announce` via HA e a documentação de integração.
- **Pendente de validação externa:** depende da sua conta Amazon, do Echo e da escolha entre Nabu Casa e skill manual.
