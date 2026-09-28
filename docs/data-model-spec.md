# Data Model Specification — Handbook Q&A Retrieval

## Overview

This spec defines the data model, ingestion pipeline, caching layer, and infrastructure for a Retrieval-Augmented Generation (RAG) system that indexes the PostHog handbook PDF and serves grounded Q&A responses with citations.

The stack runs entirely via Docker Compose.

---

## Infrastructure

| Service         | Image / Base              | Role                                      | Port  |
|-----------------|---------------------------|--------------------------------------------|-------|
| `postgres`      | `pgvector/pgvector:pg16`  | Vector store + chunk metadata              | 5432  |
| `redis`         | `redis:7-alpine`          | Query cache + rate limiting                | 6379  |
| `ingest`        | Custom (Python)           | PDF parsing + embedding + DB load at build | -     |
| `api`           | Custom (Python/Node)      | Q&A endpoint, retrieval + generation       | 8000  |

---

## Database Schema (PostgreSQL + pgvector)

### Extension

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Table: `chunks`

```sql
CREATE TABLE chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    text            TEXT NOT NULL,
    embedding       vector(1536) NOT NULL,  -- dimension matches embedding model
    source_md_path  TEXT NOT NULL,           -- e.g. "contents/handbook/brand/email-comms.md"
    section_path    TEXT NOT NULL,           -- e.g. "Email comms > Email broadcasts > Launch emails"
    department      TEXT NOT NULL,           -- e.g. "brand", extracted from source_md_path
    page_start      INTEGER NOT NULL,
    page_end        INTEGER NOT NULL,
    links           JSONB NOT NULL DEFAULT '[]'
);
```

### `links` JSONB structure

Each element in the array:

```json
{
  "anchor_text": "the new release process",
  "url": "https://posthog.com/changelog"
}
```

### Indexes

```sql
-- Vector similarity search (HNSW for fast ANN)
CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Filtered retrieval by department
CREATE INDEX idx_chunks_department ON chunks (department);

-- Deduplication / upsert key
CREATE UNIQUE INDEX idx_chunks_source_section ON chunks (source_md_path, section_path);
```

---

## Ingestion Pipeline

The `ingest` service runs **once at build time** via `docker compose up --build`. It exits after completion. The API service depends on it.

### Pipeline steps

```
PDF (Sample handbook.pdf)
  |
  1. Parse PDF -> extract pages as structured text
  |
  2. Identify section boundaries (H1/H2/H3 headings)
  |
  3. Chunk by heading hierarchy
  |     - Split at H2 boundaries
  |     - If chunk > 800 tokens, split at H3
  |     - If still > 800 tokens, split at paragraph breaks
  |     - Never split mid-table or mid-code-block
  |     - Prepend heading chain as context prefix
  |
  4. Extract metadata per chunk
  |     - source_md_path: from "contents/handbook/..." line below each H1
  |     - section_path:   concatenated heading chain with " > " separator
  |     - department:     second path segment of source_md_path
  |     - page_start/end: from PDF page index
  |     - links:          extract all <a> hrefs with anchor text
  |
  5. Generate embeddings (batch)
  |     - Model: text-embedding-3-small (1536 dims) or configurable
  |     - Batch size: 100 chunks per API call
  |
  6. Upsert into postgres
        - ON CONFLICT (source_md_path, section_path) DO UPDATE
        - Allows safe re-ingestion without duplicates
```

### Docker Compose lifecycle

```yaml
services:
  ingest:
    build: ./ingest
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./data:/data  # PDF lives here
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/handbook
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    restart: "no"  # run once and exit

  api:
    build: ./api
    depends_on:
      ingest:
        condition: service_completed_successfully
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/handbook
      - REDIS_URL=redis://redis:6379/0
      - OPENAI_API_KEY=${OPENAI_API_KEY}
```

The `api` service only starts after `ingest` exits successfully, guaranteeing chunks are available before serving queries.

---

## Caching Layer (Redis)

Redis serves two purposes: **query caching** and **rate limiting**.

### 1. Query cache

Caches the final generated answer keyed by the normalized query embedding.

```
Key:    cache:query:<sha256(embedding)>
Value:  JSON string of the response payload
TTL:    3600s (1 hour)
```

**Cache logic (pseudocode):**

```
query_embedding = embed(user_question)
cache_key = "cache:query:" + sha256(query_embedding.tobytes())

cached = redis.get(cache_key)
if cached:
    return json.loads(cached)

# Cache miss — retrieve, generate, then cache
chunks = vector_search(query_embedding)
answer = llm_generate(user_question, chunks)
response = {
    "answer": answer,
    "sources": [format_citation(c) for c in chunks]
}

redis.setex(cache_key, 3600, json.dumps(response))
return response
```

**Why hash the embedding, not the raw query?**
Semantically identical questions ("What is the PR process?" vs "How do pull requests work?") produce near-identical embeddings. Hashing the quantized embedding vector deduplicates these.

### 2. Rate limiting

Sliding window rate limit per client, using Redis sorted sets.

```
Key:    ratelimit:<client_ip>
Score:  timestamp of each request
Member: unique request ID

Limit:  60 requests per 60 seconds
```

### Redis configuration

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --maxmemory 128mb --maxmemory-policy allkeys-lru
  ports:
    - "6379:6379"
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 5s
    timeout: 3s
    retries: 5
```

`allkeys-lru` eviction ensures the cache self-manages under memory pressure — stale query caches are evicted first.

---

## Citation Format

When the API returns an answer, each source chunk is cited as:

```json
{
  "answer": "Most launch emails come from the Product Marketer...",
  "sources": [
    {
      "section_path": "Email comms > Email broadcasts > Launch emails",
      "source_md_path": "contents/handbook/brand/email-comms.md",
      "department": "brand",
      "pages": "6-6",
      "links": [
        {"anchor_text": "billing@posthog.com", "url": "mailto:billing@posthog.com"}
      ],
      "excerpt": "Most product and feature launch emails come from..."
    }
  ]
}
```

---

## Environment Variables

| Variable          | Required | Description                          |
|-------------------|----------|--------------------------------------|
| `OPENAI_API_KEY`  | Yes      | For embeddings + generation          |
| `DATABASE_URL`    | Yes      | Postgres connection string           |
| `REDIS_URL`       | Yes      | Redis connection string              |
| `EMBEDDING_MODEL` | No       | Default: `text-embedding-3-small`    |
| `EMBEDDING_DIM`   | No       | Default: `1536`                      |
| `CHUNK_MAX_TOKENS`| No       | Default: `800`                       |
| `CACHE_TTL`       | No       | Default: `3600`                      |

---

## File Structure

```
surface/
  docker-compose.yml
  .env
  data/
    Sample handbook.pdf
  ingest/
    Dockerfile
    ingest.py
    requirements.txt
  api/
    Dockerfile
    main.py
    requirements.txt
  docs/
    data-model-spec.md      # this file
```
