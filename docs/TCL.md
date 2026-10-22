# Guia do ar-condicionado TCL

## Situação
- A TCL **não** publica integração oficial com o Home Assistant nem API documentada para o app **TCL Home** (pesquisa de outubro de 2026).
- Por isso o JARVIS controla o TCL **através do Home Assistant**, como uma entidade `climate.*` comum. Ligar, desligar, temperatura, modo e leitura da temperatura ambiente já estão implementados e testados contra um HA simulado.
- Não inventamos endpoints, chaves nem protocolos.

## Caminhos para colocar o TCL no Home Assistant

| Caminho | Como funciona | Observações |
|---|---|---|
| **TCL Home (unofficial)** — integração comunitária `ha-tcl-home-unofficial-integration` (autor "nemesa") | usa a conta do app TCL Home (nuvem) | relatos de uso com Split AC, Split AC Fresh Air, portátil, janela e desumidificador; instalação pelo HACS. Confira o repositório e a discussão em https://community.home-assistant.io/t/tcl-home-integration/561846 |
| **TCL Intelligent AC** — https://github.com/jestempablo/home-assistant-tcl-intelligent-ac | controle **local** na LAN (BroadLink/DNA) | para aparelhos do app "Intelligent AC" (não o TCL Home); testado pelo autor só no XA71I; a região "EU" falhou no pareamento, "United States/Other" funcionou |
| **Tuya** (Tuya Local / Tuya Cloud) | alguns modelos OEM são Tuya | vários usuários relatam que o aparelho não aparece no app Smart Life |
| **Controle por infravermelho** (Broadlink, ESPHome + LED IR) | imita o controle remoto | funciona com qualquer modelo, mas sem retorno real de estado |
| Outra integração (ex.: via Yandex, em alguns países) | — | depende da região |

Todas são projetos comunitários, com manutenção sem garantia. Confirme o modelo e a região antes de instalar.

## Passo a passo recomendado
1. Anote o **modelo exato** (etiqueta da unidade interna) e **qual app** você usa (TCL Home ou Intelligent AC).
2. Instale o HACS no HA e a integração correspondente da tabela acima.
3. Confirme no HA que surgiu uma entidade `climate.xxx` e que ligar e ajustar a temperatura funciona pelo próprio HA.
4. No JARVIS: **Configurações → Integrações → Ar-condicionado TCL** → `climate_entity = climate.xxx`, `model = <modelo>`, `integration = <nome>`.
5. **Casa → Sincronizar.** Teste: "Jarvis, ligue o ar-condicionado", "ajuste o ar para 23 graus", "desligue o ar".

Com `climate_entity` definido, frases genéricas ("ligue o ar", "ajuste o ar") vão direto para o TCL. Com mais de um ar-condicionado, diga o cômodo ("o ar do quarto").

## Para validar a integração real, preciso de
- o **modelo exato** do aparelho;
- o **app** usado (TCL Home ou Intelligent AC) e a região da conta;
- a confirmação de que o HA já mostra a entidade `climate.*`.
