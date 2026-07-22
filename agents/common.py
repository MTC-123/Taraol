"""Shared implementation for the five deliberately tiny demo agents."""

import logging
import os
from typing import Any
from uuid import uuid4

from fastapi import Request
from opentelemetry import trace
from opentelemetry.trace import Tracer

from amr.a2a import A2AClient, A2AError, A2AServer
from amr.events import reasoning_event
from amr.genai import agent_span, chat_span, record_chat_result, tool_span
from amr.guardrail import INPUT, OUTPUT, scan
from amr.llm import complete
from amr.mesh import max_hops, next_targets
from amr.taint import Taint, mark_taint, taint_from_baggage, taint_scope

logger = logging.getLogger(__name__)
MODEL = os.environ.get("AMR_MODEL", "gpt-4.1-mini")


def _target_url(target: str) -> str:
    return os.environ.get(f"{target.upper()}_A2A_URL", f"http://{target}:8000/a2a")


def _scan_boundary(prompt: str, output: str) -> "object":
    """Scan model input then output; return the first flagged verdict (or a clean one)."""

    verdict = scan(prompt, INPUT)
    if verdict.flagged:
        return verdict
    return scan(output, OUTPUT)


def register_agent(server: A2AServer, name: str, tracer: Tracer) -> None:
    """Register the standard ``work`` method, preserving trace context per hop."""

    def work(payload: dict[str, Any]) -> dict[str, Any]:
        conversation_id = str(payload.get("conversation_id") or uuid4())
        hops = int(payload.get("hops", 0))
        # Untrusted text enters only through ``user_input`` (defaults to empty).  It is
        # scanned, never logged; the prompt below is the only place it is materialised.
        user_input = str(payload.get("user_input") or "")
        with agent_span(tracer, name, conversation_id) as a_span:
            # Taint inherited from an upstream hop marks this agent as part of the
            # injection blast radius even if its own content scans clean.
            inherited = taint_from_baggage()
            if inherited is not None:
                mark_taint(a_span, Taint(inherited.category, inherited.origin, inherited.hops + 1))
            reasoning_event(name, conversation_id, "received", hop=hops)
            prompt = f"{name} handling conversation {conversation_id}, hop {hops}. {user_input}"
            with chat_span(tracer, MODEL) as span:
                result = complete(prompt, MODEL)
                record_chat_result(span, result)
                verdict = _scan_boundary(prompt, result.text)
            local_taint = Taint(verdict.category, name, 0) if verdict.flagged else None
            if local_taint is not None:
                mark_taint(span, local_taint)
                # Content-free: only the category and this service name are recorded.
                reasoning_event(
                    name, conversation_id, "taint_flagged", hop=hops, category=verdict.category
                )
            reasoning_event(
                name,
                conversation_id,
                "completed",
                hop=hops,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )

            if name == "researcher":
                # This is intentionally metadata-only: no prompt/tool output is captured.
                with tool_span(tracer, "search_sources"):
                    pass

            # A local flag becomes the new taint origin; otherwise carry the inherited
            # marker forward with an incremented hop distance.
            active = local_taint
            if active is None and inherited is not None:
                active = Taint(inherited.category, inherited.origin, inherited.hops + 1)

            def _delegate() -> list[str]:
                targets: list[str] = []
                if hops < max_hops():
                    for target in next_targets(name):
                        client = A2AClient(name, target, tracer=tracer)
                        try:
                            client.call(
                                "work",
                                {
                                    "conversation_id": conversation_id,
                                    "hops": hops + 1,
                                    "user_input": user_input,
                                },
                                _target_url(target),
                            )
                            targets.append(target)
                        except A2AError:
                            logger.exception("%s could not call %s", name, target)
                return targets

            if active is not None:
                with taint_scope(active):
                    delegated = _delegate()
            else:
                delegated = _delegate()
            reasoning_event(
                name, conversation_id, "delegated", hop=hops, targets=",".join(delegated)
            )
            trace_id = f"{trace.get_current_span().get_span_context().trace_id:032x}"
            return {
                "agent": name,
                "conversation_id": conversation_id,
                "delegated": delegated,
                "_meta": {"trace_id": trace_id},
            }

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
