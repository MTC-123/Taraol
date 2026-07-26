"""Loop / budget / injection / edge-breaker detection over SigNoz telemetry.

Reads a SigNoz deployment (Query API primary, ClickHouse fallback), emits signals,
and — via the controller webhook — trips per-edge breakers or pauses agents. Needs the
``[detection]`` extra (httpx + fastapi/uvicorn).
"""

from .config import WatcherConfig
from .control_client import ControlClient
from .controller import Controller, Decision, create_app
from .loop_watcher import LoopWatcher
from .signals import OTLPSignalEmitter, RecordingEmitter, Signal
from .signoz_client import ClickHouseClient, SigNozClient, TimeRange

__all__ = [
    "WatcherConfig",
    "LoopWatcher",
    "Controller",
    "Decision",
    "create_app",
    "ControlClient",
    "Signal",
    "RecordingEmitter",
    "OTLPSignalEmitter",
    "SigNozClient",
    "ClickHouseClient",
    "TimeRange",
]
