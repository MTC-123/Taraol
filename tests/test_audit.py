from detection.audit import OTLPAuditEmitter


class _Logger:
    def __init__(self) -> None:
        self.records: list[object] = []

    def emit(self, record: object) -> None:
        self.records.append(record)


def test_audit_log_has_enforcement_fields_and_trace_context() -> None:
    logger = _Logger()
    audit = object.__new__(OTLPAuditEmitter)
    audit._logger = logger
    audit.emit(
        "agent_paused",
        conversation_id="c-1",
        agent="writer",
        trace_id="a" * 32,
        reason="loop-detected",
        alert_name="loop-detected",
        enforcement_mode="auto",
    )
    record = logger.records[0]
    assert record.body == "agent_paused"  # type: ignore[attr-defined]
    assert record.attributes["agent"] == "writer"  # type: ignore[attr-defined]
    assert record.attributes["enforcement_mode"] == "auto"  # type: ignore[attr-defined]
    assert record.context is not None  # type: ignore[attr-defined]
