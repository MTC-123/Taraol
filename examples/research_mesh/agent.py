"""One research-mesh agent, built entirely on otel-agent-kit.

Shows the adopter pattern: instrument() once, then wrap each step with the kit's
context managers. The researcher does a real web search (Tavily/fake). Agent output is
threaded to the next agent (a genuine A→B→C pipeline); prompts/outputs/tool-I/O are
captured on spans only when OAK_CAPTURE_CONTENT=on. Loops trip the kit's detection
watcher + per-edge breaker exactly as the library intends.
"""

import hashlib
import logging
import os
import re
from typing import Any
from uuid import uuid4

from opentelemetry import trace

from otel_agent_kit import instrument, llm
from otel_agent_kit.attributes import attrs
from otel_agent_kit.guardrail import INPUT, OUTPUT, scan
from otel_agent_kit.integrations.a2a import A2AClient, A2AError, EdgeBrokenError, create_app, run
from otel_agent_kit.quality import scan_output
from otel_agent_kit.taint import Taint, mark_taint, taint_from_baggage, taint_scope
from otel_agent_kit.tools import search

from . import mesh

logger = logging.getLogger(__name__)
MODEL = os.environ.get("MESH_MODEL", "gemini-2.5-flash")
NAMES = attrs("agentmesh")


def _state_hash(text: str) -> str:
    normalized = re.sub(r"\d+", "", re.sub(r"\s+", " ", text.strip().lower()))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _scan_boundary(prompt: str, output: str):
    verdict = scan(prompt, INPUT)
    return verdict if verdict.flagged else scan(output, OUTPUT)


def _prompt(name: str, hops: int, user_input: str, upstream: str, context: str) -> str:
    parts = [f"You are the {name} agent (step {hops})."]
    if user_input:
        parts.append(f"Task: {user_input}")
    if upstream:
        parts.append(f"Previous agent produced:\n{upstream}")
    if context:
        parts.append(f"Retrieved context:\n{context}")
    parts.append("Produce your contribution.")
    return "\n\n".join(parts)


def register_agent(kit, server, name: str) -> None:
    def work(payload: dict[str, Any]) -> dict[str, Any]:
        conversation_id = str(payload.get("conversation_id") or uuid4())
        hops = int(payload.get("hops", 0))
        user_input = str(payload.get("user_input") or "")
        upstream = str(payload.get("upstream_output") or "")  # A's output → B's input

        with kit.agent(name, conversation_id) as a_span:
            inherited = taint_from_baggage(NAMES)
            if inherited is not None:
                mark_taint(a_span, Taint(inherited.category, inherited.origin, inherited.hops + 1), NAMES)
            kit.reasoning("received", hop=hops)

            context = ""
            if name == "researcher":
                query = user_input or "recent developments"
                with kit.tool("search_sources", arguments=query) as tool:
                    hits = search.web_search(query, max_results=3)
                    tool.set_result(search.hits_to_json(hits))
                context = " ".join(h.snippet for h in hits)

            prompt = _prompt(name, hops, user_input, upstream, context)
            with kit.chat(MODEL) as chat:
                result = llm.complete(prompt, MODEL)
                chat.record(
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    finish_reason=result.finish_reason,
                )
                chat.record_content(prompt=prompt, completion=result.text)  # opt-in
                verdict = _scan_boundary(prompt, result.text)
                local_taint = Taint(verdict.category, name, 0) if verdict.flagged else None
                if local_taint is not None:
                    mark_taint(chat.span, local_taint, NAMES)

            a_span.set_attribute(NAMES.state_hash, _state_hash(result.text))
            quality = scan_output(result.text)
            if quality.flagged:
                a_span.set_attribute(NAMES.output_flagged, True)
                a_span.set_attribute(NAMES.output_category, quality.category)
            kit.reasoning(
                "completed",
                hop=hops,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )

            active = local_taint
            if active is None and inherited is not None:
                active = Taint(inherited.category, inherited.origin, inherited.hops + 1)

            def _delegate() -> list[str]:
                targets: list[str] = []
                if hops < mesh.max_hops():
                    for target in mesh.next_targets(name):
                        client = A2AClient(name, target)
                        try:
                            client.call(
                                "work",
                                {
                                    "conversation_id": conversation_id,
                                    "hops": hops + 1,
                                    "user_input": user_input,
                                    "upstream_output": result.text,
                                },
                                mesh.target_url(target),
                            )
                            targets.append(target)
                        except EdgeBrokenError:
                            kit.reasoning("edge_broken", hop=hops, target=target)
                        except A2AError:
                            logger.exception("%s could not call %s", name, target)
                return targets

            if active is not None:
                with taint_scope(active, NAMES):
                    delegated = _delegate()
            else:
                delegated = _delegate()

            kit.reasoning("delegated", hop=hops, targets=",".join(delegated))
            trace_id = f"{trace.get_current_span().get_span_context().trace_id:032x}"
            return {
                "agent": name,
                "conversation_id": conversation_id,
                "delegated": delegated,
                "_meta": {"trace_id": trace_id},
            }

    server.register("work", work)


def add_start_endpoint(server) -> None:
    from fastapi import Request

    @server.app.post("/start")
    async def start(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        return server.handlers["work"](payload if isinstance(payload, dict) else {})


def main() -> None:
    name = os.environ["OTEL_SERVICE_NAME"]
    kit = instrument(name)
    server = create_app()
    register_agent(kit, server, name)
    if name == "planner":
        add_start_endpoint(server)
    run(name, 8000, server)


if __name__ == "__main__":
    main()
