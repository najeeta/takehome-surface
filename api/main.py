import json
import os

import psycopg2
import redis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from cache import cache_get, cache_set
from models import AskRequest, AskResponse, Source

app = FastAPI(title="Surface RAG Q&A API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    cached = cache_get(req.question)
    if cached is not None:
        return AskResponse(**cached)

    try:
        from agent import run_agent

        result = await run_agent(req.question)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}") from exc

    sources = [
        Source(
            section_path=s["section_path"],
            source_md_path=s["source_md_path"],
            pages=s["pages"],
            links=s.get("links", []),
            excerpt=s["text"][:500],
        )
        for s in result["sources"]
    ]
    response = AskResponse(answer=result["answer"], sources=sources)

    cache_set(req.question, response.model_dump())
    return response


@app.post("/ask/stream")
async def ask_stream(req: AskRequest):
    from agent import run_agent_stream

    async def event_generator():
        try:
            async for event_type, data in run_agent_stream(req.question):
                yield f"event: {event_type}\ndata: {data}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
async def health():
    status: dict = {"postgres": False, "redis": False}

    try:
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        status["postgres"] = True
    except Exception:
        pass

    try:
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        r.ping()
        status["redis"] = True
    except Exception:
        pass

    if not all(status.values()):
        raise HTTPException(status_code=503, detail=status)

    return {"status": "ok", **status}
