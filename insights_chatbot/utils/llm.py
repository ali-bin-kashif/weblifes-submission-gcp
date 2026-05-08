"""
Agentic loop: Claude ↔ BigQuery via tool use with streaming.

Flow per turn:
  1. Open a streaming request to Claude.
  2. Yield text_chunk events as tokens arrive (these go straight to the UI).
  3. After the stream completes, inspect the final message for tool calls.
  4. If tool calls present: execute SQL on BigQuery, yield sql/result events, loop.
  5. If no tool calls (end_turn): text was already streamed — return.

Event types yielded:
  {"type": "text_chunk", "content": <token>}     — stream directly to the UI message
  {"type": "sql",        "content": <sql>}        — Claude issued a BQ query
  {"type": "result",     "content": <result>}     — BQ returned data
  {"type": "error",      "content": <message>}    — BQ or validation error
"""

from typing import AsyncGenerator

import anthropic

from utils.bq_client import BigQueryClient, BQQueryError
from utils.config import Config
from utils.schema import TOOLS, get_system_prompt

_MAX_TOOL_ROUNDS = 5  # prevent runaway loops


async def run_agent(
    question: str,
    history: list[dict],
    config: Config,
    bq: BigQueryClient,
) -> AsyncGenerator[dict, None]:
    """
    Runs the Claude ↔ BigQuery agentic loop with streaming.
    Text tokens are yielded immediately as text_chunk events.
    Tool call events (sql, result, error) appear between streaming turns.
    """
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    messages = history + [{"role": "user", "content": question}]

    for _ in range(_MAX_TOOL_ROUNDS):
        async with client.messages.stream(
            model=config.CLAUDE_MODEL,
            max_tokens=2048,
            system=get_system_prompt(),
            tools=TOOLS,
            messages=messages,
        ) as stream:
            # Stream text tokens as they arrive
            async for text in stream.text_stream:
                yield {"type": "text_chunk", "content": text}

            # After stream completes, get the full response to check for tool calls
            final = await stream.get_final_message()

        tool_use_blocks = [b for b in final.content if b.type == "tool_use"]

        if not tool_use_blocks:
            # end_turn with no tools — all text already streamed
            return

        # Tool call turn — execute queries and feed results back
        messages.append({"role": "assistant", "content": final.content})
        tool_results = []

        for block in tool_use_blocks:
            sql = block.input.get("sql", "")
            yield {"type": "sql", "content": sql}

            try:
                result = bq.run_query(sql)
                yield {"type": "result", "content": result}
            except BQQueryError as exc:
                result = f"Query error: {exc}"
                yield {"type": "error", "content": result}

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    yield {"type": "text_chunk", "content": "I reached the query limit without a complete answer. Please try rephrasing your question."}