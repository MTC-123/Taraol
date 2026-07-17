# Architecture

The system architecture diagram and component flow land in PLAN 07.

Until then, the repository preserves three independent layers: `agents/`, `detection/`,
and `mcp_tool/`. They communicate through OTLP, HTTP, and SigNoz only.


