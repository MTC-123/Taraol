"""Small HTTP client for the agents' conversation control endpoints."""

from collections.abc import Mapping
from typing import Any, Protocol

import httpx


class _HttpClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class ControlClient:
    def __init__(
        self, agent_urls: Mapping[str, str], *, http_client: _HttpClient | None = None
    ) -> None:
        self.agent_urls = dict(agent_urls)
        self.http_client = http_client or httpx

    def _post(self, action: str, agent: str, payload: dict[str, str]) -> dict[str, Any]:
        base_url = self.agent_urls.get(agent)
        if not base_url:
            raise ValueError(f"no control URL configured for agent {agent!r}")
        body_out = {key: value for key, value in payload.items() if value}
        try:
            response = self.http_client.post(
                f"{base_url.rstrip('/')}/control/{action}", json=body_out, timeout=5.0
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"agent {agent} {action} failed: {exc}") from exc
        if not isinstance(body, dict):
            raise RuntimeError(f"agent {agent} {action} returned a non-object response")
        return body

    def _call(
        self, action: str, agent: str, conversation_id: str, **context: str
    ) -> dict[str, Any]:
        return self._post(action, agent, {"conversation_id": conversation_id, **context})

    def pause(
        self, agent: str, conversation_id: str, *, reason: str, trace_id: str
    ) -> dict[str, Any]:
        return self._call("pause", agent, conversation_id, reason=reason, trace_id=trace_id)

    def resume(
        self, agent: str, conversation_id: str, *, reason: str, trace_id: str
    ) -> dict[str, Any]:
        return self._call("resume", agent, conversation_id, reason=reason, trace_id=trace_id)

    def break_edge(self, agent: str, edge: str, *, reason: str, trace_id: str) -> dict[str, Any]:
        payload = {"edge": edge, "reason": reason, "trace_id": trace_id}
        return self._post("break_edge", agent, payload)

    def reset_edge(self, agent: str, edge: str, *, reason: str, trace_id: str) -> dict[str, Any]:
        payload = {"edge": edge, "reason": reason, "trace_id": trace_id}
        return self._post("reset_edge", agent, payload)
