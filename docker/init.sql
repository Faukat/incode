CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS registered_projects (
    name TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_indexed_at TIMESTAMPTZ,
    last_indexed_chunk_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS code_chunks (
    id BIGSERIAL PRIMARY KEY,
    project_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    language TEXT,
    symbol_name TEXT,
    symbol_type TEXT,
    path_tokens TEXT,
    search_text TEXT,
    search_vector TSVECTOR,
    start_line INTEGER,
    end_line INTEGER,
    content TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_code_chunks_project_file_chunk
    ON code_chunks (project_name, file_path, chunk_index);

CREATE INDEX IF NOT EXISTS idx_code_chunks_project_name
    ON code_chunks (project_name);

CREATE INDEX IF NOT EXISTS idx_code_chunks_file_path
    ON code_chunks (file_path);

CREATE INDEX IF NOT EXISTS idx_code_chunks_symbol_name
    ON code_chunks (symbol_name);

CREATE INDEX IF NOT EXISTS idx_code_chunks_embedding
    ON code_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_code_chunks_search_vector
    ON code_chunks
    USING gin (search_vector);
