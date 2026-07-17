"""FastAPI JSON-RPC 2.0 A2A server with explicit context extraction."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from amr.propagation import extract_from

Handler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


class A2AServer:
    def __init__(self, *, tracer: trace.Tracer | None = None) -> None:
        self.tracer = tracer or trace.get_tracer("amr.a2a.server")
        self.handlers: dict[str, Handler] = {}
        self.app = FastAPI()
        self.app.post("/a2a")(self._handle)

    def register(self, method: str, handler: Handler) -> None:
        self.handlers[method] = handler

    async def _handle(self, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            return _error(None, -32700, "Parse error")
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            request_id = body.get("id") if isinstance(body, dict) else None
            return _error(request_id, -32600, "Invalid Request")

        request_id = body.get("id")
        method = body.get("method")
        params = body.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            return _error(request_id, -32600, "Invalid Request")

        context = extract_from(request.headers)
        with self.tracer.start_as_current_span(
            "a2a.handle",
            context=context,
            kind=SpanKind.SERVER,
            attributes={"rpc.system": "jsonrpc", "rpc.method": method},
        ) as span:
            handler = self.handlers.get(method)
            if handler is None:
                span.set_status(Status(StatusCode.ERROR, "Method not found"))
                return _error(request_id, -32601, "Method not found")
            try:
                # Agent handlers make blocking HTTP calls to their peers.  Run
                # synchronous handlers off the ASGI loop so a bounded cycle can
                # re-enter this service (writer -> critic -> writer) safely.
                if inspect.iscoroutinefunction(handler):
                    result = await handler(params)
                else:
                    result = await asyncio.to_thread(handler, params)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, dict):
                    raise TypeError("A2A handlers must return an object")
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                return _error(request_id, -32603, "Internal error")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def create_app(*, tracer: trace.Tracer | None = None) -> A2AServer:
    """Create a registrable A2A server instance."""

    return A2AServer(tracer=tracer)


def run(service_name: str, port: int, server: A2AServer) -> None:
    """Serve a configured A2A server for an already-initialized service."""

    uvicorn.run(server.app, host="0.0.0.0", port=port, log_level="info")
