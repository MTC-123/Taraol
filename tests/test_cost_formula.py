from amr.cost import cost_of


def test_cost_of_priced_model_uses_per_1k_rates_and_rounds_to_four_places() -> None:
    # gpt-4.1-mini: $0.0004 input + $0.0016 output per 1K tokens.
    assert cost_of("gpt-4.1-mini", 1250, 250) == (0.0009, False)


def test_cost_of_unknown_model_is_explicitly_unpriced() -> None:
    assert cost_of("not-in-pricing-yaml", 1000, 1000) == (0.0, True)
