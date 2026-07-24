"""JSON-RPC 2.0 A2A client with explicit trace-context propagation."""

from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from amr import semconv
from amr.breaker import edge_key, get_registry
from amr.cost import add_to_request_cost
from amr.genai import current_conversation_id
from amr.propagation import inject_into
from amr.taint import mark_taint, taint_from_baggage


class _HttpClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class A2AError(RuntimeError):
    """An invalid or error JSON-RPC response from an A2A peer."""


class EdgeBrokenError(A2AError):
    """The edge circuit breaker is open; the hop was not dispatched."""


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
        # Stamp the conversation on the edge so cross-conversation loop detection can
        # group hops by (conversation, src, peer) instead of by a single trace.
        conversation_id = current_conversation_id()
        if conversation_id:
            attributes[semconv.GEN_AI_CONVERSATION_ID] = conversation_id
        edge = edge_key(self.local_service_name, self.target_service_name)
        registry = get_registry()
        with self.tracer.start_as_current_span(
            "a2a.call", kind=SpanKind.CLIENT, attributes=attributes
        ) as span:
            # If the caller is inside a taint scope, mark the edge itself so the
            # poisoned hop is visible on the Service Map.  Baggage is injected below,
            # so the callee inherits the taint regardless of this stamp.
            carried = taint_from_baggage()
            if carried is not None:
                mark_taint(span, carried)
            # Circuit breaker: an open edge short-circuits before any dispatch, so a
            # runaway or poisoned hop stops flowing until it recovers.
            if not registry.allow(edge):
                span.set_attribute(semconv.AGENTMESH_BREAKER_STATE, registry.state_of(edge))
                span.set_attribute(semconv.AGENTMESH_BREAKER_EDGE, edge)
                raise EdgeBrokenError(f"edge breaker open: {edge}")
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
                registry.record_failure(edge)
                raise A2AError(f"A2A HTTP request failed: {exc}") from exc
            registry.record_success(edge)
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
                    # Callee subtree cost attributed to this delegation edge. NOT additive
                    # across edges — use it to see which path drives downstream cost.
                    span.set_attribute(semconv.AGENTMESH_COST_DOWNSTREAM_USD, normalized_cost)
                    add_to_request_cost(normalized_cost)
            return result
