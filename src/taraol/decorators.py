"""Decorator sugar over the context-manager API — a slicker way to say the same thing.

``@agent`` / ``@chat`` / ``@tool`` wrap a function in the matching span using the process
default handle from ``instrument()``. They are thin: each just opens the same context
manager you'd write by hand, so anything the CMs do (cost rollup, capture, propagation)
still applies. The CM API stays the public API for streaming / async / fine control.

    from taraol import instrument, agent, chat, tool, record_chat, record_chat_content

    instrument("planner")

    @tool                                   # execute_tool span; str return captured as result
    def search(query): ...

    @chat("gpt-4o")                         # chat span; record usage/content from inside
    def think(prompt):
        r = client.chat.completions.create(...)
        record_chat(input_tokens=r.usage.prompt_tokens, output_tokens=r.usage.completion_tokens)
        record_chat_content(prompt=prompt, completion=r.choices[0].message.content)
        return r.choices[0].message.content

    @agent(name="planner")                  # invoke_agent span around the whole step
    def plan(task): ...
"""

import functools
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from .facade import ChatSpan, get_default_instrument

_current_chat: ContextVar[ChatSpan | None] = ContextVar("oak_current_chat", default=None)

# (usage attr on the response, prompt-tokens attr, completion-tokens attr) per SDK shape.
_USAGE_SHAPES = (
    ("usage_metadata", "prompt_token_count", "candidates_token_count"),  # google-genai
    ("usage", "prompt_tokens", "completion_tokens"),  # OpenAI-compatible
    ("usage", "input_tokens", "output_tokens"),  # Anthropic
)


def _extract_usage(result: Any) -> tuple[int, int] | None:
    """Duck-type token usage out of a raw SDK response (genai/OpenAI/Anthropic shapes)."""

    for usage_attr, in_attr, out_attr in _USAGE_SHAPES:
        usage = getattr(result, usage_attr, None)
        if usage is None:
            continue
        input_tokens = getattr(usage, in_attr, None)
        output_tokens = getattr(usage, out_attr, None)
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            return input_tokens, output_tokens
    return None


def agent(
    func: Callable | None = None,
    *,
    name: str | None = None,
    conversation_id: str | None = None,
) -> Callable:
    """Wrap a function as an ``invoke_agent`` span. Usable as ``@agent`` or ``@agent(name=...)``."""

    def deco(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with get_default_instrument().agent(name or f.__name__, conversation_id):
                return f(*args, **kwargs)

        return wrapper

    return deco(func) if callable(func) else deco


def tool(
    func: Callable | None = None, *, name: str | None = None, capture_result: bool = True
) -> Callable:
    """Wrap a function as an ``execute_tool`` span; a str return is captured as the tool result."""

    def deco(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with get_default_instrument().tool(name or f.__name__) as span:
                result = f(*args, **kwargs)
                if capture_result and isinstance(result, str):
                    span.set_result(result)
                return result

        return wrapper

    return deco(func) if callable(func) else deco


def chat(model: str, *, provider: str | None = None) -> Callable:
    """Wrap a function as a ``chat`` span for ``model``.

    Return the raw SDK response and token usage is extracted automatically (google-genai,
    OpenAI-compatible, and Anthropic response shapes) — no extra call needed::

        @chat("gemini-2.5-flash")
        def think(prompt):
            return client.models.generate_content(model=MODEL, contents=prompt)

    :func:`record_chat` still works from inside for explicit/streaming cases (and always
    wins over auto-extraction); :func:`record_chat_content` stays the explicit, opt-in way
    to capture prompt/completion text.
    """

    def deco(f: Callable) -> Callable:
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with get_default_instrument().chat(model, provider=provider) as chat_span:
                token = _current_chat.set(chat_span)
                try:
                    result = f(*args, **kwargs)
                finally:
                    _current_chat.reset(token)
                if not chat_span.recorded:
                    usage = _extract_usage(result)
                    if usage is not None:
                        chat_span.record(input_tokens=usage[0], output_tokens=usage[1])
                return result

        return wrapper

    return deco


def record_chat(*, input_tokens: int, output_tokens: int, finish_reason: str = "stop") -> None:
    """Record usage on the chat span opened by the enclosing ``@chat``."""

    span = _current_chat.get()
    if span is not None:
        span.record(
            input_tokens=input_tokens, output_tokens=output_tokens, finish_reason=finish_reason
        )


def record_chat_content(*, prompt: str, completion: str, system: str | None = None) -> None:
    """Capture prompt/completion on the enclosing ``@chat`` span (opt-in via capture_content)."""

    span = _current_chat.get()
    if span is not None:
        span.record_content(prompt=prompt, completion=completion, system=system)
