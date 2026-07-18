from fastapi.testclient import TestClient

from detection.audit import RecordingAuditEmitter
from detection.controller import Controller, create_app

TRACE_ID = "a" * 32


class _Control:
    def __init__(self) -> None:
        self.pauses: list[tuple[str, str, str, str]] = []
        self.resumes: list[tuple[str, str, str, str]] = []

    def pause(
        self, agent: str, conversation_id: str, *, reason: str, trace_id: str
    ) -> dict[str, str]:
        self.pauses.append((agent, conversation_id, reason, trace_id))
        return {"status": "paused"}

    def resume(
        self, agent: str, conversation_id: str, *, reason: str, trace_id: str
    ) -> dict[str, str]:
        self.resumes.append((agent, conversation_id, reason, trace_id))
        return {"status": "resumed"}


def _alert(name: str, **labels: str) -> dict[str, object]:
    return {"status": "firing", "labels": {"alertname": name, "trace_id": TRACE_ID} | labels}


def test_loop_alert_pauses_callee_once_and_emits_audit() -> None:
    control, audit = _Control(), RecordingAuditEmitter()
    controller = Controller(control, audit)
    payload = {"alerts": [_alert("loop-detected", conversation_id="c-1", edge="critic -> writer")]}
    assert controller.receive(payload) == {"accepted": 1, "ignored": 0, "pending": []}
    assert controller.receive(payload) == {"accepted": 0, "ignored": 1, "pending": []}
    assert control.pauses == [("writer", "c-1", "loop-detected", TRACE_ID)]
    assert audit.events == [
        {
            "event": "agent_paused",
            "conversation_id": "c-1",
            "agent": "writer",
            "trace_id": TRACE_ID,
            "reason": "loop-detected",
            "alert_name": "loop-detected",
            "enforcement_mode": "auto",
        }
    ]


def test_budget_multi_alert_malformed_and_resume_are_safe() -> None:
    control, audit = _Control(), RecordingAuditEmitter()
    controller = Controller(control, audit)
    response = controller.receive(
        {
            "alerts": [
                _alert("budget-exceeded", conversation_id="c-2"),
                {"status": "resolved"},
                "bad",
            ]
        }
    )
    assert response == {"accepted": 1, "ignored": 2, "pending": []}
    assert control.pauses == [("writer", "c-2", "budget-exceeded", TRACE_ID)]
    assert controller.receive({"no_alerts": True}) == {"accepted": 0, "ignored": 1, "pending": []}
    controller.resume("c-2", "writer", TRACE_ID)
    assert control.resumes == [("writer", "c-2", "manual_recovery", TRACE_ID)]
    assert audit.events[-1]["event"] == "agent_resumed"


def test_approve_mode_waits_for_token_then_pauses() -> None:
    control, audit = _Control(), RecordingAuditEmitter()
    controller = Controller(control, audit, enforce="approve")
    pending = controller.receive({"alerts": [_alert("budget-exceeded", conversation_id="c-3")]})[
        "pending"
    ]
    assert len(pending) == 1 and control.pauses == []
    with TestClient(create_app(controller)) as http:
        assert http.post("/approve", json={"token": pending[0]}).json() == {"approved": True}
        assert http.post("/approve", json={"token": pending[0]}).json() == {"approved": False}
    assert control.pauses == [("writer", "c-3", "budget-exceeded", TRACE_ID)]
    assert audit.events[0]["enforcement_mode"] == "approve"
