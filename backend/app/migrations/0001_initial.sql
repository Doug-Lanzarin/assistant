-- Esquema inicial do JARVIS

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    user_agent TEXT
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE conversations (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'Conversa',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content TEXT NOT NULL,
    meta TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_messages_conv ON messages(conversation_id, id);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    tool TEXT NOT NULL,
    args TEXT,
    risk INTEGER NOT NULL,
    origin TEXT NOT NULL,
    status TEXT NOT NULL,
    result_summary TEXT,
    duration_ms INTEGER,
    conversation_id INTEGER
);
CREATE INDEX idx_audit_ts ON audit_log(ts);

CREATE TABLE pending_actions (
    id TEXT PRIMARY KEY,
    conversation_id INTEGER,
    tool TEXT NOT NULL,
    args TEXT NOT NULL,
    summary TEXT NOT NULL,
    risk INTEGER NOT NULL,
    origin TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    result TEXT
);

CREATE TABLE ai_usage (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    est_cost_usd REAL NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL,
    latency_ms INTEGER,
    error TEXT
);
CREATE INDEX idx_ai_usage_ts ON ai_usage(ts);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE memories (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    source_ref TEXT,
    status TEXT NOT NULL DEFAULT 'explicit'
        CHECK (status IN ('explicit','confirmed','inferred','outdated','contradicted','rejected')),
    confidence REAL NOT NULL DEFAULT 1.0,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    happened_at TEXT,
    sensitive INTEGER NOT NULL DEFAULT 0,
    supersedes_id INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_memories_kind ON memories(kind);
CREATE INDEX idx_memories_project ON memories(project_id);
CREATE INDEX idx_memories_created ON memories(created_at);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','cancelled')),
    due_at TEXT,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE reminders (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','fired','cancelled')),
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    fired_at TEXT
);
CREATE INDEX idx_reminders_due ON reminders(status, due_at);

CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    stored_path TEXT,
    mime TEXT,
    sha256 TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    char_count INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Trechos indexados (memórias, documentos e clipboard) com embeddings.
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY,
    owner_type TEXT NOT NULL CHECK (owner_type IN ('memory','document','clipboard')),
    owner_id INTEGER NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    embedding BLOB,
    embed_model TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_chunks_owner ON chunks(owner_type, owner_id);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER chunks_au AFTER UPDATE OF text ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

-- Grafo de conhecimento relacional
CREATE TABLE entities (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (type, normalized)
);

CREATE TABLE relations (
    id INTEGER PRIMARY KEY,
    src_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    rel TEXT NOT NULL,
    dst_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    source_type TEXT,
    source_id INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'explicit',
    created_at TEXT NOT NULL,
    UNIQUE (src_id, rel, dst_id)
);

CREATE TABLE entity_links (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    owner_type TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    PRIMARY KEY (entity_id, owner_type, owner_id)
);

-- Memória da área de transferência
CREATE TABLE clipboard_items (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    encrypted INTEGER NOT NULL DEFAULT 0,
    content_format TEXT NOT NULL DEFAULT 'text',
    category TEXT NOT NULL DEFAULT 'texto',
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    sha256 TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    sensitive INTEGER NOT NULL DEFAULT 0,
    char_count INTEGER NOT NULL DEFAULT 0,
    copy_count INTEGER NOT NULL DEFAULT 0,
    last_copied_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_clip_sha ON clipboard_items(sha256);
CREATE INDEX idx_clip_category ON clipboard_items(category);

CREATE TABLE clipboard_history (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES clipboard_items(id) ON DELETE CASCADE,
    change_type TEXT NOT NULL,
    old_title TEXT,
    old_content TEXT,
    old_encrypted INTEGER NOT NULL DEFAULT 0,
    changed_at TEXT NOT NULL
);

-- Casa inteligente
CREATE TABLE devices (
    entity_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    room TEXT,
    domain TEXT NOT NULL,
    last_state TEXT,
    attributes TEXT,
    updated_at TEXT NOT NULL
);

-- WhatsApp
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized TEXT NOT NULL,
    phone TEXT,
    aliases TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE whatsapp_messages (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    ext_id TEXT UNIQUE,
    chat TEXT,
    sender TEXT,
    text TEXT NOT NULL,
    received_at TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_wa_received ON whatsapp_messages(received_at);

CREATE TABLE whatsapp_outbox (
    id INTEGER PRIMARY KEY,
    channel TEXT NOT NULL,
    to_name TEXT NOT NULL,
    to_address TEXT,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    evidence TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
);
