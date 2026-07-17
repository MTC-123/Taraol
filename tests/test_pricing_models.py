from pathlib import Path

import yaml

from amr.llm import complete


def test_fake_llm_emits_positive_priced_model_usage() -> None:
    result = complete("a deterministic test prompt", "example-small")
    pricing = yaml.safe_load(Path("config/pricing.yaml").read_text(encoding="utf-8"))
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    assert result.model in pricing["models"]
