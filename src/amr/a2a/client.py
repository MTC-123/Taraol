"""JSON-RPC 2.0 A2A client with explicit trace-context propagation."""

from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from amr.cost import add_to_request_cost
from amr.propagation import inject_into


class _HttpClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class A2AError(RuntimeError):
    """An invalid or error JSON-RPC response from an A2A peer."""


class A2AClient:
    def __init__(
        self,
        local_service_name: str,
        target_service_name: str,
        *,
        tracer: trace.Tracer | None = None,
        http_client: _HttpClient | None = None,
    ) -> None:
        self.local_service_name = local_service_name
        self.target_service_name = target_service_name
        self.tracer = tracer or trace.get_tracer(local_service_name)
        self.http_client = http_client or httpx

    def call(self, method: str, params: Mapping[str, Any], target_url: str) -> dict[str, Any]:
        """Call one JSON-RPC method and return its object result."""

        peer_name = urlparse(target_url).hostname or "unknown"
        attributes = {
            "rpc.system": "jsonrpc",
            "rpc.method": method,
            "peer.service": self.target_service_name,
            "agentmesh.src": self.local_service_name,
            "net.peer.name": peer_name,
        }
        with self.tracer.start_as_current_span(
            "a2a.call", kind=SpanKind.CLIENT, attributes=attributes
        ) as span:
            headers: dict[str, str] = {"content-type": "application/json"}
            inject_into(headers)
            try:
                response = self.http_client.post(
                    target_url,
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": str(uuid4()),
                        "method": method,
                        "params": dict(params),
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise A2AError(f"A2A HTTP request failed: {exc}") from exc
            try:
                payload = response.json()
            except ValueError as exc:
                raise A2AError("A2A peer returned non-JSON content") from exc

            if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
                raise A2AError("A2A peer returned an invalid JSON-RPC response")
            if "error" in payload:
                raise A2AError(f"A2A peer returned an error: {payload['error']}")
            result = payload.get("result")
            if not isinstance(result, dict):
                raise A2AError("A2A peer returned a non-object result")
            meta = result.get("_meta")
            if isinstance(meta, dict):
                cost_usd = meta.get("cost_usd")
                if isinstance(cost_usd, (int, float)) and not isinstance(cost_usd, bool):
                    # A hop owns the callee subtree once.  The same value is also
                    # added to the enclosing server request so its parent can return
                    # the complete subtree to its caller.
                    normalized_cost = round(float(cost_usd), 4)
                    span.set_attribute("agentmesh.cost.usd", normalized_cost)
                    add_to_request_cost(normalized_cost)
            return result
