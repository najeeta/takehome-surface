import json
import os
from collections.abc import AsyncIterator

import anthropic
from retrieval import embed, vector_search

SYSTEM_PROMPT = """You are a Q&A assistant for the PostHog company handbook.

Rules:
1. ONLY answer based on the retrieved handbook chunks. Do not use prior knowledge.
2. Cite every claim using the format: [section_path (p.X)].
3. If the retrieved context does not contain the answer, say so explicitly.
4. Include relevant links from the source chunks when they add value.
5. Keep answers concise and direct.
"""

RETRIEVE_TOOL = {
    "name": "retrieve",
    "description": "Search the PostHog handbook for relevant sections.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of chunks to retrieve (default 5)",
            },
        },
        "required": ["query"],
    },
}


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    embedding = embed(query)
    chunks = vector_search(embedding, top_k=top_k)
    return [
        {
            "text": c["text"],
            "section_path": c["section_path"],
            "source_md_path": c["source_md_path"],
            "pages": f"{c['page_start']}-{c['page_end']}",
            "links": c["links"],
        }
        for c in chunks
    ]


def handle_tool_call(name: str, input_data: dict) -> str:
    if name == "retrieve":
        result = retrieve(
            query=input_data["query"],
            top_k=input_data.get("top_k", 5),
        )
        return json.dumps(result)
    raise ValueError(f"Unknown tool: {name}")


async def run_agent(question: str) -> dict:
    """Run the agent loop (non-streaming). Returns full answer + sources."""
    client = anthropic.Anthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    messages = [{"role": "user", "content": question}]
    all_sources: list[dict] = []

    while True:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=[RETRIEVE_TOOL],
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result_str = handle_tool_call(block.name, block.input)
                    if block.name == "retrieve":
                        all_sources.extend(json.loads(result_str))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            answer = ""
            for block in response.content:
                if hasattr(block, "text"):
                    answer += block.text
            return {"answer": answer, "sources": all_sources}


async def run_agent_stream(question: str) -> AsyncIterator[tuple[str, str]]:
    """Streaming agent loop. Yields (event_type, data) tuples for SSE."""
    client = anthropic.AsyncAnthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    messages = [{"role": "user", "content": question}]

    while True:
        response_content = []
        current_tool_inputs: dict[int, dict] = {}
        current_text: dict[int, str] = {}
        stop_reason = None

        async with client.messages.stream(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=[RETRIEVE_TOOL],
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    idx = event.index
                    block = event.content_block
                    if block.type == "text":
                        current_text[idx] = ""
                    elif block.type == "tool_use":
                        current_tool_inputs[idx] = {
                            "id": block.id,
                            "name": block.name,
                            "json_str": "",
                        }

                elif event.type == "content_block_delta":
                    idx = event.index
                    delta = event.delta
                    if delta.type == "text_delta":
                        current_text[idx] = current_text.get(idx, "") + delta.text
                        yield ("delta", json.dumps(delta.text))
                    elif delta.type == "input_json_delta":
                        if idx in current_tool_inputs:
                            current_tool_inputs[idx]["json_str"] += delta.partial_json

                elif event.type == "content_block_stop":
                    idx = event.index
                    if idx in current_text:
                        response_content.append({
                            "type": "text",
                            "text": current_text[idx],
                        })
                    elif idx in current_tool_inputs:
                        tool_info = current_tool_inputs[idx]
                        parsed_input = json.loads(tool_info["json_str"]) if tool_info["json_str"] else {}
                        response_content.append({
                            "type": "tool_use",
                            "id": tool_info["id"],
                            "name": tool_info["name"],
                            "input": parsed_input,
                        })

                elif event.type == "message_delta":
                    stop_reason = event.delta.stop_reason

        if stop_reason == "tool_use":
            yield ("status", json.dumps({"step": "retrieving"}))

            tool_results = []
            for block in response_content:
                if block["type"] == "tool_use":
                    result_str = handle_tool_call(block["name"], block["input"])

                    if block["name"] == "retrieve":
                        for source in json.loads(result_str):
                            yield ("source", json.dumps({
                                "section_path": source["section_path"],
                                "source_md_path": source["source_md_path"],
                                "pages": source["pages"],
                                "links": source.get("links", []),
                                "excerpt": source["text"][:500],
                            }))

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": result_str,
                    })

            messages.append({"role": "assistant", "content": response_content})
            messages.append({"role": "user", "content": tool_results})

            yield ("status", json.dumps({"step": "generating"}))
            response_content = []
        else:
            yield ("done", "")
            return
