# Guia da memória da área de transferência

## Fluxo
1. Copie qualquer texto ou código com **Ctrl+C**.
2. Diga ou digite: **"Jarvis, salve o que copiei como consulta SQL de coletas"**.
3. O agente lê o clipboard **uma única vez** (Win32 `CF_UNICODETEXT`). O JARVIS então:
   - recusa clipboard vazio ou imagem, explicando o motivo;
   - não duplica (compara o SHA-256 do conteúdo) e avisa quando o item já está salvo;
   - detecta segredos (chaves de API, tokens, JWT, chaves privadas, `senha=`, strings de conexão com senha, cartões válidos pelo algoritmo de Luhn) e, se encontrar, **cifra** o conteúdo e não o indexa nem o envia à IA;
   - sugere uma categoria (sql, git, docker, powershell, shell, python, javascript, java, csharp, json, yaml, html, url, email, comando, código, configuração, texto, arquivos);
   - salva o conteúdo **exato** (quebras de linha, tabs e acentos preservados; verificado byte a byte nos testes).
4. Mais tarde: **"Jarvis, copie a consulta SQL de coletas"**. O conteúdo original vai para o clipboard do Windows, o agente relê e confere, e então o JARVIS responde "Pode colar com Ctrl+V".

## Comandos
| Você diz | O que acontece |
|---|---|
| "salve o que copiei" · "guarde isso no projeto JARVIS" · "salve o clipboard como configuração do Docker" | salva (título sugerido se omitido) |
| "encontre o código que salvei ontem" · "procure aquela consulta SQL" | busca por título, categoria, projeto, conteúdo e período |
| "liste meus comandos Git salvos" · "mostre os registros da categoria SQL" | lista filtrada |
| "copie a consulta SQL de coletas" · "copie o primeiro" · "copie o conteúdo salvo para eu colar" | copia para o clipboard |
| "atualize esse registro com o que copiei agora" | substitui o conteúdo (a versão anterior vai para o histórico) |
| "renomeie esse conteúdo para …" | renomeia |
| "apague o registro que salvei por engano" | apaga **depois de confirmação** |

"Esse registro" refere-se ao último registro citado na conversa. Se a busca for ambígua, o JARVIS lista as opções e **não** mexe no clipboard até você escolher ("o segundo", "#12" ou o nome).

## Regras de privacidade
- Não há monitoramento contínuo: o clipboard só é lido quando você pede.
- Nada é salvo automaticamente.
- O clipboard só é sobrescrito quando você pede para copiar.
- Itens sensíveis: cifrados (Fernet, com chave protegida por DPAPI), com prévia mascarada, fora do índice de texto e da IA.

## Painel → Clipboard
Lista, busca, filtros por categoria, visualização e edição do conteúdo, copiar, fixar, renomear, categorizar, relacionar a projeto, etiquetas, histórico de alterações, substituir pelo clipboard atual, excluir, **exportar** (JSON, sem itens sensíveis por padrão) e **importar** (ignora duplicados e itens inválidos).

## Formatos
- **Texto e código:** suporte completo.
- **Lista de arquivos copiados no Explorer** (`CF_HDROP`): salva os caminhos como texto (categoria "arquivos").
- **Imagens e outros formatos:** detectados e recusados com mensagem clara. A estrutura (`content_format`) já está pronta para adicionar esse suporte no futuro.

## Requisito
O acesso real ao clipboard é feito pelo **agente local** (`python -m jarvis_agent`, iniciado pelo `scripts\start.ps1`). Sem o agente, o JARVIS informa que ele não está conectado; não existe simulação pelo navegador. Os itens também podem ser criados manualmente pelo painel ("Novo manual").
