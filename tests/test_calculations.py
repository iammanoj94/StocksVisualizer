import math

import pytest

from stockvisualizer.calculations.cumulative_eps_payback import (
    calculate_cumulative_eps_payback,
    calculate_eps_payback_analysis,
)
from stockvisualizer.calculations.expected_growth import calculate_expected_growth
from stockvisualizer.calculations.net_profit_cagr import (
    calculate_net_profit_cagr,
    calculate_net_profit_cagr_max_available,
    calculate_net_profit_cagr_10y,
    calculate_net_profit_cagr_4y,
)
from stockvisualizer.calculations.normalized_core_pe import (
    calculate_normalized_core_pe,
)
from stockvisualizer.calculations.payback_sensitivity import (
    SENSITIVITY_GROWTH_RATES,
    calculate_payback_sensitivity,
)
from stockvisualizer.calculations.reported_pe import calculate_reported_pe
from stockvisualizer.calculations.revenue_cagr import (
    calculate_revenue_cagr,
    calculate_revenue_cagr_max_available,
    calculate_revenue_cagr_10y,
    calculate_revenue_cagr_4y,
)
from stockvisualizer.calculations.stock_rating import calculate_stock_rating


def test_revenue_cagr_requires_observations_for_the_periods():
    assert calculate_revenue_cagr([100, 110, 121], years=2) == pytest.approx(0.10)
    assert calculate_revenue_cagr([100, 121], years=2) is None


def test_four_year_cagr_uses_trailing_five_annual_values():
    values = [10, 20, 40, 80, 160, 320]
    years = [2019, 2020, 2021, 2022, 2023, 2024]
    assert calculate_revenue_cagr_4y(values, years) == pytest.approx(1.0)
    assert calculate_net_profit_cagr_4y(values, years) == pytest.approx(1.0)
    assert calculate_net_profit_cagr_4y(values[:4]) is None


def test_max_available_cagr_uses_up_to_nine_years():
    values = [100 * (1.1**year) for year in range(11)]
    years = list(range(2014, 2025))
    assert calculate_revenue_cagr_10y(values, years) == pytest.approx(0.10)
    assert calculate_net_profit_cagr_10y(values, years) == pytest.approx(0.10)
    assert calculate_revenue_cagr_10y(values[:-1], years[:-1]) == pytest.approx(0.10)
    assert calculate_net_profit_cagr_10y(values[:-2], years[:-2]) == pytest.approx(0.10)
    assert calculate_revenue_cagr_10y(values[:5], years[:5]) == pytest.approx(0.10)
    assert calculate_revenue_cagr_10y(values[:3], years[:3]) == pytest.approx(0.10)
    assert calculate_revenue_cagr_10y(values[:2], years[:2]) is None


def test_dynamic_cagr_reports_actual_period_and_caps_at_nine_years():
    values = [100 * (1.1**year) for year in range(15)]
    assert calculate_revenue_cagr_max_available(values) == pytest.approx((0.1, 9))
    assert calculate_net_profit_cagr_max_available(values[:10]) == pytest.approx(
        (0.1, 9)
    )
    assert calculate_revenue_cagr_max_available(values[:9]) == pytest.approx(
        (0.1, 8)
    )
    assert calculate_revenue_cagr_max_available(values[:5]) == pytest.approx(
        (0.1, 4)
    )
    assert calculate_revenue_cagr_max_available(values[:3]) == pytest.approx(
        (0.1, 2)
    )
    assert calculate_revenue_cagr_max_available(values[:2]) == (None, None)


@pytest.mark.parametrize(
    "values",
    (
        [0, 100],
        [-10, 100],
        [100, 0],
        [100, -1],
        [100, math.nan],
        [100, math.inf],
        [100, None],
    ),
)
def test_cagr_rejects_zero_negative_and_invalid_observations(values):
    assert calculate_revenue_cagr(values) is None
    assert calculate_net_profit_cagr(values) is None


def test_cagr_rejects_missing_or_nonconsecutive_years():
    assert calculate_revenue_cagr_4y(
        [100, 110, 120, 130, 140], [2020, 2021, 2022, 2024, 2025]
    ) is None


def test_dynamic_cagr_uses_only_latest_consecutive_suffix():
    values = [100, 110, 121, 133.1]
    fiscal_years = [2018, 2020, 2021, 2022]

    cagr, periods = calculate_revenue_cagr_max_available(values, fiscal_years)

    assert periods == 2
    assert cagr == pytest.approx(0.10)
    assert calculate_revenue_cagr_max_available(
        [100, 121, 133.1], [2018, 2020, 2021]
    ) == (None, None)


def test_expected_growth_averages_available_valid_cagrs():
    assert calculate_expected_growth(0.10, 0.20, 0.30, 0.40) == pytest.approx(0.25)
    assert calculate_expected_growth(0.10, 0.20, 0.30, None) == pytest.approx(0.20)
    assert calculate_expected_growth(0.10, None, 0.30, math.nan) == pytest.approx(0.20)
    assert calculate_expected_growth(None, math.inf, math.nan, None) is None


def test_eps_payback_schedule_and_fractional_interpolation():
    result = calculate_eps_payback_analysis(100, 10, 0.10)
    assert result is not None
    assert [
        (row.year, row.annual_eps, row.cumulative_eps)
        for row in result.schedule[:3]
    ] == [
        (1, 10, 10),
        (2, 11, 21),
        (3, pytest.approx(12.1), pytest.approx(33.1)),
    ]
    assert result.first_full_year == 8
    assert result.estimated_payback_years == pytest.approx(7.263162)
    assert calculate_cumulative_eps_payback(25, 10, 0, max_years=5) == pytest.approx(
        2.5
    )


def test_eps_payback_reports_unreached_horizon():
    result = calculate_eps_payback_analysis(1000, 1, 0, max_years=3)
    assert result is not None
    assert len(result.schedule) == 3
    assert result.first_full_year is None
    assert result.estimated_payback_years is None


@pytest.mark.parametrize(
    "price,eps,growth",
    (
        (100, 0, 0.1),
        (100, -10, 0.1),
        (0, 10, 0.1),
        (100, 10, -1),
        (100, math.nan, 0.1),
        (100, 10, math.inf),
    ),
)
def test_eps_payback_rejects_zero_negative_and_invalid_inputs(price, eps, growth):
    assert calculate_eps_payback_analysis(price, eps, growth) is None


def test_payback_sensitivity_uses_requested_growth_rates():
    sensitivity = calculate_payback_sensitivity(100, 10)
    assert tuple(sensitivity) == SENSITIVITY_GROWTH_RATES
    assert all(result is not None for result in sensitivity.values())
    assert (
        sensitivity[0.15].estimated_payback_years
        < sensitivity[0.08].estimated_payback_years
    )


def test_reported_and_normalized_pe_are_distinct_and_guard_losses():
    assert calculate_reported_pe(120, 10) == pytest.approx(12)
    assert calculate_reported_pe(120, 0) is None
    assert calculate_reported_pe(120, -10) is None
    assert calculate_reported_pe(120, math.inf) is None
    assert calculate_normalized_core_pe(120, [10, 20, 30]) == pytest.approx(6)
    assert calculate_normalized_core_pe(120, [10, -20, 30]) is None
    assert calculate_normalized_core_pe(120, []) is None
    assert calculate_normalized_core_pe(120, [10, math.nan]) is None


def test_stock_rating_uses_transparent_thresholds():
    assert calculate_stock_rating(18, 0.16, 7) == "Attractive"
    assert calculate_stock_rating(40, 0.02, None) == "Cautious"
    assert calculate_stock_rating(None, None, None) == "Insufficient data"
