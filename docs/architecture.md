# System Architecture

Surface is a Retrieval-Augmented Generation (RAG) system that indexes a PDF handbook and serves grounded Q&A responses with citations. The stack runs entirely via Docker Compose.

---

## High-Level Overview

```
                    Browser (:3000)
                        │
                        ▼
               ┌─────────────────┐
               │   Web (SSR)     │  React Router v7 + Tailwind
               │   Node 22       │  Streams responses via SSE proxy
               └────────┬────────┘
                        │  HTTP / SSE
                        ▼
               ┌─────────────────┐
               │   API Server    │  FastAPI + Uvicorn
               │   Python 3.12   │  /ask, /ask/stream, /health
               └──┬──────┬───┬──┘
                  │      │   │
          ┌───────┘      │   └───────┐
          ▼              ▼           ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ Postgres │  │  Redis   │  │ Anthropic│
    │ pgvector │  │  Cache   │  │ Claude   │
    └──────────┘  └──────────┘  └──────────┘
          ▲
          │  (build-time)
    ┌─────┴──────┐
    │   Ingest   │  PDF → chunks → embeddings → pgvector
    └────────────┘
```

---

## Data Flow

### Ingestion (build-time, runs once)

```
PDF file
  │
  ├─ 1. Parse ──────── pymupdf extracts pages as structured text
  │
  ├─ 2. Detect ─────── Identify H1/H2/H3 headings by font size/weight
  │
  ├─ 3. Chunk ──────── Split at H2 boundaries
  │                    If chunk > 800 tokens → split at H3
  │                    If still > 800 → split at paragraphs
  │                    Never split mid-table or mid-code-block
  │                    Prepend heading chain as context prefix
  │
  ├─ 4. Metadata ───── Extract source_md_path, section_path,
  │                    department, page range, links
  │
  ├─ 5. Embed ──────── OpenAI text-embedding-3-small (1536 dims)
  │                    Batch size: 100 chunks per API call
  │
  └─ 6. Upsert ─────── INSERT INTO chunks ON CONFLICT DO UPDATE
                       (source_md_path, section_path) as dedup key
```

### Query (runtime, per request)

```
User question
  │
  ├─ 1. Cache check ──── SHA256(embedding) → Redis lookup
  │     ├─ HIT: return cached response
  │     └─ MISS: continue
  │
  ├─ 2. Agent loop ───── Anthropic Claude with tool use
  │     │
  │     ├─ Claude decides to call `retrieve` tool
  │     │     ├─ Embed query → OpenAI
  │     │     ├─ Vector search → pgvector (cosine similarity)
  │     │     └─ Return top-k chunks to Claude
  │     │
  │     └─ Claude generates grounded answer with citations
  │
  ├─ 3. Cache set ────── Store response in Redis (TTL: 1 hour)
  │
  └─ 4. Return ────────── JSON response or SSE stream
```

---

## Services

### PostgreSQL + pgvector

Stores document chunks with vector embeddings for similarity search.

**Schema:**

| Column          | Type          | Description                              |
|-----------------|---------------|------------------------------------------|
| `id`            | UUID          | Primary key                              |
| `text`          | TEXT          | Chunk content                            |
| `embedding`     | vector(1536)  | OpenAI embedding                         |
| `source_md_path`| TEXT          | Original file path in handbook           |
| `section_path`  | TEXT          | Heading chain (e.g. "Culture > Values")  |
| `department`    | TEXT          | Extracted from source path               |
| `page_start`    | INTEGER       | PDF page range start                     |
| `page_end`      | INTEGER       | PDF page range end                       |
| `links`         | JSONB         | Extracted hyperlinks with anchor text    |

**Indexes:**

- HNSW index on `embedding` with `vector_cosine_ops` for fast approximate nearest neighbor search
- B-tree index on `department` for filtered retrieval
- Unique index on `(source_md_path, section_path)` for idempotent upserts

### Redis

Caches query results to avoid redundant LLM calls.

- **Key format:** `cache:query:<sha256(embedding_bytes)>`
- **Value:** JSON-serialized response payload
- **TTL:** 3600 seconds (configurable)
- **Eviction:** `allkeys-lru` with 128MB max memory

Hashing the embedding (not the raw query text) deduplicates semantically identical questions.

### API Server (FastAPI)

Three endpoints:

| Endpoint        | Method | Description                                          |
|-----------------|--------|------------------------------------------------------|
| `/ask`          | POST   | Synchronous — returns full response after processing |
| `/ask/stream`   | POST   | Streaming — returns SSE with token-by-token text     |
| `/health`       | GET    | Checks Postgres and Redis connectivity               |

**Agent architecture:**

The API uses the Anthropic SDK directly with tool use. The agent loop:

1. Send the user question to Claude with a `retrieve` tool definition
2. Claude calls the tool → API embeds the query and runs pgvector search
3. Tool results (chunks) are sent back to Claude
4. Claude generates a grounded answer citing the chunks
5. If Claude calls the tool again (refinement), repeat from step 2

For streaming, each iteration uses `client.messages.stream()` instead of `client.messages.create()`, yielding text deltas as SSE events.

### Web (React Router v7)

Server-side rendered React application with a single route.

**Key components:**

| Component       | Role                                                    |
|-----------------|---------------------------------------------------------|
| `ChatThread`    | Scrollable message list with auto-scroll                |
| `Message`       | Renders user text or assistant markdown (react-markdown) |
| `SourcePanel`   | Right panel with numbered citation cards                |
| `Header`        | App header with logo and title                          |

**Streaming flow:**

1. User submits a question via `<form>`
2. `useStreamingChat` hook sends a `POST /ask/stream` to the web server
3. The `ask-stream` resource route proxies the request to the API server
4. SSE events flow back: `status` → `source` → `delta` (repeated) → `done`
5. The hook updates React state on each delta, re-rendering the markdown progressively

---

## Startup Sequence

```
1. postgres starts → healthcheck: pg_isready
2. redis starts → healthcheck: redis-cli ping
3. ingest starts (after postgres healthy)
   → Parses PDF, generates embeddings, writes chunks
   → Exits with code 0
4. api starts (after ingest exits 0, postgres + redis healthy)
   → Serves on :8000
5. web starts (after api)
   → Serves on :3000
```

If `ingest` fails, `api` and `web` never start.

---

## Network Topology

All services share the default Docker Compose bridge network.

```
┌────────────────────────────────────────────┐
│              Docker Network                │
│                                            │
│  postgres:5432 ◄──── ingest (build-time)   │
│       ▲              api (runtime)         │
│       │                                    │
│  redis:6379 ◄──────── api                  │
│                                            │
│  api:8000 ◄────────── web                  │
│                                            │
│  Exposed to host:                          │
│    api  → localhost:8000                   │
│    web  → localhost:3000                   │
└────────────────────────────────────────────┘
```

Postgres and Redis have no host port bindings — they are internal only.

---

## Technology Choices

| Concern           | Choice                     | Rationale                                           |
|-------------------|----------------------------|-----------------------------------------------------|
| Vector store      | pgvector (PostgreSQL)      | Single database for vectors + metadata, HNSW index  |
| Embedding model   | text-embedding-3-small     | Good quality/cost ratio, 1536 dimensions            |
| LLM               | Claude (Anthropic)         | Strong instruction following, tool use support      |
| PDF parsing       | pymupdf                    | Fast, handles complex layouts, font metadata access |
| API framework     | FastAPI                    | Async, auto-docs, Pydantic integration              |
| Cache             | Redis                      | Fast, TTL support, LRU eviction                     |
| Frontend          | React Router v7 (SSR)      | Server actions, streaming, SSR out of the box       |
| Styling           | Tailwind CSS v4            | Utility-first, fast iteration                       |
| Markdown          | react-markdown + remark-gfm| GFM tables, code blocks, lists                     |
| Container runtime | Docker Compose             | Single-command full stack, health checks            |
