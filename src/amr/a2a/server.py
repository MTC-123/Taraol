"""FastAPI JSON-RPC 2.0 A2A server with explicit context extraction."""

import asyncio
import inspect
import os
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from amr.cost import request_cost_scope
from amr.propagation import extract_from

Handler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


class A2AServer:
    def __init__(
        self, *, tracer: trace.Tracer | None = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.tracer = tracer or trace.get_tracer("amr.a2a.server")
        self.handlers: dict[str, Handler] = {}
        self._clock = clock
        self._paused: dict[str, float] = {}
        self._pause_lock = threading.Lock()
        self.app = FastAPI()
        self.app.post("/a2a")(self._handle)
        self.app.post("/control/pause")(self._pause)
        self.app.post("/control/resume")(self._resume)

    def register(self, method: str, handler: Handler) -> None:
        self.handlers[method] = handler

    def _is_paused(self, conversation_id: str) -> bool:
        with self._pause_lock:
            expires_at = self._paused.get(conversation_id)
            if expires_at is None:
                return False
            if expires_at <= self._clock():
                del self._paused[conversation_id]
                return False
            return True

    async def _pause(self, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            body = None
        conversation_id = body.get("conversation_id") if isinstance(body, dict) else None
        if not isinstance(conversation_id, str) or not conversation_id:
            return {"status": "invalid", "detail": "conversation_id is required"}
        ttl = int(os.environ.get("AMR_PAUSE_TTL_SEC", "300"))
        if ttl <= 0:
            return {"status": "invalid", "detail": "AMR_PAUSE_TTL_SEC must be positive"}
        with self._pause_lock:
            self._paused[conversation_id] = self._clock() + ttl
        return {"status": "paused", "conversation_id": conversation_id, "ttl_sec": ttl}

    async def _resume(self, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            body = None
        conversation_id = body.get("conversation_id") if isinstance(body, dict) else None
        if not isinstance(conversation_id, str) or not conversation_id:
            return {"status": "invalid", "detail": "conversation_id is required"}
        with self._pause_lock:
            was_paused = self._paused.pop(conversation_id, None) is not None
        return {"status": "resumed", "conversation_id": conversation_id, "was_paused": was_paused}

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

        # This must run before invoking the work handler: an honest pause never
        # opens an agent/chat/tool span or delegates to another service.
        conversation_id = params.get("conversation_id")
        if (
            method == "work"
            and isinstance(conversation_id, str)
            and self._is_paused(conversation_id)
        ):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"status": "paused", "conversation_id": conversation_id},
            }

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
                with request_cost_scope() as subtree:
                    if inspect.iscoroutinefunction(handler):
                        result = await handler(params)
                    else:
                        result = await asyncio.to_thread(handler, params)
                    if inspect.isawaitable(result):
                        result = await result
                    if not isinstance(result, dict):
                        raise TypeError("A2A handlers must return an object")
                    # JSON-RPC metadata is the explicit cross-process cost handoff.
                    # Each server returns its direct chat costs plus descendants;
                    # callers put that total on exactly one CLIENT hop span.
                    meta = result.get("_meta")
                    result["_meta"] = dict(meta) if isinstance(meta, dict) else {}
                    result["_meta"]["cost_usd"] = subtree.usd
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                return _error(request_id, -32603, "Internal error")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def create_app(
    *, tracer: trace.Tracer | None = None, clock: Callable[[], float] = time.monotonic
) -> A2AServer:
    """Create a registrable A2A server instance."""

    return A2AServer(tracer=tracer, clock=clock)


def run(service_name: str, port: int, server: A2AServer) -> None:
    """Serve a configured A2A server for an already-initialized service."""

    uvicorn.run(server.app, host="0.0.0.0", port=port, log_level="info")
