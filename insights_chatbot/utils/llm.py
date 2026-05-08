"""
Claude ↔ BigQuery agentic loop with streaming.

Flow per turn:
  1. Open a streaming request to Claude with the conversation history and tools.
  2. Yield text_chunk events as tokens arrive — these go straight to the UI.
  3. After the stream ends, inspect the final message for tool_use blocks.
  4. If tool calls are present: execute each SQL query, yield sql/result/error
     events, append results to the message history, and loop.
  5. If no tool calls (end_turn): all text is already streamed — return.

Events yielded:
  {"type": "text_chunk", "content": <token>}   — stream directly to the UI message
  {"type": "sql",        "content": <sql>}      — Claude issued a BigQuery query
  {"type": "result",     "content": <result>}   — BigQuery returned data
  {"type": "error",      "content": <message>}  — validation or execution error
"""

from typing import AsyncGenerator

import anthropic

from utils.bq_client import BigQueryClient, BQQueryError
from utils.config import Config
from utils.schema import TOOLS, get_system_prompt

# Cap the number of tool-call rounds per user message to avoid runaway loops
# in cases where Claude keeps issuing queries without reaching a conclusion.
_MAX_TOOL_ROUNDS = 5


async def run_agent(
    question: str,
    history: list[dict],
    config: Config,
    bq: BigQueryClient,
) -> AsyncGenerator[dict, None]:
    """
    Run the Claude ↔ BigQuery agentic loop for a single user message.

    Streams text tokens to the caller as they arrive and yields structured
    events for each SQL query and its result. The caller (app.py) maps these
    events to Chainlit UI elements.

    Args:
        question: The user's current message.
        history:  Prior turns as a list of {"role": ..., "content": ...} dicts.
        config:   Runtime configuration (API keys, model, etc.).
        bq:       Initialised BigQuery client for executing queries.

    Yields:
        Event dicts with a "type" key and a "content" key (see module docstring).
    """
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    # Prepend history so Claude has conversation context for follow-up questions
    messages = history + [{"role": "user", "content": question}]

    for _ in range(_MAX_TOOL_ROUNDS):
        async with client.messages.stream(
            model=config.CLAUDE_MODEL,
            max_tokens=2048,
            system=get_system_prompt(),
            tools=TOOLS,
            messages=messages,
        ) as stream:
            # Yield tokens immediately so the UI starts rendering before the
            # full response is available — keeps latency perception low.
            async for text in stream.text_stream:
                yield {"type": "text_chunk", "content": text}

            # get_final_message() waits for the stream to complete and returns
            # the full message including any tool_use blocks appended after text.
            final = await stream.get_final_message()

        tool_use_blocks = [b for b in final.content if b.type == "tool_use"]

        if not tool_use_blocks:
            # Claude reached end_turn without calling any tools — text already streamed.
            return

        # Append Claude's response (including tool_use blocks) before sending results back.
        # The API requires the assistant turn to appear in the message history before
        # the corresponding tool_result turn.
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

        # Feed all tool results back as a single user turn so Claude can
        # interpret them and either answer or issue another query.
        messages.append({"role": "user", "content": tool_results})

    # Reached the round cap without a final answer — surface this to the user
    # rather than silently returning an empty response.
    yield {
        "type": "text_chunk",
        "content": "I reached the query limit without a complete answer. Please try rephrasing your question.",
    }