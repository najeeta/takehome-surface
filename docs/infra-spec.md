# Infrastructure Specification

Companion to [data-model-spec.md](./data-model-spec.md), [agent-api-spec.md](./agent-api-spec.md), and [frontend-spec.md](./frontend-spec.md). This is the canonical source of truth for running the stack.

---

## Service Dependency Graph

```
postgres ──────┐
               ├──> ingest (run-once) ──┐
               │                        ├──> api ──> web
redis ─────────────────────────────────-┘
```

---

## Docker Compose (canonical)

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-user}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-pass}
      POSTGRES_DB: ${POSTGRES_DB:-handbook}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-user} -d ${POSTGRES_DB:-handbook}"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 128mb --maxmemory-policy allkeys-lru
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
      - ./data:/data:ro
    environment:
      - DATABASE_URL=postgresql://${POSTGRES_USER:-user}:${POSTGRES_PASSWORD:-pass}@postgres:5432/${POSTGRES_DB:-handbook}
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
      - DATABASE_URL=postgresql://${POSTGRES_USER:-user}:${POSTGRES_PASSWORD:-pass}@postgres:5432/${POSTGRES_DB:-handbook}
      - REDIS_URL=redis://redis:6379/0
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - ANTHROPIC_MODEL=${ANTHROPIC_MODEL:-claude-sonnet-4-6}
      - OPENAI_API_KEY=${OPENAI_API_KEY}

  web:
    build: ./web
    depends_on:
      - api
    ports:
      - "3000:3000"
    environment:
      - API_URL=http://api:8000

volumes:
  pgdata:
```

---

## Networking

All services join the default Compose bridge network. Communication is internal by hostname.

| From     | To         | URL                              | Purpose              |
|----------|------------|----------------------------------|----------------------|
| ingest   | postgres   | `postgresql://postgres:5432`     | Write chunks         |
| api      | postgres   | `postgresql://postgres:5432`     | Read chunks          |
| api      | redis      | `redis://redis:6379`             | Cache get/set        |
| web      | api        | `http://api:8000`                | SSR action calls     |

**Exposed to host:**

| Service | Host port | Purpose          |
|---------|-----------|------------------|
| api     | 8000      | Direct API access |
| web     | 3000      | Browser UI        |

Postgres and Redis are internal only. No host ports exposed for them.

---

## Dockerfiles

### `ingest/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "ingest.py"]
```

Single stage. Runs once and exits.

### `api/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Single stage. Long-running process.

### `web/Dockerfile`

```dockerfile
# Build stage
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Runtime stage
FROM node:22-alpine
WORKDIR /app
COPY --from=build /app/build ./build
COPY --from=build /app/package.json ./
COPY --from=build /app/node_modules ./node_modules
CMD ["node", "build/server/index.js"]
EXPOSE 3000
```

Multi-stage. Build stage installs deps and compiles; runtime stage copies only the output. Keeps the final image small.

---

## Volumes & Persistence

| Volume/Mount      | Type         | Persists across restarts | Purpose                        |
|-------------------|--------------|--------------------------|--------------------------------|
| `pgdata`          | Named volume | Yes                      | Postgres data (chunks table)   |
| `./data:/data:ro` | Bind mount   | N/A (read-only)          | Source PDF for ingest          |

Redis is ephemeral. Cache loss on restart is acceptable — queries re-populate it.

---

## Startup Sequencing

```
1. postgres starts, healthcheck polls pg_isready
2. redis starts, healthcheck polls redis-cli ping
3. ingest starts after postgres is healthy
   - Parses PDF, generates embeddings, writes to postgres
   - Exits with code 0 on success
4. api starts after ingest completes successfully AND postgres + redis are healthy
   - Connects to postgres (read) and redis (cache)
   - Serves on :8000
5. web starts after api is running
   - SSR actions call api:8000
   - Serves on :3000
```

If ingest fails (non-zero exit), api and web never start. Fix the issue and re-run `docker compose up --build`.

---

## Environment Variables (.env template)

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Optional (defaults shown)
ANTHROPIC_MODEL=claude-sonnet-4-6
POSTGRES_USER=user
POSTGRES_PASSWORD=pass
POSTGRES_DB=handbook
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
CACHE_TTL=3600
```

### Per-service usage

| Variable           | ingest | api | web |
|--------------------|--------|-----|-----|
| OPENAI_API_KEY     | x      | x   |     |
| ANTHROPIC_API_KEY  |        | x   |     |
| ANTHROPIC_MODEL    |        | x   |     |
| DATABASE_URL       | x      | x   |     |
| REDIS_URL          |        | x   |     |
| API_URL            |        |     | x   |

---

## Build-time vs Runtime

| Concern                          | When       | Service |
|----------------------------------|------------|---------|
| PDF parsing + chunking           | Build-time | ingest  |
| Embedding generation             | Build-time | ingest  |
| Chunk upsert to postgres         | Build-time | ingest  |
| npm build (React Router SSR)     | Build-time | web     |
| Agent query + LLM generation     | Runtime    | api     |
| Vector similarity search         | Runtime    | api     |
| Redis cache read/write           | Runtime    | api     |
| SSR rendering + action handling  | Runtime    | web     |

"Build-time" here means during `docker compose up --build`, before the service starts accepting traffic. Not during `docker build` (image creation).

---

## Commands

```bash
# Start everything (first run pulls images, builds, ingests, then serves)
docker compose up --build

# Restart just the API (after code change)
docker compose up --build api

# Re-ingest the PDF (after replacing data/Sample handbook.pdf)
docker compose up --build ingest && docker compose restart api

# Tear down everything including data
docker compose down -v

# Logs
docker compose logs -f api web
```
