from collections.abc import Sequence

from stockvisualizer.calculations.cagr import (
    calculate_max_available_cagr,
    calculate_positive_cagr,
)


def calculate_net_profit_cagr(
    profits: Sequence[float | None],
    years: int | None = None,
    fiscal_years: Sequence[int] | None = None,
) -> float | None:
    """Calculate trailing net-profit CAGR over annual periods with positive data."""
    return calculate_positive_cagr(profits, years, fiscal_years)


def calculate_net_profit_cagr_10y(
    profits: Sequence[float | None], fiscal_years: Sequence[int] | None = None
) -> float | None:
    """Calculate net-profit CAGR using the longest history, capped at nine years."""
    return calculate_net_profit_cagr_max_available(profits, fiscal_years)[0]


def calculate_net_profit_cagr_max_available(
    profits: Sequence[float | None],
    fiscal_years: Sequence[int] | None = None,
) -> tuple[float | None, int | None]:
    """Use the longest valid consecutive net-profit history, capped at nine years."""
    return calculate_max_available_cagr(profits, fiscal_years)


def calculate_net_profit_cagr_4y(
    profits: Sequence[float | None], fiscal_years: Sequence[int] | None = None
) -> float | None:
    """Calculate four-year net-profit CAGR; requires five valid annual values."""
    return calculate_net_profit_cagr(profits, years=4, fiscal_years=fiscal_years)
