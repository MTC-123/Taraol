"""Helpers for opt-in content capture (truncation + message encoding).

Content capture is gated by ``Settings.capture_content`` (default off). These helpers
keep captured text bounded so a large prompt/output never bloats a span past OTLP or
ClickHouse limits (the OTel SDK does not truncate string attributes by default).
"""

import json


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Return ``(text, truncated)``; clip to ``max_chars`` with a visible marker."""

    if text is None:
        return "", False
    if max_chars > 0 and len(text) > max_chars:
        clipped = len(text) - max_chars
        return f"{text[:max_chars]}…[truncated {clipped} chars]", True
    return text, False


def encode_messages(role: str, content: str, max_chars: int) -> tuple[str, bool]:
    """JSON-encode a single-message list (gen_ai.input/output.messages shape), truncated."""

    body, was_truncated = truncate(content, max_chars)
    return json.dumps([{"role": role, "content": body}], ensure_ascii=False), was_truncated
