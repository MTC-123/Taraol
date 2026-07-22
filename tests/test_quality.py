from dataclasses import fields

from amr.quality import (
    HALLUCINATION,
    QualityVerdict,
    default_quality_scanner,
    scan_output,
    set_quality_scanner,
)


def test_flags_hallucination_marker() -> None:
    verdict = default_quality_scanner("The revenue figure was HALLUCINATE for Q3.")
    assert verdict.flagged
    assert verdict.category == HALLUCINATION


def test_benign_output_passes() -> None:
    assert default_quality_scanner("Revenue grew 4% quarter over quarter.").flagged is False


def test_verdict_carries_no_content() -> None:
    assert {f.name for f in fields(QualityVerdict)} == {"flagged", "category"}


def test_scanner_is_swappable() -> None:
    original = default_quality_scanner
    try:
        set_quality_scanner(lambda text: QualityVerdict(True, "custom"))
        assert scan_output("anything") == QualityVerdict(True, "custom")
    finally:
        set_quality_scanner(original)
