# Implementation Plan

Builds the full stack defined across [data-model-spec.md](./data-model-spec.md), [agent-api-spec.md](./agent-api-spec.md), [frontend-spec.md](./frontend-spec.md), and [infra-spec.md](./infra-spec.md) using agent swarms.

---

## 1. Dependency Graph

```
Phase 0: Scaffolding
    │
    ├──────────────────────┐
    v                      v
Phase 1A: Data Layer    Phase 1B: Frontend Scaffold
    │                      │
    v                      │
Phase 2A: API Service      │
Phase 2B: Agent Harness    │
    │                      │
    v                      v
Phase 3: Frontend ← API Integration
    │
    v
Phase 4: Docker Compose + E2E
```

**Critical path:** Phase 0 → 1A → 2 → 3 → 4

Phase 1B runs off the critical path, in parallel with 1A.

---

## 2. Phases

### Phase 0 — Project Scaffolding

One agent. Sets up the shared skeleton that all other agents build into.

| Task         | Deliverable                                                                 | Complexity |
|--------------|-----------------------------------------------------------------------------|------------|
| Scaffold     | `docker-compose.yml`, `.env`, `ingest/`, `api/`, `web/` dirs, `.gitignore` | Small      |

**Files produced:**
```
docker-compose.yml          # from infra-spec.md (canonical)
.env.example                # from infra-spec.md (.env template)
.gitignore
ingest/Dockerfile
ingest/requirements.txt
api/Dockerfile
api/requirements.txt
web/Dockerfile
web/package.json
web/react-router.config.ts
data/                       # empty dir, user places PDF here
```

**Reads:** `infra-spec.md`

### Phase 1A — Data Layer (postgres + ingest pipeline)

One agent. Builds the ingestion pipeline that parses the PDF and populates pgvector.

| Task           | Deliverable                              | Complexity |
|----------------|------------------------------------------|------------|
| SQL schema     | `ingest/schema.sql`                      | Small      |
| Ingest script  | `ingest/ingest.py`                       | Large      |

**Files produced:**
```
ingest/schema.sql           # CREATE EXTENSION, CREATE TABLE, CREATE INDEX
ingest/ingest.py            # PDF parse → chunk → embed → upsert
ingest/requirements.txt     # pymupdf, openai, psycopg2-binary, tiktoken
```

**Reads:** `data-model-spec.md` (schema, chunking rules, pipeline steps)

### Phase 1B — Frontend Scaffold (parallel with 1A)

One agent. Sets up the React Router v7 app with SSR, routing, components, and design system. No API integration yet — uses mock data.

| Task             | Deliverable                                       | Complexity |
|------------------|---------------------------------------------------|------------|
| App shell        | `web/app/root.tsx`, `web/app/routes.ts`           | Small      |
| Design tokens    | `web/app/styles/tokens.css`, `web/app/styles/app.css` | Small |
| Components       | All 6 components in `web/app/components/`         | Medium     |
| Chat route       | `web/app/routes/chat.tsx` (mock action)           | Medium     |

**Files produced:**
```
web/app/root.tsx
web/app/routes.ts
web/app/routes/chat.tsx         # action returns mock data for now
web/app/components/Header.tsx
web/app/components/ChatThread.tsx
web/app/components/Message.tsx
web/app/components/SourceChip.tsx
web/app/components/SourcePanel.tsx
web/app/components/MessageInput.tsx
web/app/styles/tokens.css       # CSS custom properties
web/app/styles/app.css          # Tailwind directives
web/tailwind.config.ts
web/tsconfig.json
```

**Reads:** `frontend-spec.md` (layout, component tree, design system, route/action pattern)

### Phase 2 — API + Agent Harness

Two agents in parallel. Both depend on Phase 1A (need the schema to exist).

**Agent 2A — API Service:**

| Task          | Deliverable                                      | Complexity |
|---------------|--------------------------------------------------|------------|
| FastAPI app   | `api/main.py`                                    | Small      |
| Pydantic models | `api/models.py`                                | Small      |
| Retrieval     | `api/retrieval.py`                               | Medium     |
| Cache         | `api/cache.py`                                   | Small      |

**Files produced:**
```
api/main.py             # FastAPI app, /ask endpoint, /health
api/models.py           # AskRequest, AskResponse, Source
api/retrieval.py        # embed(), vector_search()
api/cache.py            # cache_get(), cache_set()
api/requirements.txt    # fastapi, uvicorn, psycopg2-binary, redis, openai
```

**Reads:** `agent-api-spec.md` (endpoint, models, cache logic), `data-model-spec.md` (chunks table schema)

**Agent 2B — Agent Harness:**

| Task          | Deliverable                    | Complexity |
|---------------|--------------------------------|------------|
| Hermes agent  | `api/agent.py`                 | Medium     |

**Files produced:**
```
api/agent.py            # Agent definition, system prompt, retrieve tool, provider config
```

**Reads:** `agent-api-spec.md` (Hermes agent definition, tool spec, system prompt, provider config)

Note: Agent 2B produces `agent.py` which is imported by `main.py` (produced by 2A). The contract between them is the `agent.run()` interface and the `parse_agent_response()` function. Agent 2A owns the function signature; 2B owns the agent instance.

### Phase 3 — Frontend API Integration

One agent. Replaces mock data in the chat route with the real API action.

| Task                | Deliverable                          | Complexity |
|---------------------|--------------------------------------|------------|
| Connect action      | Update `web/app/routes/chat.tsx`     | Small      |

**Changes:**
- Replace mock action with real `fetch(API_URL/ask)` call
- Wire SourceChip click → SourcePanel state
- Handle loading/error states

**Reads:** `frontend-spec.md` (action definition), `agent-api-spec.md` (response shape)

### Phase 4 — Docker Compose Integration + E2E

One agent. Wires everything together and validates the full stack.

| Task                   | Deliverable                          | Complexity |
|------------------------|--------------------------------------|------------|
| Finalize compose       | Update `docker-compose.yml` if needed | Small     |
| E2E smoke test         | Manual or scripted validation         | Small     |

**Reads:** `infra-spec.md`, all other specs

---

## 3. Agent Assignments

| Phase | Agents | Concurrent | Assignment                         |
|-------|--------|------------|------------------------------------|
| 0     | 1      | 1          | Scaffold entire project            |
| 1     | 2      | 2          | 1A: ingest pipeline, 1B: frontend  |
| 2     | 2      | 2          | 2A: API service, 2B: agent harness |
| 3     | 1      | 1          | Frontend ← API wiring              |
| 4     | 1      | 1          | Integration + validation           |

**Total: 7 agent runs, max 2 concurrent.**

---

## 4. Sequencing Rules

| Rule | Constraint                                     | Reason                                                              |
|------|-------------------------------------------------|---------------------------------------------------------------------|
| S1   | Phase 1A after Phase 0                         | Needs `ingest/` dir and `Dockerfile` to exist                       |
| S2   | Phase 1B after Phase 0                         | Needs `web/` dir and `package.json` to exist                        |
| S3   | Phase 1A and 1B run in parallel                | No dependencies between them                                        |
| S4   | Agent 2A after Phase 1A completes              | Retrieval queries must match the chunks table schema                |
| S5   | Agent 2B after Phase 1A completes              | Retrieve tool returns chunk fields defined by the schema            |
| S6   | Agents 2A and 2B run in parallel               | They produce separate files (`main.py` vs `agent.py`)              |
| S7   | Phase 3 after Phase 2 completes                | Frontend action calls the API — needs the response contract finalized |
| S8   | Phase 4 after Phase 3 completes                | E2E requires all services to be buildable                           |

---

## 5. Integration Points

| Contract                | Producer   | Consumer  | Verification                                                  |
|-------------------------|------------|-----------|---------------------------------------------------------------|
| Chunks table schema     | Phase 1A   | Phase 2A  | `SELECT * FROM chunks LIMIT 1` returns expected columns       |
| Embedding dimensions    | ingest     | api       | Ingest writes `vector(1536)`, retrieval queries same dimension |
| `/ask` request/response | Phase 2A   | Phase 3   | POST `{"question":"..."}` returns `{"answer":"...","sources":[...]}` |
| `agent.run()` interface | Phase 2B   | Phase 2A  | `main.py` imports agent from `agent.py` and calls `agent.run()` |
| Docker networking       | Phase 0    | Phase 4   | `web` can reach `api:8000`, `api` can reach `postgres:5432` and `redis:6379` |

---

## 6. Validation Gates

### After Phase 0
- [ ] `docker compose config` parses without errors
- [ ] All directories exist: `ingest/`, `api/`, `web/`, `data/`
- [ ] `.env.example` contains all required variables

### After Phase 1A
- [ ] `docker compose up postgres` starts and is healthy
- [ ] `docker compose up ingest` exits with code 0
- [ ] `SELECT count(*) FROM chunks` returns > 0
- [ ] Chunks have all expected fields populated (no nulls in required columns)

### After Phase 1B
- [ ] `cd web && npm install && npm run build` succeeds
- [ ] `npm run dev` serves on :3000
- [ ] Chat page renders with mock data — message input, thread, source panel

### After Phase 2
- [ ] `docker compose up api` starts and is healthy
- [ ] `GET /health` returns `{"status": "ok"}`
- [ ] `POST /ask {"question": "How do we handle failed payments?"}` returns valid `AskResponse`
- [ ] Response contains non-empty `sources` array with `section_path`, `pages`, `excerpt`
- [ ] Second identical request is served from Redis cache (faster response, check logs)

### After Phase 3
- [ ] Chat page action calls real API and renders the response
- [ ] Source chips appear in assistant messages
- [ ] Clicking a source chip populates the source panel

### After Phase 4
- [ ] `docker compose up --build` from clean state brings up all 5 services
- [ ] `curl localhost:3000` returns the chat page HTML
- [ ] `curl -X POST localhost:8000/ask -H 'Content-Type: application/json' -d '{"question":"What is PostHog culture?"}'` returns grounded answer
- [ ] Full round-trip works through the browser: type question → see answer with citations → click source → see excerpt

---

## Execution Summary

```
Agent 0 (scaffold)
    │
    ├─────────────────┐
    v                 v
Agent 1A (ingest)   Agent 1B (frontend)    ← parallel
    │                 │
    ├────────┐        │
    v        v        │
Agent 2A   Agent 2B   │                    ← parallel
    │        │        │
    v────────v        │
         │            │
         v            v
      Agent 3 (wire frontend to API)
         │
         v
      Agent 4 (integration + E2E)
```

7 agent runs. 3 sequential gates. 2 parallelization opportunities. Critical path length: 5 phases.
