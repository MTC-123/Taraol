from datetime import UTC, datetime

from detection.signals import OTLPSignalEmitter, Signal


class _Logger:
    def __init__(self) -> None:
        self.records: list[object] = []

    def emit(self, record: object) -> None:
        self.records.append(record)


class _Counter:
    def __init__(self) -> None:
        self.values: list[int] = []

    def add(self, value: int) -> None:
        self.values.append(value)


def test_signal_contains_queryable_fields_and_valid_trace_context() -> None:
    signal = Signal(
        "loop_detected", "c-1", "critic -> writer", 6, None, "a" * 32, datetime.now(UTC)
    )
    assert signal.attributes()["trace_id"] == "a" * 32
    assert signal.attributes()["signal"] == "loop_detected"
    context = OTLPSignalEmitter._context(signal)
    assert context is not None


def test_emitter_forwards_structured_trace_correlated_log_and_counter() -> None:
    logger = _Logger()
    loops = _Counter()
    emitter = object.__new__(OTLPSignalEmitter)
    emitter._logger = logger
    emitter._loops = loops
    emitter._budgets = _Counter()
    signal = Signal(
        "loop_detected", "c-1", "critic -> writer", 6, None, "a" * 32, datetime.now(UTC)
    )
    emitter.emit(signal)
    record = logger.records[0]
    assert record.attributes["trace_id"] == "a" * 32  # type: ignore[attr-defined]
    assert record.attributes["edge"] == "critic -> writer"  # type: ignore[attr-defined]
    assert record.context is not None  # type: ignore[attr-defined]
    assert loops.values == [1]
