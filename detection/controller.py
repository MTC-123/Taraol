"""Webhook controller that turns SigNoz alerts into scoped pause actions."""

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request

from .audit import AuditEmitter, OTLPAuditEmitter
from .control_client import ControlClient

logger = logging.getLogger(__name__)


class _Control(Protocol):
    def pause(
        self, agent: str, conversation_id: str, *, reason: str, trace_id: str
    ) -> dict[str, Any]: ...

    def resume(
        self, agent: str, conversation_id: str, *, reason: str, trace_id: str
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class Decision:
    conversation_id: str
    agent: str
    trace_id: str
    reason: str
    alert_name: str


class Controller:
    def __init__(
        self,
        control: _Control,
        audit: AuditEmitter,
        *,
        enforce: str = "auto",
        cooldown_sec: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if enforce not in {"auto", "approve"}:
            raise ValueError("AMR_ENFORCE must be auto or approve")
        self.control, self.audit = control, audit
        self.enforce, self.cooldown_sec, self.clock = enforce, cooldown_sec, clock
        self._recent: dict[tuple[str, str], float] = {}
        self._pending: dict[str, Decision] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _value(alert: Mapping[str, Any], key: str) -> str:
        for container in (alert.get("labels"), alert.get("annotations")):
            if isinstance(container, Mapping):
                value = container.get(key)
                if isinstance(value, str) and value:
                    return value
        return ""

    def _decision(self, alert: Mapping[str, Any]) -> Decision | None:
        conversation_id = self._value(alert, "conversation_id")
        trace_id = self._value(alert, "trace_id")
        alert_name = self._value(alert, "alertname")
        if (
            not conversation_id
            or not trace_id
            or alert_name not in {"loop-detected", "budget-exceeded"}
        ):
            return None
        edge = self._value(alert, "edge")
        if alert_name == "loop-detected":
            parts = edge.split("->", maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                return None
            agent = parts[1].strip()
        else:
            agent = "writer"
        return Decision(conversation_id, agent, trace_id, alert_name, alert_name)

    def _duplicate(self, decision: Decision) -> bool:
        key = (decision.conversation_id, decision.agent)
        with self._lock:
            previous = self._recent.get(key)
            if previous is not None and self.clock() - previous < self.cooldown_sec:
                return True
            self._recent[key] = self.clock()
            return False

    def _enforce(self, decision: Decision, mode: str) -> None:
        self.control.pause(
            decision.agent,
            decision.conversation_id,
            reason=decision.reason,
            trace_id=decision.trace_id,
        )
        self.audit.emit(
            "agent_paused",
            conversation_id=decision.conversation_id,
            agent=decision.agent,
            trace_id=decision.trace_id,
            reason=decision.reason,
            alert_name=decision.alert_name,
            enforcement_mode=mode,
        )

    def receive(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, Mapping):
            alerts = payload.get("alerts")
            logger.info(
                "received alert webhook keys=%s alerts_type=%s",
                sorted(str(key) for key in payload),
                type(alerts).__name__,
            )
        if not isinstance(payload, Mapping) or not isinstance(payload.get("alerts"), list):
            return {"accepted": 0, "ignored": 1, "pending": []}
        accepted, ignored, pending = 0, 0, []
        for alert in payload["alerts"]:
            if not isinstance(alert, Mapping) or alert.get("status") != "firing":
                ignored += 1
                continue
            decision = self._decision(alert)
            if decision is None or self._duplicate(decision):
                ignored += 1
                continue
            if self.enforce == "approve":
                token = str(uuid4())
                with self._lock:
                    self._pending[token] = decision
                pending.append(token)
            else:
                self._enforce(decision, "auto")
            accepted += 1
        return {"accepted": accepted, "ignored": ignored, "pending": pending}

    def approve(self, token: str) -> bool:
        with self._lock:
            decision = self._pending.pop(token, None)
        if decision is None:
            return False
        self._enforce(decision, "approve")
        return True

    def resume(
        self, conversation_id: str, agent: str, trace_id: str, reason: str = "manual_recovery"
    ) -> None:
        self.control.resume(agent, conversation_id, reason=reason, trace_id=trace_id)
        self.audit.emit(
            "agent_resumed",
            conversation_id=conversation_id,
            agent=agent,
            trace_id=trace_id,
            reason=reason,
            alert_name="manual_resume",
            enforcement_mode=self.enforce,
        )


def create_app(controller: Controller) -> FastAPI:
    app = FastAPI()

    @app.post("/alert")
    async def alert(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        return await asyncio.to_thread(controller.receive, payload)

    @app.post("/approve")
    async def approve(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            body = None
        token = body.get("token") if isinstance(body, dict) else None
        return (
            {"approved": await asyncio.to_thread(controller.approve, token)}
            if isinstance(token, str)
            else {"approved": False}
        )

    @app.post("/resume")
    async def resume(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not all(
            isinstance(body.get(key), str) and body[key]
            for key in ("conversation_id", "agent", "trace_id")
        ):
            return {"resumed": False, "detail": "conversation_id, agent, and trace_id are required"}
        await asyncio.to_thread(
            controller.resume, body["conversation_id"], body["agent"], body["trace_id"]
        )
        return {"resumed": True}

    return app


def main() -> None:
    agent_urls = {
        agent: os.environ.get(f"{agent.upper()}_CONTROL_URL", f"http://{agent}:8000")
        for agent in ("planner", "researcher", "writer", "critic", "router")
    }
    controller = Controller(
        ControlClient(agent_urls),
        OTLPAuditEmitter(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")),
        enforce=os.environ.get("AMR_ENFORCE", "auto").lower(),
        cooldown_sec=int(os.environ.get("AMR_ALERT_COOLDOWN_SEC", "60")),
    )
    uvicorn.run(create_app(controller), host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
