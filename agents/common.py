"""Shared implementation for the five deliberately tiny demo agents."""

import logging
import os
from typing import Any
from uuid import uuid4

from fastapi import Request
from opentelemetry.trace import Tracer

from amr.a2a import A2AClient, A2AError, A2AServer
from amr.genai import agent_span, chat_span, record_chat_result, tool_span
from amr.llm import complete
from amr.mesh import max_hops, next_targets

logger = logging.getLogger(__name__)
MODEL = os.environ.get("AMR_MODEL", "gpt-4.1-mini")


def _target_url(target: str) -> str:
    return os.environ.get(f"{target.upper()}_A2A_URL", f"http://{target}:8000/a2a")


def register_agent(server: A2AServer, name: str, tracer: Tracer) -> None:
    """Register the standard ``work`` method, preserving trace context per hop."""

    def work(payload: dict[str, Any]) -> dict[str, Any]:
        conversation_id = str(payload.get("conversation_id") or uuid4())
        hops = int(payload.get("hops", 0))
        with agent_span(tracer, name, conversation_id):
            prompt = f"{name} handling conversation {conversation_id}, hop {hops}"
            with chat_span(tracer, MODEL) as span:
                result = complete(prompt, MODEL)
                record_chat_result(span, result)

            if name == "researcher":
                # This is intentionally metadata-only: no prompt/tool output is captured.
                with tool_span(tracer, "search_sources"):
                    pass

            delegated: list[str] = []
            if hops < max_hops():
                for target in next_targets(name):
                    client = A2AClient(name, target, tracer=tracer)
                    try:
                        client.call(
                            "work",
                            {"conversation_id": conversation_id, "hops": hops + 1},
                            _target_url(target),
                        )
                        delegated.append(target)
                    except A2AError:
                        logger.exception("%s could not call %s", name, target)
            return {"agent": name, "conversation_id": conversation_id, "delegated": delegated}

    server.register("work", work)


def add_start_endpoint(server: A2AServer, tracer: Tracer) -> None:
    """Expose planner's HTTP entry point while retaining an agent root span."""

    @server.app.post("/start")
    async def start(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        # Call the registered handler directly; this endpoint is only the demo trigger.
        handler = server.handlers["work"]
        return handler(payload)  # type: ignore[return-value]
