from collections.abc import Sequence

from stockvisualizer.calculations.cagr import (
    calculate_max_available_cagr,
    calculate_positive_cagr,
)


def calculate_revenue_cagr(
    revenues: Sequence[float | None],
    years: int | None = None,
    fiscal_years: Sequence[int] | None = None,
) -> float | None:
    """Calculate trailing revenue CAGR over a specified number of annual periods."""
    return calculate_positive_cagr(revenues, years, fiscal_years)


def calculate_revenue_cagr_10y(
    revenues: Sequence[float | None], fiscal_years: Sequence[int] | None = None
) -> float | None:
    """Calculate revenue CAGR using the longest history, capped at nine years."""
    return calculate_revenue_cagr_max_available(revenues, fiscal_years)[0]


def calculate_revenue_cagr_max_available(
    revenues: Sequence[float | None],
    fiscal_years: Sequence[int] | None = None,
) -> tuple[float | None, int | None]:
    """Use the longest valid consecutive revenue history, capped at nine years."""
    return calculate_max_available_cagr(revenues, fiscal_years)


def calculate_revenue_cagr_4y(
    revenues: Sequence[float | None], fiscal_years: Sequence[int] | None = None
) -> float | None:
    """Calculate four-year revenue CAGR; requires five valid annual values."""
    return calculate_revenue_cagr(revenues, years=4, fiscal_years=fiscal_years)
