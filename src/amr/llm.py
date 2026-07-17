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
    return LLMResult(text, _estimate_tokens(prompt), _estimate_tokens(text), model, "stop")


def _real_complete(prompt: str, model: str) -> LLMResult:
    """Call an OpenAI-compatible chat-completions endpoint when explicitly enabled."""

    endpoint = os.environ.get("AMR_LLM_ENDPOINT")
    if not endpoint:
        raise RuntimeError("AMR_LLM_ENDPOINT is required when AMR_LLM=real")
    headers = {"content-type": "application/json"}
    api_key = os.environ.get("AMR_LLM_API_KEY")
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


def complete(prompt: str, model: str) -> LLMResult:
    """Complete a prompt. ``AMR_LLM=fake`` is deterministic and the default."""

    if os.environ.get("AMR_LLM", "fake").lower() == "real":
        return _real_complete(prompt, model)
    return _fake_complete(prompt, model)
