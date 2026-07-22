"""Pluggable output-quality check, distinct from the injection guardrail.

Where :mod:`amr.guardrail` scans for *security* problems (prompt injection,
jailbreak), this scans an agent's *output* for quality problems (hallucination,
unsupported claims).  It runs at the LLM boundary and, like the guardrail, returns
a **verdict only** — a boolean plus a category enum — never the offending text.

The default scanner is an offline heuristic keyed on explicit markers so the demo is
deterministic; a deployment swaps in an LLM judge or a hosted evaluator via
:func:`set_quality_scanner`.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

HALLUCINATION = "hallucination"
UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class QualityVerdict:
    flagged: bool
    category: str = ""


QualityScanner = Callable[[str], QualityVerdict]

# Deterministic demo markers.  Real evaluators replace this wholesale.
_HALLUCINATION_RE = re.compile(r"\bHALLUCINATE\b|\bfabricated\b", re.IGNORECASE)
_UNSUPPORTED_RE = re.compile(r"\bno source\b|\bunverified\b|\bmade up\b", re.IGNORECASE)


def default_quality_scanner(text: str) -> QualityVerdict:
    if not text:
        return QualityVerdict(False)
    if _HALLUCINATION_RE.search(text):
        return QualityVerdict(True, HALLUCINATION)
    if _UNSUPPORTED_RE.search(text):
        return QualityVerdict(True, UNSUPPORTED)
    return QualityVerdict(False)


_scanner: QualityScanner = default_quality_scanner


def set_quality_scanner(scanner: QualityScanner) -> None:
    global _scanner
    _scanner = scanner


def get_quality_scanner() -> QualityScanner:
    return _scanner


def scan_output(text: str) -> QualityVerdict:
    return _scanner(text)
