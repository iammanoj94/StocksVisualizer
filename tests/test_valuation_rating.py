import pytest

from stockvisualizer.calculations.valuation_rating import calculate_valuation_rating
from stockvisualizer.watchlist_metrics import build_watchlist_metrics


@pytest.mark.parametrize(
    ("valuation_ratio", "expected_rating"),
    [
        (0.70, "Strong Buy (Deep Value)"),
        (0.70001, "Good Buy (Undervalued)"),
        (0.90, "Good Buy (Undervalued)"),
        (0.90001, "Fair Value (Hold / Neutral)"),
        (1.10, "Fair Value (Hold / Neutral)"),
        (1.10001, "Slightly Overvalued"),
        (1.30, "Slightly Overvalued"),
        (1.30001, "Overvalued (Avoid / Sell)"),
    ],
)
def test_valuation_rating_obeys_scorecard_boundaries(
    valuation_ratio, expected_rating
):
    growth = 0.20
    fair_pe = 0.096 * 20**2
    actual_pe = fair_pe * valuation_ratio

    assert calculate_valuation_rating(actual_pe, growth) == expected_rating


@pytest.mark.parametrize(
    ("pe", "growth"),
    [
        (None, 0.2),
        (float("nan"), 0.2),
        (float("inf"), 0.2),
        (0, 0.2),
        (-1, 0.2),
        (20, None),
        (20, 0),
        (20, -0.1),
        (20, float("nan")),
        (20, float("inf")),
    ],
)
def test_valuation_rating_is_unavailable_for_invalid_inputs(pe, growth):
    assert calculate_valuation_rating(pe, growth) == "Unavailable"


def test_watchlist_rating_uses_reported_pe_and_expected_growth():
    observations = [
        {
            "statement": "annual",
            "period": "2025-03-31",
            "metric": "eps_reported",
            "value": 10,
        }
    ]

    metrics = build_watchlist_metrics(
        observations,
        100,
        "Example Ltd",
        {},
        expected_growth_override=0.20,
    )

    assert metrics["calculated_pe"] == pytest.approx(10)
    assert metrics["rating"] == "Strong Buy (Deep Value)"


def test_watchlist_rating_uses_yahoo_pe_when_cached():
    metrics = build_watchlist_metrics(
        [],
        100,
        "Example Ltd",
        {},
        expected_growth_override=0.20,
        live_market_data={
            "pe": 38.4,
            "eps_inr": 10,
            "market_cap_inr": 100_000_000,
        },
    )

    assert metrics["calculated_pe"] == 38.4
    assert metrics["rating"] == "Fair Value (Hold / Neutral)"
