"""Pluggable prompt-injection / jailbreak scanner (verdict only, no content)."""

import re
from collections.abc import Callable
from dataclasses import dataclass

PROMPT_INJECTION = "prompt_injection"
JAILBREAK = "jailbreak"
INPUT = "input"
OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class Verdict:
    flagged: bool
    category: str = ""


Scanner = Callable[[str, str], Verdict]

_JAILBREAK_RE = re.compile(
    "|".join(
        (
            r"ignore (?:all )?(?:previous|prior|above) instructions",
            r"disregard (?:the )?(?:system|previous) prompt",
            r"you are now (?:in )?(?:dan|developer mode|jailbreak)",
            r"pretend you have no (?:rules|restrictions|guidelines)",
            r"bypass (?:your )?(?:safety|guardrails|filters)",
        )
    ),
    re.IGNORECASE,
)
_INJECTION_RE = re.compile(
    "|".join(
        (
            r"</?(?:system|instructions?)>",
            r"new instructions?:",
            r"\bexfiltrate\b|\bleak\b.*(?:secret|api[_ ]?key|password)",
            r"reveal (?:your )?(?:system prompt|instructions)",
        )
    ),
    re.IGNORECASE,
)


def default_scanner(text: str, direction: str) -> Verdict:
    if not text:
        return Verdict(False)
    if _JAILBREAK_RE.search(text):
        return Verdict(True, JAILBREAK)
    if _INJECTION_RE.search(text):
        return Verdict(True, PROMPT_INJECTION)
    return Verdict(False)


_scanner: Scanner = default_scanner


def set_scanner(scanner: Scanner) -> None:
    global _scanner
    _scanner = scanner


def get_scanner() -> Scanner:
    return _scanner


def scan(text: str, direction: str) -> Verdict:
    return _scanner(text, direction)
