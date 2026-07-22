"""Pluggable prompt-injection / jailbreak scanner.

The scanner runs at the only place raw text exists (the LLM boundary in
``agents/common.py``) and returns a **verdict only** — a boolean plus a category
enum.  It never returns, logs, or stores the offending text, preserving the
project's no-content-capture rule.

The default scanner is an offline heuristic (a phrase list); it makes no network
calls and needs no secrets.  A deployment can swap in a stronger scanner (e.g. an
LLM judge or a hosted guardrail) via :func:`set_scanner` without touching agents.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

# Categories are a closed enum so downstream attributes/signals stay bounded.
PROMPT_INJECTION = "prompt_injection"
JAILBREAK = "jailbreak"

# Direction of the scanned text relative to the model.
INPUT = "input"
OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class Verdict:
    """A content-free scan result.  ``category`` is empty when not flagged."""

    flagged: bool
    category: str = ""


Scanner = Callable[[str, str], Verdict]

# Deliberately conservative, human-auditable patterns.  This is a demo heuristic,
# not a production guardrail; the real value is that it is swappable.
_JAILBREAK_PATTERNS = (
    r"ignore (?:all )?(?:previous|prior|above) instructions",
    r"disregard (?:the )?(?:system|previous) prompt",
    r"you are now (?:in )?(?:dan|developer mode|jailbreak)",
    r"pretend you have no (?:rules|restrictions|guidelines)",
    r"bypass (?:your )?(?:safety|guardrails|filters)",
)
_INJECTION_PATTERNS = (
    r"</?(?:system|instructions?)>",
    r"new instructions?:",
    r"\bexfiltrate\b|\bleak\b.*(?:secret|api[_ ]?key|password)",
    r"reveal (?:your )?(?:system prompt|instructions)",
)

_JAILBREAK_RE = re.compile("|".join(_JAILBREAK_PATTERNS), re.IGNORECASE)
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def default_scanner(text: str, direction: str) -> Verdict:
    """Heuristic scan.  ``direction`` is :data:`INPUT` or :data:`OUTPUT`."""

    if not text:
        return Verdict(False)
    if _JAILBREAK_RE.search(text):
        return Verdict(True, JAILBREAK)
    if _INJECTION_RE.search(text):
        return Verdict(True, PROMPT_INJECTION)
    return Verdict(False)


_scanner: Scanner = default_scanner


def set_scanner(scanner: Scanner) -> None:
    """Install a custom scanner for this process (opt-in, e.g. an LLM judge)."""

    global _scanner
    _scanner = scanner


def get_scanner() -> Scanner:
    return _scanner


def scan(text: str, direction: str) -> Verdict:
    """Scan ``text`` with the active scanner; returns a content-free verdict."""

    return _scanner(text, direction)
