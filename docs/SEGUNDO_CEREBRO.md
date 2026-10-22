# Guia do segundo cérebro

O JARVIS guarda o que importa em uma memória **independente do modelo de IA** (SQLite local), recupera por busca híbrida e relaciona as informações em um grafo. A memória persiste entre reinicializações e entra no backup.

## Tipos de memória

| Tipo | Exemplos | Como criar |
|---|---|---|
| Nota / fato | "o servidor de homologação fica no IP …" | "anote que …", "lembre que …", painel |
| Ideia | "app de receitas com IA" | "anote a ideia de …" |
| Decisão | "decidimos usar SQLite" | "registre a decisão …", ou extraída pela consolidação |
| Preferência | "prefiro respostas curtas" | painel; inferências só valem depois de confirmadas |
| Projeto | objetivos, estado, problemas | "… no projeto X", painel → Projetos |
| Episódio | o que aconteceu e quando | consolidação, painel |
| Tarefas e lembretes (prospectiva) | "revisar código amanhã às 9" | "crie um lembrete…", "crie uma tarefa…" |
| Biblioteca | PDF, DOCX, Markdown, TXT, código | painel → Documentos |
| Clipboard | consultas, comandos, configurações | ver [CLIPBOARD.md](CLIPBOARD.md) |

Cada memória registra **origem** (`user`, `consolidation`, `llm`…), **data**, **tipo**, **estado** e **confiança**:

- `explicit`: você disse ou digitou;
- `confirmed`: inferência que você confirmou;
- `inferred`: sugestão do sistema, aparece sinalizada e nunca é tratada como fato;
- `outdated`: desatualizada, aparece com aviso;
- `contradicted`: conflita com outra memória;
- `rejected`: ignorada na busca.

Memórias de projeto sem atualização há 90 dias, e preferências ou fatos sem atualização há 1 ano, aparecem como "possivelmente desatualizadas".

## Busca (RAG)
- **Palavras-chave:** FTS5/BM25, sem acentos ("configuracao" encontra "configuração").
- **Semântica:** vetores (hashing local por padrão; Ollama para semântica neural, veja [IA.md](IA.md)).
- **Combinação:** Reciprocal Rank Fusion, com um resultado por item (o melhor trecho).
- **Filtros:** tipo, projeto, período ("ontem", "mês passado", "últimos 90 dias") e fonte (memória, documento, clipboard).
- **Citação:** cada resultado traz a origem (`memória #12 (decisão, 2026-10-22)`, `documento 'arquitetura.md'`). Pergunte "de onde veio essa informação?" para ver as fontes da última resposta.
- **Sem evidência, sem resposta:** se nada for encontrado, o JARVIS diz que não encontrou.

## Grafo de conhecimento
Entidades (projetos, tecnologias, pessoas, ideias, decisões, documentos, tarefas, etiquetas) são extraídas de cada item e ligadas por relações como `utiliza`, `menciona`, `decidiu`, `tem_tarefa`, `envolve` e `relacionado_a`. Relações inferidas aparecem tracejadas no painel.

Exemplos: "quais projetos utilizam Python?", "relacione minhas notas de Java", "que ideias antigas podem ajudar na tarefa atual?". O painel → Projetos mostra decisões, ideias, tarefas e relações de cada projeto.

## Consolidação (segundo plano, a cada 60 min por padrão)
Gera **somente inferências** para revisão em painel → Segundo cérebro → Consolidação:
- resumo de cada sessão de conversa (com IA quando disponível, heurístico sem ela);
- decisões ("decidi", "vamos usar"), pendências ("preciso", "falta") e ideias ("tive uma ideia");
- duplicatas (similaridade de vetores ≥ 0,93), contradições entre preferências e novas conexões no grafo.

Mensagens, documentos ou memórias nunca alteram regras de segurança nem concedem permissões.

## Corrigir e esquecer
- Painel → Memórias: editar, confirmar, rejeitar, marcar como desatualizada, apagar.
- Por voz ou texto: "esqueça a informação sobre X" → o JARVIS mostra exatamente qual memória será apagada e pede confirmação. A exclusão remove também os trechos indexados, o FTS, os vetores e as ligações do grafo.
- Apagar documentos remove o arquivo copiado em `data/library` e seus índices.
