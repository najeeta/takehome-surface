CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    text            TEXT NOT NULL,
    embedding       vector(1536) NOT NULL,
    source_md_path  TEXT NOT NULL,
    section_path    TEXT NOT NULL,
    department      TEXT NOT NULL,
    page_start      INTEGER NOT NULL,
    page_end        INTEGER NOT NULL,
    links           JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_chunks_department ON chunks (department);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_source_section ON chunks (source_md_path, section_path);
