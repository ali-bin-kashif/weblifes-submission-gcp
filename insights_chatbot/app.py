"""
Insights Chatbot — Chainlit app entry point.

Run locally:
    cd insights_chatbot
    chainlit run app.py
"""

import re

import chainlit as cl

from utils.bq_client import BigQueryClient
from utils.config import Config
from utils.llm import run_agent

config = Config.from_env()

_mask = lambda v: (v[:6] + "****") if len(v) > 6 else ("****" if v else "NOT SET")
print("--- Chatbot Config ---")
print(f"  ANTHROPIC_API_KEY              : {_mask(config.ANTHROPIC_API_KEY)}")
print(f"  CLAUDE_MODEL                   : {config.CLAUDE_MODEL or 'NOT SET'}")
print(f"  GOOGLE_CREDENTIALS_JSON        : {'SET' if config.GOOGLE_CREDENTIALS_JSON else 'NOT SET'}")
print(f"  GOOGLE_APPLICATION_CREDENTIALS : {config.GOOGLE_APPLICATION_CREDENTIALS or 'NOT SET'}")
print(f"  BQ_PROJECT_ID                  : {config.BQ_PROJECT_ID or 'NOT SET'}")
print("  Credentials mode               :", "JSON env var" if config.GOOGLE_CREDENTIALS_JSON else ("key file" if config.GOOGLE_APPLICATION_CREDENTIALS else "ADC"))
print("----------------------")


@cl.set_starters
async def set_starters() -> list[cl.Starter]:
    return [
        
        cl.Starter(
            label="How did we do last month?",
            message="How did we do last month?",
        ),
        cl.Starter(
            label="Which product is selling the most?",
            message="Which product is selling the most?",
        ),
        cl.Starter(
            label="Which store is performing best?",
            message="Which store is performing best?",
        ),
        cl.Starter(
            label="Compare revenue across stores this year",
            message="Compare revenue across stores this year.",
        ),
    ]


@cl.on_chat_start
async def on_start() -> None:
    cl.user_session.set("history", [])


@cl.on_message
async def on_message(message: cl.Message) -> None:
    history: list[dict] = cl.user_session.get("history", [])
    bq = BigQueryClient(config)

    answer = ""
    query_count = 0
    current_step: cl.Step | None = None

    msg = cl.Message(content="")
    await msg.send()

    async for event in run_agent(message.content, history, config, bq):

        if event["type"] == "sql":
            query_count += 1
            current_step = cl.Step(name=f"BigQuery · Query {query_count}", language="sql")
            current_step.input = event["content"]
            await current_step.send()

        elif event["type"] in ("result", "error"):
            if current_step is not None:
                current_step.output = _result_summary(event["content"], event["type"])
                await current_step.update()
                current_step = None

        elif event["type"] == "text_chunk":
            await msg.stream_token(event["content"])
            answer += event["content"]

    await msg.update()

    history.append({"role": "user",      "content": message.content})
    history.append({"role": "assistant", "content": answer})
    cl.user_session.set("history", history)


def _result_summary(result: str, event_type: str) -> str:
    """Extracts a one-line summary from the BQ result string for the Step output."""
    if event_type == "error":
        return f"Error: {result}"
    match = re.search(r"(\d+) row\(s\) returned", result)
    if match:
        return f"{match.group(1)} row(s) returned"
    return "Query completed"