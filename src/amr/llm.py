"""Small LLM boundary with deterministic offline behaviour by default."""

import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    finish_reason: str


def _estimate_tokens(text: str) -> int:
    """A stable, deliberately simple approximation of tokenisation."""

    return max(1, (len(text.strip()) + 3) // 4)


def _fake_complete(prompt: str, model: str) -> LLMResult:
    text = f"[{model}] completed: {prompt.strip()[:80]}"
    # The offline demo needs enough usage to make four-decimal USD rollups
    # legible.  Real-provider mode always uses provider-reported counts.
    return LLMResult(
        text,
        max(1000, _estimate_tokens(prompt)),
        max(500, _estimate_tokens(text)),
        model,
        "stop",
    )


# Gemini ships an OpenAI-compatible surface, so one client covers both providers.
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def _openai_compatible_complete(prompt: str, model: str, endpoint: str, api_key: str) -> LLMResult:
    """Call any OpenAI-compatible chat-completions endpoint and read reported usage."""

    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    response = httpx.post(
        endpoint,
        headers=headers,
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    choice = payload["choices"][0]
    usage = payload.get("usage", {})
    text = choice.get("message", {}).get("content", "")
    return LLMResult(
        text=text,
        input_tokens=int(usage.get("prompt_tokens", _estimate_tokens(prompt))),
        output_tokens=int(usage.get("completion_tokens", _estimate_tokens(text))),
        model=str(payload.get("model", model)),
        finish_reason=str(choice.get("finish_reason", "stop")),
    )


def _real_complete(prompt: str, model: str) -> LLMResult:
    """Call a configured OpenAI-compatible endpoint (``AMR_LLM=real``)."""

    endpoint = os.environ.get("AMR_LLM_ENDPOINT")
    if not endpoint:
        raise RuntimeError("AMR_LLM_ENDPOINT is required when AMR_LLM=real")
    return _openai_compatible_complete(
        prompt, model, endpoint, os.environ.get("AMR_LLM_API_KEY", "")
    )


def _gemini_complete(prompt: str, model: str) -> LLMResult:
    """Call Gemini via its OpenAI-compatible endpoint (``AMR_LLM=gemini``)."""

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("AMR_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required when AMR_LLM=gemini")
    endpoint = os.environ.get("AMR_LLM_ENDPOINT", _GEMINI_ENDPOINT)
    return _openai_compatible_complete(prompt, model, endpoint, api_key)


def complete(prompt: str, model: str) -> LLMResult:
    """Complete a prompt. ``AMR_LLM`` selects the provider; ``fake`` is the default."""

    provider = os.environ.get("AMR_LLM", "fake").lower()
    if provider == "real":
        return _real_complete(prompt, model)
    if provider == "gemini":
        return _gemini_complete(prompt, model)
    return _fake_complete(prompt, model)
