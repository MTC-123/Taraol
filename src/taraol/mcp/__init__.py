"""MCP explain surface over the official SigNoz MCP server.

Exposes a read-only ``SigNozMCPClient`` and a terminal ``explain <trace_id>`` CLI
that render the grounded facts from :func:`taraol.explain.explain_trace`.
"""

from .cli import main
from .client import SigNozMCPClient, TimeRange, format_explanation

__all__ = [
    "SigNozMCPClient",
    "format_explanation",
    "TimeRange",
    "main",
]
