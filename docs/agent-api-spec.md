# Agent & API Service Specification

Companion to [data-model-spec.md](./data-model-spec.md). Covers the agent harness, LLM provider, and the FastAPI service.

---

## Architecture

```
                        +------------------+
  POST /ask  ────────>  |   FastAPI (api)   |
                        |                  |
                        |  Hermes Agent    |
                        |   ├── retrieve   | ──> pgvector
                        |   └── generate   | ──> Anthropic API
                        |                  |
                        +------------------+
                               |
                             Redis
                            (cache)
```

---

## Hermes Agent Harness

The agent is built using the Hermes SDK. Hermes manages the tool-calling loop, message history, and provider abstraction.

### References

- Hermes SDK repo: https://github.com/hermes-ai/hermes-sdk
- Quickstart: https://github.com/hermes-ai/hermes-sdk#quickstart
- Tool definitions: https://github.com/hermes-ai/hermes-sdk/blob/main/docs/tools.md
- Provider config: https://github.com/hermes-ai/hermes-sdk/blob/main/docs/providers.md

### Agent definition

```python
from hermes import Agent, Tool, Message, AnthropicProvider

provider = AnthropicProvider(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
)

agent = Agent(
    name="handbook-qa",
    system_prompt=SYSTEM_PROMPT,
    model=provider,
    tools=[retrieve_tool],
)
```

### System prompt

```python
SYSTEM_PROMPT = """You are a Q&A assistant for the PostHog company handbook.

Rules:
1. ONLY answer based on the retrieved handbook chunks. Do not use prior knowledge.
2. Cite every claim using the format: [section_path (p.X)].
3. If the retrieved context does not contain the answer, say so explicitly.
4. Include relevant links from the source chunks when they add value.
5. Keep answers concise and direct.
"""
```

### Tool: `retrieve`

The agent's single tool. Hermes calls it automatically when the agent decides it needs context.

```python
@Tool(
    name="retrieve",
    description="Search the PostHog handbook for relevant sections.",
    parameters={
        "query": {
            "type": "string",
            "description": "Natural language search query"
        },
        "top_k": {
            "type": "integer",
            "description": "Number of chunks to retrieve (default 5)",
            "optional": True
        }
    }
)
def retrieve(query: str, top_k: int = 5) -> list[dict]:
    embedding = embed(query)
    chunks = vector_search(embedding, top_k=top_k)
    return [
        {
            "text": c.text,
            "section_path": c.section_path,
            "source_md_path": c.source_md_path,
            "pages": f"{c.page_start}-{c.page_end}",
            "links": c.links,
        }
        for c in chunks
    ]
```

---

## FastAPI Service

### `POST /ask`

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Handbook Q&A Agent")

class AskRequest(BaseModel):
    question: str

class Source(BaseModel):
    section_path: str
    source_md_path: str
    pages: str
    links: list[dict]
    excerpt: str

class AskResponse(BaseModel):
    answer: str
    sources: list[Source]

@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    cached = await cache_get(req.question)
    if cached:
        return cached

    result = await agent.run(
        messages=[Message(role="user", content=req.question)]
    )

    response = parse_agent_response(result)
    await cache_set(req.question, response)
    return response
```

### Request/response example

```json
// POST /ask
{ "question": "How do we handle failed payments?" }
```

```json
{
  "answer": "PostHog follows a 5-step process for failed payments...",
  "sources": [
    {
      "section_path": "Billing > Failed/late payments",
      "source_md_path": "contents/handbook/growth/sales/billing.md",
      "pages": "505-506",
      "links": [
        {"anchor_text": "Stripe dashboard", "url": "https://dashboard.stripe.com"}
      ],
      "excerpt": "We define late payments as follows..."
    }
  ]
}
```

### Health check

```python
@app.get("/health")
async def health():
    return {
        "status": "ok" if await check_postgres() and await check_redis() else "degraded",
        "postgres": await check_postgres(),
        "redis": await check_redis(),
    }
```

---

## Docker Compose (full stack)

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: handbook
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d handbook"]
      interval: 5s
      timeout: 3s
      retries: 5

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

  ingest:
    build: ./ingest
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./data:/data
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/handbook
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    restart: "no"

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
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - ANTHROPIC_MODEL=${ANTHROPIC_MODEL:-claude-sonnet-4-6}
      - OPENAI_API_KEY=${OPENAI_API_KEY}

volumes:
  pgdata:
```

### Startup

```bash
docker compose up --build
```

---

## Environment Variables

| Variable           | Required | Description                             |
|--------------------|----------|-----------------------------------------|
| `ANTHROPIC_API_KEY`| Yes      | Anthropic API key for generation        |
| `OPENAI_API_KEY`   | Yes      | OpenAI API key for embeddings           |
| `ANTHROPIC_MODEL`  | No       | Default: `claude-sonnet-4-6`            |
| `DATABASE_URL`     | Yes      | Postgres connection string              |
| `REDIS_URL`        | Yes      | Redis connection string                 |
| `EMBEDDING_MODEL`  | No       | Default: `text-embedding-3-small`       |
| `EMBEDDING_DIM`    | No       | Default: `1536`                         |
| `CACHE_TTL`        | No       | Default: `3600`                         |

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
    main.py           # FastAPI app + /ask endpoint
    agent.py          # Hermes agent + retrieve tool
    retrieval.py      # pgvector search
    cache.py          # Redis cache helpers
    models.py         # Pydantic schemas
    requirements.txt
  docs/
    data-model-spec.md
    agent-api-spec.md # this file
```
