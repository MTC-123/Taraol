from fastapi.testclient import TestClient
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from amr.a2a import create_app


def _server() -> tuple[object, InMemorySpanExporter, list[dict[str, object]]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "writer"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    calls: list[dict[str, object]] = []
    server = create_app(tracer=provider.get_tracer("writer"))
    server.register("work", lambda payload: calls.append(payload) or {"worked": True})
    return server, exporter, calls


def _work(http: TestClient, conversation_id: str) -> dict[str, object]:
    return http.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "request-1",
            "method": "work",
            "params": {"conversation_id": conversation_id},
        },
    ).json()


def test_pause_short_circuits_work_and_resume_restores_it(monkeypatch) -> None:
    monkeypatch.setenv("AMR_PAUSE_TTL_SEC", "300")
    server, exporter, calls = _server()
    with TestClient(server.app) as http:
        assert (
            http.post("/control/pause", json={"conversation_id": "c-1"}).json()["status"]
            == "paused"
        )
        assert _work(http, "c-1")["result"] == {"status": "paused", "conversation_id": "c-1"}
        assert calls == []
        assert list(exporter.get_finished_spans()) == []
        assert (
            http.post("/control/resume", json={"conversation_id": "c-1"}).json()["status"]
            == "resumed"
        )
        assert _work(http, "c-1")["result"]["worked"] is True
    assert len(calls) == 1


def test_pause_ttl_expires_lazily(monkeypatch) -> None:
    now = [0.0]
    monkeypatch.setenv("AMR_PAUSE_TTL_SEC", "10")
    server = create_app(clock=lambda: now[0])
    server.register("work", lambda _: {"worked": True})
    with TestClient(server.app) as http:
        http.post("/control/pause", json={"conversation_id": "c-1"})
        now[0] = 11.0
        assert _work(http, "c-1")["result"]["worked"] is True
