# Guia do Home Assistant

O Home Assistant (HA) é a camada central da casa: o JARVIS conversa **apenas** com o HA, e o HA conversa com os dispositivos (TCL, lâmpadas, tomadas, sensores, Alexa…).

## 1. Ter um Home Assistant
Se ainda não tiver um: Home Assistant OS num Raspberry Pi, mini-PC ou máquina virtual, ou o Home Assistant Container (Docker). Veja https://www.home-assistant.io/installation/. O HA deve estar na mesma rede do notebook, por exemplo em `http://homeassistant.local:8123`.

## 2. Criar um token de longa duração
No HA: clique no seu usuário (canto inferior esquerdo) → aba **Segurança** → **Tokens de acesso de longa duração** → **Criar token** → nome "JARVIS" → copie o token (ele é exibido uma única vez).

## 3. Configurar no JARVIS
Painel → **Configurações → Integrações → Home Assistant**:
- `url`: `http://homeassistant.local:8123` (ou `http://IP:8123`);
- **Token de longa duração**: cole e salve (fica cifrado com DPAPI).

Depois, em **Casa → Sincronizar dispositivos**. O JARVIS lê `/api/states` e os cômodos (áreas) via `/api/template`.

## 4. Nomes amigáveis e cômodos
- Os cômodos vêm das **áreas** do HA. Organize os dispositivos em áreas lá para que "desligue as luzes da sala" funcione.
- Em **Casa → ✎** defina apelidos de voz ("ar", "ar do quarto", "luz do teto").
- Ou fixe os nomes em `config/jarvis.toml` (seção `[[devices]]`).

## O que funciona
| Pedido | Serviço do HA | Verificação |
|---|---|---|
| "ligue/desligue X" | `<domínio>.turn_on/turn_off` (luz, tomada, ventilador, clima, mídia…), `cover.open/close` | lê o estado depois e responde "estado confirmado" ou "NÃO mudou" |
| "ajuste o ar para 23 graus" | `climate.set_temperature` | confere `attributes.temperature`; valida contra `min_temp`/`max_temp` |
| "qual a temperatura da sala?" | sensor com `device_class: temperature` na área, ou `current_temperature` do clima | — |
| "execute a cena boa noite" | `scene.turn_on`, `script.turn_on`, `automation.trigger` | (a API não confirma o efeito de cenas) |
| "estou saindo de casa", "boa noite" | rotinas do `config/jarvis.toml` | resumo de cada passo |

**Segurança:** fechaduras, alarmes, portões e garagens exigem confirmação (risco 4), mesmo que a política geral não peça. Nomes ambíguos ("ligue a luz", quando existem várias) geram uma pergunta, não um palpite.

## Acesso remoto
O JARVIS **não** deve ser exposto à internet. Para controlar a casa de fora, use o acesso remoto do próprio HA (Nabu Casa ou VPN como Tailscale/WireGuard) e o app oficial do HA. Se quiser usar o painel do JARVIS no celular dentro de casa, veja [SEGURANCA.md](SEGURANCA.md).

## Estado da validação
A integração foi testada contra um **HA simulado** (MockTransport com a mesma API REST): sincronização, áreas, liga/desliga com verificação, clima, sensores, cenas, fechadura com confirmação, erro 401, HA fora do ar e ambiguidade. **Ainda não foi validada com o seu Home Assistant real** (pendência externa).
