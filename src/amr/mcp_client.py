"""Read-only adapter for the official SigNoz MCP server.

The demo's explain surfaces deliberately go through MCP rather than querying
ClickHouse or SigNoz HTTP directly. Detection remains independently read-only.
"""

import asyncio
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


@dataclass(frozen=True, slots=True)
class TimeRange:
    start_ms: int
    end_ms: int


def _trace_query(trace_id: str) -> dict[str, Any]:
    escaped = trace_id.replace("'", "\\'")
    return {
        "type": "builder_query",
        "spec": {
            "name": "trace_spans",
            "signal": "traces",
            "filter": {"expression": f"trace_id = '{escaped}'"},
            "selectFields": [
                {"name": "trace_id", "fieldContext": "span"},
                {"name": "span_id", "fieldContext": "span"},
                {"name": "parent_span_id", "fieldContext": "span"},
                {"name": "timestamp", "fieldContext": "span"},
                {"name": "name", "fieldContext": "span"},
                {"name": "service.name", "fieldContext": "resource"},
                {"name": "gen_ai.operation.name", "fieldContext": "span"},
                {"name": "agentmesh.cost.usd", "fieldContext": "span"},
            ],
            "disabled": False,
            "limit": 1000,
        },
    }


def _audit_query(trace_id: str) -> dict[str, Any]:
    escaped = trace_id.replace("'", "\\'")
    return {
        "type": "builder_query",
        "spec": {
            "name": "audit_events",
            "signal": "logs",
            "filter": {"expression": f"trace_id = '{escaped}' AND body = 'agent_paused'"},
            "selectFields": [
                {"name": "trace_id", "fieldContext": "log"},
                {"name": "body", "fieldContext": "log"},
                {"name": "event", "fieldContext": "log"},
                {"name": "conversation_id", "fieldContext": "log"},
                {"name": "agent", "fieldContext": "log"},
                {"name": "reason", "fieldContext": "log"},
            ],
            "disabled": False,
            "limit": 100,
        },
    }


class SigNozMCPError(RuntimeError):
    """The official MCP server was unreachable or returned unusable data."""


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        for key in ("data", "result", "rows"):
            if key in value:
                try:
                    return _rows(value[key])
                except SigNozMCPError:
                    pass
    if isinstance(value, list) and all(isinstance(row, Mapping) for row in value):
        return [dict(row) for row in value]
    raise SigNozMCPError("SigNoz MCP result did not contain object rows")


class SigNozMCPClient:
    """Tiny synchronous facade over the official streamable-HTTP MCP transport."""

    def __init__(self, url: str | None = None, api_key: str | None = None) -> None:
        self.url = (url or os.environ.get("SIGNOZ_MCP_URL", "http://localhost:8003/mcp")).rstrip(
            "/"
        )
        self.api_key = api_key if api_key is not None else os.environ.get("SIGNOZ_API_KEY", "")

    async def _call_async(self, tool: str, arguments: dict[str, Any]) -> Any:
        headers = {"SIGNOZ-API-KEY": self.api_key} if self.api_key else None
        try:
            async with streamablehttp_client(self.url, headers=headers) as streams:
                read, write, _ = streams
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments)
        except Exception as exc:  # transport errors need actionable CLI feedback
            raise SigNozMCPError(f"SigNoz MCP call {tool!r} failed: {exc}") from exc
        if result.isError:
            raise SigNozMCPError(f"SigNoz MCP tool {tool!r} returned an error")
        if result.structuredContent is not None:
            return result.structuredContent
        for content in result.content:
            text = getattr(content, "text", None)
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    continue
        raise SigNozMCPError(f"SigNoz MCP tool {tool!r} returned no JSON content")

    def execute_builder_query(
        self, query: Mapping[str, Any], time_range: TimeRange
    ) -> list[dict[str, Any]]:
        spec = query.get("spec", {})
        request_type = "raw" if isinstance(spec, Mapping) and "selectFields" in spec else "table"
        payload = {
            "start": time_range.start_ms,
            "end": time_range.end_ms,
            "requestType": request_type,
            "variables": {},
            "compositeQuery": {"queries": [dict(query)]},
        }
        result = asyncio.run(self._call_async("signoz_execute_builder_query", {"query": payload}))
        return _rows(result)

    def list_firing_alerts(self) -> Any:
        """Return the real Alertmanager instances via the official MCP tool."""

        return asyncio.run(self._call_async("signoz_list_alerts", {"state": "firing"}))

    def get_trace(self, trace_id: str, time_range: TimeRange | None = None) -> list[dict[str, Any]]:
        if time_range is None:
            end = int(time.time() * 1000)
            time_range = TimeRange(end - 86_400_000, end)
        return self.execute_builder_query(_trace_query(trace_id), time_range)

    def get_audit_events(
        self, trace_id: str, time_range: TimeRange | None = None
    ) -> list[dict[str, Any]]:
        if time_range is None:
            end = int(time.time() * 1000)
            time_range = TimeRange(end - 86_400_000, end)
        return self.execute_builder_query(_audit_query(trace_id), time_range)

    def close(self) -> None:
        """Match the detector client protocol; HTTP sessions are per call."""


def _cycle_only(agents: list[str]) -> str:
    """Reduce a detector path to its repeating cycle for display."""

    first_seen: dict[str, int] = {}
    for index, agent in enumerate(agents):
        previous = first_seen.get(agent)
        if previous is not None:
            return " → ".join(agents[previous : index + 1])
        first_seen[agent] = index
    return " → ".join(agents)


def format_explanation(facts: Mapping[str, Any]) -> str:
    """Human-readable terminal output for the post-incident beat."""

    cycles = facts.get("cycles", [])
    # Detector paths share long acyclic prefixes; show each distinct cycle once.
    paths = list(
        dict.fromkeys(
            _cycle_only(item.get("agents", [])) for item in cycles if isinstance(item, Mapping)
        )
    )
    pause = facts.get("pause_action")
    pause_text = "observed" if pause else "not observed"
    return "\n".join(
        [
            "Agent Mesh Radar — Loop Post-mortem",
            "=" * 38,
            f"Trace:        {facts.get('trace_id', 'unknown')}",
            f"Services:     {', '.join(facts.get('services', []))}",
            f"Cycle:        {'; '.join(paths) or 'none observed'}",
            f"A2A hops:     {facts.get('hop_count', 0)}",
            f"Direct cost:  USD {float(facts.get('direct_chat_cost_usd', 0.0)):.4f}",
            f"Pause action: {pause_text}",
            "Next action:  inspect the trace-correlated pause audit event.",
        ]
    )
