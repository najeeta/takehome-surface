# Surface — Handbook Q&A

A RAG-powered Q&A interface for the PostHog company handbook. Ask natural language questions and get grounded answers with citations, streamed in real time.

For architecture details, see [docs/architecture.md](docs/architecture.md).

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- An [Anthropic API key](https://console.anthropic.com/) (for answer generation)
- An [OpenAI API key](https://platform.openai.com/api-keys) (for embeddings)

---

## Quick Start

### 1. Clone and configure

```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys:

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

### 2. Add the handbook PDF

Place the PDF in the `data/` directory:

```
data/Sample handbook.pdf
```

### 3. Start the stack

```bash
docker compose up --build
```

This will:

1. Start PostgreSQL (with pgvector) and Redis
2. Run the ingestion pipeline — parses the PDF, chunks it, generates embeddings, and loads them into Postgres
3. Start the FastAPI API server on port 8000
4. Start the React web app on port 3000

Once everything is up, open **http://localhost:3000** in your browser.

---

## Services

| Service    | Port | Description                                    |
|------------|------|------------------------------------------------|
| `postgres` | -    | pgvector database (internal only)              |
| `redis`    | -    | Query cache (internal only)                    |
| `ingest`   | -    | Run-once pipeline: PDF → chunks → embeddings   |
| `api`      | 8000 | FastAPI — `/ask`, `/ask/stream`, `/health`      |
| `web`      | 3000 | React Router v7 SSR frontend                   |

---

## Common Operations

### Restart just the API (after code changes)

```bash
docker compose up --build api
```

### Re-ingest the PDF (after replacing the file in `data/`)

```bash
docker compose up --build ingest && docker compose restart api
```

### View logs

```bash
docker compose logs -f api web
```

### Tear down everything (including data)

```bash
docker compose down -v
```

---

## API Endpoints

### `POST /ask`

Synchronous endpoint. Returns the full answer with sources after processing.

```bash
curl -X POST http://localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "How do we handle failed payments?"}'
```

Response:

```json
{
  "answer": "PostHog follows a 5-step process...",
  "sources": [
    {
      "section_path": "Billing > Failed/late payments",
      "source_md_path": "contents/handbook/growth/sales/billing.md",
      "pages": "505-506",
      "links": [],
      "excerpt": "We define late payments as follows..."
    }
  ]
}
```

### `POST /ask/stream`

Streaming endpoint. Returns Server-Sent Events with token-by-token text, sources, and status updates.

```bash
curl -N -X POST http://localhost:8000/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"question": "What is the PR review process?"}'
```

SSE event types:

| Event    | Data                        | Description                     |
|----------|-----------------------------|---------------------------------|
| `status` | `{"step": "retrieving"}`    | Agent is searching the handbook |
| `status` | `{"step": "generating"}`    | Agent is writing the answer     |
| `source` | JSON source object          | A citation from the handbook    |
| `delta`  | JSON-encoded text fragment  | Incremental answer text         |
| `done`   | (empty)                     | Stream complete                 |
| `error`  | `{"detail": "..."}`         | Error message                   |

### `GET /health`

Returns service health status.

---

## Environment Variables

| Variable           | Required | Default                  | Description                  |
|--------------------|----------|--------------------------|------------------------------|
| `ANTHROPIC_API_KEY`| Yes      | -                        | Anthropic API key            |
| `OPENAI_API_KEY`   | Yes      | -                        | OpenAI API key (embeddings)  |
| `ANTHROPIC_MODEL`  | No       | `claude-sonnet-4-6`      | Model for answer generation  |
| `POSTGRES_USER`    | No       | `user`                   | Postgres username            |
| `POSTGRES_PASSWORD`| No       | `pass`                   | Postgres password            |
| `POSTGRES_DB`      | No       | `handbook`               | Postgres database name       |
| `EMBEDDING_MODEL`  | No       | `text-embedding-3-small` | OpenAI embedding model       |
| `EMBEDDING_DIM`    | No       | `1536`                   | Embedding dimensions         |
| `CACHE_TTL`        | No       | `3600`                   | Redis cache TTL (seconds)    |

---

## Project Structure

```
surface/
├── docker-compose.yml
├── .env.example
├── data/                        # Place handbook PDF here
├── ingest/
│   ├── Dockerfile
│   ├── schema.sql               # pgvector schema
│   ├── ingest.py                # PDF → chunk → embed → upsert
│   └── requirements.txt
├── api/
│   ├── Dockerfile
│   ├── main.py                  # FastAPI app
│   ├── agent.py                 # Anthropic agent with retrieve tool
│   ├── retrieval.py             # Embedding + vector search
│   ├── cache.py                 # Redis cache helpers
│   ├── models.py                # Pydantic schemas
│   └── requirements.txt
├── web/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── react-router.config.ts
│   └── app/
│       ├── root.tsx
│       ├── routes.ts
│       ├── routes/
│       │   ├── chat.tsx         # Main chat page
│       │   └── ask-stream.tsx   # SSE proxy route
│       ├── hooks/
│       │   └── useStreamingChat.ts
│       ├── components/
│       │   ├── Header.tsx
│       │   ├── ChatThread.tsx
│       │   ├── Message.tsx      # Markdown rendering
│       │   └── SourcePanel.tsx  # Citation cards
│       └── styles/
│           ├── tokens.css       # Design system
│           └── app.css          # Tailwind + markdown styles
└── docs/
    ├── architecture.md          # System design
    ├── data-model-spec.md
    ├── agent-api-spec.md
    ├── frontend-spec.md
    ├── infra-spec.md
    └── implementation-plan.md
```
