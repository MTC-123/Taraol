"""Settings for the kit — all previously hard-coded values, now parameterized.

Zero-config defaults make the 3-line path work with no environment variables; every
value is overridable via ``instrument(...)`` keyword args, a :class:`Settings`
instance, or ``OAK_*`` / standard ``OTEL_*`` environment variables.
"""

import os
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    service_name: str
    service_namespace: str = "agents"
    attr_namespace: str = "agentmesh"
    provider_name: str = "unknown"
    exporter: str = "grpc"  # "grpc" | "http"
    endpoint: str | None = None  # else OTEL_EXPORTER_OTLP_ENDPOINT
    enable_logs: bool = True
    pricing_path: str | Path | None = None  # else the bundled default table

    @classmethod
    def from_env(cls, service_name: str | None = None, **overrides: object) -> "Settings":
        name = (
            service_name
            or os.environ.get("OTEL_SERVICE_NAME")
            or overrides.get("service_name")  # type: ignore[assignment]
        )
        if not name:
            raise ValueError("service_name is required (or set OTEL_SERVICE_NAME)")
        base = cls(
            service_name=str(name),
            service_namespace=os.environ.get("OAK_SERVICE_NAMESPACE", "agents"),
            attr_namespace=os.environ.get("OAK_ATTR_NAMESPACE", "agentmesh"),
            provider_name=os.environ.get("OAK_PROVIDER_NAME", "unknown"),
            exporter=os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").split("/")[0].lower()
            if os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL")
            else "grpc",
            endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
            pricing_path=os.environ.get("OAK_PRICING_FILE"),
        )
        # Keyword overrides win over environment.
        clean = {k: v for k, v in overrides.items() if k != "service_name" and v is not None}
        return replace(base, **clean) if clean else base
