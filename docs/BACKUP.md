# Backup e restauração

## O que entra no backup
Arquivo `data/backups/jarvis-backup-AAAAMMDD-HHMMSS.zip` contendo:
- `jarvis.db`: cópia **consistente** do banco (API de backup online do SQLite, feita com o JARVIS em execução), com memórias, documentos indexados, clipboard, projetos, tarefas, lembretes, grafo, conversas, configurações, dispositivos, contatos e auditoria;
- `library/`: arquivos originais dos documentos importados;
- `manifest.json`: data, versão do esquema e contagens.

**Não entram:** `data/secrets/` (chave-mestra, tokens e chaves de API), modelos de voz, sessão do WhatsApp Web e logs.

## Criar
- Painel → Configurações → Sistema → **Criar backup** (e **Baixar**);
- ou `scripts\backup.ps1`;
- agende pelo Agendador de Tarefas do Windows, por exemplo uma vez por dia: `powershell -File C:\...\assistant\scripts\backup.ps1`.

Guarde cópias **fora do notebook** (OneDrive, HD externo).

## Restaurar
- Painel → Sistema → **Restaurar a partir de arquivo .zip**;
- ou, com o JARVIS parado: `scripts\stop.ps1` e depois `scripts\restore.ps1 -File caminho\backup.zip`.

O processo valida o manifesto, recusa caminhos suspeitos, verifica a integridade do banco, **cria um backup de segurança** em `data/backups/pre-restore/` e só então substitui os dados. Depois aplica as migrações (backups antigos são atualizados ao esquema novo) e invalida o cache de vetores.

## Itens sensíveis e troca de computador
Os itens sensíveis do clipboard e os segredos estão cifrados com uma chave protegida por **DPAPI**, que só a sua conta do Windows naquele computador consegue abrir. Ao restaurar em **outro** PC ou outra conta:
- memórias, documentos, tarefas e clipboard comum: restaurados normalmente;
- **itens sensíveis do clipboard:** ficam ilegíveis. Antes de migrar, exporte-os com Clipboard → Exportar (`include_sensitive=true` via API) e importe no novo PC;
- **segredos (chaves de API, tokens):** cadastre de novo em Configurações → Segredos.

## Validação
Testado automaticamente (`tests/test_api_security.py`): criar backup → alterar dados → restaurar → dados anteriores de volta e busca funcionando; ZIP inválido e ZIP com `../` recusados; download com tentativa de path traversal recusado.
