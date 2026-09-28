import os

import openai
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ["DATABASE_URL"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

_client = openai.OpenAI(api_key=OPENAI_API_KEY)


def embed(text: str) -> list[float]:
    """Generate an embedding for the given text using OpenAI."""
    response = _client.embeddings.create(input=text, model=EMBEDDING_MODEL)
    return response.data[0].embedding


def vector_search(embedding: list[float], top_k: int = 5) -> list[dict]:
    """Query pgvector for the most similar chunks using cosine similarity."""
    embedding_str = str(embedding)
    query = """
        SELECT id, text, source_md_path, section_path, department, page_start, page_end, links,
               1 - (embedding <=> %s::vector) AS similarity
        FROM chunks
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (embedding_str, embedding_str, top_k))
            rows = cur.fetchall()
    finally:
        conn.close()

    results = []
    for row in rows:
        result = dict(row)
        result["id"] = str(result["id"])
        # Ensure links is a Python list (psycopg2 auto-deserialises JSONB)
        if isinstance(result["links"], str):
            import json
            result["links"] = json.loads(result["links"])
        results.append(result)
    return results
